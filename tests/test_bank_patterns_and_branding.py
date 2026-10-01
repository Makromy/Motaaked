import pytest
from app.config import settings

class TestBankPatternsAndBranding:

    def test_bank_patterns_listing(self, client, auth_headers):
        res = client.get("/v1/admin/patterns", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "patterns" in data
        assert len(data["patterns"]) >= 8

    def test_bank_pattern_create_update_toggle_delete(self, client, auth_headers):
        create_payload = {
            "bank_name": "Test Custom Bank (بنك تجريبي)",
            "sender_filter": "TESTBANK",
            "pattern": r"Received (?P<amount>[\d,]+(?:\.\d{1,2})?) EGP from (?P<sender>[^.]+)\. Ref: (?P<ref>[A-Za-z0-9_-]+)",
            "amount_group": "amount",
            "ref_group": "ref",
            "account_group": "account",
            "sender_group": "sender",
            "example_sms": "Received 750.50 EGP from Sara Ali. Ref: TB-998877",
            "is_active": True,
            "priority": 5
        }
        res = client.post("/v1/admin/patterns", json=create_payload, headers=auth_headers)
        assert res.status_code == 201
        created = res.json()
        assert created["bank_name"] == "Test Custom Bank (بنك تجريبي)"
        pattern_id = created["id"]

        test_payload = {
            "pattern": created["pattern"],
            "sample_text": "Received 750.50 EGP from Sara Ali. Ref: TB-998877",
            "amount_group": "amount",
            "ref_group": "ref",
            "sender_group": "sender"
        }
        test_res = client.post("/v1/admin/patterns/test", json=test_payload, headers=auth_headers)
        assert test_res.status_code == 200
        sim_data = test_res.json()
        assert sim_data["matched"] is True
        assert sim_data["amount"] == 750.50
        assert sim_data["reference_id"] == "TB-998877"
        assert sim_data["sender_name"] == "Sara Ali"

        webhook_payload = {
            "raw_message": "Received 750.50 EGP from Sara Ali. Ref: TB-998877",
            "sender": "TESTBANK"
        }
        wh_res = client.post("/v1/webhook/sms", json=webhook_payload, headers=auth_headers)
        assert wh_res.status_code == 201
        wh_data = wh_res.json()
        assert wh_data["success"] is True
        assert wh_data["data"]["reference_id"] == "TB-998877"
        assert wh_data["data"]["amount"] == 750.50

        toggle_res = client.patch(f"/v1/admin/patterns/{pattern_id}/toggle", headers=auth_headers)
        assert toggle_res.status_code == 200
        assert toggle_res.json()["is_active"] is False

        del_res = client.delete(f"/v1/admin/patterns/{pattern_id}", headers=auth_headers)
        assert del_res.status_code == 200
        assert del_res.json()["success"] is True

    def test_portal_branding_settings_configuration(self, client, auth_headers):
        settings_payload = {
            "admin_key": settings.MASTER_API_KEY,
            "instapay_handle": "merchant@instapay",
            "instapay_phone": "01011112222",
            "instapay_account_ending": "5566",
            "instapay_receiver_name": "Haitham Refaat",
            "default_trial_days": 180,
            "search_credit_cost": 1,
            "vault_unlock_cost": 0,
            "statement_export_cost": 5,
            "monthly_free_credits": 150,
            "portal_name": "InstaPay Enterprise VIP",
            "portal_title": "Enterprise Transaction Verification Engine",
            "portal_subtitle_ar": "بوابة الشركات المعتمدة للتحقق من معاملات إنستاباي",
            "portal_subtitle_en": "Certified Enterprise Gateway for InstaPay Transactions"
        }

        res = client.post("/v1/admin/settings", json=settings_payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["portal_name"] == "InstaPay Enterprise VIP"
        assert data["portal_title"] == "Enterprise Transaction Verification Engine"
        assert data["portal_subtitle_ar"] == "بوابة الشركات المعتمدة للتحقق من معاملات إنستاباي"

        pub_res = client.get("/v1/portal/config")
        assert pub_res.status_code == 200
        pub_data = pub_res.json()
        assert pub_data["portal_name"] == "InstaPay Enterprise VIP"
        assert pub_data["portal_title"] == "Enterprise Transaction Verification Engine"
        assert pub_data["portal_subtitle_ar"] == "بوابة الشركات المعتمدة للتحقق من معاملات إنستاباي"
        assert pub_data["portal_subtitle_en"] == "Certified Enterprise Gateway for InstaPay Transactions"

    def test_white_label_and_dynamic_banks_and_ads_banner(self, client, auth_headers):
        # 1. Update system settings with White-Label AR brand and Announcement Ads Banner
        payload = {
            "admin_key": settings.MASTER_API_KEY,
            "portal_name": "Takid",
            "portal_name_ar": "تأكيد للدفع الذكي",
            "announcement_enabled": True,
            "announcement_title_en": "Special Offer: 50% Off Top-Ups",
            "announcement_title_ar": "عرض خاص: خصم 50% على باقات الشحن",
            "announcement_desc_en": "Valid until end of this week for all Egyptian merchants.",
            "announcement_desc_ar": "ساري حتى نهاية هذا الأسبوع لجميع التجار في مصر."
        }
        res = client.post("/v1/admin/settings", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["portal_name"] == "Takid"
        assert data["portal_name_ar"] == "تأكيد للدفع الذكي"
        assert data["announcement_enabled"] is True
        assert data["announcement_title_en"] == "Special Offer: 50% Off Top-Ups"
        assert data["announcement_title_ar"] == "عرض خاص: خصم 50% على باقات الشحن"
        assert data["announcement_desc_en"] == "Valid until end of this week for all Egyptian merchants."
        assert data["announcement_desc_ar"] == "ساري حتى نهاية هذا الأسبوع لجميع التجار في مصر."

        # 2. Verify Public Config API returns dynamic branding, announcement, and deduplicated banks
        pub_res = client.get("/v1/portal/config")
        assert pub_res.status_code == 200
        pub_data = pub_res.json()
        assert pub_data["portal_name"] == "Takid"
        assert pub_data["portal_name_ar"] == "تأكيد للدفع الذكي"
        assert pub_data["announcement_enabled"] is True
        assert pub_data["announcement_title_en"] == "Special Offer: 50% Off Top-Ups"
        assert pub_data["announcement_title_ar"] == "عرض خاص: خصم 50% على باقات الشحن"
        assert isinstance(pub_data["supported_banks"], list)
        assert len(pub_data["supported_banks"]) > 0

        # Check deduplication: no bank name appears more than once (case-insensitive)
        lower_banks = [b.lower() for b in pub_data["supported_banks"]]
        assert len(lower_banks) == len(set(lower_banks)), "Supported banks contains duplicate entries!"

        # 3. Verify Dynamic PWA Manifest uses the configured white-label names
        manifest_res = client.get("/manifest.json")
        assert manifest_res.status_code == 200
        manifest = manifest_res.json()
        assert "Takid" in manifest["name"]
        assert "تأكيد للدفع الذكي" in manifest["name"]
        assert manifest["short_name"] == "Takid"

        # 4. Verify announcement banner can be disabled
        disable_payload = {
            "admin_key": settings.MASTER_API_KEY,
            "announcement_enabled": False
        }
        res_dis = client.post("/v1/admin/settings", json=disable_payload, headers=auth_headers)
        assert res_dis.status_code == 200
        assert res_dis.json()["announcement_enabled"] is False

        pub_dis = client.get("/v1/portal/config").json()
        assert pub_dis["announcement_enabled"] is False
