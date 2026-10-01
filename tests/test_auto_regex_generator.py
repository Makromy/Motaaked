import pytest
from app.parser import auto_generate_regex_from_sms, parse_with_regex_pattern
from app.config import settings

class TestAutoRegexGenerator:

    def test_auto_generate_arabic_nbe_sms(self):
        sms = "تم تحويل مبلغ 500.00 جم لحسابكم المنتهي بـ 1001 من احمد محمد عبر انستاباي بمرجع NBE123456789"
        res = auto_generate_regex_from_sms(sms)
        assert res["success"] is True
        assert res["detected_bank"] == "NBE (البنك الأهلي المصري)"
        assert res["detected_sender"] == "NBE"
        assert res["preview"]["amount"] == 500.00
        assert res["preview"]["reference_id"] == "NBE123456789"
        assert res["preview"]["account_ending"] == "1001"
        assert res["preview"]["sender_name"] == "احمد محمد"

        # Verify the generated pattern works on a DIFFERENT amount and ref with same format!
        diff_sms = "تم تحويل مبلغ 1,850.50 جم لحسابكم المنتهي بـ 4455 من سارة علي عبر انستاباي بمرجع NBE998877665"
        parsed = parse_with_regex_pattern(diff_sms, res["generated_pattern"])
        assert parsed is not None
        assert parsed.amount == 1850.50
        assert parsed.reference_id == "NBE998877665"
        assert parsed.account_ending == "4455"
        assert parsed.sender_name == "سارة علي"

    def test_auto_generate_arabic_banque_misr_sms(self):
        sms = "تم إيداع مبلغ 350.00 جم في حسابكم من محمد علي رقم العملية BM624FCFCB"
        res = auto_generate_regex_from_sms(sms)
        assert res["success"] is True
        assert res["detected_bank"] == "Banque Misr (بنك مصر)"
        assert res["preview"]["amount"] == 350.00
        assert res["preview"]["reference_id"] == "BM624FCFCB"

        diff_sms = "تم إيداع مبلغ 2,400.00 جم في حسابكم من خالد حسن رقم العملية BM8899AABB"
        parsed = parse_with_regex_pattern(diff_sms, res["generated_pattern"])
        assert parsed is not None
        assert parsed.amount == 2400.00
        assert parsed.reference_id == "BM8899AABB"

    def test_auto_generate_english_hsbc_sms(self):
        sms = "Transfer of EGP 750.00 received into account 1001 from SARAH KHALID. Ref: HSBC88990011"
        res = auto_generate_regex_from_sms(sms)
        assert res["success"] is True
        assert res["detected_bank"] == "HSBC"
        assert res["preview"]["amount"] == 750.00
        assert res["preview"]["reference_id"] == "HSBC88990011"
        assert res["preview"]["account_ending"] == "1001"
        assert res["preview"]["sender_name"] == "SARAH KHALID"

        diff_sms = "Transfer of EGP 3,200.00 received into account 9988 from OMAR ALI. Ref: HSBC11223344"
        parsed = parse_with_regex_pattern(diff_sms, res["generated_pattern"])
        assert parsed is not None
        assert parsed.amount == 3200.00
        assert parsed.reference_id == "HSBC11223344"
        assert parsed.account_ending == "9988"
        assert parsed.sender_name == "OMAR ALI"

    def test_auto_generate_new_unseen_bank_faisal(self):
        sms = "تم استلام تحويل بقيمة 900.00 جنيه لحسابكم 5566 من بنك فيصل مرجع FAISAL-998811"
        res = auto_generate_regex_from_sms(sms)
        assert res["success"] is True
        assert "فيصل" in res["detected_bank"]
        assert res["preview"]["amount"] == 900.00
    def test_auto_generate_banque_du_caire_sms(self):
        sms = "تمت استجابة تحويل لحظي بمبلغ 5.00 جم من HAITHAM REFAAT ELMAKKOOY يوم 9/25/24 في 14:56 رقم المعاملة : 24C16810 . للاستفسار اتصل على 19855"
        res = auto_generate_regex_from_sms(sms)
        assert res["success"] is True
        assert res["detected_bank"] == "Banque du Caire (بنك القاهرة)"
        assert res["detected_sender"] == "BDCA"
        assert res["preview"]["amount"] == 5.00
        assert res["preview"]["reference_id"] == "24C16810"
        assert res["preview"]["sender_name"] == "HAITHAM REFAAT ELMAKKOOY"

        # Verify the generated pattern works on a DIFFERENT amount, ref, date, time, and sender!
        diff_sms = "تمت استجابة تحويل لحظي بمبلغ 3,450.75 جم من OMAR HASSAN يوم 10/14/24 في 17:35 رقم المعاملة : 99B12345 . للاستفسار اتصل على 19855"
        parsed = parse_with_regex_pattern(diff_sms, res["generated_pattern"])
        assert parsed is not None
        assert parsed.amount == 3450.75
        assert parsed.reference_id == "99B12345"
        assert parsed.sender_name == "OMAR HASSAN"

    def test_auto_generate_missing_entities_rejection(self):
        # Missing reference ID
        res = auto_generate_regex_from_sms("تم إيداع مبلغ 500 جم بحسابكم بنجاح.")
        assert res["success"] is False
        assert "error" in res

        # Empty string
        res_empty = auto_generate_regex_from_sms("")
        assert res_empty["success"] is False

    def test_api_auto_generate_endpoint(self, client, auth_headers):
        payload = {
            "sample_text": "Credit of EGP 1,450.00 to A/C 9900 from TAREK NOUR Ref AAIB55443322"
        }
        res = client.post("/v1/admin/patterns/auto-generate", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["generated_pattern"] != ""
        assert data["detected_bank"] == "AAIB (البنك العربي الأفريقي الدولي)"
        assert data["preview"]["amount"] == 1450.00
        assert data["preview"]["reference_id"] == "AAIB55443322"
        assert data["preview"]["account_ending"] == "9900"
        assert data["preview"]["sender_name"] == "TAREK NOUR"
