#!/usr/bin/env bash
# Build the ML Lambda layer (numpy/scipy/pandas/sklearn) and slim it to fit under the
# Lambda 250 MiB unzipped limit (deployment package + all layers).
# Run before deploy when ML pins change:
#   bash scripts/build_ml_scipy_layer.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="python3.13"
IMAGE="public.ecr.aws/sam/build-${RUNTIME}:latest-x86_64"
UID_GID="$(id -u):$(id -g)"

REQ="${ROOT}/requirements-ml-layer.txt"
SITE="${ROOT}/layers/ml-deps/python/lib/${RUNTIME}/site-packages"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

rm -rf "${ROOT}/layers/ml-deps/python"
mkdir -p "${SITE}"

docker run --rm \
  --user "${UID_GID}" \
  -v "${REQ}:/var/task/req.txt:ro" \
  -v "${SITE}:/out:z" \
  "${IMAGE}" \
  /bin/sh -c "python3.13 -m pip install --no-cache-dir -r /var/task/req.txt -t /out"

slim_python_site_packages() {
  local site="$1"
  # Match Serverless pythonRequirements "slim" defaults (drop bytecode + metadata).
  find "${site}" -type f \( -name '*.py[co]' -o -name '*.opt-1.pyc' \) -delete 2>/dev/null || true
  find "${site}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
  find "${site}" -path '*.dist-info/*' -delete 2>/dev/null || true
  find "${site}" -type d -empty -delete 2>/dev/null || true

  # Drop bundled test suites (large, unused at runtime).
  for top in numpy scipy pandas sklearn; do
    if [[ -d "${site}/${top}" ]]; then
      find "${site}/${top}" -type d \( -name tests -o -name test \) -exec rm -rf {} + 2>/dev/null || true
    fi
  done

  # Strip debug symbols from native extensions (same idea as Serverless strip: true).
  if command -v strip >/dev/null 2>&1; then
    find "${site}" -name '*.so' -print0 | xargs -0 strip 2>/dev/null || true
  fi
}

slim_python_site_packages "${SITE}"

BYTES="$(du -sb "${ROOT}/layers/ml-deps/python" | awk '{print $1}')"
echo "ML layer (unzipped) size: ${BYTES} bytes (~$((BYTES / 1024 / 1024)) MiB) under ${ROOT}/layers/ml-deps/python"
if [[ "${BYTES}" -gt 200000000 ]]; then
  echo "warning: ML layer is still very large; consider a container image for mlRiskJob" >&2
fi
