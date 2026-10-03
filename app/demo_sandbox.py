"""
In-Memory Synthetic Sandbox Engine for Motaaked.
Provides realistic Egyptian Bank InstaPay demo data (CIB, NBE, HSBC, QNB, AlexBank, AAIB, Banque du Caire, Faisal).
100% Air-gapped from production database: zero queries, zero mutations, zero wallet deductions.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from app.config import settings
from app.models import UserProfileResponse, utc_now


DEMO_BANKS = [
    {"code": "CIB", "name_en": "Commercial International Bank (CIB)", "name_ar": "البنك التجاري الدولي (CIB)"},
    {"code": "NBE", "name_en": "National Bank of Egypt (NBE)", "name_ar": "البنك الأهلي المصري (NBE)"},
    {"code": "HSBC", "name_en": "HSBC Bank Egypt", "name_ar": "بنك إتش إس بي سي مصر (HSBC)"},
    {"code": "QNB", "name_en": "QNB Alahli", "name_ar": "بنك قطر الوطني الأهلي (QNB)"},
    {"code": "ALEX", "name_en": "Bank of Alexandria", "name_ar": "بنك الإسكندرية"},
    {"code": "AAIB", "name_en": "Arab African International Bank", "name_ar": "البنك العربي الأفريقي الدولي"},
    {"code": "BDC", "name_en": "Banque du Caire", "name_ar": "بنك القاهرة"},
    {"code": "FAISAL", "name_en": "Faisal Islamic Bank of Egypt", "name_ar": "بنك فيصل الإسلامي المصري"},
]

# In-Memory Realistic Synthetic Bank SMS Dataset (Strictly Egyptian Banks, No Mobile Wallets)
SYNTHETIC_TRANSACTIONS = [
    {
        "id": 9001,
        "bank_code": "CIB",
        "bank_name": "CIB",
        "amount": 450.00,
        "currency": "EGP",
        "reference_id": "24100200101",
        "sender_name": "Haitham Refaat",
        "account_ending": "4812",
        "raw_sms": "تم تحويل مبلغ 450.00 جم إلى حسابكم طرف CIB من حساب هاثم رفعت عبر إنستاباي. مرجع: 24100200101 في 2026-10-02 14:15",
        "raw_sms_en": "CIB: You have received EGP 450.00 from Haitham Refaat via InstaPay. Ref: 24100200101 on 2026-10-02 14:15",
        "status": "UNCLAIMED",
        "minutes_ago": 3,
    },
    {
        "id": 9002,
        "bank_code": "NBE",
        "bank_name": "NBE (Al Ahli)",
        "amount": 1250.00,
        "currency": "EGP",
        "reference_id": "24100200102",
        "sender_name": "Sara Ahmed",
        "account_ending": "9934",
        "raw_sms": "تم إضافة 1,250.00 جم لحسابكم بالبنك الأهلي المصري تحويل إنستاباي من سارة أحمد. الرقم المرجعي: 24100200102 في 2026-10-02 14:10",
        "raw_sms_en": "NBE: Received EGP 1,250.00 via InstaPay from Sara Ahmed. Ref: 24100200102 on 2026-10-02 14:10",
        "status": "UNCLAIMED",
        "minutes_ago": 8,
    },
    {
        "id": 9003,
        "bank_code": "HSBC",
        "bank_name": "HSBC Egypt",
        "amount": 320.00,
        "currency": "EGP",
        "reference_id": "24100200103",
        "sender_name": "Mohamed Mahmoud",
        "account_ending": "7719",
        "raw_sms": "إشعار إيداع HSBC: استلام تحويل فوري IPN بمبلغ 320.00 جم بحسابكم طرف HSBC من محمد محمود. كود العملية: 24100200103",
        "raw_sms_en": "HSBC Egypt: IPN Instant Transfer of EGP 320.00 received from Mohamed Mahmoud. Ref: 24100200103",
        "status": "UNCLAIMED",
        "minutes_ago": 15,
    },
    {
        "id": 9004,
        "bank_code": "QNB",
        "bank_name": "QNB Alahli",
        "amount": 890.00,
        "currency": "EGP",
        "reference_id": "24100200104",
        "sender_name": "Omar Khaled",
        "account_ending": "1045",
        "raw_sms": "QNB ALAHLI: تحويل إنستاباي وارد بقيمة 890.00 جم من حساب عمر خالد. المرجع: 24100200104",
        "raw_sms_en": "QNB ALAHLI: Instant Transfer of EGP 890.00 received from Omar Khaled via InstaPay. Ref: 24100200104",
        "status": "CLAIMED",
        "minutes_ago": 28,
    },
    {
        "id": 9005,
        "bank_code": "ALEX",
        "bank_name": "AlexBank",
        "amount": 175.00,
        "currency": "EGP",
        "reference_id": "24100200105",
        "sender_name": "Mona Ali",
        "account_ending": "6201",
        "raw_sms": "بنك الإسكندرية: تم استلام تحويل إنستاباي بقيمة 175.00 جم من منى علي. المرجع: 24100200105",
        "raw_sms_en": "AlexBank: Received InstaPay transfer of EGP 175.00 from Mona Ali. Ref: 24100200105",
        "status": "UNCLAIMED",
        "minutes_ago": 42,
    },
    {
        "id": 9006,
        "bank_code": "AAIB",
        "bank_name": "AAIB",
        "amount": 2100.00,
        "currency": "EGP",
        "reference_id": "24100200106",
        "sender_name": "Tarek Hassan",
        "account_ending": "3388",
        "raw_sms": "AAIB: تم استلام تحويل لحظي إنستاباي بمبلغ 2,100.00 جم من طارق حسن. كود المعاملة: 24100200106",
        "raw_sms_en": "AAIB: You have received EGP 2,100.00 via InstaPay from Tarek Hassan. Ref: 24100200106",
        "status": "UNCLAIMED",
        "minutes_ago": 65,
    },
]


def is_demo_enabled() -> bool:
    """Check whether Sandbox Demo Mode is enabled in settings."""
    return bool(getattr(settings, "DEMO_MODE_ENABLED", True))


def is_demo_passcode(raw: Optional[str]) -> bool:
    """Validate if the provided passcode matches the configured Demo Sandbox passcode."""
    if not is_demo_enabled() or not raw:
        return False
    configured = getattr(settings, "DEMO_PASSCODE", "DEMO-SANDBOX-2026").strip().upper()
    return raw.strip().upper() == configured


def get_demo_user_profile(passcode: Optional[str] = None) -> UserProfileResponse:
    """Returns a synthetic sandbox UserProfileResponse."""
    code = passcode or getattr(settings, "DEMO_PASSCODE", "DEMO-SANDBOX-2026")
    now = utc_now()
    return UserProfileResponse(
        id=999999,
        name="Demo Merchant (Sandbox)",
        email="demo@motaaked.com",
        phone="01000000000",
        passcode=code,
        role="demo",
        account_ending="4812",
        forwarder_api_key="demo_sandbox_forwarder_key_2026",
        credits_balance=250,
        free_credits=100,
        free_credits_days_left=30,
        free_credits_reset_date=(now + timedelta(days=30)).strftime("%Y-%m-%d"),
        free_credits_granted_month=now.strftime("%Y-%m"),
        free_credits_cycle_end=now + timedelta(days=30),
        pass_credits=150,
        pass_credits_expires_at=now + timedelta(days=30),
        lifetime_credits=0,
        subscription_expires_at=now + timedelta(days=30),
        terms_accepted=True,
        is_active=True,
        is_subscription_valid=True,
        cashier_pin="123456",
        approval_status="APPROVED",
        ecommerce_enabled=True,
        created_at=now - timedelta(days=5),
        last_active_at=now,
    )


# In-Memory Dynamic Simulated Watchlist Storage
DEMO_WATCHES: Dict[str, Dict[str, Any]] = {}
_DEMO_WATCH_ID_COUNTER = 9800


def register_demo_watch(
    session_id: str,
    reference_id: str,
    timeout_minutes: int = 30,
    simulation_seconds: int = 30,
) -> Dict[str, Any]:
    """
    Registers a synthetic reference in the in-memory demo watchlist.
    If the reference is a known static initial transaction (e.g. 24100200101),
    it matches immediately.
    If the reference is a custom manual reference (e.g. bfcf3886) or test run,
    it enters PENDING status with a live simulation countdown (default 30 seconds)
    and transitions to MATCHED upon polling after 30 seconds.
    """
    global _DEMO_WATCH_ID_COUNTER
    clean_ref = reference_id.strip()
    key = f"{session_id}:{clean_ref}"
    now = utc_now()

    # Check if reference is in initial static synthetic list
    static_matches = [
        tx for tx in SYNTHETIC_TRANSACTIONS
        if clean_ref == tx["reference_id"]
    ]

    # Pre-existing static transactions match immediately
    if static_matches and clean_ref.startswith("2410020010"):
        matched_item = static_matches[0]
        is_claimed = (matched_item["status"] == "CLAIMED")
        simulated_time = now - timedelta(minutes=matched_item["minutes_ago"])
        credit_data = {
            "id": matched_item["id"],
            "user_id": 999999,
            "bank_code": matched_item["bank_code"],
            "bank_name": matched_item["bank_name"],
            "amount": matched_item["amount"],
            "currency": matched_item["currency"],
            "reference_id": matched_item["reference_id"],
            "sender_name": matched_item["sender_name"],
            "account_ending": matched_item["account_ending"],
            "raw_sms": matched_item["raw_sms"],
            "raw_sms_en": matched_item.get("raw_sms_en", ""),
            "status": matched_item["status"],
            "is_matched": is_claimed,
            "received_at": simulated_time,
            "matched_at": (simulated_time + timedelta(seconds=12)) if is_claimed else now,
            "matched_order_id": None,
            "is_sandbox_demo": True,
        }
        res = {
            "id": matched_item["id"],
            "session_id": session_id,
            "reference_id": matched_item["reference_id"],
            "status": "MATCHED",
            "created_at": now,
            "expires_at": now + timedelta(minutes=timeout_minutes),
            "matched_at": now,
            "matched_credit": credit_data,
            "seconds_remaining": 0,
            "credits_remaining": 250,
            "already_matched": is_claimed,
            "is_sandbox_demo": True,
        }
        DEMO_WATCHES[key] = res
        return res

    # Otherwise (e.g. bfcf3886, or any manual reference, or 30s test simulation):
    _DEMO_WATCH_ID_COUNTER += 1
    watch_id = _DEMO_WATCH_ID_COUNTER

    # Pick bank & details deterministically based on reference
    ref_hash = sum(ord(c) for c in clean_ref)
    banks = [
        ("CIB", "CIB", 750.00, "Haitham Refaat", "4812"),
        ("NBE", "NBE (Al Ahli)", 1250.00, "Sara Ahmed", "9934"),
        ("HSBC", "HSBC Egypt", 320.00, "Mohamed Mahmoud", "7719"),
        ("QNB", "QNB Alahli", 890.00, "Omar Khaled", "1045"),
        ("ALEX", "AlexBank", 175.00, "Mona Ali", "6201"),
        ("AAIB", "AAIB", 2100.00, "Tarek Hassan", "3388"),
    ]
    bank_info = banks[ref_hash % len(banks)]

    watch_record = {
        "id": watch_id,
        "session_id": session_id,
        "reference_id": clean_ref,
        "status": "PENDING",
        "created_at": now,
        "expires_at": now + timedelta(minutes=timeout_minutes),
        "simulation_seconds": simulation_seconds,
        "bank_code": bank_info[0],
        "bank_name": bank_info[1],
        "amount": bank_info[2],
        "sender_name": bank_info[3],
        "account_ending": bank_info[4],
        "matched_at": None,
        "matched_credit": None,
        "seconds_remaining": simulation_seconds,
        "credits_remaining": 250,
        "already_matched": False,
        "is_sandbox_demo": True,
    }
    DEMO_WATCHES[key] = watch_record
    return watch_record


def poll_demo_watchlist(
    session_id: Optional[str] = None,
    reference_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Polls active demo watchlist items. Automatically transitions PENDING watches
    to MATCHED once the simulation countdown (e.g. 30s) elapses.
    """
    now = utc_now()
    items = []
    total_pending = 0
    total_matched = 0

    target_keys = list(DEMO_WATCHES.keys())
    for key in target_keys:
        watch = DEMO_WATCHES.get(key)
        if not watch:
            continue
        if session_id and watch.get("session_id") != session_id:
            continue
        if reference_ids and watch.get("reference_id") not in reference_ids:
            continue

        if watch["status"] == "PENDING":
            elapsed = (now - watch["created_at"]).total_seconds()
            sim_sec = watch.get("simulation_seconds", 30)
            if elapsed >= sim_sec:
                # Transition to MATCHED!
                watch["status"] = "MATCHED"
                matched_time = watch["created_at"] + timedelta(seconds=sim_sec)
                watch["matched_at"] = matched_time
                watch["seconds_remaining"] = 0

                credit_data = {
                    "id": watch["id"],
                    "user_id": 999999,
                    "bank_code": watch["bank_code"],
                    "bank_name": watch["bank_name"],
                    "amount": watch["amount"],
                    "currency": "EGP",
                    "reference_id": watch["reference_id"],
                    "sender_name": watch["sender_name"],
                    "account_ending": watch["account_ending"],
                    "raw_sms": f"تم تحويل مبلغ {watch['amount']:.2f} جم إلى حسابكم طرف {watch['bank_code']} من حساب {watch['sender_name']} عبر إنستاباي. مرجع: {watch['reference_id']}",
                    "raw_sms_en": f"{watch['bank_code']}: You have received EGP {watch['amount']:.2f} from {watch['sender_name']} via InstaPay. Ref: {watch['reference_id']}",
                    "status": "UNCLAIMED",
                    "is_matched": True,
                    "received_at": matched_time,
                    "matched_at": matched_time,
                    "matched_order_id": None,
                    "is_sandbox_demo": True,
                }
                watch["matched_credit"] = credit_data
                total_matched += 1
            else:
                watch["seconds_remaining"] = max(1, int(sim_sec - elapsed))
                total_pending += 1
        elif watch["status"] == "MATCHED":
            watch["seconds_remaining"] = 0
            total_matched += 1

        items.append(watch)

    # If specific reference_ids were requested and not found in DEMO_WATCHES,
    # resolve them against static synthetic transactions
    if reference_ids:
        found_refs = {w["reference_id"] for w in items}
        for ref in reference_ids:
            if ref not in found_refs:
                static_res = search_demo_transactions(reference_id=ref)
                if static_res:
                    s_item = static_res[0]
                    items.append({
                        "id": s_item["id"],
                        "reference_id": s_item["reference_id"],
                        "status": "MATCHED",
                        "created_at": now - timedelta(seconds=10),
                        "expires_at": now + timedelta(minutes=30),
                        "matched_at": s_item.get("matched_at") or now,
                        "matched_credit": s_item,
                        "seconds_remaining": 0,
                        "credits_remaining": 250,
                        "already_matched": s_item.get("is_matched", False),
                        "is_sandbox_demo": True,
                    })
                    total_matched += 1
                else:
                    items.append({
                        "id": 9999,
                        "reference_id": ref,
                        "status": "PENDING",
                        "created_at": now,
                        "expires_at": now + timedelta(minutes=30),
                        "matched_at": None,
                        "matched_credit": None,
                        "seconds_remaining": 30,
                        "credits_remaining": 250,
                        "already_matched": False,
                        "is_sandbox_demo": True,
                    })
                    total_pending += 1

    return {
        "items": items,
        "total_pending": total_pending,
        "total_matched": total_matched,
    }


def dismiss_demo_watch(session_id: Optional[str], watch_id: int) -> bool:
    """Removes a watched card from in-memory demo watches."""
    for key, val in list(DEMO_WATCHES.items()):
        if val.get("id") == watch_id or (session_id and val.get("session_id") == session_id and val.get("id") == watch_id):
            del DEMO_WATCHES[key]
            return True
    return False


def search_demo_transactions(
    reference_id: Optional[str] = None,
    amount: Optional[float] = None,
    sender: Optional[str] = None,
    account_ending: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    In-memory synthetic transaction search for Demo Sandbox mode.
    Returns matched synthetic records with zero database queries.
    Includes matched simulated watches.
    """
    results = []
    clean_ref = reference_id.strip() if reference_id else None

    # First search static transactions
    for tx in SYNTHETIC_TRANSACTIONS:
        # Match by Reference ID (exact or suffix match)
        if clean_ref:
            if clean_ref != tx["reference_id"] and not tx["reference_id"].endswith(clean_ref):
                continue

        # Match by Amount (within floating point precision)
        if amount is not None:
            if abs(tx["amount"] - amount) > 0.01:
                continue

        # Match by Account ending
        if account_ending:
            if tx["account_ending"] != account_ending.strip():
                continue

        # Match by sender
        if sender:
            if sender.strip().lower() not in tx["sender_name"].lower():
                continue

        # Format simulated timestamp
        simulated_time = utc_now() - timedelta(minutes=tx["minutes_ago"])
        is_claimed = (tx["status"] == "CLAIMED")
        results.append({
            "id": tx["id"],
            "user_id": 999999,
            "bank_code": tx["bank_code"],
            "bank_name": tx["bank_name"],
            "amount": tx["amount"],
            "currency": tx["currency"],
            "reference_id": tx["reference_id"],
            "sender_name": tx["sender_name"],
            "account_ending": tx["account_ending"],
            "raw_sms": tx["raw_sms"],
            "raw_sms_en": tx["raw_sms_en"],
            "status": tx["status"],
            "is_matched": is_claimed,
            "received_at": simulated_time,
            "matched_at": (simulated_time + timedelta(seconds=12)) if is_claimed else None,
            "matched_order_id": None,
            "is_sandbox_demo": True,
        })

    # Also search dynamic DEMO_WATCHES if they matched
    if clean_ref:
        for val in DEMO_WATCHES.values():
            if val.get("reference_id") == clean_ref and val.get("status") == "MATCHED" and val.get("matched_credit"):
                mc = val["matched_credit"]
                if not any(r["reference_id"] == clean_ref for r in results):
                    results.append(mc)

    return results


def get_demo_livestream_feed() -> List[Dict[str, Any]]:
    """Returns simulated LiveStream feed transactions with dynamic timestamps."""
    feed = []
    now = utc_now()

    # Prepend any newly MATCHED simulated watches
    for val in DEMO_WATCHES.values():
        if val.get("status") == "MATCHED" and val.get("matched_credit"):
            mc = val["matched_credit"]
            feed.append({
                "id": mc["id"],
                "user_id": 999999,
                "amount": mc["amount"],
                "currency": mc["currency"],
                "reference_id": mc["reference_id"],
                "sender_name": mc["sender_name"],
                "account_ending": mc["account_ending"],
                "bank_code": mc["bank_code"],
                "bank_name": mc["bank_name"],
                "raw_sms": mc["raw_sms"],
                "status": mc["status"],
                "is_matched": mc["is_matched"],
                "matched_at": mc["matched_at"],
                "received_at": mc["received_at"],
                "matched_order_id": None,
                "timestamp": mc["received_at"].strftime("%Y-%m-%d %H:%M:%S") if isinstance(mc["received_at"], datetime) else str(mc["received_at"]),
                "is_sandbox_demo": True,
            })

    for tx in SYNTHETIC_TRANSACTIONS:
        tx_time = now - timedelta(minutes=tx["minutes_ago"])
        is_claimed = (tx["status"] == "CLAIMED")
        feed.append({
            "id": tx["id"],
            "user_id": 999999,
            "amount": tx["amount"],
            "currency": tx["currency"],
            "reference_id": tx["reference_id"],
            "sender_name": tx["sender_name"],
            "account_ending": tx["account_ending"],
            "bank_code": tx["bank_code"],
            "bank_name": tx["bank_name"],
            "raw_sms": tx["raw_sms"],
            "status": tx["status"],
            "is_matched": is_claimed,
            "matched_at": (tx_time + timedelta(seconds=12)) if is_claimed else None,
            "received_at": tx_time,
            "matched_order_id": None,
            "timestamp": tx_time.strftime("%Y-%m-%d %H:%M:%S"),
            "is_sandbox_demo": True,
        })
    return feed


def get_demo_telemetry() -> Dict[str, Any]:
    """Returns simulated phone forwarder telemetry for Demo Mode."""
    now = utc_now()
    return {
        "status": "ONLINE",
        "battery": 94,
        "network": "4G LTE (Vodafone EG)",
        "device": "Samsung Galaxy A54 (Demo Bridge)",
        "uptime": "14d 6h 32m",
        "ping_ms": 22,
        "last_seen_at": now.isoformat(),
        "is_sandbox_demo": True,
    }


