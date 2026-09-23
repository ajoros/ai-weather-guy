#!/usr/bin/env python3
"""Build short Discord-ready MP4 loops from cooked frames. ponytail: 8 fps + 960w keeps each clip under Discord's 25 MB free cap."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
OUT = ROOT / "previews"
MANIFEST = json.loads((SITE / "manifest.json").read_text())


def encode(pngs: list[Path], dest: Path, fps: int = 8, width: int = 960) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    lst = dest.with_suffix(".ffconcat")
    dur = 1.0 / fps
    lines = ["ffconcat version 1.0"]
    for p in pngs:
        lines.append(f"file '{p.resolve()}'")
        lines.append(f"duration {dur:.4f}")
    lines.append(f"file '{pngs[-1].resolve()}'")
    lst.write_text("\n".join(lines) + "\n")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(lst),
        "-vf",
        f"scale={width}:-2",
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "26",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    print("encode", dest.name, len(pngs), "frames", flush=True)
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        raise SystemExit(r.returncode)
    lst.unlink(missing_ok=True)
    print("  ", dest.stat().st_size // 1024, "KB", flush=True)


def field_pngs(field: str) -> list[Path]:
    return [SITE / fr["files"][field] for fr in MANIFEST["frames"]]


def stack_2x2(clips: list[Path], dest: Path) -> None:
    # All four already same fps/count; scale each cell then tile.
    ins: list[str] = []
    for p in clips:
        ins += ["-i", str(p)]
    filt = (
        "[0:v]scale=640:304:force_original_aspect_ratio=decrease,pad=640:304:(ow-iw)/2:(oh-ih)/2,setsar=1[a];"
        "[1:v]scale=640:304:force_original_aspect_ratio=decrease,pad=640:304:(ow-iw)/2:(oh-ih)/2,setsar=1[b];"
        "[2:v]scale=640:304:force_original_aspect_ratio=decrease,pad=640:304:(ow-iw)/2:(oh-ih)/2,setsar=1[c];"
        "[3:v]scale=640:304:force_original_aspect_ratio=decrease,pad=640:304:(ow-iw)/2:(oh-ih)/2,setsar=1[d];"
        "[a][b]hstack=inputs=2[top];"
        "[c][d]hstack=inputs=2[bot];"
        "[top][bot]vstack=inputs=2"
    )
    cmd = [
        "ffmpeg",
        "-y",
        *ins,
        "-filter_complex",
        filt,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "26",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    print("encode", dest.name, "2x2", flush=True)
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
        raise SystemExit(r.returncode)
    print("  ", dest.stat().st_size // 1024, "KB", flush=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    named = [
        ("wn3_temp.mp4", "station_t"),
        ("wn3_qpf6.mp4", "qpf6_imerg"),
        ("wn3_slp.mp4", "slp"),
        ("wn3_wind.mp4", "wind10"),
    ]
    paths = []
    for name, field in named:
        dest = OUT / name
        encode(field_pngs(field), dest)
        paths.append(dest)
    stack_2x2(paths, OUT / "wn3_page_2x2.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
