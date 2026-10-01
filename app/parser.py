import re
from dataclasses import dataclass
from typing import Optional, Tuple


class SMSParseError(Exception):
    """Raised when an incoming SMS cannot be parsed as a valid InstaPay transfer alert."""
    pass


@dataclass
class ParsedTransfer:
    amount: float
    reference_id: str
    account_ending: Optional[str] = None
    currency: str = "EGP"
    sender_name: Optional[str] = None
    raw_message: str = ""


# Digit and symbol translation table
ARABIC_DIGITS_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫،", "01234567890123456789.,")


def normalize_text(text: str) -> str:
    """Normalize digits, tatweel, unicode spaces, and common Arabic character variations."""
    if not text:
        return ""
    # Convert Arabic/Persian digits and comma separators
    normalized = text.translate(ARABIC_DIGITS_TRANS)
    # Remove Arabic Tatweel (kashida \u0640)
    normalized = re.sub(r"[\u0640]", "", normalized)
    # Replace non-breaking spaces and unicode format markers
    normalized = re.sub(r"[\xa0\u200b\u200e\u200f]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def clean_amount(val: str) -> float:
    """Clean amount string with commas/spaces and convert to float."""
    cleaned = val.replace(",", "").replace(" ", "").strip()
    return round(float(cleaned), 2)


def clean_name(val: Optional[str]) -> Optional[str]:
    """Clean sender name removing trailing dots or artifacts."""
    if not val:
        return None
    # Remove stopwords that might be captured
    val = re.sub(r"^(?:sender|مرسل|المرسل)\s+", "", val, flags=re.IGNORECASE)
    cleaned = val.strip(" .,:-_()[]{}")
    return cleaned if len(cleaned) > 1 else None


# =========================================================================
# Sensitive Financial Data Redaction (Customer Available Balance & Limits)
# =========================================================================

BALANCE_LIMIT_REGEXES = [
    # English: available balance / ending balance / account balance
    re.compile(
        r'(?:[-.,;|]?\s*)?'
        r'(?:Your\s+|Card\s+)?'
        r'(?:available\s+balance|avail(?:able|\.)?\s*bal(?:ance|\.)?|avl\s*bal|account\s+balance|current\s+balance|remaining\s+balance|ledger\s+balance|ending\s+balance|closing\s+balance|total\s+balance|balance\s+is|bal\s*[:=])'
        r'(?:\s+is|\s*:|\s*=)?'
        r'\s*(?:EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية|E£|\$)?\s*[\d,]+(?:\.\d{1,2})?\s*(?:EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية|E£|\$)?',
        re.IGNORECASE
    ),
    # English: card available limit / credit limit / spending limit
    re.compile(
        r'(?:[-.,;|]?\s*)?'
        r'(?:Your\s+|Card\s+)?'
        r'(?:available\s+limit|avail(?:able|\.)?\s*limit|avl\s*limit|card\s+available\s+limit|credit\s+limit|card\s+limit|spending\s+limit|remaining\s+limit|available\s+credit|limit\s+is|limit\s*[:=])'
        r'(?:\s+is|\s*:|\s*=)?'
        r'\s*(?:EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية|E£|\$)?\s*[\d,]+(?:\.\d{1,2})?\s*(?:EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية|E£|\$)?',
        re.IGNORECASE
    ),
    # Arabic: رصيدك المتاح / الرصيد الحالي / رصيد الحساب المتبقي
    re.compile(
        r'(?:[-.,;|،]?\s*)?'
        r'(?:علماً\s*بأن\s*)?'
        r'(?:رصيدك|رصيدكم|الرصيد|رصيد\s*الحساب|صافي\s*الرصيد)'
        r'(?:\s+(?:المتاح|الحالي|المتبقي|الفعلي|النهائي|الإجمالي|الاجمالي|لحسابك|بحسابك|لديك))*'
        r'(?:\s*(?:هو|بلغ|يبلغ|:|=))?'
        r'\s*(?:EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية|E£|\$)?\s*[\d,]+(?:\.\d{1,2})?\s*(?:EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية|E£|\$)?',
        re.IGNORECASE
    ),
    # Arabic: الحد الائتماني المتاح / حد الائتمان / حد بطاقتك
    re.compile(
        r'(?:[-.,;|،]?\s*)?'
        r'(?:الحد\s*الائتماني|حد\s*الائتمان|حد\s*البطاقة|حد\s*بطاقتك|المتبقي\s*من\s*الحد|المبلغ\s*المتاح\s*للبطاقة|الحد\s*المتاح|حدك\s*المتاح)'
        r'(?:\s+(?:المتاح|المتبقي|الحالي|للبطاقة|لبطاقتك|لكارتك|لحسابك))*'
        r'(?:\s*(?:هو|بلغ|يبلغ|:|=))?'
        r'\s*(?:EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية|E£|\$)?\s*[\d,]+(?:\.\d{1,2})?\s*(?:EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية|E£|\$)?',
        re.IGNORECASE
    ),
]


def redact_sensitive_financial_data(text: str) -> str:
    """
    Strips customer available balance, remaining balance, and credit limit
    clauses from bank SMS text across English and Arabic variations.
    Guarantees privacy and prevents balance figures from interfering with transfer amounts.
    """
    if not text:
        return ""
    cleaned = text
    for rx in BALANCE_LIMIT_REGEXES:
        cleaned = rx.sub("", cleaned)
    # Clean up leftover trailing separators
    cleaned = re.sub(r"[\s\-_,;.]+$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def extract_reference_id(text: str) -> Optional[str]:
    """Extract InstaPay / IPN / Bank reference ID."""
    # Pattern 1: Explicit reference keywords followed by colon/hash/space and alphanumeric code
    ref_match = re.search(
        r"(?:(?:(?:ب)?رقم\s*(?:المرجع|العملي[ةه]|المعامل[ةه]|التحويل|الحرك[ةه]|الحوال[ةه]|المرجعي|مرجعي|مرجع|عملي[ةه]|معامل[ةه]|حرك[ةه]|حوال[ةه]|الطلب|الإشعار|الاشعار|الإيداع|الايداع|الإيصال|الايصال)"
        r"|(?:ب)?(?:مرجع|معامل[ةه]|عملي[ةه]|حرك[ةه]|حوال[ةه]|إشعار|اشعار|إيصال|ايصال)(?:\s*رقم)?"
        r"|كود\s*(?:المرجع|العملي[ةه]|المعامل[ةه]|التحويل|المرجعي|مرجعي|مرجع)?"
        r"|المرجع|مرجع"
        r"|Transaction\s*(?:reference|ref|No|ID|Number|#)?"
        r"|Ref(?:erence)?(?:\s*(?:No|ID|Number|#))?"
        r"|RRN|TRX(?:\s*(?:No|ID|Number|#))?"
        r"|Txn(?:\s*(?:No|ID|Number|#))?)[:\s#]+)([A-Za-z0-9_-]+)",
        text,
        re.IGNORECASE,
    )
    if ref_match:
        val = ref_match.group(1).strip()
        # Avoid common English/Arabic stop words
        if val.lower() not in ["transfer", "inward", "outward", "alert", "notification", "ipn", "reference", "ref"]:
            return val

    # Pattern 2: Standalone IPN / alphanumeric reference code (e.g. IPN202401011234, IPN123456789)
    ipn_standalone = re.search(r"\b(IPN[0-9A-Za-z]+)\b", text, re.IGNORECASE)
    if ipn_standalone:
        val = ipn_standalone.group(1).strip()
        if val.lower() not in ["ipn"]:
            return val

    # Pattern 3: Hex / Alphanumeric reference following keywords
    hex_ref = re.search(r"(?:مرجع|reference|rrn|trx)[:\s#]*([a-f0-9]{8,16})\b", text, re.IGNORECASE)
    if hex_ref:
        return hex_ref.group(1).strip()

    return None


def extract_amount_and_currency(text: str) -> Tuple[Optional[float], str]:
    """Extract transfer amount and normalize currency to EGP."""
    # Try amount preceded or followed by currency
    amount_patterns = [
        # Preceded/followed by known transaction verbs and currency
        r"(?:مبلغ|بقيمة|قيمة|بمبلغ|credited\s+with|transfer\s+of|amount\s+of|received|إيداع|ايداع|تحويل)\s*[:\s]?"
        r"(?:(EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية)\s*)?([\d,]+(?:\.\d{1,2})?)\s*(EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية)?",
        # Explicit currency followed by amount (e.g. EGP 81.00, USD 50, ج.م 250)
        r"(EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية)\s*([\d,]+(?:\.\d{1,2})?)",
        # Generic amount followed by currency symbol (not part of account/card numbers)
        r"(?<![-\*#\d/])\b([\d,]+(?:\.\d{1,2})?)\s*(EGP|LE|USD|EUR|جم|ج\.م|جنيه|جنية)\b",
    ]

    for pat in amount_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            groups = [g for g in match.groups() if g]
            # Separate numeric from currency
            amount_val = None
            curr_val = "EGP"
            for g in groups:
                if re.match(r"^[\d,]+(?:\.\d{1,2})?$", g):
                    amount_val = g
                elif g.upper() in ["EGP", "LE", "USD", "EUR", "جم", "ج.م", "جنيه", "جنية"]:
                    curr_val = g.upper()
            if amount_val:
                try:
                    amount = clean_amount(amount_val)
                    currency = "EGP" if curr_val in ["جم", "ج.م", "جنيه", "جنية", "LE", "EGP"] else curr_val
                    return amount, currency
                except Exception:
                    pass

    return None, "EGP"


def extract_account_ending(text: str) -> Optional[str]:
    """Extract masked account ending (last 3-6 digits)."""
    acc_patterns = [
        r"(?:A/C|acc|account(?:\s*ending(?:\s*(?:in|to|with))?|\s*number|\s*no)?|حسابك(?:م)?(?:\s*المنتهي\s*(?:بـ?|ب)?)?|بحسابك(?:\s*رقم)?|لحسابك(?:م)?(?:\s*رقم)?|حساب\s*رقم)\s*[:#\.\*]*\s*(\d{3,6})",
        r"(?:\.\.\.|\*{2,})(\d{3,6})",
        r"account\s+ending\s+(\d{3,6})",
    ]
    for pat in acc_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def extract_sender_name(text: str) -> Optional[str]:
    """Extract sender / payer name from SMS."""
    sender_patterns = [
        # English: from SENDER. Ref... or from SENDER on... or from SENDER via...
        r"from\s+([A-Za-z\s._-]+?)(?:\s+(?:on|via|to|into|\.|\n|Ref|Reference|RRN|TRX|$))",
        # Arabic: من HAITHAM REFAAT ELMAKROM برقم مرجعي... / من احمد محمد إلى... / من عمر خالد.
        r"من\s+([\u0600-\u06FFa-zA-Z\s._-]+?)(?:\s+(?:عبر|إلى|الى|لحساب|بحساب|في|فى|يوم|بتاريخ|تاريخ|الساع[ةه]|وذلك|تحويل|(?:ب)?مرجع|(?:ب)?رقم|للمزيد|للاستفسار|on|at|via|\.|\n|$))",
    ]
    for pat in sender_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            name = clean_name(match.group(1))
            if name:
                return name
    return None


def is_outward_debit_transfer(normalized: str) -> bool:
    """Detects whether an SMS represents an outgoing/debit transfer rather than an incoming credit."""
    has_debit_keyword = bool(re.search(
        r"(?:من\s+حسابك(?:م)?|خصم|debited|outward|withdrawn|سحب|مشتريات)",
        normalized,
        re.IGNORECASE
    ))
    has_credit_keyword = bool(re.search(
        r"(?:إلى\s+حسابك(?:م)?|لحسابك(?:م)?|بحسابك(?:م)?|credited|إيداع|ايداع|تم\s+إضافة|تم\s+اضافة|تم\s+استلام)",
        normalized,
        re.IGNORECASE
    ))
    return has_debit_keyword and not has_credit_keyword


def extract_group_value(match: re.Match, group_spec: Optional[str]) -> Optional[str]:
    """Helper to extract a group value by name or index from a regex Match object."""
    if not group_spec or not match:
        return None
    group_spec = group_spec.strip()
    # Try as integer index
    if group_spec.isdigit():
        idx = int(group_spec)
        if 0 <= idx <= len(match.groups()):
            val = match.group(idx)
            return val.strip() if val else None
    # Try named group
    groupdict = match.groupdict()
    if group_spec in groupdict and groupdict[group_spec]:
        return groupdict[group_spec].strip()
    # Try common alternatives if specified is amount/ref
    if group_spec == "amount":
        for k in ["amount", "amount_ar", "amt"]:
            if k in groupdict and groupdict[k]:
                return groupdict[k].strip()
    elif group_spec == "ref":
        for k in ["ref", "ref_id", "reference", "reference_id"]:
            if k in groupdict and groupdict[k]:
                return groupdict[k].strip()
    elif group_spec == "sender":
        for k in ["sender", "sender_ar", "sender_name"]:
            if k in groupdict and groupdict[k]:
                return groupdict[k].strip()
    elif group_spec == "account":
        for k in ["account", "account_ar", "acc", "account_ending"]:
            if k in groupdict and groupdict[k]:
                return groupdict[k].strip()
    return None


def parse_with_regex_pattern(
    raw_text: str,
    pattern: str,
    amount_group: str = "amount",
    ref_group: str = "ref",
    account_group: Optional[str] = "account",
    sender_group: Optional[str] = "sender"
) -> Optional[ParsedTransfer]:
    """
    Attempts to parse an SMS string using a specific regex pattern and capture groups.
    Returns ParsedTransfer if matched with valid amount and reference_id, else None.
    """
    if not raw_text or not pattern:
        return None
    sanitized_text = redact_sensitive_financial_data(raw_text)
    normalized = normalize_text(sanitized_text)
    if is_outward_debit_transfer(normalized):
        return None

    try:
        compiled = re.compile(pattern, re.IGNORECASE | re.DOTALL)
        match = compiled.search(normalized)
        if not match:
            return None

        raw_amount = extract_group_value(match, amount_group)
        raw_ref = extract_group_value(match, ref_group)
        raw_account = extract_group_value(match, account_group) if account_group else None
        raw_sender = extract_group_value(match, sender_group) if sender_group else None

        if not raw_amount or not raw_ref:
            return None

        amount = clean_amount(raw_amount)
        if amount <= 0:
            return None

        ref_id = raw_ref.strip()
        account_ending = raw_account.strip() if raw_account else extract_account_ending(normalized)
        sender_name = clean_name(raw_sender) if raw_sender else extract_sender_name(normalized)

        return ParsedTransfer(
            amount=amount,
            reference_id=ref_id,
            account_ending=account_ending,
            currency="EGP",
            sender_name=sender_name,
            raw_message=sanitized_text,
        )
    except Exception:
        return None


def parse_sms(raw_text: str) -> ParsedTransfer:
    """
    Main entry point for parsing raw SMS text into a structured ParsedTransfer object.
    Supports English & Arabic bank alerts for InstaPay/IPN.
    Throws SMSParseError if essential fields (amount, reference_id) cannot be extracted
    or if the message is an outgoing debit rather than an incoming credit.
    """
    if not raw_text or not raw_text.strip():
        raise SMSParseError("Empty SMS text provided.")

    # 1. Redact customer available balance and credit limits for privacy & clean amount matching
    sanitized_text = redact_sensitive_financial_data(raw_text)
    normalized = normalize_text(sanitized_text)

    # 2. Reject outgoing debit transfers (e.g. money sent from merchant's account)
    if is_outward_debit_transfer(normalized):
        raise SMSParseError("Outgoing transfer or debit alert detected. Only incoming credit transfers are ingested.")

    # 3. Extract Reference ID
    ref_id = extract_reference_id(normalized)
    if not ref_id:
        raise SMSParseError("Missing or undetectable InstaPay transfer reference ID.")

    # 4. Extract Amount & Currency
    amount, currency = extract_amount_and_currency(normalized)
    if amount is None or amount <= 0:
        raise SMSParseError("Missing or invalid transfer amount.")

    # 5. Extract Optional Account Ending
    account_ending = extract_account_ending(normalized)

    # 6. Extract Optional Sender Name
    sender_name = extract_sender_name(normalized)

    return ParsedTransfer(
        amount=amount,
        reference_id=ref_id,
        account_ending=account_ending,
        currency=currency,
        sender_name=sender_name,
        raw_message=sanitized_text,
    )


def detect_bank_identity(text: str) -> Tuple[str, Optional[str]]:
    """Detect bank name and optional sender tag from message text or signatures."""
    text_lower = text.lower()

    bank_signatures = [
        (["nbe", "الأهلي المصري", "البنك الاهلي", "الأهلى", "19623"], "NBE (البنك الأهلي المصري)", "NBE"),
        (["cib", "التجاري الدولي", "التجارى الدولى", "19666"], "CIB (البنك التجاري الدولي)", "CIB"),
        (["banque misr", "بنك مصر", "bm", "19888"], "Banque Misr (بنك مصر)", "BM"),
        (["hsbc"], "HSBC", "HSBC"),
        (["qnb", "قطر الوطني", "قطر الوطنى", "19700"], "QNB Alahli (بنك قطر الوطني الأهلي)", "QNB"),
        (["alexbank", "alex bank", "الإسكندرية", "الاسكندرية", "بنك اسكندرية", "19033"], "AlexBank (بنك الإسكندرية)", "ALEXBANK"),
        (["aaib", "العربي الأفريقي", "العربى الافريقى", "19555"], "AAIB (البنك العربي الأفريقي الدولي)", "AAIB"),
        (["faisal", "فيصل الإسلامي", "فيصل الاسلامي", "بنك فيصل", "19851"], "Faisal Islamic Bank (بنك فيصل الإسلامي)", "FAISAL"),
        (["fab", "أبوظبي الأول", "ابوظبي الاول", "19577"], "FAB (بنك أبوظبي الأول)", "FAB"),
        (["adib", "أبوظبي الإسلامي", "ابوظبي الاسلامي", "19951"], "ADIB (مصرف أبوظبي الإسلامي)", "ADIB"),
        (["ebank", "تنمية الصادرات", "المصري لتنمية الصادرات", "16722"], "EBank (البنك المصري لتنمية الصادرات)", "EBANK"),
        (["bdca", "بنك القاهرة", "du caire", "19855", "استجابة تحويل لحظي"], "Banque du Caire (بنك القاهرة)", "BDCA"),
        (["saib", "بنك الشركة المصرفية", "saib bank", "16668"], "saib (بنك الشركة المصرفية العربية الدولية)", "SAIB"),
        (["egbank", "البنك المصري الخليجي", "المصرى الخليجى", "19342"], "EG-Bank (البنك المصري الخليجي)", "EGBANK"),
        (["albaraka", "بنك البركة", "البركة", "19373"], "Al Baraka Bank (بنك البركة مصر)", "ALBARAKA"),
        (["attijariwafa", "التجاري وفا", "وفا بنك", "16222"], "Attijariwafa Bank (التجاري وفا بنك)", "ATTIJARIWAFA"),
        (["instapay", "انستاباي", "انستا باي", "ipn"], "InstaPay IPN Network", "INSTAPAY"),
    ]

    for keywords, name, sender in bank_signatures:
        for kw in keywords:
            if kw in text_lower:
                return name, sender

    return "Custom Bank Alert", None


def auto_generate_regex_from_sms(sample_text: str) -> dict:
    """
    Intelligently reverse-engineers and synthesizes a production-grade Regular Expression pattern
    with named capture groups from a raw bank SMS message.
    Self-validates the generated pattern against the sample text before returning.
    """
    if not sample_text or not sample_text.strip():
        return {
            "success": False,
            "error": "Empty sample SMS message provided.",
            "generated_pattern": "",
            "preview": None,
        }

    normalized = normalize_text(sample_text)
    bank_name, sender_tag = detect_bank_identity(normalized)

    # 1. Extract Essential Entities
    ref_id = extract_reference_id(normalized)
    amount, currency = extract_amount_and_currency(normalized)
    account_ending = extract_account_ending(normalized)
    sender_name = extract_sender_name(normalized)

    if not ref_id or amount is None:
        return {
            "success": False,
            "error": "Could not identify a valid Transfer Amount or Reference ID in the provided text. Please ensure the message contains both.",
            "generated_pattern": "",
            "preview": None,
        }

    # 2. Determine Spans for Entities
    spans = []

    # Find ref_id span (must match the literal string ref_id)
    ref_idx = normalized.rfind(ref_id)
    if ref_idx != -1:
        spans.append((ref_idx, ref_idx + len(ref_id), "ref"))

    # Find amount span (format may have commas like 1,250.00 or digits like 500.00)
    for m in re.finditer(r"[\d,]+(?:\.\d{1,2})?", normalized):
        try:
            if clean_amount(m.group(0)) == amount:
                # Ensure it doesn't overlap with ref_id
                if not (ref_idx <= m.start() < ref_idx + len(ref_id)):
                    spans.append((m.start(), m.end(), "amount"))
                    break
        except Exception:
            continue

    # Find account ending span if present
    if account_ending:
        acc_idx = normalized.find(account_ending)
        if acc_idx != -1 and not any(s <= acc_idx < e for s, e, _ in spans):
            spans.append((acc_idx, acc_idx + len(account_ending), "account"))

    # Find sender name span if present
    if sender_name:
        sender_idx = normalized.find(sender_name)
        if sender_idx != -1 and not any(s <= sender_idx < e for s, e, _ in spans):
            spans.append((sender_idx, sender_idx + len(sender_name), "sender"))

    # Sort spans by start index
    spans.sort(key=lambda x: x[0])

    # 3. Construct Regex by replacing literal tokens with flexible capture groups
    pattern_parts = []
    last_idx = 0

    for start, end, label in spans:
        # Literal slice before this entity
        literal_chunk = normalized[last_idx:start]
        if literal_chunk:
            escaped = re.escape(literal_chunk)
            # Generalize dates (e.g. 9/25/24, 25/09/2024, 2024-09-25)
            escaped = re.sub(r"\b\d{1,4}[/\-]\d{1,2}[/\-]\d{2,4}\b", lambda m: r"\d{1,4}[/\-]\d{1,2}[/\-]\d{2,4}", escaped)
            # Generalize times (e.g. 14:56, 14:56:00)
            escaped = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", lambda m: r"\d{1,2}:\d{2}(?::\d{2})?", escaped)
            # Generalize escaped spaces
            escaped = re.sub(r"\\\s+", r"\\s+", escaped)
            escaped = re.sub(r"\s+", r"\\s+", escaped)
            # Generalize currencies
            escaped = re.sub(r"(?:جم|ج\\\.م|EGP|LE|جنيه)", lambda m: r"(?:جم|ج\.م|EGP|LE|جنيه)?", escaped)
            # Generalize transaction verbs
            escaped = re.sub(
                r"(?:تم(?:ت)?(?:\s+|\\s\+|\\s\*)*(?:(?:استجاب[ةه])(?:\s+|\\s\+|\\s\*)*)?(?:إيداع|ايداع|تحويل|استلام)|إيداع|ايداع|تحويل|استلام)",
                lambda m: r"(?:تم(?:ت)?\s*(?:استجاب[ةه]\s+)?(?:إيداع|ايداع|تحويل|استلام)|إيداع|ايداع|تحويل|استلام)",
                escaped,
            )
            # Generalize reference keyword tokens
            escaped = re.sub(
                r"(?:(?:ب)?رقم(?:\s+|\\s\+|\\s\*)*(?:المرجع|العملي[ةه]|المعامل[ةه]|التحويل|الحرك[ةه]|الحوال[ةه]|مرجع|عملي[ةه]|معامل[ةه])|(?:ب)?(?:مرجع|معامل[ةه]|عملي[ةه]|حرك[ةه]|حوال[ةه])(?:\s+|\\s\+|\\s\*)*(?:رقم)?|المرجع|مرجع|رقم(?:\s+|\\s\+|\\s\*)*(?:العملي[ةه]|المعامل[ةه]))",
                lambda m: r"(?:ب?مرجع(?:\s*رقم)?|ب?رقم\s*(?:المرجع|العملي[ةه]|المعامل[ةه]|التحويل|الحرك[ةه]|الحوال[ةه])|مرجع|المرجع|معامل[ةه]|عملي[ةه]|\bRef(?:erence)?\b|\bRRN\b|\bTRX\b|\bTxn\b)",
                escaped,
            )
            pattern_parts.append(escaped)

        # Entity capture group
        if label == "amount":
            pattern_parts.append(r"(?P<amount>[\d,]+(?:\.\d{1,2})?)")
        elif label == "ref":
            pattern_parts.append(r"(?P<ref>[A-Za-z0-9_-]+)")
        elif label == "account":
            pattern_parts.append(r"(?P<account>\d+)")
        elif label == "sender":
            if re.search(r"[\u0600-\u06FF]", sender_name or ""):
                pattern_parts.append(r"(?P<sender>[\u0600-\u06FFa-zA-Z\s._-]+)")
            else:
                pattern_parts.append(r"(?P<sender>[A-Za-z\s._-]+)")

        last_idx = end

    # Remaining literal suffix
    suffix = normalized[last_idx:]
    if suffix:
        escaped_suffix = re.escape(suffix)
        escaped_suffix = re.sub(r"\\\s+", r"\\s+", escaped_suffix)
        escaped_suffix = re.sub(r"\s+", r"\\s+", escaped_suffix)
        escaped_suffix = re.sub(r"\b\d{4,6}\b", lambda m: r"\d+", escaped_suffix)
        pattern_parts.append(f"(?:{escaped_suffix})?")

    generated_pattern = "".join(pattern_parts)

    # 4. Self-Validation Loop
    parsed = parse_with_regex_pattern(normalized, generated_pattern)
    if parsed and parsed.amount == amount and parsed.reference_id == ref_id:
        return {
            "success": True,
            "generated_pattern": generated_pattern,
            "detected_bank": bank_name,
            "detected_sender": sender_tag or "",
            "amount_group": "amount",
            "ref_group": "ref",
            "account_group": "account" if account_ending else "",
            "sender_group": "sender" if sender_name else "",
            "preview": {
                "amount": parsed.amount,
                "reference_id": parsed.reference_id,
                "account_ending": parsed.account_ending,
                "sender_name": parsed.sender_name,
                "currency": parsed.currency,
            },
        }

    # 5. Fallback: Adaptive Structural Generalization
    is_arabic = bool(re.search(r"[\u0600-\u06FF]", normalized))
    if is_arabic:
        acc_chunk = r"(?:(?:لحسابكم|بحسابك|لحسابك|في\s+حسابكم|حساب\s*رقم)\s*(?:المنتهي\s*بـ?\s*)?(?P<account>\d+))?.*?" if account_ending else r""
        sender_chunk = r"(?:من\s+(?P<sender>[\u0600-\u06FFa-zA-Z\s._-]+?))?.*?" if sender_name else r""
        structural_pattern = (
            r"(?:تم(?:ت)?\s*(?:استجابة\s+)?(?:إيداع|ايداع|تحويل|استلام)|إيداع|ايداع|تحويل|وارد|استلام)\s*(?:لحظي)?\s*(?:مبلغ|بقيمة|قيمة|بمبلغ)?\s*"
            r"(?P<amount>[\d,]+(?:\.\d{1,2})?)\s*(?:جم|ج\.م|EGP|جنيه)?.*?"
            + acc_chunk
            + sender_chunk
            + r"(?:ب?مرجع(?:\s*رقم)?|ب?رقم\s*(?:المرجع|العملي[ةه]|المعامل[ةه]|التحويل|الحرك[ةه]|الحوال[ةه])|مرجع|المرجع|معامل[ةه]|عملي[ةه]|\bRef(?:erence)?\b|\bRRN\b|\bTRX\b|\bTxn\b)[:\s#]*(?P<ref>[A-Za-z0-9_-]+)"
        )
    else:
        acc_chunk = r"(?:(?:into|to|in)\s+(?:account|A/C|acc)?\s*(?:ending\s+)?(?P<account>\d+))?.*?" if account_ending else r""
        sender_chunk = r"(?:from\s+(?P<sender>[A-Za-z\s._-]+?))?.*?" if sender_name else r""
        structural_pattern = (
            r"(?:credited\s+with|transfer\s+of|received|amount\s+of|paid)\s*(?:EGP\s*)?"
            r"(?P<amount>[\d,]+(?:\.\d{1,2})?).*?"
            + acc_chunk
            + sender_chunk
            + r"(?:\bRef(?:erence)?\b|\bTxn\b|\bRRN\b|\bTRX\b|مرجع)[:\s#]*(?P<ref>[A-Za-z0-9_-]+)"
        )

    parsed_fallback = parse_with_regex_pattern(normalized, structural_pattern)
    if parsed_fallback and parsed_fallback.amount == amount:
        return {
            "success": True,
            "generated_pattern": structural_pattern,
            "detected_bank": bank_name,
            "detected_sender": sender_tag or "",
            "amount_group": "amount",
            "ref_group": "ref",
            "account_group": "account" if account_ending else "",
            "sender_group": "sender" if sender_name else "",
            "preview": {
                "amount": parsed_fallback.amount,
                "reference_id": parsed_fallback.reference_id,
                "account_ending": parsed_fallback.account_ending,
                "sender_name": parsed_fallback.sender_name,
                "currency": parsed_fallback.currency,
            },
        }

    # If all generation failed
    return {
        "success": False,
        "error": "Failed to synthesize a regex pattern that fully validates against this SMS text. Please check the sample format.",
        "generated_pattern": generated_pattern or structural_pattern,
        "preview": None,
    }
