#!/bin/sh
# Start the us-east1 cook VM, render 64-mean upper air, copy PNGs home, stop the VM.
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:-weathernext3-joros}"
ZONE="${WN3_ENS_ZONE:-us-east1-b}"
NAME="${WN3_ENS_VM:-wn3-ens-cook}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export GOOGLE_CLOUD_PROJECT="$PROJECT"

gcloud() { command gcloud --project="$PROJECT" "$@"; }

if [ -z "${WN3_ENS_ARGS:-}" ]; then
  CHECK="$("$ROOT/.venv/bin/python" "$ROOT/cook_ensemble.py" --check --out "$ROOT/site" || true)"
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
  if gcloud compute ssh "$NAME" --zone="$ZONE" --command="true" >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 5
done

gcloud compute ssh "$NAME" --zone="$ZONE" --command="
set -e
if [ ! -x /opt/wn3/.venv/bin/python ]; then
  sudo mkdir -p /opt/wn3
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip
  sudo python3 -m venv /opt/wn3/.venv
  sudo /opt/wn3/.venv/bin/pip install -q xarray zarr obstore matplotlib numpy google-auth dask[array]
fi
sudo mkdir -p /opt/wn3/src /opt/wn3/site /opt/wn3/cred
sudo chown -R \$(id -un):\$(id -gn) /opt/wn3/src /opt/wn3/site /opt/wn3/cred
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

gcloud compute ssh "$NAME" --zone="$ZONE" --command="
set -e
export GOOGLE_CLOUD_PROJECT=$PROJECT
export GOOGLE_APPLICATION_CREDENTIALS=/opt/wn3/cred/adc.json
cd /opt/wn3/src
/opt/wn3/.venv/bin/python cook_ensemble.py --out /opt/wn3/site --members 64 ${WN3_ENS_ARGS:-}
" | tee "$ROOT/.cache/ensemble-cook.log"
if ! grep -q '^COOK_STATUS=updated$' "$ROOT/.cache/ensemble-cook.log"; then
  echo "COOK_STATUS=noop"
  exit 0
fi

for fid in h500 t850 wind925 wind700 wind500 wind300; do
  mkdir -p "$ROOT/site/frames/$fid"
  gcloud compute scp --recurse "$NAME:/opt/wn3/site/frames/$fid/." "$ROOT/site/frames/$fid/" --zone="$ZONE" || true
done

"$ROOT/.venv/bin/python" "$ROOT/cook_ensemble.py" --merge-only --out "$ROOT/site"
