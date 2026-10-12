#!/bin/bash
# Cook on the us-east1 VM, publish gh-pages, power off.
# Replaces update_local.sh + run_ensemble_vm.sh (those two drove the cook from a Mac).
# Runs as the instance startup-script. WN3_NO_SHUTDOWN=1 keeps the VM up for debugging.
set -u
ROOT=/opt/wn3/src
LOG=/var/log/wn3-cook.log
exec > >(tee -a "$LOG") 2>&1
echo "==== boot $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="

finish() {
  code=$?
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
git pull --ff-only origin main || echo "git pull failed; cooking with the tree already here"

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

# Surface maps from the free stats Zarr. Earth Engine is past its monthly quota.
"$PY" cook.py --fields core --pnw-out "$SITE/pnw" --ca-out "$SITE/ca" --nepac-out "$SITE/nepac" || echo "surface cook failed"

CHECK="$("$PY" cook_ensemble.py --check --out "$SITE" --pnw-out "$SITE/pnw" --ca-out "$SITE/ca" --nepac-out "$SITE/nepac" || true)"
echo "$CHECK"
if echo "$CHECK" | grep -q '^COOK_STATUS=needed$'; then
  "$PY" cook_ensemble.py --out "$SITE" --pnw-out "$SITE/pnw" --ca-out "$SITE/ca" --nepac-out "$SITE/nepac" --members 64 || echo "ensemble cook failed"
fi

# deploy_pages.sh exits 0 with "nothing to publish" when no JPEG changed.
"$ROOT/deploy_pages.sh"
