#!/usr/bin/env python3
"""Read site manifests → site/runs/status.json for the runs board."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from cook import ENSEMBLE_IDS, FIELDS, PAGE_IDS, SITE

HOURLY_LEADS = set(range(1, 49))
SYN_LEADS = set(range(54, 361, 6))
ENS_LEADS = set(range(6, 361, 6))
RUN_LABELS = {
    "station_t": "Station T",
    "qpf1_imerg": "1-h IMERG",
    "qpf_acc": "QPF total",
    "slp": "SLP",
    "wind10": "10 m wind",
    "wind10_p90": "10 m gust",
    "h500": "500H",
    "t850": "850T",
    "wind925": "925 wind",
    "wind700": "700 wind",
    "wind500": "500 wind",
    "wind300": "300 wind",
}


def _synoptic_init(iso: str) -> bool:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt.minute == 0 and dt.second == 0 and dt.hour % 6 == 0


def _want(fid: str, leads: set[int]) -> int:
    if fid in ENSEMBLE_IDS:
        return 60 if leads & ENS_LEADS else 0
    n = 0
    if leads & HOURLY_LEADS:
        n += 48
    if leads & SYN_LEADS:
        n += 52
    return n


def scan_manifest(path: Path) -> dict[str, dict[str, dict[str, int]]]:
    """fid → init → {n, want} from one manifest."""
    empty = {fid: {} for fid in PAGE_IDS}
    if not path.is_file() or path.stat().st_size == 0:
        return empty
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    by: dict[str, dict[str, set[int]]] = {fid: defaultdict(set) for fid in PAGE_IDS}
    for fr in m.get("frames") or []:
        init = fr.get("init")
        lead = fr.get("lead")
        if not init or lead is None:
            continue
        for fid in fr.get("files") or {}:
            if fid not in by:
                continue
            # Hourly frames reuse the last 6-h upper-air map; don't mark those as a new run.
            if fid in ENSEMBLE_IDS and not _synoptic_init(str(init)):
                continue
            by[fid][str(init)].add(int(lead))
    return {
        fid: {init: {"n": len(leads), "want": _want(fid, leads)} for init, leads in cells.items()}
        for fid, cells in by.items()
    }


def _merge(
    a: dict[str, dict[str, dict[str, int]]], b: dict[str, dict[str, dict[str, int]]]
) -> dict[str, dict[str, dict[str, int]]]:
    merged: dict[str, dict[str, dict[str, int]]] = {}
    for fid in PAGE_IDS:
        cells: dict[str, dict[str, int]] = {}
        for src in (a.get(fid) or {}, b.get(fid) or {}):
            for init, cell in src.items():
                old = cells.get(init)
                if old is None or cell["n"] > old["n"]:
                    cells[init] = cell
        merged[fid] = cells
    return merged


def collect_runs(site: Path) -> dict:
    wide = scan_manifest(site / "manifest.json")
    pnw = site / "pnw" / "manifest.json"
    if pnw.is_file():
        wide = _merge(wide, scan_manifest(pnw))
    return {
        "fields": [
            {
                "id": fid,
                "label": RUN_LABELS.get(fid) or FIELDS[fid][1],
                "inits": wide.get(fid) or {},
            }
            for fid in PAGE_IDS
        ]
    }


def write_status(site: Path = SITE) -> Path:
    dest = site / "runs" / "status.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(collect_runs(site), indent=2) + "\n", encoding="utf-8")
    return dest


def main() -> None:
    path = write_status()
    print(f"wrote {path}", flush=True)


if __name__ == "__main__":
    main()
