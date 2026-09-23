#!/bin/sh
# Publish site/ to github.io. main stays thin; Pages gets one JPEG snapshot.
# ponytail: JPEG q80 is the same maps at about half the PNG bytes.
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SITE="$ROOT/site"
ORIGIN="$(git -C "$ROOT" remote get-url origin)"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/wn3-pages.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

test -f "$SITE/index.html"
test -f "$SITE/manifest.json"

echo "staging JPEGs from $SITE" >&2
cp "$SITE/index.html" "$STAGE/"
python3 - "$SITE" "$STAGE" <<'PY'
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

site, stage = Path(sys.argv[1]), Path(sys.argv[2])
m = json.loads((site / "manifest.json").read_text(encoding="utf-8"))
for fr in m.get("frames", []):
    files = fr.get("files") or {}
    fr["files"] = {
        k: (v[:-4] + ".jpg" if isinstance(v, str) and v.endswith(".png") else v)
        for k, v in files.items()
    }
(stage / "manifest.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")

jobs = []
for png in site.glob("frames/*/*.png"):
    dest = stage / png.relative_to(site).with_suffix(".jpg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    jobs.append((png, dest))


def convert(pair: tuple[Path, Path]) -> None:
    png, dest = pair
    subprocess.run(
        ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "80", str(png), "--out", str(dest)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(convert, jobs))
print(f"converted {len(jobs)} maps", flush=True)
PY

echo "pushing orphan gh-pages to $ORIGIN" >&2
git -C "$STAGE" init -q
git -C "$STAGE" add -A
git -C "$STAGE" commit -qm "Publish WeatherNext 3 maps for github.io"
git -C "$STAGE" branch -M gh-pages
git -C "$STAGE" remote add origin "$ORIGIN"
git -C "$STAGE" push -f origin gh-pages
echo "done. enable Pages on branch gh-pages / (root) if the URL 404s." >&2
