import pytest
from datetime import datetime, timezone, timedelta
from app.config import settings
from app.parser import redact_sensitive_financial_data, parse_sms, extract_amount_and_currency
from app.models import User, IncomingCredit, CreditTransaction

class TestSensitiveFinancialDataRedaction:

    def test_hsbc_sample_redaction_and_extraction(self):
        msg = "From HSBC: 31DEC25 ELKENAWY FOR TRADING Purchase from 006-109***-001 EGP 81.00- Your available balance is EGP 22,932.71"
        sanitized = redact_sensitive_financial_data(msg)
        assert "22,932.71" not in sanitized
        assert "Your available balance" not in sanitized
        assert "81.00" in sanitized

        amount, currency = extract_amount_and_currency(sanitized)
        assert amount == 81.00
        assert currency == "EGP"

    def test_emirates_misr_card_limit_redaction_and_extraction(self):
        msg = "Your credit card ending with#1525 was charged for EGP 1000.00 at EMIRATES MISR on 08/09/26 at 20:06. Card available limit is EGP 914"
        sanitized = redact_sensitive_financial_data(msg)
        assert "914" not in sanitized
        assert "Card available limit" not in sanitized
        assert "1000.00" in sanitized

        amount, currency = extract_amount_and_currency(sanitized)
        assert amount == 1000.00
        assert currency == "EGP"

    def test_arabic_balance_redaction_and_extraction(self):
        msg = "تم تحويل مبلغ 450.00 جم بنجاح. رصيدك المتاح الحالي هو 8500.50 جم."
        sanitized = redact_sensitive_financial_data(msg)
        assert "8500.50" not in sanitized

        amount, currency = extract_amount_and_currency(sanitized)
        assert amount == 450.00

    def test_arabic_credit_limit_redaction_and_extraction(self):
        msg = "تمت عملية شراء بقيمة 320.00 ج.م. الحد الائتماني المتاح لبطاقتك هو 14200 ج.م."
        sanitized = redact_sensitive_financial_data(msg)
        assert "14200" not in sanitized

        amount, currency = extract_amount_and_currency(sanitized)
        assert amount == 320.00

    def test_full_parse_sms_with_ref_id_redacts_balance(self):
        msg = "From HSBC: Purchase EGP 81.00 Ref: TRX819922 Your available balance is EGP 22,932.71"
        parsed = parse_sms(msg)
        assert parsed.amount == 81.00
        assert parsed.reference_id == "TRX819922"
        assert "22,932.71" not in parsed.raw_message

    def test_webhook_persists_redacted_message(self, client, auth_headers, db_session):
        msg = "From HSBC: Purchase EGP 81.00 Ref: HSBC819922 Your available balance is EGP 22,932.71"
        res = client.post("/v1/webhook/sms", json={"raw_message": msg, "sender": "HSBC"}, headers=auth_headers)
        assert res.status_code == 201

        credit = db_session.query(IncomingCredit).filter(IncomingCredit.reference_id == "HSBC819922").first()
        assert credit is not None
        assert "22,932.71" not in credit.raw_message
        assert credit.amount == 81.00


class TestAdminRegistrationApprovalWorkflow:

    def test_default_registration_is_auto_approved(self, client):
        reg_payload = {
            "name": "Auto Approved Merchant",
            "email": "auto_approved@example.com",
            "phone": "0100000001",
            "terms_accepted": True
        }
        res = client.post("/v1/auth/register", json=reg_payload)
        assert res.status_code == 201
        data = res.json()
        assert data["approval_status"] == "APPROVED"
        assert data["is_active"] is True
        assert data["is_subscription_valid"] is True

        # Passcode login succeeds immediately
        login_res = client.post("/v1/auth/passcode/login", json={"passcode": data["passcode"]})
        assert login_res.status_code == 200
        assert login_res.json()["approval_status"] == "APPROVED"

    def test_registration_approval_lifecycle(self, client, auth_headers, db_session):
        # 1. Super Admin enables require_merchant_approval
        settings_res = client.post(
            "/v1/admin/settings",
            json={
                "admin_key": settings.MASTER_API_KEY,
                "instapay_handle": "haitham@instapay",
                "require_merchant_approval": True
            },
            headers=auth_headers
        )
        assert settings_res.status_code == 200
        assert settings_res.json()["require_merchant_approval"] is True

        # Public config reflects this
        pub_res = client.get("/v1/settings/public")
        assert pub_res.status_code == 200
        assert pub_res.json()["require_merchant_approval"] is True

        # 2. New Merchant registers
        reg_payload = {
            "name": "Pending Merchant Shop",
            "email": "pending_shop@example.com",
            "phone": "0109999999",
            "terms_accepted": True
        }
        reg_res = client.post("/v1/auth/register", json=reg_payload)
        assert reg_res.status_code == 201
        reg_data = reg_res.json()
        merchant_id = reg_data["id"]
        merchant_passcode = reg_data["passcode"]
        assert reg_data["approval_status"] == "PENDING"
        assert reg_data["is_active"] is False

        # 3. Attempting login before approval fails with informative 403
        login_res = client.post("/v1/auth/passcode/login", json={"passcode": merchant_passcode})
        assert login_res.status_code == 403
        assert "pending Super Admin approval" in login_res.json()["detail"]

        # 4. Super Admin lists users and verifies PENDING status
        list_res = client.get("/v1/admin/users/list", headers=auth_headers)
        assert list_res.status_code == 200
        users_list = list_res.json()["users"]
        target = next((u for u in users_list if u["id"] == merchant_id), None)
        assert target is not None
        assert target["approval_status"] == "PENDING"

        # 5. Super Admin Approves merchant
        appr_res = client.post(f"/v1/admin/users/{merchant_id}/approve", headers=auth_headers)
        assert appr_res.status_code == 200
        appr_data = appr_res.json()
        assert appr_data["approval_status"] == "APPROVED"
        assert appr_data["is_active"] is True
        assert appr_data["is_subscription_valid"] is True

        # Trial expiration is in the future
        exp_str = appr_data["subscription_expires_at"].replace("Z", "")
        if "+" in exp_str:
            exp_str = exp_str.split("+")[0]
        exp_dt = datetime.fromisoformat(exp_str)
        assert exp_dt > datetime.utcnow() + timedelta(days=170)

        # Audit transaction exists
        audit_tx = db_session.query(CreditTransaction).filter(
            CreditTransaction.user_id == merchant_id,
            CreditTransaction.operation_type == "MERCHANT_ADMIN_APPROVED"
        ).first()
        assert audit_tx is not None

        # 6. Merchant can now login successfully
        login_after_appr = client.post("/v1/auth/passcode/login", json={"passcode": merchant_passcode})
        assert login_after_appr.status_code == 200
        assert login_after_appr.json()["approval_status"] == "APPROVED"
        assert login_after_appr.json()["is_active"] is True

    def test_registration_rejection(self, client, auth_headers):
        # 1. Enable require_merchant_approval
        client.post(
            "/v1/admin/settings",
            json={
                "admin_key": settings.MASTER_API_KEY,
                "require_merchant_approval": True
            },
            headers=auth_headers
        )

        # 2. Register merchant
        reg_payload = {
            "name": "To Be Rejected Shop",
            "email": "rejected_shop@example.com",
            "phone": "0108888888",
            "terms_accepted": True
        }
        reg_res = client.post("/v1/auth/register", json=reg_payload)
        reg_data = reg_res.json()
        merchant_id = reg_data["id"]
        merchant_passcode = reg_data["passcode"]

        # 3. Super Admin Rejects merchant
        rej_res = client.post(f"/v1/admin/users/{merchant_id}/reject", headers=auth_headers)
        assert rej_res.status_code == 200
        assert rej_res.json()["approval_status"] == "REJECTED"
        assert rej_res.json()["is_active"] is False

        # 4. Login returns 403 rejected message
        login_res = client.post("/v1/auth/passcode/login", json={"passcode": merchant_passcode})
        assert login_res.status_code == 403
        assert "not approved" in login_res.json()["detail"]
