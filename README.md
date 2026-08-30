# Settlement Detective — AI Finance Controller for Razorpay Merchants

Settlement Detective reconciles merchant orders, payments, refunds, and Razorpay settlement batches using deterministic matching, first-principles anomaly detection, database-grounded AI investigations, and a secure Razorpay Test Mode integration layer.

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       EXTERNAL PAYMENT SOURCES                          │
│     Razorpay Test Mode API       │    Razorpay HMAC Webhooks            │
│  (GET /v1/payments, recon/combined)│  (payment.captured, settlement.proc)│
└────────────────────┬────────────────────────────┬───────────────────────┘
                     │                            │
                     ▼                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   RAZORPAY INTEGRATION LAYER (Agent D)                  │
│   RazorpayClient (HTTPS Basic Auth) │ RazorpayWebhookHandler (HMAC-SHA)  │
│   RazorpayDataIngester (Source Tag: "RAZORPAY_TEST_MODE")               │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    DATABASE & EVENT STORE (Agent A)                     │
│   orders │ settlements │ settlement_line_items │ variances │ audit_log   │
│   Monetary convention: All amounts strictly in integer paise (BIGINT)   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              DETERMINISTIC RECONCILIATION ENGINE (Agent B)              │
│   5-Pass Matching Pipeline │ First-Principles Anomaly Detection         │
│   Zero LLM Arithmetic │ Zero Hardcoded Results │ Strict Math Integrity   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  AI INVESTIGATION SERVICE (Agent C)                     │
│   POST /api/investigate │ POST /api/chat │ Anti-Hallucination Validator  │
│   Grounded Root-Cause Trees │ Explanatory & Read-Only Layer             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Environment Configuration (`.env`)

Copy `.env.example` to `.env` and fill in your keys:

```bash
# Razorpay Test Mode API Credentials (Dashboard -> Settings -> API Keys)
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_key_secret

# Razorpay Webhook Secret (Dashboard -> Settings -> Webhooks)
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret

# AI Provider Configuration ('gemini' or 'mock')
LLM_PROVIDER=mock
GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-flash

# Server Configuration
PORT=8000
HOST=0.0.0.0
```

---

## 3. Unified REST API Endpoints

### AI Endpoints
* `POST /api/investigate`: Explains a reconciliation variance using grounded evidence and generates a visual root-cause tree.
* `POST /api/chat`: Answers natural-language merchant financial questions with grounded database evidence and exact rupee formatting.
* `GET /api/variances`: Lists all detected variances.

### Razorpay Integration Endpoints
* `GET /api/razorpay/health`: Reports Razorpay connection status and configuration (masked secrets).
* `GET /api/razorpay/payment/:id`: Fetches and normalizes a payment from Razorpay Test Mode.
* `GET /api/razorpay/payment/:id/refunds`: Fetches refunds for a payment.
* `POST /api/razorpay/sync/payment/:id`: Ingests and syncs a Razorpay payment into the local database.
* `POST /api/razorpay/sync/recon`: Fetches and ingests a combined settlement recon report (`GET /v1/settlements/recon/combined`).
* `POST /api/webhooks/razorpay`: Secure webhook endpoint with raw-byte HMAC-SHA256 signature verification and idempotency.

### Health & Documentation
* `GET /api/health`: System health check.
* `GET /api/docs` (`/docs`): OpenAPI / REST documentation.

---

## 4. Webhook Security & Idempotency

* **Signature Verification**: Validates `X-Razorpay-Signature` using constant-time HMAC-SHA256 comparison over the raw request bytes.
* **Supported Events**:
  - `payment.authorized`
  - `payment.captured`
  - `order.paid`
  - `refund.created`
  - `refund.processed`
  - `refund.failed`
  - `settlement.processed`
* **Idempotency**: Processed event IDs are recorded in the append-only `audit_log`. Duplicate deliveries return `200 OK` with `status: "duplicate_ignored"`.

---

## 5. Automated Test Suites (56 Tests Total)

### Run Razorpay Integration Suite (20 Tests)
```bash
python3 scripts/test_razorpay_integration.py
```

### Run Deterministic Reconciliation Suite (14 Tests)
```bash
python3 scripts/test_reconciliation.py
```

### Run AI Investigation Suite (14 Tests)
```bash
python3 scripts/test_ai_service.py
```

### Run Database & Data Integrity Suite (8 Tests)
```bash
python3 scripts/verify_data.py
```

### Start Unified Backend HTTP Server
```bash
python3 src/ai/server.py
```
