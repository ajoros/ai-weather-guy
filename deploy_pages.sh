#!/bin/sh
# Publish site/ onto the existing gh-pages branch.
# Wide maps stay as already published when site/manifest.json is an empty placeholder.
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SITE="$ROOT/site"
ORIGIN="$(git -C "$ROOT" remote get-url origin)"
PY="$ROOT/.venv/bin/python"
if ! "$PY" -c "import PIL.Image" >/dev/null 2>&1; then
  PY="$HOME/.venvs/weathernext3/bin/python"
fi
# Wait if another publish is mid-push. Do not start a second clone.
DEPLOCK="$ROOT/.cache/deploy.lockdir"
mkdir -p "$ROOT/.cache"
n=0
while ! mkdir "$DEPLOCK" 2>/dev/null; do
  oldpid=$(cat "$DEPLOCK/pid" 2>/dev/null || true)
  if [ -n "$oldpid" ] && ! kill -0 "$oldpid" 2>/dev/null; then
    rm -rf "$DEPLOCK"
    continue
  fi
  n=$((n + 1))
  if [ "$n" -gt 60 ]; then
    echo "deploy already running; giving up" >&2
    exit 1
  fi
  echo "waiting for other deploy ($n)" >&2
  sleep 5
done
echo $$ > "$DEPLOCK/pid"

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/wn3-pages.XXXXXX")"
WORK="$STAGE/pages"
trap 'rm -rf "$STAGE" "$DEPLOCK"' EXIT

test -f "$SITE/index.html"
if git ls-remote --heads "$ORIGIN" gh-pages | grep -q gh-pages; then
  echo "cloning published site" >&2
  git clone --depth 1 --branch gh-pages "$ORIGIN" "$WORK"
else
  git init -q "$WORK"
fi

echo "staging JPEGs from $SITE" >&2
"$PY" "$ROOT/runs_status.py"
"$PY" "$ROOT/stage_pages.py" "$SITE" "$WORK"
if [ ! -s "$WORK/manifest.json" ]; then
  echo "published manifest is missing; refusing to replace the live site" >&2
  exit 1
fi

git -C "$WORK" add -A
if git -C "$WORK" diff --cached --quiet; then
  echo "nothing to publish" >&2
  exit 0
fi
git -C "$WORK" commit -qm "Publish WeatherNext 3 maps for github.io"
if ! git -C "$WORK" remote get-url origin >/dev/null 2>&1; then
  git -C "$WORK" remote add origin "$ORIGIN"
  git -C "$WORK" branch -M gh-pages
fi
git -C "$WORK" push origin HEAD:gh-pages
echo "done." >&2
