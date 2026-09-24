#!/usr/bin/env python3
"""Copy the viewer and JPEG-compress cooked PNGs into a Pages folder."""

from __future__ import annotations

import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image


def stage(site: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(site / "index.html", dest / "index.html")
    (dest / ".nojekyll").write_text("", encoding="utf-8")
    m = json.loads((site / "manifest.json").read_text(encoding="utf-8"))
    for fr in m.get("frames", []):
        files = fr.get("files") or {}
        fr["files"] = {
            k: (v[:-4] + ".jpg" if isinstance(v, str) and v.endswith(".png") else v)
            for k, v in files.items()
        }
    (dest / "manifest.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")

    jobs = []
    for png in site.glob("frames/*/*.png"):
        jpg = dest / png.relative_to(site).with_suffix(".jpg")
        jpg.parent.mkdir(parents=True, exist_ok=True)
        jobs.append((png, jpg))

    def convert(pair: tuple[Path, Path]) -> None:
        src, jpg = pair
        with Image.open(src) as im:
            im.convert("RGB").save(jpg, "JPEG", quality=80, optimize=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(convert, jobs))
    return len(jobs)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: stage_pages.py SITE_DIR DEST_DIR", file=sys.stderr)
        return 2
    n = stage(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"converted {n} maps", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
