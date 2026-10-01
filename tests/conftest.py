import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.config import settings

# In-memory SQLite with StaticPool for test isolation
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
    future=True,
)


@pytest.fixture(scope="function", autouse=True)
def setup_test_database():
    """Create fresh database tables before each test and drop them after."""
    from app.database import seed_default_packages, seed_default_bank_patterns
    from app.services import seed_default_faqs
    Base.metadata.create_all(bind=test_engine)
    with TestingSessionLocal() as session:
        seed_default_packages(session)
        seed_default_bank_patterns(session)
        seed_default_faqs(session)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def db_session(setup_test_database):
    """Provides a database session for testing."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client(setup_test_database):
    """Test client with overridden database dependency."""
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    """Standard authenticated headers."""
    return {"X-API-Key": settings.MASTER_API_KEY}
