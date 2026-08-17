-- Group Buying MVP -- SQLite schema
-- All timestamps are ISO-8601 UTC strings. All dates are 'YYYY-MM-DD'.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sequences (
    name        TEXT PRIMARY KEY,
    value       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customers (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    mobile      TEXT UNIQUE,
    mobile_verified INTEGER NOT NULL DEFAULT 0,   -- OTP hook for post-MVP
    area        TEXT,
    city        TEXT,
    pincode     TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customers_city ON customers(city);

CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL UNIQUE,
    customer_id   TEXT REFERENCES customers(id),
    messages      TEXT NOT NULL DEFAULT '[]',   -- JSON array of {role, text, ts, chips?}
    extracted_information TEXT NOT NULL DEFAULT '{}',  -- JSON slot bag
    stage         TEXT NOT NULL DEFAULT 'greeting',
    referral_code TEXT,
    landing_group_code TEXT,
    intent_id     TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_customer ON conversations(customer_id);

CREATE TABLE IF NOT EXISTS buying_groups (
    id                    TEXT PRIMARY KEY,
    code                  TEXT NOT NULL UNIQUE,
    product_category      TEXT NOT NULL,
    product_specification TEXT NOT NULL DEFAULT '{}',  -- JSON: the grouping spec
    spec_signature        TEXT NOT NULL,               -- canonical string used for matching
    match_mode            TEXT NOT NULL DEFAULT 'flexible',  -- 'exact' | 'flexible'
    city                  TEXT NOT NULL,
    area                  TEXT,
    purchase_window_start TEXT,
    purchase_window_end   TEXT,
    current_qty           INTEGER NOT NULL DEFAULT 0,
    strong_intent_qty     INTEGER NOT NULL DEFAULT 0,
    confirmed_qty         INTEGER NOT NULL DEFAULT 0,
    reference_price       REAL,
    current_price         REAL,
    current_slab_min_qty  INTEGER,
    next_target_qty       INTEGER,
    next_price            REAL,
    supplier_price_confirmed INTEGER NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'collecting_intent',
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_groups_match
    ON buying_groups(product_category, city, spec_signature, status);

CREATE TABLE IF NOT EXISTS purchase_intents (
    id                    TEXT PRIMARY KEY,
    customer_id           TEXT REFERENCES customers(id),
    conversation_id       TEXT REFERENCES conversations(id),
    category              TEXT NOT NULL,
    product               TEXT,
    specifications_json   TEXT NOT NULL DEFAULT '{}',
    quantity              INTEGER NOT NULL DEFAULT 0,
    unit                  TEXT NOT NULL DEFAULT 'unit',
    area                  TEXT,
    city                  TEXT,
    -- Earliest acceptable date. A "within N days" answer is a deadline, so the
    -- buyer is available from today; an explicit date is a genuine target.
    earliest_purchase_date TEXT,
    desired_purchase_date TEXT,
    maximum_purchase_date TEXT,
    can_wait              INTEGER NOT NULL DEFAULT 0,
    brand_flexible        INTEGER NOT NULL DEFAULT 0,
    budget                REAL,
    status                TEXT NOT NULL DEFAULT 'active',   -- active | expired | cancelled | fulfilled
    intent_strength       TEXT NOT NULL DEFAULT 'enquiry',  -- enquiry | intent | strong_intent | ready_to_buy | confirmed
    group_id              TEXT REFERENCES buying_groups(id),
    referral_id           TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    expires_at            TEXT,
    reconfirm_sent_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_intents_group  ON purchase_intents(group_id, status);
CREATE INDEX IF NOT EXISTS idx_intents_expiry ON purchase_intents(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_intents_match  ON purchase_intents(category, city, status);

-- Slabs are either a product-level template (group_id IS NULL, product_key set)
-- or a group-level override (group_id set). Group rows win when present.
CREATE TABLE IF NOT EXISTS pricing_slabs (
    id            TEXT PRIMARY KEY,
    group_id      TEXT REFERENCES buying_groups(id) ON DELETE CASCADE,
    product_key   TEXT,
    minimum_qty   INTEGER NOT NULL,
    maximum_qty   INTEGER,                 -- NULL = open ended top slab
    price         REAL NOT NULL,
    price_status  TEXT NOT NULL DEFAULT 'indicative',  -- indicative | supplier_confirmed
    supplier_id   TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_slabs_group   ON pricing_slabs(group_id, minimum_qty);
CREATE INDEX IF NOT EXISTS idx_slabs_product ON pricing_slabs(product_key, minimum_qty);

CREATE TABLE IF NOT EXISTS referrals (
    id                    TEXT PRIMARY KEY,
    referral_code         TEXT NOT NULL UNIQUE,
    referrer_customer_id  TEXT REFERENCES customers(id),
    referred_customer_id  TEXT REFERENCES customers(id),
    group_id              TEXT REFERENCES buying_groups(id),
    quantity_generated    INTEGER NOT NULL DEFAULT 0,
    clicks                INTEGER NOT NULL DEFAULT 0,
    chats_started         INTEGER NOT NULL DEFAULT 0,
    intents_submitted     INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_customer_id);

CREATE TABLE IF NOT EXISTS referral_events (
    id            TEXT PRIMARY KEY,
    referral_code TEXT NOT NULL,
    event_type    TEXT NOT NULL,   -- click | chat_started | intent_submitted
    session_id    TEXT,
    intent_id     TEXT,
    quantity      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refevents_code ON referral_events(referral_code);

CREATE TABLE IF NOT EXISTS notifications (
    id          TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    group_id    TEXT REFERENCES buying_groups(id),
    intent_id   TEXT,
    type        TEXT NOT NULL,      -- price_drop | near_target | progress | expiry_reminder | referral_joined | admin_broadcast
    channel     TEXT NOT NULL,      -- whatsapp | sms | email
    message     TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued | sent | failed
    dedupe_key  TEXT UNIQUE,
    created_at  TEXT NOT NULL,
    sent_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_group  ON notifications(group_id);

CREATE TABLE IF NOT EXISTS admin_audit (
    id         TEXT PRIMARY KEY,
    action     TEXT NOT NULL,
    entity     TEXT,
    entity_id  TEXT,
    detail     TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
