-- Optional traceability: link auto-generated incidents to ml_predictions.
-- Apply manually if you want FK-backed linkage (code uses column when present).

ALTER TABLE public.incidents
  ADD COLUMN IF NOT EXISTS source_ml_prediction_id bigint;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'incidents_source_ml_prediction_id_fkey'
  ) THEN
    ALTER TABLE public.incidents
      ADD CONSTRAINT incidents_source_ml_prediction_id_fkey
      FOREIGN KEY (source_ml_prediction_id)
      REFERENCES public.ml_predictions (id)
      ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS incidents_source_ml_prediction_id_idx
  ON public.incidents (source_ml_prediction_id)
  WHERE source_ml_prediction_id IS NOT NULL;
