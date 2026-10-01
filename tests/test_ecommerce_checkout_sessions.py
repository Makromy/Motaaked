from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, IncomingCredit, PendingOrder, CheckoutSession
from app.services import utc_now
from app.config import settings


@pytest.fixture
def test_merchant(db_session: Session) -> User:
    """Creates an active merchant with 10 credits and valid subscription."""
    merchant = User(
        name="Test LMS Merchant",
        email="lms@merchant.com",
        phone="01011112222",
        passcode="LMS-TEST-PASSCODE",
        role="user",
        subscription_expires_at=utc_now() + timedelta(days=90),
        credits_balance=10,
        free_credits=10,
        ecommerce_enabled=True,
        is_active=True,
    )
    db_session.add(merchant)
    db_session.commit()
    db_session.refresh(merchant)
    return merchant


def test_create_checkout_session_success(client: TestClient, test_merchant: User):
    """Verify that a merchant can initiate a 15-minute checkout session."""
    payload = {
        "order_id": "ORD-COURSE-101",
        "amount": 250.0,
        "currency": "EGP",
        "description": "Python Web Development Masterclass",
        "return_url": "https://lms.example.com/courses/python/success",
    }
    resp = client.post(
        "/v1/checkout/session",
        json=payload,
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["order_id"] == "ORD-COURSE-101"
    assert data["amount"] == 250.0
    assert data["session_token"].startswith("cs_")
    assert "/checkout/embed?session=" in data["checkout_url"]
    assert data["merchant_name"] == "Test LMS Merchant"


def test_get_checkout_session_public(client: TestClient, test_merchant: User):
    """Verify public endpoint for drop-in iframe returns safe session data."""
    # Create session
    create_resp = client.post(
        "/v1/checkout/session",
        json={"order_id": "ORD-PUB-202", "amount": 150.0, "description": "Laravel Bootcamp"},
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert create_resp.status_code == 201
    token = create_resp.json()["session_token"]

    # Public read without auth
    resp = client.get(f"/v1/checkout/session/{token}")
    assert resp.status_code == 200
    pub_data = resp.json()
    assert pub_data["session_token"] == token
    assert pub_data["order_id"] == "ORD-PUB-202"
    assert pub_data["amount"] == 150.0
    assert pub_data["status"] == "PENDING"
    assert pub_data["seconds_remaining"] > 800

    # Non-existent session
    resp_404 = client.get("/v1/checkout/session/cs_non_existent_token_12345")
    assert resp_404.status_code == 404


def test_verify_checkout_session_and_deduct_credit(
    client: TestClient, db_session: Session, test_merchant: User
):
    """
    Verify payment match via reference ID:
    - Session status becomes MATCHED
    - Bank SMS credit claimed
    - Exactly 1 credit deducted from merchant wallet
    """
    # 1. Create incoming credit from bank SMS
    bank_ref = "240923009988"
    credit = IncomingCredit(
        user_id=test_merchant.id,
        amount=500.0,
        reference_id=bank_ref,
        sender_name="Ahmed Ali",
        status="UNCLAIMED",
        is_matched=False,
        received_at=utc_now(),
        raw_message=f"تم استلام 500.00 ج.م مرجع {bank_ref}",
    )
    db_session.add(credit)
    db_session.commit()

    # 2. Merchant creates checkout session
    create_resp = client.post(
        "/v1/checkout/session",
        json={"order_id": "ORD-PREMIUM-303", "amount": 500.0, "description": "Complete Diploma"},
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert create_resp.status_code == 201
    token = create_resp.json()["session_token"]
    assert test_merchant.credits_balance == 10

    # 3. Customer submits Reference ID via Drop-In Modal
    verify_resp = client.post(
        "/v1/checkout/verify",
        json={"session_token": token, "reference_id": bank_ref},
    )
    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()
    assert verify_data["verified"] is True
    assert verify_data["status"] == "MATCHED"
    assert verify_data["order_id"] == "ORD-PREMIUM-303"
    assert verify_data["reference_id"] == bank_ref

    # 4. Verify 1 credit deducted
    db_session.refresh(test_merchant)
    assert test_merchant.credits_balance == 9

    # 5. Idempotent check: calling again returns success without deducting duplicate credit
    verify_resp_2 = client.post(
        "/v1/checkout/verify",
        json={"session_token": token, "reference_id": bank_ref},
    )
    assert verify_resp_2.status_code == 200
    assert verify_resp_2.json()["verified"] is True
    db_session.refresh(test_merchant)
    assert test_merchant.credits_balance == 9


def test_checkout_session_expiry(client: TestClient, db_session: Session, test_merchant: User):
    """Expired checkout sessions cannot be verified."""
    expired_session = CheckoutSession(
        session_token="cs_expired_test_token_12345",
        merchant_id=test_merchant.id,
        order_id="ORD-EXP-404",
        amount=100.0,
        currency="EGP",
        status="PENDING",
        created_at=utc_now() - timedelta(minutes=30),
        expires_at=utc_now() - timedelta(minutes=15),
    )
    db_session.add(expired_session)
    db_session.commit()

    # Public fetch marks expired
    pub_resp = client.get("/v1/checkout/session/cs_expired_test_token_12345")
    assert pub_resp.status_code == 200
    assert pub_resp.json()["status"] == "EXPIRED"

    # Verify attempt fails
    verify_resp = client.post(
        "/v1/checkout/verify",
        json={"session_token": "cs_expired_test_token_12345", "reference_id": "REF999"},
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["verified"] is False
    assert "expired" in verify_resp.json()["message"].lower()


def test_global_portal_toggle_enforcement(
    client: TestClient, test_merchant: User, auth_headers: dict
):
    """When Super Admin disables E-Commerce globally, all external sessions/verifications pause (503)."""
    # 1. Disable globally
    resp = client.post(
        "/v1/admin/settings",
        json={"admin_key": settings.MASTER_API_KEY, "ecommerce_gateway_enabled": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # 2. Checkout session creation blocked
    block_resp = client.post(
        "/v1/checkout/session",
        json={"order_id": "ORD-BLOCKED-1", "amount": 100.0},
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert block_resp.status_code == 503
    assert "disabled" in block_resp.json()["detail"].lower()

    # 3. Direct order verification also blocked
    order_resp = client.post(
        "/v1/orders/verify",
        json={"order_id": "ORD-BLOCKED-1", "amount": 100.0, "reference_id": "REF123"},
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert order_resp.status_code == 503

    # 4. Re-enable globally
    re_enable = client.post(
        "/v1/admin/settings",
        json={"admin_key": settings.MASTER_API_KEY, "ecommerce_gateway_enabled": True},
        headers=auth_headers,
    )
    assert re_enable.status_code == 200

    # 5. Restored
    success_resp = client.post(
        "/v1/checkout/session",
        json={"order_id": "ORD-RESTORED-1", "amount": 100.0},
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert success_resp.status_code == 201


def test_merchant_toggle_enforcement(
    client: TestClient, db_session: Session, test_merchant: User, auth_headers: dict
):
    """Super Admin can toggle e-commerce per merchant. Disabled merchants get 403."""
    # 1. Super Admin toggles merchant OFF
    toggle_off = client.post(
        f"/v1/admin/users/{test_merchant.id}/toggle-ecommerce",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert toggle_off.status_code == 200
    assert toggle_off.json()["ecommerce_enabled"] is False

    # 2. Merchant gets 403 Forbidden
    block_resp = client.post(
        "/v1/checkout/session",
        json={"order_id": "ORD-MERCH-BLOCK", "amount": 100.0},
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert block_resp.status_code == 403
    assert "disabled for this merchant" in block_resp.json()["detail"]

    # 3. Super Admin toggles merchant ON
    toggle_on = client.post(
        f"/v1/admin/users/{test_merchant.id}/toggle-ecommerce",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert toggle_on.status_code == 200
    assert toggle_on.json()["ecommerce_enabled"] is True

    # 4. Merchant can checkout again
    ok_resp = client.post(
        "/v1/checkout/session",
        json={"order_id": "ORD-MERCH-OK", "amount": 100.0},
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert ok_resp.status_code == 201


def test_credit_exhaustion_gate(client: TestClient, db_session: Session, test_merchant: User):
    """When merchant wallet is at 0 credits, e-commerce checkout session creation returns 402."""
    test_merchant.credits_balance = 0
    test_merchant.free_credits = 0
    db_session.commit()

    resp = client.post(
        "/v1/checkout/session",
        json={"order_id": "ORD-NOCREDIT-1", "amount": 100.0},
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert resp.status_code == 402
    assert "insufficient merchant credits" in resp.json()["detail"].lower()


def test_security_headers_and_embed_page(client: TestClient):
    """
    Verify security headers:
    - /checkout/embed allows framing (frame-ancestors * and no X-Frame-Options: SAMEORIGIN)
    - / (portal root) strictly blocks framing (X-Frame-Options: SAMEORIGIN)
    - /js/motaaked-checkout.js is accessible
    """
    # 1. Embed page header check
    embed_resp = client.get("/checkout/embed?session=cs_dummy")
    assert embed_resp.status_code == 200
    assert "X-Frame-Options" not in embed_resp.headers
    assert "frame-ancestors *;" in embed_resp.headers["Content-Security-Policy"]

    # 2. General page clickjacking protection check
    root_resp = client.get("/")
    assert root_resp.status_code == 200
    assert root_resp.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self';" in root_resp.headers["Content-Security-Policy"]

    # 3. Client widget JS check
    js_resp = client.get("/js/motaaked-checkout.js")
    assert js_resp.status_code == 200
    assert "MotaakedCheckout" in js_resp.text


def test_merchant_store_orders_endpoint(client: TestClient, test_merchant: User):
    """Verify that merchant can fetch store orders and sessions."""
    # Create 2 sessions
    client.post(
        "/v1/checkout/session",
        json={"order_id": "ORD-STORE-A", "amount": 120.0},
        headers={"X-Passcode": test_merchant.passcode},
    )
    client.post(
        "/v1/checkout/session",
        json={"order_id": "ORD-STORE-B", "amount": 340.0},
        headers={"X-Passcode": test_merchant.passcode},
    )

    resp = client.get(
        "/v1/merchant/store-orders",
        headers={"X-Passcode": test_merchant.passcode},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["merchant_id"] == test_merchant.id
    assert data["total_sessions"] >= 2
    assert len(data["recent_sessions"]) >= 2
    assert any(s["order_id"] == "ORD-STORE-A" for s in data["recent_sessions"])
    assert any(s["order_id"] == "ORD-STORE-B" for s in data["recent_sessions"])
