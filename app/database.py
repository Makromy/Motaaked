import os
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

# Configure engine connection args (SQLite requires check_same_thread=False for FastAPI concurrency)
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    # Auto-create parent directory if path contains a folder (e.g. ./data/instapay.db)
    sqlite_path = settings.DATABASE_URL.replace("sqlite:///", "")
    if sqlite_path and not sqlite_path.startswith(":memory:"):
        db_dir = os.path.dirname(sqlite_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    future=True,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True
)

Base = declarative_base()


def get_db():
    """Dependency that provides a SQLAlchemy database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_default_users():
    """Seeds default starter accounts if not present."""
    from app.models import User, ApiKey, utc_now
    db = SessionLocal()
    try:
        now = utc_now()
        # Seed/update Demo Account (Standard user for testing)
        demo = db.query(User).filter(User.passcode == "PASS-DEMO-2026").first()
        if not demo:
            user2 = User(
                name="Demo Merchant",
                email="demo@merchant.com",
                phone="01111111111",
                passcode="PASS-DEMO-2026",
                account_ending="8831",
                role="user",
                subscription_expires_at=now + timedelta(days=30),
                credits_balance=100,
                free_credits=100,
                free_credits_cycle_start=now,
                pass_credits=0,
                lifetime_credits=0,
                cashier_pin="A123C4",
                is_active=True,
                created_at=now,
            )
            db.add(user2)
        else:
            if not demo.email:
                demo.email = "demo@merchant.com"
            demo.account_ending = "8831"
            demo.role = "user"
            if not getattr(demo, "cashier_pin", None) or demo.cashier_pin == "1234":
                demo.cashier_pin = "A123C4"
            if not getattr(demo, "free_credits", None):
                demo.free_credits = 100
                demo.free_credits_cycle_start = now
                demo.pass_credits = 0
                demo.lifetime_credits = 0

        # Remove any static placeholder keys if present
        db.query(ApiKey).filter(ApiKey.key.in_(["instapay_live_demo_forwarder"])).delete(synchronize_session=False)

        db.commit()
    except Exception as e:
        db.rollback()
    finally:
        db.close()



def seed_default_packages(session=None):
    """Seeds default packages if the packages table is empty."""
    import json
    from app.models import Package, utc_now
    db = session or SessionLocal()
    should_close = (session is None)
    try:
        if db.query(Package).count() == 0:
            p1 = Package(
                plan_id="plan_30d",
                name="30 Days Validity Period",
                badge="Starter",
                price=30.00,
                original_price=30.00,
                discount_label=None,
                duration_days=30,
                credits=100,
                features=json.dumps([
                    "30 Days Dashboard Validity",
                    "100 Free Search Credits",
                    "Excel CSV Exports",
                    "Instant Auto-Matching"
                ]),
                is_active=True,
                sort_order=1,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            p2 = Package(
                plan_id="plan_90d",
                name="90 Days Validity Period",
                badge="Best Value",
                price=80.00,
                original_price=100.00,
                discount_label="20% OFF",
                duration_days=90,
                credits=350,
                features=json.dumps([
                    "90 Days Dashboard Validity",
                    "350 Search Credits",
                    "Priority Support",
                    "Instant Auto-Matching"
                ]),
                is_active=True,
                sort_order=2,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            p3 = Package(
                plan_id="plan_200pts",
                name="+200 Extra Search Credits",
                badge="Credits Only",
                price=25.00,
                original_price=25.00,
                discount_label=None,
                duration_days=0,
                credits=200,
                features=json.dumps([
                    "200 Extra Lookups",
                    "Never Expires (Lifetime)",
                    "Requires Active Validity"
                ]),
                is_active=True,
                sort_order=3,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add_all([p1, p2, p3])
            db.commit()

        # Check if plan_livestream exists; if not, add it
        p_ls = db.query(Package).filter(Package.plan_id == "plan_livestream").first()
        if not p_ls:
            new_ls = Package(
                plan_id="plan_livestream",
                name="Live Stream POS Terminal",
                badge="Cashier POS",
                price=100.00,
                original_price=150.00,
                discount_label="33% OFF",
                duration_days=30,
                credits=0,
                features=json.dumps([
                    "Live Real-Time Transactions Feed",
                    "ECG Heartbeat & Phone Monitor",
                    "Cashier Unread/Read Highlighting",
                    "Zero Search Credit Deductions",
                    "+5 Days Grace Period for Renewal"
                ]),
                is_active=True,
                sort_order=4,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            db.add(new_ls)
            db.commit()
    except Exception as e:
        db.rollback()
    finally:
        if should_close:
            db.close()


def migrate_columns_if_missing():
    """Auto-migrates SQLite tables when new columns are introduced."""
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            res = conn.execute(text("PRAGMA table_info(users)")).fetchall()
            existing_cols = [r[1] for r in res]
            if existing_cols:
                if "email" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(120)"))
                if "account_ending" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN account_ending VARCHAR(30)"))
                if "role" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))
                if "free_credits" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN free_credits INTEGER NOT NULL DEFAULT 100"))
                if "free_credits_granted_month" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN free_credits_granted_month VARCHAR(7)"))
                if "free_credits_cycle_start" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN free_credits_cycle_start DATETIME"))
                if "pass_credits" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN pass_credits INTEGER NOT NULL DEFAULT 0"))
                if "pass_credits_expires_at" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN pass_credits_expires_at DATETIME"))
                if "lifetime_credits" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN lifetime_credits INTEGER NOT NULL DEFAULT 0"))
                if "terms_accepted" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN terms_accepted BOOLEAN NOT NULL DEFAULT 1"))
                if "terms_accepted_at" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN terms_accepted_at DATETIME"))
                if "livestream_expires_at" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN livestream_expires_at DATETIME"))
                if "livestream_grace_until" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN livestream_grace_until DATETIME"))
                if "forwarder_last_seen_at" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN forwarder_last_seen_at DATETIME"))
                if "forwarder_battery" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN forwarder_battery INTEGER"))
                if "forwarder_network" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN forwarder_network VARCHAR(50)"))
                if "forwarder_device" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN forwarder_device VARCHAR(100)"))
                if "forwarder_uptime" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN forwarder_uptime VARCHAR(50)"))
                if "forwarder_status" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN forwarder_status VARCHAR(20) DEFAULT 'STANDBY'"))
                if "cashier_pin" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN cashier_pin VARCHAR(255) DEFAULT '1234'"))
                if "approval_status" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN approval_status VARCHAR(20) DEFAULT 'APPROVED'"))
                if "ecommerce_enabled" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN ecommerce_enabled BOOLEAN NOT NULL DEFAULT 1"))
                if "passcode_hash" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN passcode_hash VARCHAR(255)"))
                conn.commit()

            # Check api_keys columns
            result_ak = conn.execute(text("PRAGMA table_info(api_keys)"))
            ak_cols = [row[1] for row in result_ak.fetchall()]
            if "user_id" not in ak_cols:
                conn.execute(text("ALTER TABLE api_keys ADD COLUMN user_id INTEGER REFERENCES users(id)"))
                conn.commit()
            if "key_hash" not in ak_cols:
                conn.execute(text("ALTER TABLE api_keys ADD COLUMN key_hash VARCHAR(64)"))
                conn.commit()
            if "key_prefix" not in ak_cols:
                conn.execute(text("ALTER TABLE api_keys ADD COLUMN key_prefix VARCHAR(16)"))
                conn.commit()

            # Backfill key_hash and key_prefix for legacy api_keys
            try:
                import hashlib
                legacy_keys = conn.execute(text("SELECT id, key FROM api_keys WHERE key_hash IS NULL")).fetchall()
                for r in legacy_keys:
                    kid, kval = r[0], r[1]
                    if kval:
                        kh = hashlib.sha256(kval.strip().encode("utf-8")).hexdigest()
                        kp = kval.strip()[:12]
                        conn.execute(text("UPDATE api_keys SET key_hash = :kh, key_prefix = :kp WHERE id = :id"), {"kh": kh, "kp": kp, "id": kid})
                conn.commit()
            except Exception:
                pass

            # Check incoming_credits columns
            result_ic = conn.execute(text("PRAGMA table_info(incoming_credits)"))
            ic_cols = [row[1] for row in result_ic.fetchall()]
            if "user_id" not in ic_cols:
                conn.execute(text("ALTER TABLE incoming_credits ADD COLUMN user_id INTEGER REFERENCES users(id)"))
                conn.commit()
            if "is_matched" not in ic_cols:
                conn.execute(text("ALTER TABLE incoming_credits ADD COLUMN is_matched BOOLEAN NOT NULL DEFAULT 0"))
                conn.commit()
            if "matched_at" not in ic_cols:
                conn.execute(text("ALTER TABLE incoming_credits ADD COLUMN matched_at DATETIME"))
                conn.commit()
            if "is_read" not in ic_cols:
                conn.execute(text("ALTER TABLE incoming_credits ADD COLUMN is_read BOOLEAN NOT NULL DEFAULT 0"))
                conn.commit()
            if "read_at" not in ic_cols:
                conn.execute(text("ALTER TABLE incoming_credits ADD COLUMN read_at DATETIME"))
                conn.commit()

            # Check pending_orders columns
            result_po = conn.execute(text("PRAGMA table_info(pending_orders)"))
            po_cols = [row[1] for row in result_po.fetchall()]
            if "user_id" not in po_cols:
                conn.execute(text("ALTER TABLE pending_orders ADD COLUMN user_id INTEGER REFERENCES users(id)"))
                conn.commit()

            # Link legacy unlinked API keys to default merchant if needed
            conn.execute(text("UPDATE api_keys SET user_id = 1 WHERE user_id IS NULL AND name LIKE '%Merchant%'"))
            conn.commit()


            # Ensure default free_credits_granted_month, cycle_start & terms_accepted_at are populated if NULL
            conn.execute(text("UPDATE users SET free_credits_granted_month = strftime('%Y-%m', created_at) WHERE free_credits_granted_month IS NULL"))
            conn.execute(text("UPDATE users SET free_credits_cycle_start = created_at WHERE free_credits_cycle_start IS NULL"))
            conn.execute(text("UPDATE users SET terms_accepted_at = created_at WHERE terms_accepted_at IS NULL"))
            # Auto-assign legacy credits to user based on account_ending if user_id is NULL
            conn.execute(text("UPDATE incoming_credits SET user_id = (SELECT id FROM users WHERE users.account_ending = incoming_credits.account_ending AND users.account_ending IS NOT NULL LIMIT 1) WHERE user_id IS NULL AND account_ending IS NOT NULL"))
            # Rename legacy package names
            conn.execute(text("UPDATE packages SET name = '30 Days Validity Period' WHERE name = '30 Days Pass'"))
            conn.execute(text("UPDATE packages SET name = '90 Days Validity Period' WHERE name = '90 Days Pass'"))
            conn.execute(text("UPDATE packages SET name = '+200 Extra Search Credits' WHERE name = '+200 Credits'"))
            # Reset any legacy PBKDF2 hashed or 4-digit cashier_pin back to standard default 'A123C4'
            conn.execute(text("UPDATE users SET cashier_pin = 'A123C4' WHERE cashier_pin LIKE 'pbkdf2:%' OR cashier_pin = '1234'"))
            conn.commit()
        except Exception as e:
            print(f"[!] Migration warning: {e}")


def deduplicate_bank_patterns(session=None):
    """Removes duplicate bank patterns with identical bank_name and sender_filter, keeping only the first one."""
    from app.models import BankPattern
    db = session or SessionLocal()
    should_close = (session is None)
    try:
        all_patterns = db.query(BankPattern).order_by(BankPattern.id.asc()).all()
        seen = set()
        to_delete = []
        for p in all_patterns:
            key = (p.bank_name.strip().lower(), (p.sender_filter or "").strip().lower())
            if key in seen:
                to_delete.append(p.id)
            else:
                seen.add(key)
        
        if to_delete:
            for pid in to_delete:
                db.query(BankPattern).filter(BankPattern.id == pid).delete()
            db.commit()
            print(f"[+] Deduplicated bank patterns: removed {len(to_delete)} duplicate entries.")
    except Exception as e:
        print(f"[!] Error deduplicating bank patterns: {e}")
        db.rollback()
    finally:
        if should_close:
            db.close()


def seed_default_bank_patterns(session=None):
    """Seeds initial production regex patterns for all Egyptian banks idempotently."""
    from app.models import BankPattern, utc_now
    db = session or SessionLocal()
    should_close = (session is None)
    try:
        now = utc_now()
        default_patterns = [
            BankPattern(
                bank_name="NBE (البنك الأهلي المصري)",
                sender_filter="NBE",
                pattern=r"تم\s+(?:إيداع|تحويل)\s+مبلغ\s+(?P<amount>[\d,]+(?:\.\d{1,2})?)\s*(?:جم|ج\.م|EGP)?\s*(?:في|إلى|لحسابك)?\s*(?:حسابك)?\s*(?:المنتهي\s*بـ?\s*(?P<account>\d+))?.*?(?:من\s+(?P<sender>[\u0600-\u06FFa-zA-Z\s._-]+?))?(?:\s+عبر\s+انستاباي|\s+عبر\s+IPN)?.*?(?:ب?مرجع(?:\s*رقم)?|ب?رقم\s*(?:المرجع|العملية)|مرجع|رقم\s*المرجع|\bRef(?:erence)?\b)[:\s#]*(?P<ref>[A-Za-z0-9_-]+)",
                amount_group="amount",
                ref_group="ref",
                account_group="account",
                sender_group="sender",
                priority=10,
                is_active=True,
                example_sms="تم تحويل مبلغ 500.00 جم لحسابكم المنتهي بـ 1001 من احمد محمد عبر انستاباي بمرجع NBE123456789",
                created_at=now,
                updated_at=now,
            ),
            BankPattern(
                bank_name="CIB (البنك التجاري الدولي)",
                sender_filter="CIB",
                pattern=r"(?:Your\s+account\s+(?:ending\s+(?P<account>\d+))?\s+has\s+been\s+credited\s+with\s+(?:EGP\s*)?(?P<amount>[\d,]+(?:\.\d{1,2})?)|تم\s+إيداع\s+(?P<amount_ar>[\d,]+(?:\.\d{1,2})?)\s*(?:جم|ج\.م|EGP)?\s+بحسابك\s*(?P<account_ar>\d+)?).*?(?:from\s+(?P<sender>[A-Za-z\s._-]+)|من\s+(?P<sender_ar>[\u0600-\u06FFa-zA-Z\s._-]+))?.*?(?:\bRef(?:erence)?\b|ب?مرجع(?:\s*رقم)?|مرجع)[:\s#]*(?P<ref>[A-Za-z0-9_-]+)",
                amount_group="amount",
                ref_group="ref",
                account_group="account",
                sender_group="sender",
                priority=20,
                is_active=True,
                example_sms="Your account ending 1001 has been credited with EGP 1,250.00 from JOHN DOE. Ref: CIB987654321",
                created_at=now,
                updated_at=now,
            ),
            BankPattern(
                bank_name="Banque Misr (بنك مصر)",
                sender_filter="BM",
                pattern=r"تم\s+إيداع\s+مبلغ\s+(?P<amount>[\d,]+(?:\.\d{1,2})?)\s*(?:جم|ج\.م|EGP)?\s+في\s+حسابكم\s*(?:المنتهي\s*بـ?\s*(?P<account>\d+))?.*?(?:من\s+(?P<sender>[\u0600-\u06FFa-zA-Z\s._-]+))?.*?(?:رقم\s*العملية|ب?مرجع(?:\s*رقم)?|مرجع|المرجع|\bRef(?:erence)?\b)[:\s#]*(?P<ref>[A-Za-z0-9_-]+)",
                amount_group="amount",
                ref_group="ref",
                account_group="account",
                sender_group="sender",
                priority=30,
                is_active=True,
                example_sms="تم إيداع مبلغ 350.00 جم في حسابكم من محمد علي رقم العملية BM624FCFCB",
                created_at=now,
                updated_at=now,
            ),
            BankPattern(
                bank_name="HSBC",
                sender_filter="HSBC",
                pattern=r"Transfer\s+of\s+EGP\s*(?P<amount>[\d,]+(?:\.\d{1,2})?)\s+received\s+into\s+account\s*(?P<account>\d+)?.*?(?:from\s+(?P<sender>[A-Za-z\s._-]+))?.*?\bRef(?:erence)?\b[:\s#]*(?P<ref>[A-Za-z0-9_-]+)",
                amount_group="amount",
                ref_group="ref",
                account_group="account",
                sender_group="sender",
                priority=40,
                is_active=True,
                example_sms="Transfer of EGP 750.00 received into account 1001 from SARAH KHALID. Ref: HSBC88990011",
                created_at=now,
                updated_at=now,
            ),
            BankPattern(
                bank_name="QNB Alahli (بنك قطر الوطني الأهلي)",
                sender_filter="QNB",
                pattern=r"تم\s+إيداع\s+(?P<amount>[\d,]+(?:\.\d{1,2})?)\s*(?:جم|ج\.م|EGP)?\s+في\s+حسابك\s*(?:المنتهي\s*بـ?\s*(?P<account>\d+))?.*?(?:من\s+(?P<sender>[\u0600-\u06FFa-zA-Z\s._-]+))?.*?(?:المرجع|مرجع|ب?مرجع(?:\s*رقم)?|\bRef(?:erence)?\b)[:\s#]*(?P<ref>[A-Za-z0-9_-]+)",
                amount_group="amount",
                ref_group="ref",
                account_group="account",
                sender_group="sender",
                priority=50,
                is_active=True,
                example_sms="تم إيداع 400.00 جم في حسابك المنتهي بـ 1001 من عمر حسام المرجع QNB11223344",
                created_at=now,
                updated_at=now,
            ),
            BankPattern(
                bank_name="AlexBank (بنك الإسكندرية)",
                sender_filter="ALEXBANK",
                pattern=r"تم\s+(?:إيداع|تحويل)\s+مبلغ\s+(?P<amount>[\d,]+(?:\.\d{1,2})?)\s*(?:جم|ج\.م|EGP)?\s+بحسابك\s*(?:المنتهي\s*بـ?\s*(?P<account>\d+))?.*?(?:من\s+(?P<sender>[\u0600-\u06FFa-zA-Z\s._-]+))?.*?(?:رقم\s*(?:المرجع|العملية)|مرجع|ب?مرجع(?:\s*رقم)?|\bRef(?:erence)?\b)[:\s#]*(?P<ref>[A-Za-z0-9_-]+)",
                amount_group="amount",
                ref_group="ref",
                account_group="account",
                sender_group="sender",
                priority=60,
                is_active=True,
                example_sms="تم إيداع مبلغ 600.00 جم بحسابك من طارق يوسف رقم المرجع ALEX778899",
                created_at=now,
                updated_at=now,
            ),
            BankPattern(
                bank_name="AAIB (البنك العربي الأفريقي الدولي)",
                sender_filter="AAIB",
                pattern=r"Credit\s+of\s+EGP\s*(?P<amount>[\d,]+(?:\.\d{1,2})?)\s+to\s+A/C\s*(?P<account>\d+)?.*?(?:from\s+(?P<sender>[A-Za-z\s._-]+))?.*?(?:\bRef(?:erence)?\b|\bTxn\b|\bReference\b|مرجع)[:\s#]*(?P<ref>[A-Za-z0-9_-]+)",
                amount_group="amount",
                ref_group="ref",
                account_group="account",
                sender_group="sender",
                priority=70,
                is_active=True,
                example_sms="Credit of EGP 850.00 to A/C 1001 from AYMAN NOUR Ref AAIB55443322",
                created_at=now,
                updated_at=now,
            ),
            BankPattern(
                bank_name="Generic Insta / IPN Fallback",
                sender_filter=None,
                pattern=r"(?:مبلغ|بقيمة|قيمة|بمبلغ|credited|transfer|received|إيداع|ايداع|تحويل)\s*[:\s]?(?:EGP|LE|جم|ج\.م|جنيه)?\s*(?P<amount>[\d,]+(?:\.\d{1,2})?).*?(?:ب?مرجع(?:\s*رقم)?|ب?رقم\s*(?:المرجع|العملية)|مرجع|\bRef(?:erence)?\b|\bRRN\b|\bTRX\b)[:\s#]*(?P<ref>[A-Za-z0-9_-]+)",
                amount_group="amount",
                ref_group="ref",
                account_group="account",
                sender_group="sender",
                priority=100,
                is_active=True,
                example_sms="تحويل وارد بمبلغ 250.00 جم بمرجع IPN99887766",
                created_at=now,
                updated_at=now,
            ),
        ]
        
        for dp in default_patterns:
            exists = db.query(BankPattern).filter(
                BankPattern.bank_name == dp.bank_name,
                BankPattern.sender_filter == dp.sender_filter
            ).first()
            if not exists:
                db.add(dp)
        db.commit()
    except Exception as e:
        print(f"[!] Error seeding bank patterns: {e}")
        db.rollback()
    finally:
        if should_close:
            db.close()


def init_db():
    """Initialize database tables, run migrations, and seed starter data."""
    Base.metadata.create_all(bind=engine)
    migrate_columns_if_missing()
    seed_default_users()
    seed_default_packages()
    seed_default_bank_patterns()
    deduplicate_bank_patterns()
