import pytest
from app.models import User, utc_now


class TestCycle4AdminAndTopUp:

    def test_topup_initiate_and_automated_activation(self, client, auth_headers):
        # 1. Create a user with 10 credits
        res_user = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "E-Commerce Merchant", "custom_code": "PASS-MERCHANT-01", "duration_days": 30, "credits": 10},
        )
        assert res_user.status_code == 201
        user_headers = {"X-Passcode": "PASS-MERCHANT-01"}

        # 2. User initiates top-up for 30 Days Plan (30.00 EGP)
        res_topup = client.post(
            "/v1/topup/initiate",
            headers=user_headers,
            json={"plan_id": "plan_30d"},
        )
        assert res_topup.status_code == 200
        topup_data = res_topup.json()
        assert topup_data["amount"] == 30.00
        order_id = topup_data["order_id"]
        assert order_id.startswith("TOPUP-")

        # 3. User makes the transfer via InstaPay -> Forwarder receives SMS!
        sms_text = f"Your HSBC Account ********1001 was credited with IPN inward transfer for EGP 30.00 from MERCHANT with reference TOPUP_REF_999."
        res_sms = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": sms_text},
        )
        assert res_sms.status_code == 201

        # 4. User enters reference ID to verify and activate
        res_verify = client.post(
            "/v1/topup/verify",
            headers=user_headers,
            json={"order_id": order_id, "reference_id": "TOPUP_REF_999"},
        )
        assert res_verify.status_code == 200
        data_verify = res_verify.json()
        assert data_verify["success"] is True
        assert data_verify["amount"] == 30.00
        profile = data_verify["user_profile"]
        # Credits balance should now be 10 + 100 = 110!
        assert profile["credits_balance"] == 110

    def test_recharge_tracking_never_deducts_credits_even_with_zero_balance(self, client, auth_headers):
        # 1. Create a user with exactly 0 credits
        res_user = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Zero Balance Merchant", "custom_code": "PASS-ZERO-CREDIT", "duration_days": 30, "credits": 0},
        )
        assert res_user.status_code == 201
        user_headers = {"X-Passcode": "PASS-ZERO-CREDIT"}

        # 2. User tracks recharge payment with is_topup=True -> must NOT deduct credits, must succeed!
        res_watch = client.post(
            "/v1/watchlist/watch",
            headers=user_headers,
            json={"reference_id": "RECHARGE-REF-123", "is_topup": True},
        )
        assert res_watch.status_code == 201
        data = res_watch.json()
        assert data["credits_remaining"] == 0  # No negative balance, no deduction!

    def test_gift_voucher_purchase_and_90day_redemption(self, client, auth_headers):
        # 1. User A (Buyer) registers
        res_buyer = client.post(
            "/v1/auth/register",
            json={"name": "Buyer Merchant", "email": "buyer@merchant.com"},
        )
        assert res_buyer.status_code == 201
        buyer_passcode = res_buyer.json()["passcode"]
        buyer_headers = {"X-Passcode": buyer_passcode}

        # 2. Buyer initiates Gift Code Purchase for 90 Days Plan (80.00 EGP)
        res_init = client.post(
            "/v1/topup/initiate",
            headers=buyer_headers,
            json={
                "plan_id": "plan_90d",
                "purchase_type": "gift",
                "recipient_email": "friend@company.com",
            },
        )
        assert res_init.status_code == 200
        init_data = res_init.json()
        assert init_data["purchase_type"] == "gift"
        order_id = init_data["order_id"]
        assert order_id.startswith("GIFT-")

        # 3. Transfer SMS arrives
        res_sms = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": "تم تحويل 80.00 جم إلى حسابك برقم مرجعي GIFT_REF_8888 بتاريخ اليوم"},
        )
        assert res_sms.status_code == 201

        # 4. Verify & Activate -> Generates 90-day Voucher Code
        res_verify = client.post(
            "/v1/topup/verify",
            headers=buyer_headers,
            json={
                "order_id": order_id,
                "reference_id": "GIFT_REF_8888",
                "recipient_email": "friend@company.com",
            },
        )
        assert res_verify.status_code == 200
        v_data = res_verify.json()
        assert v_data["success"] is True
        assert v_data["purchase_type"] == "gift"
        assert v_data["voucher_code"] is not None
        assert v_data["voucher_code"].startswith("PASS-")
        voucher_code = v_data["voucher_code"]

        # Buyer's account should NOT have received the 350 credits (buyer only bought a gift code!)
        res_buyer_prof = client.get("/v1/user/profile", headers=buyer_headers)
        assert res_buyer_prof.json()["credits_balance"] == 100  # original starter credits

        # 5. User B (Recipient) registers and redeems the voucher code
        res_recipient = client.post(
            "/v1/auth/register",
            json={"name": "Recipient Merchant", "email": "friend@company.com"},
        )
        assert res_recipient.status_code == 201
        rec_passcode = res_recipient.json()["passcode"]
        rec_headers = {"X-Passcode": rec_passcode}

        res_redeem = client.post(
            "/v1/passcodes/redeem",
            headers=rec_headers,
            json={"passcode": voucher_code},
        )
        assert res_redeem.status_code == 200
        rec_prof = res_redeem.json()
        # 100 starter + 350 package credits = 450 credits!
        assert rec_prof["credits_balance"] == 450

        # 6. Attempting to re-redeem the same voucher code must fail
        res_double_redeem = client.post(
            "/v1/passcodes/redeem",
            headers=rec_headers,
            json={"passcode": voucher_code},
        )
        assert res_double_redeem.status_code == 400
        assert "already been redeemed" in res_double_redeem.json()["detail"]

    def test_admin_metrics_and_user_adjustment(self, client, auth_headers):
        # 1. Create a user first
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Adjustable User", "custom_code": "PASS-ADJUST-ME", "duration_days": 30, "credits": 40},
        )

        # 2. Fetch Admin Metrics
        res_metrics = client.get("/v1/admin/metrics", headers=auth_headers)
        assert res_metrics.status_code == 200
        met = res_metrics.json()
        assert "total_transactions" in met
        assert "total_volume_egp" in met
        assert "unclaimed_credits" in met
        assert "claimed_credits" in met
        assert met["total_users"] >= 1

        # 3. List Users
        res_users = client.get("/v1/admin/users/list", headers=auth_headers)
        assert res_users.status_code == 200
        users_list = res_users.json()
        assert users_list["total"] >= 1
        target_user = users_list["users"][0]
        user_id = target_user["id"]
        initial_balance = target_user["credits_balance"]

        # 4. Admin adjusts quota (+50 credits, +30 days)
        res_adj = client.post(
            "/v1/admin/users/adjust",
            headers=auth_headers,
            json={"user_id": user_id, "add_credits": 50, "add_days": 30},
        )
        assert res_adj.status_code == 200
        assert res_adj.json()["credits_balance"] == initial_balance + 50

    def test_admin_system_settings_config(self, client, auth_headers):
        # 1. Create an admin user
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Haitham Admin", "custom_code": "PASS-HAITHAM-TEST", "duration_days": 30, "credits": 50, "role": "admin"},
        )

        # 2. Fetch current settings
        res_get = client.get("/v1/admin/settings", headers={"X-Passcode": "PASS-HAITHAM-TEST"})
        assert res_get.status_code == 200
        data = res_get.json()
        assert "instapay_handle" in data

        # 3. Reject update if wrong or missing master admin key
        res_fail = client.post(
            "/v1/admin/settings",
            headers={"X-Passcode": "PASS-HAITHAM-TEST"},
            json={
                "admin_key": "WRONG_KEY_123",
                "instapay_handle": "hacker@instapay",
            },
        )
        assert res_fail.status_code == 403

        # 4. Accept update when valid Master Admin Key is provided
        res_post = client.post(
            "/v1/admin/settings",
            headers={"X-Passcode": "PASS-HAITHAM-TEST"},
            json={
                "admin_key": "XAZAjxjhbCtSgiq7",
                "instapay_handle": "custom_haitham@instapay",
                "instapay_phone": "01234567890",
                "instapay_account_ending": "5555",
                "instapay_receiver_name": "Haitham Refaat Admin",
                "match_window_minutes": 45,
                "default_trial_days": 180,
            },
        )
        assert res_post.status_code == 200
        updated = res_post.json()
        assert updated["instapay_handle"] == "custom_haitham@instapay"
        assert updated["instapay_account_ending"] == "5555"
        assert updated["match_window_minutes"] == 45
        assert updated["default_trial_days"] == 180

    def test_expired_validity_blocks_credit_only_purchases(self, client, auth_headers, db_session):
        from datetime import timedelta
        from app.models import User, utc_now

        # 1. Create a user
        res_create = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Expired User", "custom_code": "PASS-EXPI-9999", "duration_days": 30, "credits": 50},
        )
        assert res_create.status_code == 201
        user_headers = {"X-Passcode": "PASS-EXPI-9999"}

        # Manually expire the user's subscription in the database session
        user_row = db_session.query(User).filter(User.name == "Expired User").first()
        assert user_row is not None
        user_row.subscription_expires_at = utc_now() - timedelta(days=5)
        db_session.commit()

        # 2. Try to initiate topup for credit-only pack (plan_200pts) -> must be BLOCKED with 400 for both direct and gift!
        res_blocked_direct = client.post(
            "/v1/topup/initiate",
            headers=user_headers,
            json={"plan_id": "plan_200pts", "purchase_type": "direct"},
        )
        assert res_blocked_direct.status_code == 400
        assert "Validity Period has expired" in res_blocked_direct.json()["detail"]

        res_blocked_gift = client.post(
            "/v1/topup/initiate",
            headers=user_headers,
            json={"plan_id": "plan_200pts", "purchase_type": "gift"},
        )
        assert res_blocked_gift.status_code == 400
        assert "Validity Period has expired" in res_blocked_gift.json()["detail"]

        # 3. Initiating topup for Validity Period package (plan_30d) -> must SUCCEED!
        res_valid = client.post(
            "/v1/topup/initiate",
            headers=user_headers,
            json={"plan_id": "plan_30d", "purchase_type": "direct"},
        )
        assert res_valid.status_code == 200
        assert res_valid.json()["order_id"].startswith("TOPUP-")

    def test_claimed_reference_id_is_immediately_rejected(self, client, auth_headers):
        # 1. Create User 1 and User 2
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Merchant One", "custom_code": "PASS-M1", "duration_days": 30, "credits": 10},
        )
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Merchant Two", "custom_code": "PASS-M2", "duration_days": 30, "credits": 10},
        )

        # 2. User 1 creates order and pays
        res_ord1 = client.post("/v1/topup/initiate", headers={"X-Passcode": "PASS-M1"}, json={"plan_id": "plan_30d"})
        ord1_id = res_ord1.json()["order_id"]

        # Incoming SMS arrives
        client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": "Your HSBC Account ********1001 was credited with IPN inward transfer for EGP 30.00 from M1 with reference REF_DUPE_TEST."},
        )

        # User 1 verifies -> MATCHED
        res_ver1 = client.post(
            "/v1/topup/verify",
            headers={"X-Passcode": "PASS-M1"},
            json={"order_id": ord1_id, "reference_id": "REF_DUPE_TEST"}
        )
        assert res_ver1.json()["success"] is True
        assert res_ver1.json()["status"] == "MATCHED"

        # 3. User 2 creates a gift order and tries to reuse the SAME reference REF_DUPE_TEST
        res_ord2 = client.post("/v1/topup/initiate", headers={"X-Passcode": "PASS-M2"}, json={"plan_id": "plan_30d", "purchase_type": "gift"})
        ord2_id = res_ord2.json()["order_id"]

        res_ver2 = client.post(
            "/v1/topup/verify",
            headers={"X-Passcode": "PASS-M2"},
            json={"order_id": ord2_id, "reference_id": "REF_DUPE_TEST"}
        )
        assert res_ver2.json()["success"] is False
        assert res_ver2.json()["status"] == "REJECTED"
        assert "already been claimed" in res_ver2.json()["message"]

        # 4. Check Admin Purchases report: ord2_id must show status REJECTED
        res_rep = client.get("/v1/admin/purchases/filter", headers=auth_headers)
        items = res_rep.json()["items"]
        ord2_item = next(it for it in items if it["order_id"] == ord2_id)
        assert ord2_item["status"] == "REJECTED"

    def test_expired_reference_outside_window_is_rejected(self, client, auth_headers, db_session):
        from app.models import IncomingCredit, utc_now
        from datetime import timedelta

        # 1. User initiates order
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Merchant Three", "custom_code": "PASS-M3", "duration_days": 30, "credits": 10},
        )
        res_ord = client.post("/v1/topup/initiate", headers={"X-Passcode": "PASS-M3"}, json={"plan_id": "plan_30d"})
        ord_id = res_ord.json()["order_id"]

        # 2. Inject an unclaimed credit from 3 hours ago
        stale_credit = IncomingCredit(
            reference_id="REF_OLD_STALE",
            amount=30.00,
            status="UNCLAIMED",
            is_matched=False,
            received_at=utc_now() - timedelta(hours=3),
            sender_name="Old Sender",
            raw_message="Your HSBC Account was credited with 30 EGP ref REF_OLD_STALE",
        )
        db_session.add(stale_credit)
        db_session.commit()

        # 3. Attempt verify with stale reference -> Must be REJECTED!
        res_ver = client.post(
            "/v1/topup/verify",
            headers={"X-Passcode": "PASS-M3"},
            json={"order_id": ord_id, "reference_id": "REF_OLD_STALE"}
        )
        assert res_ver.json()["success"] is False
        assert res_ver.json()["status"] == "REJECTED"
        assert "outside the allowed" in res_ver.json()["message"]

    def test_expired_user_voucher_redemption_rules(self, client, auth_headers, db_session):
        from app.models import User, utc_now
        from datetime import timedelta

        # 1. Create a user and expire them
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Test Expired User", "custom_code": "PASS-VOUCH-EXP", "duration_days": 30, "credits": 10},
        )
        user_row = db_session.query(User).filter(User.name == "Test Expired User").first()
        assert user_row is not None
        user_row.subscription_expires_at = utc_now() - timedelta(days=2)
        db_session.commit()

        user_headers = {"X-Passcode": "PASS-VOUCH-EXP"}

        # 2. Admin generates a Credits-Only voucher (duration_days=0, credits=200, is_voucher=True)
        res_cred_vouch = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Gift Pack 200", "custom_code": "PASS-CRED-ONLY", "duration_days": 0, "credits": 200, "is_voucher": True},
        )
        assert res_cred_vouch.status_code == 201

        # Expired user attempts to redeem credits-only voucher -> MUST BE REJECTED with 400!
        res_redeem_fail = client.post(
            "/v1/passcodes/redeem",
            headers=user_headers,
            json={"passcode": "PASS-CRED-ONLY"}
        )
        assert res_redeem_fail.status_code == 400
        assert "requires an active subscription" in res_redeem_fail.json()["detail"]

        # Ensure no free 30 days was granted!
        db_session.refresh(user_row)
        assert user_row.subscription_expires_at < utc_now()

        # 3. Admin generates a Validity Renewal voucher (duration_days=60, credits=50, is_voucher=True)
        res_val_vouch = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Renewal 60 Days", "custom_code": "PASS-RENEW-60D", "duration_days": 60, "credits": 50, "is_voucher": True},
        )
        assert res_val_vouch.status_code == 201

        # Expired user redeems validity voucher -> MUST SUCCEED and reactivate account!
        res_redeem_ok = client.post(
            "/v1/passcodes/redeem",
            headers=user_headers,
            json={"passcode": "PASS-RENEW-60D"}
        )
        assert res_redeem_ok.status_code == 200
        assert res_redeem_ok.json()["is_subscription_valid"] is True

        # 4. Now that account has active validity, they CAN redeem the Credits-Only voucher!
        res_redeem_cred_ok = client.post(
            "/v1/passcodes/redeem",
            headers=user_headers,
            json={"passcode": "PASS-CRED-ONLY"}
        )
        assert res_redeem_cred_ok.status_code == 200
        assert res_redeem_cred_ok.json()["credits_balance"] >= 250

    def test_forwarder_heartbeat_and_telemetry(self, client, auth_headers, db_session):
        from app.models import User
        res_u = client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Live POS Merchant", "custom_code": "PASS-POS-01", "duration_days": 30, "credits": 50},
        )
        assert res_u.status_code == 201
        user_headers = {"X-Passcode": "PASS-POS-01"}

        res_hb = client.post(
            "/v1/forwarder/heartbeat",
            headers=user_headers,
            json={
                "battery": 88,
                "network": "WE 4G",
                "uptime": "5d 12h",
                "device": "Samsung Galaxy A52",
                "ping_ms": 32,
            }
        )
        assert res_hb.status_code == 200
        data = res_hb.json()
        assert data["success"] is True
        assert data["status"] == "ONLINE"
        assert data["battery"] == 88
        assert data["network"] == "WE 4G"

        user_row = db_session.query(User).filter(User.passcode == "PASS-POS-01").first()
        assert user_row.forwarder_battery == 88
        assert user_row.forwarder_status == "ONLINE"

    def test_livestream_feed_lockdown_grace_period_and_activation(self, client, auth_headers, db_session):
        from app.models import User, utc_now
        from datetime import timedelta

        # 1. Create a user without livestream
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Cashier Store", "custom_code": "PASS-CASHIER-01", "duration_days": 30, "credits": 50},
        )
        user_headers = {"X-Passcode": "PASS-CASHIER-01"}

        # 2. Before subscribing to Live Stream -> feed must be LOCKED
        res_feed_locked = client.get("/v1/livestream/feed", headers=user_headers)
        assert res_feed_locked.status_code == 200
        data_locked = res_feed_locked.json()
        assert data_locked["is_unlocked"] is False
        assert data_locked["in_grace_period"] is False

        # 3. Buy Live Stream package (plan_livestream) directly
        user_row = db_session.query(User).filter(User.passcode == "PASS-CASHIER-01").first()
        res_ord = client.post("/v1/topup/initiate", headers=user_headers, json={"plan_id": "plan_livestream"})
        assert res_ord.status_code == 200
        ord_id = res_ord.json()["order_id"]

        # Incoming SMS arrives
        client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": "Your HSBC Account ********1001 was credited with IPN transfer for EGP 100.00 from Cashier with ref REF_LIVE_TOPUP."},
        )

        # Verify order -> unlocks Live Stream!
        res_ver = client.post("/v1/topup/verify", headers=user_headers, json={"order_id": ord_id, "reference_id": "REF_LIVE_TOPUP"})
        assert res_ver.status_code == 200
        assert res_ver.json()["success"] is True

        # 4. Now feed must be UNLOCKED!
        # First verify unauthenticated call without shift token is blocked with 403 Forbidden (SEC-005)
        res_blocked = client.get("/v1/livestream/feed", headers=user_headers)
        assert res_blocked.status_code == 403

        # Unlock shift with Cashier PIN
        res_pin = client.post("/v1/user/verify-cashier-pin", headers=user_headers, json={"cashier_pin": user_row.cashier_pin})
        assert res_pin.status_code == 200
        user_headers["X-Shift-Token"] = res_pin.json()["shift_token"]

        res_feed_unlocked = client.get("/v1/livestream/feed", headers=user_headers)
        assert res_feed_unlocked.status_code == 200
        data_unlocked = res_feed_unlocked.json()
        assert data_unlocked["is_unlocked"] is True
        assert data_unlocked["in_grace_period"] is False

        # 5. Test Grace Period (30 days expired, but within 5 days grace)
        now = utc_now()
        db_session.refresh(user_row)
        user_row.livestream_expires_at = now - timedelta(days=2)
        user_row.livestream_grace_until = now + timedelta(days=3)
        db_session.commit()

        res_feed_grace = client.get("/v1/livestream/feed", headers=user_headers)
        assert res_feed_grace.status_code == 200
        data_grace = res_feed_grace.json()
        assert data_grace["is_unlocked"] is True
        assert data_grace["in_grace_period"] is True
        assert data_grace["grace_days_remaining"] >= 2

        # 6. Test completely expired after grace period
        user_row.livestream_expires_at = now - timedelta(days=7)
        user_row.livestream_grace_until = now - timedelta(days=2)
        db_session.commit()

        res_feed_expired = client.get("/v1/livestream/feed", headers=user_headers)
        assert res_feed_expired.status_code == 200
        assert res_feed_expired.json()["is_unlocked"] is False

    def test_livestream_read_unread_and_highlighting(self, client, auth_headers, db_session):
        from app.models import User, IncomingCredit, utc_now
        from datetime import timedelta

        # 1. Create user and grant livestream
        client.post(
            "/v1/admin/passcodes/generate",
            headers=auth_headers,
            json={"user_name": "Store Front", "custom_code": "PASS-STORE-99", "duration_days": 30, "credits": 50},
        )
        user_headers = {"X-Passcode": "PASS-STORE-99"}
        user_row = db_session.query(User).filter(User.passcode == "PASS-STORE-99").first()
        now = utc_now()
        user_row.livestream_expires_at = now + timedelta(days=30)
        user_row.livestream_grace_until = now + timedelta(days=35)
        db_session.commit()

        # 2. Add two incoming credits for this user
        c1 = IncomingCredit(
            user_id=user_row.id,
            amount=500.0,
            currency="EGP",
            reference_id="REF_TX_001",
            status="UNCLAIMED",
            is_matched=False,
            is_read=False,
            raw_message="Transfer of 500 EGP from Ahmed to QNB Ref REF_TX_001",
            received_at=now - timedelta(minutes=5),
        )
        c2 = IncomingCredit(
            user_id=user_row.id,
            amount=750.0,
            currency="EGP",
            reference_id="REF_TX_002",
            status="UNCLAIMED",
            is_matched=False,
            is_read=False,
            raw_message="Transfer of 750 EGP from Sarah to QNB Ref REF_TX_002",
            received_at=now - timedelta(minutes=1),
        )
        db_session.add_all([c1, c2])
        db_session.commit()

        # 3. Request livestream feed (requires cashier shift unlock)
        res_pin = client.post("/v1/user/verify-cashier-pin", headers=user_headers, json={"cashier_pin": user_row.cashier_pin})
        assert res_pin.status_code == 200
        user_headers["X-Shift-Token"] = res_pin.json()["shift_token"]

        res_feed = client.get("/v1/livestream/feed", headers=user_headers)
        assert res_feed.status_code == 200
        data = res_feed.json()
        assert len(data["items"]) >= 2
        assert data["unread_count"] >= 2

        # The newest transaction (c2, index 0) must have is_highlighted == True!
        newest_item = data["items"][0]
        assert newest_item["reference_id"] == "REF_TX_002"
        assert newest_item["is_highlighted"] is True
        assert newest_item["is_read"] is False

        # 4. Mark newest transaction as Read
        res_read = client.post(
            "/v1/livestream/mark-read",
            headers=user_headers,
            json={"credit_ids": [newest_item["id"]]}
        )
        assert res_read.status_code == 200
        assert res_read.json()["updated_count"] == 1

        # 5. Fetch feed again: c2 must now be is_read=True and NOT highlighted!
        res_feed2 = client.get("/v1/livestream/feed", headers=user_headers)
        item0 = res_feed2.json()["items"][0]
        assert item0["id"] == newest_item["id"]
        assert item0["is_read"] is True
        assert item0["is_highlighted"] is False

    def test_admin_forwarders_health_watchdog(self, client, auth_headers):
        res = client.get("/v1/admin/forwarders/health", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "online_count" in data
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_tier3_owner_gate_and_cashier_pin(self, client):
        # 1. Register a brand new merchant
        reg_res = client.post(
            "/v1/auth/register",
            json={
                "name": "Security Merchant",
                "email": "owner@securitystore.com",
                "phone": "01099998888",
                "account_ending": "5544",
            }
        )
        assert reg_res.status_code == 201
        reg_data = reg_res.json()
        assert reg_data["cashier_pin"] is not None
        assert len(reg_data["cashier_pin"]) == 6
        assert reg_data["cashier_pin"].isalnum()
        # Check 5-day free trial on registration
        assert reg_data["livestream_expires_at"] is not None
        assert reg_data["is_livestream_valid"] is True

        passcode = reg_data["passcode"]
        fwd_key = reg_data["forwarder_api_key"]
        original_pin = reg_data["cashier_pin"]
        user_headers = {"X-Passcode": passcode}

        # 2. Regular login with passcode -> forwarder_api_key is masked and cashier_pin is hidden!
        login_res = client.post("/v1/auth/passcode/login", json={"passcode": passcode})
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert "••••" in login_data["forwarder_api_key"]
        assert login_data["cashier_pin"] is None
        assert login_data["is_owner_unlocked"] is False

        # 3. Cashier tries to verify invalid owner key -> 403 Forbidden
        bad_gate = client.post(
            "/v1/user/verify-owner-key",
            headers=user_headers,
            json={"owner_key": "wrong_fwd_key"}
        )
        assert bad_gate.status_code == 403

        # 4. Owner verifies with correct Forwarder API Key -> 200 OK with unmasked profile & real cashier PIN!
        good_gate = client.post(
            "/v1/user/verify-owner-key",
            headers=user_headers,
            json={"owner_key": fwd_key}
        )
        assert good_gate.status_code == 200
        unmasked = good_gate.json()["user_profile"]
        assert unmasked["forwarder_api_key"] == fwd_key
        assert unmasked["cashier_pin"] == original_pin
        assert unmasked["is_owner_unlocked"] is True

        # 5. Owner updates cashier PIN to 'B987D6'
        pin_update = client.post(
            "/v1/user/cashier-pin",
            headers=user_headers,
            json={"owner_key": fwd_key, "new_cashier_pin": "B987D6"}
        )
        assert pin_update.status_code == 200
        assert pin_update.json()["user_profile"]["cashier_pin"] == "B987D6"

        # 6. Cashier verifies the new PIN 'B987D6' (also test case-insensitive lowercase 'b987d6')
        cashier_ver = client.post(
            "/v1/user/verify-cashier-pin",
            headers=user_headers,
            json={"cashier_pin": "b987d6"}
        )
        assert cashier_ver.status_code == 200
        assert cashier_ver.json()["success"] is True

        # 7. Old PIN fails
        old_ver = client.post(
            "/v1/user/verify-cashier-pin",
            headers=user_headers,
            json={"cashier_pin": original_pin}
        )
        assert old_ver.status_code == 403

    def test_admin_grant_livestream_and_dynamic_trials(self, client, auth_headers):
        # 1. Update dynamic trial settings as Admin
        res_set = client.post(
            "/v1/admin/settings",
            headers=auth_headers,
            json={
                "admin_key": auth_headers["X-API-Key"],
                "default_trial_days": 120,
                "default_livestream_trial_days": 14,
            }
        )
        assert res_set.status_code == 200
        assert res_set.json()["default_trial_days"] == 120
        assert res_set.json()["default_livestream_trial_days"] == 14

        # 2. Public config reflects dynamic settings
        res_cfg = client.get("/v1/portal/config")
        assert res_cfg.status_code == 200
        assert res_cfg.json()["default_trial_days"] == 120
        assert res_cfg.json()["default_livestream_trial_days"] == 14

        # 3. New merchant registers with dynamic trial values
        res_reg = client.post(
            "/v1/auth/register",
            json={
                "name": "Dynamic Trial Merchant",
                "email": "dynamic@trial.com",
            }
        )
        assert res_reg.status_code == 201
        m_data = res_reg.json()
        assert m_data["is_livestream_valid"] is True
        merchant_id = m_data["id"]

        # 4. Super Admin grants complimentary 45 days Live Stream session
        res_grant = client.post(
            f"/v1/admin/users/{merchant_id}/grant-livestream",
            headers=auth_headers,
            json={"days": 45, "reason": "SPECIAL_PROMOTION"}
        )
        assert res_grant.status_code == 200
        prof = res_grant.json()
        assert prof["is_livestream_valid"] is True
        assert prof["livestream_expires_at"] is not None

        # 5. Check user list endpoint returns livestream columns
        res_list = client.get("/v1/admin/users/list", headers=auth_headers)
        assert res_list.status_code == 200
        user_item = next(u for u in res_list.json()["users"] if u["id"] == merchant_id)
        assert user_item["livestream_expires_at"] is not None

        # 6. Admin adjusts live stream days via /v1/admin/users/adjust
        res_adj = client.post(
            "/v1/admin/users/adjust",
            headers=auth_headers,
            json={
                "user_id": merchant_id,
                "set_livestream_days": 60,
            }
        )
        assert res_adj.status_code == 200
        assert res_adj.json()["is_livestream_valid"] is True





