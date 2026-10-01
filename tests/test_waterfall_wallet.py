import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User, Passcode, Package, utc_now
from app.services import (
    deduct_credits,
    check_and_refresh_monthly_free_credits,
    redeem_user_passcode,
    admin_adjust_user_quota,
    update_system_settings,
    register_new_merchant,
    generate_user_passcode,
)


class TestWaterfallWalletAndExpiration:
    """
    Tests for the 3-Bucket Waterfall Credit Wallet:
    - Bucket 1: Free Monthly Credits (100 pts, resets 1st of each calendar month)
    - Bucket 2: Day Pass Credits (tied to active day passes, non-stacking duration ceiling)
    - Bucket 3: Lifetime Rollover Credits (never expire, consumed last)
    """

    def test_waterfall_deduction_order(self, client, db_session: Session):
        now = utc_now()
        current_month = now.strftime("%Y-%m")
        user = User(
            name="Waterfall Test Merchant",
            email="waterfall@merchant.com",
            passcode="PASS-WATERFALL-01",
            subscription_expires_at=now + timedelta(days=30),
            free_credits=10,
            free_credits_granted_month=current_month,
            free_credits_cycle_start=now,
            pass_credits=20,
            pass_credits_expires_at=now + timedelta(days=30),
            lifetime_credits=50,
            credits_balance=80,
            is_active=True,
            created_at=now,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # 1. Deduct 5 credits -> Should deduct entirely from Free Credits (10 -> 5)
        deduct_credits(db_session, user, amount=5, operation="SEARCH_LOOKUP")
        assert user.free_credits == 5
        assert user.pass_credits == 20
        assert user.lifetime_credits == 50
        assert user.credits_balance == 75

        # 2. Deduct 10 credits -> Drains remaining 5 Free + 5 from Day Pass (20 -> 15)
        deduct_credits(db_session, user, amount=10, operation="UNLOCK_TRANSACTIONS_VAULT")
        assert user.free_credits == 0
        assert user.pass_credits == 15
        assert user.lifetime_credits == 50
        assert user.credits_balance == 65

        # 3. Deduct 25 credits -> Drains remaining 15 Day Pass + 10 from Lifetime (50 -> 40)
        deduct_credits(db_session, user, amount=25, operation="SEARCH_BATCH")
        assert user.free_credits == 0
        assert user.pass_credits == 0
        assert user.lifetime_credits == 40
        assert user.credits_balance == 40

    def test_day_pass_non_stacking_duration_ceiling(self, client, db_session: Session):
        now = utc_now()
        current_month = now.strftime("%Y-%m")
        user = User(
            name="Ceiling Duration User",
            email="ceiling@merchant.com",
            passcode="PASS-CEILING-01",
            subscription_expires_at=now + timedelta(days=10),
            free_credits=100,
            free_credits_granted_month=current_month,
            free_credits_cycle_start=now,
            pass_credits=0,
            lifetime_credits=0,
            credits_balance=100,
            is_active=True,
            created_at=now,
        )
        db_session.add(user)

        voucher = Passcode(
            code="PASS-30D-PASS",
            duration_days=30,
            credits_allocated=100,
            is_redeemed=False,
            expires_at=now + timedelta(days=90),
            created_at=now,
        )
        db_session.add(voucher)
        db_session.commit()

        redeem_user_passcode(db_session, user, "PASS-30D-PASS")

        diff_days = (user.subscription_expires_at - now).total_seconds() / 86400
        assert 29.5 <= diff_days <= 30.5
        assert user.pass_credits == 100
        assert user.credits_balance == 200

    def test_first_of_month_calendar_reset(self, client, db_session: Session):
        """
        Verifies that when a new calendar month begins (e.g. 2026-08 -> 2026-09),
        free monthly credits reset cleanly to 100 on the 1st of the month.
        """
        now = utc_now()
        # User had their credits granted in previous month (e.g. 2026-07) and spent down to 0
        user = User(
            name="Calendar Month Reset User",
            email="calreset@merchant.com",
            passcode="PASS-CALRESET-01",
            subscription_expires_at=now + timedelta(days=60),
            free_credits=0,
            free_credits_granted_month="2026-01", # Past month
            free_credits_cycle_start=now - timedelta(days=30),
            pass_credits=0,
            lifetime_credits=50,
            credits_balance=50,
            is_active=True,
            created_at=now - timedelta(days=30),
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        refreshed = check_and_refresh_monthly_free_credits(db_session, user)
        assert refreshed is True
        assert user.free_credits == 100
        assert user.free_credits_granted_month == now.strftime("%Y-%m")
        assert user.lifetime_credits == 50
        assert user.credits_balance == 150

    def test_security_anti_tampering_and_idempotency(self, client, db_session: Session):
        """
        Security Audit:
        1. Calling refresh 100 times in the same month cannot reset or multiply credits (idempotent).
        2. Client PUT /v1/user/profile payload cannot tamper with credit balances or granted month.
        """
        now = utc_now()
        current_month = now.strftime("%Y-%m")
        user = User(
            name="Security Target User",
            email="security@merchant.com",
            passcode="PASS-SEC-01",
            subscription_expires_at=now + timedelta(days=30),
            free_credits=45, # partially consumed
            free_credits_granted_month=current_month,
            free_credits_cycle_start=now,
            pass_credits=0,
            lifetime_credits=10,
            credits_balance=55,
            is_active=True,
            created_at=now,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        # 1. Repeated calls to refresh within same month MUST NOT reset the consumed balance
        for _ in range(20):
            refreshed = check_and_refresh_monthly_free_credits(db_session, user)
            assert refreshed is False
            assert user.free_credits == 45
            assert user.credits_balance == 55

        # 2. Tampering via profile update API
        user_headers = {"X-Passcode": "PASS-SEC-01"}
        tamper_res = client.put(
            "/v1/user/profile",
            headers=user_headers,
            json={
                "name": "Security Target User",
                "email": "security@merchant.com",
                "free_credits": 99999,
                "credits_balance": 99999,
                "free_credits_granted_month": "2020-01"
            }
        )
        assert tamper_res.status_code == 200
        prof = tamper_res.json()
        assert prof["free_credits"] == 45
        assert prof["credits_balance"] == 55
        assert prof["free_credits_granted_month"] == current_month

    def test_admin_wallet_adjustment_controls(self, client, db_session: Session):
        now = utc_now()
        user = User(
            name="Admin Adjust User",
            email="adjust@merchant.com",
            passcode="PASS-ADJUST-01",
            subscription_expires_at=now + timedelta(days=574),
            free_credits=20,
            free_credits_granted_month=now.strftime("%Y-%m"),
            free_credits_cycle_start=now,
            pass_credits=450,
            lifetime_credits=100,
            credits_balance=570,
            is_active=True,
            created_at=now,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        admin_adjust_user_quota(
            db=db_session,
            user_id=user.id,
            set_free_credits=100,
            set_pass_credits=0,
            set_lifetime_credits=200,
            set_subscription_days=30,
        )

        assert user.free_credits == 100
        assert user.pass_credits == 0
        assert user.lifetime_credits == 200
        assert user.credits_balance == 300
        diff_days = (user.subscription_expires_at - now).total_seconds() / 86400
        assert 29.5 <= diff_days <= 30.5

    def test_dynamic_monthly_free_credits_and_trial_days(self, client, db_session: Session):
        """
        Verify that:
        1. When monthly_free_credits and default_trial_days are customized in system settings,
           new merchants receive the dynamic credits and trial days (NO hardcoded 100 or 180).
        2. Monthly calendar reset honors the custom monthly_free_credits value.
        3. Passcode generation defaults to dynamic system settings when duration/credits are omitted.
        """
        # 1. Update system settings to custom non-default values
        update_system_settings(db_session, {
            "monthly_free_credits": 250,
            "default_trial_days": 90,
        })

        # 2. Self-register a new merchant
        now = utc_now()
        user, passcode = register_new_merchant(
            db=db_session,
            name="Dynamic Settings Merchant",
            email="dynamic@merchant.com",
        )

        assert user.credits_balance == 250
        assert user.free_credits == 250
        assert user.pass_credits == 0
        assert user.lifetime_credits == 0
        diff_days = (user.subscription_expires_at - now).total_seconds() / 86400
        assert 89 <= diff_days <= 91

        # 3. Test month rollover resets to dynamic 250 credits
        user.free_credits = 10
        user.credits_balance = 10
        user.free_credits_granted_month = "2025-12"
        db_session.commit()

        refreshed = check_and_refresh_monthly_free_credits(db_session, user)
        assert refreshed is True
        assert user.free_credits == 250
        assert user.credits_balance == 250

        # 4. Generate passcode with None for duration and credits -> defaults to 90 days and 250 credits
        p_user, p_code = generate_user_passcode(
            db=db_session,
            user_name="Auto Settings User",
            email="auto_settings@merchant.com",
            duration_days=None,
            credits=None,
        )
        assert p_user.free_credits == 250
        assert p_user.credits_balance == 250
        diff_p_days = (p_user.subscription_expires_at - now).total_seconds() / 86400
        assert 89 <= diff_p_days <= 91
