#!/usr/bin/env python3
"""Faster cook: Earth Engine thumbs → same site/ stacked viewer.

Google crops and renders the NA+Pacific window. We only download PNGs
and add the NWS colorbar. Same frames/manifest as cook.py.

    export GOOGLE_CLOUD_PROJECT=weathernext3-joros
    .venv/bin/python cook_ee.py
    .venv/bin/python cook_ee.py --fields core --leads 1,2,3
    # default: latest hourly init for F+1–48, latest 15-day synoptic for F+54–360
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
from google.auth import default
from google.auth.transport.requests import Request

import ee

from cook import (
    FIELDS,
    LAT0,
    LAT1,
    LON0,
    LON1,
    PALETTES,
    SITE,
    display_leads,
    parse_fields,
    write_manifest,
)

COL_01 = "projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p1deg"
COL_05 = "projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p05deg"
THUMB_W, THUMB_H = 1400, 506

CONV = {
    "k_to_f": lambda img: img.multiply(1.8).subtract(459.67),
    "m_to_in": lambda img: img.multiply(39.37007874),
    "ms_to_mph": lambda img: img.multiply(2.23693629),
    "pa_to_hpa": lambda img: img.divide(100.0),
    "frac_to_pct": lambda img: img.multiply(100.0),
}
CONV_FOR = {
    "station_head_temperature_2m_mean": "k_to_f",
    "station_head_dewpoint_temperature_2m_mean": "k_to_f",
    "temperature_2m_mean": "k_to_f",
    "dewpoint_temperature_2m_mean": "k_to_f",
    "imerg_tp_1hr_mean": "m_to_in",
    "imerg_tp_1hr_p90": "m_to_in",
    "total_precipitation_1hr_mean": "m_to_in",
    "experimental_tp_1hr_mean": "m_to_in",
    "mean_sea_level_pressure_mean": "pa_to_hpa",
    "wind_speed_10m_mean": "ms_to_mph",
    "sea_surface_temperature_mean": "k_to_f",
    "total_cloud_cover_mean": "frac_to_pct",
    "low_cloud_cover_mean": "frac_to_pct",
    "medium_cloud_cover_mean": "frac_to_pct",
    "high_cloud_cover_mean": "frac_to_pct",
}


def ee_init(project_id: str) -> None:
    scopes = (
        "https://www.googleapis.com/auth/earthengine",
        "https://www.googleapis.com/auth/cloud-platform",
    )
    creds, _ = default(scopes=scopes)
    if not creds.valid:
        creds.refresh(Request())
    ee.Initialize(credentials=creds, project=project_id)


def iso_init(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def start_for_lead(lead: int, hourly: str, synoptic: str) -> str:
    """F+1–48 from the newest init (often an interim hourly). Day 3–15 from synoptic."""
    return hourly if lead <= 48 else synoptic


def has_forecast(col: ee.ImageCollection, start: str, hour: int) -> bool:
    n = (
        col.filter(ee.Filter.eq("start_time", start))
        .filter(ee.Filter.eq("forecast_hour", hour))
        .size()
        .getInfo()
    )
    return bool(n)


def latest_run(
    col: ee.ImageCollection,
    *,
    need_hour: int,
    step_h: int,
    lookback: int,
    lag_h: float,
) -> str | None:
    now = datetime.now(timezone.utc) - timedelta(hours=lag_h)
    hour = (now.hour // step_h) * step_h
    t = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    for _ in range(lookback):
        start = iso_init(t)
        if has_forecast(col, start, need_hour):
            return start
        print(f"skip missing {start} (need F+{need_hour})", flush=True)
        t -= timedelta(hours=step_h)
    return None


def latest_hourly(col: ee.ImageCollection) -> str | None:
    # Need F+48 so a half-ingested new init does not replace a complete 48-h loop.
    return latest_run(col, need_hour=48, step_h=1, lookback=36, lag_h=0)


def latest_synoptic(col: ee.ImageCollection) -> str | None:
    return latest_run(col, need_hour=360, step_h=6, lookback=16, lag_h=0)


def resolve_inits(col: ee.ImageCollection, forced: str) -> tuple[str, str, int]:
    """Newest hourly init, newest 360-h synoptic, long-range horizon."""
    if forced:
        hz = 360 if has_forecast(col, forced, 360) else 48
        syn = forced if hz == 360 else (latest_synoptic(col) or forced)
        long_h = 360 if has_forecast(col, syn, 360) else 48
        return forced, syn, long_h
    hourly = latest_hourly(col)
    synoptic = latest_synoptic(col)
    if not hourly and not synoptic:
        raise SystemExit("No run in Earth Engine yet.")
    if not hourly:
        hourly = synoptic
    if not synoptic:
        return hourly, hourly, 48
    return hourly, synoptic, 360


def classify(img: ee.Image, bounds: np.ndarray) -> ee.Image:
    out = ee.Image.constant(0).rename("b").toFloat()
    last = len(bounds) - 2
    for i in range(len(bounds) - 1):
        lo, hi = float(bounds[i]), float(bounds[i + 1])
        out = out.where(img.gte(lo).And(img.lt(hi)), i)
    return out.where(img.gte(float(bounds[-1])), last)


def paint_lines(rgb: ee.Image) -> ee.Image:
    countries = ee.FeatureCollection("USDOS/LSIB_SIMPLE/2017")
    states = ee.FeatureCollection("TIGER/2018/States")
    return rgb.paint(countries, "111111", 1).paint(states, "444444", 1)


def thumb_params() -> dict:
    dx = (LON1 - LON0) / THUMB_W
    dy = (LAT1 - LAT0) / THUMB_H
    return {
        "dimensions": [THUMB_W, THUMB_H],
        "crs": "EPSG:4326",
        # ponytail: 0–360 strip so Pacific+NA is one image. If EE rejects
        # lon>180, stitch two -180/180 thumbs instead.
        "crsTransform": [dx, 0, LON0, 0, -dy, LAT1],
        "format": "png",
    }


def field_image(start: str, hour: int, spec: tuple) -> ee.Image:
    _fid, _label, var, _conv, pal, grid, accum = spec
    col_id = COL_05 if grid == "0p05" else COL_01
    col = ee.ImageCollection(col_id).filter(ee.Filter.eq("start_time", start))
    hours = list(range(max(1, hour - max(accum, 1) + 1), hour + 1)) if accum else [hour]
    ic = col.filter(ee.Filter.inList("forecast_hour", hours)).select(var)
    img = ic.sum() if accum > 1 else ic.first()
    img = CONV[CONV_FOR[var]](img)
    rgb = classify(img, PALETTES[pal]["bounds"]).visualize(
        min=0,
        max=len(PALETTES[pal]["colors"]) - 1,
        palette=list(PALETTES[pal]["colors"]),
    )
    return paint_lines(rgb)


def compute_grid(img: ee.Image, dx: float):
    width = int(round((LON1 - LON0) / dx))
    height = int(round((LAT1 - LAT0) / dx))
    arr = ee.data.computePixels(
        {
            "expression": img,
            "fileFormat": "NUMPY_NDARRAY",
            "grid": {
                "dimensions": {"width": width, "height": height},
                "affineTransform": {
                    "scaleX": dx,
                    "shearX": 0,
                    "translateX": LON0,
                    "shearY": 0,
                    "scaleY": -dx,
                    "translateY": LAT1,
                },
                "crsCode": "EPSG:4326",
            },
        }
    )
    lon = LON0 + (np.arange(width) + 0.5) * dx
    lat = LAT1 - (np.arange(height) + 0.5) * dx
    return lon, lat, arr


def hourly_01(start: str, hour: int) -> ee.Image:
    return (
        ee.ImageCollection(COL_01)
        .filter(ee.Filter.eq("start_time", start))
        .filter(ee.Filter.eq("forecast_hour", hour))
        .first()
    )


def wrap_thumb(
    raw: Path,
    dest: Path,
    title: str,
    palette: str,
    *,
    contours=None,
    barbs=None,
) -> None:
    pal = PALETTES[palette]
    arr = plt.imread(raw)
    fig, ax = plt.subplots(figsize=(13.5, 6.4), dpi=110)
    ax.imshow(arr, extent=[LON0, LON1, LAT0, LAT1], origin="upper", aspect="auto")
    if contours is not None:
        lon, lat, z = contours
        cs = ax.contour(
            lon,
            lat,
            z,
            levels=np.arange(960, 1060, 4),
            colors="k",
            linewidths=0.35,
            alpha=0.75,
        )
        ax.clabel(cs, [lv for lv in cs.levels if lv % 8 == 0], fmt="%d", fontsize=6)
    if barbs is not None:
        lon, lat, u, v = barbs
        xx, yy = np.meshgrid(lon, lat)
        ax.barbs(
            xx,
            yy,
            u,
            v,
            length=5.4,
            linewidth=0.4,
            color="0.1",
            barb_increments={"half": 5, "full": 10, "flag": 50},
        )
    ax.set_title(title, loc="left", fontsize=11)
    ax.set_xlabel("longitude (0–360)", fontsize=8)
    ax.set_ylabel("latitude", fontsize=8)
    ax.tick_params(labelsize=8)
    cmap = mcolors.ListedColormap(list(pal["colors"]))
    norm = mcolors.BoundaryNorm(pal["bounds"], cmap.N)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    fig.colorbar(
        sm,
        ax=ax,
        shrink=0.78,
        label=pal["label"],
        pad=0.015,
        ticks=pal.get("ticks", pal["bounds"]),
        extend="both",
    )
    fig.tight_layout()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(dest, facecolor="white")
    plt.close(fig)


def fetch_one(start: str, hour: int, spec: tuple, dest: Path, force: bool) -> str:
    fid, label, _var, _c, pal, _g, accum = spec
    stamp = dest.with_suffix(".init")
    # ponytail: sidecar so a leftover PNG cannot be relabeled as a newer init.
    if (
        dest.exists()
        and dest.stat().st_size > 1000
        and not force
        and stamp.exists()
        and stamp.read_text().strip() == start
    ):
        return f"skip {fid} f{hour:03d}"
    extra = f"  ({hour}h window)" if accum == 6 and hour < 6 else ""
    valid = (
        datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=hour)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = dest.with_suffix(".ee.png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for n in range(6):
        try:
            url = field_image(start, hour, spec).getThumbURL(thumb_params())
            urllib.request.urlretrieve(url, raw)
            last = None
            break
        except (urllib.error.HTTPError, urllib.error.URLError, ee.EEException) as exc:
            last = exc
            code = getattr(exc, "code", None)
            if code not in (None, 429, 500, 502, 503, 504) and not isinstance(
                exc, (urllib.error.URLError, ee.EEException)
            ):
                raise
            wait = 8 * (n + 1)
            print(f"  retry {fid} f{hour:03d} {type(exc).__name__} {code} in {wait}s", flush=True)
            time.sleep(wait)
    if last is not None:
        raise last
    contours = barbs = None
    overlay_err: Exception | None = None
    for n in range(6):
        try:
            if fid == "slp":
                lon, lat, grid = compute_grid(
                    hourly_01(start, hour).select("mean_sea_level_pressure_mean").divide(100.0),
                    1.0,
                )
                contours = (lon, lat, np.asarray(grid["mean_sea_level_pressure_mean"]))
            elif fid == "wind10":
                lon, lat, grid = compute_grid(
                    hourly_01(start, hour)
                    .select(
                        ["u_component_of_wind_10m_mean", "v_component_of_wind_10m_mean"]
                    )
                    .multiply(1.943844),  # m/s → kt
                    3.5,
                )
                barbs = (
                    lon,
                    lat,
                    np.asarray(grid["u_component_of_wind_10m_mean"]),
                    np.asarray(grid["v_component_of_wind_10m_mean"]),
                )
            overlay_err = None
            break
        except (ee.EEException, urllib.error.HTTPError, urllib.error.URLError) as exc:
            overlay_err = exc
            time.sleep(8 * (n + 1))
    if overlay_err is not None and fid in ("slp", "wind10"):
        print(f"  overlay skip {fid} f{hour:03d}: {overlay_err}", flush=True)
    if fid == "qpf6_imerg_p90":
        note = "  (sum of 1-h p90)"
    elif fid == "wind10":
        note = " + barbs (kt)"
    else:
        note = extra
    wrap_thumb(
        raw,
        dest,
        f"{label}{note}   WN3 mean   valid {valid}   F+{hour:03d}",
        pal,
        contours=contours,
        barbs=barbs,
    )
    raw.unlink(missing_ok=True)
    if dest.stat().st_size < 1000:
        raise RuntimeError(f"tiny PNG {dest}")
    stamp.write_text(start + "\n")
    return f"ok {fid} f{hour:03d}"


def merge_manifest(
    out: Path,
    *,
    run: str,
    init: str,
    source: str,
    new_ids: list[str],
    done_hours: dict[int, dict],
    extra: dict | None = None,
) -> list[dict]:
    path = out / "manifest.json"
    old = json.loads(path.read_text()) if path.exists() else {"variables": [], "frames": []}
    ids = [v["id"] for v in old.get("variables", [])]
    for fid in new_ids:
        if fid in ids:
            continue
        if fid == "qpf6_imerg_p90" and "qpf6_imerg" in ids:
            ids.insert(ids.index("qpf6_imerg") + 1, fid)
        else:
            ids.append(fid)
    by_lead = {fr["lead"]: fr for fr in old.get("frames", [])}
    for hour, fr in done_hours.items():
        cur = by_lead.get(hour, {"lead": hour, "valid": fr["valid"], "files": {}})
        cur["valid"] = fr["valid"]
        if fr.get("init"):
            cur["init"] = fr["init"]
        cur["files"].update(fr["files"])
        by_lead[hour] = cur
    if extra and extra.get("synoptic_init"):
        for h, fr in by_lead.items():
            if "init" not in fr and h > 48:
                fr["init"] = extra["synoptic_init"]
    frames = [by_lead[h] for h in display_leads() if h in by_lead]
    write_manifest(
        out,
        run=run,
        init=init,
        source=source,
        field_ids=ids,
        frames=frames,
        extra=extra,
    )
    return frames


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--init",
        default="",
        help="ISO init UTC; default = latest hourly for F+1–48 + latest synoptic for F+54–360",
    )
    p.add_argument("--fields", default="all")
    p.add_argument("--leads", default="")
    p.add_argument("--out", type=Path, default=SITE)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def main() -> None:
    assert display_leads()[-1] == 360 and len(display_leads()) == 100
    args = parse_args()
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if not project_id:
        sys.exit("Set GOOGLE_CLOUD_PROJECT.")
    ee_init(project_id)

    field_ids = parse_fields(args.fields)
    col01 = ee.ImageCollection(COL_01)
    hourly, synoptic, long_h = resolve_inits(col01, args.init)
    run_dt = datetime.fromisoformat(hourly.replace("Z", "+00:00"))
    run = run_dt.strftime("%Y%m%d_%Hhr_01_preds")
    extra = {
        "hourly_init": hourly,
        "synoptic_init": synoptic,
        "note": (
            "F+1–48 from latest hourly init (interim or synoptic). "
            "F+54–360 from latest 15-day synoptic. Maps only — no downloadable grids."
        ),
    }

    old_path = args.out / "manifest.json"
    old = json.loads(old_path.read_text()) if old_path.exists() else {}
    old_hourly = old.get("hourly_init") or old.get("init")
    old_syn = old.get("synoptic_init") or old.get("init")
    old_by_lead = {fr["lead"]: fr for fr in old.get("frames", [])}

    targets = (
        [int(x) for x in args.leads.split(",") if x.strip()] if args.leads else display_leads()
    )
    targets = [h for h in targets if h <= long_h]
    if not args.leads and not args.force and old_hourly == hourly and old_syn == synoptic:
        print(f"already latest hourly {hourly} synoptic {synoptic}", flush=True)
        return
    if not args.leads and not args.force and old_syn == synoptic:
        targets = [h for h in targets if h <= 48]
        print(f"synoptic {synoptic} unchanged — recook F+1–48 from {hourly}", flush=True)

    print(
        f"EE hourly {hourly}  synoptic {synoptic}  fields {field_ids}  frames {len(targets)}",
        flush=True,
    )

    jobs: list[tuple] = []
    for hour in targets:
        start = start_for_lead(hour, hourly, synoptic)
        init_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        valid = (init_dt + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_fr = old_by_lead.get(hour, {})
        stale = old_fr.get("init") != start
        for fid in field_ids:
            rel = f"frames/{fid}/f{hour:03d}.png"
            jobs.append(
                (start, hour, valid, fid, FIELDS[fid], args.out / rel, args.force or stale)
            )

    # ponytail: one slider; F+1–48 and F+54–360 may be different inits.
    # Ceiling: EE QPS; drop workers if 429s.
    t0 = time.time()
    done_hours: dict[int, dict] = {}
    source = f"earthengine:{COL_01} hourly={hourly} synoptic={synoptic}"
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(fetch_one, start, hour, spec, dest, force): (
                start,
                hour,
                valid,
                fid,
            )
            for start, hour, valid, fid, spec, dest, force in jobs
        }
        n = 0
        for fut in as_completed(futs):
            start, hour, valid, fid = futs[fut]
            msg = fut.result()
            n += 1
            done_hours.setdefault(
                hour, {"lead": hour, "valid": valid, "init": start, "files": {}}
            )
            done_hours[hour]["files"][fid] = f"frames/{fid}/f{hour:03d}.png"
            merge_manifest(
                args.out,
                run=run,
                init=hourly,
                source=source,
                new_ids=field_ids,
                done_hours=done_hours,
                extra=extra,
            )
            print(f"  {msg}  {n}/{len(jobs)}  {time.time() - t0:.0f}s", flush=True)

    assert done_hours, "no frames"
    print(f"manifest {args.out / 'manifest.json'}  n={len(done_hours)}  {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
