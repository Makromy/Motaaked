# Motaaked - Developer Integration Guide & E-Commerce Framework Manual

> **CRITICAL VERIFICATION PRINCIPLE**:  
> Motaaked verifies payments **strictly and exclusively** via the **Bank SMS Reference ID** extracted from official bank SMS notifications delivered to the merchant's forwarder phone.  
> **NEVER** prompt the customer for or match against the reference number or transaction ID displayed on the customer's InstaPay mobile app screenshot. Screenshots can be altered, faked, or reused. The Bank SMS Reference ID guarantees 100% fraud protection and atomic ledger reconciliation.

---

## Table of Contents
1. [Architecture & System Flow](#1-architecture--system-flow)
2. [Authentication & API Key Management](#2-authentication--api-key-management)
3. [The Core Verification Model: Bank SMS Reference ID](#3-the-core-verification-model-bank-sms-reference-id)
4. [E-Commerce Integration Options Overview](#4-e-commerce-integration-options-overview)
5. [Option 1: Universal 2-Line Drop-In Modal Widget (`motaaked-checkout.js`)](#5-option-1-universal-2-line-drop-in-modal-widget-motaaked-checkoutjs)
6. [Option 2: WooCommerce & WordPress](#6-option-2-woocommerce--wordpress)
7. [Option 3: Shopify Integration (Draft Orders API + Liquid)](#7-option-3-shopify-integration-draft-orders-api--liquid)
8. [Option 4: Laravel Framework (PHP)](#8-option-4-laravel-framework-php)
9. [Option 5: Node.js & Express.js](#9-option-5-nodejs--expressjs)
10. [Option 6: React & Next.js (SPA, Pages & App Router)](#10-option-6-react--nextjs-spa-pages--app-router)
11. [Option 7: Learning Platforms (LearnDash LMS & Moodle)](#11-option-7-learning-platforms-learndash-lms--moodle)
12. [Option 8: Pure PHP (cURL / Backend Proxy)](#12-option-8-pure-php-curl--backend-proxy)
13. [Option 9: Python (FastAPI, Django & Flask)](#13-option-9-python-fastapi-django--flask)
14. [Core REST API Reference](#14-core-rest-api-reference)
15. [Comprehensive E-Commerce Q&A / FAQ](#15-comprehensive-e-commerce-qa--faq)

---

## 1. Architecture & System Flow

Motaaked acts as a secure, decentralized payment gateway bridge between Egypt's Instant Payment Network (IPN / InstaPay) and modern e-commerce web applications.

```mermaid
sequenceDiagram
    autonumber
    actor Customer as Customer (Shopper / Student)
    participant Store as Merchant Store / E-Commerce App
    participant Gateway as Motaaked API Gateway
    actor MerchantPhone as Merchant Android Phone (Forwarder)
    actor Bank as Egyptian Bank / IPN

    Customer->>Store: 1. Checkout (Select "InstaPay Direct")
    Store->>Gateway: 2. POST /v1/orders/create (Order ID, Amount, Description)
    Gateway-->>Store: 3. Return Order Confirmation & Payment Handle (IPA)
    Store-->>Customer: 4. Display InstaPay Handle, Amount & SMS Reference ID field (or Drop-In Modal)
    Customer->>Bank: 5. Sends transfer via InstaPay App to Merchant Handle
    Bank->>MerchantPhone: 6. Bank sends official SMS confirmation (Contains Amount & SMS Reference ID)
    MerchantPhone->>Gateway: 7. SMS Forwarder posts encrypted SMS payload via Webhook
    Gateway->>Gateway: 8. Regex parser extracts Amount, SMS Reference ID & Bank; marks UNCLAIMED
    Customer->>Store: 9. Enters Bank SMS Reference ID from their transfer alert
    Store->>Gateway: 10. POST /v1/orders/verify (Order ID, Amount, SMS Reference ID)
    Gateway->>Gateway: 11. Atomic match: checks SMS Ref ID + Amount (marks CLAIMED)
    Gateway-->>Store: 12. Returns { verified: true, status: "MATCHED", matched_at: "..." }
    Store-->>Customer: 13. Instant Order Fulfillment / Course Access Granted!
```

---

## 2. Authentication & API Key Management

All server-to-server requests to Motaaked require authentication using your **Merchant API Key**.

| Header Name | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `X-API-Key` | String | Merchant API key generated in the portal | `mk_live_9b4e78a3c1f20d65e4...` |
| `Content-Type` | String | JSON request body | `application/json` |

> **Security Tip**: Never expose your `X-API-Key` directly in client-side HTML or public browser code. Always route verification calls through your backend server or use temporary, scoped checkout sessions (`POST /v1/checkout/session`).

---

## 3. The Core Verification Model: Bank SMS Reference ID

### Why Bank SMS Reference ID?
1. **Zero-Trust Security**: Anyone can edit an image in Photoshop to generate a fake green InstaPay receipt with arbitrary amounts and names.
2. **Bank Authorization Authority**: Bank SMS messages come directly from the authorized banking core (NBE, CIB, Banque Misr, QNB, AAIB, HSBC, etc.) and contain an immutable reference number.
3. **Automated Reconciliation**: The Bank SMS Reference ID matches the merchant's electronic bank statement line by line.

```
+-----------------------------------------------------------------------------------+
|  [SAMPLE OFFICIAL BANK SMS]                                                       |
|  "تم تحويل مبلغ 450.00 جم من حسابكم إلى تاجر إنستاباي بنجاح. رقم المرجع: 240923000123"|
|                                                          ^^^^^^^^^^^^^^^^^^^^^^   |
|                                                          = BANK SMS REFERENCE ID  |
+-----------------------------------------------------------------------------------+
```

---

## 4. E-Commerce Integration Options Overview

Motaaked provides integration paths designed for every architecture:

| Solution | Best For | Technical Complexity | Typical Setup Time |
| :--- | :--- | :--- | :--- |
| **Universal Drop-In Modal** | Any website, custom carts, landings | ★☆☆☆☆ (2 lines of code) | 5 minutes |
| **WooCommerce Plugin** | WordPress online stores | ★☆☆☆☆ (No-code / upload) | 5 minutes |
| **Shopify Integration** | Shopify merchants | ★★☆☆☆ (Snippet + Backend) | 20 minutes |
| **Laravel Package** | PHP / Laravel enterprise apps & LMS | ★★☆☆☆ (Composer / Facade) | 15 minutes |
| **Node.js / Express** | JavaScript / TypeScript backends | ★★☆☆☆ (npm / middleware) | 15 minutes |
| **React / Next.js SDK** | Headless storefronts, Jamstack | ★★☆☆☆ (Component & Hook) | 15 minutes |
| **LearnDash / Moodle** | Educational portals & universities | ★☆☆☆☆ (WordPress / LMS) | 10 minutes |
| **Pure PHP / cURL** | Traditional PHP ecommerce | ★★☆☆☆ (Single file proxy) | 15 minutes |
| **Python SDK** | FastAPI, Django, Flask | ★★☆☆☆ (Async/Sync requests) | 15 minutes |

---

## 5. Option 1: Universal 2-Line Drop-In Modal Widget (`motaaked-checkout.js`)

The **Universal Drop-In Modal** is a zero-dependency, self-contained JavaScript widget. It creates a responsive, high-converting checkout modal with a 15-minute countdown, InstaPay handle copy button, Arabic/English RTL support, and automated polling.

### Step 1: Backend Creates a Checkout Session
Your backend creates a temporary 15-minute checkout session:

```bash
POST /v1/checkout/session
X-API-Key: YOUR_MERCHANT_API_KEY
Content-Type: application/json

{
  "order_id": "ORD-78901",
  "amount": 250.00,
  "currency": "EGP",
  "customer_name": "Karim Farouk",
  "customer_email": "karim@example.com",
  "customer_phone": "01012345678",
  "description": "Premium Cotton T-Shirt"
}
```

**Response (`201 Created`):**
```json
{
  "session_token": "sess_live_9a8b7c6d5e4f3a2b1c",
  "checkout_url": "https://api.yourdomain.com/checkout/embed?session=sess_live_9a8b7c6d5e4f3a2b1c",
  "expires_at": "2026-09-24T14:15:00Z"
}
```

### Step 2: Include the Widget in Any Frontend (2 Lines of Code)

```html
<!-- 1. Include the Drop-In Modal SDK -->
<script src="https://api.yourdomain.com/static/js/motaaked-checkout.js"></script>

<!-- 2. Trigger the modal upon checkout button click -->
<button onclick="payWithInstaPay()">Pay with InstaPay</button>

<script>
function payWithInstaPay() {
  // Call your backend to get session_token, then open:
  MotaakedCheckout.open({
    sessionToken: "sess_live_9a8b7c6d5e4f3a2b1c",
    onSuccess: function(data) {
      console.log("Payment Confirmed!", data);
      alert("Payment verified! Order #" + data.order_id);
      window.location.href = "/thank-you?order_id=" + data.order_id;
    },
    onCancel: function() {
      console.log("Customer closed the checkout window.");
    },
    onError: function(err) {
      console.error("Verification error:", err);
    }
  });
}
</script>
```

---

## 6. Option 2: WooCommerce & WordPress

The **Motaaked WooCommerce Gateway** integrates directly into WordPress as a native payment method.

### Architecture & Capabilities:
- Full compatibility with **WooCommerce HPOS** (High-Performance Order Storage).
- Adds InstaPay to WooCommerce Checkout settings.
- Prompts customer with clear step-by-step payment instructions and an input field for the **Bank SMS Reference ID**.
- Automatically marks order as `Processing` or `Completed`, reduces inventory, and adds an internal audit note containing the SMS Reference ID and timestamp.

### Installation Walkthrough:
1. Copy the plugin folder to `wp-content/plugins/instapay-for-woocommerce/`.
2. In WordPress Admin, navigate to **Plugins** and activate **InstaPay Gateway for WooCommerce**.
3. Go to **WooCommerce > Settings > Payments > InstaPay Gateway**.
4. Configure your:
   - **InstaPay Handle (IPA)**: e.g. `yourname@instapay`
   - **Gateway Base URL**: `https://api.yourdomain.com`
   - **Merchant API Key**: `mk_live_...`
   - **Order Status After Verification**: `Processing` or `Completed`
5. Click **Save Changes**.

### Order Verification Hook:
```php
add_action('instapay_payment_verified', function($order_id, $reference_id, $matched_at) {
    $order = wc_get_order($order_id);
    $order->add_order_note(sprintf(
        __('InstaPay verified automatically via Bank SMS Reference ID: %s at %s', 'instapay'),
        $reference_id,
        $matched_at
    ));
    $order->payment_complete($reference_id);
}, 10, 3);
```

---

## 7. Option 3: Shopify Integration (Draft Orders API + Liquid)

Because Shopify restricts direct native gateway development for regional payment networks, Motaaked provides a battle-tested architecture using **Shopify Draft Orders API** and a **Verification Proxy Server**.

### Architecture:
```
[Customer on Shopify Cart]
       |
       v (Click "Pay via InstaPay")
[Liquid Snippet: instapay-checkout.liquid]
       |
       v (Creates Draft Order via Storefront)
[Node.js / Express Verification Server]
       |
       +---> POST /v1/orders/verify (Motaaked Gateway)
       |
       v (If SMS Reference ID Matches)
[Complete Shopify Draft Order via Admin REST/GraphQL API]
       |
       v
[Redirect Customer to Shopify Thank-You Page]
```

### Liquid Snippet (`snippets/instapay-checkout.liquid`):
```liquid
<div id="instapay-container" class="instapay-checkout-box">
  <button type="button" id="btn-instapay-pay" class="btn btn-primary w-full">
    <span>الدفع بواسطة إنستاباي | Pay with InstaPay</span>
  </button>
</div>

<script src="{{ 'instapay-checkout.js' | asset_url }}" defer></script>
```

### Node.js Verification Handler (`server/index.js`):
```javascript
app.post('/instapay/verify', async (req, res) => {
  const { shopify_draft_order_id, order_id, amount, reference_id } = req.body;

  // 1. Verify against Motaaked Gateway
  const verifyRes = await fetch(`${process.env.INSTAPAY_BASE_URL}/v1/orders/verify`, {
    method: 'POST',
    headers: {
      'X-API-Key': process.env.INSTAPAY_API_KEY,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      order_id: order_id,
      amount: parseFloat(amount),
      reference_id: reference_id // Bank SMS Reference ID
    })
  });

  const verification = await verifyRes.json();
  if (!verification.verified) {
    return res.status(400).json({ success: false, message: verification.message });
  }

  // 2. Complete Shopify Draft Order
  const shopifyRes = await fetch(`https://${process.env.SHOPIFY_SHOP}/admin/api/2026-01/draft_orders/${shopify_draft_order_id}/complete.json`, {
    method: 'PUT',
    headers: {
      'X-Shopify-Access-Token': process.env.SHOPIFY_ADMIN_TOKEN,
      'Content-Type': 'application/json'
    }
  });

  const shopifyOrder = await shopifyRes.json();
  return res.json({
    success: true,
    redirect_url: shopifyOrder.draft_order.completed_at ? shopifyOrder.draft_order.invoice_url : '/checkout'
  });
});
```

---

## 8. Option 4: Laravel Framework (PHP)

Laravel applications can integrate with Motaaked using either:
1. **Approach A: Universal Drop-In Modal Widget (`MotaakedCheckout` in Blade)** — Recommended for the fastest integration with ready-made UI, live countdown timer, auto-polling, and QR/handle display.
2. **Approach B: Native Custom Form & Server-Side Verification** — For bespoke checkout pages where you build your own form input for the Bank SMS Reference ID.

---

### 1. Configuration in `.env` & `config/services.php`

**`.env`:**
```env
INSTAPAY_BASE_URL=https://api.yourdomain.com
INSTAPAY_API_KEY=mk_live_your_key_here
INSTAPAY_HANDLE=merchant@instapay
```

**`config/services.php`:**
```php
'instapay' => [
    'base_url' => env('INSTAPAY_BASE_URL', 'https://api.yourdomain.com'),
    'api_key'  => env('INSTAPAY_API_KEY'),
    'handle'   => env('INSTAPAY_HANDLE'),
],
```

---

### 2. Service Implementation (`app/Services/InstaPayService.php`)

```php
<?php

namespace App\Services;

use App\Models\Order;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;

class InstaPayService
{
    protected string $baseUrl;
    protected string $apiKey;

    public function __construct()
    {
        $this->baseUrl = rtrim(config('services.instapay.base_url'), '/');
        $this->apiKey = config('services.instapay.api_key');
    }

    /**
     * Create an interactive Drop-In Checkout Session (Approach A: MotaakedCheckout Widget)
     */
    public function createCheckoutSession(Order $order): array
    {
        try {
            $response = Http::withHeaders([
                'X-API-Key'    => $this->apiKey,
                'Content-Type' => 'application/json',
            ])->post("{$this->baseUrl}/v1/checkout/session", [
                'order_id'       => $order->code,
                'amount'         => (float) $order->total_amount,
                'currency'       => 'EGP',
                'description'    => "Order #{$order->code}",
                'customer_name'  => $order->customer_name,
                'customer_email' => $order->customer_email,
                'customer_phone' => $order->customer_phone,
                'return_url'     => route('orders.confirmed', $order->id),
            ]);

            return $response->json();
        } catch (\Exception $e) {
            Log::error("InstaPay Checkout Session Creation Failed: " . $e->getMessage());
            return ['session_token' => null, 'error' => $e->getMessage()];
        }
    }

    /**
     * Create a pending order on the gateway (Approach B: Custom Form)
     */
    public function createOrder(string $orderId, float $amount, string $description = ''): array
    {
        $response = Http::withHeaders([
            'X-API-Key'    => $this->apiKey,
            'Content-Type' => 'application/json',
        ])->post("{$this->baseUrl}/v1/orders/create", [
            'order_id'    => $orderId,
            'amount'      => $amount,
            'description' => $description,
        ]);

        return $response->json();
    }

    /**
     * Verify payment against incoming Bank SMS credit (Approach B: Custom Form)
     */
    public function verifyOrder(string $orderId, float $amount, string $smsReferenceId): array
    {
        try {
            $response = Http::withHeaders([
                'X-API-Key'    => $this->apiKey,
                'Content-Type' => 'application/json',
            ])->timeout(12)->post("{$this->baseUrl}/v1/orders/verify", [
                'order_id'     => $orderId,
                'amount'       => $amount,
                'reference_id' => $smsReferenceId, // Must be Bank SMS Reference ID
            ]);

            return $response->json();
        } catch (\Exception $e) {
            Log::error("InstaPay Gateway Connection Failure: " . $e->getMessage());
            return ['verified' => false, 'message' => 'Verification gateway unreachable.'];
        }
    }
}
```

---

### 3. Approach A: Universal Drop-In Modal Widget (`MotaakedCheckout` in Blade)

This approach uses `motaaked-checkout.js` in your Blade template to pop open the responsive payment modal with zero custom UI styling required.

#### A. Controller Action (`app/Http/Controllers/OrderPaymentController.php`)
```php
namespace App\Http\Controllers;

use App\Models\Order;
use App\Services\InstaPayService;
use Illuminate\Http\Request;

class OrderPaymentController extends Controller
{
    public function checkout(Order $order, InstaPayService $instaPay)
    {
        // 1. Generate session token from Motaaked Gateway
        $session = $instaPay->createCheckoutSession($order);

        if (empty($session['session_token'])) {
            return back()->with('error', 'Unable to initiate InstaPay checkout session. Please try again.');
        }

        // 2. Render Blade view with session_token
        return view('orders.checkout', [
            'order'        => $order,
            'sessionToken' => $session['session_token'],
            'gatewayUrl'   => config('services.instapay.base_url'),
        ]);
    }
}
```

#### B. Blade View (`resources/views/orders/checkout.blade.php`)
```html
@extends('layouts.app')

@section('content')
<div class="container py-5 text-center">
    <div class="card shadow-sm p-4 mx-auto" style="max-width: 480px;">
        <h4 class="mb-3">Complete Payment</h4>
        <p class="text-muted">Order #{{ $order->code }}</p>
        <h2 class="text-primary mb-4">{{ number_format($order->total_amount, 2) }} EGP</h2>

        <!-- Trigger Button -->
        <button id="pay-instapay-btn" class="btn btn-success btn-lg w-100">
            Pay with InstaPay
        </button>
    </div>
</div>

<!-- 1. Load Motaaked Drop-In SDK -->
<script src="{{ $gatewayUrl }}/static/js/motaaked-checkout.js"></script>

<!-- 2. Trigger MotaakedCheckout Modal -->
<script>
document.getElementById('pay-instapay-btn').addEventListener('click', function() {
    MotaakedCheckout.open({
        sessionToken: "{{ $sessionToken }}",
        onSuccess: function(data) {
            console.log("Payment Confirmed!", data);
            window.location.href = "{{ route('orders.confirmed', $order->id) }}";
        },
        onCancel: function() {
            console.log("Customer closed the checkout window.");
        },
        onError: function(err) {
            alert("Verification error: " + (err.message || 'An error occurred.'));
        }
    });
});
</script>
@endsection
```

---

### 4. Approach B: Native Custom Form & Server-Side Verification

If you prefer building your own custom HTML form without an iframe modal:

#### A. Blade Template (`resources/views/orders/custom_verify.blade.php`)
```html
@extends('layouts.app')

@section('content')
<div class="card p-4 mx-auto" style="max-width: 500px;">
    <h4>InstaPay Transfer Instructions</h4>
    <p>Please transfer <strong>{{ number_format($order->total_amount, 2) }} EGP</strong> to:</p>
    <div class="alert alert-info font-monospace">{{ config('services.instapay.handle') }}</div>

    <form method="POST" action="{{ route('orders.verify_payment', $order->id) }}">
        @csrf
        <div class="mb-3">
            <label for="sms_reference_id" class="form-label">Bank SMS Reference ID (From Bank SMS alert)</label>
            <input type="text" name="sms_reference_id" id="sms_reference_id" class="form-control" required placeholder="e.g. 5241890245">
            <small class="text-muted">Enter the reference number from your Bank SMS, not the InstaPay screenshot.</small>
        </div>
        <button type="submit" class="btn btn-primary w-100">Verify Payment</button>
    </form>
</div>
@endsection
```

#### B. Controller Action (`app/Http/Controllers/OrderPaymentController.php`)
```php
public function verify(Request $request, Order $order, InstaPayService $instaPay)
{
    $request->validate([
        'sms_reference_id' => 'required|string|min:4|max:40',
    ]);

    $result = $instaPay->verifyOrder(
        $order->code,
        $order->total_amount,
        $request->input('sms_reference_id')
    );

    if (!empty($result['verified'])) {
        $order->update([
            'status'            => 'paid',
            'payment_reference' => $request->input('sms_reference_id'),
            'paid_at'           => now(),
        ]);

        return response()->json([
            'success'  => true,
            'message'  => 'Payment verified successfully!',
            'redirect' => route('orders.confirmed', $order->id),
        ]);
    }

    return response()->json([
        'success' => false,
        'message' => $result['message'] ?? 'Payment match pending. Please retry shortly.',
    ], 422);
}
```

---

## 9. Option 5: Node.js & Express.js

### Client Class & Middleware Factory (`src/instapay.js`):
```javascript
export class InstaPayClient {
  constructor({ baseUrl, apiKey }) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.apiKey = apiKey;
  }

  async verifyOrder({ orderId, amount, referenceId }) {
    const res = await fetch(`${this.baseUrl}/v1/orders/verify`, {
      method: 'POST',
      headers: {
        'X-API-Key': this.apiKey,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        order_id: orderId,
        amount: Number(amount),
        reference_id: referenceId, // Bank SMS Reference ID
      }),
    });
    return await res.json();
  }
}

export function instaPayMiddleware(client) {
  return async (req, res, next) => {
    const { orderId, amount, smsReferenceId } = req.body;
    const result = await client.verifyOrder({
      orderId,
      amount,
      referenceId: smsReferenceId,
    });

    if (result && result.verified) {
      req.instapayResult = result;
      return next();
    }
    return res.status(402).json({
      error: 'Payment Verification Failed',
      message: result?.message || 'Bank SMS Reference ID not matched yet.',
    });
  };
}
```

---

## 10. Option 6: React & Next.js (SPA, Pages & App Router)

### Next.js App Router API Route (`app/api/checkout/verify/route.ts`):
```typescript
import { NextResponse } from 'next/server';

export async function POST(req: Request) {
  const body = await req.json();
  const { orderId, amount, smsReferenceId } = body;

  const res = await fetch(`${process.env.INSTAPAY_BASE_URL}/v1/orders/verify`, {
    method: 'POST',
    headers: {
      'X-API-Key': process.env.INSTAPAY_API_KEY!,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      order_id: orderId,
      amount: Number(amount),
      reference_id: smsReferenceId,
    }),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
```

### React Component (`components/InstaPayCheckout.tsx`):
```tsx
import React, { useState } from 'react';

interface Props {
  orderId: string;
  amount: number;
  handle: string;
  onSuccess: (res: any) => void;
}

export const InstaPayCheckout: React.FC<Props> = ({ orderId, amount, handle, onSuccess }) => {
  const [refId, setRefId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleVerify = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/checkout/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ orderId, amount, smsReferenceId: refId }),
      });
      const data = await res.json();
      if (data.verified) {
        onSuccess(data);
      } else {
        setError(data.message || 'Verification pending. Retrying...');
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 bg-slate-900 text-white rounded-2xl border border-slate-800">
      <h3 className="font-bold text-lg mb-2">InstaPay Bank Transfer</h3>
      <p className="text-sm text-slate-300 mb-4">
        Transfer <strong>{amount.toFixed(2)} EGP</strong> to handle <code className="bg-slate-800 px-2 py-1 rounded text-emerald-400">{handle}</code>.
      </p>
      
      <div className="mb-4">
        <label className="block text-xs font-semibold text-slate-300 mb-1">
          Bank SMS Reference ID (from bank text message, NOT InstaPay screenshot):
        </label>
        <input
          type="text"
          value={refId}
          onChange={(e) => setRefId(e.target.value)}
          placeholder="e.g. 240923000123"
          className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl font-mono text-sm"
        />
      </div>

      {error && <p className="text-xs text-rose-400 mb-3">{error}</p>}

      <button
        onClick={handleVerify}
        disabled={loading || !refId.trim()}
        className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 rounded-xl font-bold transition disabled:opacity-50"
      >
        {loading ? 'Verifying Bank SMS...' : 'Verify Payment'}
      </button>
    </div>
  );
};
```

---

## 11. Option 7: Learning Platforms (LearnDash LMS & Moodle)

### LearnDash Course Unlock Flow:
1. Student clicks **"Enroll with InstaPay"** on course page.
2. Shortcode `[instapay_checkout course_id="45" price="650"]` generates checkout dialog.
3. Student transfers fee via InstaPay and submits the **Bank SMS Reference ID**.
4. Gateway confirms match; plugin calls LearnDash API:
   ```php
   ld_update_course_access($student_user_id, $course_id, $remove = false);
   ```
5. Student is immediately redirected to Lesson 1 with enrollment status active.

### Moodle (`enrol_instapay`):
- Standard Moodle 4.x enrolment plugin.
- In course settings, teachers set course fee and enable InstaPay.
- On `process.php`: upon verified match, plugin executes:
  ```php
  $plugin->enrol_user($instance, $USER->id, $roleid, $timestart, $timeend);
  ```

---

## 12. Option 8: Pure PHP (cURL / Backend Proxy)

For legacy PHP stores or custom carts without frameworks, use this secure proxy:

```php
<?php
// verify_order_proxy.php
header('Content-Type: application/json');

$apiKey = 'mk_live_your_merchant_key';
$gatewayUrl = 'https://api.yourdomain.com/v1/orders/verify';

$input = json_decode(file_get_contents('php://input'), true);

$payload = json_encode([
    'order_id' => $input['order_id'] ?? '',
    'amount' => floatval($input['amount'] ?? 0),
    'reference_id' => trim($input['sms_reference_id'] ?? ''), // Bank SMS Reference ID
]);

$ch = curl_init($gatewayUrl);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $payload,
    CURLOPT_HTTPHEADER => [
        'Content-Type: application/json',
        'X-API-Key: ' . $apiKey,
    ],
    CURLOPT_TIMEOUT => 15,
]);

$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

http_response_code($httpCode);
echo $response;
```

---

## 13. Option 9: Python (FastAPI, Django & Flask)

```python
import httpx

async def verify_instapay_payment(order_id: str, amount: float, sms_reference_id: str, api_key: str, base_url: str):
    url = f"{base_url.rstrip('/')}/v1/orders/verify"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "order_id": order_id,
        "amount": amount,
        "reference_id": sms_reference_id.strip()
    }
    
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        return resp.status_code, resp.json()
```

---

## 14. Core REST API Reference

### 14.1 Create Order
- **Endpoint**: `POST /v1/orders/create`
- **Headers**: `X-API-Key: mk_live_...`
- **Request Body**:
  ```json
  {
    "order_id": "ORD-1092",
    "amount": 350.00,
    "currency": "EGP",
    "description": "2x Organic Coffee Beans"
  }
  ```
- **Response (`201 Created`)**:
  ```json
  {
    "order_id": "ORD-1092",
    "amount": 350.0,
    "status": "PENDING",
    "instapay_handle": "store@instapay",
    "payment_instructions": "Please transfer 350.00 EGP to store@instapay and paste your Bank SMS Reference ID."
  }
  ```

### 14.2 Verify Order via Bank SMS Reference ID
- **Endpoint**: `POST /v1/orders/verify`
- **Headers**: `X-API-Key: mk_live_...`
- **Request Body**:
  ```json
  {
    "order_id": "ORD-1092",
    "amount": 350.00,
    "reference_id": "240923000123"
  }
  ```
- **Response (`200 OK` - Match Confirmed)**:
  ```json
  {
    "verified": true,
    "status": "MATCHED",
    "order_id": "ORD-1092",
    "amount": 350.0,
    "reference_id": "240923000123",
    "matched_at": "2026-09-24T12:30:15Z",
    "message": "Payment verified successfully."
  }
  ```

---

## 15. Comprehensive Integration Q&A / Knowledge Base (Bilingual EN / AR)

This section serves as the definitive reference for merchants, developers, and the integrated AI Copilot Assistant.

---

### 15.1 Core Production & Forwarder FAQs (الأسئلة الشائعة الأساسية)

#### Q1: Can I use any phone to set up the SMS Forwarder app? / هل يمكنني استخدام أي هاتف لتثبيت تطبيق تحويل الرسائل؟
- **English**: You must have an **Android** phone to be able to set up the SMS Forwarder app. It is a lightweight, open-source application with its download link available directly in the portal dashboard. Because it is installed from outside Google Play, you must enable installation from unknown sources, grant SMS read permissions, and set Battery Optimization to **Unrestricted** ("Don't Optimize").
- **العربية**: يجب أن يكون لديك هاتف يعمل بنظام **Android** حتى تتمكن من إعداد تطبيق SMS Forwarder. وهو تطبيق خفيف مفتوح المصدر يتوفر رابطه المباشر داخل لوحة تحكم المنصة. ونظراً لتثبيته من خارج متجر Google Play، يجب الموافقة على تثبيت التطبيقات من مصادر غير معروفة، ومنح صلاحيات قراءة الرسائل، واستثناء التطبيق من موفر الطاقة (Battery Optimization -> Unrestricted).

#### Q2: Does this portal read all the SMS messages on my phone? / هل تقرأ البوابة جميع رسائل الـ SMS على هاتفي؟
- **English**: No. Motaaked does **NOT** have direct access to your phone or your general SMS inbox. The portal receives only the specific messages that your phone forwarder app pushes via encrypted webhook. To ensure complete privacy, configure the forwarder with sender rules (e.g. sender: `"CIB"`, `"NBE"`, `"BM"`, `"QNB"`) and a text filter (e.g. `"IPN inward transfer"` or `"تم تحويل"`). Only matching incoming bank payment notifications are dispatched to the portal.
- **العربية**: لا، البوابة **لا تقرأ جميع رسائل الـ SMS** الموجودة على هاتفك. البوابة تستقبل فقط الرسائل التي يقوم تطبيق التحويل بإرسالها إليها مشفرة عبر الـ Webhook، ولا تملك أي صلاحية للوصول المباشر إلى هاتفك. لحماية خصوصيتك التامة، قم بضبط فلتر الرسائل داخل التطبيق: حدد اسم أو رقم المرسل (مثل CIB أو NBE) وأضف فلتر نصي دقيق (مثل `"IPN inward transfer"` أو `"تم تحويل"`). بهذه الطريقة، يتم إرسال إشعارات المعاملات البنكية المطلوبة فقط.

#### Q3: What should I do if my bank is not listed in active banks? / ماذا أفعل إذا لم يكن بنكي مدرجاً في قائمة البنوك المدعومة؟
- **English**: You can easily open a Support / Dispute Ticket from the portal's Support Hub and paste an exact sample of the incoming bank SMS message. The system administrator will configure the regular expression template in Tab 4 (Bank Patterns) to recognize your bank instantly without needing any system redeployment.
- **العربية**: يمكنك فتح تذكرة دعم فني بسهولة من مركز المساعدة (Support Hub) وإرفاق نص تجريبي لرسالة البنك المستلمة. ستقوم الإدارة بإضافة قالب التعبير النمطي (Regex Pattern) الخاص ببنكك فورياً من لوحة التحكم في تبويب قوالب البنوك دون الحاجة لتحديث الكود أو إعادة تشغيل الخادم.

#### Q4: What should I do if a transaction does not appear on Live Stream? / ماذا أفعل إذا لم تظهر المعاملة في البث المباشر؟
- **English**: First, check if your Android forwarder phone is connected to the internet. If the phone was temporarily offline, ensure it reconnects to Wi-Fi or cellular; all buffered unread SMS alerts will automatically synchronize. If the payment still hasn't appeared, you can enter the Bank SMS Reference ID manually in Tab 1 (Live Tracker); it will be monitored in the Pending Watchlist for up to 30 minutes until matched.
- **العربية**: أولاً، تأكد من اتصال هاتف التحويل بالإنترنت؛ إذا كان الهاتف غير متصل، بمجرد إعادة الاتصال بالشبكة ستتم مزامنة كافة الرسائل غير المقروءة تلقائياً. إذا لم تظهر المعاملة بعد ذلك، يمكنك البحث عنها يدوياً بإدخال رقم مرجع رسالة البنك في تبويب المراقبة (Tab 1)، وستظل في قائمة الانتظار (Watchlist) لمدة تصل إلى 30 دقيقة حتى اكتمال المطابقة.

#### Q5: How does automated InstaPay verification work? / كيف تعمل المطابقة والتحقق الآلي في إنستاباي؟
- **English**: When a customer transfers funds via InstaPay to your merchant handle, your receiving bank issues an official incoming credit SMS. The Android forwarder dispatches the alert to Motaaked within seconds. When the customer submits their order or checkout form with their Bank SMS Reference ID, Motaaked matches the reference ID and exact amount within a 30-minute sliding window, marks the credit as claimed, and instantly confirms the order.
- **العربية**: عند قيام العميل بالتحويل عبر تطبيق إنستاباي إلى عنوان التاجر، يرسل بنك التاجر رسالة نصية فورية تفيد بدخول المبلغ. يمرر هاتف التحويل الرسالة إلى البوابة خلال ثوانٍ. وعند إدخال العميل لرقم المرجع في صفحة الدفع، يقوم النظام بمطابقة رقم المرجع والمبلغ بدقة متناهية خلال نافذة 30 دقيقة، وتثبيت المعاملة كمدفوعة وتفعيل الطلب آلياً بدون أي تدخل يدوي.

#### Q6: Where can the customer find the Bank SMS Reference ID vs the InstaPay screenshot? / أين يجد العميل رقم المرجع البنكي مقارنة بلقطة شاشة إنستاباي؟
- **English**: After completing a transfer in the official InstaPay app, a green success receipt is displayed with a reference number, and the customer also receives an SMS from their bank with an official Bank Reference ID. **Crucial Distinction**: Motaaked strictly uses the **Bank SMS Reference ID**, NOT the screenshot transaction number. Screenshots are easily faked or duplicated; the Bank SMS Reference ID directly reconciles with bank statements and guarantees 100% fraud immunity.
- **العربية**: بعد إتمام التحويل، يظهر للعميل إيصال أخضر في تطبيق إنستاباي، كما تصل رسالة نصية SMS من بنكه تحتوي على رقم المرجع البنكي. **تنبيه حاسم**: تعتمد منصة متأكد حصرياً على **رقم المرجع الوارد في رسالة البنك SMS**، وليس الرقم الظاهر في لقطة شاشة تطبيق إنستاباي (Screenshot)، لأن لقطات الشاشة قابلة للتزوير والتكرار، بينما رقم مرجع الرسالة النصية مطابق بنسبة 100% لكشف الحساب البنكي الرسمي ويمنع الاحتيال تماماً.

#### Q7: How do I integrate Motaaked with WooCommerce, Shopify, or custom platforms? / كيف أربط منصة متأكد مع ووكومرس أو شوبيفاي أو المنصات المخصصة؟
- **English**: Download official ready-to-use plugins from the Plugins Hub: for WordPress/WooCommerce and LearnDash, upload the zip plugin into WordPress admin; for Shopify, use our Draft Orders integration and liquid modal; for Laravel, Node.js, React, and Python, install our lightweight, zero-dependency SDKs. For any other custom website, embed our 2-line Drop-In Checkout Modal (`motaaked-checkout.js`).
- **العربية**: يمكنك تحميل حزم وإضافات الربط الجاهزة من قسم حزم التكامل (Plugins Hub): لمتاجر ووكومرس وليرنداش ارفع ملف الـ ZIP مباشرة في لوحة ووردبريس؛ ولمتاجر شوبيفاي استخدم حزمة مسودات الطلبات؛ ولمشاريع Laravel و Node.js و React و Python استخدم حزم الـ SDK المعتمدة. ولأي موقع أو سلة شراء مخصصة أخرى، يكفي تضمين نافذة الدفع السريع المدمجة بسطرين كود فقط (`motaaked-checkout.js`).

---

### 15.2 E-Commerce & Framework Technical Q&A (الأسئلة التقنية للتجارة الإلكترونية)

#### Q8: How can I integrate Motaaked with my E-Commerce store (WooCommerce, Shopify, Laravel, etc.)? / كيف يمكنني ربط متجري الإلكتروني مع منصة متأكد؟
- **English**: You can integrate Motaaked into any platform using turnkey plugins and SDKs: 
  1. **WooCommerce**: Native WordPress gateway with automated status updates (`Processing`/`Completed`) and HPOS compatibility.
  2. **Universal Drop-In Widget**: Add 2 lines of JavaScript (`motaaked-checkout.js`) to any checkout page for an instant popup modal.
  3. **Shopify**: Integration via Draft Orders API and a Liquid checkout modal snippet.
  4. **Framework SDKs**: Turnkey libraries for Laravel, Node.js/Express, React/Next.js, Python, and pure PHP.
- **العربية**: يمكنك ربط منصة متأكد بأي متجر إلكتروني باستخدام إضافاتنا ومكتباتنا البرمجية الجاهزة:
  1. **ووكومرس**: إضافة ووردبريس متكاملة لتحديث حالة الطلبات آلياً مع دعم كامل لنظام التخزين عالي الأداء (HPOS).
  2. **نافذة الدفع السريع (Universal Drop-In Widget)**: إضافة سطرين فقط من كود JavaScript (`motaaked-checkout.js`) لأي صفحة دفع لفتح نافذة منبثقة عصرية.
  3. **شوبيفاي**: ربط سلس عبر واجهة مسودات الطلبات (Draft Orders API) وقالب Liquid.
  4. **حزم برمجية مخصصة**: لأطر عمل Laravel، Node.js، React/Next.js، بايثون، وPHP.

#### Q9: How can I build and customize an E-Commerce checkout flow using the REST API? / كيف يمكنني بناء وتخصيص مسار الدفع الإلكتروني عبر الـ REST API؟
- **English**: Building a custom checkout requires just 2 API steps:
  1. Call `POST /v1/orders/create` with your Merchant API Key (`X-API-Key`), `order_id`, and `amount` to register the pending order.
  2. On your checkout UI, display your InstaPay IPA handle and an input field for the customer's Bank SMS Reference ID.
  3. When the customer submits the form, call `POST /v1/orders/verify`. If matched, `verified: true` is returned, allowing you to instantly fulfill the order, unlock downloads, or deliver goods.
- **العربية**: يمكنك بناء مسار دفع مخصص بخطوتين فقط عبر الـ API:
  1. إرسال طلب `POST /v1/orders/create` يحتوي على مفتاح التاجر (`X-API-Key`) ورقم الطلب والمبلغ لتسجيل الطلب المعلق.
  2. عرض عنوان إنستاباي الخاص بك في صفحة الشراء مع حقل مخصص لإدخال الرقم المرجعي للرسالة النصية SMS المستلمة من البنك.
  3. عند ضغط العميل على تأكيد الدفع، استدعِ `POST /v1/orders/verify` ليقوم النظام بمطابقة العملية فوراً. إذا تمت المطابقة، تُرجع البوابة `verified: true` لتتمكن من تسليم الطلب فورياً.

#### Q10: How does the Universal 2-Line Drop-In Checkout Widget work for E-Commerce? / كيف تعمل نافذة الدفع السريع المدمجة (سطرين كود) للتجارة الإلكترونية؟
- **English**: The Universal Drop-In Widget (`motaaked-checkout.js`) is a zero-dependency JavaScript SDK that works with any CMS, website, or framework. Simply include `<script src="/static/js/motaaked-checkout.js"></script>` and trigger `MotaakedCheckout.open({ sessionToken: '...', onSuccess: (res) => { ... } })`. It opens a sleek, mobile-responsive modal overlay with a 15-minute countdown, InstaPay handle copy button, Bank SMS Reference ID validation, and real-time verification polling.
- **العربية**: نافذة الدفع السريع (`motaaked-checkout.js`) هي مكتبة JavaScript مستقلة تماماً بدون أي مكتبات خارجية تعمل مع أي متجر أو موقع أو قالب. ما عليك سوى تضمين ملف السكريبت ثم استدعاء `MotaakedCheckout.open` مع رمز الجلسة والدوال المرجعية عند النجاح. تفتح النافذة واجهة منبثقة متجاوبة وعصرية تحتوي على عد تنازلي مدته 15 دقيقة، زر لنسخ عنوان التحويل، حقل إدخال الرقم المرجعي لرسالة البنك SMS، وفحص آلي دوري حتى تأكيد الدفع.

#### Q11: Why does Motaaked verify the Bank SMS Reference ID instead of the InstaPay screenshot? / لماذا تعتمد منصة متأكد على رقم المرجع البنكي بدلاً من لقطة شاشة إنستاباي؟
- **English**: Motaaked's zero-trust automated matching engine operates by ingesting official, cryptographic bank SMS alerts forwarded in real time from your merchant device. App screenshots can be easily faked, photoshopped, or reused. Furthermore, banks assign their own unique internal transaction reference numbers in the SMS that directly reconcile with bank statements. Matching the SMS Reference ID guarantees 100% fraud prevention and instant, tamper-proof verification.
- **العربية**: يعتمد محرك التحقق الآلي في منصة متأكد على استقبال ومعالجة رسائل البنك النصية الرسمية الواردة إلى هاتف التاجر لحظياً. لقطات الشاشة للتطبيقات قابلة للتزييف أو التعديل بالفوتوشوب أو التكرار الاحتيالي. بالإضافة إلى ذلك، تصدر البنوك أرقاماً مرجعية فريدة لكل تحويل في رسائلها النصية تتطابق مباشرة مع كشف الحساب البنكي. التحقق عبر الرقم المرجعي للرسالة النصية SMS يضمن منع الاحتيال بنسبة 100% وتأكيداً لحظياً موثوقاً.

#### Q12: How does the Drop-In Modal widget handle network latency or delayed bank SMS? / كيف تتعامل نافذة الدفع المدمجة مع بطء شبكات الاتصالات أو تأخر رسائل البنك؟
- **English**: During bank rush hours, bank SMS messages may experience 10 to 45 seconds of telecom delivery delay. The Drop-In Modal widget (`motaaked-checkout.js`) features built-in automated polling. When a customer enters their Bank SMS Reference ID, the widget polls `/v1/orders/verify` every 3 to 4 seconds for up to 20 attempts while displaying an active countdown timer. As soon as the SMS arrives and is ingested, the modal automatically transitions to success and redirects the customer.
- **العربية**: في أوقات الذروة البنكية، قد تتأخر رسالة البنك النصية من 10 إلى 45 ثانية بسبب شبكات الاتصالات. تحتوي نافذة الدفع المدمجة (`motaaked-checkout.js`) على نظام استعلام آلي مدمج؛ حيث تقوم بطلب التحقق من الخادم كل 3 إلى 4 ثوانٍ لما يصل إلى 20 محاولة مع إظهار عداد زمني للعميل. وبمجرد وصول رسالة البنك ومطابقتها، تتحول النافذة فورياً لشاشة النجاح وتوجيه العميل لصفحة الشكر.

#### Q13: What happens if a customer transfers an incorrect amount (underpayment / overpayment)? / ماذا يحدث إذا حول العميل مبلغاً غير مطابق (مبلغ منقوص أو زائد)؟
- **English**: Motaaked enforces exact-amount matching with zero tolerance. If an order expects `250.00 EGP` and the customer transfers `240.00 EGP`, the payment will **NOT** be matched to the order, preventing underpayment fraud. The incoming credit remains marked as `UNCLAIMED` in your merchant dashboard, where your staff can review it or assign it manually.
- **العربية**: تطبق المنصة سياسة المطابقة التامة للمبلغ بدون تساهل. إذا كان إجمالي الطلب `250.00 ج.م` وحول العميل `240.00 ج.م`، فلن تتم مطابقة العملية للطلب تفادياً للاحتيال وسداد مبالغ منقوصة. تظل المعاملة مسجلة في لوحة تحكم التاجر بحالة غير مطالب بها (`UNCLAIMED`) ليتمكن فريق العمل من مراجعتها أو ربطها يدوياً.

#### Q14: Can the same Bank SMS Reference ID be used twice for different orders (Replay Attacks)? / هل يمكن استخدام نفس رقم المرجع البنكي مرتين لطلبين مختلفين (الحماية من التكرار)؟
- **English**: No. All matches are completely atomic. When an incoming credit is matched to an order, its state is immediately committed as `CLAIMED` in the database within a serializable database transaction. Subsequent verification attempts with the same reference ID will be rejected as already claimed, preventing replay attacks and double-spending.
- **العربية**: لا. كافة عمليات المطابقة تتم بشكل ذري وآمن تماماً (`Atomic Transaction`). بمجرد تأكيد مطابقة رسالة البنك لطلب معين، تتغير حالتها فورياً في قاعدة البيانات إلى مستهلكة (`CLAIMED`). وأي محاولة لاحقة لاستخدام نفس رقم المرجع لطلب آخر تُرفض فوراً لمنع هجمات إعادة الاستخدام والاحتيال المزدوج (`Double-Spending`).

#### Q15: How do I handle inventory reservation in WooCommerce or Shopify during payment? / كيف أتعامل مع حجز المخزون في ووكومرس أو شوبيفاي أثناء الدفع؟
- **English**: In WooCommerce, orders created with InstaPay are placed in `Pending payment` status with WooCommerce's built-in hold stock timer (e.g. 15 minutes). When Motaaked verifies the Bank SMS Reference ID, the order moves to `Processing` or `Completed`, permanently deducting inventory. If the customer abandons the checkout without paying within 15 minutes, WooCommerce automatically cancels the order and restores the inventory.
- **العربية**: في ووكومرس، يتم وضع الطلبات التي تختار الدفع بإنستاباي في حالة `Pending payment` (قيد انتظار الدفع) مع تفعيل مؤقت حجز المخزون الافتراضي لووكومرس (مثلاً 15 دقيقة). وبمجرد تأكيد الدفع عبر متأكد، ينتقل الطلب لحالة قيد التنفيذ أو مكتمل ويتم خصم المخزون نهائياً. وإذا تراجع العميل ولم يسدد خلال المهلة، يُلغى الطلب آلياً ويعود المخزون لحالته.

#### Q16: What if the merchant's Android forwarder phone loses Wi-Fi connection or battery? / ماذا يحدث إذا فقد هاتف التحويل الاتصال بالإنترنت أو نفدت بطاريته؟
- **English**: If the forwarder phone temporarily loses Wi-Fi or battery, the Android SMS inbox continues receiving SMS alerts from the telecom carrier. As soon as the device reconnects to Wi-Fi or cellular data, the forwarder application immediately catches up and dispatches all unread bank SMS messages in chronological order. Pending orders that were awaiting verification will be matched instantly upon reconnection.
- **العربية**: إذا فقد هاتف التحويل الاتصال بالإنترنت أو نفدت بطاريته مؤقتاً، يستمر صندوق رسائل الهاتف في استقبال رسائل البنك عبر شبكة المحمول بدون توقف. وبمجرد إعادة توصيل الهاتف بالإنترنت، يقوم التطبيق بمزامنة وإرسال كافة الرسائل المتراكمة بالترتيب الزمني فوراً، وتتم مطابقة كافة الطلبات المعلقة فورياً عند إعادة الاتصال.

#### Q17: Can multiple branch cashiers or multiple websites share the same Motaaked gateway? / هل يمكن لعدة كاشيرات في الفروع أو عدة مواقع مشاركة نفس بوابة متأكد؟
- **English**: Yes. Motaaked includes a complete Multi-User & Multi-Key system. You can generate distinct API keys for your WooCommerce store, your Shopify store, your mobile app, and individual retail POS cashiers. Each transaction tracks the originating merchant and API key for full accounting isolation.
- **العربية**: نعم. تشتمل منصة متأكد على منظومة متعددة المستخدمين ومفاتيح الـ API. يمكنك إنشاء مفاتيح ربط مستقلة لكل متجر من متاجرك (ووكومرس، شوبيفاي، تطبيق الموبايل، أو كاشيرات الفروع). ويتم تسجيل كل معاملة مع مفتاح الربط والتاجر التابع له لعزل الحسابات والتقارير المالية بدقة.

#### Q18: How do I test the entire e-commerce checkout flow in local development? / كيف أختبر دورة الدفع الكاملة للتجارة الإلكترونية في بيئة التطوير المحلية؟
- **English**: In development mode (`http://localhost:8000`), you can simulate incoming bank SMS alerts via the Merchant Dashboard's **Test Drop-In Modal** or by calling `POST /webhook` with a simulated SMS text (e.g., `"تم تحويل مبلغ 100.00 جم إلى حسابكم بنجاح. رقم المرجع: 240923000999"`). Then run your checkout flow and input `240923000999` to see real-time verification and fulfillment.
- **العربية**: في بيئة التطوير المحلية (`http://localhost:8000`)، يمكنك محاكاة رسائل البنك الواردة من خلال زر **تجربة نافذة الدفع (Test Drop-In Modal)** في لوحة التاجر، أو عبر إرسال طلب `POST /webhook` بنص رسالة بنكية تجريبية (مثال: `"تم تحويل مبلغ 100.00 جم إلى حسابكم بنجاح. رقم المرجع: 240923000999"`). بعد ذلك، قم بتجربة الدفع وإدخال رقم المرجع `240923000999` لتشاهد التحقق والتأكيد اللحظي للطلب.

---

### 15.3 Platform Operations & Awareness FAQs (الأسئلة الإرشادية والتشغيلية للمنصة)

#### Q19: What is Live Stream and how does it work? / ما هو البث المباشر (Live Stream) وكيف يعمل؟
- **English**: **Live Stream** (Tab 1 in your dashboard) is a real-time monitor that displays incoming bank transfer SMS messages the exact moment they are pushed from your forwarder phone. Each card reveals the received amount, timestamp, originating bank, sending party, and current claim status (`UNCLAIMED` or `CLAIMED`). It gives store owners and branch cashiers a live, transparent window into incoming payments as they happen without having to manually check their phone or bank app.
- **العربية**: **البث المباشر (Live Stream)** في التبويب الأول هو شاشة مراقبة لحظية تعرض إشعارات ورسائل البنك فور وصولها من هاتف التحويل. توضح كل بطاقة معاملة: المبلغ المستلم، وقت وتاريخ المعاملة، البنك المستلم، وحالة المطالبة (`غير مطالب بها / UNCLAIMED` أو `تمت المطالبة / CLAIMED`). يتيح ذلك لأصحاب المتاجر وكاشيرات الفروع رؤية التحويلات الواردة لحظة بلحظة دون الحاجة لفتح هاتف التحويل أو تطبيق البنك.

#### Q20: How can I make a manual search for a Reference ID? / كيف أقوم بالبحث اليدوي عن رقم المرجع (Manual Reference Search)؟
- **English**: To perform a **Manual Search**, navigate to Tab 1 (Live Tracker & Watchlist) or Tab 2 (Audit Explorer). Enter the 12-digit Bank SMS Reference ID provided by the customer into the Reference ID search box and click **Search**. The system queries the bank credits database; if found, it immediately displays the transaction details, verification status, and bank timestamp. If the SMS has not yet arrived due to telecom delay, the system automatically places it into the **Pending Watchlist** to monitor it live for up to 30 minutes without needing to re-enter it. Each manual search deducts 1 search credit from your active wallet balance.
- **العربية**: لإجراء **البحث اليدوي (Manual Search)**، توجه إلى التبويب الأول (المراقبة الحية) أو التبويب الثاني (سجل المعاملات). اكتب رقم المرجع البنكي (12 رقماً) الذي يقدمه العميل في خانة البحث ثم اضغط على زر **فحص المرجع**. يقوم النظام بالبحث في قاعدة بيانات رسائل البنك فوراً؛ وإذا وُجدت الرسالة، تظهر تفاصيل العملية وحالتها ووقت وصولها. وإذا لم تكن الرسالة قد وصلت بعد بسبب تأخر شبكات الاتصالات، يُسجل الرقم تلقائياً في **قائمة الانتظار (Watchlist)** لمراقبته آلياً لمدة 30 دقيقة بمجرد وصوله. يخصم كل بحث يدوي نقطة واحدة (1 Credit) من رصيد محفظتك النشط.

#### Q21: What is the charging and credit deduction mechanism? / ما هي آلية خصم النقاط والرسوم (Charging Mechanism)؟
- **English**: Motaaked utilizes a fair, transparent **Waterfall Credit Deduction** model for payment verification:
  1. **1 Verification / Search = 1 Credit**: Deducted only upon verifying an order or executing a manual reference search.
  2. **Waterfall Deduction Hierarchy**: The platform first consumes your **Free Monthly Tier Credits** (renewed on the 1st of each month). If a **Day Pass** is active, all searches are 100% free and unlimited. Next, it consumes any active **Promotional / Top-Up Wallet Credits**.
  3. **No Fees on Payments**: InstaPay and IPN network transfers have **0% transaction fees** from the Central Bank of Egypt. Motaaked does not take any percentage cut of your transaction money.
- **العربية**: تعتمد منصة متأكد على **نموذج المحفظة الشلالية (Waterfall Deduction Model)** العادل والشفاف:
  1. **1 عملية فحص أو تحقق = 1 نقطة (Credit)**: تُخصم فقط عند التحقق من طلب دفع أو إجراء بحث يدوي عن رقم المرجع.
  2. **ترتيب الخصم الشلالي**: يستهلك النظام أولاً **النقاط الشهرية المجانية** (التي تتجدد تلقائياً أول كل شهر ميلادي). وفي حال تفعيل **تذكرة اليوم غير المحدود (Day Pass)** تكون جميع العمليات مجانية وغير محدودة. وبعدها يتم الخصم من **رصيد باقات الشحن الترويجية**.
  3. **صفر عمولات على التحويلات**: شبكة إنستاباي القومية مجانية بنسبة **0% وبدون عمولات** من البنك المركزي المصري، ولا تقتطع منصة متأكد أي نسبة مئوية من أموال معاملاتك.

#### Q22: How can we recharge our balance and buy credit packages? / كيف يمكننا شحن الرصيد وشراء باقات النقاط (Recharge / Top-Up)؟
- **English**: To recharge your credit balance:
  1. Navigate to **Tab 3 (Packages & Top-Up / شحن الرصيد)** in your merchant dashboard.
  2. Select your desired package (e.g. Starter, Pro, or Enterprise) and click **Recharge**.
  3. The platform displays an automated invoice with the portal's official InstaPay IPA handle and the exact required amount.
  4. Open your InstaPay app, transfer the exact amount, and copy the **Bank SMS Reference ID** received on your phone.
  5. Paste the Reference ID into the invoice confirmation box and click **Verify Payment**.
  6. The platform's automated engine verifies the transfer instantly and activates your credits immediately 24/7. Alternatively, if your administrator issued a prepaid voucher code, enter it under **Redeem Voucher** to top up instantly.
- **العربية**: لشحن رصيد محفظتك وشراء باقات النقاط:
  1. توجه إلى **التبويب الثالث (باقات الشحن / Packages & Top-Up)** في لوحة التحكم.
  2. اختر الباقة المناسبة لاحتياجاتك (مثلاً: Starter أو Pro أو Enterprise) واضغط على **شحن الرصيد**.
  3. تُظهر المنصة فاتورة سداد فورية تحتوي على عنوان إنستاباي المعتمد للمنصة والمبلغ المطلوب بدقة.
  4. افتح تطبيق إنستاباي على هاتفك، وقم بتحويل المبلغ، ثم انسخ **رقم المرجع البنكي** من رسالة البنك النصية SMS التي تصلك.
  5. الصق رقم المرجع في خانة تأكيد الفاتورة واضغط **تأكيد الدفع**.
  6. يتحقق محرك النظام من التحويل آلياً ويقوم بتفعيل النقاط في محفظتك فوراً على مدار الساعة (24/7). كما يمكنك أيضاً شحن رصيدك إذا كان لديك كود قسيمة مسبقة الدفع بإدخاله في قسم **شحن عبر قسيمة (Redeem Voucher)**.

#### Q23: What do you mean by Validity and when do credits expire? / ماذا تعني فترة الصلاحية (Validity Period) ومتى تنتهي النقاط؟
- **English**: **Validity Period** defines the active lifespan of purchased credits and merchant accounts:
  1. **Package Validity**: When you purchase a top-up package, it includes a defined validity duration (e.g., 30, 90, or 365 days). All purchased credits remain usable until that date.
  2. **Free Monthly Tier**: Resets on the **1st day of every calendar month** at 00:00 UTC. Unused free tier credits do not roll over to the next month.
  3. **Day Pass Unlimited**: Grants 24 consecutive hours of unlimited searches from the exact second of activation.
  4. **Expiration Monitoring**: Your active expiration date is prominently displayed on your top dashboard badge. If validity expires, you can simply purchase any package or redeem a voucher to instantly reactivate your wallet balance.
- **العربية**: **فترة الصلاحية (Validity Period)** هي المدة الزمنية المحددة التي تظل فيها نقاطك وحسابك نشطاً وقابلاً للاستخدام:
  1. **صلاحية باقات الشحن**: عند شراء باقة نقاط، يكون لها مدة صلاحية محددة (مثل 30 أو 90 أو 365 يوماً). تظل كافة النقاط المشتراة صالحة للاستخدام حتى تاريخ الانتهاء.
  2. **النقاط الشهرية المجانية**: تتجدد تلقائياً في **اليوم الأول من كل شهر ميلادي** الساعة 00:00، ولا ترحل النقاط المجانية غير المستهلكة للشهر التالي.
  3. **تذكرة اليوم غير المحدود (Day Pass)**: تمنحك 24 ساعة متواصلة من عمليات البحث والتحقق غير المحدودة تبدأ من لحظة التفعيل.
  4. **متابعة الصلاحية**: يظهر تاريخ انتهاء الصلاحية بوضوح في الشارة أعلى لوحة التحكم. وإذا انتهت الصلاحية، يكفي شراء أي باقة أو تفعيل قسيمة شحن لإعادة تفعيل رصيدك فورياً.

#### Q24: How can I activate SMS Push / Webhook Ingestion? / كيف أقوم بتفعيل إرسال الرسائل الفوري (SMS Push / Webhook)؟
- **English**: To activate automated SMS Push from your Android forwarder device:
  1. Open the **SMS Forwarder** application on your dedicated forwarder phone.
  2. Go to **Settings / Rules** and add a **Webhook (HTTP POST)** destination.
  3. Set the **Destination URL** to your portal's webhook endpoint: `https://your-domain.com/webhook` (e.g., `https://insta.saf7etna.dpdns.org/webhook`).
  4. Set the **Request Method** to `POST` and format to `JSON`.
  5. In **Custom Headers**, add: `X-Forwarder-Key: YOUR_FORWARDER_SECRET_KEY` (as configured in Tab 4 / Settings).
  6. Set the JSON payload template to dispatch `{"sender": "[sender]", "message": "[message]", "timestamp": [timestamp]}`.
  7. Turn on the **Auto-forward incoming SMS** toggle and test connection. Incoming bank credits will now push in under 2 seconds.
- **العربية**: لتفعيل إرسال الرسائل اللحظي (SMS Push) من هاتف الأندرويد إلى المنصة:
  1. افتح تطبيق **SMS Forwarder** على هاتف التحويل المخصص للخدمة.
  2. انتقل إلى **الإعدادات / القواعد (Rules)** وأضف وجهة إرسال من نوع **Webhook (HTTP POST)**.
  3. اكتب رابط الخادم (Webhook URL) الخاص بمنصتك: `https://your-domain.com/webhook` (مثال: `https://insta.saf7etna.dpdns.org/webhook`).
  4. اختر طريقة الإرسال `POST` وصيغة البيانات `JSON`.
  5. في خانة **Custom Headers**، أضف المفتاح السري للتحويل: `X-Forwarder-Key: YOUR_FORWARDER_SECRET_KEY` (المحدد في إعدادات النظام في تبويب الإدارة).
  6. اضبط قالب الـ JSON ليرسل المرسل والرسالة والوقت: `{"sender": "[sender]", "message": "[message]", "timestamp": [timestamp]}`.
  7. فعّل خيار التحويل التلقائي عند استلام الرسائل واضغط اختبار الاتصال، وسيتم استقبال رسائل البنوك خلال أقل من ثانيتين.

#### Q25: How can I set up the SMS Forwarder without sending all my personal SMS messages? / كيف أضبط تطبيق التحويل لحماية خصوصيتي دون إرسال جميع رسائل هاتفي؟
- **English**: To maintain 100% personal privacy on your forwarder phone and ensure only bank payment alerts are pushed:
  1. In the SMS Forwarder application, create a **Dedicated Forwarding Rule** rather than forwarding all SMS.
  2. In the **Sender Filter (مرسل الرسالة)** field, whitelist only your specific banks (e.g., `CIB`, `NBE`, `BM`, `QNB`, `AAIB`, `BDC`, `AlexBank`, `HSBC`).
  3. In the **Content / Text Filter (فلتر محتوى الرسالة)** field, enter incoming payment keywords: `"تم تحويل"` OR `"IPN inward transfer"` OR `"إيداع"` OR `"credited"`.
  4. Add an **Exclusion Filter** for debit/spending alerts containing `"سحب"` or `"خصم"` or `"مشتريات"` or `"debit"`.
  5. With these rules, personal text messages, OTP verification codes, and unrelated SMS alerts are strictly ignored by the app and are never transmitted over the internet.
- **العربية**: لضمان الخصوصية التامة (100%) لهاتفك والتأكد من إرسال رسائل التحويلات البنكية فقط دون أي رسائل شخصية:
  1. داخل تطبيق SMS Forwarder، قم بإنشاء **قاعدة تحويل مخصصة (Specific Rule)** وتجنب خيار تحويل جميع الرسائل.
  2. في حقل **فلتر المرسل (Sender Filter)**: أضف أسماء البنوك المعتمدة لديك فقط (مثل: `CIB`، `NBE`، `BM`، `QNB`، `AAIB`، `AlexBank`، `HSBC`).
  3. في حقل **فلتر نص الرسالة (Content / Text Filter)**: أضف الكلمات الدالة على التحويلات الواردة فقط، مثل: `"تم تحويل"` أو `"IPN inward transfer"` أو `"إيداع"` أو `"credited"`.
  4. أضف استثناءً لكلمات الخصم والمشتريات مثل: `"سحب"` أو `"خصم"` أو `"مشتريات"` أو `"debit"`.
  5. بفضل هذا الضبط، يتجاهل التطبيق تماماً أي رسائل شخصية أو رموز تحقق (OTP) أو رسائل دعائية، ولا يخرج من هاتفك سوى إشعارات الإيداع البنكية المطلوبة للمتجر.

#### Q26: What is the meaning of Heartbeat & how does it work? / ما هو النبض (Heartbeat) وكيف يعمل لمراقبة هاتف التحويل؟
- **English**: **Heartbeat** is an automated telemetry health ping sent by the forwarder phone to Motaaked every 5 minutes:
  1. **What it monitors**: It reports the phone's current battery percentage, charging state (plugged in or running on battery), network connection type (Wi-Fi or 4G), and forwarder background service vitality.
  2. **How it works**: The app sends a lightweight ping to `/v1/telemetry/heartbeat`. Motaaked updates the forwarder telemetry badge on Tab 1 and Tab 4.
  3. **Zero-Downtime Alerts**: If Motaaked does not receive a heartbeat for more than 15 minutes, it flags the forwarder status as `WARNING` or `OFFLINE`, alerting administrators immediately before any incoming payments are missed due to a drained battery or disconnected Wi-Fi.
- **العربية**: **النبض (Heartbeat)** هو إشارة فحص وحالة صحية دورية يرسلها هاتف التحويل تلقائياً إلى المنصة كل 5 دقائق:
  1. **ماذا يراقب**: يقوم بإرسال نسبة شحن البطارية الحالية، حالة الشاحن (متصل بالكهرباء أم يعمل على البطارية)، نوع شبكة الاتصال (Wi-Fi أو بيانات 4G)، واستقرار التطبيق في الخلفية.
  2. **كيف يعمل**: يرسل التطبيق إشارة خفيفة إلى مسار `/v1/telemetry/heartbeat`، لتقوم المنصة بتحديث شارة حالة الهاتف في التبويب الأول والرابع فوراً.
  3. **الحماية من انقطاع الخدمة**: إذا انقطعت إشارات النبض لأكثر من 15 دقيقة، تتغير حالة الهاتف تلقائياً إلى `تحذير / WARNING` أو `غير متصل / OFFLINE`، لتنبيه التاجر فوراً لتفقد شاحن الهاتف أو شبكة الإنترنت قبل أن تتأثر عمليات الدفع الواردة لمتجرك.

#### Q27: What is the Pending Watchlist and how does it protect delayed payments? / ما هي قائمة الانتظار والمراقبة (Pending Watchlist) وكيف تحمي المدفوعات المتأخرة؟
- **English**: The **Pending Watchlist** (Tab 1) is a real-time monitor for orders or reference searches that were submitted before the bank SMS arrived at the merchant's phone:
  1. When a customer or cashier enters a Reference ID that hasn't arrived yet, the platform registers it as a `PENDING` watcher for **30 minutes** with an active live countdown.
  2. The moment the delayed bank SMS reaches the forwarder phone, Motaaked matches the reference ID atomically, marks the transaction as `MATCHED`, and notifies the checkout or cashier UI in real time without requiring the user to search again.
- **العربية**: **قائمة الانتظار والمراقبة (Pending Watchlist)** في التبويب الأول هي ميزة ذكية لمتابعة المعاملات التي أدخل العميل أو الكاشير رقم مرجعها قبل وصول رسالة البنك لهاتف التاجر:
  1. عند إدخال رقم مرجع لم تصل رسالته بعد، يسجله النظام كمعاملة معلقة (`PENDING`) لمدة **30 دقيقة** مع مؤقت تنازلي حي.
  2. بمجرد وصول رسالة البنك المتأخرة لهاتف التحويل، يطابقها النظام فورياً، ويحول حالتها إلى `تمت المطابقة / MATCHED` ويُحدث شاشة الدفع أو الكاشير تلقائياً دون الحاجة لإعادة كتابة الرقم.

#### Q28: How can I export reports and financial statements? / كيف أقوم بتصدير التقارير وكشوف الحسابات المالية (CSV & PDF)؟
- **English**: Motaaked allows you to export complete audit trails and accounting statements from **Tab 2 (Audit Explorer / سجل المعاملات)**:
  1. **Filters**: Filter your transactions by date range (e.g. today, last 7 days, this month, or custom dates), status (`CLAIMED`, `UNCLAIMED`), or specific API key / cashier.
  2. **Excel / CSV Export**: Click **Export CSV** to download a clean spreadsheet with reference IDs, exact amounts, timestamps, and customer order numbers for reconciliation.
  3. **Official PDF Statement**: Click **Generate PDF Statement** to download a stamped, branded financial statement with proper Arabic text rendering, total credit summary, and verification totals.
- **العربية**: تتيح لك منصة متأكد تصدير تقارير محاسبية وكشوف حسابات رسمية كاملة من **التبويب الثاني (سجل المعاملات / Audit Explorer)**:
  1. **تصفية المعاملات**: يمكنك فلترة المعاملات حسب التاريخ (اليوم، آخر 7 أيام، هذا الشهر، أو فترة مخصصة)، أو حسب الحالة (`مطالب بها / CLAIMED` أو `غير مطالب بها / UNCLAIMED`)، أو مفتاح API / كاشير معين.
  2. **تصدير إكسل (CSV Export)**: اضغط على زر **تصدير CSV** لتحميل ملف جدول بيانات يحتوي على أرقام المراجع، المبالغ، التواريخ، وأرقام الطلبات لمطابقتها مع دفاتر حساباتك.
  3. **كشف حساب PDF رسمي**: اضغط على زر **كشف حساب PDF** لتنزيل تقرير مالي منسق ومروس ومختوم يدعم اللغة العربية بالكامل، مع إجمالي المبالغ وعدد المعاملات الناجحة.


