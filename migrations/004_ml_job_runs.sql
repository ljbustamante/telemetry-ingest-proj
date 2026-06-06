-- Tracking de ejecuciones de mlRiskJob
CREATE TABLE ml_job_runs (
    id                   BIGSERIAL PRIMARY KEY,
    started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at         TIMESTAMPTZ,
    status               TEXT NOT NULL DEFAULT 'running',  -- 'running' | 'completed' | 'failed'
    trigger_source       TEXT,                             -- 'schedule' | 'http'
    devices_processed    INT  DEFAULT 0,
    predictions_inserted INT  DEFAULT 0,
    incidents_inserted   INT  DEFAULT 0,
    devices_deactivated  INT  DEFAULT 0,
    skipped_no_rows      INT  DEFAULT 0,
    errors               JSONB,
    config               JSONB,
    error_summary        TEXT
);

ALTER TABLE ml_predictions
    ADD COLUMN IF NOT EXISTS job_run_id BIGINT
        REFERENCES ml_job_runs(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ml_predictions_job_run_id ON ml_predictions(job_run_id);
CREATE INDEX IF NOT EXISTS idx_ml_job_runs_completed_at  ON ml_job_runs(completed_at DESC);
