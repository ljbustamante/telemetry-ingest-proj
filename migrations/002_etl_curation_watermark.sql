-- Watermark for incremental raw -> curated (+ hardware) ETL.
-- Apply manually against the target database before deploying the curation Lambda.

CREATE TABLE IF NOT EXISTS public.etl_curation_watermark (
  pipeline    text PRIMARY KEY,
  last_raw_id bigint NOT NULL DEFAULT 0,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.etl_curation_watermark (pipeline, last_raw_id)
VALUES ('curation_v1', 0)
ON CONFLICT (pipeline) DO NOTHING;

-- One curated row per device per event_ts (idempotent ETL).
CREATE UNIQUE INDEX IF NOT EXISTS readings_curated_uidx_device_event_ts
  ON public.readings_curated_parent (device_id, event_ts);
