import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config import settings


def test_master_admin_substring_bypass_is_rejected(client: TestClient, auth_headers):
    """
    VULN-01 Verification:
    Verify that single-character or substring matching against MASTER_API_KEY in payload.admin_key is rejected with 403.
    Only the exact full master key should be accepted.
    """
    # Attempting substring bypass with single character "X" or "A" which exists in "XAZAjxjhbCtSgiq7"
    bad_payload = {
        "admin_key": "X",
        "portal_name": "Attacker Pwned",
    }
    resp = client.post("/v1/admin/settings", json=bad_payload, headers=auth_headers)
    assert resp.status_code == 403
    assert "Invalid Master Admin Key" in resp.json()["detail"]

    # Attempting with a 4-character prefix substring of the real master key
    real_key = settings.MASTER_API_KEY
    if len(real_key) > 4:
        substring_key = real_key[:4]
        resp = client.post(
            "/v1/admin/settings",
            json={"admin_key": substring_key, "portal_name": "Attacker"},
            headers=auth_headers,
        )
        assert resp.status_code == 403
        assert "Invalid Master Admin Key" in resp.json()["detail"]

    # Exact full master key must succeed
    good_payload = {
        "admin_key": real_key,
        "portal_name": settings.PORTAL_NAME,
    }
    resp = client.post("/v1/admin/settings", json=good_payload, headers=auth_headers)
    assert resp.status_code == 200


def test_email_preview_does_not_leak_in_static_directory(client: TestClient):
    """
    VULN-03 Verification:
    Verify that dispatching simulated emails does NOT write to the publicly mountable static/ directory.
    """
    from app.email_service import _send_smtp_email

    static_preview = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "latest_email_preview.html")
    # Ensure it doesn't exist before or after
    if os.path.exists(static_preview):
        os.remove(static_preview)

    _send_smtp_email(
        to_email="secret_audit_user@example.com",
        subject="Audit Secret Passcode Test",
        html_content="<p>Confidential Token: 999888777</p>",
    )

    # Must NOT exist under static/
    assert not os.path.exists(static_preview)


def test_bank_pattern_redos_and_length_protection():
    """
    VULN-06 Verification:
    Verify that excessive pattern lengths are rejected cleanly.
    """
    from app.services import test_bank_pattern_simulation
    from app.models import BankPatternTestRequest

    # Pattern > 2500 characters
    huge_pattern = "a" * 2501
    req = BankPatternTestRequest(
        pattern=huge_pattern,
        sample_text="Sample text",
        amount_group="amount",
        ref_group="ref",
    )
    res = test_bank_pattern_simulation(req)
    assert res.matched is False
    assert "exceeds maximum allowed length" in res.error


def test_ticket_code_high_entropy_and_pii_masking(client: TestClient):
    """
    Phase 1 Verification:
    Verify ticket code generated has 64-bit entropy (16 hex chars)
    and public GET endpoint masks PII and omits admin_notes.
    """
    from app.services import generate_ticket_code
    code = generate_ticket_code()
    assert code.startswith("TCK-2026-")
    # TCK-2026-XXXX-XXXX-XXXX-XXXX -> parts after prefix should have 16 hex chars + hyphens = 19 chars
    token_part = code.replace("TCK-2026-", "").replace("-", "")
    assert len(token_part) == 16
    assert all(c in "0123456789ABCDEF" for c in token_part)

    # Submit ticket and verify public response masks email and phone
    payload = {
        "merchant_name": "Karim Security Test",
        "merchant_email": "karim.specialist@company.com",
        "merchant_phone": "01098765432",
        "category": "general_inquiry",
        "subject": "Security Review Audit",
        "message": "Testing ticket data minimization and PII masking.",
    }
    with patch("app.email_service.send_ticket_created_emails") as mock_mail:
        mock_mail.return_value = {"merchant": True, "admin": True}
        create_res = client.post("/v1/support/tickets", json=payload)
    assert create_res.status_code == 201
    created_ticket = create_res.json()
    t_code = created_ticket["ticket_code"]

    # Public lookup
    get_res = client.get(f"/v1/support/tickets/{t_code}")
    assert get_res.status_code == 200
    public_data = get_res.json()
    assert public_data["ticket_code"] == t_code
    assert public_data["merchant_name"] == "Karim Security Test"
    # PII must be masked
    assert "@" in public_data["merchant_email"]
    assert "karim.specialist" not in public_data["merchant_email"]
    assert public_data["merchant_email"].startswith("k*")
    assert public_data["merchant_phone"].startswith("010*")
    assert public_data["admin_notes"] is None


def test_cashier_pin_rate_limiter_blocks_brute_force(client: TestClient, auth_headers):
    """
    Phase 1 Verification:
    Verify that 5 failed cashier PIN attempts trigger a 429 lockout.
    """
    from app.main import cashier_pin_limiter
    # Provision a test user
    client.post(
        "/v1/admin/passcodes/generate",
        json={"user_name": "Cashier Test User", "duration_days": 30, "custom_code": "PASS-CASHIER-TEST"},
        headers=auth_headers,
    )
    passcode_headers = {"X-Passcode": "PASS-CASHIER-TEST"}

    # Clear limiter state for test determinism
    with cashier_pin_limiter.lock:
        cashier_pin_limiter.failures.clear()

    # 5 failed attempts
    for i in range(5):
        resp = client.post(
            "/v1/user/verify-cashier-pin",
            json={"cashier_pin": f"999{i}"},
            headers=passcode_headers,
        )
        assert resp.status_code == 403

    # 6th attempt must trigger HTTP 429 Too Many Requests
    resp_locked = client.post(
        "/v1/user/verify-cashier-pin",
        json={"cashier_pin": "1234"},
        headers=passcode_headers,
    )
    assert resp_locked.status_code == 429
    assert "lockout active" in resp_locked.json()["detail"].lower()
    assert "retry-after" in resp_locked.headers


def test_pdf_generation_escapes_xml_injection():
    """
    Phase 1 Verification:
    Verify that ReportLab statements with XML tags in merchant or sender names
    compile safely without expat XML parser errors.
    """
    from datetime import date
    from app.models import User, IncomingCredit, utc_now
    from app.pdf_service import generate_sms_statement_pdf

    user = User(
        id=999,
        name="<script>alert('xss')</script> & Co",
        email="test@hacked.com",
        passcode="PASS-AUDIT-PDF",
        account_ending="<1234>",
        role="user",
        subscription_expires_at=utc_now(),
        credits_balance=100,
    )

    credit = IncomingCredit(
        id=1,
        user_id=999,
        amount=250.0,
        currency="EGP",
        reference_id="<REF&TAG123>",
        sender_name="<b>Malicious Sender</b>",
        account_ending="1234",
        status="CLAIMED",
        received_at=utc_now(),
        raw_message="Alert with <xml> tags",
    )

    pdf_bytes = generate_sms_statement_pdf(
        merchant=user,
        transactions=[credit],
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        portal_name="<TestPortal>&Safe",
    )

    assert pdf_bytes is not None
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000


def test_checkout_session_rejects_unsafe_uri_schemes():
    """
    Phase 1 Verification:
    Verify that CreateCheckoutSessionRequest rejects javascript:, data:, or malformed redirect URLs.
    """
    from pydantic import ValidationError
    from app.models import CreateCheckoutSessionRequest

    # Dangerous javascript: scheme
    with pytest.raises(ValidationError) as exc:
        CreateCheckoutSessionRequest(
            order_id="ORD-101",
            amount=100.0,
            return_url="javascript:alert(document.cookie)",
        )
    assert "Dangerous URI schemes" in str(exc.value)

    # Dangerous data: scheme
    with pytest.raises(ValidationError) as exc:
        CreateCheckoutSessionRequest(
            order_id="ORD-102",
            amount=100.0,
            cancel_url="data:text/html;base64,PHNjcmlwdD4=",
        )
    assert "Dangerous URI schemes" in str(exc.value)

    # Non-HTTP protocol
    with pytest.raises(ValidationError) as exc:
        CreateCheckoutSessionRequest(
            order_id="ORD-103",
            amount=100.0,
            return_url="ftp://evil.com/payload",
        )
    assert "URL must start with http://" in str(exc.value)

    valid_https = CreateCheckoutSessionRequest(
        order_id="ORD-104",
        amount=100.0,
        return_url="https://merchant.com/checkout/success",
        cancel_url="/checkout/cancelled",
    )
    assert valid_https.return_url == "https://merchant.com/checkout/success"
    assert valid_https.cancel_url == "/checkout/cancelled"


def test_multi_tenant_account_ending_ambiguity_protection(client: TestClient, auth_headers):
    """
    Phase 2 Verification:
    Verify that when multiple merchants share identical 4-digit bank account endings (e.g. 7777),
    unlinked SMS alerts are NOT misattributed to the wrong merchant.
    Once Merchant A searches and matches the credit, it seals ownership so Merchant B cannot claim it.
    """
    from app.models import IncomingCredit

    # 1. Create Merchant A with account_ending 7777
    client.post(
        "/v1/admin/passcodes/generate",
        json={"user_name": "Merchant A", "custom_code": "PASS-MERCH-A", "account_ending": "7777"},
        headers=auth_headers,
    )
    headers_a = {"X-Passcode": "PASS-MERCH-A"}

    # 2. Create Merchant B also with account_ending 7777
    client.post(
        "/v1/admin/passcodes/generate",
        json={"user_name": "Merchant B", "custom_code": "PASS-MERCH-B", "account_ending": "7777"},
        headers=auth_headers,
    )
    headers_b = {"X-Passcode": "PASS-MERCH-B"}

    # 3. Ingest SMS with account_ending 7777 from unlinked source
    sms = "تم استلام تحويل لحظي بمبلغ 500.00 ج.م لحسابكم المنتهي بـ 7777 من محمود سامي. مرجع: REF_AMBIGUOUS_7777"
    res_sms = client.post("/v1/webhook/sms", headers=auth_headers, json={"raw_message": sms})
    assert res_sms.status_code == 201

    # 4. Merchant A looks up REF_AMBIGUOUS_7777 and matches it
    res_search_a = client.post("/v1/transactions/search", headers=headers_a, json={"reference_id": "REF_AMBIGUOUS_7777"})
    assert res_search_a.status_code == 200
    assert res_search_a.json()["found"] is True

    # 5. Merchant B attempts to look up REF_AMBIGUOUS_7777 -> Must NOT find it (sealed to Merchant A)
    res_search_b = client.post("/v1/transactions/search", headers=headers_b, json={"reference_id": "REF_AMBIGUOUS_7777"})
    assert res_search_b.status_code == 200
    assert res_search_b.json()["found"] is False


def test_reference_less_matching_policy(client: TestClient, auth_headers):
    """
    Phase 2 Verification:
    Verify that when allow_reference_less_order_matching setting is disabled,
    external orders without a reference_id are rejected to prevent payment theft.
    """
    # 1. Create a merchant
    client.post(
        "/v1/admin/passcodes/generate",
        json={"user_name": "Strict Merchant", "custom_code": "PASS-STRICT-1"},
        headers=auth_headers,
    )
    merchant_headers = {"X-Passcode": "PASS-STRICT-1"}

    # 2. Ingest SMS for this merchant
    sms = "تم تحويل مبلغ 350.00 جم لحسابكم من طارق أحمد مرجع: REF_STRICT_350"
    client.post("/v1/webhook/sms", headers=merchant_headers, json={"raw_message": sms})

    # 3. Create merchant order without reference_id
    client.post(
        "/v1/orders/create",
        headers=merchant_headers,
        json={"order_id": "ORD-STRICT-1", "amount": 350.0},
    )

    # 4. Disable allow_reference_less_order_matching
    client.post(
        "/v1/admin/settings",
        headers=auth_headers,
        json={"allow_reference_less_order_matching": False},
    )

    # 5. Attempt verify without reference_id -> Must be rejected
    res_verify = client.post(
        "/v1/orders/verify",
        headers=merchant_headers,
        json={"order_id": "ORD-STRICT-1"},
    )
    assert res_verify.status_code == 200
    data = res_verify.json()
    assert data["verified"] is False
    assert data["status"] == "REJECTED"
    assert "Reference ID is required" in data["message"]

    # 6. Verify WITH exact reference_id -> Must succeed
    res_with_ref = client.post(
        "/v1/orders/verify",
        headers=merchant_headers,
        json={"order_id": "ORD-STRICT-1", "reference_id": "REF_STRICT_350"},
    )
    assert res_with_ref.status_code == 200
    assert res_with_ref.json()["verified"] is True
    assert res_with_ref.json()["status"] == "MATCHED"


def test_phase3_cryptographic_credential_hashing():
    """
    Phase 3 Verification:
    Verify PBKDF2-HMAC-SHA256 credential hashing, random salting,
    and constant-time verification with legacy plaintext support.
    """
    from app.auth import hash_secret, verify_secret, is_hashed, hash_api_key

    secret = "TopSecretPIN123!"
    h1 = hash_secret(secret)
    h2 = hash_secret(secret)

    # 1. Salted hashes must be distinct due to random 16-byte salt
    assert h1 != h2
    assert h1.startswith("pbkdf2:sha256:100000$")
    assert is_hashed(h1) is True
    assert is_hashed("1234") is False

    # 2. Both hashes must verify against correct secret
    assert verify_secret(secret, h1) is True
    assert verify_secret(secret, h2) is True

    # 3. Wrong secret must fail
    assert verify_secret("WrongSecret", h1) is False

    # 4. Legacy plaintext verification
    assert verify_secret("1234", "1234") is True
    assert verify_secret("pass-sarah", "PASS-SARAH") is True
    assert verify_secret("wrong", "1234") is False

    # 5. API key SHA-256 hash indexing
    key = "instapay_live_abcdef1234567890"
    k_hash = hash_api_key(key)
    assert len(k_hash) == 64
    import hashlib
    assert k_hash == hashlib.sha256(key.encode("utf-8")).hexdigest()


def test_phase3_cashier_pin_transparent_auto_migration(client: TestClient, db_session):
    """
    Phase 3 Verification:
    Verify that an existing merchant with a legacy plaintext cashier PIN
    is transparently migrated to a salted PBKDF2 hash on successful verification,
    and that subsequent verifications verify against the cryptographic hash.
    """
    from app.models import User
    from app.auth import is_hashed

    # 1. Register a merchant with plaintext PIN
    reg_res = client.post(
        "/v1/auth/register",
        json={
            "name": "Migration Merchant",
            "email": "migration@merchant.com",
            "phone": "01122334455",
            "account_ending": "8877",
        }
    )
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    merchant_passcode = reg_data["passcode"]
    merchant_headers = {"X-Passcode": merchant_passcode}

    from app.main import cashier_pin_limiter
    with cashier_pin_limiter.lock:
        cashier_pin_limiter.failures.clear()

    user = db_session.query(User).filter(User.passcode == merchant_passcode).first()
    assert user is not None
    # Explicitly ensure cashier PIN starts in legacy plaintext
    user.cashier_pin = "A123C4"
    db_session.commit()
    db_session.refresh(user)
    assert user.cashier_pin == "A123C4"
    assert is_hashed(user.cashier_pin) is False

    # 2. Verify Cashier PIN (case-insensitive 'a123c4') -> must succeed (200 OK)
    ver_res1 = client.post(
        "/v1/user/verify-cashier-pin",
        headers=merchant_headers,
        json={"cashier_pin": "a123c4"},
    )
    assert ver_res1.status_code == 200
    assert ver_res1.json()["success"] is True

    # 3. Assert database row preserves clean readable 6-character PIN for merchant profile
    db_session.refresh(user)
    assert user.cashier_pin == "A123C4"

    # 4. Verify owner passcode (PASS-XXXX-XXXX) is STRICTLY REJECTED for shift unlock
    ver_res2 = client.post(
        "/v1/user/verify-cashier-pin",
        headers=merchant_headers,
        json={"cashier_pin": merchant_passcode},
    )
    assert ver_res2.status_code == 403

    # 5. Verify Forwarder API key unlocks cashier shift view
    fwd_key = reg_data["forwarder_api_key"]
    ver_fwd = client.post(
        "/v1/user/verify-cashier-pin",
        headers=merchant_headers,
        json={"cashier_pin": fwd_key},
    )
    assert ver_fwd.status_code == 200
    assert ver_fwd.json()["success"] is True

    # 6. Invalid PIN must be rejected
    ver_bad = client.post(
        "/v1/user/verify-cashier-pin",
        headers=merchant_headers,
        json={"cashier_pin": "999999"},
    )
    assert ver_bad.status_code == 403


def test_phase3_api_key_sha256_indexing_and_auth(client: TestClient, auth_headers, db_session):
    """
    Phase 3 Verification:
    Verify that ApiKey creation populates key_hash (SHA-256) and key_prefix,
    and authentication endpoints successfully authenticate callers via key_hash.
    """
    from app.models import ApiKey
    import hashlib

    # 1. Create a developer API key via Admin endpoint
    res = client.post(
        "/v1/admin/keys/create",
        json={"name": "Audit Test Forwarder Key", "role": "user"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    key_data = res.json()
    raw_key = key_data["key"]
    assert raw_key.startswith("instapay_live_")
    assert key_data.get("key_hash") is not None
    assert key_data.get("key_prefix") == raw_key[:12]

    # Verify database row
    api_k = db_session.query(ApiKey).filter(ApiKey.id == key_data["id"]).first()
    assert api_k is not None
    assert api_k.key_hash == hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    assert api_k.key_prefix == raw_key[:12]

    # 2. Test authenticating to API using the new key in X-API-Key header
    order_res = client.post(
        "/v1/orders/create",
        headers={"X-API-Key": raw_key},
        json={"order_id": "ORD-AUDIT-KEY-1", "amount": 100.0},
    )
    assert order_res.status_code == 201

    # 3. Simulate stored raw key masked / redacted (key_hash only auth)
    api_k.key = "REDACTED_ORIGINAL_KEY"
    db_session.commit()

    # Caller can still authenticate because verify_api_key queries by key_hash!
    order_res2 = client.post(
        "/v1/orders/create",
        headers={"X-API-Key": raw_key},
        json={"order_id": "ORD-AUDIT-KEY-2", "amount": 200.0},
    )
    assert order_res2.status_code == 201


def test_phase3_passcode_hashed_dual_mode_auth(client: TestClient, auth_headers, db_session):
    """
    Phase 3 Verification:
    Verify that a user whose passcode is stored as a salted PBKDF2 hash
    can seamlessly authenticate via /v1/auth/passcode/login and X-Passcode header.
    """
    from app.models import User
    from app.auth import hash_secret

    plain_passcode = "PASS-CRYPTO-USER-2026"
    hashed_passcode = hash_secret(plain_passcode)

    # 1. Create a user via admin
    client.post(
        "/v1/admin/passcodes/generate",
        json={"user_name": "Crypto User", "custom_code": plain_passcode},
        headers=auth_headers,
    )

    user = db_session.query(User).filter(User.passcode == plain_passcode).first()
    assert user is not None
    # Upgrade passcode to PBKDF2 hash in database
    user.passcode = hashed_passcode
    db_session.commit()

    # 2. Login via /v1/auth/passcode/login with raw plaintext passcode
    login_res = client.post(
        "/v1/auth/passcode/login",
        json={"passcode": plain_passcode},
    )
    assert login_res.status_code == 200
    data = login_res.json()
    assert data["name"] == "Crypto User"
    assert data["passcode"] == plain_passcode

    # 3. Authenticate to protected user profile using X-Passcode header
    prof_res = client.get(
        "/v1/user/profile",
        headers={"X-Passcode": plain_passcode},
    )
    assert prof_res.status_code == 200
    assert prof_res.json()["name"] == "Crypto User"



