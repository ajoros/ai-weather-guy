#!/bin/sh
# Start the us-east1 cook VM, render 64-mean upper air, copy PNGs home once, stop.
# One cook + one tarball pull. Mid-batch scp recopies were the bill (VM hours + egress).
set -e
set -o pipefail
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:-weathernext3-joros}"
ZONE="${WN3_ENS_ZONE:-us-east1-b}"
NAME="${WN3_ENS_VM:-wn3-ens-cook}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export GOOGLE_CLOUD_PROJECT="$PROJECT"

gcloud() { command gcloud --project="$PROJECT" "$@"; }
ssh_vm() {
  gcloud compute ssh "$NAME" --zone="$ZONE" \
    --ssh-flag="-o ServerAliveInterval=30" \
    --ssh-flag="-o ServerAliveCountMax=20" \
    "$@"
}

PY="$ROOT/.venv/bin/python"
if ! "$PY" -c "import matplotlib; matplotlib.use('Agg')" >/dev/null 2>&1; then
  PY="$HOME/.venvs/weathernext3/bin/python"
fi

if [ -z "${WN3_ENS_ARGS:-}" ]; then
  CHECK="$("$PY" "$ROOT/cook_ensemble.py" --check --out "$ROOT/site" --pnw-out "$ROOT/site/pnw" --ca-out "$ROOT/site/ca" || true)"
  echo "$CHECK"
  if echo "$CHECK" | grep -q '^COOK_STATUS=noop$'; then
    echo "COOK_STATUS=noop"
    exit 0
  fi
fi

if ! gcloud services list --enabled --filter="config.name=compute.googleapis.com" --format="value(config.name)" | grep -q compute; then
  echo "Compute Engine API is off. Enable it, then rerun:" >&2
  echo "  gcloud services enable compute.googleapis.com --project=$PROJECT" >&2
  echo "COOK_STATUS=noop"
  exit 0
fi

if ! gcloud compute instances describe "$NAME" --zone="$ZONE" >/dev/null 2>&1; then
  echo "creating $NAME in $ZONE" >&2
  gcloud compute instances create "$NAME" \
    --zone="$ZONE" \
    --machine-type=e2-standard-4 \
    --boot-disk-size=40GB \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --scopes=cloud-platform
fi

status="$(gcloud compute instances describe "$NAME" --zone="$ZONE" --format='get(status)')"
if [ "$status" != "RUNNING" ]; then
  echo "starting $NAME" >&2
  gcloud compute instances start "$NAME" --zone="$ZONE"
fi

cleanup() {
  echo "stopping $NAME" >&2
  gcloud compute instances stop "$NAME" --zone="$ZONE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# SSH can race the guest agent.
i=0
while [ "$i" -lt 24 ]; do
  if ssh_vm --command="true" >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 5
done

ssh_vm --command="
set -e
if [ ! -x /opt/wn3/.venv/bin/python ]; then
  sudo mkdir -p /opt/wn3
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip
  sudo python3 -m venv /opt/wn3/.venv
  sudo /opt/wn3/.venv/bin/pip install -q xarray zarr obstore matplotlib numpy google-auth dask[array]
fi
sudo mkdir -p /opt/wn3/src /opt/wn3/site /opt/wn3/pnw /opt/wn3/ca /opt/wn3/cred
sudo chown -R \$(id -un):\$(id -gn) /opt/wn3/src /opt/wn3/site /opt/wn3/pnw /opt/wn3/ca /opt/wn3/cred
"

ADC="$HOME/.config/gcloud/application_default_credentials.json"
if [ ! -f "$ADC" ]; then
  echo "missing $ADC (gcloud auth application-default login)" >&2
  exit 1
fi
gcloud compute scp "$ADC" "$NAME:/opt/wn3/cred/adc.json" --zone="$ZONE"
gcloud compute scp \
  "$ROOT/cook_ensemble.py" "$ROOT/cook.py" "$ROOT/plot_wn3_stats.py" \
  "$NAME:/opt/wn3/src/" --zone="$ZONE"

: > "$ROOT/.cache/ensemble-cook.log"
echo "ensemble cook all leads" >&2
ssh_vm --command="
set -e
export GOOGLE_CLOUD_PROJECT=$PROJECT
export GOOGLE_APPLICATION_CREDENTIALS=/opt/wn3/cred/adc.json
cd /opt/wn3/src
/opt/wn3/.venv/bin/python cook_ensemble.py --out /opt/wn3/site --pnw-out /opt/wn3/pnw --ca-out /opt/wn3/ca --members 64 ${WN3_ENS_ARGS:-}
" </dev/null | tee -a "$ROOT/.cache/ensemble-cook.log"

if ! grep -q '^COOK_STATUS=updated$' "$ROOT/.cache/ensemble-cook.log"; then
  echo "COOK_STATUS=noop"
  exit 0
fi
INIT=$(sed -n 's/^ENSEMBLE_INIT=//p' "$ROOT/.cache/ensemble-cook.log" | tail -1)

# One compressed pull. Recopying frames/ after every batch was ~5.7× egress.
STAGE="${HOME}/Library/Application Support/ai-weather-guy/ens-in"
mkdir -p "$STAGE"
echo "packing remote frames" >&2
ssh_vm --command="
set -e
cd /opt/wn3
tar -czf /tmp/wn3-frames.tgz pnw/frames ca/frames site/frames
ls -l /tmp/wn3-frames.tgz
"
gcloud compute scp "$NAME:/tmp/wn3-frames.tgz" "$STAGE/wn3-frames.tgz" --zone="$ZONE"
rm -rf "$STAGE/unpacked"
mkdir -p "$STAGE/unpacked"
tar -C "$STAGE/unpacked" -xzf "$STAGE/wn3-frames.tgz"

copy_tree() {
  src="$1"
  dest="$2"
  [ -d "$src" ] || return 0
  mkdir -p "$dest"
  n=0
  while [ "$n" -lt 5 ]; do
    if cp -R "$src/." "$dest/"; then
      return 0
    fi
    n=$((n + 1))
    sleep $((n * 2))
  done
  echo "copy failed $dest" >&2
  return 0
}

copy_tree "$STAGE/unpacked/pnw/frames" "$ROOT/site/pnw/frames"
copy_tree "$STAGE/unpacked/ca/frames" "$ROOT/site/ca/frames"
if [ -s "$ROOT/site/manifest.json" ]; then
  copy_tree "$STAGE/unpacked/site/frames" "$ROOT/site/frames"
fi

# Stop the VM before local merge. Waiting on cook_ee used to bill idle hours.
trap - EXIT
cleanup
rm -f "$STAGE/wn3-frames.tgz"
rm -rf "$STAGE/unpacked"

if [ -n "$INIT" ] && [ -s "$ROOT/site/pnw/manifest.json" ]; then
  "$PY" "$ROOT/cook_ensemble.py" --merge-only --out "$ROOT/site/pnw" --init "$INIT"
fi
if [ -n "$INIT" ] && [ -d "$ROOT/site/ca/frames" ]; then
  "$PY" "$ROOT/cook_ensemble.py" --merge-only --out "$ROOT/site/ca" --init "$INIT"
fi
if [ -s "$ROOT/site/manifest.json" ] && [ -n "$INIT" ]; then
  "$PY" "$ROOT/cook_ensemble.py" --merge-only --out "$ROOT/site" --init "$INIT"
fi
echo "COOK_STATUS=updated"
