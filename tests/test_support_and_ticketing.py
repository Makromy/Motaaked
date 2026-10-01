import pytest
from unittest.mock import patch
from app.config import settings


def test_public_config_includes_support_channels(client):
    """Verify that public portal configuration includes support widget settings."""
    res = client.get("/v1/settings/public")
    assert res.status_code == 200
    data = res.json()
    assert "support_widget_enabled" in data
    assert data["support_widget_enabled"] is True
    assert "support_ticketing_enabled" in data
    assert "support_faq_enabled" in data
    assert "support_social_enabled" in data
    assert "support_whatsapp_number" in data


def test_admin_update_support_settings(client, auth_headers):
    """Verify admin can update support channels and toggles."""
    update_payload = {
        "support_widget_enabled": True,
        "support_whatsapp_number": "201099998888",
        "support_telegram_handle": "instasupport",
        "support_telegram_enabled": True,
        "support_admin_email": "admin@instatakeed.com",
    }
    res = client.post("/v1/admin/settings", json=update_payload, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["support_whatsapp_number"] == "201099998888"
    assert data["support_telegram_handle"] == "instasupport"
    assert data["support_telegram_enabled"] is True

    # Check public config reflects update
    pub_res = client.get("/v1/settings/public")
    assert pub_res.status_code == 200
    pub_data = pub_res.json()
    assert pub_data["support_whatsapp_number"] == "201099998888"
    assert pub_data["support_telegram_handle"] == "instasupport"
    assert pub_data["support_telegram_enabled"] is True


def test_create_support_ticket(client):
    """Verify user can submit a trouble ticket and receive a unique tracking code."""
    payload = {
        "merchant_name": "Ahmed Merchant",
        "merchant_email": "ahmed@example.com",
        "merchant_phone": "01012345678",
        "category": "payment_dispute",
        "reference_id": "INSTA998877",
        "subject": "Missing payment notification for order 1042",
        "message": "Customer transferred 500 EGP via InstaPay with ref INSTA998877 but transaction is not showing.",
    }

    with patch("app.email_service.send_ticket_created_emails") as mock_email:
        mock_email.return_value = {"merchant": True, "admin": True}
        res = client.post("/v1/support/tickets", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["ticket_code"].startswith("TCK-")
        assert data["merchant_name"] == "Ahmed Merchant"
        assert data["category"] == "payment_dispute"
        assert data["reference_id"] == "INSTA998877"
        assert data["status"] == "OPEN"
        assert mock_email.called


def test_get_support_ticket_by_code(client):
    """Verify ticket lookup by public tracking code."""
    payload = {
        "merchant_name": "Mona Ali",
        "merchant_email": "mona@example.com",
        "category": "general_inquiry",
        "subject": "API Integration Question",
        "message": "How do I install the WooCommerce plugin?",
    }
    create_res = client.post("/v1/support/tickets", json=payload)
    assert create_res.status_code == 201
    ticket_code = create_res.json()["ticket_code"]

    get_res = client.get(f"/v1/support/tickets/{ticket_code}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["ticket_code"] == ticket_code
    assert data["merchant_name"] == "Mona Ali"
    assert data["status"] == "OPEN"


def test_get_ticket_not_found(client):
    """Verify 404 for nonexistent ticket code."""
    res = client.get("/v1/support/tickets/TCK-9999-XXXXXX")
    assert res.status_code == 404


def test_public_list_faqs(client):
    """Verify public FAQs list and category filtering."""
    res = client.get("/v1/support/faqs")
    assert res.status_code == 200
    faqs = res.json()
    assert len(faqs) >= 5
    assert any(f["category"] == "payments" for f in faqs)

    # Filter by category
    res_cat = client.get("/v1/support/faqs?category=payments")
    assert res_cat.status_code == 200
    cat_faqs = res_cat.json()
    assert len(cat_faqs) >= 1
    assert all(f["category"] == "payments" for f in cat_faqs)


def test_admin_manage_tickets(client, auth_headers):
    """Verify admin ticket listing, searching, and updating."""
    # Create two tickets
    client.post("/v1/support/tickets", json={
        "merchant_name": "User One",
        "merchant_email": "user1@example.com",
        "category": "forwarder_setup",
        "subject": "SMS Forwarder battery issue",
        "message": "Phone went to sleep overnight.",
    })
    t2 = client.post("/v1/support/tickets", json={
        "merchant_name": "User Two",
        "merchant_email": "user2@example.com",
        "category": "payment_dispute",
        "reference_id": "REF123456",
        "subject": "Delay in verification",
        "message": "Please check reference REF123456.",
    }).json()

    # List tickets
    list_res = client.get("/v1/admin/support/tickets", headers=auth_headers)
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["total"] >= 2
    assert len(data["items"]) >= 2

    # Search filter
    search_res = client.get("/v1/admin/support/tickets?search=REF123456", headers=auth_headers)
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["total"] >= 1
    assert any(item["ticket_code"] == t2["ticket_code"] for item in search_data["items"])

    # Admin update ticket
    with patch("app.email_service.send_ticket_status_update_email") as mock_update_email:
        mock_update_email.return_value = True
        update_res = client.put(
            f"/v1/admin/support/tickets/{t2['id']}",
            headers=auth_headers,
            json={
                "status": "RESOLVED",
                "admin_notes": "Matched manually with bank SMS from CIB at 14:30.",
                "reply_message": "Your transaction has been verified and settled. Thank you!",
            },
        )
        assert update_res.status_code == 200
        up_data = update_res.json()
        assert up_data["status"] == "RESOLVED"
        assert up_data["admin_notes"] == "Matched manually with bank SMS from CIB at 14:30."
        assert mock_update_email.called


def test_admin_faq_crud(client, auth_headers):
    """Verify admin can create, read, update, and delete FAQs."""

    # 1. Create FAQ
    new_faq = {
        "question_en": "How do I upgrade to the Enterprise Plan?",
        "question_ar": "كيف يمكنني الترقية إلى الباقة المؤسسية؟",
        "answer_en": "Contact our support team or upgrade from the Packages tab.",
        "answer_ar": "تواصل مع فريق الدعم أو قم بالترقية من تبويب الباقات.",
        "category": "pricing",
        "sort_order": 99,
        "is_active": True,
    }
    create_res = client.post("/v1/admin/support/faqs", headers=auth_headers, json=new_faq)
    assert create_res.status_code == 201
    created_id = create_res.json()["id"]

    # 2. Update FAQ
    update_res = client.put(
        f"/v1/admin/support/faqs/{created_id}",
        headers=auth_headers,
        json={"question_en": "How do I upgrade to Custom Enterprise?", "sort_order": 10},
    )
    assert update_res.status_code == 200
    assert update_res.json()["question_en"] == "How do I upgrade to Custom Enterprise?"
    assert update_res.json()["sort_order"] == 10

    # 3. Delete FAQ
    del_res = client.delete(f"/v1/admin/support/faqs/{created_id}", headers=auth_headers)
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Verify not in public faqs
    pub_faqs = client.get("/v1/support/faqs").json()
    assert not any(f["id"] == created_id for f in pub_faqs)


def test_create_ticket_add_new_bank(client):
    """Verify creating a trouble ticket with 'add_new_bank' category."""
    payload = {
        "merchant_name": "Tariq Bank Merchant",
        "merchant_email": "tariq@example.com",
        "merchant_phone": "01099887766",
        "category": "add_new_bank",
        "subject": "Request support for New Egyptian Digital Bank",
        "message": "Please add SMS parser support for the newly licensed digital bank notifications.",
    }
    with patch("app.email_service.send_ticket_created_emails") as mock_email:
        mock_email.return_value = {"merchant": True, "admin": True}
        res = client.post("/v1/support/tickets", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["ticket_code"].startswith("TCK-")
        assert data["category"] == "add_new_bank"
        assert data["merchant_name"] == "Tariq Bank Merchant"
        assert mock_email.called

