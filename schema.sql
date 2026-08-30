-- ============================================================================
-- Settlement Detective — Minimal P0 Database Schema
-- Optimized for Hackathon Execution: 5 Core Tables
-- Monetary convention: All amounts stored as BIGINT in paise (1 INR = 100 paise)
-- ============================================================================

-- Drop existing tables if re-initializing (in reverse FK dependency order)
DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS variances CASCADE;
DROP TABLE IF EXISTS settlement_line_items CASCADE;
DROP TABLE IF EXISTS settlements CASCADE;
DROP TABLE IF EXISTS orders CASCADE;

-- ----------------------------------------------------------------------------
-- 1. ORDERS TABLE
-- Represents internal merchant order & linked payment/refund status
-- ----------------------------------------------------------------------------
CREATE TABLE orders (
    id                      TEXT PRIMARY KEY,              -- UUID or internal ID (e.g. ord_001)
    merchant_order_id       TEXT UNIQUE NOT NULL,          -- Internal merchant order reference
    razorpay_order_id       TEXT UNIQUE,                   -- Razorpay order ID (e.g. order_xxx)
    razorpay_payment_id     TEXT UNIQUE,                   -- Razorpay payment ID (e.g. pay_xxx)
    
    -- Monetary fields (always in paise)
    amount_paise            BIGINT NOT NULL CHECK (amount_paise > 0),
    fee_paise               BIGINT NOT NULL DEFAULT 0 CHECK (fee_paise >= 0),
    tax_paise               BIGINT NOT NULL DEFAULT 0 CHECK (tax_paise >= 0),
    net_paise               BIGINT NOT NULL DEFAULT 0,     -- amount - fee - tax
    refunded_amount_paise   BIGINT NOT NULL DEFAULT 0 CHECK (refunded_amount_paise >= 0),
    currency                TEXT NOT NULL DEFAULT 'INR',
    
    -- Status and categorization
    status                  TEXT NOT NULL CHECK (status IN ('created', 'authorized', 'captured', 'refunded', 'partially_refunded', 'failed')),
    payment_method          TEXT NOT NULL CHECK (payment_method IN ('upi', 'card', 'netbanking', 'wallet')),
    refund_status           TEXT NOT NULL DEFAULT 'none' CHECK (refund_status IN ('none', 'partial', 'full')),
    
    -- Customer & contextual details
    customer_email          TEXT,
    customer_phone          TEXT,
    
    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL,
    captured_at             TIMESTAMPTZ,
    refunded_at             TIMESTAMPTZ,
    
    -- Metadata / Extensibility
    metadata                JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_orders_merchant_order_id ON orders(merchant_order_id);
CREATE INDEX idx_orders_razorpay_order_id ON orders(razorpay_order_id);
CREATE INDEX idx_orders_razorpay_payment_id ON orders(razorpay_payment_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_payment_method ON orders(payment_method);
CREATE INDEX idx_orders_created_at ON orders(created_at);
CREATE INDEX idx_orders_captured_at ON orders(captured_at);

-- ----------------------------------------------------------------------------
-- 2. SETTLEMENTS TABLE
-- Represents Razorpay batch payouts to the merchant's bank account
-- ----------------------------------------------------------------------------
CREATE TABLE settlements (
    id                      TEXT PRIMARY KEY,              -- UUID or internal ID (e.g. set_001)
    razorpay_settlement_id  TEXT UNIQUE NOT NULL,          -- Razorpay settlement ID (e.g. set_xxx)
    utr                     TEXT UNIQUE,                   -- Bank Unique Transaction Reference
    
    -- Aggregated monetary fields (in paise)
    amount_paise            BIGINT NOT NULL,               -- Net payout amount transferred to bank
    gross_paise             BIGINT NOT NULL DEFAULT 0,     -- Sum of gross payments captured
    fees_paise              BIGINT NOT NULL DEFAULT 0 CHECK (fees_paise >= 0),
    tax_paise               BIGINT NOT NULL DEFAULT 0 CHECK (tax_paise >= 0),
    refunds_paise           BIGINT NOT NULL DEFAULT 0 CHECK (refunds_paise >= 0),
    adjustments_paise       BIGINT NOT NULL DEFAULT 0,     -- Adjustments/deductions (signed)
    currency                TEXT NOT NULL DEFAULT 'INR',
    
    -- Status & cycle dates
    status                  TEXT NOT NULL CHECK (status IN ('created', 'processed', 'failed')),
    period_start            TIMESTAMPTZ NOT NULL,          -- Start of transaction capture window
    period_end              TIMESTAMPTZ NOT NULL,          -- End of transaction capture window
    settled_at              TIMESTAMPTZ,                   -- Actual settlement timestamp
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Metadata
    metadata                JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_settlements_razorpay_id ON settlements(razorpay_settlement_id);
CREATE INDEX idx_settlements_utr ON settlements(utr);
CREATE INDEX idx_settlements_status ON settlements(status);
CREATE INDEX idx_settlements_settled_at ON settlements(settled_at);
CREATE INDEX idx_settlements_period ON settlements(period_start, period_end);

-- ----------------------------------------------------------------------------
-- 3. SETTLEMENT_LINE_ITEMS TABLE
-- Per-transaction breakdown reported inside a settlement batch
-- ----------------------------------------------------------------------------
CREATE TABLE settlement_line_items (
    id                      TEXT PRIMARY KEY,              -- UUID or internal ID (e.g. sli_001)
    settlement_id           TEXT NOT NULL REFERENCES settlements(id) ON DELETE CASCADE,
    
    -- Entity references
    entity_id               TEXT NOT NULL,                 -- Razorpay payment/refund/adjustment ID
    entity_type             TEXT NOT NULL CHECK (entity_type IN ('payment', 'refund', 'adjustment')),
    order_id                TEXT REFERENCES orders(id) ON DELETE SET NULL,
    
    -- Line item financials (in paise)
    amount_paise            BIGINT NOT NULL,               -- Gross transaction amount
    fee_paise               BIGINT NOT NULL DEFAULT 0 CHECK (fee_paise >= 0),
    tax_paise               BIGINT NOT NULL DEFAULT 0 CHECK (tax_paise >= 0),
    debit_paise             BIGINT NOT NULL DEFAULT 0 CHECK (debit_paise >= 0),   -- Deducted amount (e.g. refunds)
    credit_paise            BIGINT NOT NULL DEFAULT 0 CHECK (credit_paise >= 0),  -- Credited amount (e.g. payments)
    currency                TEXT NOT NULL DEFAULT 'INR',
    
    -- Timestamps
    settled_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Metadata
    metadata                JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_sli_settlement_id ON settlement_line_items(settlement_id);
CREATE INDEX idx_sli_entity_id ON settlement_line_items(entity_id);
CREATE INDEX idx_sli_entity_type ON settlement_line_items(entity_type);
CREATE INDEX idx_sli_order_id ON settlement_line_items(order_id);
CREATE INDEX idx_sli_created_at ON settlement_line_items(created_at);

-- ----------------------------------------------------------------------------
-- 4. VARIANCES TABLE
-- Discrepancies and anomalies detected during deterministic reconciliation
-- ----------------------------------------------------------------------------
CREATE TABLE variances (
    id                      TEXT PRIMARY KEY,              -- UUID or internal ID (e.g. var_001)
    settlement_id           TEXT REFERENCES settlements(id) ON DELETE CASCADE,
    order_id                TEXT REFERENCES orders(id) ON DELETE SET NULL,
    line_item_id            TEXT REFERENCES settlement_line_items(id) ON DELETE SET NULL,
    
    -- Anomaly classification
    anomaly_type            TEXT NOT NULL CHECK (anomaly_type IN (
        'AMOUNT_MISMATCH',
        'MISSING_SETTLEMENT_LINE',
        'DUPLICATE',
        'REFUND_MISMATCH',
        'TIMING_DIFFERENCE',
        'UNEXPLAINED_VARIANCE',
        'FEE_ANOMALY'
    )),
    severity                TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    
    -- Financial variance figures (in paise)
    expected_amount_paise   BIGINT NOT NULL,
    actual_amount_paise     BIGINT NOT NULL,
    variance_paise          BIGINT NOT NULL,               -- actual - expected
    
    -- Investigation & resolution details
    title                   TEXT NOT NULL,
    description             TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'detected' CHECK (status IN ('detected', 'investigating', 'resolved', 'false_positive')),
    
    -- Grounded evidence snapshot for AI / auditor
    evidence                JSONB DEFAULT '{}'::jsonb,
    
    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_variances_settlement_id ON variances(settlement_id);
CREATE INDEX idx_variances_order_id ON variances(order_id);
CREATE INDEX idx_variances_anomaly_type ON variances(anomaly_type);
CREATE INDEX idx_variances_severity ON variances(severity);
CREATE INDEX idx_variances_status ON variances(status);
CREATE INDEX idx_variances_created_at ON variances(created_at);

-- ----------------------------------------------------------------------------
-- 5. AUDIT_LOG TABLE
-- Minimal append-only audit trail for financial events and investigation actions
-- ----------------------------------------------------------------------------
CREATE TABLE audit_log (
    id                      TEXT PRIMARY KEY,              -- UUID or internal ID (e.g. aud_001)
    event_type              TEXT NOT NULL,                 -- e.g. DATA_GENERATED, SETTLEMENT_RECONCILED, ANOMALY_SEEDED
    entity_type             TEXT NOT NULL,                 -- e.g. settlement, order, variance, line_item
    entity_id               TEXT NOT NULL,
    description             TEXT NOT NULL,
    actor                   TEXT NOT NULL DEFAULT 'system',-- system, agent_a, reconciler, ai_controller
    metadata                JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_created_at ON audit_log(created_at);
