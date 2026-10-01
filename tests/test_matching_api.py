from datetime import timedelta
import pytest
from app.models import utc_now


class TestAuthAndHealth:

    def test_health_check(self, client):
        response = client.get("/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_webhook_requires_auth(self, client):
        # Missing API Key
        res_missing = client.post("/v1/webhook/sms", json={"raw_message": "test"})
        assert res_missing.status_code == 401

        # Invalid API Key
        res_invalid = client.post(
            "/v1/webhook/sms",
            headers={"X-API-Key": "wrong_key"},
            json={"raw_message": "test"},
        )
        assert res_invalid.status_code == 403


class TestSMSWebhook:

    def test_successful_sms_webhook_ingestion(self, client, auth_headers):
        sms_text = (
            "Your account ending in 1234 has been credited with EGP 1500.00 "
            "from AHMED MAHMOUD. Ref: IPN99887766 (IPN Inward Transfer)"
        )
        response = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": sms_text, "sender": "HSBC"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["data"]["amount"] == 1500.0
        assert data["data"]["reference_id"] == "IPN99887766"
        assert data["data"]["status"] == "UNCLAIMED"

    def test_duplicate_sms_webhook_rejection(self, client, auth_headers):
        sms_text = (
            "You have received an IPN transfer of EGP 350.00 to account ending 4321 "
            "from OMAR KHALED. Ref No: IPNDUP12345."
        )
        # First ingest
        res1 = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": sms_text},
        )
        assert res1.status_code == 201

        # Second ingest with same reference
        res2 = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": sms_text},
        )
        assert res2.status_code == 409
        assert "already been processed" in res2.json()["detail"]

    def test_invalid_sms_webhook_parsing_error(self, client, auth_headers):
        response = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": "Hello your balance is low."},
        )
        assert response.status_code == 422
        assert "SMS Parsing Failed" in response.json()["detail"]


class TestOrderMatchingEngine:

    def test_order_creation(self, client, auth_headers):
        response = client.post(
            "/v1/orders/create",
            headers=auth_headers,
            json={"order_id": "ORD-1001", "amount": 500.0, "reference_id": "IPN556677"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["order_id"] == "ORD-1001"
        assert data["amount"] == 500.0
        assert data["status"] == "PENDING"
        assert data["reference_id"] == "IPN556677"

    def test_duplicate_order_rejection(self, client, auth_headers):
        client.post(
            "/v1/orders/create",
            headers=auth_headers,
            json={"order_id": "ORD-DUP", "amount": 250.0},
        )
        res_dup = client.post(
            "/v1/orders/create",
            headers=auth_headers,
            json={"order_id": "ORD-DUP", "amount": 250.0},
        )
        assert res_dup.status_code == 409

    def test_verify_by_exact_reference_id(self, client, auth_headers):
        # 1. Ingest SMS
        sms = "تم تحويل مبلغ 1,200.00 جم لحسابكم المنتهي بـ 9988 من منى سيد مرجع رقم REF_EXACT_01"
        res_sms = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": sms},
        )
        assert res_sms.status_code == 201

        # 2. Create Order with reference_id
        res_order = client.post(
            "/v1/orders/create",
            headers=auth_headers,
            json={"order_id": "ORD-2001", "amount": 1200.0, "reference_id": "REF_EXACT_01"},
        )
        assert res_order.status_code == 201

        # 3. Verify Order
        res_verify = client.post(
            "/v1/orders/verify",
            headers=auth_headers,
            json={"order_id": "ORD-2001"},
        )
        assert res_verify.status_code == 200
        data = res_verify.json()
        assert data["verified"] is True
        assert data["status"] == "MATCHED"
        assert data["matched_credit"]["reference_id"] == "REF_EXACT_01"
        assert data["matched_credit"]["status"] == "CLAIMED"

        # 4. Verify idempotency
        res_reverify = client.post(
            "/v1/orders/verify",
            headers=auth_headers,
            json={"order_id": "ORD-2001"},
        )
        assert res_reverify.status_code == 200
        assert res_reverify.json()["verified"] is True
        assert "already verified" in res_reverify.json()["message"]

    def test_verify_fallback_by_amount_within_window(self, client, auth_headers):
        # 1. Ingest SMS (without knowing client order reference in advance)
        sms = "تم استلام تحويل لحظي بمبلغ 750.00 ج.م من سيف محمود إلى حسابكم. رقم المرجع IPN_FALLBACK_01"
        res_sms = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": sms},
        )
        assert res_sms.status_code == 201

        # 2. Create Order with amount only (no reference)
        res_order = client.post(
            "/v1/orders/create",
            headers=auth_headers,
            json={"order_id": "ORD-FALLBACK-1", "amount": 750.0},
        )
        assert res_order.status_code == 201

        # 3. Verify Order -> matches by amount within 30 min window
        res_verify = client.post(
            "/v1/orders/verify",
            headers=auth_headers,
            json={"order_id": "ORD-FALLBACK-1"},
        )
        assert res_verify.status_code == 200
        data = res_verify.json()
        assert data["verified"] is True
        assert data["status"] == "MATCHED"
        assert data["reference_id"] == "IPN_FALLBACK_01"
        assert data["matched_credit"]["status"] == "CLAIMED"

    def test_verify_expired_window_rejection(self, client, auth_headers):
        # Ingest SMS with timestamp 45 minutes ago
        past_time = utc_now() - timedelta(minutes=45)
        sms = "تم إضافة مبلغ 300 جم لحسابك المنتهي بـ 1111 من علي حسن تحويل لحظي مرجع: IPN_EXPIRED_01"
        res_sms = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": sms, "timestamp": past_time.isoformat()},
        )
        assert res_sms.status_code == 201

        # Create Order without reference_id
        client.post(
            "/v1/orders/create",
            headers=auth_headers,
            json={"order_id": "ORD-EXPIRED", "amount": 300.0},
        )

        # Verification by amount should fail because credit is outside 30-min window
        res_verify = client.post(
            "/v1/orders/verify",
            headers=auth_headers,
            json={"order_id": "ORD-EXPIRED"},
        )
        assert res_verify.status_code == 200
        assert res_verify.json()["verified"] is False
        assert res_verify.json()["status"] == "PENDING"

    def test_prevent_double_claim_on_same_credit(self, client, auth_headers):
        # Ingest 1 credit of 400 EGP
        sms = "You have received an IPN transfer of EGP 400.00 from ALY. Ref No: IPN_SINGLE_400"
        client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": sms},
        )

        # Create 2 orders for 400 EGP
        client.post("/v1/orders/create", headers=auth_headers, json={"order_id": "ORD-A", "amount": 400.0})
        client.post("/v1/orders/create", headers=auth_headers, json={"order_id": "ORD-B", "amount": 400.0})

        # Order A verifies first -> should succeed
        res_a = client.post("/v1/orders/verify", headers=auth_headers, json={"order_id": "ORD-A"})
        assert res_a.json()["verified"] is True
        assert res_a.json()["status"] == "MATCHED"

        # Order B verifies next -> should fail because credit is already CLAIMED
        res_b = client.post("/v1/orders/verify", headers=auth_headers, json={"order_id": "ORD-B"})
        assert res_b.json()["verified"] is False
        assert res_b.json()["status"] == "PENDING"

    def test_verify_order_not_found(self, client, auth_headers):
        response = client.post(
            "/v1/orders/verify",
            headers=auth_headers,
            json={"order_id": "NON_EXISTENT_ORDER"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_verify_supplying_ref_in_verify_request(self, client, auth_headers):
        # 1. Ingest SMS
        sms = "تم تحويل مبلغ 850 جم لحسابكم المنتهي بـ 3344 من أحمد جمال مرجع: REF_LATE_PROVIDE"
        client.post("/v1/webhook/sms", headers=auth_headers, json={"raw_message": sms})

        # 2. Create Order without reference
        client.post("/v1/orders/create", headers=auth_headers, json={"order_id": "ORD-LATE", "amount": 850.0})

        # 3. Supply reference in verify payload
        res_verify = client.post(
            "/v1/orders/verify",
            headers=auth_headers,
            json={"order_id": "ORD-LATE", "reference_id": "REF_LATE_PROVIDE"},
        )
        assert res_verify.status_code == 200
        assert res_verify.json()["verified"] is True
        assert res_verify.json()["status"] == "MATCHED"

    def test_merchant_isolation_cross_tenant_rejection(self, client, db_session):
        from datetime import datetime, timedelta
        from app.models import User, utc_now

        # 1. Create Merchant A and Merchant B
        merchant_a = User(
            name="Merchant A (LMS)",
            email="merchant_a@test.com",
            passcode="PASS-MERCHANT-A",
            account_ending="1111",
            role="user",
            subscription_expires_at=utc_now() + timedelta(days=30),
            credits_balance=100,
            free_credits=100,
            is_active=True,
        )
        merchant_b = User(
            name="Merchant B (Store)",
            email="merchant_b@test.com",
            passcode="PASS-MERCHANT-B",
            account_ending="2222",
            role="user",
            subscription_expires_at=utc_now() + timedelta(days=30),
            credits_balance=100,
            free_credits=100,
            is_active=True,
        )
        db_session.add_all([merchant_a, merchant_b])
        db_session.commit()
        db_session.refresh(merchant_a)
        db_session.refresh(merchant_b)

        headers_a = {"X-Passcode": "PASS-MERCHANT-A"}
        headers_b = {"X-Passcode": "PASS-MERCHANT-B"}

        # 2. Ingest SMS received by Merchant B's forwarder
        sms_b = "تم تحويل مبلغ 500 جم لحسابكم المنتهي بـ 2222 من عميل بي مرجع: REF_MERCHANT_B_999"
        res_sms = client.post("/v1/webhook/sms", headers=headers_b, json={"raw_message": sms_b})
        assert res_sms.status_code == 201

        # 3. Merchant A creates an order on their LMS for 500 EGP
        res_create_a = client.post(
            "/v1/orders/create",
            headers=headers_a,
            json={"order_id": "ORD-LMS-101", "amount": 500.0}
        )
        assert res_create_a.status_code == 201

        # 4. Student tries to claim Merchant B's reference ID on Merchant A's LMS -> MUST BE REJECTED!
        res_verify_a = client.post(
            "/v1/orders/verify",
            headers=headers_a,
            json={"order_id": "ORD-LMS-101", "reference_id": "REF_MERCHANT_B_999"}
        )
        assert res_verify_a.status_code == 200
        data_a = res_verify_a.json()
        assert data_a["verified"] is False
        assert data_a["status"] == "REJECTED"
        assert "different merchant" in data_a["message"]

        # 5. Merchant B creates an order for their store for 500 EGP
        res_create_b = client.post(
            "/v1/orders/create",
            headers=headers_b,
            json={"order_id": "ORD-STORE-202", "amount": 500.0}
        )
        assert res_create_b.status_code == 201

        # 6. Customer uses the reference on Merchant B's store -> SUCCEEDS!
        res_verify_b = client.post(
            "/v1/orders/verify",
            headers=headers_b,
            json={"order_id": "ORD-STORE-202", "reference_id": "REF_MERCHANT_B_999"}
        )
        assert res_verify_b.status_code == 200
        data_b = res_verify_b.json()
        assert data_b["verified"] is True
        assert data_b["status"] == "MATCHED"

    def test_merchant_isolation_external_plugin_routes_and_explorer(self, client, db_session):
        from datetime import datetime, timedelta
        from app.models import User, ApiKey, utc_now

        # 1. Create Merchant X and Merchant Y with API Keys
        user_x = User(
            name="Merchant X",
            passcode="PASS-MERCHANT-X",
            account_ending="5555",
            role="user",
            subscription_expires_at=utc_now() + timedelta(days=30),
            credits_balance=100,
            free_credits=100,
            is_active=True,
        )
        user_y = User(
            name="Merchant Y",
            passcode="PASS-MERCHANT-Y",
            account_ending="7777",
            role="user",
            subscription_expires_at=utc_now() + timedelta(days=30),
            credits_balance=100,
            free_credits=100,
            is_active=True,
        )
        db_session.add_all([user_x, user_y])
        db_session.commit()
        db_session.refresh(user_x)
        db_session.refresh(user_y)

        key_x = ApiKey(key="instapay_live_key_x_1234567890", name="Merchant X Key", role="user", user_id=user_x.id, is_active=True)
        key_y = ApiKey(key="instapay_live_key_y_1234567890", name="Merchant Y Key", role="user", user_id=user_y.id, is_active=True)
        db_session.add_all([key_x, key_y])
        db_session.commit()

        headers_x = {"X-API-Key": key_x.key}
        headers_y = {"X-API-Key": key_y.key}

        # 2. Ingest SMS belonging to Merchant Y (account 7777)
        sms_y = "تم تحويل مبلغ 1500 جم لحسابكم المنتهي بـ 7777 من عميل واي مرجع: REF_MERCHANT_Y_ISOLATED"
        res_sms = client.post("/v1/webhook/sms", headers=headers_y, json={"raw_message": sms_y})
        assert res_sms.status_code == 201

        # 3. Test LearnDash Compatibility Route: GET /v1/transfers/{ref_id}
        # Merchant X tries to query Merchant Y's transfer -> MUST RETURN NOT_FOUND!
        res_ld_x = client.get(
            "/v1/transfers/REF_MERCHANT_Y_ISOLATED",
            headers={"Authorization": f"Bearer {key_x.key}"},
        )
        assert res_ld_x.status_code == 200
        assert res_ld_x.json()["status"] == "NOT_FOUND"

        # Merchant Y queries their own transfer -> SUCCEEDS!
        res_ld_y = client.get(
            "/v1/transfers/REF_MERCHANT_Y_ISOLATED",
            headers={"Authorization": f"Bearer {key_y.key}"},
        )
        assert res_ld_y.status_code == 200
        assert res_ld_y.json()["status"] == "SUCCESS"
        assert res_ld_y.json()["amount"] == 1500.0

        # 4. Test Shopify Compatibility Route: GET /transactions/{ref_id}
        # Merchant X tries to query Merchant Y's transfer -> NOT_FOUND!
        res_sh_x = client.get(
            "/transactions/REF_MERCHANT_Y_ISOLATED",
            headers={"Authorization": f"Bearer {key_x.key}"},
        )
        assert res_sh_x.status_code == 200
        assert res_sh_x.json()["status"] == "NOT_FOUND"

        # 5. Test Laravel Compatibility Route: POST /api/verify
        # Merchant X tries to verify Merchant Y's transfer -> REJECTED!
        client.post("/api/orders", headers=headers_x, json={"order_id": "ORD-LARAVEL-X", "amount": 1500.0})
        res_lar_x = client.post(
            "/api/verify",
            headers=headers_x,
            json={"order_id": "ORD-LARAVEL-X", "reference_id": "REF_MERCHANT_Y_ISOLATED"},
        )
        assert res_lar_x.status_code == 200
        assert res_lar_x.json()["verified"] is False
        assert res_lar_x.json()["status"] == "REJECTED"

        # 6. Test Transaction Explorer /v1/transactions/filter
        # Merchant X views explorer -> 0 transactions visible
        res_exp_x = client.get("/v1/transactions/filter", headers=headers_x)
        assert res_exp_x.status_code == 200
        assert res_exp_x.json()["total"] == 0

        # 7. Test Single Search /v1/transactions/search
        # Merchant X searches Merchant Y's reference -> found is False
        res_search_x = client.post(
            "/v1/transactions/search",
            headers=headers_x,
            json={"reference_id": "REF_MERCHANT_Y_ISOLATED"},
        )
        assert res_search_x.status_code == 200
        assert res_search_x.json()["found"] is False



