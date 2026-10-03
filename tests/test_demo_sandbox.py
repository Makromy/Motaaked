import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.database import Base, engine, get_db, SessionLocal
from app.models import User, IncomingCredit, ApiKey


@pytest.fixture(scope="function")
def db_session():
    """Provides a clean database session for test verification."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client():
    """FastAPI TestClient instance."""
    with TestClient(app) as test_client:
        yield test_client


def test_demo_login_synthetic_profile(client, db_session):
    """Verifies one-click demo login returns a fully populated synthetic profile without touching the database."""
    user_count_before = db_session.query(User).count()

    response = client.post(
        "/v1/auth/passcode/login",
        json={"passcode": "DEMO-SANDBOX-2026"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == 999999
    assert data["name"] == "Demo Merchant (Sandbox)"
    assert data["role"] == "demo"
    assert data["credits_balance"] == 250
    assert data["free_credits"] == 100
    assert data["pass_credits"] == 150
    assert data["is_subscription_valid"] is True
    assert data["account_ending"] == "4812"

    # Strict Zero-DB Air-gap assertion
    user_count_after = db_session.query(User).count()
    assert user_count_after == user_count_before, "Demo login must not write any user records to SQLite."


def test_demo_user_profile_endpoint(client):
    """Verifies GET /v1/user/profile accepts demo passcode and returns synthetic profile."""
    response = client.get(
        "/v1/user/profile",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "demo"
    assert data["credits_balance"] == 250


def test_demo_search_egyptian_banks(client, db_session):
    """
    Verifies searching synthetic Egyptian bank transactions (CIB, NBE, HSBC, QNB, AlexBank, AAIB).
    Strictly excludes mobile wallets and Banque Misr.
    """
    credit_count_before = db_session.query(IncomingCredit).count()

    # 1. Search CIB transaction
    res_cib = client.post(
        "/v1/transactions/search",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={"reference_id": "24100200101"}
    )
    assert res_cib.status_code == 200
    cib_data = res_cib.json()
    assert cib_data["found"] is True
    assert cib_data["credit"]["amount"] == 450.0
    assert cib_data["credit"]["currency"] == "EGP"
    assert cib_data["credit"]["reference_id"] == "24100200101"
    assert cib_data["credits_remaining"] == 250

    # 2. Search NBE transaction
    res_nbe = client.post(
        "/v1/transactions/search",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={"reference_id": "24100200102"}
    )
    assert res_nbe.status_code == 200
    nbe_data = res_nbe.json()
    assert nbe_data["found"] is True
    assert nbe_data["credit"]["amount"] == 1250.0

    # 3. Search HSBC Egypt transaction
    res_hsbc = client.post(
        "/v1/transactions/search",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={"reference_id": "24100200103"}
    )
    assert res_hsbc.status_code == 200
    hsbc_data = res_hsbc.json()
    assert hsbc_data["found"] is True
    assert hsbc_data["credit"]["amount"] == 320.0

    # 4. Search QNB Alahli transaction (Claimed)
    res_qnb = client.post(
        "/v1/transactions/search",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={"reference_id": "24100200104"}
    )
    assert res_qnb.status_code == 200
    qnb_data = res_qnb.json()
    assert qnb_data["found"] is True
    assert qnb_data["already_matched"] is True

    # 5. Search Non-existent Reference
    res_unknown = client.post(
        "/v1/transactions/search",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={"reference_id": "NON_EXISTENT_REF_999"}
    )
    assert res_unknown.status_code == 200
    assert res_unknown.json()["found"] is False

    # Air-gap: Database credits table remains untouched
    credit_count_after = db_session.query(IncomingCredit).count()
    assert credit_count_after == credit_count_before


def test_demo_transactions_filter_and_statement(client):
    """Verifies filter/history endpoint and statement summary return synthetic data in demo mode."""
    # 1. Filter / History
    res_filter = client.get(
        "/v1/transactions/filter",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"}
    )
    assert res_filter.status_code == 200
    filter_data = res_filter.json()
    assert filter_data["total"] == 6
    assert len(filter_data["items"]) == 6
    assert filter_data["credits_remaining"] == 250

    # 2. Statement Summary
    res_stmt = client.get(
        "/v1/statement/summary",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"}
    )
    assert res_stmt.status_code == 200
    stmt_data = res_stmt.json()
    assert stmt_data["total_count"] == 6
    assert stmt_data["total_volume"] > 0


def test_demo_livestream_feed_and_unlock(client):
    """Verifies LiveStream POS feed and vault unlock endpoints for demo user."""
    # 1. Vault Unlock
    res_unlock = client.post(
        "/v1/transactions/unlock",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={"forwarder_api_key": "123456"}
    )
    assert res_unlock.status_code == 200
    assert res_unlock.json()["success"] is True

    # 2. LiveStream Feed
    res_ls = client.get(
        "/v1/livestream/feed",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"}
    )
    assert res_ls.status_code == 200
    ls_data = res_ls.json()
    assert ls_data["is_unlocked"] is True
    assert len(ls_data["items"]) == 6
    assert ls_data["telemetry"]["battery"] == 94
    assert ls_data["telemetry"]["status"] == "ONLINE"


def test_demo_watchlist_search_and_poll(client):
    """Verifies that searching a synthetic bank reference ID (e.g. CIB) immediately matches on the watchlist."""
    # 1. Watch synthetic CIB reference
    res_watch = client.post(
        "/v1/watchlist/watch",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={
            "reference_id": "24100200101",
            "session_id": "sess_demo_test",
            "timeout_minutes": 30
        }
    )
    assert res_watch.status_code == 201
    watch_data = res_watch.json()
    assert watch_data["status"] == "MATCHED"
    assert watch_data["reference_id"] == "24100200101"
    assert watch_data["matched_credit"]["amount"] == 450.0
    assert watch_data["matched_credit"]["sender_name"] == "Haitham Refaat"
    assert watch_data["matched_credit"]["account_ending"] == "4812"

    # 2. Batch poll synthetic references
    res_poll = client.post(
        "/v1/watchlist/poll",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={
            "reference_ids": ["24100200101", "24100200102", "NON_EXISTENT_REF"],
            "session_id": "sess_demo_test"
        }
    )
    assert res_poll.status_code == 200
    poll_data = res_poll.json()
    assert poll_data["total_matched"] == 2
    assert poll_data["total_pending"] == 1


def test_demo_mutations_strictly_blocked_with_403(client):
    """
    Zero-Trust Security Test:
    Ensures that state-modifying operations (orders, top-ups, cashier-pin updates, PDF statements)
    are strictly rejected with 403 Forbidden when called with Demo credentials.
    """
    # 1. Order creation must fail with 403
    res_order = client.post(
        "/v1/orders/create",
        headers={"X-API-Key": "DEMO-SANDBOX-2026"},
        json={"order_id": "DEMO_ORD_001", "amount": 100.0}
    )
    assert res_order.status_code == 403
    assert "disabled in Demo Sandbox" in res_order.json()["detail"]

    # 2. Order verification must fail with 403
    res_verify = client.post(
        "/v1/orders/verify",
        headers={"X-API-Key": "DEMO-SANDBOX-2026"},
        json={"order_id": "DEMO_ORD_001", "reference_id": "24100200101"}
    )
    assert res_verify.status_code == 403

    # 3. Checkout session creation must fail with 403
    res_sess = client.post(
        "/v1/checkout/session",
        headers={"X-API-Key": "DEMO-SANDBOX-2026"},
        json={"order_id": "DEMO_SESS_001", "amount": 250.0}
    )
    assert res_sess.status_code == 403

    # 4. Top-up initiation must fail with 403
    res_topup = client.post(
        "/v1/topup/initiate",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={"plan_id": "plan_30d", "purchase_type": "direct"}
    )
    assert res_topup.status_code == 403

    # 5. Cashier PIN update must fail with 403
    res_pin = client.post(
        "/v1/user/cashier-pin",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={"owner_key": "DEMO-SANDBOX-2026", "new_cashier_pin": "654321"}
    )
    assert res_pin.status_code == 403

    # 6. PDF Statement export must fail with 403
    res_pdf = client.post(
        "/v1/statement/export/pdf",
        headers={"X-Passcode": "DEMO-SANDBOX-2026"},
        json={"confirm": True}
    )
    assert res_pdf.status_code == 403

    # 7. Admin control panel access must fail with 403
    res_admin = client.get(
        "/v1/admin/metrics",
        headers={"X-API-Key": "DEMO-SANDBOX-2026"}
    )
    assert res_admin.status_code == 403
