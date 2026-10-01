from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any
import secrets as _secrets
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index
)
from sqlalchemy.orm import relationship
from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.database import Base


def _random_cashier_pin() -> str:
    """Generate a 6-character cashier PIN with 4 digits and 2 uppercase letters (e.g. A123C4, 2D5A72)."""
    digits = [str(_secrets.randbelow(10)) for _ in range(4)]
    letters = [_secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(2)]
    chars = digits + letters
    shuffled = chars[:]
    for i in range(len(shuffled) - 1, 0, -1):
        j = _secrets.randbelow(i + 1)
        shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
    return "".join(shuffled)


def utc_now() -> datetime:
    """Return timezone-naive UTC timestamp."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def current_utc_month_str() -> str:
    """Return current UTC month in YYYY-MM format."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


# =========================================================================
# SQLAlchemy Database Models
# =========================================================================

class ApiKey(Base):
    """Stores developer / merchant API keys."""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    key_hash = Column(String(64), index=True, nullable=True)
    key_prefix = Column(String(16), nullable=True)
    name = Column(String(100), nullable=False)  # e.g. "Ahmed LMS", "Haitham Phone Forwarder"
    role = Column(String(20), nullable=False, default="user")  # "user", "forwarder", "admin"
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    last_used_at = Column(DateTime, nullable=True)


class User(Base):
    """Stores platform users identified by a unique passcode."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), nullable=True, index=True)
    phone = Column(String(30), nullable=True)
    passcode = Column(String(255), unique=True, nullable=False, index=True)
    passcode_hash = Column(String(255), nullable=True)
    account_ending = Column(String(30), nullable=True, index=True)
    role = Column(String(20), nullable=False, default="user")
    subscription_expires_at = Column(DateTime, nullable=False, index=True)
    credits_balance = Column(Integer, nullable=False, default=100)

    # 3-Bucket Waterfall Credit Wallet System
    free_credits = Column(Integer, nullable=False, default=100)
    free_credits_granted_month = Column(String(7), nullable=False, default=current_utc_month_str)
    free_credits_cycle_start = Column(DateTime, nullable=True, default=utc_now)
    pass_credits = Column(Integer, nullable=False, default=0)
    pass_credits_expires_at = Column(DateTime, nullable=True)
    lifetime_credits = Column(Integer, nullable=False, default=0)

    # Legal & Terms Acceptance (Egyptian Law Compliance)
    terms_accepted = Column(Boolean, nullable=False, default=True)
    terms_accepted_at = Column(DateTime, nullable=True, default=utc_now)

    # Live Stream POS Terminal Add-on Validity & Grace Period
    livestream_expires_at = Column(DateTime, nullable=True)
    livestream_grace_until = Column(DateTime, nullable=True)

    # Forwarder Connection Telemetry
    forwarder_last_seen_at = Column(DateTime, nullable=True)
    forwarder_battery = Column(Integer, nullable=True)
    forwarder_network = Column(String(50), nullable=True)
    forwarder_device = Column(String(100), nullable=True)
    forwarder_uptime = Column(String(50), nullable=True)
    forwarder_status = Column(String(20), nullable=True, default="STANDBY")
    # Cashier & Staff Shift Security PIN — auto-generated random 6-digit on user creation
    cashier_pin = Column(String(255), nullable=True, default=_random_cashier_pin)

    approval_status = Column(String(20), nullable=False, default="APPROVED")  # "APPROVED", "PENDING", "REJECTED"
    ecommerce_enabled = Column(Boolean, nullable=False, default=True, index=True)

    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    last_active_at = Column(DateTime, nullable=True)

    # Relationships
    credit_transactions = relationship("CreditTransaction", back_populates="user", cascade="all, delete-orphan")
    watched_references = relationship("WatchedReference", back_populates="user", cascade="all, delete-orphan")
    incoming_credits = relationship("IncomingCredit", back_populates="user", cascade="all, delete-orphan")
    forwarder_health_logs = relationship("ForwarderHealthLog", back_populates="user", cascade="all, delete-orphan")


class Passcode(Base):
    """Stores pre-generated / purchasable passcodes conferring subscription validity and credits."""
    __tablename__ = "passcodes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    duration_days = Column(Integer, nullable=False, default=30)
    credits_allocated = Column(Integer, nullable=False, default=100)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_redeemed = Column(Boolean, nullable=False, default=False, index=True)
    redeemed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)  # Validity to redeem code
    created_at = Column(DateTime, nullable=False, default=utc_now)


class CreditTransaction(Base):
    """Audit log of user credit deductions and top-ups."""
    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Integer, nullable=False)  # negative for deductions, positive for credits
    operation_type = Column(String(50), nullable=False)  # "SEARCH_LOOKUP", "CSV_EXPORT", "MONTHLY_RENEWAL", "TOPUP"
    reference_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)

    user = relationship("User", back_populates="credit_transactions")


class WatchedReference(Base):
    """Stores references actively watched/polled by users while pending bank SMS arrival."""
    __tablename__ = "watched_references"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    reference_id = Column(String(100), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)  # "PENDING", "MATCHED", "EXPIRED", "DISMISSED"
    matched_credit_id = Column(Integer, ForeignKey("incoming_credits.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    matched_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="watched_references")
    matched_credit = relationship("IncomingCredit")

    __table_args__ = (
        Index("ix_watched_session_status", "session_id", "status"),
    )


class IncomingCredit(Base):
    """Stores incoming InstaPay / IPN transfer credits parsed from SMS."""
    __tablename__ = "incoming_credits"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    account_ending = Column(String(20), nullable=True, index=True)
    amount = Column(Float, nullable=False, index=True)
    currency = Column(String(10), nullable=False, default="EGP")
    sender_name = Column(String(255), nullable=True)
    reference_id = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="UNCLAIMED", index=True)  # 'UNCLAIMED', 'CLAIMED'
    is_matched = Column(Boolean, nullable=False, default=False, index=True)
    matched_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    raw_message = Column(Text, nullable=False)
    matched_order_id = Column(String(100), nullable=True, index=True)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    read_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="incoming_credits")
    matched_order = relationship("PendingOrder", back_populates="matched_credit", uselist=False)

    __table_args__ = (
        Index("ix_incoming_credits_amount_status_received", "amount", "status", "received_at"),
    )


class PendingOrder(Base):
    """Stores pending orders waiting for InstaPay verification."""
    __tablename__ = "pending_orders"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    order_id = Column(String(100), unique=True, nullable=False, index=True)
    amount = Column(Float, nullable=False, index=True)
    reference_id = Column(String(100), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)  # 'PENDING', 'MATCHED', 'EXPIRED'
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    matched_at = Column(DateTime, nullable=True)
    matched_credit_id = Column(Integer, ForeignKey("incoming_credits.id"), nullable=True)

    # Relationship to credit & user
    user = relationship("User")
    matched_credit = relationship("IncomingCredit", back_populates="matched_order")


class CheckoutSession(Base):
    """Tracks short-lived (15 min) popup modal checkout sessions."""
    __tablename__ = "checkout_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_token = Column(String(64), unique=True, nullable=False, index=True)
    merchant_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order_id = Column(String(100), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="EGP")
    description = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)  # PENDING, MATCHED, EXPIRED, CANCELLED
    reference_id = Column(String(100), nullable=True)
    return_url = Column(String(500), nullable=True)
    cancel_url = Column(String(500), nullable=True)
    webhook_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    matched_at = Column(DateTime, nullable=True)

    merchant = relationship("User")


class SystemSetting(Base):
    """Stores key-value system configuration managed by Super Admin."""
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class Package(Base):
    """Stores dynamic subscription & top-up packages with before/after discount pricing."""
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    plan_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    badge = Column(String(50), nullable=True)
    price = Column(Float, nullable=False)
    original_price = Column(Float, nullable=True)
    discount_label = Column(String(50), nullable=True)
    duration_days = Column(Integer, nullable=False, default=30)
    credits = Column(Integer, nullable=False, default=100)
    features = Column(Text, nullable=False, default="[]")  # JSON string of list
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    sort_order = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class BankPattern(Base):
    """Stores configurable regex patterns for parsing bank SMS templates."""
    __tablename__ = "bank_patterns"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    bank_name = Column(String(100), nullable=False, index=True)
    sender_filter = Column(String(100), nullable=True)
    pattern = Column(Text, nullable=False)
    amount_group = Column(String(50), nullable=False, default="amount")
    ref_group = Column(String(50), nullable=False, default="ref")
    account_group = Column(String(50), nullable=True, default="account")
    sender_group = Column(String(50), nullable=True, default="sender")
    priority = Column(Integer, nullable=False, default=10, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    example_sms = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class ForwarderHealthLog(Base):
    """Audit log of forwarder phone connection health, battery, and network incidents."""
    __tablename__ = "forwarder_health_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="ONLINE", index=True)  # "ONLINE", "STANDBY", "OFFLINE", "LOW_BATTERY"
    battery = Column(Integer, nullable=True)
    network = Column(String(50), nullable=True)
    ping_ms = Column(Integer, nullable=True)
    message = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)

    user = relationship("User", back_populates="forwarder_health_logs")


class SupportTicket(Base):
    """Stores merchant trouble tickets, dispute reports, and support requests."""
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ticket_code = Column(String(32), unique=True, nullable=False, index=True)
    merchant_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    merchant_name = Column(String(100), nullable=False)
    merchant_email = Column(String(255), nullable=False, index=True)
    merchant_phone = Column(String(50), nullable=True)
    category = Column(String(50), nullable=False, default="transaction_issue", index=True)
    subject = Column(String(255), nullable=False)
    reference_id = Column(String(100), nullable=True, index=True)
    message = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="OPEN", index=True)  # OPEN, IN_PROGRESS, RESOLVED, CLOSED
    priority = Column(String(20), nullable=False, default="NORMAL", index=True)  # LOW, NORMAL, HIGH, URGENT
    admin_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    merchant = relationship("User")


class FaqItem(Base):
    """Stores bilingual Knowledge Base / Q&A items."""
    __tablename__ = "faq_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    question_en = Column(String(255), nullable=False)
    question_ar = Column(String(255), nullable=False)
    answer_en = Column(Text, nullable=False)
    answer_ar = Column(Text, nullable=False)
    category = Column(String(50), nullable=False, default="general", index=True)
    sort_order = Column(Integer, nullable=False, default=1, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


# =========================================================================
# Pydantic Schemas - Live Watchlist
# =========================================================================

class WatchReferenceRequest(BaseModel):
    reference_id: str = Field(..., min_length=2, description="Reference ID to monitor live")
    session_id: Optional[str] = Field(None, description="Optional browser session ID")
    timeout_minutes: Optional[int] = Field(30, ge=1, le=120, description="Monitoring window in minutes")
    is_topup: Optional[bool] = Field(False, description="Set True for recharge / top-up order tracking to bypass credit deduction")



class WatchedReferenceItem(BaseModel):
    id: int
    reference_id: str
    status: str
    created_at: datetime
    expires_at: datetime
    matched_at: Optional[datetime] = None
    matched_credit: Optional["IncomingCreditRead"] = None
    seconds_remaining: int
    credits_remaining: Optional[int] = None
    already_matched: bool = False

    model_config = ConfigDict(from_attributes=True)


class WatchlistBatchPollRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Browser session ID")
    reference_ids: Optional[List[str]] = Field(None, description="Specific reference IDs to check")
    watch_ids: Optional[List[int]] = Field(None, description="Specific watch task IDs to check")


class WatchlistBatchPollResponse(BaseModel):
    items: List[WatchedReferenceItem]
    total_pending: int
    total_matched: int


class WatchlistDismissRequest(BaseModel):
    watch_id: Optional[int] = Field(None, description="Watch task ID to dismiss")
    reference_id: Optional[str] = Field(None, description="Reference ID to dismiss")
    session_id: Optional[str] = Field(None, description="Browser session ID")


# =========================================================================
# Pydantic Schemas - Users, Passcodes & Credits
# =========================================================================

class UserLoginRequest(BaseModel):
    passcode: str = Field(..., min_length=4, description="User access passcode")


class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Merchant or business full name")
    email: str = Field(..., min_length=5, max_length=120, description="Primary contact/recovery email address")
    phone: Optional[str] = Field(None, description="Contact phone number")
    account_ending: Optional[str] = Field(None, min_length=4, max_length=6, description="Bank account ending (e.g. 1001)")
    terms_accepted: bool = Field(True, description="Must be true to agree to Terms & Conditions and Legal Disclaimer")

    @field_validator("terms_accepted")
    @classmethod
    def must_accept_terms(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the Terms and Conditions and Legal Disclaimer to create an account.")
        return v


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120, description="Registered email address")


class SendForwarderSetupEmailRequest(BaseModel):
    email: Optional[str] = Field(None, min_length=5, max_length=120, description="Optional target email override")
    server_url: Optional[str] = Field(None, description="Optional custom server host/URL for webhook")


class UserProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[str] = Field(None, min_length=5, max_length=120)
    phone: Optional[str] = Field(None)
    account_ending: Optional[str] = Field(None, min_length=4, max_length=6)


class UserProfileResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    passcode: str
    role: Optional[str] = "user"
    account_ending: Optional[str] = None
    forwarder_api_key: Optional[str] = None
    credits_balance: int
    free_credits: int = 100
    free_credits_days_left: int = 30
    free_credits_reset_date: Optional[str] = None
    free_credits_granted_month: Optional[str] = None
    free_credits_cycle_end: Optional[datetime] = None
    pass_credits: int = 0
    pass_credits_expires_at: Optional[datetime] = None
    lifetime_credits: int = 0
    subscription_expires_at: datetime
    terms_accepted: bool = True
    is_active: bool
    is_subscription_valid: bool
    livestream_expires_at: Optional[datetime] = None
    livestream_grace_until: Optional[datetime] = None
    is_livestream_valid: bool = False
    is_livestream_grace: bool = False
    forwarder_last_seen_at: Optional[datetime] = None
    forwarder_battery: Optional[int] = None
    forwarder_network: Optional[str] = None
    forwarder_device: Optional[str] = None
    forwarder_uptime: Optional[str] = None
    forwarder_status: Optional[str] = "STANDBY"
    vault_unlock_cost: int = 0
    statement_export_cost: int = 10
    search_credit_cost: int = 1
    cashier_pin: Optional[str] = None
    is_owner_unlocked: bool = False
    approval_status: str = "APPROVED"
    ecommerce_enabled: bool = True

    model_config = ConfigDict(from_attributes=True)


class VerifyOwnerKeyRequest(BaseModel):
    owner_key: str = Field(..., min_length=4, description="Merchant Forwarder API Key or Master Super Admin Key")


class VerifyOwnerKeyResponse(BaseModel):
    success: bool
    user_profile: UserProfileResponse
    message: str


class UpdateCashierPinRequest(BaseModel):
    owner_key: str = Field(..., min_length=4, description="Merchant Forwarder API Key required to authorize PIN change")
    new_cashier_pin: str = Field(..., min_length=4, max_length=20, description="New 6-character Cashier PIN (4 digits & 2 letters, e.g. A123C4)")


class VerifyCashierPinRequest(BaseModel):
    cashier_pin: str = Field(..., min_length=2, max_length=64, description="Cashier PIN or Forwarder Key to unlock shift views")


class VerifyCashierPinResponse(BaseModel):
    success: bool
    message: str
    shift_token: Optional[str] = None


class PublicConfigResponse(BaseModel):
    portal_name: str = "Motaaked"
    portal_name_ar: Optional[str] = "متأكد | Motaaked"
    portal_title: str = "Instant Insta Transactions Verification Platform"
    portal_subtitle_ar: str = "منظومة إنستا غير الرسمية لتأكيد وصول رسائل المدفوعات في البنك"
    portal_subtitle_en: Optional[str] = "Unofficial Insta Platform for Automated Bank SMS Payment Verification"
    vault_unlock_cost: int = 0
    statement_export_cost: int = 10
    search_credit_cost: int = 1
    monthly_free_credits: int = 100
    default_trial_days: int = 180
    default_livestream_trial_days: int = 5
    require_merchant_approval: bool = False
    instapay_handle: str = "haitham@instapay"
    instapay_receiver_name: Optional[str] = None
    supported_banks: List[str] = Field(default_factory=list, description="De-duplicated active supported bank names")
    announcement_enabled: bool = True
    announcement_title_en: Optional[str] = "Phase 2: Support E-Commerce to Validate transactions from outside our portal"
    announcement_title_ar: Optional[str] = "المرحلة 2: دعم منصات التجارة الإلكترونية لتأكيد المدفوعات آلياً"
    announcement_desc_en: Optional[str] = "Universal 8-Platform Plugin Suite: WordPress, WooCommerce, LearnDash, Moodle, Shopify, React, Node.js, Laravel"
    announcement_desc_ar: Optional[str] = "حزمة تكامل موحدة لـ 8 منصات: ووردبريس، ووكومرس، شوبيفاي، لارفيل، رياكت، نود جي اس، مودل، ليرنداش"
    
    # Floating Support Hub & Channels
    support_widget_enabled: bool = True
    support_ticketing_enabled: bool = True
    support_faq_enabled: bool = True
    support_social_enabled: bool = True
    support_whatsapp_number: Optional[str] = "201000000000"
    support_whatsapp_enabled: bool = True
    support_telegram_handle: Optional[str] = ""
    support_telegram_enabled: bool = False
    support_facebook_url: Optional[str] = ""
    support_facebook_enabled: bool = False
    support_linkedin_url: Optional[str] = ""
    support_linkedin_enabled: bool = False
    support_youtube_url: Optional[str] = ""
    support_youtube_enabled: bool = False
    support_phone_number: Optional[str] = ""
    support_phone_enabled: bool = False
    support_email_address: Optional[str] = "haitham.refaat@gmail.com"
    support_email_enabled: bool = True
    copilot_widget_enabled: bool = True
    copilot_provider: str = "local"


class PasscodeGenerateRequest(BaseModel):
    user_name: str = Field(..., min_length=2, max_length=100, description="Name of the user/merchant or 'Voucher'")
    phone: Optional[str] = Field(None, description="Optional phone number")
    duration_days: Optional[int] = Field(None, ge=0, le=3650, description="Access duration in days (None for system default, 0 for credits-only)")
    credits: Optional[int] = Field(None, ge=0, description="Allocated search credits (None for system default monthly free credits)")
    custom_code: Optional[str] = Field(None, min_length=4, description="Optional custom passcode")
    account_ending: Optional[str] = Field(None, description="Optional bank account ending (e.g. 1001)")
    role: Optional[str] = Field("user", description="User role: 'user' or 'admin'")
    is_voucher: Optional[bool] = Field(False, description="Set True to generate an unredeemed voucher code for any user to claim")


class PasscodeResponse(BaseModel):
    id: int
    code: str
    duration_days: int
    credits_allocated: int
    is_redeemed: bool
    redeemed_at: Optional[datetime] = None
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PasscodeListResponse(BaseModel):
    total: int
    passcodes: List[PasscodeResponse]


class PasscodeRedeemRequest(BaseModel):
    passcode: str = Field(..., min_length=4, description="New passcode to redeem/extend subscription")


# =========================================================================
# Pydantic Schemas - Transaction Explorer & Single Search
# =========================================================================

class TransactionItem(BaseModel):
    id: int
    amount: float
    currency: str
    reference_id: str
    sender_name: Optional[str] = None
    account_ending: Optional[str] = None
    status: str
    is_matched: bool = False
    matched_at: Optional[datetime] = None
    received_at: datetime
    matched_order_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TransactionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    credits_remaining: Optional[int] = None
    items: List[TransactionItem]


class ReferenceSearchRequest(BaseModel):
    reference_id: str = Field(..., min_length=2, description="Reference ID to look up")


class ReferenceSearchResponse(BaseModel):
    found: bool
    credit: Optional[TransactionItem] = None
    credits_remaining: Optional[int] = None
    already_matched: bool = False
    message: str


class StatementSummaryResponse(BaseModel):
    total_count: int
    total_volume: float
    matched_count: int = 0
    claimed_count: int = 0
    matched_only_count: int = 0
    unclaimed_count: int = 0
    unmatched_count: int = 0
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    export_fee_credits: int = 10


class StatementExportPDFRequest(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    confirm: bool = False


class TransactionsUnlockRequest(BaseModel):
    forwarder_api_key: str = Field(..., min_length=4, description="Developer / Forwarder API Key or Master Key")


class TransactionsUnlockResponse(BaseModel):
    success: bool
    credits_remaining: int
    message: str


# =========================================================================
# Pydantic Schemas - Developer API Keys
# =========================================================================

class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Friendly name for the user/merchant")
    role: Optional[str] = Field("user", description="Role: 'user', 'forwarder', or 'admin'")
    custom_key: Optional[str] = Field(None, min_length=8, description="Optional custom key string (auto-generated if omitted)")
    user_id: Optional[int] = Field(None, description="Optional merchant User ID to bind this key to")


class ApiKeyResponse(BaseModel):
    id: int
    key: str
    key_hash: Optional[str] = None
    key_prefix: Optional[str] = None
    name: str
    role: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyListResponse(BaseModel):
    total: int
    keys: List[ApiKeyResponse]


class ApiKeyActionRequest(BaseModel):
    key: Optional[str] = Field(None, description="API Key string to modify")
    id: Optional[int] = Field(None, description="API Key ID to modify")


# =========================================================================
# Pydantic Schemas - Webhook & Orders
# =========================================================================

class IncomingCreditRead(BaseModel):
    id: int
    user_id: Optional[int] = None
    account_ending: Optional[str] = None
    amount: float
    currency: str
    sender_name: Optional[str] = None
    reference_id: str
    status: str
    is_matched: bool = False
    matched_at: Optional[datetime] = None
    received_at: datetime
    matched_order_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SMSWebhookPayload(BaseModel):
    raw_message: Optional[str] = Field(None, description="Raw SMS text received by forwarder")
    text: Optional[str] = Field(None, description="SMS text alias used by some forwarders (%text%)")
    msg: Optional[str] = Field(None, description="SMS text alias used by some forwarders (%msg%)")
    message: Optional[str] = Field(None, description="SMS text alias")
    body: Optional[str] = Field(None, description="SMS text alias")
    sender: Optional[str] = Field(None, description="SMS sender name/number")
    from_: Optional[str] = Field(None, alias="from", description="SMS sender alias (%from%)")
    timestamp: Optional[datetime] = Field(None, description="Optional SMS reception timestamp")

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    def get_raw_text(self) -> str:
        return (self.raw_message or self.text or self.msg or self.message or self.body or "").strip()

    def get_sender(self) -> Optional[str]:
        return self.sender or self.from_


class SMSWebhookResponse(BaseModel):
    success: bool
    message: str
    data: Optional[IncomingCreditRead] = None


class OrderCreateRequest(BaseModel):
    order_id: str = Field(..., min_length=1, description="Unique client order ID")
    amount: float = Field(..., gt=0, description="Order payment amount")
    reference_id: Optional[str] = Field(None, description="Optional expected InstaPay transfer reference ID")


class OrderResponse(BaseModel):
    order_id: str
    amount: float
    reference_id: Optional[str] = None
    status: str
    created_at: datetime
    matched_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OrderVerifyRequest(BaseModel):
    order_id: Optional[str] = Field(None, description="Client order ID to verify (auto-generated if omitted)")
    reference_id: Optional[str] = Field(None, description="Reference ID to match")
    amount: Optional[float] = Field(None, description="Optional expected order amount in EGP")


class OrderVerifyResponse(BaseModel):
    verified: bool
    status: str
    order_id: str
    amount: float
    reference_id: Optional[str] = None
    matched_at: Optional[datetime] = None
    matched_credit: Optional[IncomingCreditRead] = None
    message: str
    success: bool = True
    order_status: Optional[str] = None
    is_paid: Optional[bool] = None


# =========================================================================
# Pydantic Schemas - Self-Service Top-Up & Subscriptions (Cycle 4)
# =========================================================================

class TopUpInitiateRequest(BaseModel):
    plan_id: str = Field(..., description="Selected plan: 'plan_30d', 'plan_90d', or 'plan_200pts'")
    purchase_type: Optional[str] = Field("direct", description="Purchase type: 'direct' or 'gift'")
    recipient_email: Optional[str] = Field(None, description="Optional destination email for gift voucher code")
    passcode: Optional[str] = Field(None, description="Optional passcode if not passed via header")


class TopUpInitiateResponse(BaseModel):
    order_id: str
    amount: float
    currency: str = "EGP"
    plan_name: str
    purchase_type: str = "direct"
    recipient_email: Optional[str] = None
    instapay_handle: str
    instructions: str


class TopUpVerifyRequest(BaseModel):
    order_id: str = Field(..., min_length=1, description="Top-up order ID to verify")
    reference_id: Optional[str] = Field(None, description="InstaPay transfer reference ID")
    recipient_email: Optional[str] = Field(None, description="Optional destination email for gift voucher code")
    server_url: Optional[str] = Field(None, description="Optional base URL for email template links")


class TopUpVerifyResponse(BaseModel):
    success: bool
    message: str
    order_id: str
    amount: float
    purchase_type: str = "direct"
    status: Optional[str] = None
    voucher_code: Optional[str] = None
    voucher_expires_at: Optional[datetime] = None
    user_profile: Optional[UserProfileResponse] = None


# =========================================================================
# Pydantic Schemas - Admin Analytics & User Management (Cycle 4)
# =========================================================================

class AdminMetricsResponse(BaseModel):
    total_transactions: int
    total_volume_egp: float
    unclaimed_credits: int
    claimed_credits: int
    total_users: int
    total_passcodes: int
    active_watches: int


class AdminAdjustUserRequest(BaseModel):
    user_id: int
    add_credits: Optional[int] = Field(0, description="Credits to add or subtract from lifetime credits")
    add_days: Optional[int] = Field(0, description="Days to extend subscription")
    set_free_credits: Optional[int] = Field(None, ge=0, description="Set exact free monthly credits balance")
    set_pass_credits: Optional[int] = Field(None, ge=0, description="Set exact day pass credits balance")
    set_lifetime_credits: Optional[int] = Field(None, ge=0, description="Set exact lifetime rollover credits balance")
    set_subscription_days: Optional[int] = Field(None, ge=0, description="Set exact active subscription days from today")
    set_livestream_days: Optional[int] = Field(None, ge=0, description="Set exact active Live Stream POS days from today (0 = revoke)")
    add_livestream_days: Optional[int] = Field(0, description="Days to add/extend Live Stream POS access")
    set_role: Optional[str] = Field(None, description="Set user role: 'user' or 'admin'")


class AdminGrantLiveStreamRequest(BaseModel):
    days: int = Field(30, ge=1, le=3650, description="Number of free Live Stream days to grant to merchant")
    reason: Optional[str] = Field("ADMIN_COMPLIMENTARY", description="Reason or note for complimentary access")


class UserListItem(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    passcode: str
    role: Optional[str] = "user"
    account_ending: Optional[str] = None
    credits_balance: int
    free_credits: int = 100
    pass_credits: int = 0
    lifetime_credits: int = 0
    subscription_expires_at: datetime
    livestream_expires_at: Optional[datetime] = None
    livestream_grace_until: Optional[datetime] = None
    approval_status: str = "APPROVED"
    ecommerce_enabled: bool = True
    is_active: bool
    last_active_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserListResponse(BaseModel):
    total: int
    users: List[UserListItem]


class SystemSettingsRead(BaseModel):
    portal_name: str = "Motaaked"
    portal_name_ar: Optional[str] = "متأكد | Motaaked"
    portal_title: str = "Instant Insta Transactions Verification Platform"
    portal_subtitle_ar: str = "منظومة إنستا غير الرسمية لتأكيد وصول رسائل المدفوعات في البنك"
    portal_subtitle_en: Optional[str] = "Unofficial Insta Platform for Automated Bank SMS Payment Verification"
    instapay_handle: str
    instapay_phone: Optional[str] = None
    instapay_account_ending: Optional[str] = None
    instapay_receiver_name: Optional[str] = None
    match_window_minutes: int = 30
    default_trial_days: int = 180
    default_livestream_trial_days: int = 5
    require_merchant_approval: bool = False
    search_credit_cost: int = 1
    vault_unlock_cost: int = 10
    statement_export_cost: int = 10
    monthly_free_credits: int = 100
    forwarder_online_timeout_minutes: int = 7
    forwarder_offline_timeout_minutes: int = 15
    announcement_enabled: bool = True
    announcement_title_en: Optional[str] = "Phase 2: Support E-Commerce to Validate transactions from outside our portal"
    announcement_title_ar: Optional[str] = "المرحلة 2: دعم منصات التجارة الإلكترونية لتأكيد المدفوعات آلياً"
    announcement_desc_en: Optional[str] = "Universal 8-Platform Plugin Suite: WordPress, WooCommerce, LearnDash, Moodle, Shopify, React, Node.js, Laravel"
    announcement_desc_ar: Optional[str] = "حزمة تكامل موحدة لـ 8 منصات: ووردبريس، ووكومرس، شوبيفاي، لارفيل، رياكت، نود جي اس، مودل، ليرنداش"
    
    # Floating Support Hub & Channels
    support_widget_enabled: bool = True
    support_ticketing_enabled: bool = True
    support_faq_enabled: bool = True
    support_social_enabled: bool = True
    support_admin_email: str = "haitham.refaat@gmail.com"
    support_whatsapp_number: Optional[str] = "201000000000"
    support_whatsapp_enabled: bool = True
    support_telegram_handle: Optional[str] = ""
    support_telegram_enabled: bool = False
    support_facebook_url: Optional[str] = ""
    support_facebook_enabled: bool = False
    support_linkedin_url: Optional[str] = ""
    support_linkedin_enabled: bool = False
    support_youtube_url: Optional[str] = ""
    support_youtube_enabled: bool = False
    support_phone_number: Optional[str] = ""
    support_phone_enabled: bool = False
    support_email_address: Optional[str] = "support@motaaked.com"
    support_email_enabled: bool = True
    smtp_from: Optional[str] = ""
    smtp_host: Optional[str] = "smtp-relay.brevo.com"
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = ""
    smtp_password: Optional[str] = ""
    smtp_tls: Optional[bool] = True
    ecommerce_gateway_enabled: bool = True
    order_verification_credit_cost: int = 1
    allow_reference_less_order_matching: bool = True
    allowed_checkout_embed_origins: Optional[str] = "*"
    copilot_widget_enabled: bool = True
    copilot_provider: str = "local"
    copilot_api_key: Optional[str] = ""
    copilot_model: Optional[str] = "gemini-1.5-flash"


class SystemSettingsUpdate(BaseModel):
    admin_key: Optional[str] = Field(None, description="Super Admin Master Key required to confirm modifications")
    allow_reference_less_order_matching: Optional[bool] = Field(None, description="Allow matching external orders without reference_id by amount within window")
    allowed_checkout_embed_origins: Optional[str] = Field(None, max_length=1000, description="Allowed CORS/CSP origin list for iframe embedding")

    smtp_from: Optional[str] = Field(None, max_length=150, description="System outgoing sender email address (SMTP_FROM)")
    smtp_host: Optional[str] = Field(None, max_length=150, description="SMTP Server Host (e.g. smtp-relay.brevo.com)")
    smtp_port: Optional[int] = Field(None, ge=1, le=65535, description="SMTP Port (e.g. 587, 2525, 465)")
    smtp_user: Optional[str] = Field(None, max_length=150, description="SMTP Username")
    smtp_password: Optional[str] = Field(None, max_length=250, description="SMTP Password or Brevo SMTP Key")
    smtp_tls: Optional[bool] = Field(None, description="Use TLS/STARTTLS encryption")
    portal_name: Optional[str] = Field(None, min_length=2, max_length=100, description="Portal brand name (English)")
    portal_name_ar: Optional[str] = Field(None, min_length=2, max_length=100, description="Portal brand name (Arabic)")
    portal_title: Optional[str] = Field(None, min_length=2, max_length=200, description="Main hero headline")
    portal_subtitle_ar: Optional[str] = Field(None, min_length=2, max_length=300, description="Hero Arabic subtitle")
    portal_subtitle_en: Optional[str] = Field(None, min_length=2, max_length=300, description="Hero English subtitle")
    instapay_handle: Optional[str] = Field(None, description="InstaPay receiving handle (e.g. haitham@instapay)")
    instapay_phone: Optional[str] = Field(None, description="InstaPay receiving phone number")
    instapay_account_ending: Optional[str] = Field(None, description="Receiving bank account ending (e.g. 1001)")
    instapay_receiver_name: Optional[str] = Field(None, description="Receiver name (e.g. Haitham Refaat)")
    match_window_minutes: Optional[int] = Field(None, ge=5, le=1440, description="Matching timeout window in minutes")
    default_trial_days: Optional[int] = Field(None, ge=1, le=3650, description="Default free trial validity period in days for new merchants")
    default_livestream_trial_days: Optional[int] = Field(None, ge=0, le=365, description="Default free Live Stream POS trial days for new merchants (0 = Disabled)")
    require_merchant_approval: Optional[bool] = Field(None, description="Require Super Admin approval for new merchant registrations")
    search_credit_cost: Optional[int] = Field(None, ge=0, le=1000, description="Cost in credits per transaction search lookup (0 = Free)")
    vault_unlock_cost: Optional[int] = Field(None, ge=0, le=1000, description="Cost in credits to unlock historical transactions vault (0 = Free)")
    statement_export_cost: Optional[int] = Field(None, ge=0, le=1000, description="Cost in credits to export PDF statement (0 = Free)")
    monthly_free_credits: Optional[int] = Field(None, ge=0, le=10000, description="Monthly free credits granted to active merchants on 1st of each month")
    forwarder_online_timeout_minutes: Optional[int] = Field(None, ge=1, le=120, description="Minutes before forwarder phone moves from ONLINE to STANDBY")
    forwarder_offline_timeout_minutes: Optional[int] = Field(None, ge=2, le=360, description="Minutes before forwarder phone moves from STANDBY to OFFLINE")
    announcement_enabled: Optional[bool] = Field(None, description="Enable or disable the announcement/ads banner")
    announcement_title_en: Optional[str] = Field(None, max_length=200, description="Announcement title in English")
    announcement_title_ar: Optional[str] = Field(None, max_length=200, description="Announcement title in Arabic")
    announcement_desc_en: Optional[str] = Field(None, max_length=500, description="Announcement description in English")
    announcement_desc_ar: Optional[str] = Field(None, max_length=500, description="Announcement description in Arabic")
    
    # Floating Support Hub & Channels
    support_widget_enabled: Optional[bool] = Field(None, description="Enable or disable the floating support widget globally")
    support_ticketing_enabled: Optional[bool] = Field(None, description="Enable or disable the trouble ticketing feature")
    support_faq_enabled: Optional[bool] = Field(None, description="Enable or disable the Q&A / FAQ section")
    support_social_enabled: Optional[bool] = Field(None, description="Enable or disable social media & direct contact links")
    support_admin_email: Optional[str] = Field(None, description="Email address where new ticket alerts are dispatched")
    support_whatsapp_number: Optional[str] = Field(None, description="WhatsApp support phone number (international format e.g. 2010...)")
    support_whatsapp_enabled: Optional[bool] = Field(None, description="Show or hide WhatsApp chat action")
    support_telegram_handle: Optional[str] = Field(None, description="Telegram support username or channel link")
    support_telegram_enabled: Optional[bool] = Field(None, description="Show or hide Telegram action")
    support_facebook_url: Optional[str] = Field(None, description="Facebook page or Messenger URL")
    support_facebook_enabled: Optional[bool] = Field(None, description="Show or hide Facebook action")
    support_linkedin_url: Optional[str] = Field(None, description="LinkedIn company or profile URL")
    support_linkedin_enabled: Optional[bool] = Field(None, description="Show or hide LinkedIn action")
    support_youtube_url: Optional[str] = Field(None, description="YouTube tutorial or channel URL")
    support_youtube_enabled: Optional[bool] = Field(None, description="Show or hide YouTube action")
    support_phone_number: Optional[str] = Field(None, description="Direct hotline or support phone number")
    support_phone_enabled: Optional[bool] = Field(None, description="Show or hide Phone action")
    support_email_address: Optional[str] = Field(None, description="Public customer support email address")
    support_email_enabled: Optional[bool] = Field(None, description="Show or hide Email action")
    ecommerce_gateway_enabled: Optional[bool] = Field(None, description="Global Portal-level toggle for external E-Commerce integrations & plugins")
    order_verification_credit_cost: Optional[int] = Field(None, ge=0, le=100, description="Credit cost deducted per verified external order (default: 1)")
    copilot_widget_enabled: Optional[bool] = Field(None, description="Enable or disable the AI Copilot Assistant")
    copilot_provider: Optional[str] = Field(None, description="AI Copilot Provider: local, gemini, openai, ollama")
    copilot_api_key: Optional[str] = Field(None, description="API Key for AI Copilot provider")
    copilot_model: Optional[str] = Field(None, description="Model identifier for AI Copilot")


# =========================================================================
# Pydantic Schemas - E-Commerce Drop-In Checkout Sessions
# =========================================================================

class CreateCheckoutSessionRequest(BaseModel):
    order_id: str = Field(..., min_length=1, max_length=100, description="Unique merchant order number or invoice ID")
    amount: float = Field(..., gt=0, description="Total order amount to be paid via InstaPay")
    currency: Optional[str] = Field("EGP", max_length=10)
    description: Optional[str] = Field(None, max_length=255, description="Product title, course name, or cart summary")
    return_url: Optional[str] = Field(None, max_length=500, description="URL to redirect customer upon successful payment")
    cancel_url: Optional[str] = Field(None, max_length=500, description="URL to redirect customer if payment is cancelled")
    webhook_url: Optional[str] = Field(None, max_length=500, description="Merchant server webhook notification URL")

    @field_validator("return_url", "cancel_url", "webhook_url")
    @classmethod
    def validate_safe_urls(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        v_clean = v.strip()
        if not v_clean:
            return None
        low = v_clean.lower()
        if low.startswith("javascript:") or low.startswith("data:") or low.startswith("vbscript:"):
            raise ValueError("Dangerous URI schemes (javascript:, data:, vbscript:) are strictly forbidden.")
        if not (low.startswith("http://") or low.startswith("https://") or low.startswith("/")):
            raise ValueError("URL must start with http://, https://, or /")
        return v_clean


class CreateCheckoutSessionResponse(BaseModel):
    session_token: str
    order_id: str
    amount: float
    currency: str
    checkout_url: str
    expires_at: str
    merchant_name: str
    instapay_handle: str


class CheckoutSessionPublicRead(BaseModel):
    session_token: str
    order_id: str
    amount: float
    currency: str
    description: Optional[str] = None
    merchant_name: str
    instapay_handle: str
    status: str
    expires_at: str
    seconds_remaining: int


class VerifyCheckoutSessionRequest(BaseModel):
    session_token: str = Field(..., min_length=10, max_length=64)
    reference_id: str = Field(..., min_length=4, max_length=100)


class VerifyCheckoutSessionResponse(BaseModel):
    verified: bool
    status: str
    order_id: str
    amount: float
    reference_id: str
    matched_at: Optional[str] = None
    message: str
    return_url: Optional[str] = None


class AdminToggleEcommerceRequest(BaseModel):
    enabled: bool = Field(..., description="Enable or disable e-commerce integrations for merchant")


class TestSMTPRequest(BaseModel):
    admin_key: Optional[str] = Field(None, description="Super Admin Master Key")
    test_recipient: Optional[str] = Field(None, description="Optional email address to send a test message to")


# =========================================================================
# Pydantic Schemas - Dynamic Packages & Pricing
# =========================================================================

class PackageCreate(BaseModel):
    plan_id: str = Field(..., min_length=2, max_length=50, description="Unique plan code (e.g. plan_30d)")
    name: str = Field(..., min_length=2, max_length=100, description="Package title")
    badge: Optional[str] = Field(None, max_length=50, description="Card badge e.g. Starter, Best Value")
    price: float = Field(..., gt=0, description="Selling price in EGP")
    original_price: Optional[float] = Field(None, description="Pre-discount price for strike-through display")
    discount_label: Optional[str] = Field(None, description="Discount badge text e.g. -20% OFF")
    duration_days: int = Field(0, ge=0, description="Subscription duration days granted")
    credits: int = Field(0, ge=0, description="Search credits granted")
    features: List[str] = Field(default_factory=list, description="List of bullet point features")
    is_active: bool = Field(True, description="True = Visible on portal, False = Hidden")
    sort_order: int = Field(1, description="Display sorting order")


class PackageUpdate(BaseModel):
    name: Optional[str] = None
    badge: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    original_price: Optional[float] = None
    discount_label: Optional[str] = None
    duration_days: Optional[int] = Field(None, ge=0)
    credits: Optional[int] = Field(None, ge=0)
    features: Optional[List[str]] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class PackageResponse(BaseModel):
    id: int
    plan_id: str
    name: str
    badge: Optional[str] = None
    price: float
    original_price: Optional[float] = None
    discount_label: Optional[str] = None
    duration_days: int
    credits: int
    features: List[str]
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PackageListResponse(BaseModel):
    total: int
    packages: List[PackageResponse]


# =========================================================================
# Pydantic Schemas - Admin Purchases & Subscriptions Reporting
# =========================================================================

class AdminPurchaseReportItem(BaseModel):
    id: int
    order_id: str
    merchant_id: Optional[int] = None
    merchant_name: str
    merchant_email: Optional[str] = None
    plan_name: str
    purchase_type: str  # "direct" or "gift"
    amount: float
    currency: str = "EGP"
    reference_id: Optional[str] = None
    status: str  # "MATCHED", "PENDING", "EXPIRED"
    purchase_date: datetime
    expiry_date: Optional[datetime] = None
    voucher_code: Optional[str] = None
    voucher_redeemed: Optional[bool] = None
    voucher_redeemed_by: Optional[str] = None
    voucher_redeemed_at: Optional[datetime] = None


class AdminPurchaseReportResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_revenue_egp: float
    total_direct_purchases: int
    total_gift_vouchers: int
    items: List[AdminPurchaseReportItem]


# =========================================================================
# Pydantic Schemas - Camera OCR & SMS Text Parsing
# =========================================================================

class ExtractReferenceRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Raw SMS text, OCR transcribed text, or pasted message")


class ExtractReferenceResponse(BaseModel):
    success: bool
    reference_id: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "EGP"
    sender_name: Optional[str] = None
    account_ending: Optional[str] = None
    message: str


# =========================================================================
# Pydantic Schemas - Database-Driven Bank SMS Patterns
# =========================================================================

class BankPatternCreate(BaseModel):
    bank_name: str = Field(..., min_length=2, max_length=100, description="Bank Name e.g. CIB, NBE, Banque Misr")
    sender_filter: Optional[str] = Field(None, max_length=100, description="Optional SMS Sender Tag e.g. CIB, NBE, BM")
    pattern: str = Field(..., min_length=5, description="Regex pattern with capture groups")
    amount_group: str = Field("amount", max_length=50, description="Named group or index for amount")
    ref_group: str = Field("ref", max_length=50, description="Named group or index for reference ID")
    account_group: Optional[str] = Field("account", max_length=50, description="Named group or index for account ending")
    sender_group: Optional[str] = Field("sender", max_length=50, description="Named group or index for sender name")
    priority: int = Field(10, ge=1, le=1000, description="Execution priority (lower runs earlier)")
    is_active: bool = Field(True, description="Whether pattern is actively evaluated")
    example_sms: Optional[str] = Field(None, description="Sample SMS message string for documentation and testing")


class BankPatternUpdate(BaseModel):
    bank_name: Optional[str] = Field(None, min_length=2, max_length=100)
    sender_filter: Optional[str] = Field(None, max_length=100)
    pattern: Optional[str] = Field(None, min_length=5)
    amount_group: Optional[str] = Field(None, max_length=50)
    ref_group: Optional[str] = Field(None, max_length=50)
    account_group: Optional[str] = Field(None, max_length=50)
    sender_group: Optional[str] = Field(None, max_length=50)
    priority: Optional[int] = Field(None, ge=1, le=1000)
    is_active: Optional[bool] = None
    example_sms: Optional[str] = None


class BankPatternResponse(BaseModel):
    id: int
    bank_name: str
    sender_filter: Optional[str] = None
    pattern: str
    amount_group: str = "amount"
    ref_group: str = "ref"
    account_group: Optional[str] = "account"
    sender_group: Optional[str] = "sender"
    priority: int = 10
    is_active: bool = True
    example_sms: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BankPatternListResponse(BaseModel):
    total: int
    patterns: List[BankPatternResponse]


class BankPatternTestRequest(BaseModel):
    pattern: str = Field(..., min_length=5, description="Regex pattern with capture groups")
    sample_text: str = Field(..., min_length=5, description="Sample SMS text to test against the pattern")
    amount_group: str = Field("amount", description="Group name or 1-based index for amount")
    ref_group: str = Field("ref", description="Group name or 1-based index for reference ID")
    account_group: Optional[str] = Field("account", description="Group name or 1-based index for account ending")
    sender_group: Optional[str] = Field("sender", description="Group name or 1-based index for sender name")


class BankPatternTestResponse(BaseModel):
    matched: bool
    amount: Optional[float] = None
    reference_id: Optional[str] = None
    account_ending: Optional[str] = None
    sender_name: Optional[str] = None
    currency: Optional[str] = "EGP"
    error: Optional[str] = None
    raw_groups: Optional[dict] = None


class BankPatternAutoGenerateRequest(BaseModel):
    sample_text: str = Field(..., min_length=5, description="Raw bank SMS alert message to reverse-engineer into regex")


class BankPatternAutoGenerateResponse(BaseModel):
    success: bool
    generated_pattern: str = ""
    detected_bank: str = "Custom Bank Alert"
    detected_sender: Optional[str] = None
    amount_group: str = "amount"
    ref_group: str = "ref"
    account_group: Optional[str] = "account"
    sender_group: Optional[str] = "sender"
    preview: Optional[dict] = None
    error: Optional[str] = None


# =========================================================================
# Merchant Credit Movement & Audit Statement Schemas
# =========================================================================

class CreditMovementItem(BaseModel):
    id: int
    created_at: datetime
    operation_type: str
    operation_label: str
    reference_id: Optional[str] = None
    amount: int
    balance_before: int
    balance_after: int


class MerchantCreditAuditResponse(BaseModel):
    user_id: int
    user_name: str
    user_email: Optional[str] = None
    user_passcode: str
    current_balance: int
    free_credits: int
    pass_credits: int
    lifetime_credits: int
    subscription_expires_at: datetime
    total_movements: int
    total_added: int
    total_deducted: int
    page: int
    page_size: int
    items: List[CreditMovementItem]


# =========================================================================
# Pydantic Schemas - Live Stream POS Terminal & Forwarder Telemetry
# =========================================================================

class ForwarderHeartbeatRequest(BaseModel):
    battery: Optional[int] = Field(None, ge=0, le=100, description="Phone battery percentage")
    network: Optional[str] = Field(None, description="Network type e.g. WE 4G (Good), Wi-Fi")
    uptime: Optional[str] = Field(None, description="Forwarder uptime e.g. 14d 2h")
    device: Optional[str] = Field(None, description="Device model e.g. Samsung Galaxy A52")
    ping_ms: Optional[int] = Field(None, description="Ping latency in ms")


class ForwarderHeartbeatResponse(BaseModel):
    success: bool
    status: str
    recorded_at: datetime
    battery: Optional[int] = None
    network: Optional[str] = None


class ForwarderTelemetryRead(BaseModel):
    status: str = "STANDBY"  # "ONLINE", "STANDBY", "OFFLINE"
    last_seen_at: Optional[datetime] = None
    battery: Optional[int] = None
    network: Optional[str] = None
    uptime: Optional[str] = None
    ping_ms: Optional[int] = 25
    device: Optional[str] = None


class LiveStreamTransactionItem(BaseModel):
    id: int
    amount: float
    currency: str = "EGP"
    bank_name: Optional[str] = "InstaPay"
    account_ending: Optional[str] = None
    sender_name: Optional[str] = None
    reference_id: str
    status: str  # "VERIFIED" / "CLAIMED", "UNCLAIMED"
    is_matched: bool = False
    is_read: bool = False
    read_at: Optional[datetime] = None
    received_at: datetime
    is_highlighted: bool = False

    model_config = ConfigDict(from_attributes=True)


class LiveStreamFeedResponse(BaseModel):
    is_unlocked: bool
    in_grace_period: bool = False
    grace_days_remaining: int = 0
    expires_at: Optional[datetime] = None
    grace_until: Optional[datetime] = None
    telemetry: ForwarderTelemetryRead
    unread_count: int = 0
    total_count: int = 0
    items: List[LiveStreamTransactionItem]


class LiveStreamMarkReadRequest(BaseModel):
    credit_ids: Optional[List[int]] = Field(None, description="Specific transaction IDs to mark as read")
    mark_all: Optional[bool] = Field(False, description="Set True to mark all visible transactions as read")


class AdminForwarderHealthItem(BaseModel):
    user_id: int
    merchant_name: str
    email: Optional[str] = None
    account_ending: Optional[str] = None
    forwarder_status: str
    battery: Optional[int] = None
    network: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    uptime: Optional[str] = None
    livestream_expires_at: Optional[datetime] = None
    livestream_grace_until: Optional[datetime] = None
    is_livestream_active: bool = False


class AdminForwarderHealthResponse(BaseModel):
    total: int
    online_count: int
    standby_count: int
    offline_count: int
    items: List[AdminForwarderHealthItem]


# =========================================================================
# Pydantic Schemas - Support Hub & Trouble Ticketing
# =========================================================================

class SupportTicketCreate(BaseModel):
    merchant_name: str = Field(..., min_length=2, max_length=100, description="Full name of contact person / merchant")
    merchant_email: str = Field(..., min_length=5, max_length=255, description="Email address for notifications")
    merchant_phone: Optional[str] = Field(None, max_length=50, description="Optional contact phone or WhatsApp")
    category: str = Field("add_new_bank", description="Category: add_new_bank, forwarder_setup, credits_topup, plugin_integration, general_inquiry")
    subject: str = Field(..., min_length=3, max_length=255, description="Short summary of issue")
    reference_id: Optional[str] = Field(None, max_length=100, description="Optional InstaPay Reference ID related to dispute")
    message: str = Field(..., min_length=10, max_length=5000, description="Detailed description of the issue or question")


class SupportTicketResponse(BaseModel):
    id: int
    ticket_code: str
    merchant_id: Optional[int] = None
    merchant_name: str
    merchant_email: str
    merchant_phone: Optional[str] = None
    category: str
    subject: str
    reference_id: Optional[str] = None
    message: str
    status: str
    priority: str
    admin_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupportTicketAdminUpdate(BaseModel):
    status: Optional[str] = Field(None, description="New status: OPEN, IN_PROGRESS, RESOLVED, CLOSED")
    priority: Optional[str] = Field(None, description="New priority: LOW, NORMAL, HIGH, URGENT")
    admin_notes: Optional[str] = Field(None, max_length=5000, description="Internal notes or resolution summary")
    reply_message: Optional[str] = Field(None, max_length=5000, description="Optional email message to dispatch to the merchant")


class SupportTicketListResponse(BaseModel):
    total: int
    open_count: int
    resolved_count: int
    items: List[SupportTicketResponse]


class FaqItemCreate(BaseModel):
    question_en: str = Field(..., min_length=3, max_length=255)
    question_ar: str = Field(..., min_length=3, max_length=255)
    answer_en: str = Field(..., min_length=5)
    answer_ar: str = Field(..., min_length=5)
    category: str = Field("general", max_length=50)
    sort_order: int = Field(1, ge=0, le=1000)
    is_active: bool = Field(True)


class FaqItemUpdate(BaseModel):
    question_en: Optional[str] = Field(None, min_length=3, max_length=255)
    question_ar: Optional[str] = Field(None, min_length=3, max_length=255)
    answer_en: Optional[str] = Field(None, min_length=5)
    answer_ar: Optional[str] = Field(None, min_length=5)
    category: Optional[str] = Field(None, max_length=50)
    sort_order: Optional[int] = Field(None, ge=0, le=1000)
    is_active: Optional[bool] = Field(None)


class FaqItemResponse(BaseModel):
    id: int
    question_en: str
    question_ar: str
    answer_en: str
    answer_ar: str
    category: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FaqItemListResponse(BaseModel):
    total: int
    items: List[FaqItemResponse]


# =========================================================================
# Pydantic Schemas - AI Copilot Assistant
# =========================================================================

class CopilotChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="User query for the AI Copilot")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional page or session context")
    session_id: Optional[str] = Field(None, max_length=100, description="Optional user session ID")
    language: Optional[str] = Field("auto", description="Preferred response language: 'ar', 'en', 'auto'")


class CopilotChatResponse(BaseModel):
    reply: str
    suggestions: List[str] = Field(default_factory=list)
    provider: str = "local"
    sources: List[str] = Field(default_factory=list)
    status: str = "success"







