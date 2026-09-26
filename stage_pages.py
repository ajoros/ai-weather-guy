#!/usr/bin/env python3
"""Copy the viewer and JPEG-compress cooked PNGs into a Pages folder."""

from __future__ import annotations

import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image


def stage(site: Path, dest: Path, *, root: bool = True) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(site / "index.html", dest / "index.html")
    if root:
        logo = site / "logo-mark.png"
        if logo.is_file():
            shutil.copy2(logo, dest / "logo-mark.png")
        (dest / ".nojekyll").write_text("", encoding="utf-8")
    manifest_path = site / "manifest.json"
    if manifest_path.stat().st_size == 0:
        raise SystemExit(f"{manifest_path} is an empty placeholder")
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    keep = {v["id"] for v in m.get("variables") or []}
    for fr in m.get("frames", []):
        files = fr.get("files") or {}
        if keep:
            files = {k: v for k, v in files.items() if k in keep}
        fr["files"] = {
            k: (v[:-4] + ".jpg" if isinstance(v, str) and v.endswith(".png") else v)
            for k, v in files.items()
        }
    (dest / "manifest.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")

    jobs = []
    folders = [site / "frames" / fid for fid in keep] if keep else list((site / "frames").glob("*"))
    for folder in folders:
        for png in folder.glob("f[0-9][0-9][0-9].png"):
            jpg = dest / png.relative_to(site).with_suffix(".jpg")
            jpg.parent.mkdir(parents=True, exist_ok=True)
            jobs.append((png, jpg))

    def convert(pair: tuple[Path, Path]) -> None:
        src, jpg = pair
        with Image.open(src) as im:
            im.convert("RGB").save(jpg, "JPEG", quality=85, optimize=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(convert, jobs))
    return len(jobs)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: stage_pages.py SITE_DIR DEST_DIR", file=sys.stderr)
        return 2
    site = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    wide = site / "manifest.json"
    if wide.is_file() and wide.stat().st_size > 0:
        n += stage(site, dest, root=True)
    else:
        shutil.copy2(site / "index.html", dest / "index.html")
        print(f"skipped wide frames; {wide} is empty", flush=True)
    runs_html = site / "runs" / "index.html"
    if runs_html.is_file():
        runs_dest = dest / "runs"
        runs_dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runs_html, runs_dest / "index.html")
        status = site / "runs" / "status.json"
        if status.is_file():
            shutil.copy2(status, runs_dest / "status.json")
    pnw = site / "pnw" / "manifest.json"
    if pnw.is_file() and pnw.stat().st_size > 0:
        pnw_dest = dest / "pnw"
        if pnw_dest.exists():
            shutil.rmtree(pnw_dest)
        n += stage(site / "pnw", pnw_dest, root=False)
    print(f"converted {n} maps", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
