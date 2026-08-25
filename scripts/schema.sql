-- =============================================================================
-- Optional persistence schema — NOT used in demo mode.
--
-- The demo keeps incident state in LangGraph's MemorySaver and the audit trail
-- in memory, so nothing here is required to run the system. This file is the
-- target schema for the production step described in the README's "Known
-- limitations": swapping MemorySaver for the Postgres checkpointer and
-- persisting the audit trail so decisions survive a restart.
--
-- Apply with:
--     psql "$DATABASE_URL" -f scripts/schema.sql
-- =============================================================================

-- GCB Crisis Squad — Metrics persistence schema
-- SQLite-compatible (also valid PostgreSQL with minor adjustments)
--
-- Usage:
--   sqlite3 data/metrics.db < scripts/schema.sql
--
-- In production, swap to Postgres:
--   psql $DATABASE_URL < scripts/schema.sql

-- ---------------------------------------------------------------------------
-- Incidents
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS incidents (
    run_id          TEXT        PRIMARY KEY,
    incident_id     TEXT        NOT NULL,
    service         TEXT        NOT NULL DEFAULT 'unknown',
    started_at      TEXT        NOT NULL,   -- ISO-8601 UTC
    resolved_at     TEXT,                   -- NULL while in progress
    mttr_minutes    REAL,                   -- NULL while in progress
    mttr_seconds    REAL,
    approval_decision  TEXT,               -- APPROVED | REJECTED | NULL
    decided_by      TEXT,
    created_at      TEXT        NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_incidents_incident_id ON incidents (incident_id);
CREATE INDEX IF NOT EXISTS idx_incidents_started_at  ON incidents (started_at);

-- ---------------------------------------------------------------------------
-- Phase timings (one row per phase per run)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS phase_timings (
    id              INTEGER     PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT        NOT NULL REFERENCES incidents(run_id) ON DELETE CASCADE,
    phase           TEXT        NOT NULL,   -- instana | jira | rag | playbook | teams | hitl | record_decision
    duration_ms     REAL        NOT NULL,
    recorded_at     TEXT        NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_phase_timings_run_id ON phase_timings (run_id);

-- ---------------------------------------------------------------------------
-- LLM cost records (one row per LLM call)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS llm_calls (
    id              INTEGER     PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,                   -- NULL for calls outside an incident run
    node            TEXT,                   -- graph node that made the call
    model           TEXT        NOT NULL,
    prompt_tokens   INTEGER     NOT NULL DEFAULT 0,
    completion_tokens INTEGER   NOT NULL DEFAULT 0,
    total_tokens    INTEGER     NOT NULL DEFAULT 0,
    cost_usd        REAL        NOT NULL DEFAULT 0.0,
    called_at       TEXT        NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_run_id   ON llm_calls (run_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model    ON llm_calls (model);
CREATE INDEX IF NOT EXISTS idx_llm_calls_called_at ON llm_calls (called_at);

-- ---------------------------------------------------------------------------
-- DORA aggregate views
-- ---------------------------------------------------------------------------

-- MTTR by service (last 30 days)
CREATE VIEW IF NOT EXISTS v_mttr_by_service AS
SELECT
    service,
    COUNT(*)                                AS incident_count,
    ROUND(AVG(mttr_minutes), 1)             AS avg_mttr_minutes,
    ROUND(MIN(mttr_minutes), 1)             AS min_mttr_minutes,
    ROUND(MAX(mttr_minutes), 1)             AS max_mttr_minutes
FROM incidents
WHERE resolved_at IS NOT NULL
  AND started_at >= datetime('now', '-30 days')
GROUP BY service
ORDER BY avg_mttr_minutes DESC;

-- Approval rate (last 30 days)
CREATE VIEW IF NOT EXISTS v_approval_rate AS
SELECT
    COUNT(*)                                                            AS total_decisions,
    SUM(CASE WHEN approval_decision = 'APPROVED' THEN 1 ELSE 0 END)    AS approved,
    SUM(CASE WHEN approval_decision = 'REJECTED' THEN 1 ELSE 0 END)    AS rejected,
    ROUND(
        100.0 * SUM(CASE WHEN approval_decision = 'APPROVED' THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0),
        1
    )                                                                   AS approval_rate_pct
FROM incidents
WHERE approval_decision IS NOT NULL
  AND started_at >= datetime('now', '-30 days');

-- LLM cost by model (all time)
CREATE VIEW IF NOT EXISTS v_cost_by_model AS
SELECT
    model,
    COUNT(*)                    AS call_count,
    SUM(total_tokens)           AS total_tokens,
    ROUND(SUM(cost_usd), 6)     AS total_cost_usd,
    ROUND(AVG(cost_usd), 6)     AS avg_cost_per_call_usd
FROM llm_calls
GROUP BY model
ORDER BY total_cost_usd DESC;

-- Phase timing averages (last 30 days)
CREATE VIEW IF NOT EXISTS v_avg_phase_timing AS
SELECT
    phase,
    COUNT(*)                            AS sample_count,
    ROUND(AVG(duration_ms), 0)          AS avg_duration_ms,
    ROUND(MIN(duration_ms), 0)          AS min_duration_ms,
    ROUND(MAX(duration_ms), 0)          AS max_duration_ms
FROM phase_timings pt
JOIN incidents i ON pt.run_id = i.run_id
WHERE i.started_at >= datetime('now', '-30 days')
GROUP BY phase
ORDER BY avg_duration_ms DESC;
