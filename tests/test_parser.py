import pytest
from app.parser import parse_sms, SMSParseError, normalize_text


class TestSMSParser:

    def test_english_hsbc_sms(self):
        sms = (
            "Your account ending in 1234 has been credited with EGP 1,500.00 on 22/08/2026 "
            "from AHMED MAHMOUD. Ref: IPN260822143000 (IPN Inward Transfer)"
        )
        result = parse_sms(sms)
        assert result.amount == 1500.00
        assert result.currency == "EGP"
        assert result.reference_id == "IPN260822143000"
        assert result.account_ending == "1234"
        assert "AHMED MAHMOUD" in result.sender_name

    def test_english_cib_sms(self):
        sms = (
            "You have received an IPN transfer of EGP 350.00 to account ending 4321 "
            "from OMAR KHALED. Ref No: IPN123456789."
        )
        result = parse_sms(sms)
        assert result.amount == 350.00
        assert result.currency == "EGP"
        assert result.reference_id == "IPN123456789"
        assert result.account_ending == "4321"
        assert "OMAR KHALED" in result.sender_name

    def test_english_generic_ipn(self):
        sms = (
            "Dear customer, IPN transfer of 2500.50 EGP credited to account 8876 "
            "from SARA IBRAHIM. Reference: TRX987654321"
        )
        result = parse_sms(sms)
        assert result.amount == 2500.50
        assert result.currency == "EGP"
        assert result.reference_id == "TRX987654321"
        assert result.account_ending == "8876"
        assert "SARA IBRAHIM" in result.sender_name

    def test_arabic_nbe_sms(self):
        sms = (
            "تم تحويل مبلغ 1,500.00 جم لحسابكم المنتهي بـ 1234 من احمد محمد "
            "عبر شبكة المدفوعات اللحظية مرجع رقم IPN260822143000"
        )
        result = parse_sms(sms)
        assert result.amount == 1500.00
        assert result.currency == "EGP"
        assert result.reference_id == "IPN260822143000"
        assert result.account_ending == "1234"
        assert "احمد محمد" in result.sender_name

    def test_arabic_nbe_variant_sms(self):
        sms = "تم إضافة مبلغ 500 جم إلى حسابك المنتهي بـ 4321 من علي حسن تحويل لحظي مرجع: IPN1122334455"
        result = parse_sms(sms)
        assert result.amount == 500.00
        assert result.currency == "EGP"
        assert result.reference_id == "IPN1122334455"
        assert result.account_ending == "4321"
        assert "علي حسن" in result.sender_name

    def test_arabic_cib_sms(self):
        sms = "تم استلام تحويل لحظي بمبلغ 250.00 ج.م من عمر خالد إلى حسابكم المنتهي بـ 5678. رقم المرجع IPN99887766"
        result = parse_sms(sms)
        assert result.amount == 250.00
        assert result.currency == "EGP"
        assert result.reference_id == "IPN99887766"
        assert result.account_ending == "5678"
        assert "عمر خالد" in result.sender_name

    def test_arabic_banque_misr_sms(self):
        sms = "إيداع تحويل لحظي IPN بمبلغ 750.50 جم بحسابك رقم ...1234 من كريم يوسف مرجع IPN44556677"
        result = parse_sms(sms)
        assert result.amount == 750.50
        assert result.currency == "EGP"
        assert result.reference_id == "IPN44556677"
        assert result.account_ending == "1234"
        assert "كريم يوسف" in result.sender_name

    def test_arabic_numerals_conversion(self):
        sms = "تم تحويل مبلغ ١,٥٠٠.٥٠ جم لحسابكم المنتهي بـ ١٢٣٤ من سارة احمد مرجع رقم IPN99998888"
        result = parse_sms(sms)
        assert result.amount == 1500.50
        assert result.currency == "EGP"
        assert result.reference_id == "IPN99998888"
        assert result.account_ending == "1234"

    def test_empty_or_whitespace_sms(self):
        with pytest.raises(SMSParseError):
            parse_sms("")
        with pytest.raises(SMSParseError):
            parse_sms("   ")

    def test_arabic_instant_transfer_sms(self):
        sms = "يرجى العلم انه تم تنفيذ تحويل لحظي بمبلغ 5.00 جم إلى حسابك المنتهي بـ ********8831 من HAITHAM REFAAT ELMAKROM برقم مرجعي 87901e09 بتاريخ 22-08-2026 13:16 للمزيد، برجاء الاتصال بـ 19666"
        result = parse_sms(sms)
        assert result.amount == 5.00
        assert result.currency == "EGP"
        assert result.reference_id == "87901e09"
        assert result.account_ending == "8831"
        assert "HAITHAM REFAAT ELMAKROM" in result.sender_name

    def test_non_transfer_sms_rejection(self):
        with pytest.raises(SMSParseError):
            parse_sms("Your OTP is 482910. Valid for 5 minutes. Do not share with anyone.")
        with pytest.raises(SMSParseError):
            parse_sms("استمتع بأقوى العروض والخصومات على بطاقتك الائتمانية من البنك.")

    def test_outgoing_debit_sms_rejection(self):
        # Sent/debit SMS where money left merchant's account
        outward_sms = "يرجى العلم انه تم تنفيذ تحويل لحظي بمبلغ 5.00 جم من حسابك المنتهي بـ ********8831 برقم مرجعي d0723a00 بتاريخ 22-08-2026 16:30 للمزيد، برجاء الاتصال بـ 19666"
        with pytest.raises(SMSParseError) as exc_info:
            parse_sms(outward_sms)
        assert "Outgoing transfer or debit alert detected" in str(exc_info.value)


class TestExtractReferenceAPI:

    @pytest.fixture(autouse=True)
    def setup_client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app)

    def test_extract_from_english_sms(self):
        res = self.client.post("/v1/parser/extract-reference", json={
            "text": "Your account ***1001 credited with EGP 500.00 from HAITHAM REFAAT. Ref: bfcf3886"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["reference_id"] == "bfcf3886"
        assert data["amount"] == 500.00
        assert data["currency"] == "EGP"

    def test_extract_from_arabic_sms_with_eastern_digits(self):
        res = self.client.post("/v1/parser/extract-reference", json={
            "text": "تم تحويل مبلغ ١,٥٠٠.٠٠ جم لحسابكم من احمد محمد برقم مرجع 0d2e0392"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["reference_id"] == "0d2e0392"
        assert data["amount"] == 1500.00
        assert data["currency"] == "EGP"

    def test_extract_standalone_reference_hash(self):
        res = self.client.post("/v1/parser/extract-reference", json={
            "text": "Payment confirmed! Transaction reference: 87901e09"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["reference_id"] == "87901e09"

    def test_extract_standalone_ipn_code(self):
        res = self.client.post("/v1/parser/extract-reference", json={
            "text": "IPN20260828143000"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["reference_id"] == "IPN20260828143000"

    def test_extract_empty_or_invalid_text(self):
        res = self.client.post("/v1/parser/extract-reference", json={
            "text": "Welcome to our store!"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False
        assert data["reference_id"] is None

