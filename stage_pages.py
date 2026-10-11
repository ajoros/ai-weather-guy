#!/usr/bin/env python3
"""Copy the viewer and JPEG-compress cooked PNGs into a Pages folder."""

from __future__ import annotations

import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image


def _init_text(png: Path) -> str | None:
    try:
        text = png.with_suffix(".init").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _load_stamps(dest: Path) -> dict:
    path = dest / ".frame-stamps.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _jpg_fresh(png: Path, jpg: Path, stamps: dict, rel: str) -> bool:
    """Skip a JPEG only when it was built from this PNG's init stamp.

    A gh-pages checkout sets every JPEG mtime to 'now', which is newer than
    the PNG, so mtime cannot be the check. Frames with no stamp still use mtime.
    """
    try:
        if not jpg.is_file() or jpg.stat().st_size <= 1000:
            return False
    except OSError:
        return False
    want = _init_text(png)
    if want is not None:
        return stamps.get(rel) == want
    try:
        return jpg.stat().st_mtime >= png.stat().st_mtime
    except OSError:
        return False


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

    wanted: set[str] = set()
    for fr in m.get("frames", []):
        for rel in (fr.get("files") or {}).values():
            if isinstance(rel, str):
                wanted.add(rel)

    stamps = _load_stamps(dest)
    jobs = []
    for rel in wanted:
        if not rel.endswith(".jpg"):
            continue
        png = site / (rel[:-4] + ".png")
        jpg = dest / rel
        if not png.is_file() or _jpg_fresh(png, jpg, stamps, rel):
            continue
        jpg.parent.mkdir(parents=True, exist_ok=True)
        jobs.append((rel, png, jpg))

    frames_dir = dest / "frames"
    if frames_dir.is_dir():
        for old in frames_dir.rglob("*.jpg"):
            if old.relative_to(dest).as_posix() not in wanted:
                old.unlink()

    def convert(job: tuple[str, Path, Path]) -> None:
        _rel, src, jpg = job
        with Image.open(src) as im:
            im.convert("RGB").save(jpg, "JPEG", quality=85, optimize=True)

    if jobs:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(convert, jobs))
        for rel, png, _jpg in jobs:
            want = _init_text(png)
            if want:
                stamps[rel] = want
        (dest / ".frame-stamps.json").write_text(json.dumps(stamps, indent=2) + "\n", encoding="utf-8")
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
    for name in ("pnw", "ca"):
        man = site / name / "manifest.json"
        if man.is_file() and man.stat().st_size > 0:
            n += stage(site / name, dest / name, root=False)
    print(f"converted {n} maps", flush=True)
    return 0


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        png = root / "f.png"
        jpg = root / "f.jpg"
        png.write_bytes(b"x")
        png.with_suffix(".init").write_text("stats 1\n")
        jpg.write_bytes(b"y" * 1001)
        assert not _jpg_fresh(png, jpg, {}, "f.jpg")
        assert _jpg_fresh(png, jpg, {"f.jpg": "stats 1"}, "f.jpg")
        assert not _jpg_fresh(png, jpg, {"f.jpg": "stats 0"}, "f.jpg")
    print("stage stamps ok")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--check":
        _self_check()
        raise SystemExit(0)
    raise SystemExit(main())
