#!/bin/sh
# Cook on this Mac; deploy github.io when a cook finishes or local inits
# are ahead of the last publish (a crashed run used to skip forever).
# EE and ensemble use separate locks so a long VM job cannot skip new hourlies.
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-weathernext3-joros}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
# Temp + matplotlib scratch stay off Dropbox so cooks do not EDEADLK mid-write.
export TMPDIR="${TMPDIR:-$HOME/Library/Application Support/ai-weather-guy/tmp}"
mkdir -p "$TMPDIR"
cd "$ROOT"
mkdir -p "$ROOT/.cache"
EE_LOG="$ROOT/.cache/cook-ee.log"
ENS_LOG="$ROOT/.cache/cook-ens.log"
LOG="$ROOT/.cache/cook-latest.log"
DEPLOYED="$ROOT/.cache/deployed_inits"

take_lock() {
  dir="$1"
  if mkdir "$dir" 2>/dev/null; then
    echo $$ > "$dir/pid"
    return 0
  fi
  oldpid=$(cat "$dir/pid" 2>/dev/null || true)
  if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
    return 1
  fi
  rm -rf "$dir"
  mkdir "$dir"
  echo $$ > "$dir/pid"
}

drop_lock() {
  rm -rf "$1"
}

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

maybe_deploy() {
  status_log="$1"
  CUR="$(inits_now)"
  if grep -q '^COOK_STATUS=updated$' "$status_log" 2>/dev/null \
    || [ ! -f "$DEPLOYED" ] \
    || [ "$(cat "$DEPLOYED")" != "$CUR" ]; then
    "$ROOT/deploy_pages.sh"
    printf '%s\n' "$CUR" > "$DEPLOYED"
  fi
}

EE_OK=1
if take_lock "$ROOT/.cache/ee.lockdir"; then
  {
    echo "==== ee $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
    "$ROOT/.venv/bin/python" "$ROOT/cook_ee.py" --workers 8 --fields core --pnw-out "$ROOT/site/pnw" --ca-out "$ROOT/site/ca"
  } > "$EE_LOG" 2>&1 || EE_OK=0
  cat "$EE_LOG"
  maybe_deploy "$EE_LOG"
  drop_lock "$ROOT/.cache/ee.lockdir"
else
  echo "ee cook already running" >&2
fi

if pgrep -f "$ROOT/run_ensemble_vm.sh" >/dev/null 2>&1; then
  echo "ensemble cook already running" >&2
elif take_lock "$ROOT/.cache/ens.lockdir"; then
  {
    echo "==== ensemble $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
    "$ROOT/run_ensemble_vm.sh"
  } > "$ENS_LOG" 2>&1 || echo "ensemble failed" >> "$ENS_LOG"
  cat "$ENS_LOG"
  maybe_deploy "$ENS_LOG"
  drop_lock "$ROOT/.cache/ens.lockdir"
else
  echo "ensemble cook already running" >&2
fi

{
  echo "==== $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
  cat "$EE_LOG" 2>/dev/null || true
  cat "$ENS_LOG" 2>/dev/null || true
} > "$LOG" || true

[ "$EE_OK" = 1 ]
