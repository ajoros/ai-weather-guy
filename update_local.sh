#!/bin/sh
# Cook on this Mac; deploy github.io when a cook finishes or local inits
# are ahead of the last publish (a crashed run used to skip forever).
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-weathernext3-joros}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
cd "$ROOT"
mkdir -p "$ROOT/.cache"
LOG="$ROOT/.cache/cook-latest.log"
DEPLOYED="$ROOT/.cache/deployed_inits"

inits_now() {
  "$ROOT/.venv/bin/python" -c '
import json
from pathlib import Path
p = Path("site/manifest.json")
m = json.loads(p.read_text()) if p.exists() else {}
print(
    m.get("hourly_init") or "",
    m.get("synoptic_init") or "",
    m.get("ensemble_init") or "",
    m.get("generated") or "",
)
'
}

EE_OK=1
{
  echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
  "$ROOT/.venv/bin/python" "$ROOT/cook_ee.py" --workers 8 --fields core
} > "$LOG" 2>&1 || EE_OK=0
{
  echo "==== ensemble $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
  "$ROOT/run_ensemble_vm.sh"
} >> "$LOG" 2>&1 || echo "ensemble failed" >> "$LOG"

cat "$LOG"
CUR="$(inits_now)"
if grep -q '^COOK_STATUS=updated$' "$LOG" || [ ! -f "$DEPLOYED" ] || [ "$(cat "$DEPLOYED")" != "$CUR" ]; then
  "$ROOT/deploy_pages.sh"
  printf '%s\n' "$CUR" > "$DEPLOYED"
fi
[ "$EE_OK" = 1 ]
