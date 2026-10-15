#!/bin/bash
# Cook on the us-east1 VM, publish gh-pages, power off.
# Replaces update_local.sh + run_ensemble_vm.sh (those two drove the cook from a Mac).
# Runs as the instance startup-script. WN3_NO_SHUTDOWN=1 keeps the VM up for debugging.
# Test run (vm_test_run.sh): instance metadata wn3-mode=test cooks, skips the publish,
# and stays up. The last line is RUN_RESULT=ok or RUN_RESULT=failed.
set -u
ROOT=/opt/wn3/src
LOG=/var/log/wn3-cook.log
exec > >(tee -a "$LOG") 2>&1
meta() {
  curl -sf -H 'Metadata-Flavor: Google' \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1" 2>/dev/null || true
}
MODE="${WN3_MODE:-$(meta wn3-mode)}"
MODE="${MODE:-live}"
RUN_TAG="${WN3_RUN:-$(meta wn3-run)}"
echo "==== boot $(date -u +%Y-%m-%dT%H:%M:%SZ) mode=$MODE run=${RUN_TAG:-none} ===="
if [ "$MODE" = "test" ]; then
  export WN3_NO_SHUTDOWN=1
fi
fail=0

finish() {
  code=$?
  if [ "$fail" != 0 ]; then
    code=1
  fi
  echo "RUN_RESULT=$([ "$code" = 0 ] && echo ok || echo failed)"
  if [ "${WN3_NO_SHUTDOWN:-}" = "1" ]; then
    echo "WN3_NO_SHUTDOWN set; staying up (exit $code)"
    exit "$code"
  fi
  echo "shutdown (exit $code)"
  shutdown -h now
}
trap finish EXIT

export HOME=/root
export GOOGLE_CLOUD_PROJECT=weathernext3-joros
# ponytail: WeatherNext grants the EE asset and the Zarr bucket to the Google account, not to a
# service account, so the VM cooks with a copy of that account's ADC (what run_ensemble_vm.sh
# scp'd up each run). Upgrade path: get the compute SA granted, then drop this line.
export GOOGLE_APPLICATION_CREDENTIALS=/opt/wn3/cred/adc.json
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$ROOT"

# The clone is owned by the user who created it; root is the startup-script user.
if ! git config --global --get-all safe.directory 2>/dev/null | grep -qx "$ROOT"; then
  git config --global --add safe.directory "$ROOT"
fi
before=$(git rev-parse HEAD)
git pull --ff-only origin main || echo "git pull failed; cooking with the tree already here"
if [ "$(git rev-parse HEAD)" != "$before" ]; then
  exec "$ROOT/cloud_boot.sh"
fi

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv git
  python3 -m venv "$ROOT/.venv"
fi
# ponytail: pip on every boot is a few seconds when nothing changed and keeps deps in step with main.
"$ROOT/.venv/bin/pip" install -q -r requirements.txt

SITE="$ROOT/site"
mkdir -p "$ROOT/.cache"

publish() {
  if [ "$MODE" = "test" ]; then
    echo "test run: not publishing"
    return 0
  fi
  # deploy_pages.sh exits 0 with "nothing to publish" when no JPEG changed.
  "$ROOT/deploy_pages.sh" || { echo "publish failed"; fail=1; }
}

# Surface maps first, so they go live while the upper-air cook is still drawing.
"$PY" cook.py --fields core --pnw-out "$SITE/pnw" --ca-out "$SITE/ca" --nepac-out "$SITE/nepac" || { echo "surface cook failed"; fail=1; }
publish

CHECK="$("$PY" cook_ensemble.py --check --out "$SITE" --pnw-out "$SITE/pnw" --ca-out "$SITE/ca" --nepac-out "$SITE/nepac" || true)"
echo "$CHECK"
if echo "$CHECK" | grep -q '^COOK_STATUS=needed$'; then
  "$PY" cook_ensemble.py --out "$SITE" --pnw-out "$SITE/pnw" --ca-out "$SITE/ca" --nepac-out "$SITE/nepac" --members 64 || { echo "ensemble cook failed"; fail=1; }
  publish
fi
