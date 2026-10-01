"""
Interactive Live Simulator for InstaPay Verification API.
Allows you to test SMS ingestion, Order Creation, and Payment Verification
directly from your computer without needing an Android phone.
"""

import time
import os
import sys
import requests

# Ensure proper encoding on Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.getenv("INSTAPAY_URL", "http://127.0.0.1:8001")
API_KEY = os.getenv("MASTER_API_KEY", "XAZAjxjhbCtSgiq7")

HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
}

SAMPLE_SMS_TEMPLATES = [
    {
        "bank": "NBE (البنك الأهلي المصري - عربي)",
        "sender": "NBE",
        "message": "تم تحويل مبلغ 1,500.00 جم لحسابكم المنتهي بـ 1234 من احمد محمد عبر شبكة المدفوعات اللحظية مرجع رقم IPN260822143000",
        "expected_amount": 1500.0,
        "expected_ref": "IPN260822143000",
    },
    {
        "bank": "CIB (البنك التجاري الدولي - عربي)",
        "sender": "CIB",
        "message": "تم استلام تحويل لحظي بمبلغ 450.00 ج.م من عمر خالد إلى حسابكم المنتهي بـ 5678. رقم المرجع IPN99887711",
        "expected_amount": 450.0,
        "expected_ref": "IPN99887711",
    },
    {
        "bank": "HSBC Egypt (English)",
        "sender": "HSBC",
        "message": "Your account ending in 9876 has been credited with EGP 2,250.00 on 22/08/2026 from TAREK HASSAN. Ref: IPN55443322 (IPN Inward Transfer)",
        "expected_amount": 2250.0,
        "expected_ref": "IPN55443322",
    },
    {
        "bank": "Banque Misr (بنك مصر - عربي)",
        "sender": "BANQUEMISR",
        "message": "إيداع تحويل لحظي IPN بمبلغ 800.00 جم بحسابك رقم ...4321 من سارة ابراهيم مرجع IPN77889900",
        "expected_amount": 800.0,
        "expected_ref": "IPN77889900",
    },
]


def print_banner():
    print("=" * 60)
    print("   INSTAPAY VERIFICATION MICROSERVICE - LIVE SIMULATOR")
    print("=" * 60)


def check_server_health():
    try:
        res = requests.get(f"{BASE_URL}/health", timeout=3)
        is_ok = (res.status_code == 200)
    except Exception as e:
        is_ok = False
        res = None

    if is_ok:
        print(f"[+] API Server is ONLINE and reachable at {BASE_URL}\n")
        return True
    else:
        print("[-] Could not connect to API Server. Make sure uvicorn is running:")
        print(f"    .\\.venv\\Scripts\\uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload\n")
        return False


def run_interactive_simulation():
    print("Choose a bank SMS template to simulate:")
    for i, t in enumerate(SAMPLE_SMS_TEMPLATES, 1):
        print(f"  {i}. {t['bank']} - Amount: {t['expected_amount']} EGP")
    print("  5. Custom SMS (Type your own message)")
    print("  6. Test Order Matching by Amount (Without knowing reference_id)")
    print("  0. Exit")

    choice = input("\nEnter choice [1-6]: ").strip()

    if choice == "0":
        return

    if choice in ["1", "2", "3", "4"]:
        selected = SAMPLE_SMS_TEMPLATES[int(choice) - 1]
        sms_text = selected["message"]
        sender = selected["sender"]
        amount = selected["expected_amount"]
        ref_id = selected["expected_ref"]
    elif choice == "5":
        sms_text = input("Enter raw SMS text: ").strip()
        sender = input("Enter sender ID (e.g. NBE, CIB): ").strip()
        amount = float(input("Enter expected order amount: ").strip())
        ref_id = None
    elif choice == "6":
        ts = int(time.time())
        ref_id = f"IPN_AUTO_{ts}"
        amount = 350.0
        sender = "NBE"
        sms_text = f"تم تحويل مبلغ {amount} جم لحسابكم المنتهي بـ 9900 من عميل تجريبي مرجع رقم {ref_id}"
        print(f"\n[Generated SMS]: {sms_text}")
    else:
        print("Invalid option.")
        return

    order_id = f"ORDER-{int(time.time())}"

    print("\n" + "-" * 50)
    print("STEP 1: Ingesting Bank SMS Webhook...")
    print("-" * 50)
    res_webhook = requests.post(
        f"{BASE_URL}/v1/webhook/sms",
        headers=HEADERS,
        json={"raw_message": sms_text, "sender": sender},
    )
    print(f"Status Code: {res_webhook.status_code}")
    print(f"Response: {res_webhook.json()}")

    if res_webhook.status_code != 201:
        print("\n[FAILED] Webhook ingestion failed. Aborting.")
        return

    print("\n" + "-" * 50)
    print(f"STEP 2: Creating Client Order (ID: {order_id}, Amount: {amount} EGP)...")
    print("-" * 50)
    order_payload = {"order_id": order_id, "amount": amount}
    if choice != "6" and ref_id:
        order_payload["reference_id"] = ref_id

    res_order = requests.post(
        f"{BASE_URL}/v1/orders/create",
        headers=HEADERS,
        json=order_payload,
    )
    print(f"Status Code: {res_order.status_code}")
    print(f"Response: {res_order.json()}")

    print("\n" + "-" * 50)
    print(f"STEP 3: Verifying Payment for Order {order_id}...")
    print("-" * 50)
    res_verify = requests.post(
        f"{BASE_URL}/v1/orders/verify",
        headers=HEADERS,
        json={"order_id": order_id},
    )
    print(f"Status Code: {res_verify.status_code}")
    verify_data = res_verify.json()
    print(f"Response: {verify_data}")

    if verify_data.get("verified") is True:
        print(f"\n[SUCCESS] Payment for order {order_id} was MATCHED & CLAIMED atomically!")
    else:
        print(f"\n[FAILED] Verification failed: {verify_data.get('message')}")


if __name__ == "__main__":
    print_banner()
    if check_server_health():
        while True:
            run_interactive_simulation()
            cont = input("\nWould you like to run another test? (y/n): ").strip().lower()
            if cont != "y":
                print("Exiting simulator. Goodbye!")
                break
