#!/bin/sh
# Copy the committed tree on GitHub main into Dropbox as plain files.
# No .git: Dropbox syncing a shared .git between two Macs corrupts it.
# GitHub is the source of truth. The VM pulls main; this is a readable copy.
#
#   ./mirror_to_dropbox.sh                 # default Dropbox path
#   ./mirror_to_dropbox.sh /other/folder
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/Library/CloudStorage/Dropbox/weathernext3/ai-weather-guy}"

git -C "$ROOT" fetch -q origin main
SHA="$(git -C "$ROOT" rev-parse --short origin/main)"

mkdir -p "$DEST"
# Only wipe a folder this script made (has MIRROR.txt) or an empty one.
if [ -n "$(ls -A "$DEST")" ] && [ ! -f "$DEST/MIRROR.txt" ]; then
  echo "refusing: $DEST is not empty and has no MIRROR.txt" >&2
  exit 1
fi
find "$DEST" -mindepth 1 -delete
git -C "$ROOT" archive origin/main | tar -x -C "$DEST"
printf 'Read-only mirror of github.com/ajoros/ai-weather-guy main at %s, exported %s.\nEdit in a git clone, push to GitHub, then rerun mirror_to_dropbox.sh.\n' \
  "$SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$DEST/MIRROR.txt"
echo "mirrored $SHA -> $DEST"
