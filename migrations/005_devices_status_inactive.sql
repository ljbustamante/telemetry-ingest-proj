-- Agrega 'INACTIVE' como valor válido de devices.status
-- (mlRiskJob lo usa para marcar devices sin lecturas recientes)
ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_status_check;

ALTER TABLE devices ADD CONSTRAINT devices_status_check
    CHECK (status IN ('ACTIVE', 'INACTIVE', 'INVENTORY', 'RETIRED'));
