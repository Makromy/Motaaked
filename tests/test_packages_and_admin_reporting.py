import pytest
from app.models import User, Package, utc_now


class TestPackagesAndAdminReporting:

    def test_public_packages_listing(self, client):
        # 1. Fetch public packages
        res = client.get("/v1/packages")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 3
        plan_ids = [p["plan_id"] for p in data["packages"]]
        assert "plan_30d" in plan_ids
        assert "plan_90d" in plan_ids
        assert "plan_200pts" in plan_ids

        # Verify 90d plan has discount strike-through info
        p90 = next(p for p in data["packages"] if p["plan_id"] == "plan_90d")
        assert p90["price"] == 80.0
        assert p90["original_price"] == 100.0
        assert p90["discount_label"] == "20% OFF"

    def test_admin_create_modify_toggle_and_delete_package(self, client, auth_headers):
        # 1. Admin creates a new discounted package
        payload = {
            "plan_id": "plan_vip_annual",
            "name": "1 Year VIP Access",
            "badge": "Super Deal",
            "price": 300.00,
            "original_price": 450.00,
            "discount_label": "33% OFF",
            "duration_days": 365,
            "credits": 1500,
            "features": ["365 Days Access", "1500 VIP Search Credits", "Dedicated Account Manager"],
            "is_active": True,
            "sort_order": 10,
        }
        res_create = client.post("/v1/admin/packages", headers=auth_headers, json=payload)
        assert res_create.status_code == 201
        created_pkg = res_create.json()
        pkg_id = created_pkg["id"]
        assert created_pkg["plan_id"] == "plan_vip_annual"
        assert created_pkg["price"] == 300.00
        assert created_pkg["original_price"] == 450.00

        # 2. Verify it is visible in public /v1/packages
        res_pub = client.get("/v1/packages")
        assert any(p["plan_id"] == "plan_vip_annual" for p in res_pub.json()["packages"])

        # 3. Admin updates package price & discount
        res_update = client.put(
            f"/v1/admin/packages/{pkg_id}",
            headers=auth_headers,
            json={"price": 280.00, "discount_label": "38% OFF"},
        )
        assert res_update.status_code == 200
        assert res_update.json()["price"] == 280.00
        assert res_update.json()["discount_label"] == "38% OFF"

        # 4. Admin toggles visibility (Hide)
        res_toggle = client.patch(f"/v1/admin/packages/{pkg_id}/toggle", headers=auth_headers)
        assert res_toggle.status_code == 200
        assert res_toggle.json()["is_active"] is False

        # Verify it is NO LONGER visible in public endpoint
        res_pub2 = client.get("/v1/packages")
        assert not any(p["plan_id"] == "plan_vip_annual" for p in res_pub2.json()["packages"])

        # But it IS visible in admin list
        res_adm = client.get("/v1/admin/packages", headers=auth_headers)
        assert any(p["plan_id"] == "plan_vip_annual" for p in res_adm.json()["packages"])

        # 5. Toggle back to active
        client.patch(f"/v1/admin/packages/{pkg_id}/toggle", headers=auth_headers)

        # 6. Admin deletes package
        res_del = client.delete(f"/v1/admin/packages/{pkg_id}", headers=auth_headers)
        assert res_del.status_code == 200
        assert res_del.json()["success"] is True

    def test_admin_purchases_report_and_csv_export(self, client, auth_headers):
        # 1. Create a Buyer merchant
        res_buyer = client.post(
            "/v1/auth/register",
            json={"name": "Reporting Merchant", "email": "report_merchant@company.com"},
        )
        assert res_buyer.status_code == 201
        buyer_passcode = res_buyer.json()["passcode"]
        buyer_headers = {"X-Passcode": buyer_passcode}

        # 2. Buyer makes a Direct Top-Up purchase (30 Days - 30.00 EGP)
        res_init_direct = client.post(
            "/v1/topup/initiate",
            headers=buyer_headers,
            json={"plan_id": "plan_30d", "purchase_type": "direct"},
        )
        assert res_init_direct.status_code == 200
        order_direct = res_init_direct.json()["order_id"]

        # Ingest SMS
        client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": "تم استلام تحويل لحظي بقيمة 30.00 جم برقم مرجعي DIR_REP_101 بتاريخ اليوم"},
        )
        # Verify & Activate
        res_ver_dir = client.post(
            "/v1/topup/verify",
            headers=buyer_headers,
            json={"order_id": order_direct, "reference_id": "DIR_REP_101"},
        )
        assert res_ver_dir.status_code == 200

        # 3. Buyer makes a Gift Voucher purchase (90 Days - 80.00 EGP)
        res_init_gift = client.post(
            "/v1/topup/initiate",
            headers=buyer_headers,
            json={"plan_id": "plan_90d", "purchase_type": "gift", "recipient_email": "friend@company.com"},
        )
        assert res_init_gift.status_code == 200
        order_gift = res_init_gift.json()["order_id"]

        # Ingest SMS
        client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": "تم استلام تحويل لحظي بقيمة 80.00 جم برقم مرجعي GIFT_REP_202 بتاريخ اليوم"},
        )
        # Verify & Activate
        res_ver_gift = client.post(
            "/v1/topup/verify",
            headers=buyer_headers,
            json={"order_id": order_gift, "reference_id": "GIFT_REP_202", "recipient_email": "friend@company.com"},
        )
        assert res_ver_gift.status_code == 200
        gift_voucher_code = res_ver_gift.json()["voucher_code"]

        # 4. Query Admin Purchases Report
        res_rep = client.get("/v1/admin/purchases/filter", headers=auth_headers)
        assert res_rep.status_code == 200
        rep_data = res_rep.json()
        assert rep_data["total"] >= 2
        assert rep_data["total_revenue_egp"] >= 110.00
        assert rep_data["total_direct_purchases"] >= 1
        assert rep_data["total_gift_vouchers"] >= 1

        # Check item details
        items = rep_data["items"]
        gift_item = next(i for i in items if i["order_id"] == order_gift)
        assert gift_item["purchase_type"] == "gift"
        assert gift_item["amount"] == 80.00
        assert gift_item["reference_id"] == "GIFT_REP_202"
        assert gift_item["merchant_name"] == "Reporting Merchant"
        assert gift_item["voucher_code"] == gift_voucher_code
        assert gift_item["voucher_redeemed"] is False

        # 5. Filter report by type
        res_filter_direct = client.get("/v1/admin/purchases/filter?purchase_type=direct", headers=auth_headers)
        assert res_filter_direct.status_code == 200
        assert all(i["purchase_type"] == "direct" for i in res_filter_direct.json()["items"])

        res_filter_gift = client.get("/v1/admin/purchases/filter?purchase_type=gift", headers=auth_headers)
        assert res_filter_gift.status_code == 200
        assert all(i["purchase_type"] == "gift" for i in res_filter_gift.json()["items"])

        # 6. Recipient redeems the gift voucher
        res_rec = client.post(
            "/v1/auth/register",
            json={"name": "Recipient User", "email": "friend@company.com"},
        )
        rec_headers = {"X-Passcode": res_rec.json()["passcode"]}
        res_redeem = client.post("/v1/passcodes/redeem", headers=rec_headers, json={"passcode": gift_voucher_code})
        assert res_redeem.status_code == 200

        # Query report again -> voucher status should now reflect Redeemed
        res_rep2 = client.get("/v1/admin/purchases/filter", headers=auth_headers)
        items2 = res_rep2.json()["items"]
        gift_item2 = next(i for i in items2 if i["order_id"] == order_gift)
        assert gift_item2["voucher_redeemed"] is True
        assert gift_item2["voucher_redeemed_by"] == "Recipient User"

        # 7. Test CSV export
        res_csv = client.get("/v1/admin/purchases/export", headers=auth_headers)
        assert res_csv.status_code == 200
        assert res_csv.headers["content-type"].startswith("text/csv")
        csv_text = res_csv.text
        assert "Order ID,Purchase Type,Merchant Name" in csv_text
        assert "DIR_REP_101" in csv_text
        assert "GIFT_REP_202" in csv_text
        assert "Reporting Merchant" in csv_text
