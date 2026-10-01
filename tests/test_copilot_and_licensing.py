import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

client = TestClient(app)


def test_license_file_bsl11():
    """Verify official BSL 1.1 LICENSE file exists with exact required parameters."""
    license_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "LICENSE")
    assert os.path.exists(license_path), "LICENSE file must exist in repository root"

    with open(license_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Business Source License 1.1" in content
    assert "Haitham Refaat" in content
    assert "2030-01-01" in content
    assert "GPL-3.0" in content
    # Verify permitted uses
    assert "Free self-hosting" in content or "self-hosting" in content.lower()
    assert "Personal study" in content or "learning" in content.lower()
    assert "plugins" in content.lower()
    # Verify prohibited uses
    assert "white-label" in content.lower()
    assert "Software-as-a-Service" in content or "SaaS" in content
    assert "saf7etna@gmail.com" in content


def test_commercial_license_agreement_template():
    """Verify enterprise commercial contract template is safely archived and not leaked in public root."""
    archive_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archive", "COMMERCIAL_LICENSE_AGREEMENT.md")
    assert os.path.exists(archive_path), "COMMERCIAL_LICENSE_AGREEMENT.md must exist in private archive/ directory"

    root_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "COMMERCIAL_LICENSE_AGREEMENT.md")
    assert not os.path.exists(root_path), "COMMERCIAL_LICENSE_AGREEMENT.md must NOT exist in public repository root"

    with open(archive_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Haitham Refaat" in content
    assert "Cairo Economic Court" in content or "المحكمة الاقتصادية بالقاهرة" in content
    assert "Law No. 82 of 2002" in content or "82 لسنة 2002" in content
    assert "WHITE-LABEL" in content.upper()


def test_readme_open_source_policy():
    """Verify README.md contains BSL 1.1 open-source policy without leaking secret easter egg."""
    readme_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
    assert os.path.exists(readme_path)

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Business Source License 1.1 (BSL 1.1)" in content
    assert "Free Self-Hosting" in content
    assert "White-Labeling & Reselling" in content
    assert "Competing Commercial SaaS" in content
    assert "saf7etna@gmail.com" in content

    # Crucial secrecy constraint: The secret 10-tap easter egg and national ID must NEVER be in README or LICENSE!
    assert "28103270102874" not in content, "National ID must not be leaked in public README"
    assert "10 times" not in content.lower(), "Secret trigger must not be documented in README"


def test_secret_ownership_modal_in_index_html():
    """Verify secret proof of ownership modal & trigger are embedded in static/index.html."""
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "index.html")
    assert os.path.exists(html_path)

    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "btn-watchlist-secret-trigger" in content
    assert "handleWatchlistSecretClick" in content
    assert "modal-secret-ownership" in content
    assert "28103270102874" in content
    assert "Haitham Refaat" in content


def test_copilot_chat_e_commerce():
    """Test AI Copilot responses for e-commerce integration queries."""
    res = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "كيف أربط المنصة مع ووكومرس WooCommerce؟", "language": "ar"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "reply" in data
    assert "ووكومرس" in data["reply"] or "WooCommerce" in data["reply"]
    assert "Drop-In" in data["reply"] or "motaaked-checkout.js" in data["reply"]
    assert len(data.get("suggestions", [])) > 0


def test_copilot_chat_bank_sms_reference():
    """Test AI Copilot explains Bank SMS Reference ID vs Screenshot principle."""
    res = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "Why can't I use customer app screenshots for payment verification?", "language": "en"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "Bank SMS Reference ID" in data["reply"] or "SMS" in data["reply"]
    assert "screenshot" in data["reply"].lower()


def test_copilot_chat_forwarder():
    """Test AI Copilot forwarder status query."""
    res = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "ما هي خطوات تثبيت تطبيق تحويل الرسائل أندرويد؟", "language": "ar"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "SMS Forwarder" in data["reply"] or "تحويل" in data["reply"]


def test_copilot_chat_limits():
    """Test AI Copilot returns Motaaked pricing/credits and banking limits clarification without statutory transfer limits."""
    res = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "What are the InstaPay transaction limits and fees?", "language": "en"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "Motaaked" in data["reply"]
    assert "70,000" not in data["reply"]
    assert "120,000" not in data["reply"]
    assert "400,000" not in data["reply"]


def test_copilot_admin_toggle_and_enforcement():
    """Test toggling copilot_widget_enabled off and on via admin settings."""
    master_key = settings.MASTER_API_KEY or "instapay_secret_master_key_2026"
    headers = {"X-Admin-Key": master_key, "X-API-Key": master_key}

    # 1. Disable Copilot
    res_update = client.post(
        "/v1/admin/settings",
        headers=headers,
        json={"copilot_widget_enabled": False, "admin_key": master_key},
    )
    assert res_update.status_code == 200
    assert res_update.json()["copilot_widget_enabled"] is False

    # 2. Check public status & config
    res_status = client.get("/v1/ai/copilot/status")
    assert res_status.status_code == 200
    assert res_status.json()["enabled"] is False

    res_public = client.get("/v1/portal/config")
    assert res_public.status_code == 200
    assert res_public.json()["copilot_widget_enabled"] is False

    # 3. Chat request should be blocked with 403 Forbidden
    res_chat = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "Hello copilot"},
    )
    assert res_chat.status_code == 403
    assert "disabled" in res_chat.json()["detail"].lower()

    # 4. Re-enable Copilot
    res_reenable = client.post(
        "/v1/admin/settings",
        headers=headers,
        json={"copilot_widget_enabled": True, "admin_key": master_key},
    )
    assert res_reenable.status_code == 200
    assert res_reenable.json()["copilot_widget_enabled"] is True

    # 5. Chat request should succeed again
    res_chat_ok = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "Hello copilot"},
    )
    assert res_chat_ok.status_code == 200
    assert "reply" in res_chat_ok.json()


def test_copilot_developer_guide_grounding():
    """Verify that updated Q&A from DEVELOPER_INTEGRATION_GUIDE.md is reflected in AI Copilot responses."""
    # Q2 (Privacy & SMS Filters): English
    res_en = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "Does this portal read all the SMS messages on my phone?", "language": "en"},
    )
    assert res_en.status_code == 200
    data_en = res_en.json()
    assert "DEVELOPER_INTEGRATION_GUIDE.md" in data_en.get("sources", [])
    assert "webhook" in data_en["reply"].lower() or "filter" in data_en["reply"].lower()

    # Q2 (Privacy & SMS Filters): Arabic
    res_ar = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "هل تقرأ البوابة جميع رسائل الـ SMS على هاتفي؟", "language": "ar"},
    )
    assert res_ar.status_code == 200
    data_ar = res_ar.json()
    assert "DEVELOPER_INTEGRATION_GUIDE.md" in data_ar.get("sources", [])
    assert "لا تقرأ" in data_ar["reply"] or "فلتر" in data_ar["reply"]

    # Q3 (Unlisted Bank): English
    res_q3 = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "What should I do if my bank is not listed in active banks?", "language": "en"},
    )
    assert res_q3.status_code == 200
    assert "Support" in res_q3.json()["reply"] or "Ticket" in res_q3.json()["reply"]

    # Q13 (Underpayment / Overpayment): Arabic
    res_q13 = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "ماذا يحدث إذا حول العميل مبلغاً منقوصاً أو غير مطابق؟", "language": "ar"},
    )
    assert res_q13.status_code == 200
    assert "UNCLAIMED" in res_q13.json()["reply"] or "المطابقة التامة" in res_q13.json()["reply"]

    # Q14 (Replay Attacks / Double Spending): English
    res_q14 = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "Can the same Bank SMS Reference ID be used twice for different orders?", "language": "en"},
    )
    assert res_q14.status_code == 200
    assert "CLAIMED" in res_q14.json()["reply"] or "atomic" in res_q14.json()["reply"].lower()

    # Q18 (Testing in Local Development): Arabic
    res_q18 = client.post(
        "/v1/ai/copilot/chat",
        json={"message": "كيف أختبر دورة الدفع الكاملة في بيئة التطوير المحلية؟", "language": "ar"},
    )
    assert res_q18.status_code == 200
    assert "localhost:8000" in res_q18.json()["reply"] or "webhook" in res_q18.json()["reply"].lower()
