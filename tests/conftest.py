from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import pytest


def make_http_event(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    if isinstance(body, dict):
        body = json.dumps(body)
    return {
        "headers": headers or {},
        "body": body,
        "rawPath": path,
        "requestContext": {"http": {"method": method, "path": path}},
    }


@dataclass
class FakeCursor:
    rows: list[Any]
    row: Any | None = None
    executed: list[tuple[str, tuple[Any, ...] | None]] | None = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        if self.executed is None:
            self.executed = []
        self.executed.append((sql, params))

    def fetchall(self) -> list[Any]:
        return list(self.rows)

    def fetchone(self) -> Any | None:
        return self.row


class FakeConn:
    def __init__(self, cursor_factory: Callable[..., FakeCursor]):
        self._cursor_factory = cursor_factory
        self.closed = False

    def cursor(self, *args: Any, **kwargs: Any) -> FakeCursor:
        return self._cursor_factory(*args, **kwargs)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_db(monkeypatch: pytest.MonkeyPatch):
    """
    Helper to patch any module's imported get_connection symbol:
      fake_db.patch(module, rows=[...], row=...)
    """

    class _Patcher:
        def patch(
            self,
            module,
            *,
            rows: Iterable[Any] = (),
            row: Any | None = None,
        ) -> FakeConn:
            cur = FakeCursor(rows=list(rows), row=row)
            conn = FakeConn(lambda *a, **k: cur)
            monkeypatch.setattr(module, "get_connection", lambda: conn, raising=True)
            return conn

    return _Patcher()

