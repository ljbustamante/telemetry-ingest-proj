import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor

# ==========================
# Configuración de conexión
# ==========================

DB_CONFIG = {
    "host": "cn-telemetry-db.cc98o6aq48k5.us-east-1.rds.amazonaws.com",
    "port": 5432,
    "dbname": "postgres",
    "user": "postgres",
    "password": "LD3v3lop3r11#",
}

# Carpeta raíz donde se guardarán los JSON
OUTPUT_BASE_DIR = "./export_readings"


def format_event_ts_for_filename(event_ts):
    """
    Convierte un timestamp a un nombre de archivo válido.
    Ejemplo: 2025-01-15T10-30-00.123456Z
    """
    return event_ts.strftime("%Y-%m-%dT%H-%M-%S.%fZ")


def export_readings_last_month():
    # Crear la carpeta base si no existe
    os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)

    conn = psycopg2.connect(**DB_CONFIG)

    # Cursor "server-side" para no cargar todo en memoria
    cursor_name = "readings_cursor_last_month"
    with conn.cursor(name=cursor_name, cursor_factory=RealDictCursor) as cur:
        # 🔹 SOLO registros del último mes
        cur.execute("""
            SELECT id, device_id, event_ts, payload
            FROM readings_raw_parent
            WHERE event_ts >= NOW() - INTERVAL '1 month'
            ORDER BY event_ts;
        """)

        batch_size = 1000

        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break

            for row in rows:
                device_id = row["device_id"]
                event_ts = row["event_ts"]
                payload = row["payload"]

                # Carpeta por device_id
                device_dir = os.path.join(OUTPUT_BASE_DIR, str(device_id))
                os.makedirs(device_dir, exist_ok=True)

                # Nombre de archivo basado en event_ts
                filename = format_event_ts_for_filename(event_ts) + ".json"
                file_path = os.path.join(device_dir, filename)

                # Normalizar payload
                if isinstance(payload, str):
                    try:
                        payload_data = json.loads(payload)
                    except json.JSONDecodeError:
                        payload_data = payload
                else:
                    payload_data = payload

                # Escribir archivo JSON
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(payload_data, f, ensure_ascii=False, indent=2)

    conn.close()
    print("Exportación del último mes completada.")


if __name__ == "__main__":
    export_readings_last_month()
