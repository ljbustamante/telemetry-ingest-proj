
from src.infrastructure.repositories.postgres_raw_repository import PostgresRawWriter
from src.domain.models import TelemetryIngest

class SpyCursor:
    def __init__(self):
        self.executed = []; self.rowcount=0
    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if sql.strip().startswith("SELECT device_key, id FROM devices"):
            self.rowcount = 0
    def executemany(self, sql, argslist):
        self.executed.append((sql, argslist))
    def fetchall(self):
        return [("DEV-1", "uuid-1"), ("DEV-2", "uuid-2")]
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): pass

class SpyConn:
    def __init__(self): self.cur=SpyCursor(); self.committed=False; self.rolled=False
    def cursor(self): return self.cur
    def commit(self): self.committed=True
    def rollback(self): self.rolled=True
    def close(self): pass

def test_bulk_insert_on_conflict(monkeypatch):
    from src.infrastructure.repositories import postgres_raw_repository as repo_mod
    spy = SpyConn()
    monkeypatch.setattr(repo_mod, "get_connection", lambda: spy)

    w = PostgresRawWriter()
    w.upsert_raw_batch([
        TelemetryIngest(device_key="DEV-1", event_ts_ms=1730070000000, payload={"x":1}),
        TelemetryIngest(device_key="DEV-2", event_ts_ms=1730070001000, payload={"y":2}),
    ])

    last_sql = [sql for (sql, _) in spy.cur.executed if sql.strip().startswith("INSERT INTO readings_raw_parent")][-1]
    assert "ON CONFLICT (device_id, event_ts, payload_hash) DO NOTHING" in last_sql
