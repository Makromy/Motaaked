import pytest
from datetime import timedelta
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.models import User, IncomingCredit, PendingOrder, utc_now
from app.main import get_client_ip, create_shift_token, verify_shift_token, voucher_redeem_limiter


def test_sec001_cross_tenant_watchlist_isolation(client: TestClient, auth_headers, db_session):
    """
    SEC-001 (Critical): An anonymous or cross-tenant caller MUST NOT be able to match
    or observe private merchant transactions via the live watchlist.
    """
    # 1. Create Merchant A with private bank account ending 7788
    res_a = client.post(
        "/v1/admin/passcodes/generate",
        headers=auth_headers,
        json={"user_name": "Merchant Alpha", "custom_code": "PASS-ALPHA-7788", "duration_days": 30, "credits": 50},
    )
    assert res_a.status_code == 201
    user_a = db_session.query(User).filter(User.passcode == "PASS-ALPHA-7788").first()
    user_a.account_ending = "7788"
    db_session.commit()

    # 2. Add an incoming credit for Merchant A's account ending
    now = utc_now()
    credit = IncomingCredit(
        user_id=user_a.id,
        amount=1500.0,
        currency="EGP",
        reference_id="REF_CONFIDENTIAL_ALPHA",
        account_ending="7788",
        status="UNCLAIMED",
        is_matched=False,
        is_read=False,
        raw_message="Transfer of 1500 EGP to account 7788 Ref REF_CONFIDENTIAL_ALPHA",
        received_at=now,
    )
    db_session.add(credit)
    db_session.commit()

    # 3. Anonymous caller attempts to watch this confidential reference
    res_anon_watch = client.post(
        "/v1/watchlist/watch",
        json={"reference_id": "REF_CONFIDENTIAL_ALPHA", "session_id": "attacker_sess_01"},
    )
    assert res_anon_watch.status_code == 201
    data_anon = res_anon_watch.json()
    # MUST NOT MATCH: Must remain PENDING with no matched_credit leaked!
    assert data_anon["status"] == "PENDING"
    assert data_anon["matched_credit"] is None

    # 4. Merchant A himself watches the reference
    headers_a = {"X-Passcode": "PASS-ALPHA-7788"}
    res_a_watch = client.post(
        "/v1/watchlist/watch",
        headers=headers_a,
        json={"reference_id": "REF_CONFIDENTIAL_ALPHA", "session_id": "merchant_a_sess"},
    )
    assert res_a_watch.status_code == 201
    data_a = res_a_watch.json()
    # Merchant A MUST MATCH successfully
    assert data_a["status"] == "MATCHED"
    assert data_a["matched_credit"] is not None
    assert data_a["matched_credit"]["amount"] == 1500.0


def test_sec002_idor_order_verification_prevention(client: TestClient, auth_headers, db_session):
    """
    SEC-002 (Critical): Merchant B cannot verify or match orders belonging to Merchant A.
    """
    # 1. Create Merchant A and Merchant B
    client.post(
        "/v1/admin/passcodes/generate",
        headers=auth_headers,
        json={"user_name": "Merchant One", "custom_code": "PASS-MERCHANT-01", "duration_days": 30, "credits": 50},
    )
    client.post(
        "/v1/admin/passcodes/generate",
        headers=auth_headers,
        json={"user_name": "Merchant Two", "custom_code": "PASS-MERCHANT-02", "duration_days": 30, "credits": 50},
    )
    user_1 = db_session.query(User).filter(User.passcode == "PASS-MERCHANT-01").first()
    user_2 = db_session.query(User).filter(User.passcode == "PASS-MERCHANT-02").first()

    # 2. Create PendingOrder belonging to Merchant 1
    now = utc_now()
    order = PendingOrder(
        order_id="ORD-SEC-002-MERCHANT1",
        user_id=user_1.id,
        amount=250.0,
        reference_id="REF_ORD_SEC002",
        status="PENDING",
        created_at=now,
    )
    db_session.add(order)
    db_session.commit()

    # 3. Merchant 2 attempts to verify Merchant 1's order
    headers_merchant_2 = {"X-Passcode": "PASS-MERCHANT-02"}
    res_verify = client.post(
        "/v1/orders/verify",
        headers=headers_merchant_2,
        json={"order_id": "ORD-SEC-002-MERCHANT1", "amount": 250.0, "reference_id": "REF_ORD_SEC002"},
    )
    assert res_verify.status_code == 200
    data = res_verify.json()
    assert data["verified"] is False
    assert "different merchant" in data["message"] or "Unauthorized" in data["message"]


def test_sec003_idor_topup_credit_hijacking_prevention(client: TestClient, auth_headers, db_session):
    """
    SEC-003 (Critical): User B cannot verify or claim User A's top-up credit purchase.
    """
    # 1. User A initiates top-up order
    res_reg_a = client.post("/v1/auth/register", json={"name": "Buyer Alpha", "email": "buyer_alpha@test.com"})
    res_reg_b = client.post("/v1/auth/register", json={"name": "Attacker Beta", "email": "attacker_beta@test.com"})
    assert res_reg_a.status_code == 201
    assert res_reg_b.status_code == 201

    headers_a = {"X-Passcode": res_reg_a.json()["passcode"]}
    headers_b = {"X-Passcode": res_reg_b.json()["passcode"]}

    res_init = client.post("/v1/topup/initiate", headers=headers_a, json={"plan_id": "plan_livestream"})
    assert res_init.status_code == 200
    order_id = res_init.json()["order_id"]

    # 2. Attacker Beta tries to verify User A's order to credit their own account
    res_hijack = client.post(
        "/v1/topup/verify",
        headers=headers_b,
        json={"order_id": order_id, "reference_id": "REF_TOPUP_HIJACK_ATTEMPT"},
    )
    assert res_hijack.status_code == 200
    data = res_hijack.json()
    assert data["success"] is False
    assert "Multi-Tenant Isolation" in data["message"] or "Unauthorized" in data["message"]


def test_sec005_livestream_shift_gate_and_token(client: TestClient, auth_headers, db_session):
    """
    SEC-005 (High): LiveStream POS feed requires valid X-Shift-Token for non-admin merchants.
    """
    # 1. Create merchant and grant livestream
    client.post(
        "/v1/admin/passcodes/generate",
        headers=auth_headers,
        json={"user_name": "Terminal Merchant", "custom_code": "PASS-TERMINAL-01", "duration_days": 30, "credits": 50},
    )
    user = db_session.query(User).filter(User.passcode == "PASS-TERMINAL-01").first()
    now = utc_now()
    user.livestream_expires_at = now + timedelta(days=30)
    db_session.commit()

    headers = {"X-Passcode": "PASS-TERMINAL-01"}

    # 2. Without shift token -> 403 Forbidden
    res_no_token = client.get("/v1/livestream/feed", headers=headers)
    assert res_no_token.status_code == 403
    assert "Shift token required" in res_no_token.json()["detail"]

    # 3. With invalid shift token -> 403 Forbidden
    res_bad_token = client.get("/v1/livestream/feed", headers={**headers, "X-Shift-Token": "invalid_fake_token"})
    assert res_bad_token.status_code == 403

    # 4. Verify Cashier PIN -> receives signed shift token
    res_pin = client.post("/v1/user/verify-cashier-pin", headers=headers, json={"cashier_pin": user.cashier_pin})
    assert res_pin.status_code == 200
    shift_token = res_pin.json()["shift_token"]
    assert shift_token is not None

    # 5. Access LiveStream with valid shift token -> 200 OK
    res_good = client.get("/v1/livestream/feed", headers={**headers, "X-Shift-Token": shift_token})
    assert res_good.status_code == 200
    assert res_good.json()["is_unlocked"] is True


def test_sec008_reverse_proxy_ip_extractor():
    """
    SEC-008 (Medium): Correctly resolves real client IP behind Nginx reverse proxies.
    """
    # Test X-Forwarded-For parsing (leftmost IP)
    scope_xff = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"203.0.113.195, 70.41.3.18, 150.172.238.178")],
        "client": ("127.0.0.1", 12345),
    }
    req_xff = Request(scope_xff)
    assert get_client_ip(req_xff) == "203.0.113.195"

    # Test X-Real-IP fallback
    scope_xreal = {
        "type": "http",
        "headers": [(b"x-real-ip", b"198.51.100.4")],
        "client": ("127.0.0.1", 12345),
    }
    req_xreal = Request(scope_xreal)
    assert get_client_ip(req_xreal) == "198.51.100.4"

    # Test direct socket fallback
    scope_direct = {
        "type": "http",
        "headers": [],
        "client": ("192.168.1.50", 12345),
    }
    req_direct = Request(scope_direct)
    assert get_client_ip(req_direct) == "192.168.1.50"


def test_sec009_voucher_redemption_rate_limiting(client: TestClient, auth_headers):
    """
    SEC-009 (Medium): Voucher redemption is protected against automated brute-force attempts.
    """
    res_reg = client.post("/v1/auth/register", json={"name": "Voucher Tester", "email": "voucher_tester@test.com"})
    assert res_reg.status_code == 201
    headers = {"X-Passcode": res_reg.json()["passcode"]}

    # Clear rate limiter failures for test isolation
    with voucher_redeem_limiter.lock:
        voucher_redeem_limiter.failures.clear()

    # Attempt 5 failed redemptions
    for i in range(5):
        res = client.post("/v1/passcodes/redeem", headers=headers, json={"passcode": f"INVALID-VOUCHER-{i}"})
        assert res.status_code in [400, 403, 404]

    # 6th attempt MUST be blocked by rate limiter with 429
    res_blocked = client.post("/v1/passcodes/redeem", headers=headers, json={"passcode": "INVALID-VOUCHER-6"})
    assert res_blocked.status_code == 429
    assert "Too many redemption attempts" in res_blocked.json()["detail"]

    # Clean up limiter state for subsequent tests
    with voucher_redeem_limiter.lock:
        voucher_redeem_limiter.failures.clear()
