#!/bin/sh
# Start the us-east1 cook VM, render 64-mean upper air, copy PNGs home, stop the VM.
set -e
set -o pipefail
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:-weathernext3-joros}"
ZONE="${WN3_ENS_ZONE:-us-east1-b}"
NAME="${WN3_ENS_VM:-wn3-ens-cook}"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export GOOGLE_CLOUD_PROJECT="$PROJECT"

gcloud() { command gcloud --project="$PROJECT" "$@"; }

PY="$ROOT/.venv/bin/python"
if ! "$PY" -c "import matplotlib; matplotlib.use('Agg')" >/dev/null 2>&1; then
  PY="$HOME/.venvs/weathernext3/bin/python"
fi

if [ -z "${WN3_ENS_ARGS:-}" ]; then
  CHECK="$("$PY" "$ROOT/cook_ensemble.py" --check --out "$ROOT/site" --pnw-out "$ROOT/site/pnw" || true)"
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
sudo mkdir -p /opt/wn3/src /opt/wn3/site /opt/wn3/pnw /opt/wn3/cred
sudo chown -R \$(id -un):\$(id -gn) /opt/wn3/src /opt/wn3/site /opt/wn3/pnw /opt/wn3/cred
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

# One lead first so the PNW page shows upper air, then the rest in batches.
BATCHES=$("$PY" -c "
leads=list(range(6,361,6))
chunks=[[leads[0]]]+[leads[i:i+6] for i in range(1,len(leads),6)]
print('\n'.join(','.join(map(str,c)) for c in chunks))
")

: > "$ROOT/.cache/ensemble-cook.log"
updated=0
INIT=""
while IFS= read -r leads; do
  [ -n "$leads" ] || continue
  echo "ensemble batch $leads" >&2
  gcloud compute ssh "$NAME" --zone="$ZONE" --command="
set -e
export GOOGLE_CLOUD_PROJECT=$PROJECT
export GOOGLE_APPLICATION_CREDENTIALS=/opt/wn3/cred/adc.json
cd /opt/wn3/src
/opt/wn3/.venv/bin/python cook_ensemble.py --out /opt/wn3/site --pnw-out /opt/wn3/pnw --members 64 --leads $leads ${WN3_ENS_ARGS:-}
" </dev/null | tee -a "$ROOT/.cache/ensemble-cook.log"
  if grep -q '^COOK_STATUS=updated$' "$ROOT/.cache/ensemble-cook.log"; then
    updated=1
  fi
  batch_init=$(sed -n 's/^ENSEMBLE_INIT=//p' "$ROOT/.cache/ensemble-cook.log" | tail -1)
  if [ -n "$batch_init" ]; then
    INIT=$batch_init
  fi
  # scp into a non-Dropbox folder first. Writing straight into site/ hits errno 11
  # and used to abort the whole upper-air publish.
  STAGE="${HOME}/Library/Application Support/ai-weather-guy/ens-in"
  pull_frames() {
    remote="$1"
    dest="$2"
    mkdir -p "$STAGE/batch" "$dest"
    rm -rf "$STAGE/batch"
    mkdir -p "$STAGE/batch"
    gcloud compute scp --recurse "$remote" "$STAGE/batch/" --zone="$ZONE" </dev/null || return 0
    n=0
    while [ "$n" -lt 5 ]; do
      if cp -R "$STAGE/batch/." "$dest/"; then
        return 0
      fi
      n=$((n + 1))
      sleep $((n * 2))
    done
    echo "dropbox still busy copying $dest" >&2
    return 0
  }
  for fid in h500 t850 wind925 wind700 wind500 wind300; do
    pull_frames "$NAME:/opt/wn3/pnw/frames/$fid/." "$ROOT/site/pnw/frames/$fid"
    if [ -s "$ROOT/site/manifest.json" ]; then
      pull_frames "$NAME:/opt/wn3/site/frames/$fid/." "$ROOT/site/frames/$fid"
    fi
  done
  while pgrep -f "cook_ee.py" >/dev/null 2>&1; do
    echo "waiting for surface cook before manifest merge" >&2
    sleep 5
  done
  if [ -n "$INIT" ] && [ -s "$ROOT/site/pnw/manifest.json" ]; then
    "$PY" "$ROOT/cook_ensemble.py" --merge-only --out "$ROOT/site/pnw" --init "$INIT"
  fi
done <<EOF
$BATCHES
EOF

if [ "$updated" != 1 ]; then
  echo "COOK_STATUS=noop"
  exit 0
fi
if [ -s "$ROOT/site/manifest.json" ] && [ -n "$INIT" ]; then
  "$PY" "$ROOT/cook_ensemble.py" --merge-only --out "$ROOT/site" --init "$INIT"
fi
echo "COOK_STATUS=updated"
