#!/bin/sh
# Local fallback: publish site/ to the gh-pages branch. CI uses Actions Pages instead.
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SITE="$ROOT/site"
ORIGIN="$(git -C "$ROOT" remote get-url origin)"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/wn3-pages.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

test -f "$SITE/index.html"
test -f "$SITE/manifest.json"
echo "staging JPEGs from $SITE" >&2
python3 "$ROOT/stage_pages.py" "$SITE" "$STAGE"

echo "pushing orphan gh-pages to $ORIGIN" >&2
git -C "$STAGE" init -q
git -C "$STAGE" add -A
git -C "$STAGE" commit -qm "Publish WeatherNext 3 maps for github.io"
git -C "$STAGE" branch -M gh-pages
git -C "$STAGE" remote add origin "$ORIGIN"
git -C "$STAGE" push -f origin gh-pages
echo "done." >&2
