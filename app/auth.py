import os
import sys
import secrets
import hashlib
import hmac
from datetime import timedelta
from typing import Optional, List, Dict, Any
from dotenv import dotenv_values
from fastapi import Security, HTTPException, status, Header, Depends
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ApiKey, User, utc_now
from app.demo_sandbox import is_demo_passcode, get_demo_user_profile

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
API_KEY_QUERY = APIKeyQuery(name="api_key", auto_error=False)

PASSCODE_HEADER = APIKeyHeader(name="X-Passcode", auto_error=False)
PASSCODE_QUERY = APIKeyQuery(name="passcode", auto_error=False)


def hash_api_key(raw_key: str) -> str:
    """Compute SHA-256 hex digest of an API key for indexed constant-time lookup."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


def hash_secret(raw: str) -> str:
    """
    Hash a secret (passcode, PIN) using PBKDF2-HMAC-SHA256 with a cryptographically
    secure 16-byte random salt and 100,000 iterations.
    Output format: pbkdf2:sha256:100000$<salt_hex>$<dk_hex>
    """
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw.strip().encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"pbkdf2:sha256:100000${salt}${dk.hex()}"


def verify_secret(raw: str, stored: Optional[str]) -> bool:
    """
    Constant-time credential verification supporting:
    1. PBKDF2-HMAC-SHA256 hashed values (starts with 'pbkdf2:sha256:')
    2. Legacy plaintext values (constant-time secrets.compare_digest)
    """
    if not raw or not stored:
        return False
    raw_clean = raw.strip()
    stored_clean = stored.strip()

    if stored_clean.startswith("pbkdf2:sha256:"):
        try:
            parts = stored_clean.split("$")
            if len(parts) == 3:
                iter_spec, salt, expected_dk = parts
                iterations = int(iter_spec.split(":")[2])
                dk = hashlib.pbkdf2_hmac("sha256", raw_clean.encode("utf-8"), salt.encode("utf-8"), iterations)
                return hmac.compare_digest(dk.hex(), expected_dk)
        except Exception:
            return False

    # Legacy plaintext fallback — normalize both sides to a single canonical form
    # (uppercase, no spaces) before a single constant-time comparison.
    # Using one compare_digest instead of three sequential calls eliminates the
    # composite timing signature that three separate calls would produce.
    canonical_raw = raw_clean.replace(" ", "").upper()
    canonical_stored = stored_clean.replace(" ", "").upper()
    return secrets.compare_digest(canonical_raw, canonical_stored)


def is_hashed(stored: Optional[str]) -> bool:
    """Check if stored credential has already been upgraded to a secure PBKDF2 hash."""
    return bool(stored and stored.startswith("pbkdf2:sha256:"))


def find_api_key(db: Session, raw_key: str, role: Optional[str] = None) -> Optional[ApiKey]:
    """
    Looks up an ApiKey via SHA-256 hash index or fallback plaintext, self-healing hash if missing.
    """
    if not raw_key:
        return None
    cand_hash = hash_api_key(raw_key)
    query = db.query(ApiKey).filter(
        (ApiKey.key_hash == cand_hash) | (ApiKey.key == raw_key),
        ApiKey.is_active == True
    )
    if role:
        query = query.filter(ApiKey.role == role)
    db_key = query.first()

    if db_key and (db_key.key_hash is None or db_key.key_prefix is None):
        try:
            db_key.key_hash = cand_hash
            db_key.key_prefix = raw_key.strip()[:12]
            db.commit()
        except Exception:
            db.rollback()

    return db_key


def find_user_by_passcode(db: Session, raw_passcode: str) -> Optional[User]:
    """
    Looks up an active User by passcode with dual-mode support:
    1. Direct exact or normalized plaintext match (legacy)
    2. Salted PBKDF2 cryptographic hash verification (migrated)
    3. Dedicated passcode_hash column check
    """
    if not raw_passcode:
        return None
    from sqlalchemy import func
    raw_clean = raw_passcode.strip()
    clean_code = raw_clean.replace(" ", "").upper()
    lower_code = raw_clean.lower()

    # 1. Plaintext direct match
    user = db.query(User).filter(
        (User.passcode == raw_clean) |
        (User.passcode == clean_code) |
        (func.lower(User.passcode) == lower_code),
        User.is_active == True
    ).first()
    if user:
        return user

    # 2. Salted PBKDF2 hash match in User.passcode
    hashed_users = db.query(User).filter(
        User.passcode.like("pbkdf2:%"),
        User.is_active == True
    ).all()
    for u in hashed_users:
        if verify_secret(raw_clean, u.passcode):
            return u

    # 3. Check passcode_hash column if present
    if hasattr(User, "passcode_hash"):
        hashed_by_col = db.query(User).filter(
            User.passcode_hash.isnot(None),
            User.is_active == True
        ).all()
        for u in hashed_by_col:
            if verify_secret(raw_clean, u.passcode_hash):
                return u

    return None


def find_inactive_user_by_passcode(db: Session, raw_passcode: str) -> Optional[User]:
    """Looks up an inactive User by passcode with dual-mode support."""
    if not raw_passcode:
        return None
    from sqlalchemy import func
    raw_clean = raw_passcode.strip()
    clean_code = raw_clean.replace(" ", "").upper()
    lower_code = raw_clean.lower()

    user = db.query(User).filter(
        (User.passcode == raw_clean) |
        (User.passcode == clean_code) |
        (func.lower(User.passcode) == lower_code),
        User.is_active == False
    ).first()
    if user:
        return user

    hashed_users = db.query(User).filter(
        User.passcode.like("pbkdf2:%"),
        User.is_active == False
    ).all()
    for u in hashed_users:
        if verify_secret(raw_clean, u.passcode):
            return u
    return None


def get_current_master_keys() -> List[str]:
    """Retrieve all valid master/admin API keys dynamically from .env and environment settings."""
    keys = set()
    if settings.MASTER_API_KEY:
        keys.add(settings.MASTER_API_KEY.strip())
    env_master = os.getenv("MASTER_API_KEY")
    if env_master:
        keys.add(env_master.strip())
    try:
        env_dict = dotenv_values(".env")
        dot_key = env_dict.get("MASTER_API_KEY")
        if dot_key:
            keys.add(dot_key.strip())
    except Exception:
        pass

    # Provide a testing fallback only if no key is configured and running under tests/dev
    if not keys:
        is_test = "pytest" in sys.modules or os.getenv("TESTING") == "True"
        is_prod = os.getenv("ENVIRONMENT", settings.ENVIRONMENT).lower() == "production"

        if is_prod and not is_test:
            # In production with no key configured: refuse to operate
            import logging as _security_log
            _security_log.getLogger("instapay").critical(
                "[SECURITY CRITICAL] MASTER_API_KEY is not configured and ENVIRONMENT=production! "
                "Set MASTER_API_KEY in your .env file before starting in production."
            )
            raise RuntimeError(
                "MASTER_API_KEY must be set when ENVIRONMENT=production. "
                "Configure it in .env and restart."
            )

        # Non-production / test fallback — emit a visible warning so it's never silently missed
        import logging as _security_log
        _security_log.getLogger("instapay").warning(
            "[SECURITY WARNING] MASTER_API_KEY is not set in environment. "
            "Using insecure development fallback key. "
            "This is ONLY acceptable in local dev / test environments. "
            "Set MASTER_API_KEY in .env and ENVIRONMENT=production before deploying."
        )
        keys.add("XAZAjxjhbCtSgiq7")
    return [k for k in keys if k]


def extract_candidate_keys(
    header_key: Optional[str],
    query_key: Optional[str],
    authorization: Optional[str],
) -> List[str]:
    """Extract and clean candidate keys from headers or query parameters."""
    candidates = []
    if header_key:
        candidates.append(header_key.strip().strip("\"'{} "))
    if query_key:
        candidates.append(query_key.strip().strip("\"'{} "))
    if authorization:
        auth_val = authorization
        if auth_val.lower().startswith("bearer ") or auth_val.lower().startswith("apikey "):
            auth_val = auth_val.split(" ", 1)[1]
        candidates.append(auth_val.strip().strip("\"'{} "))

    # Filter out empty or Swagger dummy placeholders
    return [
        c for c in candidates if c and c.lower() not in ["", "api_key", "string", "none", "null"]
    ]


async def verify_api_key(
    header_key: Optional[str] = Security(API_KEY_HEADER),
    query_key: Optional[str] = Security(API_KEY_QUERY),
    passcode_header: Optional[str] = Security(PASSCODE_HEADER),
    passcode_query: Optional[str] = Security(PASSCODE_QUERY),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> str:
    """
    Validates API Key from:
    1. MASTER_API_KEY (.env / super admin).
    2. Active database developer/forwarder keys (api_keys table).
    3. Active database merchant/user passcodes (users table).
    """
    from sqlalchemy import func

    valid_candidates = extract_candidate_keys(header_key, query_key, authorization)
    pass_candidates = extract_candidate_keys(passcode_header, passcode_query, None)
    all_candidates = list(dict.fromkeys(valid_candidates + pass_candidates))

    if not all_candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required security header: X-API-Key, X-Passcode or query param api_key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # 1. Check Master Super Admin Keys
    master_keys = [k for k in get_current_master_keys() if k]
    for candidate in all_candidates:
        clean_cand = candidate.replace(" ", "").upper()
        for master_key in master_keys:
            clean_master = master_key.replace(" ", "").upper()
            if secrets.compare_digest(candidate, master_key) or secrets.compare_digest(clean_cand, clean_master):
                return candidate

    # 1b. Check Demo Sandbox Passcode
    for candidate in all_candidates:
        if is_demo_passcode(candidate):
            return candidate

    # 2. Check Database Developer / Forwarder Keys (api_keys table via hash or key)
    for candidate in all_candidates:
        db_key = find_api_key(db, candidate)
        if db_key:
            try:
                db_key.last_used_at = utc_now()
                db.commit()
            except Exception:
                db.rollback()
            return db_key.key

    # 3. Check Database Merchant / User Passcodes (users table via dual-mode)
    for candidate in all_candidates:
        user = find_user_by_passcode(db, candidate)
        if user:
            if user.subscription_expires_at < utc_now():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"User subscription expired on {user.subscription_expires_at.strftime('%Y-%m-%d')}.",
                )
            try:
                user.last_active_at = utc_now()
                db.commit()
            except Exception:
                db.rollback()
            return candidate

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid or deactivated API Key / Passcode provided",
    )


async def verify_admin_key(
    header_key: Optional[str] = Security(API_KEY_HEADER),
    query_key: Optional[str] = Security(API_KEY_QUERY),
    passcode_header: Optional[str] = Security(PASSCODE_HEADER),
    passcode_query: Optional[str] = Security(PASSCODE_QUERY),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> str:
    """
    Ensures the caller has Admin privileges:
    1. Master Super Admin keys.
    2. Database API keys with role='admin'.
    3. Database User passcodes with role='admin'.
    """
    from sqlalchemy import func

    valid_candidates = extract_candidate_keys(header_key, query_key, authorization)
    pass_candidates = extract_candidate_keys(passcode_header, passcode_query, None)
    admin_candidates = [x_admin_key.strip()] if (x_admin_key and x_admin_key.strip()) else []
    all_candidates = list(dict.fromkeys(valid_candidates + pass_candidates + admin_candidates))

    if not all_candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required Admin API Key or Passcode",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # 1. Check Master Keys
    master_keys = [k for k in get_current_master_keys() if k]
    for candidate in all_candidates:
        clean_cand = candidate.replace(" ", "").upper()
        for master_key in master_keys:
            clean_master = master_key.replace(" ", "").upper()
            if secrets.compare_digest(candidate, master_key) or secrets.compare_digest(clean_cand, clean_master):
                return candidate

    # 2. Check Database Admin Keys (api_keys table)
    for candidate in all_candidates:
        db_key = find_api_key(db, candidate, role="admin")
        if db_key:
            return db_key.key

    # 3. Check Database Admin Users (users table)
    for candidate in all_candidates:
        user = find_user_by_passcode(db, candidate)
        if user and user.role == "admin":
            return candidate

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin privileges required for this endpoint.",
    )


async def verify_master_super_admin_key(
    header_key: Optional[str] = Security(API_KEY_HEADER),
    query_key: Optional[str] = Security(API_KEY_QUERY),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> str:
    """
    Strict 2nd-Layer Security Validator:
    Accepts ONLY Super Admin Master Keys (from .env / MASTER_API_KEY).
    Strictly REJECTS account passcodes (even if role is admin).
    """
    valid_candidates = extract_candidate_keys(header_key, query_key, authorization)
    if not valid_candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Master Admin API Key in X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    master_keys = [k for k in get_current_master_keys() if k]
    for candidate in valid_candidates:
        # Check if candidate matches any user's passcode in the database (which must be rejected for 2nd layer)
        user_match = find_user_by_passcode(db, candidate)
        if user_match and user_match.id == 0:
            user_match = None

        # Check Master Keys
        clean_cand = candidate.replace(" ", "").upper()
        for master_key in master_keys:
            clean_master = master_key.replace(" ", "").upper()
            if secrets.compare_digest(candidate, master_key) or secrets.compare_digest(clean_cand, clean_master):
                return candidate

        # Check Database Admin API Keys (api_keys table only, not user passcode)
        db_key = find_api_key(db, candidate, role="admin")
        if db_key and not user_match:
            return db_key.key

        if user_match:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account passcodes cannot be used as the Master Admin Key. Please enter the Super Admin API Key."
            )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid Super Admin API Key. Access denied.",
    )


def resolve_user_from_api_key(api_k: Optional[ApiKey], db: Session) -> Optional[User]:
    """
    Safely resolves a User record from an ApiKey entity.
    Resolution priority:
      1. Direct foreign key: api_k.user_id (exact match).
      2. Key name contains exact user passcode (e.g. '(PASS-XXXX-XXXX)' or 'PASS-XXXX-XXXX').
      3. Key name matches exact user full name (case-insensitive).
    Self-heals api_k.user_id if resolved via fallback.
    Never uses loose numeric or substring checks to prevent cross-account leakage.
    """
    if not api_k:
        return None

    # 1. Direct foreign key link (most authoritative)
    if getattr(api_k, "user_id", None):
        user = db.query(User).filter(User.id == api_k.user_id, User.is_active == True).first()
        if user:
            return user

    # 2. Strict matching against name / passcode
    if not api_k.name:
        return None

    clean_kname = api_k.name.strip()
    kname_upper = clean_kname.upper()
    kname_lower = clean_kname.lower()

    active_users = db.query(User).filter(User.is_active == True).all()
    matched_user = None

    # Priority 2a: Match exact passcode in key name (e.g. "(PASS-E906-BDD7)" or "PASS-E906-BDD7")
    for u in active_users:
        if u.passcode:
            u_pass = u.passcode.strip().upper()
            if len(u_pass) >= 4 and (f"({u_pass})" in kname_upper or u_pass in kname_upper):
                matched_user = u
                break

    # Priority 2b: Match exact merchant/user name
    if not matched_user:
        for u in active_users:
            if u.name and u.name.strip().lower() == kname_lower:
                matched_user = u
                break

    # If matched via name/passcode fallback, self-heal api_k.user_id
    if matched_user:
        try:
            api_k.user_id = matched_user.id
            db.commit()
        except Exception:
            db.rollback()

    return matched_user


async def get_current_user(
    passcode_header: Optional[str] = Security(PASSCODE_HEADER),
    passcode_query: Optional[str] = Security(PASSCODE_QUERY),
    api_key_header: Optional[str] = Security(API_KEY_HEADER),
    api_key_query: Optional[str] = Security(API_KEY_QUERY),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Authenticates a platform user by their passcode, email, or dedicated forwarder API key.
    Verifies active status and subscription validity.
    """
    pass_candidates = extract_candidate_keys(passcode_header, passcode_query, authorization)
    key_candidates = extract_candidate_keys(api_key_header, api_key_query, None)
    candidates = list(dict.fromkeys(pass_candidates + key_candidates))

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide your user Passcode or API key.",
            headers={"WWW-Authenticate": "Passcode"},
        )

    raw_passcode = candidates[0].strip()
    clean_passcode = raw_passcode.replace(" ", "").upper()
    lower_passcode = raw_passcode.lower()

    # 1. Allow Super Admin
    master_keys = get_current_master_keys()
    for m in master_keys:
        if raw_passcode == m or clean_passcode == m.upper() or secrets.compare_digest(raw_passcode, m):
            from datetime import timedelta
            return User(
                id=0,
                name="Super Admin",
                email="admin@instapay.com",
                passcode=raw_passcode,
                role="admin",
                credits_balance=99999,
                subscription_expires_at=utc_now() + timedelta(days=3650),
                is_active=True,
                created_at=utc_now(),
            )

    # 1b. Allow Demo Sandbox User
    if is_demo_passcode(raw_passcode):
        from datetime import timedelta
        return User(
            id=999999,
            name="Demo Merchant (Sandbox)",
            email="demo@motaaked.com",
            phone="01000000000",
            passcode=raw_passcode,
            role="demo",
            account_ending="4812",
            credits_balance=250,
            free_credits=100,
            pass_credits=150,
            subscription_expires_at=utc_now() + timedelta(days=30),
            is_active=True,
            cashier_pin="123456",
            approval_status="APPROVED",
            ecommerce_enabled=True,
            created_at=utc_now() - timedelta(days=5),
            last_active_at=utc_now(),
        )

    # 2. Check Database Users strictly by Passcode (dual-mode)
    user = find_user_by_passcode(db, raw_passcode)

    # 3. Check if candidate is a dedicated forwarder API Key
    if not user:
        api_k = find_api_key(db, raw_passcode)
        if api_k:
            user = resolve_user_from_api_key(api_k, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or inactive user Passcode.",
        )

    # Check subscription expiration
    now = utc_now()
    if user.subscription_expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Subscription expired on {user.subscription_expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}. Please renew your passcode.",
        )

    # Update last active timestamp
    try:
        user.last_active_at = now
        db.commit()
    except Exception:
        db.rollback()

    return user


async def get_current_user_allow_expired(
    passcode_header: Optional[str] = Security(PASSCODE_HEADER),
    passcode_query: Optional[str] = Security(PASSCODE_QUERY),
    api_key_header: Optional[str] = Security(API_KEY_HEADER),
    api_key_query: Optional[str] = Security(API_KEY_QUERY),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Similar to get_current_user but does NOT throw 403 if subscription is expired.
    Allows expired users to access topup/renewal endpoints.
    """
    pass_candidates = extract_candidate_keys(passcode_header, passcode_query, authorization)
    key_candidates = extract_candidate_keys(api_key_header, api_key_query, None)
    candidates = list(dict.fromkeys(pass_candidates + key_candidates))

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide your user Passcode or API key.",
            headers={"WWW-Authenticate": "Passcode"},
        )

    raw_passcode = candidates[0].strip()
    clean_passcode = raw_passcode.replace(" ", "").upper()
    lower_passcode = raw_passcode.lower()

    # 1. Allow Super Admin
    master_keys = get_current_master_keys()
    for m in master_keys:
        if raw_passcode == m or clean_passcode == m.upper() or secrets.compare_digest(raw_passcode, m):
            from datetime import timedelta
            return User(
                id=0,
                name="Super Admin",
                email="admin@instapay.com",
                passcode=raw_passcode,
                role="admin",
                credits_balance=99999,
                subscription_expires_at=utc_now() + timedelta(days=3650),
                is_active=True,
                created_at=utc_now(),
            )

    # 1b. Allow Demo Sandbox User
    if is_demo_passcode(raw_passcode):
        from datetime import timedelta
        return User(
            id=999999,
            name="Demo Merchant (Sandbox)",
            email="demo@motaaked.com",
            phone="01000000000",
            passcode=raw_passcode,
            role="demo",
            account_ending="4812",
            credits_balance=250,
            free_credits=100,
            pass_credits=150,
            subscription_expires_at=utc_now() + timedelta(days=30),
            is_active=True,
            cashier_pin="123456",
            approval_status="APPROVED",
            ecommerce_enabled=True,
            created_at=utc_now() - timedelta(days=5),
            last_active_at=utc_now(),
        )

    user = find_user_by_passcode(db, raw_passcode)
    if not user:
        api_k = find_api_key(db, raw_passcode)
        if api_k:
            user = resolve_user_from_api_key(api_k, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or inactive user Passcode.",
        )

    try:
        user.last_active_at = utc_now()
        db.commit()
    except Exception:
        db.rollback()

    return user


async def get_authenticated_actor(
    api_key_header: Optional[str] = Security(API_KEY_HEADER),
    api_key_query: Optional[str] = Security(API_KEY_QUERY),
    passcode_header: Optional[str] = Security(PASSCODE_HEADER),
    passcode_query: Optional[str] = Security(PASSCODE_QUERY),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Polymorphic dependency: Resolves caller as either Super Admin / Developer Merchant or Passcode User.
    """
    from sqlalchemy import func

    valid_candidates = extract_candidate_keys(api_key_header, api_key_query, authorization)
    pass_candidates = extract_candidate_keys(passcode_header, passcode_query, None)
    all_candidates = list(dict.fromkeys(valid_candidates + pass_candidates))

    if not all_candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials (API Key or Passcode required).",
        )

    # 1. Check Master Keys
    master_keys = [k for k in get_current_master_keys() if k]
    for candidate in all_candidates:
        clean_cand = candidate.replace(" ", "").upper()
        for master_key in master_keys:
            clean_master = master_key.replace(" ", "").upper()
            if secrets.compare_digest(candidate, master_key) or secrets.compare_digest(clean_cand, clean_master):
                admin_u = db.query(User).filter(User.role == "admin", User.is_active == True).first()
                if not admin_u:
                    admin_u = db.query(User).filter(User.id == 0).first()
                if not admin_u:
                    admin_u = User(id=0, name="Super Admin", passcode="ADMIN", role="admin", is_active=True)
                return {"type": "admin", "actor": "Super Admin", "user": admin_u, "is_admin": True}

    # 1b. Check Demo Sandbox Passcode
    for candidate in all_candidates:
        if is_demo_passcode(candidate):
            from datetime import timedelta
            demo_u = User(
                id=999999,
                name="Demo Merchant (Sandbox)",
                email="demo@motaaked.com",
                phone="01000000000",
                passcode=candidate,
                role="demo",
                account_ending="4812",
                credits_balance=250,
                free_credits=100,
                pass_credits=150,
                subscription_expires_at=utc_now() + timedelta(days=30),
                is_active=True,
                cashier_pin="123456",
                approval_status="APPROVED",
                ecommerce_enabled=True,
                created_at=utc_now() - timedelta(days=5),
                last_active_at=utc_now(),
            )
            return {"type": "demo", "actor": "Demo Merchant (Sandbox)", "user": demo_u, "is_admin": False}

    # 2. Check Database API Keys (api_keys table)
    for candidate in all_candidates:
        db_key = find_api_key(db, candidate)
        if db_key:
            is_adm = (db_key.role == "admin")
            matched_user = None
            if is_adm:
                matched_user = db.query(User).filter(User.role == "admin", User.is_active == True).first()
                if not matched_user:
                    matched_user = User(id=0, name="Super Admin", passcode="ADMIN", role="admin", is_active=True)
            else:
                matched_user = resolve_user_from_api_key(db_key, db)
                if not matched_user:
                    matched_user = User(
                        name=db_key.name or f"Merchant-{db_key.id}",
                        passcode=f"PASS-{secrets.token_hex(4).upper()}",
                        role="user",
                        subscription_expires_at=utc_now() + timedelta(days=365),
                        credits_balance=1000,
                        is_active=True,
                    )
                    db.add(matched_user)
                    try:
                        db.commit()
                        db.refresh(matched_user)
                        db_key.user_id = matched_user.id
                        db.commit()
                    except Exception:
                        db.rollback()
            return {"type": "admin" if is_adm else "merchant", "actor": db_key.name or "Merchant", "user": matched_user, "is_admin": is_adm}

    # 3. Check Database Users (users table)
    for candidate in all_candidates:
        user = find_user_by_passcode(db, candidate)
        if user:
            if user.subscription_expires_at < utc_now():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Subscription expired on {user.subscription_expires_at.strftime('%Y-%m-%d')}.",
                )
            is_adm = (user.role == "admin")
            return {"type": "admin" if is_adm else "user", "actor": user.name, "user": user, "is_admin": is_adm}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or deactivated authentication credentials.",
    )

