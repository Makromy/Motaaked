import pytest
from datetime import date, timedelta
from app.models import User, CreditTransaction, utc_now

@pytest.fixture
def audit_merchant(db_session):
    now = utc_now()
    user = User(
        name="Audit Test Merchant",
        email="audit_merchant@test.com",
        passcode="PASS-AUDIT-TEST",
        account_ending="7788",
        role="user",
        subscription_expires_at=now + timedelta(days=30),
        credits_balance=288,
        free_credits=100,
        free_credits_cycle_start=now,
        pass_credits=0,
        lifetime_credits=188,
        is_active=True,
        created_at=now - timedelta(days=3),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # Tx 1: Initial Allocation +100 (Balance: 0 -> 100)
    tx1 = CreditTransaction(
        user_id=user.id,
        amount=100,
        operation_type="PASSCODE_ALLOCATION",
        reference_id="PASS-AUDIT-TEST",
        created_at=now - timedelta(days=3),
    )
    # Tx 2: Search Lookup -1 (Balance: 100 -> 99)
    tx2 = CreditTransaction(
        user_id=user.id,
        amount=-1,
        operation_type="SEARCH_LOOKUP",
        reference_id="IPN11223344",
        created_at=now - timedelta(days=2),
    )
    # Tx 3: Vault Reveal -10 (Balance: 99 -> 89)
    tx3 = CreditTransaction(
        user_id=user.id,
        amount=-10,
        operation_type="VAULT_UNLOCK",
        reference_id="IPN11223344",
        created_at=now - timedelta(days=1),
    )
    # Tx 4: Direct Top-Up +200 (Balance: 89 -> 289)
    tx4 = CreditTransaction(
        user_id=user.id,
        amount=200,
        operation_type="TOPUP_DIRECT_ACTIVATION",
        reference_id="TOPUP-AUDIT-01",
        created_at=now - timedelta(hours=12),
    )
    # Tx 5: Search Lookup -1 (Balance: 289 -> 288)
    tx5 = CreditTransaction(
        user_id=user.id,
        amount=-1,
        operation_type="SEARCH_LOOKUP",
        reference_id="NBE99887766",
        created_at=now - timedelta(hours=1),
    )
    db_session.add_all([tx1, tx2, tx3, tx4, tx5])
    db_session.commit()
    return user

class TestCreditAuditExplorer:

    def test_credit_audit_sequential_balance_calculation(self, client, auth_headers, audit_merchant):
        user = audit_merchant

        res = client.get(f"/v1/admin/users/{user.id}/credit-audit", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()

        assert data["user_id"] == user.id
        assert data["user_name"] == "Audit Test Merchant"
        assert data["current_balance"] == 288
        assert data["total_movements"] == 5
        assert data["total_added"] == 300
        assert data["total_deducted"] == 12

        items = data["items"] # Newest first: tx5, tx4, tx3, tx2, tx1
        assert len(items) == 5

        # Check Tx 5 (Newest)
        assert items[0]["operation_type"] == "SEARCH_LOOKUP"
        assert items[0]["amount"] == -1
        assert items[0]["balance_before"] == 289
        assert items[0]["balance_after"] == 288

        # Check Tx 4
        assert items[1]["operation_type"] == "TOPUP_DIRECT_ACTIVATION"
        assert items[1]["amount"] == 200
        assert items[1]["balance_before"] == 89
        assert items[1]["balance_after"] == 289

        # Check Tx 3
        assert items[2]["operation_type"] == "VAULT_UNLOCK"
        assert items[2]["amount"] == -10
        assert items[2]["balance_before"] == 99
        assert items[2]["balance_after"] == 89

        # Check Tx 2
        assert items[3]["operation_type"] == "SEARCH_LOOKUP"
        assert items[3]["amount"] == -1
        assert items[3]["balance_before"] == 100
        assert items[3]["balance_after"] == 99

        # Check Tx 1 (Oldest)
        assert items[4]["operation_type"] == "PASSCODE_ALLOCATION"
        assert items[4]["amount"] == 100
        assert items[4]["balance_before"] == 0
        assert items[4]["balance_after"] == 100

    def test_credit_audit_filtering(self, client, auth_headers, audit_merchant):
        user = audit_merchant

        # Filter by operation_type=VAULT_UNLOCK
        res = client.get(f"/v1/admin/users/{user.id}/credit-audit?operation_type=VAULT_UNLOCK", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total_movements"] == 1
        assert data["items"][0]["operation_type"] == "VAULT_UNLOCK"
        assert data["items"][0]["balance_before"] == 99
        assert data["items"][0]["balance_after"] == 89

        # Filter by search keyword
        res_search = client.get(f"/v1/admin/users/{user.id}/credit-audit?search=NBE99887766", headers=auth_headers)
        assert res_search.status_code == 200
        data_s = res_search.json()
        assert data_s["total_movements"] == 1
        assert data_s["items"][0]["reference_id"] == "NBE99887766"

    def test_credit_audit_csv_export(self, client, auth_headers, audit_merchant):
        user = audit_merchant

        res = client.get(f"/v1/admin/users/{user.id}/credit-audit/export", headers=auth_headers)
        assert res.status_code == 200
        assert "text/csv" in res.headers["content-type"]
        assert "attachment; filename=" in res.headers["content-disposition"]
        
        csv_text = res.text
        assert "MERCHANT CREDIT AUDIT STATEMENT" in csv_text
        assert "PASS-AUDIT-TEST" in csv_text
        assert "Balance Before" in csv_text
        assert "Balance After" in csv_text
        assert "SEARCH_LOOKUP" in csv_text
        assert "VAULT_UNLOCK" in csv_text

    def test_credit_audit_security(self, client, audit_merchant):
        user = audit_merchant

        # Unauthenticated request
        res = client.get(f"/v1/admin/users/{user.id}/credit-audit")
        assert res.status_code in [401, 403]
