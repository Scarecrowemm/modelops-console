PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    sla TEXT,
    region TEXT
);

CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    version TEXT,
    context_window INTEGER,
    modality TEXT NOT NULL DEFAULT 'text',
    status TEXT NOT NULL DEFAULT 'active',
    canary_percent REAL NOT NULL DEFAULT 0,
    quality_score REAL,
    release_date TEXT,
    deprecation_date TEXT,
    fallback_model TEXT,
    notes TEXT,
    FOREIGN KEY (provider_id) REFERENCES providers(id)
);

CREATE TABLE IF NOT EXISTS model_pricing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    input_price_per_1k REAL NOT NULL,
    output_price_per_1k REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    FOREIGN KEY (model_id) REFERENCES models(id)
);

CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    tier TEXT NOT NULL,
    rpm_limit INTEGER NOT NULL,
    tpm_limit INTEGER NOT NULL,
    monthly_budget REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    key_id TEXT,
    requested_model TEXT NOT NULL,
    model_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    cost REAL NOT NULL,
    latency_ms INTEGER NOT NULL,
    status_code INTEGER NOT NULL,
    error_type TEXT,
    route_reason TEXT NOT NULL DEFAULT 'direct',
    fallback_from TEXT,
    cached INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts);
CREATE INDEX IF NOT EXISTS idx_requests_tenant ON requests(tenant_id);
CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(model_id);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status_code);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    dataset TEXT NOT NULL,
    quality_score REAL,
    pass_rate REAL,
    p95_latency_ms REAL,
    cost_per_1k REAL,
    run_at TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES models(id)
);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    model_id TEXT,
    provider_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    owner TEXT,
    summary TEXT,
    root_cause TEXT,
    action_items TEXT,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_model TEXT NOT NULL,
    to_model TEXT NOT NULL,
    batch TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_migrations_tenant ON migrations(tenant_id, from_model);
CREATE INDEX IF NOT EXISTS idx_migrations_batch ON migrations(batch, status);

CREATE TABLE IF NOT EXISTS lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    reason TEXT,
    actor TEXT,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    triggered_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
);
