from __future__ import annotations

from typing import Any


def fetch_active_alerts(conn: Any) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            p.id,
            d.device_key,
            c.name AS customer_name,
            CASE p.class_label
                WHEN 'Alto' THEN 'HIGH'
                WHEN 'Medio' THEN 'MEDIUM'
                ELSE p.class_label
            END AS risk_level,
            p.class_prob,
            p.predicted_at
        FROM ml_predictions p
        JOIN devices d ON d.id = p.device_id
        JOIN customers c ON c.code = d.customer_code
        WHERE p.class_label IN ('Alto', 'Medio', 'HIGH', 'MEDIUM', 'FAILURE')
          AND p.predicted_at > NOW() - INTERVAL '24 hours'
        ORDER BY p.class_prob DESC
        """
    )
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_open_incidents(conn: Any) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            i.id,
            d.device_key,
            c.name AS customer_name,
            i.symptom,
            i.severity,
            i.opened_at,
            DATE_PART('day', NOW() - i.opened_at)::int AS days_open
        FROM incidents i
        JOIN devices d ON d.id = i.device_id
        JOIN customers c ON c.code = d.customer_code
        WHERE i.closed_at IS NULL
        ORDER BY i.opened_at ASC
        """
    )
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
