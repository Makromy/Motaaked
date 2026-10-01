import pytest
from datetime import datetime, timezone
from app.models import User, IncomingCredit
from app.pdf_service import generate_sms_statement_pdf, format_bidi, HAS_ARABIC_SUPPORT


def test_arabic_bidi_formatter():
    assert HAS_ARABIC_SUPPORT is True
    # Test English
    assert format_bidi("Haitham Refaat") == "Haitham Refaat"
    # Test None / Empty
    assert format_bidi(None) == ""
    assert format_bidi("") == ""
    # Test Arabic
    ar_text = "هيثم رفعت المكرم"
    reshaped = format_bidi(ar_text)
    assert reshaped != ""
    assert len(reshaped) > 0


def test_generate_pdf_statement_with_arabic():
    merchant = User(
        id=101,
        name="متجر الأمانة والتجارة",
        email="merchant@example.com",
        account_ending="1001",
        role="MERCHANT",
    )

    transactions = [
        IncomingCredit(
            id=1,
            user_id=101,
            reference_id="3M0A9G3CC53",
            amount=350.0,
            sender_name="هيثم رفعت المكرم",
            account_ending="1001",
            status="CLAIMED",
            is_matched=True,
            received_at=datetime.now(timezone.utc),
        ),
        IncomingCredit(
            id=2,
            user_id=101,
            reference_id="3M030468852",
            amount=350.0,
            sender_name="محمد أحمد علي",
            account_ending="8831",
            status="MATCHED",
            is_matched=True,
            received_at=datetime.now(timezone.utc),
        ),
        IncomingCredit(
            id=3,
            user_id=101,
            reference_id="LIVE-TEST-2388",
            amount=760.0,
            sender_name="HAITHAM REFAAT",
            account_ending="1001",
            status="UNCLAIMED",
            is_matched=False,
            received_at=datetime.now(timezone.utc),
        ),
    ]

    pdf_bytes = generate_sms_statement_pdf(merchant, transactions)
    assert pdf_bytes is not None
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF")


def test_statement_metrics_accuracy():
    merchant = User(id=1, name="Haitham Refaat", account_ending="1001", role="admin")
    txs = [
        IncomingCredit(id=1, reference_id="R1", amount=100.0, status="CLAIMED", is_matched=True, received_at=datetime.now(timezone.utc)),
        IncomingCredit(id=2, reference_id="R2", amount=200.0, status="UNCLAIMED", is_matched=True, received_at=datetime.now(timezone.utc)),
        IncomingCredit(id=3, reference_id="R3", amount=300.0, status="UNCLAIMED", is_matched=False, received_at=datetime.now(timezone.utc)),
    ]
    pdf_bytes = generate_sms_statement_pdf(merchant, txs)
    assert pdf_bytes is not None

    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = doc[0].get_text()
    assert "CLAIMED" in text
    assert "MATCHED" in text
    assert "UNMATCHED" in text
    assert "600.00 EGP" in text

