from datetime import timedelta
import pytest
from app.models import utc_now, WatchedReference, IncomingCredit


class TestCycle2Watchlist:

    def test_watch_reference_pending_creation(self, client):
        response = client.post(
            "/v1/watchlist/watch",
            json={"reference_id": "IPN_PENDING_001", "session_id": "test_session_1", "timeout_minutes": 30},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["reference_id"] == "IPN_PENDING_001"
        assert data["status"] == "PENDING"
        assert data["seconds_remaining"] > 1700
        assert data["matched_credit"] is None

    def test_watch_reference_already_exists_instant_match(self, client, auth_headers):
        # 1. Ingest SMS first
        sms = "تم تحويل مبلغ 1200 جم لحسابكم من طارق أحمد مرجع: IPN_INSTANT_MATCH"
        client.post("/v1/webhook/sms", headers=auth_headers, json={"raw_message": sms})

        # 2. Watch reference -> should match immediately
        res_watch = client.post(
            "/v1/watchlist/watch",
            json={"reference_id": "IPN_INSTANT_MATCH", "session_id": "test_session_2"},
        )
        assert res_watch.status_code == 201
        data = res_watch.json()
        assert data["status"] == "MATCHED"
        assert data["seconds_remaining"] == 0
        assert data["matched_credit"]["amount"] == 1200.0
        assert data["matched_credit"]["reference_id"] == "IPN_INSTANT_MATCH"

    def test_live_sms_arrival_auto_resolves_pending_watchlist(self, client, auth_headers):
        session_id = "live_tracker_session"

        # 1. User starts watching a pending reference
        res_watch = client.post(
            "/v1/watchlist/watch",
            json={"reference_id": "REF_IN_TRANSIT_777", "session_id": session_id},
        )
        assert res_watch.status_code == 201
        assert res_watch.json()["status"] == "PENDING"

        # 2. Poll watchlist -> still PENDING
        res_poll1 = client.post(
            "/v1/watchlist/poll",
            json={"session_id": session_id},
        )
        assert res_poll1.status_code == 200
        data1 = res_poll1.json()
        assert data1["total_pending"] == 1
        assert data1["total_matched"] == 0
        assert data1["items"][0]["status"] == "PENDING"

        # 3. Bank SMS arrives on the server via webhook!
        sms = "Your HSBC Account ********1001 was credited with IPN inward transfer for EGP 850.00 from HOSSAM with reference REF_IN_TRANSIT_777."
        res_sms = client.post(
            "/v1/webhook/sms",
            headers=auth_headers,
            json={"raw_message": sms},
        )
        assert res_sms.status_code == 201

        # 4. Next poll from user's screen -> INSTANTLY MATCHED!
        res_poll2 = client.post(
            "/v1/watchlist/poll",
            json={"session_id": session_id},
        )
        assert res_poll2.status_code == 200
        data2 = res_poll2.json()
        assert data2["total_pending"] == 0
        assert data2["total_matched"] == 1
        matched_item = data2["items"][0]
        assert matched_item["status"] == "MATCHED"
        assert matched_item["matched_at"] is not None
        assert matched_item["matched_credit"]["amount"] == 850.0

    def test_multi_reference_batch_monitoring(self, client, auth_headers):
        session_id = "multi_track_sess"

        # User searches 3 separate reference IDs concurrently
        client.post("/v1/watchlist/watch", json={"reference_id": "REF_MULTI_1", "session_id": session_id})
        client.post("/v1/watchlist/watch", json={"reference_id": "REF_MULTI_2", "session_id": session_id})
        client.post("/v1/watchlist/watch", json={"reference_id": "REF_MULTI_3", "session_id": session_id})

        # All 3 are pending
        res_poll1 = client.post("/v1/watchlist/poll", json={"session_id": session_id})
        assert res_poll1.json()["total_pending"] == 3

        # SMS arrives only for REF_MULTI_2
        sms2 = "تم تحويل مبلغ 400 جم لحسابكم من وائل مرجع: REF_MULTI_2"
        client.post("/v1/webhook/sms", headers=auth_headers, json={"raw_message": sms2})

        # Poll reflects 1 MATCHED, 2 PENDING
        res_poll2 = client.post("/v1/watchlist/poll", json={"session_id": session_id})
        data2 = res_poll2.json()
        assert data2["total_matched"] == 1
        assert data2["total_pending"] == 2

        statuses = {item["reference_id"]: item["status"] for item in data2["items"]}
        assert statuses["REF_MULTI_1"] == "PENDING"
        assert statuses["REF_MULTI_2"] == "MATCHED"
        assert statuses["REF_MULTI_3"] == "PENDING"

    def test_auto_expiration_of_timed_out_watchers(self, client, db_session):
        # Create an expired watch in DB (40 minutes ago)
        past_time = utc_now() - timedelta(minutes=40)
        expired_watch = WatchedReference(
            session_id="timeout_session",
            reference_id="REF_TIMED_OUT",
            status="PENDING",
            created_at=past_time,
            expires_at=past_time + timedelta(minutes=35),  # expired 5 minutes ago
        )
        db_session.add(expired_watch)
        db_session.commit()

        # Polling triggers auto-cleanup after 35 minutes
        res_poll = client.post(
            "/v1/watchlist/poll",
            json={"session_id": "timeout_session"},
        )
        assert res_poll.status_code == 200
        data = res_poll.json()
        assert data["total_pending"] == 0
        # Automatically pruned from live Tab 1 screen
        assert len(data["items"]) == 0

    def test_dismiss_watched_reference(self, client):
        session_id = "dismiss_session"
        res_watch = client.post(
            "/v1/watchlist/watch",
            json={"reference_id": "REF_DISMISS_TEST", "session_id": session_id},
        )
        watch_id = res_watch.json()["id"]

        # Active check shows 1 item
        res_active1 = client.get(f"/v1/watchlist/active?session_id={session_id}")
        assert len(res_active1.json()["items"]) == 1

        # Dismiss card
        res_dismiss = client.post(
            "/v1/watchlist/dismiss",
            json={"watch_id": watch_id},
        )
        assert res_dismiss.status_code == 200
        assert res_dismiss.json()["success"] is True

        # Active check now shows 0 items
        res_active2 = client.get(f"/v1/watchlist/active?session_id={session_id}")
        assert len(res_active2.json()["items"]) == 0
