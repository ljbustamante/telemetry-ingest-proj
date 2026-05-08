# telemetry-ingest-proj

## Tests + coverage

Install dev dependencies (includes `pytest` + `pytest-cov`):

```bash
python -m pip install -r requirements-dev.txt
```

Run unit tests:

```bash
python -m pytest
```

Run tests with coverage (configured in `pyproject.toml`):

```bash
python -m pytest --cov=src --cov-report=term-missing
```

