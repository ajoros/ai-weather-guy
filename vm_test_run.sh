#!/bin/sh
# Start the cook VM for one test run: cook, do not publish, stay up.
# Prints the VM log live and ends with RUN_RESULT=ok or RUN_RESULT=failed.
# The VM stays on afterwards so the frames can be inspected. Stop it with:
#   gcloud compute instances stop wn3-ens-cook --zone=us-east1-b --project=weathernext3-joros
set -eu
P=weathernext3-joros
Z=us-east1-b
VM=wn3-ens-cook
TAG="test-$(date -u +%Y%m%dT%H%M%SZ)"
G="gcloud compute"

$G instances add-metadata "$VM" --zone="$Z" --project="$P" --metadata="wn3-mode=test,wn3-run=$TAG" >/dev/null
$G instances start "$VM" --zone="$Z" --project="$P" --quiet >/dev/null
echo "started $VM, run $TAG"

n=0
until $G ssh "$VM" --zone="$Z" --project="$P" --command=true >/dev/null 2>&1; do
  n=$((n + 1))
  if [ "$n" -gt 36 ]; then
    echo "VM did not answer ssh in 3 minutes" >&2
    exit 1
  fi
  sleep 5
done

# Print from this run's boot line until its RUN_RESULT. Older runs in the log are skipped.
$G ssh "$VM" --zone="$Z" --project="$P" --command="tail -n 2000 -F /var/log/wn3-cook.log | awk '/^==== boot .*run=$TAG/{s=1} s{print; fflush()} s && /^RUN_RESULT=/{exit}'"

# The boot script already read the mode, so the next timer start is a normal publish again.
$G instances remove-metadata "$VM" --zone="$Z" --project="$P" --keys=wn3-mode,wn3-run >/dev/null
echo "VM is still on for inspection."
