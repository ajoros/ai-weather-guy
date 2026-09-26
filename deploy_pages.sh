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
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/wn3-pages.XXXXXX")"
WORK="$STAGE/pages"
trap 'rm -rf "$STAGE"' EXIT

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
