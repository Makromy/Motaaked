import os
from pathlib import Path
import io
import csv
import json
import re
import secrets
import logging

logger = logging.getLogger("instapay")
from datetime import datetime, timedelta, date, time
from typing import Optional, Tuple, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from fastapi import HTTPException, status

from app.models import (
    IncomingCredit,
    PendingOrder,
    User,
    Passcode,
    Package,
    PackageCreate,
    PackageUpdate,
    CreditTransaction,
    WatchedReference,
    WatchedReferenceItem,
    IncomingCreditRead,
    SystemSetting,
    BankPattern,
    BankPatternCreate,
    BankPatternUpdate,
    BankPatternTestRequest,
    BankPatternTestResponse,
    BankPatternAutoGenerateRequest,
    BankPatternAutoGenerateResponse,
    AdminPurchaseReportItem,
    AdminPurchaseReportResponse,
    CreditMovementItem,
    MerchantCreditAuditResponse,
    ForwarderHealthLog,
    ForwarderHeartbeatRequest,
    ForwarderHeartbeatResponse,
    ForwarderTelemetryRead,
    LiveStreamTransactionItem,
    LiveStreamFeedResponse,
    AdminForwarderHealthItem,
    AdminForwarderHealthResponse,
    SupportTicket,
    SupportTicketCreate,
    SupportTicketResponse,
    SupportTicketAdminUpdate,
    SupportTicketListResponse,
    FaqItem,
    FaqItemCreate,
    FaqItemUpdate,
    FaqItemResponse,
    FaqItemListResponse,
    CheckoutSession,
    CreateCheckoutSessionRequest,
    CreateCheckoutSessionResponse,
    utc_now,
)
from app.parser import (
    parse_sms,
    parse_with_regex_pattern,
    extract_group_value,
    auto_generate_regex_from_sms,
    redact_sensitive_financial_data,
    SMSParseError,
)
from app.config import settings


# =========================================================================
# SMS Ingestion & Payment Matching Engine
# =========================================================================

def record_sms_credit(
    db: Session,
    raw_message: str,
    sender: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    user_id: Optional[int] = None,
) -> IncomingCredit:
    """
    Parses an incoming SMS, checks for duplicate reference IDs,
    stores the valid unclaimed credit in incoming_credits with merchant ownership,
    and instantly resolves any pending watchlist trackers for that merchant.
    """
    parsed = None
    # 1. Try active bank regex patterns from database in priority order
    if db is not None:
        try:
            active_patterns = db.query(BankPattern).filter(BankPattern.is_active == True).order_by(BankPattern.priority.asc()).all()
            for bp in active_patterns:
                if bp.sender_filter and sender and bp.sender_filter.upper() not in sender.upper():
                    continue
                match_res = parse_with_regex_pattern(
                    raw_text=raw_message,
                    pattern=bp.pattern,
                    amount_group=bp.amount_group,
                    ref_group=bp.ref_group,
                    account_group=bp.account_group,
                    sender_group=bp.sender_group,
                )
                if match_res:
                    parsed = match_res
                    break
        except Exception:
            parsed = None

    # 2. Fallback to built-in comprehensive heuristic parser
    if not parsed:
        try:
            parsed = parse_sms(raw_message)
        except SMSParseError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"SMS Parsing Failed: {str(exc)}"
            )

    # Check for duplicate reference ID
    existing_credit = db.query(IncomingCredit).filter(
        IncomingCredit.reference_id == parsed.reference_id
    ).first()

    if existing_credit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Credit alert with reference_id '{parsed.reference_id}' has already been processed.",
        )

    # Fallback to associate with merchant by account_ending if user_id is not explicitly provided
    resolved_user_id = user_id
    if resolved_user_id is None and parsed.account_ending:
        matching_users = db.query(User).filter(User.account_ending == parsed.account_ending, User.is_active == True).limit(2).all()
        if len(matching_users) == 1:
            resolved_user_id = matching_users[0].id
        elif len(matching_users) > 1:
            # Ambiguity: Multiple merchants share this 4-digit ending.
            # Do not arbitrarily assign to the first merchant to avoid cross-tenant misattribution.
            resolved_user_id = None

    credit = IncomingCredit(
        user_id=resolved_user_id,
        account_ending=parsed.account_ending,
        amount=parsed.amount,
        currency=parsed.currency,
        sender_name=parsed.sender_name or sender,
        reference_id=parsed.reference_id,
        status="UNCLAIMED",
        received_at=timestamp if timestamp else utc_now(),
        raw_message=parsed.raw_message if (parsed and parsed.raw_message) else redact_sensitive_financial_data(raw_message),
    )

    db.add(credit)
    db.commit()
    db.refresh(credit)

    # Real-time Resolution Hook: Instantly update any live pending watchers
    resolve_watched_references_for_credit(db, credit)

    return credit


def create_pending_order(
    db: Session,
    order_id: str,
    amount: float,
    reference_id: Optional[str] = None,
    user_id: Optional[int] = None,
) -> PendingOrder:
    """
    Registers a new pending order into pending_orders.
    """
    existing_order = db.query(PendingOrder).filter(
        PendingOrder.order_id == order_id
    ).first()

    if existing_order:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order with order_id '{order_id}' already exists with status '{existing_order.status}'."
        )

    order = PendingOrder(
        user_id=user_id,
        order_id=order_id,
        amount=amount,
        reference_id=reference_id.strip() if reference_id else None,
        status="PENDING",
        created_at=utc_now(),
    )

    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def verify_order(
    db: Session,
    order_id: str,
    reference_id: Optional[str] = None,
    merchant_user: Optional[User] = None,
) -> Tuple[bool, PendingOrder, Optional[IncomingCredit], str]:
    """
    Verifies and matches an order with incoming credits in an atomic transaction:
    1. First attempts an exact match on reference_id.
    2. Fallback to matching by exact amount within a strict 30-minute window.
    3. Atomically updates credit to CLAIMED and order to MATCHED.
    Enforces multi-tenant merchant isolation for external store orders,
    while seamlessly preserving automated Top-Up & Gift subscription purchases paid to Admin.
    """
    # Determine if this is a Platform Top-Up / Subscription purchase (paid to Super Admin)
    is_topup_order = (
        order_id.startswith("TOPUP-") or 
        order_id.startswith("GIFT-") or 
        order_id.startswith("RECHARGE-")
    )
    is_admin = False
    if is_topup_order:
        is_admin = True
    elif merchant_user and (merchant_user.id == 0 or getattr(merchant_user, "role", "user") == "admin" or merchant_user.name == "Super Admin"):
        is_admin = True

    # Enforce Global & Merchant E-Commerce On/Off switches and credit balance early
    if not is_admin and not is_topup_order:
        settings_dict = get_system_settings(db)
        if not settings_dict.get("ecommerce_gateway_enabled", True):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="E-Commerce Integration Gateway is currently disabled by portal administration.",
            )
        if merchant_user and not getattr(merchant_user, "ecommerce_enabled", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="E-Commerce integration is disabled for this merchant account. Please contact portal administration.",
            )
        if merchant_user:
            required_cost = settings_dict.get("order_verification_credit_cost", 1)
            if merchant_user.credits_balance < required_cost:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Insufficient merchant credits (Current balance: {merchant_user.credits_balance}, required: {required_cost}). Please recharge your wallet in the portal.",
                )

    order = db.query(PendingOrder).filter(
        PendingOrder.order_id == order_id
    ).first()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found."
        )

    # Idempotent check: if already matched, return success
    if order.status == "MATCHED":
        credit = db.query(IncomingCredit).filter(
            IncomingCredit.id == order.matched_credit_id
        ).first()
        return True, order, credit, "Order is already verified and matched."

    target_ref = (reference_id or order.reference_id or "").strip()
    if reference_id and order.reference_id != reference_id.strip():
        order.reference_id = reference_id.strip()
        try:
            db.commit()
            db.refresh(order)
        except Exception:
            db.rollback()

    matched_credit: Optional[IncomingCredit] = None

    # Determine effective merchant context
    effective_merchant = merchant_user
    if not effective_merchant and getattr(order, "user_id", None):
        effective_merchant = db.query(User).filter(User.id == order.user_id, User.is_active == True).first()

    if not is_admin and not effective_merchant:
        order.status = "REJECTED"
        try:
            db.commit()
            db.refresh(order)
        except Exception:
            db.rollback()
        return False, order, None, "Multi-Tenant Isolation: API Key is not associated with an active merchant account."

    # Multi-Tenant Order Ownership Validation (SEC-002):
    # If order is already owned by a merchant, only that merchant (or super admin) can verify/claim it
    if not is_admin and getattr(order, "user_id", None) and effective_merchant and order.user_id != effective_merchant.id:
        order.status = "REJECTED"
        try:
            db.commit()
            db.refresh(order)
        except Exception:
            db.rollback()
        return False, order, None, "Multi-Tenant Isolation: This order belongs to a different merchant account."

    # Associate order with merchant if known
    if effective_merchant and not getattr(order, "user_id", None):
        try:
            order.user_id = effective_merchant.id
            db.commit()
            db.refresh(order)
        except Exception:
            db.rollback()

    # Step 1: Pre-validation of reference_id to reject claimed, reused, stale, or cross-merchant transfers
    if target_ref:
        # Check A: Was an incoming credit with this reference_id already claimed or matched?
        already_claimed = db.query(IncomingCredit).filter(
            func.lower(IncomingCredit.reference_id) == target_ref.lower(),
            or_(IncomingCredit.status == "CLAIMED", IncomingCredit.is_matched == True)
        ).first()
        if already_claimed:
            order.status = "REJECTED"
            try:
                db.commit()
                db.refresh(order)
            except Exception:
                db.rollback()
            return False, order, None, "This Reference ID has already been claimed and used for a previous transaction. It cannot be reused."

        # Check B: Has another order already matched with this reference_id?
        other_matched_order = db.query(PendingOrder).filter(
            PendingOrder.order_id != order.order_id,
            func.lower(PendingOrder.reference_id) == target_ref.lower(),
            PendingOrder.status == "MATCHED"
        ).first()
        if other_matched_order:
            order.status = "REJECTED"
            try:
                db.commit()
                db.refresh(order)
            except Exception:
                db.rollback()
            return False, order, None, "This Reference ID has already been used for another completed order."

        # Check C: Multi-Tenant Merchant Isolation Check (for external store orders)
        if not is_admin and effective_merchant:
            other_merchant_credit = db.query(IncomingCredit).filter(
                func.lower(IncomingCredit.reference_id) == target_ref.lower(),
                IncomingCredit.user_id.isnot(None),
                IncomingCredit.user_id != effective_merchant.id
            ).first()
            if other_merchant_credit:
                order.status = "REJECTED"
                try:
                    db.commit()
                    db.refresh(order)
                except Exception:
                    db.rollback()
                return False, order, None, "This Reference ID belongs to a transfer received by a different merchant account and cannot be claimed."

            if effective_merchant.account_ending:
                other_acct_credit = db.query(IncomingCredit).filter(
                    func.lower(IncomingCredit.reference_id) == target_ref.lower(),
                    IncomingCredit.account_ending.isnot(None),
                    IncomingCredit.account_ending != effective_merchant.account_ending
                ).first()
                if other_acct_credit:
                    order.status = "REJECTED"
                    try:
                        db.commit()
                        db.refresh(order)
                    except Exception:
                        db.rollback()
                    return False, order, None, "This Reference ID belongs to a transfer received on a different bank account and cannot be claimed."

        # Check D: Does an UNCLAIMED credit exist with this reference_id, but it is outside the verification window?
        window_cutoff = utc_now() - timedelta(minutes=settings.MATCH_WINDOW_MINUTES)
        stale_filter = [
            func.lower(IncomingCredit.reference_id) == target_ref.lower(),
            IncomingCredit.status == "UNCLAIMED",
            IncomingCredit.received_at < window_cutoff
        ]
        if not is_admin and effective_merchant:
            stale_filter.append(
                or_(
                    IncomingCredit.user_id == effective_merchant.id,
                    (IncomingCredit.user_id.is_(None) & (IncomingCredit.account_ending == effective_merchant.account_ending)) if effective_merchant.account_ending else (IncomingCredit.user_id == effective_merchant.id)
                )
            )
        stale_credit = db.query(IncomingCredit).filter(*stale_filter).first()
        if stale_credit:
            order.status = "REJECTED"
            try:
                db.commit()
                db.refresh(order)
            except Exception:
                db.rollback()
            return False, order, None, f"This transfer occurred on {stale_credit.received_at.strftime('%Y-%m-%d %H:%M:%S')}, which is outside the allowed {settings.MATCH_WINDOW_MINUTES}-minute verification window and has expired."

        # Step 2: Attempt exact match by reference_id with unclaimed credit within window
        match_query = db.query(IncomingCredit).filter(
            func.lower(IncomingCredit.reference_id) == target_ref.lower(),
            IncomingCredit.status == "UNCLAIMED",
            IncomingCredit.amount == order.amount,
            IncomingCredit.received_at >= window_cutoff
        )
        if not is_admin and effective_merchant:
            match_query = match_query.filter(
                or_(
                    IncomingCredit.user_id == effective_merchant.id,
                    (IncomingCredit.user_id.is_(None) & (IncomingCredit.account_ending == effective_merchant.account_ending)) if effective_merchant.account_ending else (IncomingCredit.user_id == effective_merchant.id)
                )
            )
        try:
            match_query = match_query.with_for_update()
        except Exception as _lock_err:
            import logging as _lock_log
            _lock_log.getLogger("instapay").warning(
                "[LOCKING] SELECT FOR UPDATE not supported (%s). "
                "Double-spend window exists on SQLite. Migrate to PostgreSQL for production-grade locking.",
                type(_lock_err).__name__,
            )

        matched_credit = match_query.first()

        if not matched_credit:
            # Check if amount mismatched
            amt_query = db.query(IncomingCredit).filter(
                func.lower(IncomingCredit.reference_id) == target_ref.lower(),
                IncomingCredit.status == "UNCLAIMED",
                IncomingCredit.received_at >= window_cutoff
            )
            if not is_admin and effective_merchant:
                amt_query = amt_query.filter(
                    or_(
                        IncomingCredit.user_id == effective_merchant.id,
                        (IncomingCredit.user_id.is_(None) & (IncomingCredit.account_ending == effective_merchant.account_ending)) if effective_merchant.account_ending else (IncomingCredit.user_id == effective_merchant.id)
                    )
                )
            amt_credit = amt_query.first()
            if amt_credit:
                order.status = "REJECTED"
                try:
                    db.commit()
                    db.refresh(order)
                except Exception:
                    db.rollback()
                return False, order, None, f"Transfer amount ({amt_credit.amount} EGP) does not match the order amount ({order.amount} EGP)."

    # Step 3: Fallback to exact amount match within MATCH_WINDOW_MINUTES if no target_ref was provided
    if not matched_credit and not target_ref:
        settings_dict = get_system_settings(db)
        allow_amount_fallback = is_admin or is_topup_order or settings_dict.get("allow_reference_less_order_matching", True)
        if not allow_amount_fallback:
            order.status = "REJECTED"
            try:
                db.commit()
                db.refresh(order)
            except Exception:
                db.rollback()
            return False, order, None, "SMS Reference ID is required to verify this order to prevent payment collision. Please provide the bank SMS reference ID (not InstaPay screenshot)."

        window_cutoff = utc_now() - timedelta(minutes=settings.MATCH_WINDOW_MINUTES)
        fallback_query = db.query(IncomingCredit).filter(
            IncomingCredit.amount == order.amount,
            IncomingCredit.status == "UNCLAIMED",
            IncomingCredit.received_at >= window_cutoff
        )
        if not is_admin and effective_merchant:
            fallback_query = fallback_query.filter(
                or_(
                    IncomingCredit.user_id == effective_merchant.id,
                    (IncomingCredit.user_id.is_(None) & (IncomingCredit.account_ending == effective_merchant.account_ending)) if effective_merchant.account_ending else (IncomingCredit.user_id == effective_merchant.id)
                )
            )
        try:
            fallback_query = fallback_query.with_for_update()
        except Exception as _lock_err:
            import logging as _lock_log
            _lock_log.getLogger("instapay").warning(
                "[LOCKING] SELECT FOR UPDATE not supported (%s). "
                "Double-spend window exists on SQLite. Migrate to PostgreSQL for production-grade locking.",
                type(_lock_err).__name__,
            )

        matched_credit = fallback_query.order_by(IncomingCredit.received_at.asc()).first()

    # Step 4: Atomic update upon matching
    if matched_credit:
        try:
            matched_credit.is_matched = True
            if not matched_credit.matched_at:
                matched_credit.matched_at = utc_now()
            matched_credit.status = "CLAIMED"
            matched_credit.matched_order_id = order.order_id
            if effective_merchant and not matched_credit.user_id:
                matched_credit.user_id = effective_merchant.id

            order.status = "MATCHED"
            order.matched_at = utc_now()
            order.matched_credit_id = matched_credit.id
            if not order.reference_id:
                order.reference_id = matched_credit.reference_id
            if effective_merchant and not getattr(order, "user_id", None):
                order.user_id = effective_merchant.id

            # Deduct verification credits for external store merchant orders
            if not is_admin and effective_merchant and not is_topup_order:
                settings_dict = get_system_settings(db)
                required_cost = settings_dict.get("order_verification_credit_cost", 1)
                if required_cost > 0:
                    deduct_credits(
                        db=db,
                        user=effective_merchant,
                        amount=required_cost,
                        operation="API_ORDER_VERIFY",
                        reference_id=order.reference_id,
                    )

            db.commit()
            db.refresh(order)
            db.refresh(matched_credit)

            return True, order, matched_credit, "Payment successfully verified and matched."
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Atomic transaction failed during matching: {str(exc)}"
            )

    return False, order, None, "No matching incoming transfer found yet. Awaiting bank SMS."


# =========================================================================
# Real-Time Pending Watchlist Engine (Cycle 2)
# =========================================================================

def resolve_watched_references_for_credit(db: Session, credit: IncomingCredit):
    """
    Hook invoked when an SMS is ingested:
    1. Matches pending Top-Up / subscription purchases paid to Admin/System and auto-activates user benefits.
    2. Matches pending customer payment watchlist trackers for recipient merchant.
    """
    clean_ref = credit.reference_id.strip()
    now = utc_now()

    # 1. Auto-claim Top-Up / Gift purchase orders waiting for this reference
    pending_topups = db.query(PendingOrder).filter(
        (PendingOrder.order_id.like("TOPUP-%") | PendingOrder.order_id.like("GIFT-%")),
        PendingOrder.status == "PENDING",
        func.lower(PendingOrder.reference_id) == clean_ref.lower()
    ).all()

    for topup_order in pending_topups:
        try:
            parts = topup_order.order_id.split("-")
            user_id = int(parts[1])
            topup_user = db.query(User).filter(User.id == user_id).first()
            if topup_user and credit.status == "UNCLAIMED":
                verify_and_apply_topup(
                    db=db,
                    user=topup_user,
                    order_id=topup_order.order_id,
                    reference_id=clean_ref
                )
                print(f"[AUTO-CLAIM TOP-UP]: Successfully verified & applied top-up for User {topup_user.name} ({topup_order.order_id})")
        except Exception as e:
            print(f"[AUTO-CLAIM TOP-UP ERROR]: {str(e)}")

    # 2. Resolve pending WatchedReference items
    all_watchers = db.query(WatchedReference).filter(
        func.lower(WatchedReference.reference_id) == clean_ref.lower(),
        WatchedReference.status == "PENDING"
    ).all()

    resolved_count = 0
    for watch in all_watchers:
        is_owner = False
        if watch.user_id and credit.user_id:
            if watch.user_id == credit.user_id:
                is_owner = True
        elif watch.user_id and credit.user_id is None:
            if credit.account_ending:
                w_user = db.query(User).filter(User.id == watch.user_id).first()
                if w_user and w_user.account_ending == credit.account_ending:
                    is_owner = True
        elif watch.user_id is None and credit.user_id is None:
            # Multi-Tenant Isolation (SEC-001): anonymous watches cannot match credits belonging to a registered merchant
            if credit.account_ending:
                owner_exists = db.query(User).filter(User.account_ending == credit.account_ending, User.is_active == True).first()
                if not owner_exists:
                    is_owner = True
            else:
                is_owner = True

        # Also match if the watcher belongs to a user whose top-up order was for this reference
        if not is_owner and watch.user_id:
            user_has_topup = db.query(PendingOrder).filter(
                (PendingOrder.order_id.like(f"TOPUP-{watch.user_id}-%") | PendingOrder.order_id.like(f"GIFT-{watch.user_id}-%")),
                func.lower(PendingOrder.reference_id) == clean_ref.lower()
            ).first()
            if user_has_topup:
                is_owner = True

        if is_owner:
            watch.status = "MATCHED"
            watch.matched_at = now
            watch.matched_credit_id = credit.id
            credit.is_matched = True
            if not credit.matched_at:
                credit.matched_at = now
            resolved_count += 1

    if resolved_count > 0 or credit.is_matched:
        db.commit()
        print(f"[WATCHLIST RESOLVED]: Resolved {resolved_count} pending watches for Ref '{clean_ref}'")



def register_watched_reference(
    db: Session,
    user: Optional[User],
    session_id: Optional[str],
    reference_id: str,
    timeout_minutes: int = 35,
) -> WatchedReference:
    """
    Registers a Reference ID into the live watchlist.
    If the transaction is already on server and belongs to THIS merchant, marks as MATCHED immediately.
    Otherwise creates a PENDING watch with countdown timer (35 mins).
    """
    clean_ref = reference_id.strip()
    sess_id = session_id.strip() if session_id else f"sess_{secrets.token_hex(8)}"
    now = utc_now()

    # 1. Check if credit is already in database and belongs to THIS merchant
    query = db.query(IncomingCredit).filter(
        func.lower(IncomingCredit.reference_id) == clean_ref.lower()
    )
    is_super_admin = user and (user.id == 0 or getattr(user, "role", "user") == "admin" or user.name == "Super Admin")
    if user and not is_super_admin:
        if user.account_ending:
            query = query.filter(
                (IncomingCredit.user_id == user.id) |
                ((IncomingCredit.user_id == None) & (IncomingCredit.account_ending == user.account_ending))
            )
        else:
            query = query.filter(IncomingCredit.user_id == user.id)
    elif not user:
        # Multi-Tenant Isolation (SEC-001): Anonymous watchers cannot match private merchant transactions.
        # They can only match credits where user_id is None and account_ending does not belong to a registered merchant.
        registered_accts = [r[0] for r in db.query(User.account_ending).filter(User.account_ending != None, User.is_active == True).all() if r[0]]
        if registered_accts:
            query = query.filter(
                IncomingCredit.user_id == None,
                ~IncomingCredit.account_ending.in_(registered_accts)
            )
        else:
            query = query.filter(IncomingCredit.user_id == None)

    existing_credit = query.first()

    if existing_credit:
        is_prev_matched = bool(existing_credit.is_matched)
        if not existing_credit.is_matched:
            existing_credit.is_matched = True
            existing_credit.matched_at = now
            try:
                db.commit()
                db.refresh(existing_credit)
            except Exception:
                db.rollback()

        # Check if there was an active pending watch for this reference in this session
        existing_watch = db.query(WatchedReference).filter(
            WatchedReference.session_id == sess_id,
            func.lower(WatchedReference.reference_id) == clean_ref.lower(),
        ).first()

        if existing_watch:
            existing_watch.status = "MATCHED"
            existing_watch.matched_credit_id = existing_credit.id
            existing_watch.matched_at = now
            db.commit()
            db.refresh(existing_watch)
            setattr(existing_watch, "already_matched", is_prev_matched)
            return existing_watch

        # Instant match: Not previously pending, so return object for instant search display without cluttering pending grid
        watch = WatchedReference(
            id=0,
            user_id=user.id if user else None,
            session_id=sess_id,
            reference_id=clean_ref,
            status="MATCHED",
            matched_credit_id=existing_credit.id,
            created_at=now,
            expires_at=now + timedelta(minutes=timeout_minutes),
            matched_at=now,
        )
        watch.matched_credit = existing_credit
        setattr(watch, "already_matched", is_prev_matched)
        return watch

    # 2. Check if already watching this reference in this session
    existing_watch = db.query(WatchedReference).filter(
        WatchedReference.session_id == sess_id,
        func.lower(WatchedReference.reference_id) == clean_ref.lower(),
        WatchedReference.status == "PENDING",
    ).first()

    if existing_watch:
        return existing_watch

    # 3. Create new pending watch
    watch = WatchedReference(
        user_id=user.id if user else None,
        session_id=sess_id,
        reference_id=clean_ref,
        status="PENDING",
        matched_credit_id=None,
        created_at=now,
        expires_at=now + timedelta(minutes=timeout_minutes),
        matched_at=None,
    )
    db.add(watch)
    db.commit()
    db.refresh(watch)
    return watch


def poll_watchlist(
    db: Session,
    user: Optional[User] = None,
    session_id: Optional[str] = None,
    reference_ids: Optional[List[str]] = None,
    watch_ids: Optional[List[int]] = None,
) -> Tuple[List[WatchedReferenceItem], int, int]:
    """
    Batch polls watched references for a session / user.
    Auto-expires timed-out watches and auto-prunes cards older than 35 minutes
    so they clear from Tab 1 (they remain permanently in Tab 2 History).
    """
    now = utc_now()
    cutoff_35m = now - timedelta(minutes=35)

    # Step 1: Auto-prune cards older than 35 minutes or expired
    db.query(WatchedReference).filter(
        (WatchedReference.expires_at < now) |
        (WatchedReference.created_at < cutoff_35m) |
        ((WatchedReference.status == "MATCHED") & (WatchedReference.matched_at < cutoff_35m))
    ).update({"status": "DISMISSED"}, synchronize_session=False)

    db.commit()

    # Step 2: Query active & resolved watchers
    query = db.query(WatchedReference).filter(
        WatchedReference.status.in_(["PENDING", "MATCHED"]),
        WatchedReference.expires_at >= now
    )

    is_super_admin = user and (user.id == 0 or getattr(user, "role", "user") == "admin" or user.name == "Super Admin")

    if user and not is_super_admin:
        query = query.filter(WatchedReference.user_id == user.id)
    elif session_id:
        query = query.filter(WatchedReference.session_id == session_id.strip())
    elif watch_ids:
        query = query.filter(WatchedReference.id.in_(watch_ids))
    elif reference_ids:
        clean_refs = [r.strip().lower() for r in reference_ids if r.strip()]
        query = query.filter(func.lower(WatchedReference.reference_id).in_(clean_refs))

    watches = query.order_by(WatchedReference.created_at.desc()).limit(100).all()

    items: List[WatchedReferenceItem] = []
    total_pending = 0
    total_matched = 0

    for w in watches:
        if w.status == "PENDING":
            total_pending += 1
            seconds_remaining = max(0, int((w.expires_at - now).total_seconds()))
        elif w.status == "MATCHED":
            total_matched += 1
            seconds_remaining = max(0, int((w.expires_at - now).total_seconds())) if w.expires_at else 0
        else:
            seconds_remaining = 0

        matched_read = IncomingCreditRead.model_validate(w.matched_credit) if w.matched_credit else None

        items.append(WatchedReferenceItem(
            id=w.id,
            reference_id=w.reference_id,
            status=w.status,
            created_at=w.created_at,
            expires_at=w.expires_at,
            matched_at=w.matched_at,
            matched_credit=matched_read,
            seconds_remaining=seconds_remaining,
        ))

    return items, total_pending, total_matched


def dismiss_watched_reference(
    db: Session,
    watch_id: Optional[int] = None,
    reference_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user: Optional[User] = None,
) -> bool:
    """
    Dismisses / removes a watched reference card.
    """
    query = db.query(WatchedReference)

    if watch_id:
        target = query.filter(WatchedReference.id == watch_id).first()
        if target:
            target.status = "DISMISSED"
            db.commit()
            return True

    if reference_id and (session_id or user):
        clean_ref = reference_id.strip()
        q = query.filter(func.lower(WatchedReference.reference_id) == clean_ref.lower())
        if session_id:
            q = q.filter(WatchedReference.session_id == session_id.strip())
        if user:
            q = q.filter(WatchedReference.user_id == user.id)
        targets = q.all()
        for t in targets:
            t.status = "DISMISSED"
        db.commit()
        return len(targets) > 0

    return False


# =========================================================================
# User & Passcode Management (Cycle 1 & Registration)
# =========================================================================

def generate_high_entropy_passcode() -> str:
    """Generates a secure 8-character hex passcode in PASS-XXXX-XXXX format (2.8 trillion combinations)."""
    return f"PASS-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"


def validate_passcode_strength(code: str):
    """Rejects known weak or trivial passcodes."""
    clean = code.strip().lower()
    weak_patterns = ["1234", "123456", "0000", "demo", "test", "pass", "admin", "password", "1111", "pass-1234", "pass-demo"]
    if clean in weak_patterns or len(clean) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Weak passcodes are not allowed. Please use a secure code of at least 6 characters or let the system auto-generate one.",
        )


def register_new_merchant(
    db: Session,
    name: str,
    email: str,
    phone: Optional[str] = None,
    account_ending: Optional[str] = None,
) -> Tuple[User, Passcode]:
    """
    Registers a new self-service merchant account with a 30-day access, 25 starter credits,
    and a cryptographically secure auto-generated PASS-XXXX-XXXX passcode.
    """
    clean_name = name.strip()
    clean_email = email.strip().lower()

    if not clean_email or "@" not in clean_email or "." not in clean_email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please provide a valid email address.",
        )

    # Check for existing email
    existing_email_user = db.query(User).filter(func.lower(User.email) == clean_email).first()
    if existing_email_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account registered with email '{clean_email}' already exists. Please sign in or use 'Forgot Passcode'.",
        )

    existing_name_user = db.query(User).filter(func.lower(User.name) == clean_name.lower()).first()
    if existing_name_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A merchant account with name '{clean_name}' already exists. Please choose a unique name.",
        )

    code = generate_high_entropy_passcode()
    # Ensure generated code is unique
    while db.query(Passcode).filter(Passcode.code == code).first() is not None:
        code = generate_high_entropy_passcode()

    sys_settings = get_system_settings(db)
    default_trial_days = int(sys_settings.get("default_trial_days", 180))
    default_ls_trial_days = int(sys_settings.get("default_livestream_trial_days", 5))
    require_approval = bool(sys_settings.get("require_merchant_approval", False))

    user, passcode = generate_user_passcode(
        db=db,
        user_name=clean_name,
        email=clean_email,
        phone=phone.strip() if phone else None,
        duration_days=default_trial_days,
        credits=int(sys_settings.get("monthly_free_credits", 100)),
        custom_code=code,
        account_ending=account_ending.strip() if account_ending else None,
        role="user",
        is_voucher=False,
    )
    if user:
        now = utc_now()
        if require_approval:
            user.approval_status = "PENDING"
            user.is_active = False
            # Hold trial timer until Super Admin approves
            user.subscription_expires_at = now
            user.livestream_expires_at = None
            user.livestream_grace_until = None
        else:
            user.approval_status = "APPROVED"
            user.is_active = True
            if default_ls_trial_days > 0:
                user.livestream_expires_at = now + timedelta(days=default_ls_trial_days)
                user.livestream_grace_until = user.livestream_expires_at + timedelta(days=5)
            else:
                user.livestream_expires_at = None
                user.livestream_grace_until = None
        db.commit()
        db.refresh(user)
    return user, passcode


def generate_user_passcode(
    db: Session,
    user_name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    duration_days: Optional[int] = None,
    credits: Optional[int] = None,
    custom_code: Optional[str] = None,
    account_ending: Optional[str] = None,
    role: str = "user",
    is_voucher: bool = False,
) -> Tuple[Optional[User], Passcode]:
    """
    Creates a user (or unredeemed voucher) and issues an active passcode.
    """
    sys_settings = get_system_settings(db)
    if duration_days is None:
        duration_days = int(sys_settings.get("default_trial_days", 180))
    if credits is None:
        credits = int(sys_settings.get("monthly_free_credits", 100))
    monthly_cap = int(sys_settings.get("monthly_free_credits", 100))

    now = utc_now()
    if custom_code:
        validate_passcode_strength(custom_code)
        code = custom_code.strip()
    else:
        code = generate_high_entropy_passcode()

    # Check for existing passcode uniqueness
    existing_code = db.query(Passcode).filter(Passcode.code == code).first()
    if existing_code:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Passcode code already exists.")

    expires_at = now + timedelta(days=duration_days)

    if is_voucher or ((user_name.strip().lower().startswith("voucher") or user_name.strip().lower().startswith("topup")) and not email):
        passcode = Passcode(
            code=code,
            duration_days=duration_days,
            credits_allocated=credits,
            assigned_user_id=None,
            is_redeemed=False,
            redeemed_at=None,
            expires_at=now + timedelta(days=365),
            created_at=now,
        )
        db.add(passcode)
        db.commit()
        db.refresh(passcode)
        return None, passcode

    # Find or create user
    clean_email = email.strip().lower() if email else None
    user = None
    if clean_email:
        user = db.query(User).filter(func.lower(User.email) == clean_email).first()
    if not user:
        user = db.query(User).filter(User.name == user_name.strip()).first()

    if user:
        if duration_days > 0:
            target_expiry = now + timedelta(days=duration_days)
            if user.subscription_expires_at > now:
                user.subscription_expires_at = max(user.subscription_expires_at, target_expiry)
            else:
                user.subscription_expires_at = target_expiry
            user.pass_credits += credits
            user.pass_credits_expires_at = user.subscription_expires_at
        else:
            user.lifetime_credits += credits

        user.credits_balance = user.free_credits + user.pass_credits + user.lifetime_credits
        from app.models import _random_cashier_pin
        if not getattr(user, "cashier_pin", None):
            user.cashier_pin = _random_cashier_pin()
        if clean_email:
            user.email = clean_email
        if phone:
            user.phone = phone
        if account_ending:
            user.account_ending = account_ending
        if role:
            user.role = role
    else:
        from app.models import _random_cashier_pin
        rand_pin = _random_cashier_pin()

        user = User(
            name=user_name.strip(),
            email=clean_email,
            phone=phone,
            passcode=code,
            account_ending=account_ending,
            role=role,
            subscription_expires_at=expires_at,
            credits_balance=credits,
            free_credits=credits if credits <= monthly_cap else monthly_cap,
            free_credits_granted_month=now.strftime("%Y-%m"),
            free_credits_cycle_start=now,
            pass_credits=max(0, credits - monthly_cap) if duration_days > 0 else 0,
            pass_credits_expires_at=expires_at if duration_days > 0 else None,
            lifetime_credits=max(0, credits - monthly_cap) if duration_days == 0 else 0,
            livestream_expires_at=None,
            livestream_grace_until=None,
            cashier_pin=rand_pin,
            is_active=True,
            created_at=now,
        )
        db.add(user)
        db.flush()

    passcode = Passcode(
        code=code,
        duration_days=duration_days,
        credits_allocated=credits,
        assigned_user_id=user.id,
        is_redeemed=True,
        redeemed_at=now,
        expires_at=expires_at + timedelta(days=365),
        created_at=now,
    )
    db.add(passcode)

    # Log credit allocation
    tx = CreditTransaction(
        user_id=user.id,
        amount=credits,
        operation_type="PASSCODE_ALLOCATION",
        reference_id=code,
        created_at=now,
    )
    db.add(tx)

    db.commit()
    db.refresh(user)
    db.refresh(passcode)
    return user, passcode


def redeem_user_passcode(db: Session, user: User, code: str) -> User:
    """
    Redeems a new passcode, extending the user's subscription and credit balance.
    Enforces non-stacking day pass duration: max(current_expiry, now + pass_duration).
    """
    now = utc_now()
    clean_code = code.strip()

    passcode = db.query(Passcode).filter(Passcode.code == clean_code).first()
    if not passcode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passcode not found.")

    if passcode.is_redeemed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This voucher code has already been redeemed.")

    if passcode.expires_at < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This voucher code has expired (validity was 90 days from purchase).")

    # Apply Duration & Bucket Credits
    if passcode.duration_days > 0:
        target_expiry = now + timedelta(days=passcode.duration_days)
        if user.subscription_expires_at > now:
            user.subscription_expires_at = max(user.subscription_expires_at, target_expiry)
        else:
            user.subscription_expires_at = target_expiry

        # Check if this voucher is for Live Stream POS
        if passcode.credits_allocated == 0 or "LIVE" in passcode.code.upper():
            base_ls = max(user.livestream_expires_at or now, now)
            user.livestream_expires_at = base_ls + timedelta(days=passcode.duration_days)
            user.livestream_grace_until = user.livestream_expires_at + timedelta(days=5)
            if user.subscription_expires_at < user.livestream_expires_at:
                user.subscription_expires_at = user.livestream_expires_at

        user.pass_credits += passcode.credits_allocated
    else:
        # Credits-Only voucher: Requires active validity period
        if user.subscription_expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This voucher contains search credits only and requires an active subscription. Please renew your account validity period first to redeem this voucher.",
            )
        user.lifetime_credits += passcode.credits_allocated

    user.credits_balance = user.free_credits + user.pass_credits + user.lifetime_credits
    passcode.is_redeemed = True
    passcode.redeemed_at = now
    passcode.assigned_user_id = user.id

    # Log transaction
    tx = CreditTransaction(
        user_id=user.id,
        amount=passcode.credits_allocated,
        operation_type="PASSCODE_REDEEM",
        reference_id=clean_code,
        created_at=now,
    )
    db.add(tx)

    db.commit()
    db.refresh(user)
    return user


def check_and_refresh_monthly_free_credits(db: Session, user: Optional[User]) -> bool:
    """
    1st of Month Calendar Reset Engine:
    Checks if the current UTC calendar month (YYYY-MM) is newer than the user's free_credits_granted_month.
    If so, resets the free monthly bucket to exactly 100 credits and sets free_credits_granted_month to current month.
    Also cleans up expired pass_credits if pass_credits_expires_at < now.
    Synchronizes user.credits_balance = free_credits + pass_credits + lifetime_credits.
    """
    if not user or user.id == 0:
        return False

    now = utc_now()
    current_month = now.strftime("%Y-%m")
    updated = False

    # 1. 1st-of-month calendar boundary check
    granted_month = getattr(user, "free_credits_granted_month", None)
    if granted_month != current_month:
        sys_settings = get_system_settings(db)
        monthly_cap = int(sys_settings.get("monthly_free_credits", 100))
        user.free_credits = monthly_cap
        user.free_credits_granted_month = current_month
        user.free_credits_cycle_start = now
        updated = True

    # 2. Check expiration of day pass credits
    if user.pass_credits > 0 and user.pass_credits_expires_at and user.pass_credits_expires_at < now:
        user.pass_credits = 0
        updated = True

    # 3. Sync credits_balance
    total_calc = user.free_credits + user.pass_credits + user.lifetime_credits
    if user.credits_balance != total_calc:
        user.credits_balance = total_calc
        updated = True

    if updated:
        try:
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()

    return updated


def deduct_credits(
    db: Session,
    user: Optional[User],
    amount: int = 1,
    operation: str = "SEARCH_LOOKUP",
    reference_id: Optional[str] = None,
) -> Optional[int]:
    """
    Deducts search/export credits from user wallet using waterfall priority:
    1. Bucket 1: Free Monthly Credits -> consumed first (resets on 1st of each month).
    2. Bucket 2: Day Pass Credits -> consumed second (expires with pass).
    3. Bucket 3: Lifetime Rollover Credits -> consumed last (never expires).
    Admin (user is None or id=0) bypasses credit deductions.
    """
    if not user or user.id == 0 or getattr(user, "role", "user") == "admin" or user.name == "Super Admin":
        return None

    now = utc_now()
    current_month = now.strftime("%Y-%m")

    # 1. Refresh free monthly credits ONLY when a new calendar month actually arrives
    user_month = getattr(user, "free_credits_granted_month", None)
    if user_month is None:
        user.free_credits_granted_month = current_month
    elif user_month != current_month:
        user.free_credits = 100
        user.free_credits_granted_month = current_month
        user.free_credits_cycle_start = now

    # 2. Expire pass credits if pass expired
    if user.pass_credits > 0 and user.pass_credits_expires_at and user.pass_credits_expires_at < now:
        user.pass_credits = 0

    total_available = user.free_credits + user.pass_credits + user.lifetime_credits
    user.credits_balance = total_available

    if total_available < amount:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Insufficient search credits (Available: {total_available}, Required: {amount}). Please top up your wallet in Tab 3.",
        )

    remaining_to_deduct = amount

    # Step 1: Deduct from Free Credits (Bucket 1)
    if user.free_credits > 0:
        deduct_from_free = min(user.free_credits, remaining_to_deduct)
        user.free_credits -= deduct_from_free
        remaining_to_deduct -= deduct_from_free

    # Step 2: Deduct from Day Pass Credits (Bucket 2)
    if remaining_to_deduct > 0 and user.pass_credits > 0:
        deduct_from_pass = min(user.pass_credits, remaining_to_deduct)
        user.pass_credits -= deduct_from_pass
        remaining_to_deduct -= deduct_from_pass

    # Step 3: Deduct from Lifetime Credits (Bucket 3)
    if remaining_to_deduct > 0 and user.lifetime_credits > 0:
        deduct_from_lifetime = min(user.lifetime_credits, remaining_to_deduct)
        user.lifetime_credits -= deduct_from_lifetime
        remaining_to_deduct -= deduct_from_lifetime

    # Sync total
    user.credits_balance = user.free_credits + user.pass_credits + user.lifetime_credits

    tx = CreditTransaction(
        user_id=user.id,
        amount=-amount,
        operation_type=operation,
        reference_id=reference_id,
        created_at=now,
    )
    db.add(tx)
    db.commit()
    db.refresh(user)
    return user.credits_balance
    return user.credits_balance


# =========================================================================
# Transaction Explorer & Single Search
# =========================================================================

def search_single_reference(
    db: Session,
    actor_info: Dict[str, Any],
    reference_id: str,
) -> Tuple[bool, Optional[IncomingCredit], Optional[int], bool]:
    """
    Looks up a single reference ID. Deducts 1 credit if called by a Passcode User.
    Enforces multi-tenant data isolation: regular merchants only match transactions received on their bank account.
    Returns: (found, credit, remaining_credits, already_matched)
    """
    clean_ref = reference_id.strip()
    user = actor_info.get("user")
    is_super_admin = actor_info.get("is_admin", False) or (user and (user.id == 0 or getattr(user, "role", "user") == "admin" or user.name == "Super Admin"))

    # Deduct dynamic search cost for regular users (0 = free)
    search_cost = get_system_setting_int(db, "SEARCH_CREDIT_COST", 1)
    if user and not is_super_admin and search_cost > 0:
        remaining_credits = deduct_credits(db, user, amount=search_cost, operation="SEARCH_LOOKUP", reference_id=clean_ref)
    else:
        remaining_credits = user.credits_balance if user else None

    query = db.query(IncomingCredit).filter(
        func.lower(IncomingCredit.reference_id) == clean_ref.lower()
    )

    if not is_super_admin:
        if not user:
            # Multi-tenant security: Unlinked non-admin key cannot access portal transactions
            return False, None, 0, False
        if user.account_ending:
            query = query.filter(
                (IncomingCredit.user_id == user.id) |
                ((IncomingCredit.user_id == None) & (IncomingCredit.account_ending == user.account_ending))
            )
        else:
            query = query.filter(IncomingCredit.user_id == user.id)

    credit = query.first()

    already_matched = False
    if credit is not None:
        if credit.is_matched:
            already_matched = True
        else:
            credit.is_matched = True
            credit.matched_at = utc_now()
            # Multi-tenant hardening: If an unlinked credit is matched by this merchant, seal tenant ownership
            if credit.user_id is None and user and user.id != 0:
                credit.user_id = user.id
            try:
                db.commit()
                db.refresh(credit)
            except Exception:
                db.rollback()

    return (credit is not None), credit, remaining_credits, already_matched


def query_filtered_transactions(
    db: Session,
    user: Optional[User] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    sender: Optional[str] = None,
    status_filter: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    page: int = 1,
    page_size: int = 50,
    matched_only: bool = True,
) -> Tuple[int, List[IncomingCredit]]:
    """
    Queries incoming_credits within date boundaries, amount limits, and sender filters.
    Enforces multi-tenant data isolation: regular users only see transactions received on their own bank account.
    Default for regular merchants: displays MATCHED transactions (both Claimed/Confirmed and Unclaimed/Unconfirmed).
    Super Admins (id=0 or role='admin') see all transactions.
    When matched_only=False or status_filter='ALL', includes all merchant transfers (used for official PDF statement).
    """
    query = db.query(IncomingCredit)

    # Multi-tenant Isolation & Strict Matched-Only Security:
    is_super_admin = user and (user.id == 0 or getattr(user, "role", "user") == "admin" or user.name == "Super Admin")
    if not is_super_admin:
        if not user:
            return 0, []
        # Multi-tenant data isolation
        if user.account_ending:
            query = query.filter(
                (IncomingCredit.user_id == user.id) |
                ((IncomingCredit.user_id == None) & (IncomingCredit.account_ending == user.account_ending))
            )
        else:
            query = query.filter(IncomingCredit.user_id == user.id)

        # Strict security constraint: regular merchants can NEVER see raw unsearched SMS in Tab 2 without searching/matching
        if matched_only and (status_filter != "ALL"):
            query = query.filter(IncomingCredit.is_matched == True)

    # Enforce maximum 90-day historical query limit
    max_past = date.today() - timedelta(days=90)
    if date_from and date_from < max_past:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Historical date queries are limited to the last 90 days."
        )
    if date_to and date_to < max_past:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Historical date queries are limited to the last 90 days."
        )
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'Date From' cannot be after 'Date To'."
        )

    if date_from:
        start_dt = datetime.combine(date_from, time.min)
        query = query.filter(IncomingCredit.received_at >= start_dt)

    if date_to:
        end_dt = datetime.combine(date_to, time.max)
        query = query.filter(IncomingCredit.received_at <= end_dt)

    if sender:
        query = query.filter(func.lower(IncomingCredit.sender_name).contains(sender.strip().lower()))

    if status_filter:
        clean_st = status_filter.strip().upper()
        if clean_st in ["CLAIMED", "CONFIRMED"]:
            query = query.filter(IncomingCredit.status == "CLAIMED")
        elif clean_st in ["UNCLAIMED", "UNCONFIRMED"]:
            query = query.filter(IncomingCredit.status == "UNCLAIMED")
        elif clean_st == "UNMATCHED":
            query = query.filter(IncomingCredit.is_matched == False)

    if min_amount is not None:
        query = query.filter(IncomingCredit.amount >= min_amount)

    if max_amount is not None:
        query = query.filter(IncomingCredit.amount <= max_amount)

    total = query.count()
    items = query.order_by(IncomingCredit.received_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return total, items


def get_statement_summary(
    db: Session,
    merchant: User,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Computes summary metrics for merchant statement without exposing row-level transaction data.
    """
    query = db.query(IncomingCredit)
    is_super_admin = merchant and (merchant.id == 0 or getattr(merchant, "role", "user") == "admin" or merchant.name == "Super Admin")
    if not is_super_admin:
        if not merchant:
            return {"total_count": 0, "total_amount": 0.0, "currency": "EGP"}
        if merchant.account_ending:
            query = query.filter(
                (IncomingCredit.user_id == merchant.id) |
                ((IncomingCredit.user_id == None) & (IncomingCredit.account_ending == merchant.account_ending))
            )
        else:
            query = query.filter(IncomingCredit.user_id == merchant.id)

    max_past = date.today() - timedelta(days=90)
    if date_from and date_from < max_past:
        date_from = max_past
    if date_to and date_to < max_past:
        date_to = date.today()

    if date_from:
        start_dt = datetime.combine(date_from, time.min)
        query = query.filter(IncomingCredit.received_at >= start_dt)
    if date_to:
        end_dt = datetime.combine(date_to, time.max)
        query = query.filter(IncomingCredit.received_at <= end_dt)

    credits = query.all()
    total_count = len(credits)
    total_volume = sum(c.amount for c in credits)
    claimed_count = sum(1 for c in credits if c.status == "CLAIMED")
    matched_only_count = sum(1 for c in credits if (getattr(c, "is_matched", False) and c.status != "CLAIMED"))
    matched_count = claimed_count + matched_only_count
    unmatched_count = total_count - matched_count

    return {
        "total_count": total_count,
        "total_volume": round(total_volume, 2),
        "matched_count": matched_count,
        "claimed_count": claimed_count,
        "matched_only_count": matched_only_count,
        "unclaimed_count": unmatched_count,
        "unmatched_count": unmatched_count,
        "date_from": date_from.strftime("%Y-%m-%d") if date_from else None,
        "date_to": date_to.strftime("%Y-%m-%d") if date_to else None,
        "export_fee_credits": 10,
    }


def export_transactions_csv(
    db: Session,
    actor_info: Dict[str, Any],
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    sender: Optional[str] = None,
    status_filter: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
) -> str:
    """
    Generates a CSV export of filtered transactions.
    Includes UTF-8 BOM (\ufeff) for seamless Microsoft Excel Arabic support.
    """
    user = actor_info.get("user")
    total, items = query_filtered_transactions(
        db=db,
        user=user,
        date_from=date_from,
        date_to=date_to,
        sender=sender,
        status_filter=status_filter,
        min_amount=min_amount,
        max_amount=max_amount,
        page=1,
        page_size=5000,
    )

    output = io.StringIO()
    output.write("\ufeff")

    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "ID",
        "Reference ID",
        "Amount",
        "Currency",
        "Status",
        "Sender Name",
        "Account Ending",
        "Received Date (UTC)",
        "Matched Order ID",
        "Raw SMS Alert",
    ])

    for item in items:
        writer.writerow([
            item.id,
            item.reference_id,
            f"{item.amount:.2f}",
            item.currency,
            item.status,
            item.sender_name or "",
            item.account_ending or "",
            item.received_at.strftime("%Y-%m-%d %H:%M:%S"),
            item.matched_order_id or "",
            item.raw_message,
        ])

    return output.getvalue()


# =========================================================================
# Automated InstaPay Top-Up & Self-Service Monetization (Cycle 4)
# =========================================================================

# =========================================================================
# Dynamic Package & Pricing Management (CRUD)
# =========================================================================

def list_packages(db: Session, include_inactive: bool = False) -> List[Package]:
    """Returns packages sorted by sort_order. If include_inactive is False, returns only visible packages."""
    query = db.query(Package)
    if not include_inactive:
        query = query.filter(Package.is_active == True)
    return query.order_by(Package.sort_order.asc(), Package.id.asc()).all()


def get_package_by_id(db: Session, pkg_id: int) -> Package:
    """Retrieves a package by primary key ID or raises 404."""
    pkg = db.query(Package).filter(Package.id == pkg_id).first()
    if not pkg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Package with ID {pkg_id} not found.")
    return pkg


def get_package_by_plan_id(db: Session, plan_id: str) -> Optional[Package]:
    """Retrieves a package by plan_id identifier."""
    return db.query(Package).filter(func.lower(Package.plan_id) == plan_id.strip().lower()).first()


def create_package(db: Session, payload: PackageCreate) -> Package:
    """Creates a new package with pricing, optional discount before/after, and benefits."""
    clean_plan_id = payload.plan_id.strip().lower()
    existing = get_package_by_plan_id(db, clean_plan_id)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Package plan_id '{clean_plan_id}' already exists.")

    features_json = json.dumps(payload.features) if payload.features else "[]"
    pkg = Package(
        plan_id=clean_plan_id,
        name=payload.name.strip(),
        badge=payload.badge.strip() if payload.badge else None,
        price=payload.price,
        original_price=payload.original_price,
        discount_label=payload.discount_label.strip() if payload.discount_label else None,
        duration_days=payload.duration_days,
        credits=payload.credits,
        features=features_json,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return pkg


def update_package(db: Session, pkg_id: int, payload: PackageUpdate) -> Package:
    """Updates an existing package's parameters, pricing, discount, and visibility."""
    pkg = get_package_by_id(db, pkg_id)

    if payload.name is not None:
        pkg.name = payload.name.strip()
    if payload.badge is not None:
        pkg.badge = payload.badge.strip() if payload.badge else None
    if payload.price is not None:
        pkg.price = payload.price
    if payload.original_price is not None:
        pkg.original_price = payload.original_price
    if payload.discount_label is not None:
        pkg.discount_label = payload.discount_label.strip() if payload.discount_label else None
    if payload.duration_days is not None:
        pkg.duration_days = payload.duration_days
    if payload.credits is not None:
        pkg.credits = payload.credits
    if payload.features is not None:
        pkg.features = json.dumps(payload.features)
    if payload.is_active is not None:
        pkg.is_active = payload.is_active
    if payload.sort_order is not None:
        pkg.sort_order = payload.sort_order

    pkg.updated_at = utc_now()
    db.commit()
    db.refresh(pkg)
    return pkg


def toggle_package_active(db: Session, pkg_id: int) -> Package:
    """1-click toggle to Hide or Show a package."""
    pkg = get_package_by_id(db, pkg_id)
    pkg.is_active = not pkg.is_active
    pkg.updated_at = utc_now()
    db.commit()
    db.refresh(pkg)
    return pkg


def delete_package(db: Session, pkg_id: int) -> bool:
    """Deletes a package permanently."""
    pkg = get_package_by_id(db, pkg_id)
    db.delete(pkg)
    db.commit()
    return True


# =========================================================================
# Automated InstaPay Top-Up & Self-Service Monetization (Cycle 4)
# =========================================================================

PLANS_CONFIG_FALLBACK = {
    "plan_30d": {
        "name": "30 Days Subscription + 100 Credits",
        "amount": 30.00,
        "duration_days": 30,
        "credits": 100,
    },
    "plan_90d": {
        "name": "90 Days Subscription + 350 Credits",
        "amount": 80.00,
        "duration_days": 90,
        "credits": 350,
    },
    "plan_200pts": {
        "name": "+200 Extra Search Credits",
        "amount": 25.00,
        "duration_days": 0,
        "credits": 200,
    },
}


def initiate_topup_order(
    db: Session,
    user: User,
    plan_id: str,
    purchase_type: str = "direct",
    recipient_email: Optional[str] = None,
) -> Tuple[PendingOrder, Dict[str, Any]]:
    """
    Registers a pending order for purchasing subscription/credits (direct or gift code) via InstaPay.
    Dynamically loads plan pricing from the packages database.
    """
    pkg = get_package_by_plan_id(db, plan_id)
    if pkg and pkg.is_active:
        plan_amount = pkg.price
        plan_name = pkg.name
        plan_dict = {
            "name": pkg.name,
            "amount": pkg.price,
            "duration_days": pkg.duration_days,
            "credits": pkg.credits,
        }
    else:
        fallback = PLANS_CONFIG_FALLBACK.get(plan_id.strip().lower())
        if not fallback:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid plan '{plan_id}'. Please select an active plan.",
            )
        plan_amount = fallback["amount"]
        plan_name = fallback["name"]
        plan_dict = fallback

    is_gift = (purchase_type.strip().lower() == "gift")

    # Enforce: If account validity has expired, user CANNOT buy credit-only packages (duration_days == 0) directly or as gift
    if plan_dict.get("duration_days", 0) == 0:
        if user.subscription_expires_at < utc_now():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your account Validity Period has expired. Please renew your Validity Period first before purchasing extra search credits.",
            )

    prefix = "GIFT" if is_gift else "TOPUP"
    order_id = f"{prefix}-{user.id}-{secrets.token_hex(4).upper()}"

    order = create_pending_order(
        db=db,
        order_id=order_id,
        amount=plan_amount,
        user_id=user.id,
    )

    return order, plan_dict


def verify_and_apply_topup(
    db: Session,
    user: User,
    order_id: str,
    reference_id: Optional[str] = None,
    recipient_email: Optional[str] = None,
    server_url: Optional[str] = None,
) -> Tuple[bool, User, float, str, Optional[str], Optional[datetime], str]:
    """
    Verifies payment for top-up order via InstaPay reference ID or amount fallback.
    - If Direct Purchase: Atomically applies the subscription extension & search credits to current user.
    - If Gift Purchase: Generates a 90-day one-time voucher code (PASS-XXXX-XXXX) and emails it to the buyer/recipient.
    Returns: (is_verified, user, amount, message, voucher_code, voucher_expires_at, purchase_type)
    """
    from app import email_service

    is_admin = user and (user.id == 0 or getattr(user, "role", "user") == "admin" or user.name == "Super Admin")

    # Multi-Tenant Ownership Check (SEC-003): Ensure the top-up order was initiated by this user
    order = db.query(PendingOrder).filter(PendingOrder.order_id == order_id).first()
    expected_uid = None
    if order:
        expected_uid = getattr(order, "user_id", None)
        if not expected_uid and (order.order_id.startswith("TOPUP-") or order.order_id.startswith("GIFT-")):
            try:
                expected_uid = int(order.order_id.split("-")[1])
            except Exception:
                pass

    if expected_uid is not None and expected_uid != user.id and not is_admin:
        ord_st = order.status if order else "REJECTED"
        p_type = "gift" if (order and order.order_id.startswith("GIFT-")) else "direct"
        return False, user, order.amount if order else 0.0, "Multi-Tenant Isolation: You are not authorized to verify or claim another merchant's top-up order.", None, None, p_type, ord_st

    is_verified, order, matched_credit, msg = verify_order(
        db=db,
        order_id=order_id,
        reference_id=reference_id,
        merchant_user=user,
    )

    if not is_verified or not matched_credit:
        ord_st = order.status if order else "PENDING"
        p_type = "gift" if (order and order.order_id.startswith("GIFT-")) else "direct"
        return False, user, order.amount if order else 0.0, msg, None, None, p_type, ord_st

    # Identify package benefits dynamically strictly from the Database packages table
    amount = order.amount
    now = utc_now()
    duration_days = 0
    credits = 0
    plan_name = "Custom Package"

    matching_pkg = db.query(Package).filter(Package.price == amount).order_by(Package.sort_order.asc()).first()
    if matching_pkg:
        duration_days = matching_pkg.duration_days
        credits = matching_pkg.credits
        plan_name = matching_pkg.name
    else:
        # Dynamic fallback based on general 1 EGP = 3 credits ratio
        duration_days = 30
        credits = max(1, int(amount * 3))
        plan_name = f"Custom {amount:.2f} EGP Pack"

    is_gift = order.order_id.startswith("GIFT-")

    if is_gift:
        # Generate 90-day One-Time Gift Voucher Code
        voucher_code = generate_high_entropy_passcode()
        while db.query(Passcode).filter(Passcode.code == voucher_code).first() is not None:
            voucher_code = generate_high_entropy_passcode()

        voucher_expires_at = now + timedelta(days=90)

        passcode = Passcode(
            code=voucher_code,
            duration_days=duration_days,
            credits_allocated=credits,
            assigned_user_id=None,
            is_redeemed=False,
            redeemed_at=None,
            expires_at=voucher_expires_at,
            created_at=now,
        )
        db.add(passcode)

        # Log gift voucher purchase transaction for exact reporting audit
        tx = CreditTransaction(
            user_id=user.id,
            amount=0,
            operation_type="GIFT_VOUCHER_PURCHASE",
            reference_id=f"{order.order_id}:{voucher_code}",
            created_at=now,
        )
        db.add(tx)
        db.commit()
        db.refresh(passcode)

        # Determine target email for voucher dispatch
        target_email = recipient_email.strip().lower() if (recipient_email and "@" in recipient_email) else getattr(user, "email", None)
        if target_email:
            email_service.send_gift_voucher_email(
                to_email=target_email,
                user_name=user.name,
                voucher_code=voucher_code,
                plan_name=plan_name,
                credits=credits,
                duration_days=duration_days,
                expires_at_str=voucher_expires_at.strftime("%Y-%m-%d"),
                server_url=server_url or "http://localhost:8000",
            )

        return True, user, order.amount, f"Gift voucher {voucher_code} generated and emailed to {target_email or 'your account'}!", voucher_code, voucher_expires_at, "gift", "MATCHED"

    # Direct Purchase on current user account
    is_livestream_pkg = (matching_pkg is not None and ("livestream" in matching_pkg.plan_id.lower() or "live stream" in matching_pkg.name.lower()))
    if is_livestream_pkg:
        base_ls = max(user.livestream_expires_at or now, now)
        user.livestream_expires_at = base_ls + timedelta(days=duration_days or 30)
        user.livestream_grace_until = user.livestream_expires_at + timedelta(days=5)
        # Also guarantee active portal subscription for the same duration
        if user.subscription_expires_at < user.livestream_expires_at:
            user.subscription_expires_at = user.livestream_expires_at

    if duration_days > 0:
        target_expiry = now + timedelta(days=duration_days)
        if user.subscription_expires_at > now:
            user.subscription_expires_at = max(user.subscription_expires_at, target_expiry)
        else:
            user.subscription_expires_at = target_expiry

        user.pass_credits += credits
        user.pass_credits_expires_at = user.subscription_expires_at
    else:
        user.lifetime_credits += credits
        if user.subscription_expires_at < now:
            user.subscription_expires_at = now + timedelta(days=30)

    user.credits_balance = user.free_credits + user.pass_credits + user.lifetime_credits

    # Log credit transaction
    tx = CreditTransaction(
        user_id=user.id,
        amount=credits,
        operation_type="INSTAPAY_TOPUP",
        reference_id=order.order_id,
        created_at=now,
    )
    db.add(tx)
    db.commit()
    db.refresh(user)

    success_msg = f"Successfully activated Live Stream POS Terminal ({duration_days} days + 5 days grace period)!" if is_livestream_pkg else f"Successfully activated {credits} credits and {duration_days} days pass!"
    return True, user, order.amount, success_msg, None, None, "direct", "MATCHED"


# =========================================================================
# Admin Purchases & Subscriptions Reporting Explorer
# =========================================================================

def get_admin_purchases_report(
    db: Session,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    purchase_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> AdminPurchaseReportResponse:
    """
    Generates a full transaction & subscription report for Super Admin with metrics, filters, and voucher statuses.
    """
    query = db.query(PendingOrder).filter(
        or_(
            PendingOrder.order_id.like("TOPUP-%"),
            PendingOrder.order_id.like("GIFT-%")
        )
    )

    if date_from:
        start_dt = datetime.combine(date_from, time.min)
        query = query.filter(PendingOrder.created_at >= start_dt)
    if date_to:
        end_dt = datetime.combine(date_to, time.max)
        query = query.filter(PendingOrder.created_at <= end_dt)

    if purchase_type:
        pt = purchase_type.strip().lower()
        if pt == "gift":
            query = query.filter(PendingOrder.order_id.like("GIFT-%"))
        elif pt == "direct":
            query = query.filter(PendingOrder.order_id.like("TOPUP-%"))

    if status_filter:
        query = query.filter(PendingOrder.status == status_filter.strip().upper())

    all_orders = query.order_by(PendingOrder.created_at.desc()).all()

    # Preload users, packages, passcodes, and gift transactions
    all_users = {u.id: u for u in db.query(User).all()}
    all_packages = db.query(Package).all()
    pkg_by_amount = {p.price: p.name for p in all_packages}
    passcodes_by_code = {pc.code: pc for pc in db.query(Passcode).all()}

    all_gift_txs = {}
    for tx in db.query(CreditTransaction).filter(CreditTransaction.operation_type == "GIFT_VOUCHER_PURCHASE").all():
        if tx.reference_id and ":" in tx.reference_id:
            ord_k, v_code = tx.reference_id.split(":", 1)
            all_gift_txs[ord_k] = v_code

    report_items = []
    total_rev = 0.0
    direct_count = 0
    gift_count = 0

    for ord_item in all_orders:
        is_gift_ord = ord_item.order_id.startswith("GIFT-")
        p_type = "gift" if is_gift_ord else "direct"
        
        if ord_item.status == "MATCHED":
            total_rev += ord_item.amount

        if is_gift_ord:
            gift_count += 1
        else:
            direct_count += 1

        # Extract user ID
        merchant_name = "Unknown Merchant"
        merchant_email = None
        merchant_id = None
        user_expiry = None

        parts = ord_item.order_id.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            merchant_id = int(parts[1])
            if merchant_id in all_users:
                u = all_users[merchant_id]
                merchant_name = u.name
                merchant_email = u.email
                user_expiry = u.subscription_expires_at

        # Determine plan name
        p_name = pkg_by_amount.get(ord_item.amount, f"Top-Up ({ord_item.amount:.2f} EGP)")

        # Find corresponding voucher if gift
        v_code = None
        v_redeemed = None
        v_redeemed_by = None
        v_redeemed_at = None
        item_expiry = user_expiry

        if is_gift_ord:
            exact_v_code = all_gift_txs.get(ord_item.order_id)
            if exact_v_code and exact_v_code in passcodes_by_code:
                pc = passcodes_by_code[exact_v_code]
                v_code = pc.code
                v_redeemed = pc.is_redeemed
                v_redeemed_at = pc.redeemed_at
                item_expiry = pc.expires_at
                if pc.is_redeemed and pc.assigned_user_id and pc.assigned_user_id in all_users:
                    v_redeemed_by = all_users[pc.assigned_user_id].name

        item = AdminPurchaseReportItem(
            id=ord_item.id,
            order_id=ord_item.order_id,
            merchant_id=merchant_id,
            merchant_name=merchant_name,
            merchant_email=merchant_email,
            plan_name=p_name,
            purchase_type=p_type,
            amount=ord_item.amount,
            currency="EGP",
            reference_id=ord_item.reference_id,
            status=ord_item.status,
            purchase_date=ord_item.matched_at or ord_item.created_at,
            expiry_date=item_expiry,
            voucher_code=v_code,
            voucher_redeemed=v_redeemed,
            voucher_redeemed_by=v_redeemed_by,
            voucher_redeemed_at=v_redeemed_at,
        )

        # Search filter
        if search:
            s = search.strip().lower()
            match = (
                s in ord_item.order_id.lower()
                or s in merchant_name.lower()
                or (merchant_email and s in merchant_email.lower())
                or (ord_item.reference_id and s in ord_item.reference_id.lower())
                or (v_code and s in v_code.lower())
                or (v_redeemed_by and s in v_redeemed_by.lower())
            )
            if not match:
                continue

        report_items.append(item)

    total_items = len(report_items)
    start_idx = (page - 1) * page_size
    paged_items = report_items[start_idx : start_idx + page_size]

    return AdminPurchaseReportResponse(
        total=total_items,
        page=page,
        page_size=page_size,
        total_revenue_egp=round(total_rev, 2),
        total_direct_purchases=direct_count,
        total_gift_vouchers=gift_count,
        items=paged_items,
    )


def export_admin_purchases_csv(
    db: Session,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    purchase_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
) -> str:
    """Generates CSV string of admin purchase transactions for Excel export."""
    report = get_admin_purchases_report(
        db=db,
        date_from=date_from,
        date_to=date_to,
        purchase_type=purchase_type,
        status_filter=status_filter,
        search=search,
        page=1,
        page_size=10000,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Order ID",
        "Purchase Type",
        "Merchant Name",
        "Merchant Email",
        "Plan Name",
        "Amount (EGP)",
        "SMS Reference ID",
        "Status",
        "Purchase Date (UTC)",
        "Expiry Date (UTC)",
        "Gift Voucher Code",
        "Voucher Redeemed?",
        "Redeemed By",
        "Redeemed At (UTC)",
    ])

    for row in report.items:
        writer.writerow([
            row.order_id,
            "Direct Top-Up" if row.purchase_type == "direct" else "Gift Voucher Code",
            row.merchant_name,
            row.merchant_email or "",
            row.plan_name,
            f"{row.amount:.2f}",
            row.reference_id or "",
            row.status,
            row.purchase_date.strftime("%Y-%m-%d %H:%M:%S") if row.purchase_date else "",
            row.expiry_date.strftime("%Y-%m-%d") if row.expiry_date else "",
            row.voucher_code or "",
            "Yes" if row.voucher_redeemed else ("No" if row.voucher_code else "N/A"),
            row.voucher_redeemed_by or "",
            row.voucher_redeemed_at.strftime("%Y-%m-%d %H:%M:%S") if row.voucher_redeemed_at else "",
        ])

    return output.getvalue()


# =========================================================================
# Admin Analytics & User Adjustments (Cycle 4)
# =========================================================================

def get_admin_metrics(db: Session) -> Dict[str, Any]:
    """
    Calculates aggregate platform metrics for Admin dashboard.
    """
    total_tx = db.query(IncomingCredit).count()
    vol = db.query(func.coalesce(func.sum(IncomingCredit.amount), 0.0)).scalar() or 0.0
    unclaimed = db.query(IncomingCredit).filter(IncomingCredit.status == "UNCLAIMED").count()
    claimed = db.query(IncomingCredit).filter(IncomingCredit.status == "CLAIMED").count()
    users_cnt = db.query(User).count()
    passcodes_cnt = db.query(Passcode).count()
    active_watches = db.query(WatchedReference).filter(WatchedReference.status == "PENDING").count()

    return {
        "total_transactions": total_tx,
        "total_volume_egp": float(vol),
        "unclaimed_credits": unclaimed,
        "claimed_credits": claimed,
        "total_users": users_cnt,
        "total_passcodes": passcodes_cnt,
        "active_watches": active_watches,
    }


def admin_adjust_user_quota(
    db: Session,
    user_id: int,
    add_credits: int = 0,
    add_days: int = 0,
    set_free_credits: Optional[int] = None,
    set_pass_credits: Optional[int] = None,
    set_lifetime_credits: Optional[int] = None,
    set_subscription_days: Optional[int] = None,
    set_livestream_days: Optional[int] = None,
    add_livestream_days: int = 0,
    set_role: Optional[str] = None,
) -> User:
    """
    Admin: Directly adjusts a user's credit buckets, expiration days, Live Stream POS access, or permission role.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if set_role and set_role.strip().lower() in ["user", "admin", "merchant"]:
        clean_role = "admin" if set_role.strip().lower() == "admin" else "user"
        user.role = clean_role

    now = utc_now()
    if set_subscription_days is not None:
        user.subscription_expires_at = now + timedelta(days=set_subscription_days)
    elif add_days != 0:
        if user.subscription_expires_at > now:
            user.subscription_expires_at += timedelta(days=add_days)
        else:
            user.subscription_expires_at = now + timedelta(days=add_days)

    # Live Stream POS Terminal Adjustment
    if set_livestream_days is not None:
        if set_livestream_days == 0:
            user.livestream_expires_at = None
            user.livestream_grace_until = None
        else:
            user.livestream_expires_at = now + timedelta(days=set_livestream_days)
            user.livestream_grace_until = user.livestream_expires_at + timedelta(days=5)
            if user.subscription_expires_at < user.livestream_expires_at:
                user.subscription_expires_at = user.livestream_expires_at
    elif add_livestream_days != 0:
        base_ls = max(user.livestream_expires_at or now, now)
        user.livestream_expires_at = base_ls + timedelta(days=add_livestream_days)
        user.livestream_grace_until = user.livestream_expires_at + timedelta(days=5)
        if user.subscription_expires_at < user.livestream_expires_at:
            user.subscription_expires_at = user.livestream_expires_at

    if set_free_credits is not None:
        user.free_credits = max(0, set_free_credits)

    if set_pass_credits is not None:
        user.pass_credits = max(0, set_pass_credits)
        if user.pass_credits > 0 and (not user.pass_credits_expires_at or user.pass_credits_expires_at < now):
            user.pass_credits_expires_at = user.subscription_expires_at

    if set_lifetime_credits is not None:
        user.lifetime_credits = max(0, set_lifetime_credits)

    if add_credits != 0:
        user.lifetime_credits = max(0, user.lifetime_credits + add_credits)
        tx = CreditTransaction(
            user_id=user.id,
            amount=add_credits,
            operation_type="ADMIN_ADJUSTMENT",
            reference_id="ADMIN_OVERRIDE",
            created_at=now,
        )
        db.add(tx)

    user.credits_balance = user.free_credits + user.pass_credits + user.lifetime_credits

    db.commit()
    db.refresh(user)
    return user


def admin_grant_livestream(
    db: Session,
    user_id: int,
    days: int = 30,
    reason: Optional[str] = "ADMIN_COMPLIMENTARY",
) -> User:
    """
    Super Admin: Directly grants or extends a merchant's Live Stream POS Terminal session.
    Calculates from max(current_expiry, now) + days, sets 5-day grace period, and ensures base subscription validity.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found.")

    now = utc_now()
    base_ls = max(user.livestream_expires_at or now, now)
    user.livestream_expires_at = base_ls + timedelta(days=days)
    user.livestream_grace_until = user.livestream_expires_at + timedelta(days=5)

    # Ensure general portal subscription is also valid at least until live stream expires
    if user.subscription_expires_at < user.livestream_expires_at:
        user.subscription_expires_at = user.livestream_expires_at

    tx = CreditTransaction(
        user_id=user.id,
        amount=0,
        operation_type="LIVESTREAM_ADMIN_GRANT",
        reference_id=f"GRANT:{days}D:{reason or 'ADMIN'}",
        created_at=now,
    )
    db.add(tx)
    db.commit()
    db.refresh(user)
    return user


def admin_approve_merchant(
    db: Session,
    user_id: int,
    admin_user: Optional[User] = None
) -> User:
    """
    Super Admin: Approves a pending merchant account.
    Activates the account and starts their portal trial and Live Stream trial from the moment of approval.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found.")

    sys_settings = get_system_settings(db)
    default_trial_days = int(sys_settings.get("default_trial_days", 180))
    default_ls_trial_days = int(sys_settings.get("default_livestream_trial_days", 5))

    now = utc_now()
    user.approval_status = "APPROVED"
    user.is_active = True
    user.subscription_expires_at = now + timedelta(days=default_trial_days)

    if default_ls_trial_days > 0:
        user.livestream_expires_at = now + timedelta(days=default_ls_trial_days)
        user.livestream_grace_until = user.livestream_expires_at + timedelta(days=5)
    else:
        user.livestream_expires_at = None
        user.livestream_grace_until = None

    monthly_free_credits = int(sys_settings.get("monthly_free_credits", 100))
    if getattr(user, "free_credits", 0) < monthly_free_credits:
        user.free_credits = monthly_free_credits
        user.credits_balance = user.free_credits + user.pass_credits + user.lifetime_credits

    admin_name = admin_user.name if admin_user else "Super Admin"
    tx = CreditTransaction(
        user_id=user.id,
        amount=0,
        operation_type="MERCHANT_ADMIN_APPROVED",
        reference_id=f"APPROVED:BY:{admin_name}",
        created_at=now,
    )
    db.add(tx)
    db.commit()
    db.refresh(user)
    return user


def admin_reject_merchant(
    db: Session,
    user_id: int,
    admin_user: Optional[User] = None
) -> User:
    """
    Super Admin: Rejects / deactivates a pending merchant account.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found.")

    now = utc_now()
    user.approval_status = "REJECTED"
    user.is_active = False

    admin_name = admin_user.name if admin_user else "Super Admin"
    tx = CreditTransaction(
        user_id=user.id,
        amount=0,
        operation_type="MERCHANT_ADMIN_REJECTED",
        reference_id=f"REJECTED:BY:{admin_name}",
        created_at=now,
    )
    db.add(tx)
    db.commit()
    db.refresh(user)
    return user


def get_system_setting_int(db: Session, key: str, default: int = 0) -> int:
    """
    Helper to retrieve integer system setting value.
    """
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row and row.value is not None:
        try:
            return int(float(str(row.value).strip()))
        except Exception:
            return default
    return default


def get_system_settings(db: Session) -> Dict[str, Any]:
    """
    Retrieves system configuration from database or environment defaults.
    """
    settings_rows = db.query(SystemSetting).all()
    config_dict = {row.key: row.value for row in settings_rows}

    return {
        "portal_name": config_dict.get("PORTAL_NAME") or os.getenv("PORTAL_NAME") or getattr(settings, "PORTAL_NAME", None) or "Motaaked",
        "portal_name_ar": config_dict.get("PORTAL_NAME_AR") or os.getenv("PORTAL_NAME_AR") or getattr(settings, "PORTAL_NAME_AR", None) or "متأكد | Motaaked",
        "portal_title": config_dict.get("PORTAL_TITLE") or os.getenv("PORTAL_TITLE", "Instant Insta Transactions Verification Platform"),
        "portal_subtitle_ar": config_dict.get("PORTAL_SUBTITLE_AR") or os.getenv("PORTAL_SUBTITLE_AR", "منظومة إنستا غير الرسمية لتأكيد وصول رسائل المدفوعات في البنك"),
        "portal_subtitle_en": config_dict.get("PORTAL_SUBTITLE_EN") or os.getenv("PORTAL_SUBTITLE_EN", "Unofficial Insta Platform for Automated Bank SMS Payment Verification"),
        "instapay_handle": config_dict.get("INSTAPAY_RECEIVER_HANDLE", os.getenv("INSTAPAY_RECEIVER_HANDLE", "haitham@instapay")),
        "instapay_phone": config_dict.get("INSTAPAY_RECEIVER_PHONE", os.getenv("INSTAPAY_RECEIVER_PHONE", "01000000000")),
        "instapay_account_ending": config_dict.get("INSTAPAY_RECEIVER_ACCOUNT_ENDING", os.getenv("INSTAPAY_RECEIVER_ACCOUNT_ENDING", "1001")),
        "instapay_receiver_name": config_dict.get("INSTAPAY_RECEIVER_NAME", os.getenv("INSTAPAY_RECEIVER_NAME", "Haitham Refaat")),
        "match_window_minutes": int(config_dict.get("MATCH_WINDOW_MINUTES", settings.MATCH_WINDOW_MINUTES)),
        "default_trial_days": int(config_dict.get("DEFAULT_TRIAL_DAYS", "180")),
        "default_livestream_trial_days": int(config_dict.get("DEFAULT_LIVESTREAM_TRIAL_DAYS", "5")),
        "require_merchant_approval": config_dict.get("REQUIRE_MERCHANT_APPROVAL", "false").lower() in ["true", "1", "yes"],
        "search_credit_cost": int(config_dict.get("SEARCH_CREDIT_COST", "1")),
        "vault_unlock_cost": int(config_dict.get("VAULT_UNLOCK_COST", "10")),
        "statement_export_cost": int(config_dict.get("STATEMENT_EXPORT_COST", "10")),
        "monthly_free_credits": int(config_dict.get("MONTHLY_FREE_CREDITS", "100")),
        "forwarder_online_timeout_minutes": int(config_dict.get("FORWARDER_ONLINE_TIMEOUT_MINUTES", "7")),
        "forwarder_offline_timeout_minutes": int(config_dict.get("FORWARDER_OFFLINE_TIMEOUT_MINUTES", "15")),
        "announcement_enabled": config_dict.get("ANNOUNCEMENT_ENABLED", "true").lower() in ["true", "1", "yes"],
        "announcement_title_en": config_dict.get("ANNOUNCEMENT_TITLE_EN", "Phase 2: Support E-Commerce to Validate transactions from outside our portal"),
        "announcement_title_ar": config_dict.get("ANNOUNCEMENT_TITLE_AR", "المرحلة 2: دعم منصات التجارة الإلكترونية لتأكيد المدفوعات آلياً"),
        "announcement_desc_en": config_dict.get("ANNOUNCEMENT_DESC_EN", "Universal 8-Platform Plugin Suite: WordPress, WooCommerce, LearnDash, Moodle, Shopify, React, Node.js, Laravel"),
        "announcement_desc_ar": config_dict.get("ANNOUNCEMENT_DESC_AR", "حزمة تكامل موحدة لـ 8 منصات: ووردبريس، ووكومرس، شوبيفاي، لارفيل، رياكت، نود جي اس، مودل، ليرنداش"),
        
        # Floating Support Hub & Channels
        "support_widget_enabled": config_dict.get("SUPPORT_WIDGET_ENABLED", "true").lower() in ["true", "1", "yes"],
        "support_ticketing_enabled": config_dict.get("SUPPORT_TICKETING_ENABLED", "true").lower() in ["true", "1", "yes"],
        "support_faq_enabled": config_dict.get("SUPPORT_FAQ_ENABLED", "true").lower() in ["true", "1", "yes"],
        "support_social_enabled": config_dict.get("SUPPORT_SOCIAL_ENABLED", "true").lower() in ["true", "1", "yes"],
        "support_admin_email": config_dict.get("SUPPORT_ADMIN_EMAIL", "haitham.refaat@gmail.com"),
        "support_whatsapp_number": config_dict.get("SUPPORT_WHATSAPP_NUMBER", "201000000000"),
        "support_whatsapp_enabled": config_dict.get("SUPPORT_WHATSAPP_ENABLED", "true").lower() in ["true", "1", "yes"],
        "support_telegram_handle": config_dict.get("SUPPORT_TELEGRAM_HANDLE", ""),
        "support_telegram_enabled": config_dict.get("SUPPORT_TELEGRAM_ENABLED", "false").lower() in ["true", "1", "yes"],
        "support_facebook_url": config_dict.get("SUPPORT_FACEBOOK_URL", ""),
        "support_facebook_enabled": config_dict.get("SUPPORT_FACEBOOK_ENABLED", "false").lower() in ["true", "1", "yes"],
        "support_linkedin_url": config_dict.get("SUPPORT_LINKEDIN_URL", ""),
        "support_linkedin_enabled": config_dict.get("SUPPORT_LINKEDIN_ENABLED", "false").lower() in ["true", "1", "yes"],
        "support_youtube_url": config_dict.get("SUPPORT_YOUTUBE_URL", ""),
        "support_youtube_enabled": config_dict.get("SUPPORT_YOUTUBE_ENABLED", "false").lower() in ["true", "1", "yes"],
        "support_phone_number": config_dict.get("SUPPORT_PHONE_NUMBER", ""),
        "support_phone_enabled": config_dict.get("SUPPORT_PHONE_ENABLED", "false").lower() in ["true", "1", "yes"],
        "support_email_address": config_dict.get("SUPPORT_EMAIL_ADDRESS", "support@motaaked.com"),
        "support_email_enabled": config_dict.get("SUPPORT_EMAIL_ENABLED", "true").lower() in ["true", "1", "yes"],
        "smtp_from": config_dict.get("SMTP_FROM", "") or "",
        "smtp_host": config_dict.get("SMTP_HOST") or os.getenv("SMTP_HOST") or getattr(settings, "SMTP_HOST", "smtp-relay.brevo.com"),
        "smtp_port": int(config_dict.get("SMTP_PORT") or os.getenv("SMTP_PORT") or getattr(settings, "SMTP_PORT", 587)),
        "smtp_user": config_dict.get("SMTP_USER") or os.getenv("SMTP_USER") or getattr(settings, "SMTP_USER", "") or "",
        "smtp_password": config_dict.get("SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD") or getattr(settings, "SMTP_PASSWORD", "") or "",
        "smtp_tls": str(config_dict.get("SMTP_TLS", os.getenv("SMTP_TLS", str(getattr(settings, "SMTP_TLS", True))))).lower() in ["true", "1", "yes", "tls", "starttls"],
        "ecommerce_gateway_enabled": config_dict.get("ECOMMERCE_GATEWAY_ENABLED", "true").lower() in ["true", "1", "yes"],
        "order_verification_credit_cost": int(config_dict.get("ORDER_VERIFICATION_CREDIT_COST", "1")),
        "allow_reference_less_order_matching": config_dict.get("ALLOW_REFERENCE_LESS_ORDER_MATCHING", "true").lower() in ["true", "1", "yes"],
        "allowed_checkout_embed_origins": config_dict.get("ALLOWED_CHECKOUT_EMBED_ORIGINS", "*"),
        "copilot_widget_enabled": config_dict.get("COPILOT_WIDGET_ENABLED", "true").lower() in ["true", "1", "yes"],
        "copilot_provider": config_dict.get("COPILOT_PROVIDER", "local"),
        "copilot_api_key": config_dict.get("COPILOT_API_KEY", ""),
        "copilot_model": config_dict.get("COPILOT_MODEL", "gemini-1.5-flash"),
    }


def update_system_settings(db: Session, updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates system configuration in system_settings table.
    """
    key_mapping = {
        "allow_reference_less_order_matching": "ALLOW_REFERENCE_LESS_ORDER_MATCHING",
        "allowed_checkout_embed_origins": "ALLOWED_CHECKOUT_EMBED_ORIGINS",
        "smtp_from": "SMTP_FROM",

        "smtp_host": "SMTP_HOST",
        "smtp_port": "SMTP_PORT",
        "smtp_user": "SMTP_USER",
        "smtp_password": "SMTP_PASSWORD",
        "smtp_tls": "SMTP_TLS",
        "portal_name": "PORTAL_NAME",
        "portal_name_ar": "PORTAL_NAME_AR",
        "portal_title": "PORTAL_TITLE",
        "portal_subtitle_ar": "PORTAL_SUBTITLE_AR",
        "portal_subtitle_en": "PORTAL_SUBTITLE_EN",
        "instapay_handle": "INSTAPAY_RECEIVER_HANDLE",
        "instapay_phone": "INSTAPAY_RECEIVER_PHONE",
        "instapay_account_ending": "INSTAPAY_RECEIVER_ACCOUNT_ENDING",
        "instapay_receiver_name": "INSTAPAY_RECEIVER_NAME",
        "match_window_minutes": "MATCH_WINDOW_MINUTES",
        "default_trial_days": "DEFAULT_TRIAL_DAYS",
        "default_livestream_trial_days": "DEFAULT_LIVESTREAM_TRIAL_DAYS",
        "require_merchant_approval": "REQUIRE_MERCHANT_APPROVAL",
        "search_credit_cost": "SEARCH_CREDIT_COST",
        "vault_unlock_cost": "VAULT_UNLOCK_COST",
        "statement_export_cost": "STATEMENT_EXPORT_COST",
        "monthly_free_credits": "MONTHLY_FREE_CREDITS",
        "forwarder_online_timeout_minutes": "FORWARDER_ONLINE_TIMEOUT_MINUTES",
        "forwarder_offline_timeout_minutes": "FORWARDER_OFFLINE_TIMEOUT_MINUTES",
        "announcement_enabled": "ANNOUNCEMENT_ENABLED",
        "announcement_title_en": "ANNOUNCEMENT_TITLE_EN",
        "announcement_title_ar": "ANNOUNCEMENT_TITLE_AR",
        "announcement_desc_en": "ANNOUNCEMENT_DESC_EN",
        "announcement_desc_ar": "ANNOUNCEMENT_DESC_AR",
        "support_widget_enabled": "SUPPORT_WIDGET_ENABLED",
        "support_ticketing_enabled": "SUPPORT_TICKETING_ENABLED",
        "support_faq_enabled": "SUPPORT_FAQ_ENABLED",
        "support_social_enabled": "SUPPORT_SOCIAL_ENABLED",
        "support_admin_email": "SUPPORT_ADMIN_EMAIL",
        "support_whatsapp_number": "SUPPORT_WHATSAPP_NUMBER",
        "support_whatsapp_enabled": "SUPPORT_WHATSAPP_ENABLED",
        "support_telegram_handle": "SUPPORT_TELEGRAM_HANDLE",
        "support_telegram_enabled": "SUPPORT_TELEGRAM_ENABLED",
        "support_facebook_url": "SUPPORT_FACEBOOK_URL",
        "support_facebook_enabled": "SUPPORT_FACEBOOK_ENABLED",
        "support_linkedin_url": "SUPPORT_LINKEDIN_URL",
        "support_linkedin_enabled": "SUPPORT_LINKEDIN_ENABLED",
        "support_youtube_url": "SUPPORT_YOUTUBE_URL",
        "support_youtube_enabled": "SUPPORT_YOUTUBE_ENABLED",
        "support_phone_number": "SUPPORT_PHONE_NUMBER",
        "support_phone_enabled": "SUPPORT_PHONE_ENABLED",
        "support_email_address": "SUPPORT_EMAIL_ADDRESS",
        "support_email_enabled": "SUPPORT_EMAIL_ENABLED",
        "ecommerce_gateway_enabled": "ECOMMERCE_GATEWAY_ENABLED",
        "order_verification_credit_cost": "ORDER_VERIFICATION_CREDIT_COST",
        "copilot_widget_enabled": "COPILOT_WIDGET_ENABLED",
        "copilot_provider": "COPILOT_PROVIDER",
        "copilot_api_key": "COPILOT_API_KEY",
        "copilot_model": "COPILOT_MODEL",
    }

    now = utc_now()
    for field_name, setting_key in key_mapping.items():
        if field_name in updates and updates[field_name] is not None:
            if isinstance(updates[field_name], bool) or field_name.endswith("_enabled") or field_name == "require_merchant_approval":
                val = "true" if updates[field_name] else "false"
            else:
                val = str(updates[field_name]).strip()
            row = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()
            if row:
                row.value = val
                row.updated_at = now
            else:
                row = SystemSetting(
                    key=setting_key,
                    value=val,
                    description=f"System setting for {field_name}",
                    updated_at=now,
                )
                db.add(row)

    db.commit()
    updated_settings = get_system_settings(db)

    # Automatically keep static/manifest.json in sync with active portal branding
    try:
        manifest_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "manifest.json")
        if os.path.exists(manifest_path):
            p_name = updated_settings.get("portal_name") or "Motaaked"
            p_name_ar = updated_settings.get("portal_name_ar") or ""
            full_name = f"{p_name} - Automated InstaPay Verification Gateway"
            if p_name_ar:
                full_name += f" | {p_name_ar}"
            import json
            with open(manifest_path, "r", encoding="utf-8") as mf:
                m_data = json.load(mf)
            m_data["name"] = full_name
            m_data["short_name"] = p_name
            with open(manifest_path, "w", encoding="utf-8") as mf:
                json.dump(m_data, mf, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[MANIFEST SYNC NOTICE] {e}")

    return updated_settings


def get_active_supported_banks(db: Session) -> List[str]:
    """
    Returns unique active bank names from bank_patterns, ordered by priority and insertion.
    Automatically de-duplicates multiple SMS templates for the same bank (e.g. multiple CIB templates).
    """
    patterns = (
        db.query(BankPattern)
        .filter(BankPattern.is_active == True)
        .order_by(BankPattern.priority.asc(), BankPattern.id.asc())
        .all()
    )
    seen = set()
    banks = []
    for p in patterns:
        clean_name = p.bank_name.strip()
        if clean_name and clean_name.lower() not in seen:
            seen.add(clean_name.lower())
            banks.append(clean_name)

    if not banks:
        # Graceful fallback to Egyptian standard network if no patterns are seeded
        banks = ["CIB", "NBE", "Banque Misr", "HSBC", "QNB", "AlexBank", "AAIB", "Insta IPN"]

    return banks


# =========================================================================
# Bank SMS Regex Patterns Management (Admin)
# =========================================================================

def get_all_bank_patterns(db: Session) -> List[BankPattern]:
    """Returns all bank SMS regex patterns ordered by priority."""
    return db.query(BankPattern).order_by(BankPattern.priority.asc(), BankPattern.id.asc()).all()


def get_bank_pattern_by_id(db: Session, pattern_id: int) -> Optional[BankPattern]:
    """Retrieves a single bank pattern by ID."""
    return db.query(BankPattern).filter(BankPattern.id == pattern_id).first()


def create_bank_pattern(db: Session, data: BankPatternCreate) -> BankPattern:
    """Creates a new BankPattern entry."""
    now = utc_now()
    pattern = BankPattern(
        bank_name=data.bank_name.strip(),
        sender_filter=data.sender_filter.strip() if data.sender_filter else None,
        pattern=data.pattern.strip(),
        amount_group=data.amount_group.strip() if data.amount_group else "amount",
        ref_group=data.ref_group.strip() if data.ref_group else "ref",
        account_group=data.account_group.strip() if data.account_group else "account",
        sender_group=data.sender_group.strip() if data.sender_group else "sender",
        priority=data.priority,
        is_active=data.is_active,
        example_sms=data.example_sms.strip() if data.example_sms else None,
        created_at=now,
        updated_at=now,
    )
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return pattern


def update_bank_pattern(db: Session, pattern_id: int, data: BankPatternUpdate) -> BankPattern:
    """Updates an existing BankPattern."""
    pattern = get_bank_pattern_by_id(db, pattern_id)
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bank Pattern with ID {pattern_id} not found."
        )

    if data.bank_name is not None:
        pattern.bank_name = data.bank_name.strip()
    if data.sender_filter is not None:
        pattern.sender_filter = data.sender_filter.strip() if data.sender_filter.strip() else None
    if data.pattern is not None:
        pattern.pattern = data.pattern.strip()
    if data.amount_group is not None:
        pattern.amount_group = data.amount_group.strip()
    if data.ref_group is not None:
        pattern.ref_group = data.ref_group.strip()
    if data.account_group is not None:
        pattern.account_group = data.account_group.strip() if data.account_group.strip() else None
    if data.sender_group is not None:
        pattern.sender_group = data.sender_group.strip() if data.sender_group.strip() else None
    if data.priority is not None:
        pattern.priority = data.priority
    if data.is_active is not None:
        pattern.is_active = data.is_active
    if data.example_sms is not None:
        pattern.example_sms = data.example_sms.strip() if data.example_sms.strip() else None

    pattern.updated_at = utc_now()
    db.commit()
    db.refresh(pattern)
    return pattern


def delete_bank_pattern(db: Session, pattern_id: int) -> bool:
    """Deletes a BankPattern by ID."""
    pattern = get_bank_pattern_by_id(db, pattern_id)
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bank Pattern with ID {pattern_id} not found."
        )
    db.delete(pattern)
    db.commit()
    return True


def test_bank_pattern_simulation(data: BankPatternTestRequest) -> BankPatternTestResponse:
    """
    Simulates testing a regex pattern against a sample text string.
    Returns matched status and extracted groups, or error message if invalid.
    """
    import re
    from app.parser import normalize_text, is_outward_debit_transfer, clean_amount, clean_name

    try:
        norm = normalize_text(data.sample_text)
        if is_outward_debit_transfer(norm):
            return BankPatternTestResponse(
                matched=False,
                error="Sample text was detected as an outgoing debit or withdrawal alert."
            )

        if len(data.pattern) > 2500:
            return BankPatternTestResponse(
                matched=False,
                error="Regex pattern exceeds maximum allowed length of 2500 characters."
            )
        if len(data.sample_text) > 5000:
            return BankPatternTestResponse(
                matched=False,
                error="Sample text exceeds maximum allowed length of 5000 characters."
            )

        compiled = re.compile(data.pattern, re.IGNORECASE | re.DOTALL)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(compiled.search, norm)
            try:
                match = future.result(timeout=1.0)
            except concurrent.futures.TimeoutError:
                return BankPatternTestResponse(
                    matched=False,
                    error="Regex evaluation timed out (possible catastrophic backtracking / ReDoS detected)."
                )

        if not match:
            return BankPatternTestResponse(
                matched=False,
                error="Regex pattern did not match the sample text."
            )

        raw_dict = match.groupdict()

        raw_amount = extract_group_value(match, data.amount_group)
        raw_ref = extract_group_value(match, data.ref_group)
        raw_acc = extract_group_value(match, data.account_group) if data.account_group else None
        raw_sender = extract_group_value(match, data.sender_group) if data.sender_group else None

        if not raw_amount:
            return BankPatternTestResponse(
                matched=False,
                error=f"Pattern matched text, but amount capture group '{data.amount_group}' was empty or not found in capture groups.",
                raw_groups=raw_dict
            )

        if not raw_ref:
            return BankPatternTestResponse(
                matched=False,
                error=f"Pattern matched text, but reference ID capture group '{data.ref_group}' was empty or not found in capture groups.",
                raw_groups=raw_dict
            )

        try:
            amt = clean_amount(raw_amount)
        except Exception:
            return BankPatternTestResponse(
                matched=False,
                error=f"Captured amount value '{raw_amount}' could not be parsed as a valid numeric amount.",
                raw_groups=raw_dict
            )

        return BankPatternTestResponse(
            matched=True,
            amount=amt,
            reference_id=raw_ref.strip(),
            account_ending=raw_acc.strip() if raw_acc else None,
            sender_name=clean_name(raw_sender) if raw_sender else None,
            currency="EGP",
            raw_groups=raw_dict
        )
    except re.error as re_err:
        return BankPatternTestResponse(
            matched=False,
            error=f"Invalid Regular Expression syntax: {str(re_err)}"
        )
    except Exception as e:
        return BankPatternTestResponse(
            matched=False,
            error=f"Simulation error: {str(e)}"
        )


def auto_generate_bank_pattern_service(data: BankPatternAutoGenerateRequest) -> BankPatternAutoGenerateResponse:
    """Reverse-engineers and generates a regex pattern from sample SMS text."""
    res = auto_generate_regex_from_sms(data.sample_text)
    return BankPatternAutoGenerateResponse(
        success=res.get("success", False),
        generated_pattern=res.get("generated_pattern", ""),
        detected_bank=res.get("detected_bank", "Custom Bank Alert"),
        detected_sender=res.get("detected_sender", None),
        amount_group=res.get("amount_group", "amount"),
        ref_group=res.get("ref_group", "ref"),
        account_group=res.get("account_group", "account"),
        sender_group=res.get("sender_group", "sender"),
        preview=res.get("preview", None),
        error=res.get("error", None),
    )


# =========================================================================
# Merchant Credit Movement & Audit Statement Explorer
# =========================================================================

OPERATION_LABELS = {
    "SEARCH_LOOKUP": "Single Search Lookup",
    "VAULT_UNLOCK": "Vault Masked SMS Reveal",
    "PDF_STATEMENT_EXPORT": "PDF / Excel Statement Export",
    "PASSCODE_ALLOCATION": "Voucher / Passcode Allocation",
    "TOPUP_DIRECT_ACTIVATION": "Direct Package Top-Up",
    "ADMIN_ADJUSTMENT": "Admin Quota Adjustment",
    "MONTHLY_FREE_CREDITS": "Monthly Free Credits Grant",
}


def get_operation_label(op_type: str) -> str:
    return OPERATION_LABELS.get(op_type, op_type.replace("_", " ").title())


def get_merchant_credit_audit(
    db: Session,
    user_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    operation_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> MerchantCreditAuditResponse:
    """
    Computes chronological running balance before and after for every credit movement of a merchant.
    Allows date range, operation type, and keyword filtering.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Merchant with ID {user_id} not found.")

    # Fetch ALL transactions for this merchant chronologically from beginning
    all_txs = (
        db.query(CreditTransaction)
        .filter(CreditTransaction.user_id == user_id)
        .order_by(CreditTransaction.created_at.asc(), CreditTransaction.id.asc())
        .all()
    )

    # Compute sequential balance before and balance after from the beginning
    computed_movements: List[CreditMovementItem] = []
    running_balance = 0
    total_added = 0
    total_deducted = 0

    for tx in all_txs:
        bal_before = running_balance
        bal_after = running_balance + tx.amount
        running_balance = bal_after

        if tx.amount > 0:
            total_added += tx.amount
        else:
            total_deducted += abs(tx.amount)

        item = CreditMovementItem(
            id=tx.id,
            created_at=tx.created_at,
            operation_type=tx.operation_type,
            operation_label=get_operation_label(tx.operation_type),
            reference_id=tx.reference_id,
            amount=tx.amount,
            balance_before=bal_before,
            balance_after=bal_after,
        )
        computed_movements.append(item)

    # Apply Filters on the computed movements stream
    filtered = computed_movements

    if date_from:
        start_dt = datetime.combine(date_from, time.min)
        filtered = [m for m in filtered if m.created_at >= start_dt]

    if date_to:
        end_dt = datetime.combine(date_to, time.max)
        filtered = [m for m in filtered if m.created_at <= end_dt]

    if operation_type and operation_type.strip():
        clean_op = operation_type.strip().upper()
        filtered = [m for m in filtered if m.operation_type == clean_op]

    if search and search.strip():
        s = search.strip().lower()
        filtered = [
            m for m in filtered
            if (m.reference_id and s in m.reference_id.lower())
            or s in m.operation_type.lower()
            or s in m.operation_label.lower()
            or s in str(m.amount)
        ]

    # Present newest first for table browsing
    filtered.reverse()

    total_filtered = len(filtered)
    start_idx = (page - 1) * page_size
    paged_items = filtered[start_idx : start_idx + page_size]

    return MerchantCreditAuditResponse(
        user_id=user.id,
        user_name=user.name,
        user_email=user.email,
        user_passcode=user.passcode,
        current_balance=user.credits_balance,
        free_credits=user.free_credits if getattr(user, "free_credits", None) is not None else 0,
        pass_credits=user.pass_credits if getattr(user, "pass_credits", None) is not None else 0,
        lifetime_credits=user.lifetime_credits if getattr(user, "lifetime_credits", None) is not None else 0,
        subscription_expires_at=user.subscription_expires_at,
        total_movements=total_filtered,
        total_added=total_added,
        total_deducted=total_deducted,
        page=page,
        page_size=page_size,
        items=paged_items,
    )


def export_merchant_credit_audit_csv(
    db: Session,
    user_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    operation_type: Optional[str] = None,
    search: Optional[str] = None,
) -> Tuple[str, str]:
    """Generates a downloadable CSV audit statement for Excel."""
    audit_resp = get_merchant_credit_audit(
        db=db,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        operation_type=operation_type,
        search=search,
        page=1,
        page_size=10000,
    )

    output = io.StringIO()
    writer = csv.writer(output)

    # Header metadata
    writer.writerow([f"MERCHANT CREDIT AUDIT STATEMENT - {audit_resp.user_name} ({audit_resp.user_passcode})"])
    writer.writerow([f"Email: {audit_resp.user_email or 'N/A'}", f"Current Total Balance: {audit_resp.current_balance} Credits"])
    writer.writerow([
        f"Free Monthly: {audit_resp.free_credits}",
        f"Day Pass: {audit_resp.pass_credits}",
        f"Lifetime Rollover: {audit_resp.lifetime_credits}",
        f"Subscription Expiry: {audit_resp.subscription_expires_at.strftime('%Y-%m-%d %H:%M:%S') if audit_resp.subscription_expires_at else 'N/A'}"
    ])
    writer.writerow([])
    writer.writerow([
        "Transaction ID",
        "Timestamp (UTC)",
        "Operation Type",
        "Action Description",
        "Reference ID / Details",
        "Credit Change",
        "Balance Before",
        "Balance After"
    ])

    for item in audit_resp.items:
        change_str = f"+{item.amount}" if item.amount > 0 else str(item.amount)
        writer.writerow([
            item.id,
            item.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            item.operation_type,
            item.operation_label,
            item.reference_id or "",
            change_str,
            item.balance_before,
            item.balance_after,
        ])

    filename = f"credit_audit_user_{user_id}_{audit_resp.user_passcode}.csv"
    return output.getvalue(), filename


# =========================================================================
# Live Stream POS Terminal & Forwarder Telemetry Services
# =========================================================================

def parse_battery_value(val) -> Optional[int]:
    """
    Robustly parses battery telemetry from integers, floats, strings with %,
    or mixed payloads. Returns an integer between 0 and 100, or None if unparseable.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        if 0 < val <= 1.0:
            val = val * 100
        return max(0, min(100, int(round(val))))
    val_str = str(val).strip()
    if not val_str:
        return None
    if val_str.startswith("%") or val_str.startswith("{{") or val_str.startswith("["):
        return None
    cleaned = val_str.replace("%", "").strip()
    import re
    match = re.search(r"\b(\d{1,3})\b", cleaned)
    if match:
        num = int(match.group(1))
        if 0 <= num <= 100:
            return num
    try:
        num = int(cleaned)
        return max(0, min(100, num))
    except Exception:
        return None


def record_forwarder_heartbeat(
    db: Session,
    user: User,
    payload: ForwarderHeartbeatRequest
) -> ForwarderHeartbeatResponse:
    """
    Records heartbeat telemetry (battery, network, uptime, ping) from the merchant's Android SMS Forwarder.
    Logs health incidents into ForwarderHealthLog for Admin monitoring.
    """
    now = utc_now()
    user.forwarder_last_seen_at = now
    if payload.battery is not None:
        user.forwarder_battery = max(0, min(100, payload.battery))
    if payload.network:
        user.forwarder_network = payload.network.strip()[:50]
    if payload.uptime:
        user.forwarder_uptime = payload.uptime.strip()[:50]
    if payload.device:
        user.forwarder_device = payload.device.strip()[:100]

    status_str = "ONLINE"
    if payload.battery is not None and payload.battery <= 15:
        status_str = "LOW_BATTERY"
    user.forwarder_status = status_str

    # Log incident in ForwarderHealthLog if none exists or 10 mins passed or low battery
    last_log = (
        db.query(ForwarderHealthLog)
        .filter(ForwarderHealthLog.user_id == user.id)
        .order_by(ForwarderHealthLog.created_at.desc())
        .first()
    )
    should_log = (
        last_log is None
        or (now - last_log.created_at).total_seconds() >= 600
        or (status_str == "LOW_BATTERY" and last_log.status != "LOW_BATTERY")
    )
    if should_log:
        log_entry = ForwarderHealthLog(
            user_id=user.id,
            status=status_str,
            battery=user.forwarder_battery,
            network=user.forwarder_network,
            ping_ms=payload.ping_ms or 25,
            message=f"Heartbeat from {user.forwarder_device or 'SMS Forwarder'} ({user.forwarder_network or 'Mobile Data'})",
            created_at=now,
        )
        db.add(log_entry)

    db.commit()
    db.refresh(user)

    return ForwarderHeartbeatResponse(
        success=True,
        status=user.forwarder_status,
        recorded_at=now,
        battery=user.forwarder_battery,
        network=user.forwarder_network,
    )


def get_livestream_feed_data(
    db: Session,
    user: User,
    since_id: Optional[int] = None,
    limit: int = 50,
) -> LiveStreamFeedResponse:
    """
    Fetches real-time incoming transactions for the merchant's Live Stream POS Terminal.
    Verifies subscription validity and 5-day grace period. Highlights the latest unread transaction.
    """
    now = utc_now()
    is_admin = (getattr(user, "role", "user") == "admin" or user.id == 0)
    ls_exp = getattr(user, "livestream_expires_at", None)
    ls_grace = getattr(user, "livestream_grace_until", None)

    is_unlocked = False
    in_grace = False
    days_left = 0

    if is_admin:
        is_unlocked = True
        in_grace = False
        days_left = 365
    elif ls_exp and ls_exp >= now:
        is_unlocked = True
        in_grace = False
        days_left = max(1, (ls_exp - now).days)
    elif ls_grace and ls_grace >= now:
        is_unlocked = True
        in_grace = True
        days_left = max(0, (ls_grace - now).days)
    else:
        is_unlocked = False
        in_grace = False
        days_left = 0

    # Forwarder dynamic status check using Admin configured timeouts
    last_seen = getattr(user, "forwarder_last_seen_at", None)
    fwd_status = getattr(user, "forwarder_status", "STANDBY") or "STANDBY"
    
    sys_settings = get_system_settings(db)
    online_window = sys_settings.get("forwarder_online_timeout_minutes", 7)
    offline_window = sys_settings.get("forwarder_offline_timeout_minutes", 15)

    if last_seen:
        diff_mins = (now - last_seen).total_seconds() / 60
        if diff_mins <= online_window:
            fwd_status = "ONLINE"
        elif diff_mins <= offline_window:
            fwd_status = "STANDBY"
        else:
            fwd_status = "OFFLINE"
    else:
        fwd_status = "STANDBY"

    telemetry = ForwarderTelemetryRead(
        status=fwd_status,
        last_seen_at=last_seen,
        battery=getattr(user, "forwarder_battery", None),
        network=getattr(user, "forwarder_network", None),
        uptime=getattr(user, "forwarder_uptime", None),
        ping_ms=25,
        device=getattr(user, "forwarder_device", None),
    )

    if not is_unlocked:
        return LiveStreamFeedResponse(
            is_unlocked=False,
            in_grace_period=in_grace,
            grace_days_remaining=days_left,
            expires_at=ls_exp,
            grace_until=ls_grace,
            telemetry=telemetry,
            unread_count=0,
            total_count=0,
            items=[],
        )

    # Fetch incoming credits scoped to user
    query = db.query(IncomingCredit)
    if not is_admin:
        if user.account_ending:
            query = query.filter(
                or_(
                    IncomingCredit.user_id == user.id,
                    (IncomingCredit.user_id.is_(None) & (IncomingCredit.account_ending == user.account_ending))
                )
            )
        else:
            query = query.filter(IncomingCredit.user_id == user.id)

    if since_id:
        query = query.filter(IncomingCredit.id > since_id)

    total_count = query.count()
    credits_list = query.order_by(IncomingCredit.received_at.desc(), IncomingCredit.id.desc()).limit(limit).all()

    # Calculate unread count (for merchant's credits)
    unread_q = db.query(IncomingCredit).filter(IncomingCredit.is_read == False)
    if not is_admin:
        if user.account_ending:
            unread_q = unread_q.filter(
                or_(
                    IncomingCredit.user_id == user.id,
                    (IncomingCredit.user_id.is_(None) & (IncomingCredit.account_ending == user.account_ending))
                )
            )
        else:
            unread_q = unread_q.filter(IncomingCredit.user_id == user.id)
    unread_count = unread_q.count()

    items: List[LiveStreamTransactionItem] = []
    for i, c in enumerate(credits_list):
        bank_label = "InstaPay"
        raw_lower = (c.raw_message or "").lower()
        if "qnb" in raw_lower:
            bank_label = "QNB"
        elif "cib" in raw_lower:
            bank_label = "CIB"
        elif "misr" in raw_lower or "مصر" in (c.raw_message or ""):
            bank_label = "Banque Misr"
        elif "ahly" in raw_lower or "أهلي" in (c.raw_message or "") or "nbe" in raw_lower:
            bank_label = "NBE الأهلي"
        elif "hsbc" in raw_lower:
            bank_label = "HSBC"
        elif "alex" in raw_lower or "إسكندرية" in (c.raw_message or ""):
            bank_label = "AlexBank"
        elif "aaib" in raw_lower:
            bank_label = "AAIB"
        elif "fawry" in raw_lower or "فوري" in (c.raw_message or ""):
            bank_label = "Fawry"
        elif "vodafone" in raw_lower or "فودافون" in (c.raw_message or ""):
            bank_label = "Vodafone Cash"

        is_unread = not bool(c.is_read)
        is_highlighted = (i == 0 and is_unread)

        items.append(
            LiveStreamTransactionItem(
                id=c.id,
                amount=c.amount,
                currency=c.currency or "EGP",
                bank_name=bank_label,
                account_ending=c.account_ending,
                sender_name=c.sender_name,
                reference_id=c.reference_id,
                status="VERIFIED" if (c.status == "CLAIMED" or c.is_matched) else "UNCLAIMED",
                is_matched=c.is_matched,
                is_read=bool(c.is_read),
                read_at=c.read_at,
                received_at=c.received_at,
                is_highlighted=is_highlighted,
            )
        )

    return LiveStreamFeedResponse(
        is_unlocked=True,
        in_grace_period=in_grace,
        grace_days_remaining=days_left,
        expires_at=ls_exp,
        grace_until=ls_grace,
        telemetry=telemetry,
        unread_count=unread_count,
        total_count=total_count,
        items=items,
    )


def mark_credits_read(
    db: Session,
    user: User,
    credit_ids: Optional[List[int]] = None,
    mark_all: bool = False,
) -> int:
    """
    Marks one, multiple, or all transactions as Read for the cashier.
    """
    now = utc_now()
    is_admin = (getattr(user, "role", "user") == "admin" or user.id == 0)

    query = db.query(IncomingCredit).filter(IncomingCredit.is_read == False)
    if not is_admin:
        query = query.filter(
            or_(
                IncomingCredit.user_id == user.id,
                (IncomingCredit.user_id.is_(None) & (IncomingCredit.account_ending == user.account_ending))
            )
        )

    if not mark_all:
        if not credit_ids:
            return 0
        query = query.filter(IncomingCredit.id.in_(credit_ids))

    updated_count = query.update(
        {"is_read": True, "read_at": now},
        synchronize_session=False,
    )
    db.commit()
    return updated_count


def get_admin_forwarders_health(db: Session) -> AdminForwarderHealthResponse:
    """
    Retrieves phone forwarder connection health and telemetry for all platform merchants.
    """
    now = utc_now()
    users = db.query(User).order_by(User.created_at.desc()).all()

    online_c = 0
    standby_c = 0
    offline_c = 0
    items: List[AdminForwarderHealthItem] = []
    sys_settings = get_system_settings(db)
    online_window = sys_settings.get("forwarder_online_timeout_minutes", 7)
    offline_window = sys_settings.get("forwarder_offline_timeout_minutes", 15)

    for u in users:
        last_seen = getattr(u, "forwarder_last_seen_at", None)
        status_str = getattr(u, "forwarder_status", "STANDBY") or "STANDBY"
        if last_seen:
            diff_mins = (now - last_seen).total_seconds() / 60
            if diff_mins <= online_window:
                status_str = "ONLINE"
                online_c += 1
            elif diff_mins <= offline_window:
                status_str = "STANDBY"
                standby_c += 1
            else:
                status_str = "OFFLINE"
                offline_c += 1
        else:
            status_str = "OFFLINE"
            offline_c += 1

        ls_exp = getattr(u, "livestream_expires_at", None)
        ls_grace = getattr(u, "livestream_grace_until", None)
        is_active = (u.role == "admin" or (ls_exp and ls_exp >= now) or (ls_grace and ls_grace >= now))

        items.append(
            AdminForwarderHealthItem(
                user_id=u.id,
                merchant_name=u.name,
                email=getattr(u, "email", None),
                account_ending=getattr(u, "account_ending", None),
                forwarder_status=status_str,
                battery=getattr(u, "forwarder_battery", None),
                network=getattr(u, "forwarder_network", None),
                last_seen_at=last_seen,
                uptime=getattr(u, "forwarder_uptime", None),
                livestream_expires_at=ls_exp,
                livestream_grace_until=ls_grace,
                is_livestream_active=bool(is_active),
            )
        )

    return AdminForwarderHealthResponse(
        total=len(items),
        online_count=online_c,
        standby_count=standby_c,
        offline_count=offline_c,
        items=items,
    )


# =========================================================================
# Support Hub & Trouble Ticketing Services
# =========================================================================

def generate_ticket_code() -> str:
    """Generates unique trouble ticket reference with 64-bit entropy e.g. TCK-2026-9F8A-B1C2-D3E4-F5A6."""
    token = secrets.token_hex(8).upper()
    return f"TCK-2026-{token[:4]}-{token[4:8]}-{token[8:12]}-{token[12:]}"


def create_support_ticket(
    db: Session,
    payload: SupportTicketCreate,
    merchant_user: Optional[User] = None
) -> SupportTicket:
    """
    Creates a new support trouble ticket with a unique tracking code.
    Auto-links authenticated merchant user if available.
    """
    ticket_code = generate_ticket_code()
    for _ in range(10):
        if not db.query(SupportTicket).filter(SupportTicket.ticket_code == ticket_code).first():
            break
        ticket_code = generate_ticket_code()

    now = utc_now()
    ticket = SupportTicket(
        ticket_code=ticket_code,
        merchant_id=merchant_user.id if merchant_user else None,
        merchant_name=payload.merchant_name.strip(),
        merchant_email=payload.merchant_email.strip().lower(),
        merchant_phone=payload.merchant_phone.strip() if payload.merchant_phone else None,
        category=payload.category.strip(),
        subject=payload.subject.strip(),
        reference_id=payload.reference_id.strip() if payload.reference_id else None,
        message=payload.message.strip(),
        status="OPEN",
        priority="NORMAL",
        admin_notes=None,
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # Trigger email notifications
    try:
        from app.email_service import send_ticket_created_emails
        send_ticket_created_emails(ticket)
    except Exception as e:
        print(f"[TICKET EMAIL NOTICE] {e}")

    return ticket


def list_support_tickets(
    db: Session,
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 50
) -> Dict[str, Any]:
    """
    Returns paginated support tickets with status metrics for Admin Control Center.
    """
    query = db.query(SupportTicket)

    if status_filter and status_filter.upper() != "ALL":
        query = query.filter(SupportTicket.status == status_filter.upper())

    if category_filter and category_filter.lower() != "all":
        query = query.filter(SupportTicket.category == category_filter.lower())

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                SupportTicket.ticket_code.ilike(s),
                SupportTicket.merchant_name.ilike(s),
                SupportTicket.merchant_email.ilike(s),
                SupportTicket.subject.ilike(s),
                SupportTicket.reference_id.ilike(s),
            )
        )

    total = query.count()
    open_count = db.query(SupportTicket).filter(SupportTicket.status.in_(["OPEN", "IN_PROGRESS"])).count()
    resolved_count = db.query(SupportTicket).filter(SupportTicket.status.in_(["RESOLVED", "CLOSED"])).count()

    items = (
        query.order_by(SupportTicket.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "total": total,
        "open_count": open_count,
        "resolved_count": resolved_count,
        "items": items,
    }


def get_support_ticket_by_code(db: Session, ticket_code: str) -> Optional[SupportTicket]:
    """Retrieves a support ticket by public ticket code."""
    return db.query(SupportTicket).filter(SupportTicket.ticket_code == ticket_code.strip().upper()).first()


def update_support_ticket(
    db: Session,
    ticket_id: int,
    updates: SupportTicketAdminUpdate
) -> SupportTicket:
    """Updates status, priority, or admin notes on a trouble ticket."""
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")

    if updates.status:
        ticket.status = updates.status.strip().upper()
    if updates.priority:
        ticket.priority = updates.priority.strip().upper()
    if updates.admin_notes is not None:
        ticket.admin_notes = updates.admin_notes.strip()

    ticket.updated_at = utc_now()
    db.commit()
    db.refresh(ticket)

    # If admin provided a reply_message, dispatch email to merchant
    if updates.reply_message:
        try:
            from app.email_service import send_ticket_status_update_email
            send_ticket_status_update_email(ticket, reply_message=updates.reply_message.strip())
        except Exception as e:
            print(f"[TICKET REPLY EMAIL NOTICE] {e}")

    return ticket


# =========================================================================
# FAQ & Knowledge Base Services
# =========================================================================

def list_active_faqs(db: Session, category: Optional[str] = None) -> List[FaqItem]:
    """Returns active FAQs sorted by sort_order for public knowledge base."""
    query = db.query(FaqItem).filter(FaqItem.is_active == True)
    if category and category.lower() != "all":
        query = query.filter(FaqItem.category == category.lower())
    return query.order_by(FaqItem.sort_order.asc(), FaqItem.id.asc()).all()


def list_all_faqs(db: Session) -> List[FaqItem]:
    """Returns all FAQs (active and inactive) for Admin Knowledge Base Manager."""
    return db.query(FaqItem).order_by(FaqItem.sort_order.asc(), FaqItem.id.asc()).all()


def create_faq_item(db: Session, payload: FaqItemCreate) -> FaqItem:
    """Creates a new FAQ / Knowledge Base item."""
    now = utc_now()
    item = FaqItem(
        question_en=payload.question_en.strip(),
        question_ar=payload.question_ar.strip(),
        answer_en=payload.answer_en.strip(),
        answer_ar=payload.answer_ar.strip(),
        category=payload.category.strip().lower(),
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_faq_item(db: Session, faq_id: int, updates: FaqItemUpdate) -> FaqItem:
    """Updates an existing FAQ item."""
    item = db.query(FaqItem).filter(FaqItem.id == faq_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="FAQ item not found")

    if updates.question_en is not None:
        item.question_en = updates.question_en.strip()
    if updates.question_ar is not None:
        item.question_ar = updates.question_ar.strip()
    if updates.answer_en is not None:
        item.answer_en = updates.answer_en.strip()
    if updates.answer_ar is not None:
        item.answer_ar = updates.answer_ar.strip()
    if updates.category is not None:
        item.category = updates.category.strip().lower()
    if updates.sort_order is not None:
        item.sort_order = updates.sort_order
    if updates.is_active is not None:
        item.is_active = updates.is_active

    item.updated_at = utc_now()
    db.commit()
    db.refresh(item)
    return item


def delete_faq_item(db: Session, faq_id: int) -> bool:
    """Deletes an FAQ item."""
    item = db.query(FaqItem).filter(FaqItem.id == faq_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="FAQ item not found")
    db.delete(item)
    db.commit()
    return True


def seed_default_faqs(db: Session):
    """
    Seeds and synchronizes curated bilingual FAQs on system initialization.
    Preserves and prioritizes live production custom questions (1-7),
    alongside E-Commerce integrations & framework plugins (8-11),
    while cleaning up obsolete legacy questions so production changes are never lost.
    """
    try:
        defaults = [
            # --- Live Production Curated FAQs (1 to 7) ---
            {
                "question_en": "Can i use any any phone to set up the SMS Forwarder app?",
                "question_ar": "هل يمكنني استخدام أي هاتف لإعداد تطبيق SMS Forwarder?",
                "answer_en": "You must have an Android phone to be able to set up the SMS Forwarder app\nIt is an open-source application 'link in the dashboard,' and you have to agree to install it from outside the Google Play Store.",
                "answer_ar": "يجب أن يكون لديك هاتف يعمل بنظام Android حتى تتمكن من إعداد تطبيق SMS Forwarder.\nوهو تطبيق مفتوح المصدر، ويتوفر رابطه داخل لوحة التحكم. ويجب عليك الموافقة على تثبيته من خارج متجر Google Play.\nامنح صلاحيات قراءة الرسائل واستثناء موفر الطاقة.",
                "category": "forwarder",
                "sort_order": 1,
            },
            {
                "question_en": "Does this portal read all my SMS?",
                "question_ar": "هل تقوم هذه البوابة بقراءة جميع رسائل الموجودة على هاتفي؟",
                "answer_en": "No, the portal only read all that you pushed from your phone to us, as we don't have access to your phone\nso be sure to write the sender (number or text) like \"CIB\" and don't forget to add text filter like \"IPN inward transfer\" based on your bank message",
                "answer_ar": "لا، البوابة لا تقرأ جميع رسائل الـSMS الموجودة على هاتفك.\n\nالبوابة تستقبل فقط الرسائل التي يقوم هاتفك بإرسالها إليها، ولا نملك أي صلاحية للوصول إلى هاتفك أو قراءة رسائلك مباشرة.\n\nلذلك، تأكد من إعداد فلتر الرسائل بشكل صحيح:\n\nاكتب اسم أو رقم المرسل، مثل CIB.\nأضف Text Filter مناسبًا لرسالة البنك، مثل \"IPN inward transfer\".\n\nبهذه الطريقة، سيتم إرسال رسائل المعاملات المطلوبة فقط إلى البوابة.",
                "category": "forwarder",
                "sort_order": 2,
            },
            {
                "question_en": "What should I do if my bank not found at active banks?",
                "question_ar": "ماذا أفعل إذا لم أجد البنك الخاص بي ضمن Active Banks?",
                "answer_en": "You can create a trouble ticket and paste an example from your bank SMS text",
                "answer_ar": "يمكنك إنشاء تذكرة دعم (Trouble Ticket) وإرفاق مثال من نص رسالة الـSMS التي يرسلها البنك.",
                "category": "forwarder",
                "sort_order": 3,
            },
            {
                "question_en": "What should I do if a transaction is not appeared on Live Stream?",
                "question_ar": "ماذا يجب أن أفعل إذا لم تظهر المعاملة في البث المباشر (Live Stream)?",
                "answer_en": "If your phone forwarder was offline, ensure it reconnects; unread SMS will automatically sync upon reconnecting. If it still didn't appear, you can search manually using the Reference ID and it will be pending in the watch list for 30 minutes till it verifies",
                "answer_ar": "إذا لم تظهر المعاملة في Live Stream وكان تطبيق SMS Forwarder غير متصل، تأكد من إعادة الاتصال بالإنترنت، وستتم مزامنة رسائل الـSMS تلقائيًا.\n\nإذا لم تظهر المعاملة بعد ذلك، يمكنك البحث عنها يدويًا باستخدام Reference ID، وستظهر في Watch List بحالة Pending لمدة تصل إلى 30 دقيقة حتى يتم التحقق منها.",
                "category": "general",
                "sort_order": 4,
            },
            {
                "question_en": "How does automated InstaPay verification work?",
                "question_ar": "كيف تعمل منظومة التحقق الآلي من تحويلات إنستاباي؟",
                "answer_en": "The system automatically matches incoming bank SMS notifications against your order Reference IDs within 30 minutes. Once a match is confirmed, your order is verified in real-time.",
                "answer_ar": "يقوم النظام بمطابقة إشعارات ورسائل البنك اللحظية مع أرقام المرجع للطلبات خلال نافذة 30 دقيقة. بمجرد تأكيد التحويل في البنك، يتم تفعيل الطلب آلياً بدون أي تدخل بشري.",
                "category": "payments",
                "sort_order": 5,
            },
            {
                "question_en": "Where can customer find the InstaPay Reference ID?",
                "question_ar": "أين يجد العميل رقم المرجع (Reference ID) في تطبيق إنستاباي؟",
                "answer_en": "After completing the transfer in the official InstaPay app, a green success receipt is displayed with Reference ID & Receive SMS with Reference ID\nWhile our portal uses the SMS Reference ID, not the Screenshot Reference ID",
                "answer_ar": "بعد إتمام التحويل من خلال تطبيق InstaPay الرسمي، تظهر إيصال نجاح باللون الأخضر يحتوي على رقم مرجعي (Reference ID)، كما تصل رسالة SMS تحتوي أيضًا على رقم مرجعي (Reference ID).\n\nلكن البوابة الخاصة بنا تعتمد على الرقم المرجعي الموجود في رسالة الـSMS، وليس الرقم المرجعي الظاهر في لقطة الشاشة (Screenshot)",
                "category": "payments",
                "sort_order": 6,
            },
            {
                "question_en": "How do I integrate with WooCommerce, Shopify, or custom platforms?",
                "question_ar": "كيف أقوم بربط البوابة مع متجري على ووكومرس أو شوبيفاي أو لارفيل؟",
                "answer_en": "Download our ready-to-use plugins under the Plugins Hub tab. For WooCommerce and LearnDash, simply upload the zip in WordPress. For Node.js, Laravel, or React, use our lightweight zero-dependency SDKs.",
                "answer_ar": "يمكنك تحميل الإضافات الجاهزة من قسم حزم التكامل (Plugins Hub). لمتاجر ووكومرس وليرنداش، ارفع ملف ZIP مباشرة في ووردبريس. ولمشاريع لارفيل ورياكت ونود، استخدم مكتباتنا البرمجية المعتمدة.",
                "category": "plugins",
                "sort_order": 7,
            },
            # --- E-Commerce & Framework Integrations (8 to 11) ---
            {
                "question_en": "How can I integrate Motaaked with my E-Commerce store (WooCommerce, Shopify, Laravel, etc.)?",
                "question_ar": "كيف يمكنني ربط منصة متأكد مع متجري الإلكتروني (ووكومرس، شوبيفاي، لارفيل، إلخ)؟",
                "answer_en": "You can integrate Motaaked into any e-commerce platform using our turnkey plugins and SDKs: 1. WooCommerce: Native WordPress gateway with automated order status updates and HPOS support. 2. Universal Drop-In Widget: Add 2 lines of JavaScript (`motaaked-checkout.js`) to any checkout page for an instant modal checkout. 3. Shopify: Seamless integration via Draft Orders API and a Liquid checkout modal snippet. 4. Framework SDKs: Full-featured libraries for Laravel, Node.js/Express, React/Next.js, Python, and pure PHP. Each solution creates a checkout session, displays your InstaPay handle, prompts the customer for their Bank SMS Reference ID, and verifies the payment instantly via POST /v1/orders/verify.",
                "answer_ar": "يمكنك ربط منصة متأكد بأي متجر إلكتروني باستخدام إضافاتنا ومكتباتنا البرمجية الجاهزة: 1. ووكومرس: إضافة ووردبريس متكاملة لتحديث حالة الطلبات آلياً مع دعم كامل لنظام التخزين عالي الأداء (HPOS). 2. نافذة الدفع السريع (Universal Drop-In Widget): إضافة سطرين فقط من كود JavaScript (motaaked-checkout.js) لأي صفحة دفع لفتح نافذة منبثقة عصرية. 3. شوبيفاي: ربط سلس عبر واجهة مسودات الطلبات (Draft Orders API) وقالب Liquid. 4. حزم برمجية مخصصة لأطر عمل لارفيل، نود، رياكت/نكست، بايثون، وPHP. تقوم جميع الحلول بإنشاء جلسة دفع وعرض عنوان التحويل، ثم استلام الرقم المرجعي للرسالة النصية SMS والتحقق منه فوراً عبر واجهة API.",
                "category": "ecommerce",
                "sort_order": 8,
            },
            {
                "question_en": "How can I build and customize an E-Commerce checkout flow using the API?",
                "question_ar": "كيف يمكنني بناء وتخصيص تجربة دفع إلكتروني خاصة بمتجري باستخدام الـ API؟",
                "answer_en": "Building a custom checkout requires just 2 API steps: 1. Call POST /v1/orders/create with your Merchant API Key (X-API-Key), order_id, and amount to register the pending order. 2. On your checkout UI, display your InstaPay IPA handle and an input field for the customer's Bank SMS Reference ID. 3. When the customer submits the form, call POST /v1/orders/verify. The gateway performs an atomic lookup against incoming bank SMS credits. If matched, verified=true is returned, allowing you to instantly fulfill the order, unlock downloads, or deliver goods. You can also embed our ready-made Drop-In modal widget (/checkout/embed?session=...) to avoid building custom UI.",
                "answer_ar": "يمكنك بناء مسار دفع مخصص بخطوتين فقط عبر الـ API: 1. إرسال طلب POST إلى /v1/orders/create يحتوي على مفتاح التاجر (X-API-Key) ورقم الطلب والمبلغ. 2. عرض عنوان إنستاباي الخاص بك في صفحة الشراء مع حقل مخصص لإدخال الرقم المرجعي للرسالة النصية SMS المستلمة من البنك. 3. عند ضغط العميل على تأكيد الدفع، استدعِ POST إلى /v1/orders/verify ليقوم النظام بمطابقة العملية فوراً. إذا تمت المطابقة، تُرجع البوابة verified=true لتتمكن من تسليم الطلب فورياً. يمكنك أيضاً استخدام نافذة الدفع الجاهزة المضمنة لتوفير وقت التطوير.",
                "category": "ecommerce",
                "sort_order": 9,
            },
            {
                "question_en": "How does the Universal 2-Line Drop-In Checkout Widget work for E-Commerce?",
                "question_ar": "كيف تعمل نافذة الدفع السريع الشاملة (Universal Drop-In Widget) في المتاجر بسطرين كود فقط؟",
                "answer_en": "The Universal Drop-In Widget (`motaaked-checkout.js`) is a zero-dependency JavaScript SDK that works with any CMS, website, or framework. Simply include `<script src='https://your-domain/static/js/motaaked-checkout.js'></script>` and trigger `MotaakedCheckout.open({ sessionToken: '...', onSuccess: (res) => { ... } })`. It opens a sleek, mobile-responsive modal overlay with a 15-minute countdown, InstaPay handle copy button, Bank SMS Reference ID validation, and real-time verification polling. When verified, it triggers your onSuccess callback with order details.",
                "answer_ar": "نافذة الدفع السريع (motaaked-checkout.js) هي مكتبة JavaScript مستقلة تماماً بدون أي مكتبات خارجية تعمل مع أي متجر أو موقع أو قالب. ما عليك سوى تضمين ملف السكريبت ثم استدعاء MotaakedCheckout.open مع رمز الجلسة والدوال المرجعية عند النجاح. تفتح النافذة واجهة منبثقة متجاوبة وعصرية تحتوي على عد تنازلي مدته 15 دقيقة، زر لنسخ عنوان التحويل، حقل إدخال الرقم المرجعي لرسالة البنك SMS، وفحص آلي دوري حتى تأكيد الدفع واستدعاء دالة النجاح فوراً.",
                "category": "ecommerce",
                "sort_order": 10,
            },
            {
                "question_en": "Why does Motaaked verify the Bank SMS Reference ID instead of the InstaPay screenshot?",
                "question_ar": "لماذا تعتمد منصة متأكد حصرياً على الرقم المرجعي لرسالة البنك SMS وليس لقطة شاشة إنستاباي؟",
                "answer_en": "Motaaked's zero-trust automated matching engine operates by ingesting official, cryptographic bank SMS alerts forwarded in real time from your merchant device. App screenshots can be easily faked, photoshopped, or reused. Furthermore, banks assign their own unique internal transaction reference numbers in the SMS that directly reconcile with bank statements. Matching the SMS Reference ID guarantees 100% fraud prevention and instant, tamper-proof verification.",
                "answer_ar": "يعتمد محرك التحقق الآلي في منصة متأكد على استقبال ومعالجة رسائل البنك النصية الرسمية الواردة إلى هاتف التاجر لحظياً. لقطات الشاشة للتطبيقات قابلة للتزييف أو التعديل بالفوتوشوب أو التكرار الاحتيالي. بالإضافة إلى ذلك، تصدر البنوك أرقاماً مرجعية فريدة لكل تحويل في رسائلها النصية تتطابق مباشرة مع كشف الحساب البنكي. التحقق عبر الرقم المرجعي للرسالة النصية SMS يضمن منع الاحتيال بنسبة 100% وتأكيداً لحظياً موثوقاً.",
                "category": "ecommerce",
                "sort_order": 11,
            },
            # --- Platform Awareness & Operations (12 to 19) ---
            {
                "question_en": "What is Live Stream and how does it work?",
                "question_ar": "ما هو البث المباشر (Live Stream) وكيف يعمل؟",
                "answer_en": "Live Stream (Tab 1 in your dashboard) is a real-time monitor that displays incoming bank transfer SMS messages the exact moment they are pushed from your forwarder phone. Each card reveals the received amount, timestamp, originating bank, sending party, and current claim status (UNCLAIMED or CLAIMED). It gives store owners and branch cashiers a live, transparent window into incoming payments as they happen without having to manually check their phone or bank app.",
                "answer_ar": "البث المباشر (Live Stream) في التبويب الأول هو شاشة مراقبة لحظية تعرض إشعارات ورسائل البنك فور وصولها من هاتف التحويل. توضح كل بطاقة معاملة: المبلغ المستلم، وقت وتاريخ المعاملة، البنك المستلم، وحالة المطالبة (غير مطالب بها / UNCLAIMED أو تمت المطالبة / CLAIMED). يتيح ذلك لأصحاب المتاجر وكاشيرات الفروع رؤية التحويلات الواردة لحظة بلحظة دون الحاجة لفتح هاتف التحويل أو تطبيق البنك.",
                "category": "operations",
                "sort_order": 12,
            },
            {
                "question_en": "How can I make a manual search for a Reference ID?",
                "question_ar": "كيف أقوم بالبحث اليدوي عن رقم المرجع (Manual Reference Search)؟",
                "answer_en": "To perform a Manual Search, navigate to Tab 1 (Live Tracker & Watchlist) or Tab 2 (Audit Explorer). Enter the 12-digit Bank SMS Reference ID provided by the customer into the Reference ID search box and click Search. The system queries the bank credits database; if found, it immediately displays the transaction details, verification status, and bank timestamp. If the SMS has not yet arrived due to telecom delay, the system automatically places it into the Pending Watchlist to monitor it live for up to 30 minutes without needing to re-enter it. Each manual search deducts 1 search credit from your active wallet balance.",
                "answer_ar": "لإجراء البحث اليدوي (Manual Search)، توجه إلى التبويب الأول (المراقبة الحية) أو التبويب الثاني (سجل المعاملات). اكتب رقم المرجع البنكي (12 رقماً) الذي يقدمه العميل في خانة البحث ثم اضغط على زر فحص المرجع. يقوم النظام بالبحث في قاعدة بيانات رسائل البنك فوراً؛ وإذا وُجدت الرسالة، تظهر تفاصيل العملية وحالتها ووقت وصولها. وإذا لم تكن الرسالة قد وصلت بعد بسبب تأخر شبكات الاتصالات، يُسجل الرقم تلقائياً في قائمة الانتظار (Watchlist) لمراقبته آلياً لمدة 30 دقيقة بمجرد وصوله. يخصم كل بحث يدوي نقطة واحدة (1 Credit) من رصيد محفظتك النشط.",
                "category": "operations",
                "sort_order": 13,
            },
            {
                "question_en": "What is the charging and credit deduction mechanism?",
                "question_ar": "ما هي آلية خصم النقاط والرسوم (Charging Mechanism)؟",
                "answer_en": "Motaaked utilizes a fair, transparent Waterfall Credit Deduction model for payment verification: 1. 1 Verification / Search = 1 Credit: Deducted only upon verifying an order or executing a manual reference search. 2. Waterfall Deduction Hierarchy: The platform first consumes your Free Monthly Tier Credits (renewed on the 1st of each month). If a Day Pass is active, all searches are 100% free and unlimited. Next, it consumes any active Promotional / Top-Up Wallet Credits. 3. No Fees on Payments: InstaPay and IPN network transfers have 0% transaction fees from the Central Bank of Egypt. Motaaked does not take any percentage cut of your transaction money.",
                "answer_ar": "تعتمد منصة متأكد على نموذج المحفظة الشلالية (Waterfall Deduction Model) العادل والشفاف: 1. 1 عملية فحص أو تحقق = 1 نقطة (Credit): تُخصم فقط عند التحقق من طلب دفع أو إجراء بحث يدوي عن رقم المرجع. 2. ترتيب الخصم الشلالي: يستهلك النظام أولاً النقاط الشهرية المجانية (التي تتجدد تلقائياً أول كل شهر ميلادي). وفي حال تفعيل تذكرة اليوم غير المحدود (Day Pass) تكون جميع العمليات مجانية وغير محدودة. وبعدها يتم الخصم من رصيد باقات الشحن الترويجية. 3. صفر عمولات على التحويلات: شبكة إنستاباي القومية مجانية بنسبة 0% وبدون عمولات من البنك المركزي المصري، ولا تقتطع منصة متأكد أي نسبة مئوية من أموال معاملاتك.",
                "category": "billing",
                "sort_order": 14,
            },
            {
                "question_en": "How can we recharge our balance and buy credit packages?",
                "question_ar": "كيف يمكننا شحن الرصيد وشراء باقات النقاط (Recharge / Top-Up)؟",
                "answer_en": "To recharge your credit balance: 1. Navigate to Tab 3 (Packages & Top-Up / شحن الرصيد) in your merchant dashboard. 2. Select your desired package (e.g. Starter, Pro, or Enterprise) and click Recharge. 3. The platform displays an automated invoice with the portal's official InstaPay IPA handle and the exact required amount. 4. Open your InstaPay app, transfer the exact amount, and copy the Bank SMS Reference ID received on your phone. 5. Paste the Reference ID into the invoice confirmation box and click Verify Payment. 6. The platform's automated engine verifies the transfer instantly and activates your credits immediately 24/7. Alternatively, if your administrator issued a prepaid voucher code, enter it under Redeem Voucher to top up instantly.",
                "answer_ar": "لشحن رصيد محفظتك وشراء باقات النقاط: 1. توجه إلى التبويب الثالث (باقات الشحن / Packages & Top-Up) في لوحة التحكم. 2. اختر الباقة المناسبة لاحتياجاتك (مثلاً: Starter أو Pro أو Enterprise) واضغط على شحن الرصيد. 3. تُظهر المنصة فاتورة سداد فورية تحتوي على عنوان إنستاباي المعتمد للمنصة والمبلغ المطلوب بدقة. 4. افتح تطبيق إنستاباي على هاتفك، وقم بتحويل المبلغ، ثم انسخ رقم المرجع البنكي من رسالة البنك النصية SMS التي تصلك. 5. الصق رقم المرجع في خانة تأكيد الفاتورة واضغط تأكيد الدفع. 6. يتحقق محرك النظام من التحويل آلياً ويقوم بتفعيل النقاط في محفظتك فوراً على مدار الساعة (24/7). كما يمكنك أيضاً شحن رصيدك إذا كان لديك كود قسيمة مسبقة الدفع بإدخاله في قسم شحن عبر قسيمة (Redeem Voucher).",
                "category": "billing",
                "sort_order": 15,
            },
            {
                "question_en": "What do you mean by Validity and when do credits expire?",
                "question_ar": "ماذا تعني فترة الصلاحية (Validity Period) ومتى تنتهي النقاط؟",
                "answer_en": "Validity Period defines the active lifespan of purchased credits and merchant accounts: 1. Package Validity: When you purchase a top-up package, it includes a defined validity duration (e.g., 30, 90, or 365 days). All purchased credits remain usable until that date. 2. Free Monthly Tier: Resets on the 1st day of every calendar month at 00:00 UTC. Unused free tier credits do not roll over to the next month. 3. Day Pass Unlimited: Grants 24 consecutive hours of unlimited searches from the exact second of activation. 4. Expiration Monitoring: Your active expiration date is prominently displayed on your top dashboard badge. If validity expires, you can simply purchase any package or redeem a voucher to instantly reactivate your wallet balance.",
                "answer_ar": "فترة الصلاحية (Validity Period) هي المدة الزمنية المحددة التي تظل فيها نقاطك وحسابك نشطاً وقابلاً للاستخدام: 1. صلاحية باقات الشحن: عند شراء باقة نقاط، يكون لها مدة صلاحية محددة (مثل 30 أو 90 أو 365 يوماً). تظل كافة النقاط المشتراة صالحة للاستخدام حتى تاريخ الانتهاء. 2. النقاط الشهرية المجانية: تتجدد تلقائياً في اليوم الأول من كل شهر ميلادي الساعة 00:00، ولا ترحل النقاط المجانية غير المستهلكة للشهر التالي. 3. تذكرة اليوم غير المحدود (Day Pass): تمنحك 24 ساعة متواصلة من عمليات البحث والتحقق غير المحدودة تبدأ من لحظة التفعيل. 4. متابعة الصلاحية: يظهر تاريخ انتهاء الصلاحية بوضوح في الشارة أعلى لوحة التحكم. وإذا انتهت الصلاحية، يكفي شراء أي باقة أو تفعيل قسيمة شحن لإعادة تفعيل رصيدك فورياً.",
                "category": "billing",
                "sort_order": 16,
            },
            {
                "question_en": "How can I activate SMS Push / Webhook Ingestion?",
                "question_ar": "كيف أقوم بتفعيل إرسال الرسائل الفوري (SMS Push / Webhook)؟",
                "answer_en": "To activate automated SMS Push from your Android forwarder device: 1. Open the SMS Forwarder application on your dedicated forwarder phone. 2. Go to Settings / Rules and add a Webhook (HTTP POST) destination. 3. Set the Destination URL to your portal's webhook endpoint: https://your-domain.com/webhook (e.g., https://insta.saf7etna.dpdns.org/webhook). 4. Set the Request Method to POST and format to JSON. 5. In Custom Headers, add: X-Forwarder-Key: YOUR_FORWARDER_SECRET_KEY (as configured in Tab 4 / Settings). 6. Set the JSON payload template to dispatch {\"sender\": \"[sender]\", \"message\": \"[message]\", \"timestamp\": [timestamp]}. 7. Turn on the Auto-forward incoming SMS toggle and test connection. Incoming bank credits will now push in under 2 seconds.",
                "answer_ar": "لتفعيل إرسال الرسائل اللحظي (SMS Push) من هاتف الأندرويد إلى المنصة: 1. افتح تطبيق SMS Forwarder على هاتف التحويل المخصص للخدمة. 2. انتقل إلى الإعدادات / القواعد (Rules) وأضف وجهة إرسال من نوع Webhook (HTTP POST). 3. اكتب رابط الخادم (Webhook URL) الخاص بمنصتك: https://your-domain.com/webhook (مثال: https://insta.saf7etna.dpdns.org/webhook). 4. اختر طريقة الإرسال POST وصيغة البيانات JSON. 5. في خانة Custom Headers، أضف المفتاح السري للتحويل: X-Forwarder-Key: YOUR_FORWARDER_SECRET_KEY (المحدد في إعدادات النظام في تبويب الإدارة). 6. اضبط قالب الـ JSON ليرسل المرسل والرسالة والوقت: {\"sender\": \"[sender]\", \"message\": \"[message]\", \"timestamp\": [timestamp]}. 7. فعّل خيار التحويل التلقائي عند استلام الرسائل واضغط اختبار الاتصال، وسيتم استقبال رسائل البنوك خلال أقل من ثانيتين.",
                "category": "forwarder",
                "sort_order": 17,
            },
            {
                "question_en": "How can I set up the SMS Forwarder without sending all my personal SMS messages?",
                "question_ar": "كيف أضبط تطبيق التحويل لحماية خصوصيتي دون إرسال جميع رسائل هاتفي؟",
                "answer_en": "To maintain 100% personal privacy on your forwarder phone and ensure only bank payment alerts are pushed: 1. In the SMS Forwarder application, create a Dedicated Forwarding Rule rather than forwarding all SMS. 2. In the Sender Filter field, whitelist only your specific banks (e.g., CIB, NBE, BM, QNB, AAIB, BDC, AlexBank, HSBC). 3. In the Content / Text Filter field, enter incoming payment keywords: \"تم تحويل\" OR \"IPN inward transfer\" OR \"إيداع\" OR \"credited\". 4. Add an Exclusion Filter for debit/spending alerts containing \"سحب\" or \"خصم\" or \"مشتريات\" or \"debit\". 5. With these rules, personal text messages, OTP verification codes, and unrelated SMS alerts are strictly ignored by the app and are never transmitted over the internet.",
                "answer_ar": "لضمان الخصوصية التامة (100%) لهاتفك والتأكد من إرسال رسائل التحويلات البنكية فقط دون أي رسائل شخصية: 1. داخل تطبيق SMS Forwarder، قم بإنشاء قاعدة تحويل مخصصة (Specific Rule) وتجنب خيار تحويل جميع الرسائل. 2. في حقل فلتر المرسل (Sender Filter): أضف أسماء البنوك المعتمدة لديك فقط (مثل: CIB، NBE، BM، QNB، AAIB، AlexBank، HSBC). 3. في حقل فلتر نص الرسالة (Content / Text Filter): أضف الكلمات الدالة على التحويلات الواردة فقط، مثل: \"تم تحويل\" أو \"IPN inward transfer\" أو \"إيداع\" أو \"credited\". 4. أضف استثناءً لكلمات الخصم والمشتريات مثل: \"سحب\" أو \"خصم\" أو \"مشتريات\" أو \"debit\". 5. بفضل هذا الضبط، يتجاهل التطبيق تماماً أي رسائل شخصية أو رموز تحقق (OTP) أو رسائل دعائية، ولا يخرج من هاتفك سوى إشعارات الإيداع البنكية المطلوبة للمتجر.",
                "category": "forwarder",
                "sort_order": 18,
            },
            {
                "question_en": "What is the meaning of Heartbeat & how does it work?",
                "question_ar": "ما هو النبض (Heartbeat) وكيف يعمل لمراقبة هاتف التحويل؟",
                "answer_en": "Heartbeat is an automated telemetry health ping sent by the forwarder phone to Motaaked every 5 minutes: 1. What it monitors: It reports the phone's current battery percentage, charging state (plugged in or running on battery), network connection type (Wi-Fi or 4G), and forwarder background service vitality. 2. How it works: The app sends a lightweight ping to /v1/telemetry/heartbeat. Motaaked updates the forwarder telemetry badge on Tab 1 and Tab 4. 3. Zero-Downtime Alerts: If Motaaked does not receive a heartbeat for more than 15 minutes, it flags the forwarder status as WARNING or OFFLINE, alerting administrators immediately before any incoming payments are missed due to a drained battery or disconnected Wi-Fi.",
                "answer_ar": "النبض (Heartbeat) هو إشارة فحص وحالة صحية دورية يرسلها هاتف التحويل تلقائياً إلى المنصة كل 5 دقائق: 1. ماذا يراقب: يقوم بإرسال نسبة شحن البطارية الحالية، حالة الشاحن (متصل بالكهرباء أم يعمل على البطارية)، نوع شبكة الاتصال (Wi-Fi أو بيانات 4G)، واستقرار التطبيق في الخلفية. 2. كيف يعمل: يرسل التطبيق إشارة خفيفة إلى مسار /v1/telemetry/heartbeat، لتقوم المنصة بتحديث شارة حالة الهاتف في التبويب الأول والرابع فوراً. 3. الحماية من انقطاع الخدمة: إذا انقطعت إشارات النبض لأكثر من 15 دقيقة، تتغير حالة الهاتف تلقائياً إلى تحذير / WARNING أو غير متصل / OFFLINE، لتنبيه التاجر فوراً لتفقد شاحن الهاتف أو شبكة الإنترنت قبل أن تتأثر عمليات الدفع الواردة لمتجرك.",
                "category": "forwarder",
                "sort_order": 19,
            },
        ]

        now = utc_now()

        # 1. Clean up obsolete old seed questions that were replaced by the live production questions
        obsolete_titles = [
            "what are the official instapay transaction limits in egypt?",
            "what should i do if a transaction is not matched automatically?",
            "where does the customer find the bank sms reference id?",
            "how do i set up the sms forwarder app on my android phone?",
            "how can i integrate instatakeed with my e-commerce store (woocommerce, shopify, laravel, etc.)?",
            "how can i integrate motaaked with my e-commerce store (woocommerce, shopify, laravel, etc.)?",
            "why does instatakeed verify the bank sms reference id instead of the instapay screenshot?",
            "why does motaaked verify the bank sms reference id instead of the instapay screenshot?",
        ]
        for obs_title in obsolete_titles:
            obs_matches = db.query(FaqItem).filter(func.lower(FaqItem.question_en) == obs_title).all()
            for obs in obs_matches:
                db.delete(obs)

        # 2. Synchronize all 11 curated FAQs (match by question text first, then sort_order)
        for item in defaults:
            existing = db.query(FaqItem).filter(
                func.lower(FaqItem.question_en) == item["question_en"].strip().lower()
            ).first()

            if not existing:
                existing = db.query(FaqItem).filter(
                    FaqItem.sort_order == item["sort_order"]
                ).first()

            if existing:
                existing.question_en = item["question_en"]
                existing.question_ar = item["question_ar"]
                existing.answer_en = item["answer_en"]
                existing.answer_ar = item["answer_ar"]
                existing.category = item["category"]
                existing.sort_order = item["sort_order"]
                existing.is_active = True
                existing.updated_at = now
            else:
                f = FaqItem(
                    question_en=item["question_en"],
                    question_ar=item["question_ar"],
                    answer_en=item["answer_en"],
                    answer_ar=item["answer_ar"],
                    category=item["category"],
                    sort_order=item["sort_order"],
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                db.add(f)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[SEED FAQS NOTICE] {e}")


# =========================================================================
# E-Commerce Drop-In Popup Checkout Sessions
# =========================================================================

def create_checkout_session(
    db: Session,
    merchant: User,
    data: CreateCheckoutSessionRequest,
) -> CheckoutSession:
    """
    Creates a temporary 15-minute checkout session for drop-in modal or hosted checkout.
    Enforces:
    1. Global Portal E-Commerce switch (ECOMMERCE_GATEWAY_ENABLED)
    2. Merchant E-Commerce switch (merchant.ecommerce_enabled)
    3. Active subscription validity (subscription_expires_at > now)
    4. Minimum credit balance (credits_balance >= order_verification_credit_cost)
    """
    settings_dict = get_system_settings(db)
    if not settings_dict.get("ecommerce_gateway_enabled", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="E-Commerce Integration Gateway is currently disabled by portal administration.",
        )

    if not getattr(merchant, "ecommerce_enabled", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="E-Commerce integration is disabled for this merchant account. Please contact portal administration or upgrade your subscription plan.",
        )

    now = utc_now()
    if merchant.subscription_expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Merchant subscription expired on {merchant.subscription_expires_at.strftime('%Y-%m-%d')}. Please top up your subscription in the portal.",
        )

    required_cost = settings_dict.get("order_verification_credit_cost", 1)
    if merchant.credits_balance < required_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Insufficient merchant credits (Current balance: {merchant.credits_balance}, required: {required_cost}). Please recharge your wallet in the portal.",
        )

    session_token = f"cs_{secrets.token_hex(20)}"
    session = CheckoutSession(
        session_token=session_token,
        merchant_id=merchant.id,
        order_id=data.order_id.strip(),
        amount=float(data.amount),
        currency=data.currency or "EGP",
        description=data.description,
        return_url=data.return_url,
        cancel_url=data.cancel_url,
        webhook_url=data.webhook_url,
        status="PENDING",
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    db.add(session)

    # Pre-register order into pending_orders if not already existing
    existing_order = db.query(PendingOrder).filter(PendingOrder.order_id == data.order_id.strip()).first()
    if not existing_order:
        pending_order = PendingOrder(
            user_id=merchant.id,
            order_id=data.order_id.strip(),
            amount=float(data.amount),
            status="PENDING",
            created_at=now,
        )
        db.add(pending_order)

    db.commit()
    db.refresh(session)
    return session


def get_checkout_session_public(db: Session, session_token: str) -> Dict[str, Any]:
    """
    Retrieves public session details for rendering the Drop-In Modal iframe.
    Does not expose sensitive merchant credentials.
    """
    session = db.query(CheckoutSession).filter(CheckoutSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Checkout session not found or invalid.")

    now = utc_now()
    if session.status == "PENDING" and session.expires_at < now:
        session.status = "EXPIRED"
        db.commit()

    merchant = db.query(User).filter(User.id == session.merchant_id).first()
    portal_cfg = get_system_settings(db)

    instapay_handle = portal_cfg.get("instapay_handle", "haitham@instapay")
    merchant_name = merchant.name if merchant else "Verified Merchant"

    seconds_remaining = max(0, int((session.expires_at - now).total_seconds())) if session.status == "PENDING" else 0

    return {
        "session_token": session.session_token,
        "order_id": session.order_id,
        "amount": session.amount,
        "currency": session.currency,
        "description": session.description or f"Order #{session.order_id}",
        "merchant_name": merchant_name,
        "instapay_handle": instapay_handle,
        "status": session.status,
        "expires_at": session.expires_at.isoformat(),
        "seconds_remaining": seconds_remaining,
        "return_url": session.return_url,
    }


def verify_checkout_session(
    db: Session,
    session_token: str,
    reference_id: str,
) -> Tuple[bool, CheckoutSession, str]:
    """
    Verifies payment for an active Drop-In CheckoutSession and deducts 1 credit.
    """
    session = db.query(CheckoutSession).filter(CheckoutSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid checkout session token.")

    if session.status == "MATCHED":
        return True, session, "Payment already verified and confirmed."

    now = utc_now()
    if session.expires_at < now:
        session.status = "EXPIRED"
        db.commit()
        return False, session, "Checkout session has expired. Please initiate a new payment session."

    merchant = db.query(User).filter(User.id == session.merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated merchant account not found.")

    settings_dict = get_system_settings(db)
    if not settings_dict.get("ecommerce_gateway_enabled", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="E-Commerce Integration Gateway is currently disabled by portal administration.",
        )

    if not getattr(merchant, "ecommerce_enabled", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="E-Commerce integration is disabled for this merchant account.",
        )

    required_cost = settings_dict.get("order_verification_credit_cost", 1)
    if merchant.credits_balance < required_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Insufficient merchant credits (Current balance: {merchant.credits_balance}, required: {required_cost}). Please top up in the portal.",
        )

    is_verified, order, matched_credit, message = verify_order(
        db=db,
        order_id=session.order_id,
        reference_id=reference_id,
        merchant_user=merchant,
    )

    if is_verified:
        session.status = "MATCHED"
        session.reference_id = reference_id.strip()
        session.matched_at = now
        db.commit()
        db.refresh(session)
        return True, session, "Payment successfully verified!"

    return False, session, message


_DEV_GUIDE_CACHE: Dict[str, Any] = {"mtime": 0.0, "items": []}

_COPILOT_STOP_WORDS = {
    # English
    "what", "where", "when", "why", "how", "who", "which", "whose", "whom",
    "can", "cant", "cannot", "could", "would", "should", "will", "shall", "may", "might", "must",
    "does", "doesnt", "did", "didnt", "have", "has", "had", "having",
    "the", "this", "that", "these", "those", "and", "but", "for", "with",
    "from", "into", "onto", "your", "you", "our", "their", "its", "any", "all",
    "are", "was", "were", "been", "being", "not", "use", "using", "able", "out",
    "hello", "hi", "hey", "greetings", "good", "morning", "evening", "thanks", "thank", "please",
    "instapay", "portal", "motaaked", "gateway",
    # Arabic
    "ما", "ماذا", "لماذا", "كيف", "أين", "اين", "متى", "هل", "من", "عن", "في",
    "على", "الى", "إلى", "مع", "هذا", "هذه", "ذلك", "تلك", "كان", "كانت",
    "يكون", "تكون", "ان", "أن", "انها", "أنها", "هو", "هي", "كل", "جميع",
    "أي", "اي", "غير", "بين", "لدى", "عند", "أو", "او", "قد", "تم", "لا", "لن", "لم",
    "إنستاباي", "انستاباي", "منصة", "بوابة", "متأكد", "نفس", "إذا", "اذا",
    "سلام", "السلام", "عليكم", "مرحبا", "مرحباً", "اهلا", "أهلا", "شكرا", "شكراً",
    "صباح", "مساء", "الخير", "خير", "اريد", "أريد", "ممكن", "فضلك", "لو",
}


def _tokenize_copilot_text(s: str) -> List[str]:
    """Tokenize and normalize text for semantic Q&A scoring with Arabic/English stemming."""
    s = s.lower()
    s = re.sub(r'[إأآا]', 'ا', s)
    s = re.sub(r'ة', 'ه', s)
    s = re.sub(r'ى', 'ي', s)
    tokens = re.findall(r'[\w]+', s)
    res = []
    for t in tokens:
        if len(t) <= 2:
            continue
        if t.startswith('ال') and len(t) > 4:
            t = t[2:]
        if t in _COPILOT_STOP_WORDS:
            continue
        # Arabic dual & plural suffix stripping (e.g. فرعين -> فرع, كاشيرات -> كاشير, مواقع -> موقع)
        if t.endswith(('ين', 'ان', 'ات', 'ون')) and len(t) > 4:
            t = t[:-2]
        # English plural ending (e.g. cashiers -> cashier, websites -> website, branches -> branch)
        if t.endswith('es') and len(t) > 5 and not t.endswith('sses'):
            t = t[:-2]
        elif t.endswith('s') and len(t) > 4 and not t.endswith('ss'):
            t = t[:-1]
        res.append(t)
    return res


def get_developer_guide_faqs() -> List[Dict[str, Any]]:
    """
    Parses and caches Section 15 of DEVELOPER_INTEGRATION_GUIDE.md into structured bilingual Q&A objects.
    Checks multiple deployment filesystem locations (app package, workspace root, container paths).
    Falls back seamlessly to the pre-compiled built-in knowledge base (BUILTIN_GUIDE_FAQS).
    """
    global _DEV_GUIDE_CACHE

    possible_paths = [
        Path(__file__).resolve().parent / "DEVELOPER_INTEGRATION_GUIDE.md",
        Path(__file__).resolve().parent.parent / "DEVELOPER_INTEGRATION_GUIDE.md",
        Path("/app/DEVELOPER_INTEGRATION_GUIDE.md"),
        Path("/app/app/DEVELOPER_INTEGRATION_GUIDE.md"),
        Path("DEVELOPER_INTEGRATION_GUIDE.md"),
    ]
    guide_path = None
    for p in possible_paths:
        if p.exists():
            guide_path = p
            break

    if guide_path:
        try:
            current_mtime = guide_path.stat().st_mtime
            if _DEV_GUIDE_CACHE.get("mtime") == current_mtime and _DEV_GUIDE_CACHE.get("items"):
                return _DEV_GUIDE_CACHE["items"]

            text = guide_path.read_text(encoding="utf-8")
            sec15_match = re.search(r'## 15\.\s+Comprehensive Integration Q&A.*', text, re.DOTALL)
            if sec15_match:
                sec15_text = sec15_match.group(0)
                blocks = re.split(r'####\s+Q\d+:\s*', sec15_text)

                items = []
                for i, b in enumerate(blocks[1:], 1):
                    lines = b.strip().split("\n")
                    title = lines[0].strip()
                    parts = title.split(" / ")
                    q_en = parts[0].strip()
                    q_ar = parts[1].strip() if len(parts) > 1 else q_en

                    en_match = re.search(r'-\s+\*\*English\*\*:\s*(.*?)(?=\n-\s+\*\*العربية\*\*:|\Z)', b, re.DOTALL)
                    ar_match = re.search(r'-\s+\*\*العربية\*\*:\s*(.*?)(?=\n####|\n---|\Z)', b, re.DOTALL)

                    en_ans = en_match.group(1).strip() if en_match else ""
                    ar_ans = ar_match.group(1).strip() if ar_match else ""

                    t_tokens = set(_tokenize_copilot_text(title))
                    b_tokens = set(_tokenize_copilot_text(en_ans + ' ' + ar_ans)) - t_tokens

                    items.append({
                        "id": i,
                        "title": title,
                        "q_en": q_en,
                        "q_ar": q_ar,
                        "answer_en": en_ans,
                        "answer_ar": ar_ans,
                        "title_tokens": t_tokens,
                        "body_tokens": b_tokens,
                    })

                if items:
                    _DEV_GUIDE_CACHE = {"mtime": current_mtime, "items": items}
                    return items
        except Exception as e:
            logger.warning(f"Error loading developer integration guide FAQs from file: {e}")

    # Fallback to pre-compiled built-in knowledge base if file is absent in container
    if not _DEV_GUIDE_CACHE.get("items"):
        try:
            from app.faqs_data import BUILTIN_GUIDE_FAQS
            items = []
            for it in BUILTIN_GUIDE_FAQS:
                t_tokens = set(_tokenize_copilot_text(it["title"]))
                b_tokens = set(_tokenize_copilot_text(it["answer_en"] + ' ' + it["answer_ar"])) - t_tokens
                items.append({
                    "id": it["id"],
                    "title": it["title"],
                    "q_en": it["q_en"],
                    "q_ar": it["q_ar"],
                    "answer_en": it["answer_en"],
                    "answer_ar": it["answer_ar"],
                    "title_tokens": t_tokens,
                    "body_tokens": b_tokens,
                })
            _DEV_GUIDE_CACHE = {"mtime": 1.0, "items": items}
            return items
        except Exception as e:
            logger.warning(f"Error loading fallback BUILTIN_GUIDE_FAQS: {e}")

    return _DEV_GUIDE_CACHE.get("items", [])


def copilot_chat_service(db: Session, payload: Any, user: Optional[Any] = None) -> Dict[str, Any]:
    """
    Intelligent AI Copilot conversational assistant for Motaaked.
    Grounded on active FAQs, system telemetry, forwarder status, and developer integration documentation.
    Supports local grounded rule-based offline engine, as well as external LLM providers (Gemini, OpenAI).
    """
    settings_dict = get_system_settings(db)
    if not settings_dict.get("copilot_widget_enabled", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI Copilot Assistant is currently disabled by administrator / المساعد الذكي معطل حالياً من قِبل المسؤول.",
        )

    query = payload.message.strip()
    is_arabic = bool(re.search(r'[\u0600-\u06FF]', query))
    if getattr(payload, "language", "auto") == "ar":
        is_arabic = True
    elif getattr(payload, "language", "auto") == "en":
        is_arabic = False

    if not query:
        return {
            "reply": "يرجى كتابة سؤالك أو اختيار أحد الموضوعات المقترحة أدناه." if is_arabic else "Please enter a question or select one of the suggested topics below.",
            "suggestions": ["كيف أربط ووكومرس؟", "أين أجد رقم المرجع البنكي؟", "ما هو البث المباشر وكيف يعمل؟"] if is_arabic else ["How to connect WooCommerce?", "Where to find Bank SMS Reference ID?", "What is Live Stream?"],
            "provider": "local",
            "sources": [],
            "status": "success",
        }

    provider = settings_dict.get("copilot_provider", "local").lower()
    api_key = settings_dict.get("copilot_api_key", "").strip()
    model = settings_dict.get("copilot_model", "gemini-1.5-flash").strip()

    # Gather system context
    portal_name = settings_dict.get("portal_name", "Motaaked")
    instapay_handle = settings_dict.get("instapay_handle", "haitham@instapay")
    match_window = settings_dict.get("match_window_minutes", 30)

    # Forwarder status
    fwd_info = "Standby"
    try:
        fwd_status = get_forwarder_status_service(db)
        if isinstance(fwd_status, dict):
            fwd_info = fwd_status.get("status", "STANDBY")
    except Exception:
        pass

    guide_faqs = get_developer_guide_faqs()

    # Attempt External LLM if configured and key is available
    if provider in ["gemini", "openai"] and api_key:
        try:
            if provider == "gemini":
                import urllib.request
                import json
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                guide_context = ""
                if guide_faqs:
                    guide_context = "\nKey Guide Q&A Reference Facts:\n" + "\n".join(
                        [f"- {it['q_en']} ({it['q_ar']}): {it['answer_en'][:130]}..." for it in guide_faqs[:8]]
                    )
                system_instruction = (
                    f"You are the official AI Assistant for {portal_name} (متأكد), an automated InstaPay payment matching & verification platform in Egypt. "
                    f"Key facts: Instapay handle is {instapay_handle}. Match window is {match_window} minutes. Forwarder status is {fwd_info}. "
                    "Verification principle: Transactions are verified EXCLUSIVELY via the Bank SMS Reference ID received on the merchant forwarder phone, NEVER from customer app screenshots. "
                    "Motaaked provides integrations for WooCommerce, Shopify, Laravel, Node.js, React, LearnDash, and a 2-line drop-in checkout modal. "
                    f"{guide_context} "
                    f"Answer concisely in {'Arabic' if is_arabic else 'English'}."
                )
                req_data = {
                    "contents": [
                        {"role": "user", "parts": [{"text": f"System Context: {system_instruction}\n\nUser Question: {query}"}]}
                    ],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800}
                }
                req = urllib.request.Request(
                    gemini_url,
                    data=json.dumps(req_data).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    res_body = json.loads(resp.read().decode("utf-8"))
                    generated_text = res_body["candidates"][0]["content"]["parts"][0]["text"]
                    return {
                        "reply": generated_text,
                        "suggestions": [
                            "كيف أربط ووكومرس؟" if is_arabic else "How to connect WooCommerce?",
                            "أين أجد رقم المرجع البنكي؟" if is_arabic else "Where to find Bank SMS Reference ID?",
                            "فحص حالة هاتف التحويل" if is_arabic else "Check Forwarder Phone Status",
                        ],
                        "provider": "gemini",
                        "sources": ["DEVELOPER_INTEGRATION_GUIDE.md", "System Knowledge Base", "Motaaked Live Telemetry"],
                        "status": "success",
                    }
        except Exception as e:
            logger.warning(f"External AI Provider {provider} failed or timed out: {e}. Falling back to local grounded engine.")

    # Local Grounded Engine (Developer Guide Grounding + Semantic rule matching + FAQs)
    query_lower = query.lower()

    # 1. Platform Pricing, Packages & Search Credits
    if re.search(r'(?:^|[\s\.\,\،\؟\?])(رسوم|عمولة|تكلفة|اسعار|أسعار|باقة|باقات|نقاط|شحن|رصيد|fee|fees|cost|credits|pricing|package|packages|recharge|topup)(?:$|[\s\.\,\،\؟\?])', query_lower):
        if is_arabic:
            reply = (
                "💰 **رسوم وباقات ونقاط منصة متأكد:**\n\n"
                "- **نظام نقاط البحث (Search Credits):** تعمل المنصة بنظام النقاط الرصيدية لكل عملية تحقق وبحث مرجعي ناجحة.\n"
                "- **باقات الشحن:** يمكنك شحن رصيد حسابك وشراء باقات إضافية بسهولة عبر لوحة التحكم من تبويب **الباقات (Packages)**.\n"
                "- **الاستضافة الذاتية:** كود المنصة متاح للمتاجر والشركات للاستضافة الذاتية وفق رخصة BSL 1.1."
            )
            suggestions = [
                "ما هي آلية احتساب الرسوم ونقاط البحث؟",
                "كيف يمكنني شحن رصيد الحساب؟",
                "ما هو البث المباشر وكيف يعمل؟"
            ]
        else:
            reply = (
                "💰 **Motaaked Platform Pricing & Search Credits:**\n\n"
                "- **Search Credits System:** The platform operates on a per-query search credits model for automated bank SMS verification and reference matching.\n"
                "- **Recharge Packages:** You can top up your account balance and purchase additional credit packages anytime directly from the **Packages** tab in your dashboard.\n"
                "- **Self-Hosting:** The platform code is available for merchants and enterprises to self-host under the BSL 1.1 license."
            )
            suggestions = [
                "What is the search credits and charging mechanism?",
                "How do I recharge my account balance?",
                "What is Live Stream and how does it work?"
            ]
        return {
            "reply": reply,
            "suggestions": suggestions,
            "provider": "local",
            "sources": ["DEVELOPER_INTEGRATION_GUIDE.md", "System Packages & Wallet Engine"],
            "status": "success",
        }

    # Clarification on InstaPay Network Transfer Limits (Disclaimed & Out of Scope)
    if re.search(r'(?:^|[\s\.\,\،\؟\?])(حد|حدود|الحد|الحدود|limit|limits)(?:$|[\s\.\,\،\؟\?])', query_lower):
        if is_arabic:
            reply = (
                "ℹ️ **توضيح بخصوص حدود المعاملات البنكية:**\n\n"
                "منصة **متأكد** هي نظام برمجي تقني مخصص للتحقق الفوري ومطابقة إشعارات ورسائل الإيداع البنكية عبر رقم المرجع البنكي، وليست جهة مصرفية.\n\n"
                "للاطلاع على حدود وقواعد المعاملات المصرفية الخاصة بشبكة إنستاباي، يُرجى مراجعة البنك التابع له حسابك أو الموقع الرسمي لشبكة المدفوعات اللحظية (IPN)."
            )
            suggestions = [
                "ما هي آلية احتساب الرسوم ونقاط البحث؟",
                "ما هو البث المباشر وكيف يعمل؟",
                "كيف أربط ووكومرس؟"
            ]
        else:
            reply = (
                "ℹ️ **InstaPay Banking Limits Clarification:**\n\n"
                "**Motaaked** is a technical verification platform that automatically matches incoming Bank SMS alerts using the Bank Reference ID. It is not a financial intermediary or bank.\n\n"
                "For official banking transaction limits and rules governing the InstaPay network, please consult your bank directly or visit the official InstaPay / IPN website."
            )
            suggestions = [
                "What is the search credits and charging mechanism?",
                "What is Live Stream and how does it work?",
                "How to connect WooCommerce?"
            ]
        return {
            "reply": reply,
            "suggestions": suggestions,
            "provider": "local",
            "sources": ["Motaaked Platform Architecture"],
            "status": "success",
        }

    # 2. Matching Window
    if any(k in query_lower for k in [
        "نافذة", "window", "مهلة"
    ]):
        if is_arabic:
            reply = (
                f"⏱️ **نافذة المطابقة اللحظية والحماية من التكرار:**\n\n"
                f"- **مدة نافذة المطابقة الافتراضية:** `{match_window}` دقيقة من لحظة وصول رسالة البنك.\n"
                "- **الحماية من إعادة الاستخدام (Double-Spend Protection):** بمجرد مطابقة إشعار البنك مع طلب دفع أو بحث مرجعي، يتم قفل المعاملة ذرياً (Atomic Lock) وتسجيلها كمعاملة مستهلكة، مما يمنع نهائياً إعادة استخدام نفس التحويل لطلب آخر."
            )
            suggestions = [
                "ماذا يحدث إذا تأخرت رسالة البنك؟",
                "أين أجد رقم المرجع البنكي؟",
                "كيف أربط ووكومرس؟"
            ]
        else:
            reply = (
                f"⏱️ **Matching Window & Double-Spend Immunity:**\n\n"
                f"- **Active Matching Window:** `{match_window}` minutes from incoming bank notification timestamp.\n"
                "- **Atomic Double-Spend Lock:** Once a bank credit is matched to an order or searched reference, it is locked immediately to prevent replay attacks across any store or terminal."
            )
            suggestions = [
                "What if the bank SMS is delayed?",
                "Where to find Bank SMS Reference ID?",
                "How to connect WooCommerce?"
            ]
        return {
            "reply": reply,
            "suggestions": suggestions,
            "provider": "local",
            "sources": ["Atomic Matching Engine", "System Settings"],
            "status": "success",
        }

    # 3. Developer Integration Guide Comprehensive Q&A Grounding
    if guide_faqs:
        q_tokens = _tokenize_copilot_text(query)
        scored_faqs = []

        for it in guide_faqs:
            score = 0
            for t in q_tokens:
                if t in it["title_tokens"] or (len(t) >= 4 and any(tok.startswith(t[:4]) for tok in it["title_tokens"] if len(tok) >= 4)):
                    score += 5
                elif t in it["body_tokens"] or (len(t) >= 4 and any(tok.startswith(t[:4]) for tok in it["body_tokens"] if len(tok) >= 4)):
                    score += 1
            scored_faqs.append((score, it))

        scored_faqs.sort(key=lambda x: x[0], reverse=True)
        best_guide_score, best_guide_item = scored_faqs[0]

        if best_guide_item and best_guide_score >= 5:
            guide_ans = best_guide_item["answer_ar"] if is_arabic else best_guide_item["answer_en"]
            title_disp = best_guide_item["q_ar"] if is_arabic else best_guide_item["q_en"]

            # Recommend other questions ranked by relevance to query keywords
            other_recs = [it for s, it in scored_faqs if it["id"] != best_guide_item["id"] and s > 0][:3]
            if len(other_recs) < 3:
                seen_ids = {best_guide_item["id"]} | {it["id"] for it in other_recs}
                for _, it in scored_faqs:
                    if it["id"] not in seen_ids:
                        other_recs.append(it)
                        seen_ids.add(it["id"])
                        if len(other_recs) >= 3:
                            break

            suggested_titles = [(it["q_ar"] if is_arabic else it["q_en"]) for it in other_recs]
            return {
                "reply": guide_ans,
                "suggestions": suggested_titles,
                "provider": "local",
                "sources": ["DEVELOPER_INTEGRATION_GUIDE.md", title_disp],
                "status": "success",
            }
        elif best_guide_item and best_guide_score >= 2:
            guide_ans = best_guide_item["answer_ar"] if is_arabic else best_guide_item["answer_en"]
            title_disp = best_guide_item["q_ar"] if is_arabic else best_guide_item["q_en"]

            other_recs = [it for s, it in scored_faqs if it["id"] != best_guide_item["id"] and s > 0][:3]
            if len(other_recs) < 3:
                seen_ids = {best_guide_item["id"]} | {it["id"] for it in other_recs}
                for _, it in scored_faqs:
                    if it["id"] not in seen_ids:
                        other_recs.append(it)
                        seen_ids.add(it["id"])
                        if len(other_recs) >= 3:
                            break

            suggested_titles = [(it["q_ar"] if is_arabic else it["q_en"]) for it in other_recs]
            if is_arabic:
                reply = (
                    f"بناءً على كلمات استفسارك، إليك الإجابة الأكثر صلة بموضوع **\"{title_disp}\"**:\n\n"
                    f"{guide_ans}"
                )
            else:
                reply = (
                    f"Based on your query keywords, here is the most relevant answer regarding **\"{title_disp}\"**:\n\n"
                    f"{guide_ans}"
                )
            return {
                "reply": reply,
                "suggestions": suggested_titles,
                "provider": "local",
                "sources": ["DEVELOPER_INTEGRATION_GUIDE.md", title_disp],
                "status": "success",
            }

    # 1. E-Commerce & Framework Integrations
    if any(k in query_lower for k in [
        "woocommerce", "ووكومرس", "shopify", "شوبيفاي", "laravel", "لارافيل", "wordpress", 
        "ووردبريس", "react", "رياكت", "node", "نود", "moodle", "مودل", "learndash", 
        "ليرنداش", "ربط", "متجر", "ecommerce", "plugin", "sdk", "cart", "سلة", "drop-in", "modal"
    ]):
        if is_arabic:
            reply = (
                f"تدعم منصة **{portal_name}** حزمة تكامل موحدة وشاملة لمنصات التجارة الإلكترونية عبر طريقتين رئيسيتين:\n\n"
                "1. **نافذة الدفع المدمجة (Drop-In Modal - سطرين كود فقط):**\n"
                "   يمكنك إضافة كود الـ JavaScript إلى أي موقع (PHP, HTML, Python, إلخ):\n"
                "   ```html\n"
                '   <script src="/static/js/motaaked-checkout.js"></script>\n'
                "   <script>Motaaked.checkout({ orderId: 'ORD-101', amount: 250.00 });</script>\n"
                "   ```\n\n"
                "2. **الإضافات والـ SDKs الجاهزة:**\n"
                "   - **WooCommerce**: إضافة ووردبريس كاملة تتيح الدفع المباشر والتحقق الآلي وتغيير حالة الطلب فوراً.\n"
                "   - **Shopify**: دمج عبر Draft Orders API وسيرفر تحقق وسيط.\n"
                "   - **Laravel**: حزمة جاهزة مع Facade و Middleware وأحداث `PaymentVerified`.\n"
                "   - **Node.js / Express**: حزمة npm رسمية مع Middleware للتحقق الفوري.\n"
                "   - **React / Next.js**: مكون `<InstaPayModal />` مع Hook `useInstaPay()`.\n"
                "   - **Moodle & LearnDash**: لتأكيد تسجيل الطلاب في الكورسات تلقائياً بمجرد إتمام التحويل.\n\n"
                "للاطلاع على دليل المطورين الشامل والأمثلة، راجع ملف `DEVELOPER_INTEGRATION_GUIDE.md` أو صفحة الدفع التجريبية `/checkout/embed`."
            )
            suggestions = [
                "أين أجد مفتاح API للمتجر؟",
                "كيف يعمل إشعار Webhook عند نجاح الدفع؟",
                "ما هو الفرق بين السكرين شوت ورقم المرجع؟"
            ]
        else:
            reply = (
                f"**{portal_name}** supports complete enterprise e-commerce integrations via two primary pathways:\n\n"
                "1. **Universal Drop-In Modal (`motaaked-checkout.js`)**:\n"
                "   Drop into ANY custom cart or HTML/PHP site with just 2 lines of code:\n"
                "   ```html\n"
                '   <script src="/static/js/motaaked-checkout.js"></script>\n'
                "   <script>Motaaked.checkout({ orderId: 'ORD-101', amount: 250.00 });</script>\n"
                "   ```\n\n"
                "2. **Ready-Made Framework Plugins & SDKs:**\n"
                "   - **WooCommerce**: Native WordPress gateway plugin that auto-settles orders.\n"
                "   - **Shopify**: Draft Orders API with proxy verification webhook.\n"
                "   - **Laravel**: Official composer package with Facade and Events.\n"
                "   - **Node.js / Express**: npm client with express middleware.\n"
                "   - **React / Next.js**: `@instapay/react` hook and accessible modal.\n"
                "   - **Moodle & LearnDash LMS**: Instant automated student course enrolment.\n\n"
                "For detailed code examples, visit the `/checkout/embed` interactive preview or read `DEVELOPER_INTEGRATION_GUIDE.md`."
            )
            suggestions = [
                "How do I generate a Merchant API Key?",
                "How does the Webhook notification work?",
                "Why Bank SMS Reference instead of Screenshots?"
            ]
        return {
            "reply": reply,
            "suggestions": suggestions,
            "provider": "local",
            "sources": ["DEVELOPER_INTEGRATION_GUIDE.md", "README.md"],
            "status": "success",
        }

    # 2. Bank SMS Reference ID vs Screenshot
    if any(k in query_lower for k in [
        "رقم المرجع", "reference", "سكرين", "screenshot", "ايصال", "صورة", "وصل", "بانك", "sms", "كود"
    ]):
        if is_arabic:
            reply = (
                "⚠️ **المبدأ الأساسي والحاسم لمنصة متأكد:**\n\n"
                "التحقق من صحة التحويل يتم **حصرياً عبر رقم المرجع البنكي (Bank SMS Reference ID)** الوارد في الرسالة النصية الرسمية للبنك التي تصل على هاتف التاجر، **وليس من لقطة شاشة (Screenshot) لتطبيق إنستا باي لدى العميل**.\n\n"
                "**لماذا؟**\n"
                "1. **الحماية التامة من التزوير:** لقطات الشاشة يمكن تزييفها بسهولة تامة عبر تطبيقات ومواقع توليد الصور المزيفة.\n"
                "2. **التطابق المالي الحقيقي:** رسالة البنك تؤكد دخول الأموال فعلياً في حساب التاجر البنكي اللحظي.\n"
                "3. **أين يجد العميل رقم المرجع؟** يصله في الرسالة النصية القصيرة (SMS) من بنكه فور التحويل، أو في إشعار المعاملة البنكية."
            )
            suggestions = [
                "أين أجد رقم المرجع البنكي في رسالة البنك؟",
                "كيف يعمل هاتف تحويل الرسائل؟",
                "ما هي البنوك المصرية المدعومة؟"
            ]
        else:
            reply = (
                "⚠️ **CRITICAL VERIFICATION PRINCIPLE OF MOTAAKED:**\n\n"
                "Verification is performed **exclusively via the Bank SMS Reference ID** extracted from official bank SMS notifications delivered to the merchant's forwarder phone.\n\n"
                "**Why NOT customer app screenshots?**\n"
                "1. **Fraud Prevention:** Mobile app screenshots can be easily fabricated or manipulated using fake receipt generators.\n"
                "2. **Settlement Guarantee:** The official bank SMS guarantees that the funds have genuinely settled into the merchant's bank balance.\n"
                "3. **Where does the customer find it?** The customer receives it in the official SMS sent by their issuing bank immediately upon transfer execution."
            )
            suggestions = [
                "Where is the Bank SMS Reference located?",
                "How does the Android SMS Forwarder work?",
                "Which Egyptian banks are supported?"
            ]
        return {
            "reply": reply,
            "suggestions": suggestions,
            "provider": "local",
            "sources": ["Core Architecture Principles", "FAQ Knowledge Base"],
            "status": "success",
        }

    # 3. Android Forwarder Setup & Health Status
    if any(k in query_lower for k in [
        "تطبيق", "هاتف", "forwarder", "battery", "بطارية", "اندرويد", "android", "apk", "تثبيت", "حالة الهاتف", "phone"
    ]):
        if is_arabic:
            reply = (
                f"📱 **إعداد وحالة هاتف تحويل رسائل البنك (SMS Forwarder):**\n\n"
                f"- **حالة الاتصال الحالية:** `{fwd_info}`\n"
                "- **آلية العمل:** يقوم تطبيق أندرويد الخفيف بقراءة الرسائل النصية الرسمية الواردة من البنك فقط، وإرسالها مشفرة إلى خادم المنصة لمطابقتها فورياً.\n"
                "- **خطوات الإعداد السليم:**\n"
                "  1. تثبيت تطبيق SMS Forwarder على هاتف التاجر الحامل للشريحة البنكية.\n"
                "  2. استثناء التطبيق من موفر البطارية (Battery Optimization -> Unrestricted).\n"
                "  3. تفعيل إذن قراءة الرسائل وتعيين رابط الخادم (Webhook Endpoint).\n"
                "  4. إبقاء الهاتف متصلاً بالإنترنت (Wi-Fi أو 4G)."
            )
            suggestions = [
                "كيف أتحقق من استلام رسائل البنك؟",
                "ما هو الفرق بين السكرين شوت ورقم المرجع؟",
                "كيف أربط متجري الإلكتروني؟"
            ]
        else:
            reply = (
                f"📱 **Bank SMS Forwarder Setup & Telemetry:**\n\n"
                f"- **Current Forwarder Status:** `{fwd_info}`\n"
                "- **How it works:** A lightweight Android forwarder reads incoming SMS alerts from supported banks and securely dispatches them to Motaaked for instant regex parsing.\n"
                "- **Key Requirements for Zero-Downtime:**\n"
                "  1. Disable Battery Optimization (set app to 'Don't Optimize' / Unrestricted).\n"
                "  2. Grant SMS receive and network permissions.\n"
                "  3. Configure the webhook destination URL and merchant authorization key.\n"
                "  4. Keep the forwarder phone connected to steady Wi-Fi or 4G."
            )
            suggestions = [
                "Check forwarder health status",
                "Supported banks list",
                "How to integrate with WooCommerce?"
            ]
        return {
            "reply": reply,
            "suggestions": suggestions,
            "provider": "local",
            "sources": ["Forwarder Documentation", "System Telemetry"],
            "status": "success",
        }

    # 6. Check Active FAQs in DB for semantic overlap
    try:
        faq_items = get_faq_items(db, active_only=True)
        tokens = [t for t in re.split(r'[\s\?\!\.\,\،\؟]+', query_lower) if len(t) > 3]
        for f in faq_items:
            q_ar = f.question_ar.lower()
            q_en = f.question_en.lower()
            match_score = sum(1 for t in tokens if t in q_ar or t in q_en)
            if match_score >= 2 or (len(tokens) == 1 and match_score == 1):
                ans = f.answer_ar if is_arabic else f.answer_en
                return {
                    "reply": ans,
                    "suggestions": [
                        "كيف أربط ووكومرس؟" if is_arabic else "How to connect WooCommerce?",
                        "الفرق بين السكرين شوت ورقم المرجع" if is_arabic else "Bank SMS Ref vs Screenshot",
                        "فحص حالة هاتف التحويل" if is_arabic else "Check Forwarder Phone Status",
                    ],
                    "provider": "local",
                    "sources": [f.question_ar if is_arabic else f.question_en],
                    "status": "success",
                }
    except Exception:
        pass

    # 7. Smart Keyword-Based Recommendation Fallback & Friendly Greeting
    if guide_faqs:
        q_tokens = _tokenize_copilot_text(query)
        scored_faqs = []
        for it in guide_faqs:
            score = 0
            for t in q_tokens:
                if t in it["title_tokens"] or (len(t) >= 4 and any(tok.startswith(t[:4]) for tok in it["title_tokens"] if len(tok) >= 4)):
                    score += 5
                elif t in it["body_tokens"] or (len(t) >= 4 and any(tok.startswith(t[:4]) for tok in it["body_tokens"] if len(tok) >= 4)):
                    score += 1
            if score > 0:
                scored_faqs.append((score, it))

        if scored_faqs:
            scored_faqs.sort(key=lambda x: x[0], reverse=True)
            top_recs = scored_faqs[:3]
            suggested_titles = [(it["q_ar"] if is_arabic else it["q_en"]) for _, it in top_recs]

            if is_arabic:
                rec_lines = "\n".join([f"- 💡 **{it['q_ar']}**" for _, it in top_recs])
                reply = (
                    f"لم أتمكن من العثور على إجابة مباشرة بدقة 100% لسؤالك، ولكن بناءً على الكلمات المفتاحية في استفسارك، قد تفيدك الموضوعات التالية من دليل المطورين والأسئلة الشائعة:\n\n"
                    f"{rec_lines}\n\n"
                    f"👇 **انقر على أحد الاقتراحات أدناه لعرض الإجابة التفصيلية:**"
                )
            else:
                rec_lines = "\n".join([f"- 💡 **{it['q_en']}**" for _, it in top_recs])
                reply = (
                    f"I couldn't find an exact direct match for your question, but based on the keywords in your query, here are the most relevant topics from our Developer Guide & FAQs:\n\n"
                    f"{rec_lines}\n\n"
                    f"👇 **Click any of the suggested topics below to view the full answer:**"
                )

            return {
                "reply": reply,
                "suggestions": suggested_titles,
                "provider": "local",
                "sources": ["DEVELOPER_INTEGRATION_GUIDE.md", "Smart Recommendations"],
                "status": "success",
            }

    if is_arabic:
        reply = (
            f"مرحباً بك! أنا **المساعد الذكي لمنصة {portal_name}**.\n\n"
            "يمكنني إرشادك فورياً في الأمور التالية:\n"
            "- 🛒 **ربط المتاجر الإلكترونية** (WooCommerce, Shopify, Laravel, React, Node.js, Moodle, LearnDash).\n"
            "- 🔍 **التحقق من المدفوعات** عبر رقم المرجع البنكي في رسالة البنك النصية (Bank SMS Reference ID).\n"
            "- 📱 **إعداد تطبيق تحويل الرسائل (SMS Forwarder)** للهاتف واستكشاف الأخطاء.\n"
            "- 💳 **نظام شحن الرصيد** وباقات النقاط والاشتراكات.\n\n"
            "يرجى كتابة سؤالك أو النقر على أحد الاقتراحات السريعة أدناه."
        )
        suggestions = [
            "كيف أربط متجري عبر ووكومرس؟",
            "أين أجد رقم المرجع البنكي؟",
            "فحص حالة هاتف تحويل الرسائل",
            "ما هو البث المباشر وكيف يعمل؟",
        ]
    else:
        reply = (
            f"Welcome! I am the **AI Copilot for {portal_name}**.\n\n"
            "I can assist you with:\n"
            "- 🛒 **E-Commerce Integrations** (WooCommerce, Shopify, Laravel, React, Node.js, LMS plugins).\n"
            "- 🔍 **Payment Verification** using the official Bank SMS Reference ID.\n"
            "- 📱 **Android SMS Forwarder** setup, battery optimization, and live health.\n"
            "- 💳 **Credit Packages & Top-Up** policies and subscriptions.\n\n"
            "Please ask your question or choose one of the quick suggestions below."
        )
        suggestions = [
            "How do I integrate WooCommerce?",
            "Where is the Bank SMS Reference ID?",
            "Check SMS forwarder status",
            "What is Live Stream and how does it work?",
        ]

    return {
        "reply": reply,
        "suggestions": suggestions,
        "provider": "local",
        "sources": ["Motaaked Knowledge Base"],
        "status": "success",
    }
