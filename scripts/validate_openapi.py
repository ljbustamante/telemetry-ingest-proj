#!/usr/bin/env python3
"""Valida docs/openapi.yaml contra el esquema OpenAPI 3 (requiere openapi-spec-validator)."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
    from openapi_spec_validator import validate_spec
except ImportError as e:
    print("Instala dependencias de desarrollo: pip install -r requirements-dev.txt", file=sys.stderr)
    raise SystemExit(1) from e


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "docs" / "openapi.yaml"
    if not path.is_file():
        print(f"No existe {path}", file=sys.stderr)
        return 2
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate_spec(spec)
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
