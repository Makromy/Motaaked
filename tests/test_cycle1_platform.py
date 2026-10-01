from datetime import date, timedelta
import pytest
from app.models import utc_now, IncomingCredit, User, Passcode


class TestCycle1Platform:

    def test_admin_generate_passcode(self, client, auth_headers):
        response = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Dr. Tarek LMS", "phone": "01012345678", "duration_days": 30, "credits": 100},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Dr. Tarek LMS"
        assert data["credits_balance"] == 100
        assert data["is_subscription_valid"] is True
        assert data["passcode"].startswith("PASS-")

    def test_passcode_login_and_profile(self, client, auth_headers):
        # 1. Admin generates code
        res_gen = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Sarah Shop", "custom_code": "PASS-SARAH-2026", "duration_days": 60, "credits": 150},
        )
        assert res_gen.status_code == 201

        # 2. User logs in with passcode
        res_login = client.post(
            "/v1/auth/passcode/login",
            json={"passcode": "PASS-SARAH-2026"},
        )
        assert res_login.status_code == 200
        data = res_login.json()
        assert data["name"] == "Sarah Shop"
        assert data["credits_balance"] == 150
        assert data["is_subscription_valid"] is True

        # 3. User views profile via header
        user_headers = {"X-Passcode": "PASS-SARAH-2026"}
        res_prof = client.get("/v1/user/profile", headers=user_headers)
        assert res_prof.status_code == 200
        assert res_prof.json()["passcode"] == "PASS-SARAH-2026"

    def test_reference_search_with_credit_deduction(self, client, auth_headers):
        # 1. Create user with 10 credits and bank account ending 1001
        res_gen = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Search Tester", "custom_code": "PASS-SEARCH-10", "credits": 10},
        )
        passcode = res_gen.json()["passcode"]
        user_headers = {"X-Passcode": passcode}
        client.put("/v1/user/profile", headers=user_headers, json={"account_ending": "1001"})

        # 2. Ingest SMS for 1001
        sms = "Your HSBC Account ********1001 was credited with IPN inward transfer for EGP 500.00 from KHALED with reference REF_SEARCH_101."
        client.post("/v1/webhook/sms", headers=auth_headers, json={"raw_message": sms})

        # 3. Search reference -> deducts 1 credit (balance becomes 9)
        res_search = client.post(
            "/v1/transactions/search",
            headers=user_headers,
            json={"reference_id": "REF_SEARCH_101"},
        )
        assert res_search.status_code == 200
        data = res_search.json()
        assert data["found"] is True
        assert data["credit"]["amount"] == 500.0
        assert data["credits_remaining"] == 9

        # 4. Search non-existent reference -> still deducts 1 credit (balance becomes 8)
        res_search2 = client.post(
            "/v1/transactions/search",
            headers=user_headers,
            json={"reference_id": "NON_EXISTENT_REF"},
        )
        assert res_search2.status_code == 200
        assert res_search2.json()["found"] is False
        assert res_search2.json()["credits_remaining"] == 8

    def test_out_of_credits_rejection(self, client, auth_headers):
        # Create user with 1 credit
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Broke User", "custom_code": "PASS-LOW-1", "credits": 1},
        )
        user_headers = {"X-Passcode": "PASS-LOW-1"}

        # First search consumes the 1 credit
        res1 = client.post("/v1/transactions/search", headers=user_headers, json={"reference_id": "TEST_1"})
        assert res1.status_code == 200

        # Second search fails with 402 Payment Required
        res2 = client.post("/v1/transactions/search", headers=user_headers, json={"reference_id": "TEST_2"})
        assert res2.status_code == 402
        assert "Insufficient search credits" in res2.json()["detail"]

    def test_date_range_filtering_and_csv_export(self, client, auth_headers):
        # 1. Ingest transactions across different dates
        t1 = utc_now() - timedelta(days=5)
        t2 = utc_now() - timedelta(days=1)
        t3 = utc_now()

        client.post("/v1/webhook/sms", headers=auth_headers, json={"raw_message": "تم تحويل مبلغ 100 جم لحسابكم من علي مرجع: DATE_REF_1", "timestamp": t1.isoformat()})
        client.post("/v1/webhook/sms", headers=auth_headers, json={"raw_message": "تم تحويل مبلغ 200 جم لحسابكم من منى مرجع: DATE_REF_2", "timestamp": t2.isoformat()})
        client.post("/v1/webhook/sms", headers=auth_headers, json={"raw_message": "تم تحويل مبلغ 300 جم لحسابكم من هاني مرجع: DATE_REF_3", "timestamp": t3.isoformat()})

        # 2. Filter transactions by date range
        start_date = (date.today() - timedelta(days=2)).isoformat()
        end_date = date.today().isoformat()

        res_filter = client.get(
            f"/v1/transactions/filter?date_from={start_date}&date_to={end_date}",
            headers=auth_headers,
        )
        assert res_filter.status_code == 200
        data = res_filter.json()
        assert data["total"] == 2
        refs = [item["reference_id"] for item in data["items"]]
        assert "DATE_REF_2" in refs
        assert "DATE_REF_3" in refs
        assert "DATE_REF_1" not in refs

        # 3. Export to CSV as Admin (bypasses credit deduction)
        res_csv = client.get(
            f"/v1/transactions/export?date_from={start_date}&date_to={end_date}",
            headers=auth_headers,
        )
        assert res_csv.status_code == 200
        assert "text/csv" in res_csv.headers["content-type"]
        csv_text = res_csv.text
        assert "Reference ID" in csv_text
        assert "DATE_REF_2" in csv_text
        assert "DATE_REF_3" in csv_text

    def test_tab2_5_credits_deduction_and_90day_limit(self, client, auth_headers):
        # 1. Create a user with 25 credits
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Explorer User", "custom_code": "PASS-EXP-10", "credits": 25},
        )
        user_headers = {"X-Passcode": "PASS-EXP-10"}

        # Get the user's allocated forwarder API key from profile
        prof_res = client.get("/v1/user/profile", headers=user_headers)
        fwd_key = prof_res.json()["forwarder_api_key"]

        # 2. Wrong API key -> 403 Forbidden, 0 credits deducted
        res_wrong_key = client.post(
            "/v1/transactions/unlock",
            headers=user_headers,
            json={"forwarder_api_key": "wrong_key_12345"},
        )
        assert res_wrong_key.status_code == 403
        assert "No credits were deducted" in res_wrong_key.json()["detail"]

        # Verify credits are still 25
        prof_check1 = client.get("/v1/user/profile", headers=user_headers)
        assert prof_check1.json()["credits_balance"] == 25

        # 3. Correct API key -> Unlocks successfully, deducts 10 credits (25 -> 15)
        res_unlock = client.post(
            "/v1/transactions/unlock",
            headers=user_headers,
            json={"forwarder_api_key": fwd_key},
        )
        assert res_unlock.status_code == 200
        assert res_unlock.json()["success"] is True
        assert res_unlock.json()["credits_remaining"] == 15

        # 4. Filter query and CSV export do NOT deduct any additional credits (credits remain 15)
        start_date = (date.today() - timedelta(days=10)).isoformat()
        end_date = date.today().isoformat()

        res_filter = client.get(
            f"/v1/transactions/filter?date_from={start_date}&date_to={end_date}",
            headers=user_headers,
        )
        assert res_filter.status_code == 200
        assert res_filter.json()["credits_remaining"] == 15

        res_csv = client.get(
            f"/v1/transactions/export?date_from={start_date}&date_to={end_date}",
            headers=user_headers,
        )
        assert res_csv.status_code == 200

        # Verify credits balance is still 15
        prof_check2 = client.get("/v1/user/profile", headers=user_headers)
        assert prof_check2.json()["credits_balance"] == 15

        # 5. Test 90-day limit rejection
        too_old_date = (date.today() - timedelta(days=95)).isoformat()
        res_old = client.get(
            f"/v1/transactions/filter?date_from={too_old_date}&date_to={end_date}",
            headers=auth_headers,
        )
        assert res_old.status_code == 400
        assert "limited to the last 90 days" in res_old.json()["detail"]

        # 6. Invalid date range (date_from > date_to)
        res_invalid = client.get(
            f"/v1/transactions/filter?date_from={end_date}&date_to={start_date}",
            headers=auth_headers,
        )
        assert res_invalid.status_code == 400
        assert "'Date From' cannot be after 'Date To'" in res_invalid.json()["detail"]

    def test_passcode_redemption_and_topup(self, client, auth_headers):
        # 1. Admin generates code A (User account)
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Renewal User", "custom_code": "PASS-USER-MAIN", "duration_days": 30, "credits": 50},
        )
        user_headers = {"X-Passcode": "PASS-USER-MAIN"}

        # 2. Admin generates code B (Top-up recharge code)
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "TopUp Pack", "custom_code": "RECHARGE-100PTS", "duration_days": 30, "credits": 100},
        )

        # 3. User redeems recharge code
        res_redeem = client.post(
            "/v1/passcodes/redeem",
            headers=user_headers,
            json={"passcode": "RECHARGE-100PTS"},
        )
        assert res_redeem.status_code == 200
        profile = res_redeem.json()
        assert profile["credits_balance"] == 150  # 50 + 100

    def test_merchant_self_service_registration(self, client):
        # 1. Terms & Conditions rejection check (terms_accepted = False)
        res_reject_terms = client.post(
            "/v1/auth/register",
            json={
                "name": "Terms Reject Merchant",
                "email": "reject.terms@example.com",
                "terms_accepted": False,
            },
        )
        assert res_reject_terms.status_code == 422
        assert "Terms and Conditions" in res_reject_terms.text

        # 2. Register new merchant with email and terms accepted
        res_reg = client.post(
            "/v1/auth/register",
            json={
                "name": "New Cairo Store",
                "email": "cairo.store@example.com",
                "phone": "01099887766",
                "account_ending": "1001",
                "terms_accepted": True,
            },
        )
        assert res_reg.status_code == 201
        data = res_reg.json()
        assert data["name"] == "New Cairo Store"
        assert data["email"] == "cairo.store@example.com"
        assert data["passcode"].startswith("PASS-")
        assert len(data["passcode"]) == 14  # PASS-XXXX-XXXX
        assert data["credits_balance"] == 100
        assert data["account_ending"] == "1001"
        assert data["is_subscription_valid"] is True
        assert data.get("terms_accepted") is True

        # 3. Duplicate email registration check
        res_dup = client.post(
            "/v1/auth/register",
            json={"name": "Another Store", "email": "cairo.store@example.com", "terms_accepted": True},
        )
        assert res_dup.status_code == 409

        # 4. Public terms endpoint check
        res_terms = client.get("/v1/terms")
        assert res_terms.status_code == 200
        assert res_terms.json()["governing_law"] == "Arab Republic of Egypt"

    def test_user_profile_update(self, client):
        # 1. Register
        res_reg = client.post(
            "/v1/auth/register",
            json={"name": "Profile Edit User", "email": "prof.edit@example.com"},
        )
        assert res_reg.status_code == 201
        passcode = res_reg.json()["passcode"]
        headers = {"X-Passcode": passcode}

        # 2. Update profile
        res_update = client.put(
            "/v1/user/profile",
            headers=headers,
            json={
                "name": "Profile Edit User Updated",
                "email": "new.email@example.com",
                "phone": "01234567890",
                "account_ending": "5555"
            },
        )
        assert res_update.status_code == 200
        data = res_update.json()
        assert data["name"] == "Profile Edit User Updated"
        assert data["email"] == "new.email@example.com"
        assert data["phone"] == "01234567890"
        assert data["account_ending"] == "5555"

    def test_login_rate_limiting_brute_force_protection(self, client):
        from app.main import login_rate_limiter
        login_rate_limiter.failures.clear()

        # 5 consecutive failed login attempts
        for _ in range(5):
            res = client.post("/v1/auth/passcode/login", json={"passcode": "INVALID_PASSCODE_XYZ"})
            assert res.status_code == 403

        # 6th attempt should be blocked with 429 Too Many Requests
        res_blocked = client.post("/v1/auth/passcode/login", json={"passcode": "INVALID_PASSCODE_XYZ"})
        assert res_blocked.status_code == 429
        assert "Too many failed login attempts" in res_blocked.json()["detail"]
        login_rate_limiter.failures.clear()

    def test_vault_unlock_rate_limiting_brute_force_protection(self, client, auth_headers):
        from app.main import vault_unlock_limiter
        vault_unlock_limiter.failures.clear()

        # Generate a test user
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Vault Rate User", "custom_code": "PASS-VAULT-RATE-01", "credits": 50},
        )
        user_headers = {"X-Passcode": "PASS-VAULT-RATE-01"}

        # 5 consecutive failed vault unlock attempts with wrong key
        for _ in range(5):
            res = client.post(
                "/v1/transactions/unlock",
                headers=user_headers,
                json={"forwarder_api_key": "wrong_key_xyz"},
            )
            assert res.status_code == 403

        # 6th attempt should be blocked with 429 Too Many Requests
        res_blocked = client.post(
            "/v1/transactions/unlock",
            headers=user_headers,
            json={"forwarder_api_key": "wrong_key_xyz"},
        )
        assert res_blocked.status_code == 429
        assert "Too many incorrect key attempts" in res_blocked.json()["detail"]
        vault_unlock_limiter.failures.clear()

    def test_multi_tenant_vault_and_search_isolation(self, client, auth_headers):
        # 1. Register Merchant A ("Demo Merchant", account ending 1001)
        res_a = client.post(
            "/v1/auth/register",
            json={"name": "Demo Merchant", "email": "demo@merchant.com", "account_ending": "1001", "terms_accepted": True},
        )
        assert res_a.status_code == 201
        pass_a = res_a.json()["passcode"]
        fwd_key_a = res_a.json()["forwarder_api_key"]
        headers_a = {"X-Passcode": pass_a}

        # 2. Register Merchant B ("Dirga", account ending 2002)
        res_b = client.post(
            "/v1/auth/register",
            json={"name": "Dirga Store", "email": "dirga@store.com", "account_ending": "2002", "terms_accepted": True},
        )
        assert res_b.status_code == 201
        pass_b = res_b.json()["passcode"]
        fwd_key_b = res_b.json()["forwarder_api_key"]
        headers_b = {"X-Passcode": pass_b}

        # 3. Merchant A's forwarder sends SMS for 15.00 EGP (Ref: 89901E09, Acct: 1001)
        sms_a = "تم تحويل 15.00 جم إلى حسابك 1001 برقم مرجعي 89901E09 بتاريخ اليوم"
        res_sms_a = client.post("/v1/webhook/sms", headers={"X-API-Key": fwd_key_a}, json={"raw_message": sms_a})
        assert res_sms_a.status_code == 201

        # 4. Merchant B's forwarder sends SMS for 50.00 EGP (Ref: DIRGA7777, Acct: 2002)
        sms_b = "تم تحويل 50.00 جم إلى حسابك 2002 برقم مرجعي DIRGA7777 بتاريخ اليوم"
        res_sms_b = client.post("/v1/webhook/sms", headers={"X-API-Key": fwd_key_b}, json={"raw_message": sms_b})
        assert res_sms_b.status_code == 201

        # 5. Merchant B ("Dirga") searches for Merchant A's ref (89901E09) -> MUST NOT MATCH!
        res_search_other = client.post("/v1/transactions/search", headers=headers_b, json={"reference_id": "89901E09"})
        assert res_search_other.status_code == 200
        assert res_search_other.json()["found"] is False  # Isolated!

        # 6. Merchant B ("Dirga") searches for their own ref (DIRGA7777) -> MUST MATCH!
        res_search_own = client.post("/v1/transactions/search", headers=headers_b, json={"reference_id": "DIRGA7777"})
        assert res_search_own.status_code == 200
        assert res_search_own.json()["found"] is True
        assert res_search_own.json()["credit"]["reference_id"] == "DIRGA7777"
        assert res_search_own.json()["already_matched"] is False  # First match!

        # 6b. Merchant B searches for own ref again -> already_matched is True
        res_search_own_again = client.post("/v1/transactions/search", headers=headers_b, json={"reference_id": "DIRGA7777"})
        assert res_search_own_again.status_code == 200
        assert res_search_own_again.json()["found"] is True
        assert res_search_own_again.json()["already_matched"] is True  # Already matched before!

        # 7. Merchant B's Vault -> MUST ONLY contain Dirga's transaction (DIRGA7777)
        res_vault_b = client.get("/v1/transactions/filter", headers=headers_b)
        assert res_vault_b.status_code == 200
        b_items = res_vault_b.json()["items"]
        assert len(b_items) == 1
        assert b_items[0]["reference_id"] == "DIRGA7777"

        # 8. Merchant A searches for their own ref (89901E09) -> Matched!
        res_search_a = client.post("/v1/transactions/search", headers=headers_a, json={"reference_id": "89901E09"})
        assert res_search_a.status_code == 200
        assert res_search_a.json()["found"] is True
        assert res_search_a.json()["already_matched"] is False

        # Merchant A's Vault -> MUST ONLY contain Demo Merchant's transaction (89901E09)
        res_vault_a = client.get("/v1/transactions/filter", headers=headers_a)
        assert res_vault_a.status_code == 200
        a_items = res_vault_a.json()["items"]
        assert len(a_items) == 1
        assert a_items[0]["reference_id"] == "89901E09"

        # 9. Super Admin Vault -> Can view both transactions
        res_vault_admin = client.get("/v1/transactions/filter", headers=auth_headers)
        assert res_vault_admin.status_code == 200
        assert res_vault_admin.json()["total"] >= 2

    def test_statement_summary_and_pdf_export(self, client, auth_headers):
        # 1. Register a merchant for statement testing
        res_reg = client.post(
            "/v1/auth/register",
            json={"name": "Statement Merchant", "email": "stmt@merchant.com", "account_ending": "8899", "terms_accepted": True},
        )
        assert res_reg.status_code == 201
        passcode = res_reg.json()["passcode"]
        fwd_key = res_reg.json()["forwarder_api_key"]
        headers = {"X-Passcode": passcode}

        # 2. Ingest 2 SMS transactions
        sms1 = "تم تحويل 100.00 جم إلى حسابك 8899 برقم مرجعي STMT_REF_01 بتاريخ اليوم"
        sms2 = "تم تحويل 250.00 جم إلى حسابك 8899 برقم مرجعي STMT_REF_02 بتاريخ اليوم"
        client.post("/v1/webhook/sms", headers={"X-API-Key": fwd_key}, json={"raw_message": sms1})
        client.post("/v1/webhook/sms", headers={"X-API-Key": fwd_key}, json={"raw_message": sms2})

        # 3. Get statement summary (does not leak transaction rows)
        res_summary = client.get("/v1/statement/summary", headers=headers)
        assert res_summary.status_code == 200
        summary_data = res_summary.json()
        assert summary_data["total_count"] == 2
        assert summary_data["total_volume"] == 350.0
        assert summary_data["export_fee_credits"] == 10

        # 4. Check initial profile balance (starts with 100 credits)
        res_prof = client.get("/v1/user/profile", headers=headers)
        initial_balance = res_prof.json()["credits_balance"]
        assert initial_balance == 100

        # 5. Export PDF statement with confirm=False -> Fails 400
        res_unconfirmed = client.post("/v1/statement/export/pdf", headers=headers, json={"confirm": False})
        assert res_unconfirmed.status_code == 400

        # 6. Export PDF statement with confirm=True -> Returns PDF and deducts 10 credits
        res_pdf = client.post("/v1/statement/export/pdf", headers=headers, json={"confirm": True})
        assert res_pdf.status_code == 200
        assert res_pdf.headers["Content-Type"] == "application/pdf"
        assert len(res_pdf.content) > 1000
        assert res_pdf.content.startswith(b"%PDF")

        # 7. Check that 10 credits were deducted (balance becomes 90)
        res_prof_after = client.get("/v1/user/profile", headers=headers)
        assert res_prof_after.json()["credits_balance"] == initial_balance - 10

