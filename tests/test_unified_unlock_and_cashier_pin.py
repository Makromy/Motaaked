"""
Tests for 6-Character Alphanumeric Cashier PIN & Unified Unlock Credentials (Option 3).

Verifies:
1. PIN generation format: exactly 6 characters (4 digits and 2 letters shuffled, e.g., A123C4, 2D5A72).
2. LiveStream Shift Gate (/v1/user/verify-cashier-pin):
   - Accepts 6-character Cashier PIN (case-insensitive).
   - Accepts Merchant Forwarder API Key.
   - Accepts Super Admin Master API Key.
   - Strictly REJECTS Merchant Login Passcode (PASS-XXXX-XXXX).
3. Explorer Transaction Vault (/v1/transactions/unlock):
   - Accepts 6-character Cashier PIN (case-insensitive).
   - Accepts Merchant Forwarder API Key.
   - Accepts Super Admin Master API Key.
   - Strictly REJECTS Merchant Login Passcode (PASS-XXXX-XXXX).
4. Profile PIN update (/v1/user/cashier-pin):
   - Enforces 4-12 alphanumeric characters.
   - Normalizes to uppercase.
"""

import pytest
from fastapi.testclient import TestClient
from app.models import User, _random_cashier_pin
from app.auth import get_current_master_keys


def test_random_cashier_pin_format():
    """Verify that random Cashier PIN produces 4 digits and 2 uppercase letters shuffled."""
    for _ in range(50):
        pin = _random_cashier_pin()
        assert len(pin) == 6
        assert pin.isalnum()
        digits = sum(c.isdigit() for c in pin)
        letters = sum(c.isupper() for c in pin)
        assert digits == 4
        assert letters == 2


def test_unified_unlock_livestream_and_explorer(client: TestClient, db_session):
    """
    Test Option 3 Unified Unlock Credentials on both LiveStream and Explorer endpoints.
    """
    # 1. Register a fresh merchant
    reg_resp = client.post(
        "/v1/auth/register",
        json={
            "name": "Unified Store",
            "email": "unified@store.com",
            "phone": "01055554444",
            "account_ending": "3322",
        },
    )
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    passcode = data["passcode"]
    fwd_key = data["forwarder_api_key"]
    cashier_pin = data["cashier_pin"]

    assert len(cashier_pin) == 6
    assert cashier_pin.isalnum()
    assert sum(c.isdigit() for c in cashier_pin) == 4
    assert sum(c.isupper() for c in cashier_pin) == 2

    headers = {"X-Passcode": passcode}
    master_key = get_current_master_keys()[0]

    # --- LiveStream Shift Gate (/v1/user/verify-cashier-pin) ---

    # A. 6-character PIN uppercase -> 200 OK
    res1 = client.post("/v1/user/verify-cashier-pin", headers=headers, json={"cashier_pin": cashier_pin.upper()})
    assert res1.status_code == 200
    assert res1.json()["success"] is True

    # B. 6-character PIN lowercase (case-insensitive test) -> 200 OK
    res2 = client.post("/v1/user/verify-cashier-pin", headers=headers, json={"cashier_pin": cashier_pin.lower()})
    assert res2.status_code == 200
    assert res2.json()["success"] is True

    # C. Forwarder API Key -> 200 OK
    res3 = client.post("/v1/user/verify-cashier-pin", headers=headers, json={"cashier_pin": fwd_key})
    assert res3.status_code == 200
    assert res3.json()["success"] is True

    # D. Super Admin Master Key -> 200 OK
    res4 = client.post("/v1/user/verify-cashier-pin", headers=headers, json={"cashier_pin": master_key})
    assert res4.status_code == 200
    assert res4.json()["success"] is True

    # E. Login Passcode (PASS-XXXX-XXXX) -> MUST BE REJECTED with 403 Forbidden
    res5 = client.post("/v1/user/verify-cashier-pin", headers=headers, json={"cashier_pin": passcode})
    assert res5.status_code == 403

    # F. Invalid random key -> 403 Forbidden
    res6 = client.post("/v1/user/verify-cashier-pin", headers=headers, json={"cashier_pin": "INVALID99"})
    assert res6.status_code == 403

    # --- Explorer Vault Gate (/v1/transactions/unlock) ---

    # A. 6-character PIN uppercase -> 200 OK
    v_res1 = client.post("/v1/transactions/unlock", headers=headers, json={"forwarder_api_key": cashier_pin.upper()})
    assert v_res1.status_code == 200
    assert v_res1.json()["success"] is True

    # B. 6-character PIN lowercase -> 200 OK
    v_res2 = client.post("/v1/transactions/unlock", headers=headers, json={"forwarder_api_key": cashier_pin.lower()})
    assert v_res2.status_code == 200
    assert v_res2.json()["success"] is True

    # C. Forwarder API Key -> 200 OK
    v_res3 = client.post("/v1/transactions/unlock", headers=headers, json={"forwarder_api_key": fwd_key})
    assert v_res3.status_code == 200
    assert v_res3.json()["success"] is True

    # D. Super Admin Master Key -> 200 OK
    v_res4 = client.post("/v1/transactions/unlock", headers=headers, json={"forwarder_api_key": master_key})
    assert v_res4.status_code == 200
    assert v_res4.json()["success"] is True

    # E. Login Passcode (PASS-XXXX-XXXX) -> MUST BE REJECTED with 403 Forbidden
    v_res5 = client.post("/v1/transactions/unlock", headers=headers, json={"forwarder_api_key": passcode})
    assert v_res5.status_code == 403

    # F. Invalid key -> 403 Forbidden
    v_res6 = client.post("/v1/transactions/unlock", headers=headers, json={"forwarder_api_key": "WRONG_KEY_000"})
    assert v_res6.status_code == 403


def test_update_cashier_pin_validation(client: TestClient):
    """Verify owner update of Cashier PIN with format enforcement."""
    # Register merchant
    reg_resp = client.post(
        "/v1/auth/register",
        json={
            "name": "PIN Update Store",
            "email": "pinupdate@store.com",
            "phone": "01011112222",
            "account_ending": "9988",
        },
    )
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    passcode = data["passcode"]
    fwd_key = data["forwarder_api_key"]
    headers = {"X-Passcode": passcode}

    # 1. Update with valid 6-char alphanumeric PIN
    up_res = client.post(
        "/v1/user/cashier-pin",
        headers=headers,
        json={"owner_key": fwd_key, "new_cashier_pin": "2d5a72"},
    )
    assert up_res.status_code == 200
    assert up_res.json()["user_profile"]["cashier_pin"] == "2D5A72"

    # 2. Verify new PIN unlocks LiveStream and Explorer (case-insensitive)
    ls_ver = client.post("/v1/user/verify-cashier-pin", headers=headers, json={"cashier_pin": "2d5a72"})
    assert ls_ver.status_code == 200

    exp_ver = client.post("/v1/transactions/unlock", headers=headers, json={"forwarder_api_key": "2D5A72"})
    assert exp_ver.status_code == 200

    # 3. Reject non-alphanumeric PIN
    bad_res = client.post(
        "/v1/user/cashier-pin",
        headers=headers,
        json={"owner_key": fwd_key, "new_cashier_pin": "A12-3C"},
    )
    assert bad_res.status_code == 400

    # 4. Reject too short (< 4 chars) -> 422 Unprocessable Entity from Pydantic schema or 400
    short_res = client.post(
        "/v1/user/cashier-pin",
        headers=headers,
        json={"owner_key": fwd_key, "new_cashier_pin": "A1"},
    )
    assert short_res.status_code in [400, 422]


def test_secondary_api_key_unlocks_livestream_and_explorer(client: TestClient, db_session, auth_headers):
    """
    Verify that secondary/custom ApiKey records bound to the merchant
    (e.g. issued via Admin Panel or Plugin SDK) successfully unlock both LiveStream and Explorer.
    """
    from app.models import ApiKey
    from app.auth import hash_api_key

    # 1. Register a merchant
    reg_resp = client.post(
        "/v1/auth/register",
        json={
            "name": "Multi Key Merchant",
            "email": "multikey@merchant.com",
            "phone": "01099991111",
            "account_ending": "7766",
        },
    )
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    user_id = data["id"]
    passcode = data["passcode"]
    headers = {"X-Passcode": passcode}

    # 2. Add an additional custom API key bound to this user
    custom_key = "instapay_live_custom_plugin_key_99887766"
    new_api_key = ApiKey(
        key=custom_key,
        key_hash=hash_api_key(custom_key),
        key_prefix=custom_key[:12],
        user_id=user_id,
        name=f"Custom Plugin Key ({passcode})",
        role="user",
        is_active=True,
    )
    db_session.add(new_api_key)
    db_session.commit()

    # 3. LiveStream Shift Modal unlocks with custom_key -> 200 OK
    ls_res = client.post("/v1/user/verify-cashier-pin", headers=headers, json={"cashier_pin": custom_key})
    assert ls_res.status_code == 200
    assert ls_res.json()["success"] is True

    # 4. Explorer Vault Gate unlocks with custom_key -> 200 OK
    exp_res = client.post("/v1/transactions/unlock", headers=headers, json={"forwarder_api_key": custom_key})
    assert exp_res.status_code == 200
    assert exp_res.json()["success"] is True

