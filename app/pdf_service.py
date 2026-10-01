import io
import os
import shutil
import hashlib
import xml.sax.saxutils as saxutils
from datetime import datetime, date
from typing import List, Optional
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    HRFlowable,
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_ARABIC_SUPPORT = True
except ImportError:
    HAS_ARABIC_SUPPORT = False

from app.models import IncomingCredit, User, utc_now

# =============================================================================
# Font Registration Engine (Auto-detect & Fallback for Arabic / Unicode TTF)
# =============================================================================
FONT_REGULAR = "InstaFont"
FONT_BOLD = "InstaFont-Bold"

_FONTS_INITIALIZED = False


def _init_fonts():
    global _FONTS_INITIALIZED, FONT_REGULAR, FONT_BOLD
    if _FONTS_INITIALIZED:
        return

    # Potential font candidates (Windows, Bundled, Linux)
    candidate_regular_paths = [
        os.path.join(os.path.dirname(__file__), "fonts", "Arial.ttf"),
        os.path.join(os.path.dirname(__file__), "fonts", "arial.ttf"),
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]

    candidate_bold_paths = [
        os.path.join(os.path.dirname(__file__), "fonts", "Arial-Bold.ttf"),
        os.path.join(os.path.dirname(__file__), "fonts", "arialbd.ttf"),
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\tahomabd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]

    reg_path = next((p for p in candidate_regular_paths if os.path.exists(p)), None)
    bold_path = next((p for p in candidate_bold_paths if os.path.exists(p)), None)

    # If found on Windows, also mirror to app/fonts for portable standalone execution
    fonts_dir = os.path.join(os.path.dirname(__file__), "fonts")
    if reg_path and not os.path.exists(os.path.join(fonts_dir, "Arial.ttf")):
        try:
            os.makedirs(fonts_dir, exist_ok=True)
            if "Windows" in reg_path:
                shutil.copy2(reg_path, os.path.join(fonts_dir, "Arial.ttf"))
            if bold_path and "Windows" in bold_path:
                shutil.copy2(bold_path, os.path.join(fonts_dir, "Arial-Bold.ttf"))
        except Exception:
            pass

    if reg_path:
        try:
            pdfmetrics.registerFont(TTFont(FONT_REGULAR, reg_path))
            if bold_path:
                pdfmetrics.registerFont(TTFont(FONT_BOLD, bold_path))
            else:
                pdfmetrics.registerFont(TTFont(FONT_BOLD, reg_path))
            _FONTS_INITIALIZED = True
            return
        except Exception:
            pass

    # Fallback to standard core 14 fonts if no TTF font is accessible
    FONT_REGULAR = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"
    _FONTS_INITIALIZED = True


# Initialize font metrics on module load
_init_fonts()


def format_bidi(text: Optional[str]) -> str:
    """
    Reshapes Arabic letters and applies Unicode Bidirectional Algorithm (BiDi)
    to render correctly in PDF documents from Right to Left.
    """
    if not text:
        return ""
    text_str = str(text).strip()
    if not text_str:
        return ""

    # Check for Arabic Unicode ranges
    has_arabic = any(
        '\u0600' <= char <= '\u06FF' or
        '\u0750' <= char <= '\u077F' or
        '\u08A0' <= char <= '\u08FF' or
        '\uFB50' <= char <= '\uFDFF' or
        '\uFE70' <= char <= '\uFEFF'
        for char in text_str
    )

    if has_arabic and HAS_ARABIC_SUPPORT:
        try:
            reshaped = arabic_reshaper.reshape(text_str)
            return get_display(reshaped)
        except Exception:
            return text_str

    return text_str


def escape_xml(val: Optional[str]) -> str:
    """Escapes XML/HTML characters to prevent ReportLab Paragraph markup injection and crashes."""
    if not val:
        return ""
    return saxutils.escape(str(val))


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to calculate the total page count dynamically.
    Draws modern running headers, footers, page numbering and Egyptian compliance metadata.
    """
    portal_name: str = "InstaVerify"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont(FONT_REGULAR, 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Header Accent Line
        self.setStrokeColor(colors.HexColor("#6366f1"))
        self.setLineWidth(1.5)
        self.line(30, 812, 565, 812)

        # Dynamic Header Text
        brand_display = getattr(self, "portal_name", None) or "InstaVerify"
        brand_upper = brand_display.upper()
        self.drawString(30, 818, f"{brand_upper} — OFFICIAL BANK SMS STATEMENT")
        self.drawRightString(565, 818, "CONFIDENTIAL & SECURE")

        # Footer Accent Line
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(30, 35, 565, 35)

        # Dynamic Footer Text
        self.drawString(30, 24, f"Generated via {brand_display} Automated Ledger Platform | Egyptian Law Compliant")
        self.drawRightString(565, 24, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def generate_sms_statement_pdf(
    merchant: User,
    transactions: List[IncomingCredit],
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    portal_name: Optional[str] = None,
) -> bytes:
    """
    Generates a high-quality PDF statement for the merchant's bank SMS transactions
    with full Arabic glyph shaping, BiDi support, and multi-page pagination.
    """
    _init_fonts()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=30,
        rightMargin=30,
        topMargin=45,
        bottomMargin=45,
    )

    styles = getSampleStyleSheet()

    # Custom Typography Styles (Using Arabic / Unicode Compatible Fonts)
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName=FONT_BOLD,
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=12,
    )
    meta_label = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#475569"),
    )
    meta_val = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#0f172a"),
    )
    table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#ffffff"),
        alignment=1,  # Center
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1e293b"),
        alignment=0,
    )
    table_cell_mono = ParagraphStyle(
        "TableCellMono",
        parent=styles["Normal"],
        fontName="Courier-Bold",
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#4338ca"),
        alignment=0,
    )
    table_cell_right = ParagraphStyle(
        "TableCellRight",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0f172a"),
        alignment=2,  # Right
    )
    status_claimed = ParagraphStyle(
        "StatusClaimed",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#059669"),
        alignment=1,
    )
    status_matched = ParagraphStyle(
        "StatusMatched",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#2563eb"),
        alignment=1,
    )
    status_unmatched = ParagraphStyle(
        "StatusUnmatched",
        parent=styles["Normal"],
        fontName=FONT_REGULAR,
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#64748b"),
        alignment=1,
    )

    if not portal_name:
        try:
            from app.database import SessionLocal
            from app.services import get_system_settings
            from app.config import settings
            with SessionLocal() as db:
                s = get_system_settings(db)
                portal_name = s.get("portal_name") or getattr(settings, "PORTAL_NAME", None) or os.getenv("PORTAL_NAME", "Motaaked")
        except Exception:
            from app.config import settings
            portal_name = getattr(settings, "PORTAL_NAME", None) or os.getenv("PORTAL_NAME", "Motaaked")

    brand_display = portal_name or "Motaaked"
    brand_upper = brand_display.upper()

    story = []

    # 1. Document Header
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"{escape_xml(brand_upper)} TRANSACTION STATEMENT", title_style))
    story.append(Paragraph("Official Bank SMS Incoming Transfers & Settlement Ledger", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cbd5e1"), spaceAfter=10))

    # 2. Metadata Information Block
    now_dt = utc_now()
    period_str = f"{date_from.strftime('%Y-%m-%d') if date_from else 'Beginning'} to {date_to.strftime('%Y-%m-%d') if date_to else 'Today'}"
    raw_merchant_name = getattr(merchant, "name", "Merchant") or "Merchant"
    merchant_name = format_bidi(raw_merchant_name)
    account_ending = getattr(merchant, "account_ending", "----") or "----"

    total_count = len(transactions)
    total_volume = sum(t.amount for t in transactions)
    claimed_count = sum(1 for t in transactions if t.status == "CLAIMED")
    matched_count = sum(1 for t in transactions if (getattr(t, "is_matched", False) and t.status != "CLAIMED"))
    unmatched_count = sum(1 for t in transactions if (not getattr(t, "is_matched", False) and t.status != "CLAIMED"))

    meta_data = [
        [
            Paragraph("<b>Merchant Name:</b>", meta_label),
            Paragraph(escape_xml(merchant_name), meta_val),
            Paragraph("<b>Statement Period:</b>", meta_label),
            Paragraph(escape_xml(period_str), meta_val),
        ],
        [
            Paragraph("<b>Bank Account:</b>", meta_label),
            Paragraph(f"***{escape_xml(account_ending)}", meta_val),
            Paragraph("<b>Generated On:</b>", meta_label),
            Paragraph(now_dt.strftime("%Y-%m-%d %H:%M:%S UTC"), meta_val),
        ],
    ]

    meta_table = Table(meta_data, colWidths=[90, 175, 95, 175])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#f1f5f9")),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # 3. Summary Metrics Cards Table (Aligned 1-to-1 with Ledger Statuses)
    summary_data = [
        [
            Paragraph("<b>TOTAL TRANSFERS</b>", ParagraphStyle("S1", parent=meta_label, alignment=1, textColor=colors.HexColor("#475569"))),
            Paragraph("<b>TOTAL VOLUME</b>", ParagraphStyle("S2", parent=meta_label, alignment=1, textColor=colors.HexColor("#475569"))),
            Paragraph("<b>CLAIMED</b>", ParagraphStyle("S3", parent=meta_label, alignment=1, textColor=colors.HexColor("#059669"))),
            Paragraph("<b>MATCHED</b>", ParagraphStyle("S4", parent=meta_label, alignment=1, textColor=colors.HexColor("#2563eb"))),
            Paragraph("<b>UNMATCHED</b>", ParagraphStyle("S5", parent=meta_label, alignment=1, textColor=colors.HexColor("#64748b"))),
        ],
        [
            Paragraph(f"<b>{total_count}</b>", ParagraphStyle("V1", parent=title_style, fontSize=13, leading=15, alignment=1)),
            Paragraph(f"<b>{total_volume:,.2f} EGP</b>", ParagraphStyle("V2", parent=title_style, fontSize=13, leading=15, alignment=1, textColor=colors.HexColor("#4338ca"))),
            Paragraph(f"<b>{claimed_count}</b>", ParagraphStyle("V3", parent=title_style, fontSize=13, leading=15, alignment=1, textColor=colors.HexColor("#059669"))),
            Paragraph(f"<b>{matched_count}</b>", ParagraphStyle("V4", parent=title_style, fontSize=13, leading=15, alignment=1, textColor=colors.HexColor("#2563eb"))),
            Paragraph(f"<b>{unmatched_count}</b>", ParagraphStyle("V5", parent=title_style, fontSize=13, leading=15, alignment=1, textColor=colors.HexColor("#64748b"))),
        ]
    ]

    summary_table = Table(summary_data, colWidths=[95, 130, 100, 100, 110])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("PADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 14))

    # 4. Transactions Ledger Table
    story.append(Paragraph("<b>TRANSACTION DETAILS</b>", ParagraphStyle("TblHead", parent=styles["Normal"], fontName=FONT_BOLD, fontSize=10, textColor=colors.HexColor("#0f172a"))))
    story.append(Spacer(1, 4))

    tx_rows = [
        [
            Paragraph("#", table_header),
            Paragraph("Date / Time (UTC)", table_header),
            Paragraph("Reference ID", table_header),
            Paragraph("Sender Name", table_header),
            Paragraph("Account", table_header),
            Paragraph("Amount (EGP)", table_header),
            Paragraph("Status", table_header),
        ]
    ]

    if not transactions:
        tx_rows.append([
            Paragraph("—", table_cell),
            Paragraph("No transactions recorded in this period.", table_cell),
            Paragraph("—", table_cell),
            Paragraph("—", table_cell),
            Paragraph("—", table_cell),
            Paragraph("0.00", table_cell_right),
            Paragraph("—", table_cell),
        ])
    else:
        for idx, tx in enumerate(transactions, start=1):
            date_str = tx.received_at.strftime("%Y-%m-%d %H:%M") if tx.received_at else "—"
            raw_sender = tx.sender_name or "Unknown"
            if len(raw_sender) > 30:
                raw_sender = raw_sender[:28] + "..."
            sender_str = format_bidi(raw_sender)
            acc_str = f"***{tx.account_ending}" if tx.account_ending else "—"
            if tx.status == "CLAIMED":
                status_para = Paragraph("CLAIMED", status_claimed)
            elif getattr(tx, "is_matched", False):
                status_para = Paragraph("MATCHED", status_matched)
            else:
                status_para = Paragraph("UNMATCHED", status_unmatched)

            tx_rows.append([
                Paragraph(str(idx), ParagraphStyle("Idx", parent=table_cell, alignment=1)),
                Paragraph(escape_xml(date_str), table_cell),
                Paragraph(escape_xml(tx.reference_id), table_cell_mono),
                Paragraph(escape_xml(sender_str), table_cell),
                Paragraph(escape_xml(acc_str), table_cell),
                Paragraph(f"{tx.amount:,.2f}", table_cell_right),
                status_para,
            ])

    # Table Column Widths (Total: ~535pt)
    tx_table = Table(tx_rows, colWidths=[25, 80, 110, 140, 50, 70, 60], repeatRows=1)
    tx_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e1b4b")),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
        ("PADDING", (0, 0), (-1, -1), 3.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
    ]))
    story.append(tx_table)

    # 5. Security Hash & Verification Seal
    story.append(Spacer(1, 15))
    doc_hash_input = f"{merchant.id}_{total_count}_{total_volume}_{now_dt.isoformat()}"
    doc_hash = hashlib.sha256(doc_hash_input.encode()).hexdigest()[:24].upper()

    seal_data = [
        [
            Paragraph(f"<b>Verification Hash:</b> <font face='Courier'>{doc_hash}</font>", ParagraphStyle("Seal", parent=styles["Normal"], fontName=FONT_REGULAR, fontSize=7, textColor=colors.HexColor("#64748b"))),
            Paragraph("<b>Automated InstaPay Settlement Document</b> — Valid without manual signature.", ParagraphStyle("SealR", parent=styles["Normal"], fontName=FONT_REGULAR, fontSize=7, alignment=2, textColor=colors.HexColor("#64748b"))),
        ]
    ]
    seal_table = Table(seal_data, colWidths=[267, 268])
    seal_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(KeepTogether([seal_table]))

    # Build Document with custom NumberedCanvas
    def make_canvas(*args, **kwargs):
        c = NumberedCanvas(*args, **kwargs)
        c.portal_name = brand_display
        return c

    doc.build(story, canvasmaker=make_canvas)
    return buffer.getvalue()
