import pytest
from app.config import settings
from app.models import User, ApiKey, utc_now


class TestAdminSecurityGate:

    def test_gate_accepts_super_admin_master_key(self, client, auth_headers):
        res = client.post("/v1/admin/gate/verify", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["valid"] is True

    def test_gate_rejects_admin_user_passcode(self, client, db_session):
        # Create an admin user with a passcode
        admin_user = User(
            name="Admin Merchant",
            passcode="PASS-SUPER-ADMIN-2026",
            role="admin",
            credits_balance=100,
            subscription_expires_at=utc_now(),
            is_active=True
        )
        db_session.add(admin_user)
        db_session.commit()

        # Try to use this admin user passcode on 2nd-layer gate
        res = client.post("/v1/admin/gate/verify", headers={"X-API-Key": "PASS-SUPER-ADMIN-2026"})
        assert res.status_code == 403
        data = res.json()
        assert "Account passcodes cannot be used" in data["detail"]

    def test_gate_rejects_regular_merchant_passcode(self, client, db_session):
        # Create regular user
        user = User(
            name="Demo Merchant",
            passcode="PASS-MERCHANT-999",
            role="user",
            credits_balance=50,
            subscription_expires_at=utc_now(),
            is_active=True
        )
        db_session.add(user)
        db_session.commit()

        # Try to use regular merchant passcode on 2nd-layer gate
        res = client.post("/v1/admin/gate/verify", headers={"X-API-Key": "PASS-MERCHANT-999"})
        assert res.status_code == 403
        data = res.json()
        assert "Account passcodes cannot be used" in data["detail"]

    def test_gate_rejects_invalid_random_key(self, client):
        res = client.post("/v1/admin/gate/verify", headers={"X-API-Key": "invalid_random_key_12345"})
        assert res.status_code == 403
        data = res.json()
        assert "Invalid Super Admin API Key" in data["detail"]
