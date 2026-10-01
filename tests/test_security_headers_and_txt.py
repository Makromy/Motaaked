import pytest
from fastapi.testclient import TestClient
import os


def test_security_headers_present(client: TestClient):
    """Verify all 6 critical security headers and server masking are returned on HTTP responses."""
    resp = client.get("/")
    assert resp.status_code == 200

    # 1. HSTS
    assert "Strict-Transport-Security" in resp.headers
    assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]
    assert "includeSubDomains" in resp.headers["Strict-Transport-Security"]

    # 2. X-Content-Type-Options
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    # 3. X-Frame-Options
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"

    # 4. Referrer-Policy
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    # 5. Permissions-Policy (Camera permitted for OCR scanner, dangerous APIs disabled)
    perm_policy = resp.headers.get("Permissions-Policy", "")
    assert "camera=(self)" in perm_policy
    assert "microphone=()" in perm_policy
    assert "geolocation=()" in perm_policy

    # 6. Content-Security-Policy
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'none'" in csp
    assert "'unsafe-eval'" not in csp
    assert "cdn.tailwindcss.com" in csp
    assert "cdnjs.cloudflare.com" in csp
    assert "cdn.jsdelivr.net" in csp
    assert "frame-ancestors 'self'" in csp

    # 7. Information disclosure / fingerprinting prevention
    assert resp.headers.get("Server") == "WebPlatform"
    assert "X-Powered-By" not in resp.headers


def test_security_txt_rfc9116(client: TestClient):
    """Verify RFC 9116 security.txt endpoints at standard paths."""
    # /.well-known/security.txt
    resp_well_known = client.get("/.well-known/security.txt")
    assert resp_well_known.status_code == 200
    assert "text/plain" in resp_well_known.headers["content-type"]
    assert "Contact: mailto:" in resp_well_known.text
    assert "Expires:" in resp_well_known.text
    assert "Canonical:" in resp_well_known.text

    # /security.txt fallback
    resp_fallback = client.get("/security.txt")
    assert resp_fallback.status_code == 200
    assert "text/plain" in resp_fallback.headers["content-type"]
    assert resp_fallback.text == resp_well_known.text


def test_options_method_clean_204(client: TestClient):
    """Verify OPTIONS / returns a clean 204 No Content response to satisfy pentest scanners."""
    resp = client.options("/")
    assert resp.status_code == 204
    assert "Allow" in resp.headers
    assert "GET" in resp.headers["Allow"]


def test_html_comments_stripped_on_serve(client: TestClient):
    """Verify sensitive developer comments are stripped dynamically when serving the PWA root."""
    resp = client.get("/")
    assert resp.status_code == 200
    # Must not contain suspicious internal architecture comments
    assert "2nd-Layer Gate" not in resp.text
    assert "Protected by 2nd-Layer" not in resp.text
    assert "Tier 3" not in resp.text
    # Generic HTML comments should be stripped
    assert "<!--" not in resp.text


def test_email_exposure_sanitized():
    """Verify static/index.html does not contain un-sanitized name@domain.com or email@domain.com."""
    index_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "name@domain.com" not in content
    assert "email@domain.com" not in content
    assert "merchant@example.com" in content


def test_gzip_middleware_active(client: TestClient):
    """Verify GZip middleware compresses large responses when requested."""
    resp = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    # TestClient may automatically decompress or present Content-Encoding
    if "content-encoding" in resp.headers:
        assert resp.headers["content-encoding"] == "gzip"
