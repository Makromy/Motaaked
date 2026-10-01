import pytest


class TestMultiUserApiKeys:

    def test_admin_create_user_api_key(self, client, auth_headers):
        response = client.post(
            "/v1/admin/keys/create",
            headers=auth_headers,
            json={"name": "Ahmed LMS Store", "role": "user"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Ahmed LMS Store"
        assert data["role"] == "user"
        assert data["is_active"] is True
        assert data["key"].startswith("instapay_live_")

    def test_admin_create_custom_key(self, client, auth_headers):
        response = client.post(
            "/v1/admin/keys/create",
            headers=auth_headers,
            json={"name": "Haitham Phone Forwarder", "role": "forwarder", "custom_key": "phone_key_custom_123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["key"] == "phone_key_custom_123"
        assert data["name"] == "Haitham Phone Forwarder"

    def test_list_api_keys(self, client, auth_headers):
        client.post("/v1/admin/keys/create", headers=auth_headers, json={"name": "Client A"})
        client.post("/v1/admin/keys/create", headers=auth_headers, json={"name": "Client B"})

        response = client.get("/v1/admin/keys/list", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2
        names = [k["name"] for k in data["keys"]]
        assert "Client A" in names
        assert "Client B" in names

    def test_use_new_user_key_for_api_operations(self, client, auth_headers):
        # 1. Create a user key
        res_key = client.post(
            "/v1/admin/keys/create",
            headers=auth_headers,
            json={"name": "Online Merchant 1"},
        )
        user_key = res_key.json()["key"]
        user_headers = {"X-API-Key": user_key}

        # 2. Ingest SMS using user key
        sms = "تم تحويل مبلغ 600 جم لحسابكم المنتهي بـ 8899 من حسام حسن مرجع: REF_USER_KEY_1"
        res_sms = client.post(
            "/v1/webhook/sms",
            headers=user_headers,
            json={"raw_message": sms},
        )
        assert res_sms.status_code == 201

        # 3. Create order using user key
        res_ord = client.post(
            "/v1/orders/create",
            headers=user_headers,
            json={"order_id": "ORD-USER-1", "amount": 600.0, "reference_id": "REF_USER_KEY_1"},
        )
        assert res_ord.status_code == 201

        # 4. Verify order using user key
        res_ver = client.post(
            "/v1/orders/verify",
            headers=user_headers,
            json={"order_id": "ORD-USER-1"},
        )
        assert res_ver.status_code == 200
        assert res_ver.json()["verified"] is True
        assert res_ver.json()["status"] == "MATCHED"

    def test_revoke_and_reactivate_user_key(self, client, auth_headers):
        # 1. Create key
        res_key = client.post(
            "/v1/admin/keys/create",
            headers=auth_headers,
            json={"name": "Temporary Client", "custom_key": "temp_key_999"},
        )
        temp_key = res_key.json()["key"]
        temp_headers = {"X-API-Key": temp_key}

        # 2. Key works initially
        res_check = client.post("/v1/orders/create", headers=temp_headers, json={"order_id": "ORD-TEMP-1", "amount": 100.0})
        assert res_check.status_code == 201

        # 3. Revoke key
        res_revoke = client.post(
            "/v1/admin/keys/revoke",
            headers=auth_headers,
            json={"key": temp_key},
        )
        assert res_revoke.status_code == 200
        assert res_revoke.json()["is_active"] is False

        # 4. Request using revoked key is rejected with 403
        res_blocked = client.post(
            "/v1/orders/create",
            headers=temp_headers,
            json={"order_id": "ORD-TEMP-2", "amount": 200.0},
        )
        assert res_blocked.status_code == 403
        assert "Invalid or deactivated" in res_blocked.json()["detail"]

        # 5. Reactivate key
        res_reactivate = client.post(
            "/v1/admin/keys/activate",
            headers=auth_headers,
            json={"key": temp_key},
        )
        assert res_reactivate.status_code == 200
        assert res_reactivate.json()["is_active"] is True

        # 6. Key works again
        res_restored = client.post(
            "/v1/orders/create",
            headers=temp_headers,
            json={"order_id": "ORD-TEMP-2", "amount": 200.0},
        )
        assert res_restored.status_code == 201

    def test_non_admin_cannot_access_admin_endpoints(self, client, auth_headers):
        # 1. Create a regular user key
        res_key = client.post(
            "/v1/admin/keys/create",
            headers=auth_headers,
            json={"name": "Regular User", "role": "user"},
        )
        regular_user_headers = {"X-API-Key": res_key.json()["key"]}

        # 2. Try to list keys as regular user -> 403 Forbidden
        res_unauthorized = client.get("/v1/admin/keys/list", headers=regular_user_headers)
        assert res_unauthorized.status_code == 403
        assert "Admin privileges required" in res_unauthorized.json()["detail"]

    def test_api_key_login_resolves_correct_user_without_crossover(self, client, auth_headers):
        """
        Regression test: An API key whose name contains a digit (e.g. 'PASS-E906-BDD7')
        must NOT match a different user whose ID equals that digit (e.g. User with id=6).
        """
        from app.models import User, ApiKey, utc_now
        from datetime import timedelta

        # 1. Create User with id=6 (or similar low digit)
        res_u1 = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={
                "user_name": "QA Mega Store 90C218",
                "custom_code": "PASS-062B-476B",
                "duration_days": 30,
                "credits": 500,
            },
        )
        assert res_u1.status_code == 201
        u1_id = res_u1.json()["id"]

        # 2. Create User 2 whose passcode contains u1_id as a substring (e.g. E90<u1_id>-BDD7)
        target_passcode = f"PASS-E90{u1_id}-BDD7"
        res_u2 = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={
                "user_name": "Dr. Haitham LMS",
                "custom_code": target_passcode,
                "duration_days": 30,
                "credits": 1000,
            },
        )
        assert res_u2.status_code == 201
        u2_id = res_u2.json()["id"]
        assert u2_id != u1_id

        # 3. Create a forwarder key linked to User 2
        fwd_key = "instapay_live_f782c033496a34ef12dfd7ae60a715af"
        res_key = client.post(
            "/v1/admin/keys/create",
            headers=auth_headers,
            json={
                "name": f"Forwarder - Dr. Haitham LMS ({target_passcode})",
                "role": "user",
                "custom_key": fwd_key,
                "user_id": u2_id,
            },
        )
        assert res_key.status_code == 201

        # 4. Attempt login via /v1/auth/passcode/login using the forwarder API key
        login_res = client.post(
            "/v1/auth/passcode/login",
            json={"passcode": fwd_key},
        )
        assert login_res.status_code == 200
        login_data = login_res.json()

        # MUST resolve to User 2 (Dr. Haitham LMS), NEVER to User 1 (QA Mega Store)
        assert login_data["id"] == u2_id
        assert login_data["name"] == "Dr. Haitham LMS"
        assert login_data["passcode"] == target_passcode

        # 5. Verify get_current_user also resolves to User 2
        profile_res = client.get(
            "/v1/user/profile",
            headers={"X-Passcode": fwd_key},
        )
        assert profile_res.status_code == 200
        assert profile_res.json()["id"] == u2_id
        assert profile_res.json()["name"] == "Dr. Haitham LMS"

    def test_legacy_api_key_without_user_id_self_heals(self, client, auth_headers):
        """
        Verify that legacy API keys with user_id=None resolve safely by passcode in name
        and automatically populate user_id in the database without crossovers.
        """
        # 1. Create a user
        res_u = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={
                "user_name": "Legacy Merchant Co",
                "custom_code": "PASS-LGCY-9988",
                "duration_days": 30,
                "credits": 200,
            },
        )
        assert res_u.status_code == 201
        user_id = res_u.json()["id"]

        # 2. Create an API key with custom name containing the passcode, and force user_id to None in DB
        legacy_key_str = "instapay_live_legacy_key_test_12345"
        res_k = client.post(
            "/v1/admin/keys/create",
            headers=auth_headers,
            json={
                "name": "Forwarder - Legacy Merchant Co (PASS-LGCY-9988)",
                "custom_key": legacy_key_str,
            },
        )
        assert res_k.status_code == 201

        from tests.conftest import TestingSessionLocal
        from app.models import ApiKey
        with TestingSessionLocal() as session:
            db_k = session.query(ApiKey).filter(ApiKey.key == legacy_key_str).first()
            assert db_k is not None
            db_k.user_id = None
            session.commit()

        # 3. Login using this key
        login_res = client.post(
            "/v1/auth/passcode/login",
            json={"passcode": legacy_key_str},
        )
        assert login_res.status_code == 200
        assert login_res.json()["id"] == user_id
        assert login_res.json()["name"] == "Legacy Merchant Co"

        # 4. Verify user_id is now self-healed in DB
        with TestingSessionLocal() as session:
            db_k = session.query(ApiKey).filter(ApiKey.key == legacy_key_str).first()
            assert db_k.user_id == user_id

