---
  Flujo completo de la aplicación

  ---
  Flujo 1 — Recepción de telemetría

  POST /telemetry → SQS → sqsConsumer

  Un agente instalado en cada equipo físico envía un snapshot JSON con datos de hardware y rendimiento.

  http_ingest (Lambda fuera de VPC):
  1. Recibe el JSON por HTTP
  2. Valida con Pydantic (TelemetryIngest): necesita device_key, event_ts_ms y payload
  3. Publica el mensaje en la cola SQS FIFO con el device_key como MessageGroupId para mantener orden por equipo
  4. Responde 202 Accepted — no toca la BD

  sqsConsumer (Lambda en VPC con RDS):
  Lee los mensajes de SQS y los persiste en lote:

  SQS messages
      │
      ▼
  [1] SELECT device_key FROM devices
         → si no existe: INSERT INTO devices (device_key)
         → si viene Identity.HostnameHash o CustomerId en el payload:
           UPDATE devices SET hostname_hash, customer_code
      │
      ▼
  [2] INSERT INTO readings_raw_parent
      (device_id, event_ts, received_at, agent_version,
       schema_version, sample_period_s, payload_hash, payload)
      ON CONFLICT (device_id, event_ts, payload_hash) DO NOTHING

  Tablas involucradas:

  devices — Registro maestro de equipos. Se crea automáticamente la primera vez que llega telemetría de un device_key nuevo. Se actualiza con
  hostname_hash y customer_code cuando el payload trae esos campos en Identity.

  readings_raw_parent — Almacén crudo. Cada snapshot queda guardado con su payload JSON completo. La deduplicación se hace con un hash SHA-256
  del payload: si llega el mismo snapshot dos veces, la segunda inserción se ignora silenciosamente (DO NOTHING). Está particionada por mes.

  ---
  Flujo 2 — Curación ETL

  curationEtl — cada 10 minutos (schedule) o POST /internal/curation/run

  Lee los registros crudos nuevos y los normaliza en columnas estructuradas. También detecta cambios de hardware.

  [1] SELECT last_raw_id FROM etl_curation_watermark FOR UPDATE
         (bloquea la fila para evitar ejecuciones paralelas)
      │
      ▼
  [2] SELECT * FROM readings_raw_parent
      WHERE id > {watermark} ORDER BY id ASC LIMIT 500
      │
      ▼
  [3] SELECT current_site_id FROM devices
      WHERE id IN (... batch de device_ids ...)
      │
      ▼
      Por cada fila raw:
      ├─[4] INSERT INTO readings_curated_parent
      │     (device_id, site_id, event_ts, cpu_pct, cpu_temp_c,
      │      mem_used_pct, battery_charge_pct, risk_score,
      │      risk_bucket, sec_tpm_present, ...)
      │     ON CONFLICT (device_id, event_ts) DO NOTHING
      │
      └─[5] SELECT machine_serial_hash, cpu_model, bios_version
            FROM device_hardware_snapshot
            WHERE device_id = ? ORDER BY snapshot_ts DESC LIMIT 1
                → si cambió la huella (serial, CPU, BIOS):
                  INSERT INTO device_hardware_snapshot (...)  RETURNING id
                  INSERT INTO device_gpu (hw_snapshot_id, vendor, model, ...)
                  INSERT INTO device_storage_drive (hw_snapshot_id, interface, model, ...)
      │
      ▼
  [6] UPDATE etl_curation_watermark
      SET last_raw_id = {max id del batch}, updated_at = now()
      COMMIT

  Tablas involucradas:

  etl_curation_watermark — Cursor del ETL. Tiene una fila por pipeline (curation_v1). Guarda el último id de readings_raw_parent procesado. Se
  bloquea con FOR UPDATE al inicio de cada ejecución para que si dos Lambdas arrancan simultáneamente, solo una procese el batch.

  readings_raw_parent — Fuente de datos: se lee en lotes ordenados por id a partir del watermark.

  readings_curated_parent — Destino principal de la curación. Cada fila raw se convierte en una fila curada con métricas individuales en
  columnas separadas (en lugar del JSON monolítico). Tiene risk_score y risk_bucket que se calculan y guardan aquí directamente desde el
  payload. También particionada por mes.

  devices — Se lee para obtener el current_site_id de cada equipo, que se copia a readings_curated_parent.site_id en el momento de la curación.

  device_hardware_snapshot — Se compara la última huella conocida del equipo (serial de máquina, modelo de CPU, versión de BIOS). Solo se
  inserta una nueva fila si algo cambió, evitando duplicados innecesarios.

  device_gpu — Se inserta una fila por cada GPU encontrada en el payload, vinculada al hw_snapshot_id recién creado.

  device_storage_drive — Se inserta una fila por cada disco/SSD encontrado en el payload, vinculada al hw_snapshot_id.

  ---
  Flujo 3 — Job ML de riesgo

  mlRiskJob — una vez al día (schedule) o POST /internal/ml-risk/run

  Analiza la evolución reciente de cada equipo y predice su probabilidad de falla.

  [1] SELECT device_key, payload, event_ts
      FROM readings_raw_parent r
      JOIN devices d ON d.id = r.device_id
      WHERE r.event_ts >= now() - {lookback_days} días
      → top N snapshots por equipo (ROW_NUMBER OVER PARTITION BY device_id)
      │
      ▼
  [2] Por cada equipo → extrae features → construye DataFrame con pandas
      → llama al modelo IsolationForest → obtiene summary
      (worst_risk_level, predicted_failure_risk, main_risk_factors)
      │
      ▼
  [3] SELECT current_site_id FROM devices WHERE id = ?
      │
      ▼
  [4] INSERT INTO ml_predictions
      (model_name, model_version, predicted_at, device_id, site_id,
       horizon_minutes, class_label, class_prob, feature_ts, features_ref)
      RETURNING id
      │
      ▼
  [5] Si riesgo supera umbral Y no hay incidente ML abierto:
      SELECT 1 FROM incidents
      WHERE device_id = ? AND closed_at IS NULL
        AND notes LIKE '%device_risk_v1%'   ← marca de incidente ML
      │
      └─ Si no hay incidente abierto:
         INSERT INTO incidents
         (device_id, site_id, opened_at, symptom, root_cause,
          severity, notes, source_ml_prediction_id)

  Tablas involucradas:

  readings_raw_parent — Fuente del ML. Se usan los payloads crudos (no los curados) para extraer todas las features numéricas que necesita el
  modelo. Se limita a los últimos N días y máximo M snapshots por equipo para controlar el costo computacional.

  devices — Se hace JOIN para obtener el device_key (identificador legible del equipo) y luego se consulta separado para obtener el
  current_site_id.

  ml_predictions — Resultado del análisis por equipo. Guarda el nivel de riesgo (Bajo/Medio/Alto), la probabilidad numérica, el modelo usado y
  una referencia JSON con los factores de riesgo principales. Cada ejecución del job produce una predicción por equipo.

  incidents — Se consulta antes de crear un incidente automático para evitar abrir tickets duplicados. Si ya existe un incidente ML sin cerrar
  para ese equipo, se omite la inserción. Si no existe, se crea un incidente con root_cause = 'predictivo_ml' y vinculado al ml_predictions.id.

  ---
  Flujo 4 — API del dashboard

  Lambdas front* — requests del frontend

  Todas requieren JWT válido (excepto /auth/login).

  Autenticación

  POST /auth/login
  → SELECT id, name, role, password_hash, active FROM users WHERE email = ?
    → verifica password con SHA-256 + hmac.compare_digest
    → retorna JWT firmado con { sub, email, role }
  users — Almacena los operadores del sistema (técnicos, admins). El campo active permite desactivar una cuenta sin borrarla. La contraseña se
  guarda como hash SHA-256.

  ---
  Administración de clientes y ubicaciones

  GET/POST/PUT/DELETE /customers
  → SELECT/INSERT/UPDATE/DELETE FROM customers

  GET/POST/PUT/DELETE /customers/{id}/sites  y  /sites/{id}
  → SELECT/INSERT/UPDATE/DELETE FROM sites
    (valida que el customer_id exista antes de crear una sede)

  GET/POST/PATCH /sites/{id}/device-assignments
  → SELECT device_assignments JOIN devices
  → INSERT INTO device_assignments (device_id, site_id, assigned_at)
  → UPDATE device_assignments SET unassigned_at = now()
    + UPDATE devices SET current_site_id = ?  (cuando se asigna)
    + UPDATE devices SET current_site_id = NULL (cuando se desasigna)

  customers — Empresas clientes. Cada device se asocia a un customer mediante customer_code. Se usa en casi todos los listados para mostrar el
  nombre de la empresa.

  sites — Sedes o ubicaciones físicas dentro de un cliente (oficinas, plantas, etc.). Un equipo tiene un current_site_id que apunta a la sede
  donde está actualmente.

  device_assignments — Historial completo de asignaciones. Una fila activa tiene unassigned_at = NULL. Al reasignar un equipo se cierra la fila
  anterior y se crea una nueva. También se actualiza devices.current_site_id en tiempo real para que las queries usen esa columna sin hacer
  JOINs costosos.

  ---
  Lista y detalle de equipos

  GET /devices
  → SELECT devices + customers + sites
    + LATERAL (SELECT ... FROM readings_curated_parent ORDER BY event_ts DESC LIMIT 1)
    + LATERAL (SELECT id FROM device_assignments WHERE unassigned_at IS NULL LIMIT 1)
    ORDER BY risk_score DESC NULLS LAST

  GET /devices/{id}
  → SELECT devices + customers + sites
    + LATERAL (SELECT risk_score, risk_bucket FROM readings_curated_parent LIMIT 1)
    + SELECT device_hardware_snapshot + device_storage_drive (último snapshot)
    + SELECT ml_predictions (última predicción)

  readings_curated_parent — Para cada equipo se obtiene el último snapshot curado (LATERAL ORDER BY event_ts DESC LIMIT 1) con las métricas
  actuales: CPU, temperatura, batería, riesgo. La lista de equipos se ordena por risk_score descendente para mostrar primero los más críticos.

  device_hardware_snapshot — En el detalle del equipo se muestra el inventario de hardware conocido (CPU, RAM, BIOS, fabricante).

  device_storage_drive — Se incluye en el detalle junto al hardware snapshot para mostrar los discos del equipo.

  ml_predictions — En el detalle se muestra la última predicción ML del equipo con su nivel de riesgo y probabilidad.

  ---
  Métricas históricas

  GET /devices/{id}/metrics?hours=24
  → SELECT date_trunc('hour', event_ts), AVG(cpu_pct), AVG(cpu_temp_c), ...
    FROM readings_curated_parent
    WHERE device_id = ? AND event_ts > now() - N hours
    GROUP BY hora

  GET /dashboard/alert-trend?days=7
  → CTE con serie de buckets de 6h
    + AVG(cpu_pct, cpu_temp_c, battery_charge_pct)
    FROM readings_curated_parent
    JOIN devices (solo ACTIVE)

  readings_curated_parent — Fuente principal de las gráficas del dashboard. Para métricas por equipo se agrupa por hora. Para la tendencia
  global se agrupa en buckets de 6 horas y promedia todos los equipos activos.

  ---
  Alertas

  GET /alerts
  → SELECT ml_predictions p
    JOIN devices + customers
    WHERE class_label IN ('Alto', 'Medio')
      AND predicted_at > now() - 24h
    ORDER BY class_prob DESC

  ml_predictions — Muestra las predicciones de riesgo activas de las últimas 24 horas con nivel medio o alto. Es la pantalla de alertas en
  tiempo real del dashboard.

  ---
  Tickets (incidentes)

  GET /tickets
  → SELECT incidents + devices + customers
    LEFT JOIN ml_feedback
    LEFT JOIN ml_predictions (via source_ml_prediction_id)
    LEFT JOIN LATERAL ml_predictions (última predicción del equipo)

  PATCH /tickets/{id}/close  { outcome, failure_type }
  → UPDATE incidents SET closed_at = now()
  → INSERT/UPDATE ml_feedback (incident_id, outcome, failure_type)

  DELETE /tickets/{id}
  → verifica que no tenga ml_feedback antes de borrar
  → DELETE FROM incidents

  incidents — Los tickets del sistema. Pueden ser creados manualmente por un técnico o automáticamente por el ML. Tienen symptom, severity,
  opened_at y closed_at. Los ML tienen source_ml_prediction_id y una marca device_risk_v1 en notes.

  ml_feedback — Se crea al cerrar un ticket. Guarda si fue una falla real (confirmed_failure) o un falso positivo (false_positive). Esta tabla
  es el ground truth del modelo ML: una vez que existe feedback para un ticket, ese ticket no puede borrarse. También se usa en el listado de
  tickets para mostrar si ya fue evaluado.

  ml_predictions — Se muestra en los tickets de dos formas: directamente si el ticket tiene source_ml_prediction_id (ticket generado por el ML),
  o via LATERAL tomando la última predicción del equipo si el ticket fue creado manualmente.

  ---
  Mapa de lectura/escritura por tabla

  ┌──────────────────────────┬──────────────────────────────────┬───────────────────────────────────────────────────────────────────────────┐
  │          Tabla           │             Escribe              │                                    Lee                                    │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ devices                  │ sqsConsumer,                     │ sqsConsumer, curationEtl, mlRiskJob, devices_list, devices_get,           │
  │                          │ device_assignments_crud          │ alerts_list, tickets_crud                                                 │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ readings_raw_parent      │ sqsConsumer                      │ curationEtl, mlRiskJob                                                    │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ etl_curation_watermark   │ curationEtl                      │ curationEtl                                                               │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ readings_curated_parent  │ curationEtl                      │ devices_list, devices_get, metrics_device, metrics_dashboard,             │
  │                          │                                  │ dashboard_alert_trend                                                     │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ device_hardware_snapshot │ curationEtl                      │ devices_get                                                               │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ device_gpu               │ curationEtl                      │ —                                                                         │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ device_storage_drive     │ curationEtl                      │ devices_get                                                               │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ ml_predictions           │ mlRiskJob                        │ alerts_list, metrics_dashboard, tickets_crud                              │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ incidents                │ mlRiskJob, tickets_crud          │ mlRiskJob, tickets_crud, tickets_export                                   │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ ml_feedback              │ tickets_crud                     │ tickets_crud, tickets_export                                              │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ customers                │ customers_crud                   │ devices_list, devices_get, alerts_list, tickets_crud                      │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ sites                    │ sites_crud                       │ devices_list, devices_get                                                 │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ device_assignments       │ device_assignments_crud          │ devices_list, device_assignments_crud                                     │
  ├──────────────────────────┼──────────────────────────────────┼───────────────────────────────────────────────────────────────────────────┤
  │ users                    │ users_crud                       │ auth_login, users_crud                                                    │
  └──────────────────────────┴──────────────────────────────────┴───────────────────────────────────────────────────────────────────────────┘