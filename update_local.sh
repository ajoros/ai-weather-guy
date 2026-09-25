#!/bin/sh
# Cook on this Mac; deploy github.io only when Earth Engine has a newer run.
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-weathernext3-joros}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "$ROOT"
mkdir -p "$ROOT/.cache"
LOG="$ROOT/.cache/cook-latest.log"
{
  echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
  "$ROOT/.venv/bin/python" "$ROOT/cook_ee.py" --workers 8 --fields core
  echo "==== ensemble $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
  "$ROOT/run_ensemble_vm.sh"
} > "$LOG" 2>&1 || {
  cat "$LOG" >&2
  exit 1
}
cat "$LOG"
if grep -q '^COOK_STATUS=updated$' "$LOG"; then
  "$ROOT/deploy_pages.sh"
fi
