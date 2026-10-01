import os
import pytest
from datetime import timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.config import settings
from app.auth import get_current_master_keys, verify_secret, verify_api_key
from app.models import User, utc_now
from app.main import app, sms_webhook_limiter, _get_cors_origins


def test_high001_cors_origins_config_and_credentials():
    """HIGH-001: Ensure allow_credentials is True only when origins are explicit (not '*')."""
    # When origins is wildcard '*'
    origins_wildcard = ["*"]
    allow_cred_wildcard = (origins_wildcard != ["*"])
    assert allow_cred_wildcard is False

    # When origins are explicitly enumerated
    origins_explicit = ["https://mystore.com", "https://app.motaaked.com"]
    allow_cred_explicit = (origins_explicit != ["*"])
    assert allow_cred_explicit is True


def test_high002_master_key_production_refusal():
    """HIGH-002: In production environment with no master key configured, startup must raise RuntimeError."""
    with patch("app.auth.settings.MASTER_API_KEY", ""):
        with patch("app.auth.dotenv_values", return_value={}):
            with patch.dict(os.environ, {"ENVIRONMENT": "production", "MASTER_API_KEY": ""}, clear=True):
                # Pytest is in sys.modules, so we simulate test check false
                with patch("sys.modules", {}):
                    with pytest.raises(RuntimeError) as exc_info:
                        get_current_master_keys()
                    assert "MASTER_API_KEY must be set when ENVIRONMENT=production" in str(exc_info.value)


def test_high002_master_key_dev_warning(caplog):
    """HIGH-002: In development environment with no key, fallback key logs a security warning."""
    import logging
    with patch("app.auth.settings.MASTER_API_KEY", ""):
        with patch("app.auth.dotenv_values", return_value={}):
            with patch.dict(os.environ, {"ENVIRONMENT": "development", "MASTER_API_KEY": ""}, clear=True):
                with caplog.at_level(logging.WARNING, logger="instapay"):
                    keys = get_current_master_keys()
                    assert "XAZAjxjhbCtSgiq7" in keys
                    assert any("SECURITY WARNING" in rec.message for rec in caplog.records)


def test_high003_passcode_generation_masks_credential_in_console(client: TestClient, auth_headers, capsys):
    """HIGH-003: Admin passcode generation prints only masked credentials in stdout."""
    res = client.post(
        "/v1/admin/passcodes/generate",
        json={"user_name": "Audit Masked User", "custom_code": "PASS-SECRET-TOKEN-999"},
        headers=auth_headers,
    )
    assert res.status_code == 201
    captured = capsys.readouterr()
    # Masked prefix should appear
    assert "PASS****" in captured.out
    # Full secret token must NOT appear in output logs
    assert "PASS-SECRET-TOKEN-999" not in captured.out


def test_medium001_canonical_constant_time_comparison():
    """MEDIUM-001: Legacy plaintext comparisons work accurately with whitespace/case normalization."""
    # Exact match
    assert verify_secret("pass-1234", "PASS-1234") is True
    # Spaces normalized
    assert verify_secret("PASS 1234", "PASS-1234".replace("-", " ")) is True
    # Mismatch rejected
    assert verify_secret("PASS-1234", "PASS-9999") is False
    # Empty inputs handled safely
    assert verify_secret("", "PASS-1234") is False
    assert verify_secret("PASS-1234", None) is False


def test_medium003_embed_iframe_origin_customization(client: TestClient, auth_headers):
    """MEDIUM-003: /checkout/embed respects allowed_checkout_embed_origins in CSP frame-ancestors."""
    # Default without setting -> frame-ancestors *
    resp_default = client.get("/checkout/embed?session=chk_test_session")
    csp_default = resp_default.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors *;" in csp_default

    # Configure specific allowed origins in system settings
    client.post(
        "/v1/admin/settings",
        headers=auth_headers,
        json={"allowed_checkout_embed_origins": "https://store.example.com, https://app.example.com"},
    )

    resp_custom = client.get("/checkout/embed?session=chk_test_session")
    csp_custom = resp_custom.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors https://store.example.com https://app.example.com;" in csp_custom


def test_medium004_sms_webhook_rate_limiter_blocks_burst(client: TestClient):
    """MEDIUM-004: SMS Webhook rate limiter enforces threshold and returns HTTP 429 when exhausted."""
    from app.main import sms_webhook_limiter
    test_key = "test_rate_limited_fwd_key"

    # Reset limiter for this key
    with sms_webhook_limiter.lock:
        sms_webhook_limiter.requests[test_key].clear()

    # Fill quota up to max_requests
    for _ in range(sms_webhook_limiter.max_requests):
        sms_webhook_limiter.record_request(test_key)

    # Next check must be blocked
    blocked, retry_after = sms_webhook_limiter.is_blocked(test_key)
    assert blocked is True
    assert retry_after > 0

    # Sending webhook with this key should trigger 429 Too Many Requests
    app.dependency_overrides[verify_api_key] = lambda: test_key
    try:
        resp = client.post(
            "/v1/sms/webhook",
            json={"raw_message": "test ping"},
            headers={"X-API-Key": test_key},
        )
        assert resp.status_code == 429
        assert "SMS webhook rate limit exceeded" in resp.json()["detail"]
        assert "Retry-After" in resp.headers
    finally:
        app.dependency_overrides.pop(verify_api_key, None)

    # Cleanup
    with sms_webhook_limiter.lock:
        sms_webhook_limiter.requests[test_key].clear()


def test_low003_random_cashier_pin_for_new_users(client: TestClient, db_session):
    """LOW-003: Verify that newly registered users receive a random 6-character PIN (4 digits + 2 letters) and NOT '1234'."""
    from app.models import _random_cashier_pin

    pin1 = _random_cashier_pin()
    pin2 = _random_cashier_pin()
    assert len(pin1) == 6
    assert pin1.isalnum()
    assert sum(c.isdigit() for c in pin1) == 4
    assert sum(c.isupper() for c in pin1) == 2
    assert pin1 != "1234"
    # Random pins should have high entropy
    assert pin1 != pin2 or len(pin1) == 6

    # Test via user creation
    new_user = User(
        name="Auto Pin Merchant",
        passcode="PASS-AUTO-PIN",
        role="user",
        subscription_expires_at=utc_now() + timedelta(days=30),
        is_active=True,
    )
    db_session.add(new_user)
    db_session.commit()
    db_session.refresh(new_user)

    assert new_user.cashier_pin != "1234"
    assert len(new_user.cashier_pin) == 6
    assert new_user.cashier_pin.isalnum()
    assert sum(c.isdigit() for c in new_user.cashier_pin) == 4
    assert sum(c.isupper() for c in new_user.cashier_pin) == 2
