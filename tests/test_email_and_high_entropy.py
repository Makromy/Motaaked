import pytest
from app.services import generate_high_entropy_passcode, validate_passcode_strength
from app.email_service import send_welcome_email, send_forgot_passcode_email, send_forwarder_setup_email
from fastapi import HTTPException


class TestEmailAndHighEntropyPasscodes:
    def test_high_entropy_passcode_format(self):
        codes = [generate_high_entropy_passcode() for _ in range(50)]
        for code in codes:
            assert code.startswith("PASS-")
            parts = code.split("-")
            assert len(parts) == 3
            assert len(parts[1]) == 4
            assert len(parts[2]) == 4
            assert parts[1].isalnum()
            assert parts[2].isalnum()
        # Ensure all 50 generated codes are distinct
        assert len(set(codes)) == 50

    def test_weak_passcode_rejection(self):
        weak_list = ["1234", "demo", "test", "pass", "admin", "1111", "pass-1234", "123"]
        for weak in weak_list:
            with pytest.raises(HTTPException) as exc_info:
                validate_passcode_strength(weak)
            assert exc_info.value.status_code == 400
            assert "Weak passcodes are not allowed" in exc_info.value.detail

    def test_strong_passcode_acceptance(self):
        # Valid strong custom passcodes should not raise
        validate_passcode_strength("PASS-SECURE-9988")
        validate_passcode_strength("MERCHANT-2026-X")

    def test_email_service_templates_rendering(self):
        # Test welcome email rendering
        assert send_welcome_email(
            to_email="test@merchant.com",
            user_name="Test Merchant",
            passcode="PASS-9F8E-2B4A",
            forwarder_key="instapay_live_abcdef0123456789",
            server_url="http://192.168.1.10:8000"
        ) is True

        # Test forgot passcode email rendering
        assert send_forgot_passcode_email(
            to_email="test@merchant.com",
            user_name="Test Merchant",
            passcode="PASS-9F8E-2B4A",
            forwarder_key="instapay_live_abcdef0123456789",
            server_url="http://192.168.1.10:8000"
        ) is True

        # Test forwarder setup email rendering
        assert send_forwarder_setup_email(
            to_email="test@merchant.com",
            user_name="Test Merchant",
            forwarder_key="instapay_live_abcdef0123456789",
            server_url="http://192.168.1.10:8000"
        ) is True

    def test_forgot_passcode_api_endpoint(self, client):
        from app.main import login_rate_limiter
        login_rate_limiter.failures.clear()

        # 1. Register a merchant
        res_reg = client.post(
            "/v1/auth/register",
            json={
                "name": "Recovery Test Merchant",
                "email": "recovery@merchant.com",
            },
        )
        assert res_reg.status_code == 201

        # 2. Request recovery for registered email
        res_rec = client.post(
            "/v1/auth/forgot-passcode",
            json={"email": "recovery@merchant.com"},
        )
        assert res_rec.status_code == 200
        assert res_rec.json()["success"] is True

        # 3. Request recovery for unknown email (should still return success for security against enumeration)
        res_unk = client.post(
            "/v1/auth/forgot-passcode",
            json={"email": "unknown@domain.com"},
        )
        assert res_unk.status_code == 200
        assert res_unk.json()["success"] is True

    def test_send_forwarder_setup_email_api(self, client):
        # 1. Register
        res_reg = client.post(
            "/v1/auth/register",
            json={
                "name": "Setup Dispatch Merchant",
                "email": "setup.dispatch@merchant.com",
            },
        )
        assert res_reg.status_code == 201
        passcode = res_reg.json()["passcode"]
        headers = {"X-Passcode": passcode}

        # 2. Trigger send setup email (First attempt should succeed)
        res_send = client.post(
            "/v1/user/send-setup-email",
            headers=headers,
            json={"server_url": "http://192.168.1.15:8000"},
        )
        assert res_send.status_code == 200
        assert res_send.json()["success"] is True
        assert "setup.dispatch@merchant.com" in res_send.json()["message"]

        # 3. Immediate second attempt should be blocked by 60s cooldown (429 Too Many Requests)
        res_cooldown = client.post(
            "/v1/user/send-setup-email",
            headers=headers,
            json={"server_url": "http://192.168.1.15:8000"},
        )
        assert res_cooldown.status_code == 429
        assert "Please wait" in res_cooldown.json()["detail"]

    def test_login_by_email_passcode_and_api_key(self, client, auth_headers):
        # 1. Register user
        res_reg = client.post(
            "/v1/auth/register",
            json={
                "name": "Dual Login Merchant",
                "email": "dual.login@merchant.com",
            },
        )
        assert res_reg.status_code == 201
        reg_data = res_reg.json()
        passcode = reg_data["passcode"]
        fwd_key = reg_data["forwarder_api_key"]

        # 2. Login using Passcode (Succeeds)
        res_login_pass = client.post(
            "/v1/auth/passcode/login",
            json={"passcode": passcode},
        )
        assert res_login_pass.status_code == 200
        assert res_login_pass.json()["email"] == "dual.login@merchant.com"

        # 3. Login using raw Email address (Rejected with 403 - Strict credential enforcement)
        res_login_email = client.post(
            "/v1/auth/passcode/login",
            json={"passcode": "dual.login@merchant.com"},
        )
        assert res_login_email.status_code == 403
        assert "Invalid or inactive Access Passcode" in res_login_email.json()["detail"]

        # 4. Login using Dedicated Forwarder API Key (Succeeds)
        res_login_key = client.post(
            "/v1/auth/passcode/login",
            json={"passcode": fwd_key},
        )
        assert res_login_key.status_code == 200
        assert res_login_key.json()["name"] == "Dual Login Merchant"

        # 5. Access profile with X-API-Key header instead of X-Passcode
        res_prof_key = client.get("/v1/user/profile", headers={"X-API-Key": fwd_key})
        assert res_prof_key.status_code == 200
        assert res_prof_key.json()["email"] == "dual.login@merchant.com"

        # 6. Access profile with X-Passcode header
        res_prof_pass = client.get("/v1/user/profile", headers={"X-Passcode": passcode})
        assert res_prof_pass.status_code == 200
        assert res_prof_pass.json()["name"] == "Dual Login Merchant"

    def test_dynamic_email_from_and_reply_to_header(self, monkeypatch):
        from app.email_service import _send_smtp_email
        import smtplib

        sent_messages = []

        class MockSMTP:
            def __init__(self, *args, **kwargs):
                pass
            def starttls(self):
                pass
            def login(self, u, p):
                pass
            def sendmail(self, envelope_from, recipients, msg_bytes):
                sent_messages.append((envelope_from, recipients, msg_bytes))
            def quit(self):
                pass

        monkeypatch.setattr("app.config.settings.SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr("app.config.settings.SMTP_USER", "haitham.refaat@gmail.com")
        monkeypatch.setattr("app.config.settings.SMTP_PASSWORD", "secret")
        monkeypatch.setattr("app.config.settings.SMTP_FROM", "OldPortal <haitham.refaat@gmail.com>")
        monkeypatch.setattr(smtplib, "SMTP", MockSMTP)

        # 1. Test with English brand name (e.g. InstaTakeed)
        monkeypatch.setattr("app.email_service._get_portal_name", lambda: "InstaTakeed")
        ok, err, sim = _send_smtp_email("user@test.com", "Test Subject", "<p>Hello</p>")
        assert ok is True
        assert len(sent_messages) == 1
        env_from, recipients, raw = sent_messages[0]
        assert env_from == "haitham.refaat@gmail.com"
        assert recipients == ["user@test.com"]
        raw_str = raw.decode("utf-8")
        assert "From: InstaTakeed <haitham.refaat@gmail.com>" in raw_str
        assert "Reply-To: InstaTakeed <haitham.refaat@gmail.com>" in raw_str

        # 2. Test with Arabic brand name
        sent_messages.clear()
        monkeypatch.setattr("app.email_service._get_portal_name", lambda: "إنستاتأكيد")
        ok, err, sim = _send_smtp_email("user@test.com", "Test Arabic", "<p>مرحبا</p>")
        assert ok is True
        assert len(sent_messages) == 1
        env_from, recipients, raw = sent_messages[0]
        assert env_from == "haitham.refaat@gmail.com"
        raw_str = raw.decode("utf-8")
        assert "<haitham.refaat@gmail.com>" in raw_str
        assert "Reply-To:" in raw_str

    def test_dynamic_env_file_reload_at_runtime(self, monkeypatch):
        """
        Tests that when .env is updated on disk (e.g. via aaPanel editor),
        the email service dynamically picks up the new SMTP_FROM and PORTAL_NAME
        without requiring a Python process restart.
        """
        import smtplib
        from app.email_service import _send_smtp_email

        sent_messages = []

        class MockSMTP:
            def __init__(self, *args, **kwargs):
                pass
            def starttls(self):
                pass
            def login(self, u, p):
                pass
            def sendmail(self, envelope_from, recipients, msg_bytes):
                sent_messages.append((envelope_from, recipients, msg_bytes))
            def quit(self):
                pass

        monkeypatch.setattr(smtplib, "SMTP", MockSMTP)
        # Mock .env file on disk returning updated values
        mock_env_data = {
            "SMTP_HOST": "smtp-relay.brevo.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "ha3d52001@smtp-brevo.com",
            "SMTP_PASSWORD": "secret_pass",
            "SMTP_FROM": '"saf7etna@gmail.com"',
            "PORTAL_NAME": '"InstaTakeed"',
        }
        monkeypatch.setattr("dotenv.dotenv_values", lambda *args, **kwargs: mock_env_data)

        # Disallow reading from old frozen settings
        monkeypatch.setattr("app.config.settings.SMTP_FROM", "haitham.refaat@gmail.com")

        ok, err, sim = _send_smtp_email("recipient@example.com", "Subject", "<p>Body</p>")
        assert ok is True
        assert len(sent_messages) == 1
        env_from, recipients, raw = sent_messages[0]
        assert env_from == "saf7etna@gmail.com"
        assert recipients == ["recipient@example.com"]
        raw_str = raw.decode("utf-8")
        assert "From: InstaTakeed <saf7etna@gmail.com>" in raw_str
        assert "Reply-To: InstaTakeed <saf7etna@gmail.com>" in raw_str

    def test_admin_smtp_settings_and_test_endpoint(self, client, db_session, monkeypatch):
        """
        Tests configuring SMTP parameters via POST /v1/admin/settings
        and validating the POST /v1/admin/test-smtp diagnostic endpoint.
        """
        import smtplib
        from app.config import settings

        class MockSMTP:
            def __init__(self, *args, **kwargs):
                pass
            def ehlo(self):
                pass
            def starttls(self):
                pass
            def login(self, u, p):
                pass
            def sendmail(self, envelope_from, recipients, msg_bytes):
                pass
            def quit(self):
                pass

        monkeypatch.setattr(smtplib, "SMTP", MockSMTP)

        # 1. Update SMTP via Admin Settings
        resp = client.post(
            "/v1/admin/settings",
            json={
                "admin_key": settings.MASTER_API_KEY,
                "smtp_host": "smtp-relay.brevo.com",
                "smtp_port": 2525,
                "smtp_user": "brevo_user_test",
                "smtp_password": "brevo_password_test",
                "smtp_from": "saf7etna@gmail.com",
            },
            headers={"X-API-Key": settings.MASTER_API_KEY}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["smtp_host"] == "smtp-relay.brevo.com"
        assert data["smtp_port"] == 2525
        assert data["smtp_user"] == "brevo_user_test"
        assert data["smtp_from"] == "saf7etna@gmail.com"

        # 2. Test SMTP endpoint with invalid admin key -> 403
        resp_bad_auth = client.post(
            "/v1/admin/test-smtp",
            json={"admin_key": "wrong-key"}
        )
        assert resp_bad_auth.status_code == 403

        # 3. Test SMTP endpoint with valid admin key -> 200
        resp_test = client.post(
            "/v1/admin/test-smtp",
            json={
                "admin_key": settings.MASTER_API_KEY,
                "test_recipient": "test@example.com",
            }
        )
        assert resp_test.status_code == 200
        assert resp_test.json()["success"] is True


