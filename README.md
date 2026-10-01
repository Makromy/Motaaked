# Motaaked (متأكد) — Real-Time InstaPay Transactions Verification Through Official Bank SMS

[![Automated Tests](https://img.shields.io/badge/tests-182%20passed-brightgreen.svg)](tests/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker&logoColor=white)](docker-compose.yml)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![License: BSL 1.1](https://img.shields.io/badge/License-BSL%201.1-orange.svg)](LICENSE)

> **Automated bank SMS reconciliation, real-time audio/visual payment alerts for cashiers & live broadcasters, and 100% fraud-proof screenshot protection.**

---

### 🌐 Ready-Made Merchant Solution

> **Want to start accepting verified InstaPay payments immediately without setting up your own server?**  
> Access our live ready-made cloud portal:  
> 🔗 **[https://insta.saf7etna.dpdns.org/](https://insta.saf7etna.dpdns.org/)**  
> Create your merchant account, connect your forwarder phone, and start verifying customer transfers in under 3 minutes!

---

## ⚡ The Core Problem: The Blind "Green Flag Screenshot"

Accepting direct consumer-to-consumer bank transfers via **InstaPay (IPN)** is the fastest-growing payment method in Egypt. However, physical merchants, POS cashiers, and live sellers face a major vulnerability:

* **The "Green Flag" Screenshot Trap:** Customers show a smartphone screenshot displaying a green checkmark / successful transfer. The merchant has **zero ways to validate** whether that image is real, photoshopped, altered, or a reused screenshot from an older transfer.
* **Operational Disruption:** Store cashiers cannot see actual incoming bank alerts without calling the owner or logging into the owner's private bank account.
* **Owner Privacy:** Business owners want their cashiers to verify transactions without exposing bank account balances, reserves, or admin credentials to staff.

---

## 🎯 Two Solutions Tailored to Your Business Scale

Motaaked eliminates human guesswork by transforming incoming bank SMS notifications into an automated, fraud-proof verification terminal:

### 1. 🔍 Freemium Tier: Manual Reference Search (Credit-Based)
*Ideal for small merchants, emerging businesses, and low-to-medium transaction volumes:*
* **How It Solves the Pain:** Instead of blindly trusting a customer's screenshot with a green flag, the cashier asks for the **Bank Reference Number** and searches the live database. Motaaked validates it against real, encrypted bank SMS records in seconds.
* **Business Model (Hosted Cloud Portal):**
  * Every merchant receives **free monthly search credits** upon registration.
  * Search and validate real bank reference IDs 100% for free until your monthly credits are consumed.
  * Flexible credit top-up packs are available when you need more volume.
  *(Note: Credits apply to the hosted cloud solution; self-hosted open-source users have full control over their own limits).*

### 2. ⚡ Premium Tier: Hands-Free LiveStream Screen (Subscription-Based)
*Engineered for high-volume retail stores, busy supermarket cashiers, and fast-paced live stream broadcasters (TikTok Live, Facebook Live, Instagram Live):*
* **How It Solves the Pain:** High-volume sellers don't have time to ask for reference numbers, type 10 digits into a search bar, and click search for every customer.
* **The Hands-Free Workflow:** Simply open the **Live Stream Screen** on any phone, tablet, or monitor at your checkout counter or streaming studio. Incoming bank transfers pop up automatically in real-time the exact second the bank SMS arrives — showing the sender's name, the exact amount, and the time, accompanied by an instant audible chime! No typing, no searching — just glance, hear the chime, see the green card, and hand over the product immediately.
* **Business Model (Hosted Cloud Portal):**
  * Available as a **premium monthly subscription** with validity period tracking and generous grace periods.
  * Perfect for busy cashiers who need completely hands-free, zero-touch verification.
  *(Note: Subscription applies to the hosted cloud solution; self-hosters running their own server have full access).*

---

## 🛡️ How Motaaked Works

```
Customer Transfers via InstaPay App (to Merchant Handle)
                      │
                      ▼
Official Bank SMS Alert Arrives on Merchant Phone (SIM)
                      │
                      ▼
Android Forwarder Pushes SMS Payload to Motaaked Gateway
                      │
                      ▼
Regex Engine Extracts: Amount, Bank SMS Ref ID & Account Ending
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
   [LiveStream POS Feed]    [Atomic Match Engine]
   • Real-time screen popup  • Verifies exact Reference ID
   • Instant Audio Chime     • Locks credit (Anti-Double-Spend)
   • Hands-free verification • Redacts sensitive bank balances
```

### Key Capabilities for POS & Live Streamers

1. **Zero-Trust Screenshot Policy**:
   Motaaked verifies transactions **strictly and exclusively** against the **Bank SMS Reference ID** extracted from official telecom SMS messages sent directly by Egyptian banks. Customer screenshots are never trusted.

2. **Hands-Free LiveStream POS Screen & Sound Alerts**:
   Open the **Live Stream Screen** on any tablet, phone, or laptop facing the cashier or streamer. The instant an SMS arrives:
   * A prominent visual card appears displaying the exact amount, sender name, and bank.
   * An **audible chime / sound alert** triggers immediately, letting the live host or cashier know the money is in the bank without typing or searching for reference numbers.

3. **Atomic Anti-Double-Spend Protection**:
   Every incoming bank credit is sealed with advisory database row locks. A single Bank SMS Reference ID can only be claimed **once**. Any attempt to reuse the same transfer reference across multiple purchases is rejected instantly.

4. **Cashier PIN & Vault Isolation**:
   Cashiers authenticate using a simple **4–6 digit Cashier PIN**. Sensitive financial details (available bank balance, credit limits) are automatically redacted from SMS alerts before display, protecting owner privacy.

5. **Camera Barcode & OCR Scanner**:
   Cashiers can also use their device camera to scan customer transfer reference codes directly, eliminating manual typing errors during busy checkout shifts.

6. **📱 The Telecom Bridge: Open-Source Android SMS Gateway**:
   Because Egyptian banks and InstaPay do not offer open public merchant webhooks, Motaaked uses a dedicated Android device (equipped with your business SIM card) as your private, secure telecom listener.
   * **Open-Source Android App:** [android_income_sms_gateway_webhook](https://github.com/bogkonstantin/android_income_sms_gateway_webhook) *(Free, Open-Source & Non-Custodial)* or MacroDroid.
   * **How It Connects to Your Server:**
     1. Install the APK on any Android phone receiving your bank SMS notifications.
     2. Configure a Webhook (HTTP POST) destination pointing to your server:
        `https://your-domain.com/v1/webhook/sms`
     3. Add your merchant forwarder key header:
        `X-Forwarder-Key: YOUR_MERCHANT_KEY`
     4. **Privacy Whitelisting (100% Personal Privacy):** Keep personal messages 100% confidential by filtering what gets forwarded:
        * **Filter by Sender:** Whitelist designated Egyptian bank sender names or shortcodes (e.g., `CIB`, `NBE`, `BM`, `QNB`, `AAIB`, `HSBC`, `AlexBank`).
        * **Filter by Message Text:** A single regex covers both directions:
          * **Forward only matching messages** — enter the keyword(s) directly. `IPN inward transfer` forwards any message containing *"IPN inward transfer"*; `IPN|inward transfer` forwards messages containing either phrase.
          * **Forward everything except matching messages** — use a negative lookahead. `(?s)^(?!.*OTP)` forwards every message that does not contain *"OTP"*; `(?si)^(?!.*(spam|promo))` excludes (case-insensitively) anything containing *"spam"* or *"promo"*. The leading `(?s)` makes `.` span newlines so a keyword on any line of a multi-line SMS is caught.
   * **Zero-Downtime Heartbeat & Watchdog:** The forwarder app sends a periodic telemetry heartbeat to `/v1/telemetry/heartbeat`, reporting phone battery levels and network vitality. Cashiers and streamers are alerted on the Live Stream screen if the phone needs recharging or loses Wi-Fi connection.

---

## 🐳 Easy VPS & Docker Deployment

Motaaked is fully containerized and production-ready. You can deploy it on any Linux VPS (Ubuntu, Debian, CentOS, or aaPanel) in **less than 2 minutes**.

### 1. Automated One-Click Deployment (`deploy.sh`)
```bash
# Clone the repository
git clone https://github.com/Makromy/Motaaked.git
cd Motaaked

# Run the automated deployment script
chmod +x deploy.sh
./deploy.sh
```

The script automatically:
* Verifies Docker & Docker Compose installation
* Generates `.env` from `.env.example`
* Configures persistent `./data` storage with correct permissions
* Builds the optimized container and starts it in the background (`restart: unless-stopped`)
* Runs health check validation against `http://127.0.0.1:8000/health`

### 2. Manual Docker Compose Deployment
```bash
# 1. Setup environment file
cp .env.example .env
nano .env   # Set your MASTER_API_KEY

# 2. Start container
docker compose up -d --build

# 3. Check live logs
docker logs -f instapay-portal
```

### Production Architecture Highlights
* **Persistent Storage**: SQLite database and configuration persist safely under `./data` across container rebuilds.
* **Low Resource Footprint**: Optimized resource limits (runs smoothly on a **1 vCPU / 512MB RAM** VPS).
* **Nginx / aaPanel Reverse Proxy Friendly**: The container listens securely on `127.0.0.1:8000`, ready to be proxied behind your Nginx reverse proxy with free Let's Encrypt SSL.

---

## 🧪 E-Commerce Integrations (Early Stage / Beta Notice)

While Motaaked provides a lightweight, session-based Drop-In Modal Widget (`static/js/motaaked-checkout.js`) and REST APIs for external checkout sessions, **e-commerce framework plugins (WooCommerce, Shopify, Laravel, etc.) are in an early community testing stage**.

We encourage framework developers, community contributors, and technical merchants to test, review, and extend these integrations at their own responsibility.

📖 **For architecture details, REST endpoint schemas, and code integration patterns, read the:**  
👉 **[Motaaked - Developer Integration Guide & E-Commerce Framework Manual](DEVELOPER_INTEGRATION_GUIDE.md)**

---

## 🏛️ Supported Egyptian Banks & Regex Engine

Motaaked's high-speed parsing engine (`app/parser.py`) supports official Arabic and English inbound SMS formats from major Egyptian financial institutions, including:

* National Bank of Egypt (NBE / البنك الأهلي المصري)
* Commercial International Bank (CIB / البنك التجاري الدولي)
* Banque Misr (بنك مصر)
* QNB Alahli (بنك قطر الوطني)
* HSBC Egypt
* Arab African International Bank (AAIB)
* Abu Dhabi Islamic Bank (ADIB)
* Bank of Alexandria (AlexBank)
* Banque du Caire (بنك القاهرة)
* Faisal Islamic Bank & others

---

## 📁 Repository Structure

```
instapay/
├── app/
│   ├── main.py             # FastAPI REST endpoints & WebSocket feeds
│   ├── parser.py           # Multi-bank Arabic/English SMS regex engine
│   ├── services.py         # Atomic verification engine & double-spend protection
│   ├── auth.py             # Multi-tier merchant API key & Cashier PIN security
│   ├── models.py           # SQLAlchemy database models & Pydantic schemas
│   ├── database.py         # Database session & transaction isolation
│   ├── config.py           # Environment settings (Pydantic BaseSettings)
│   └── email_service.py    # SMTP alerts & trouble ticketing dispatch
├── static/
│   ├── index.html          # Bilingual Merchant Dashboard & LiveStream POS Feed
│   ├── checkout_embed.html # Embeddable payment iframe
│   └── js/
│       └── motaaked-checkout.js # 2-Line Drop-In Modal SDK
├── tests/                  # 182 automated unit, security & integration tests
├── Dockerfile              # Production container build
├── docker-compose.yml      # Multi-container orchestration
├── deploy.sh               # One-click Linux VPS deployment script
├── DEVELOPER_INTEGRATION_GUIDE.md # Comprehensive developer API & framework manual
└── README.md
```

---

## 🚀 Quick Setup & Self-Hosting (Without Docker)

### Prerequisites
* Python 3.11+
* SQLite (default) or PostgreSQL

### 1. Clone & Setup Environment
```bash
git clone https://github.com/Makromy/Motaaked.git
cd Motaaked
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```ini
MASTER_API_KEY=your_secure_master_super_admin_key_here
DATABASE_URL=sqlite:///./instapay.db
MATCH_WINDOW_MINUTES=30
ENVIRONMENT=production
```

### 3. Run Development Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
* **Merchant & Cashier Portal:** `http://localhost:8000/`
* **LiveStream Terminal:** Open the dashboard and navigate to the **Live Stream** tab.

### 4. Run Automated Test Suite
```bash
python -m pytest -s tests/
```
All **182 unit, security, and integration tests** must pass cleanly.

---

## ⚖️ Open-Source License & Terms of Use (BSL 1.1)

Motaaked is distributed under the **Business Source License 1.1 (BSL 1.1)**.

### ✅ Allowed (Permitted Freely without Royalty)
* **Free Self-Hosting:** Deploy and run Motaaked on your own VPS or private servers to verify payments for your own business, physical shops, or live streams at zero licensing cost.
* **Learning & Research:** Read, audit, inspect, and learn from the codebase.
* **Security Auditing:** Conduct penetration tests, code security reviews, and vulnerability assessments.
* **Plugin & SDK Development:** Build, publish, and contribute open-source integration plugins and SDKs to connect other platforms to Motaaked.

### 🚫 Prohibited (Forbidden without Written Authorization)
* **White-Labeling & Reselling:** White-labeling, rebranding, or reselling the software (or modified versions) to third parties as a commercial product.
* **Competing Commercial SaaS:** Operating a hosted, managed, multi-tenant payment verification gateway or Software-as-a-Service (SaaS) in commercial competition with the Licensor.
* **Removing Attribution:** Stripping or altering author copyright notices or attribution notices.

### 🔄 Open-Source Transition
On **January 1, 2030**, the license automatically converts to the **GNU General Public License v3.0 (GPL-3.0-or-later)**.

### 💼 Commercial Licensing & White-Label Partnerships
Contact **Haitham Refaat** (`saf7etna@gmail.com`) for enterprise white-label licenses and commercial partnership agreements.

