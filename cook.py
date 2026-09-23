#!/usr/bin/env python3
"""Pre-render WeatherNext 3 stats maps for the local stacked viewer.

Free stats Zarr only. Latest synoptic init (00/06/12/18Z), hourly F01–48
then 6-hourly F54–360. NWS-style fixed bins. °F / inches / mph.

    export GOOGLE_CLOUD_PROJECT=weathernext3-joros
    .venv/bin/python cook.py                  # all free fields, 100 frames
    .venv/bin/python cook.py --fields core    # T / 6-h QPF / SLP / wind
    python3 -m http.server --directory site 8000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from plot_wn3_stats import (
    BUCKET,
    PREFIX_ROOT,
    candidate_prefixes,
    open_stats,
)

LAT0, LAT1 = 10.0, 75.0
LON0, LON1 = 120.0, 300.0  # 120E–60W
CACHE = Path(__file__).resolve().parent / ".cache" / "naturalearth"
SITE = Path(__file__).resolve().parent / "site"

NE_FILES = {
    "coast": "ne_50m_coastline.geojson",
    "border": "ne_50m_admin_0_boundary_lines_land.geojson",
    "states": "ne_50m_admin_1_states_provinces_lines.geojson",
    "lakes": "ne_50m_lakes.geojson",
}
NE_BASE = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
)


def display_leads() -> list[int]:
    return list(range(1, 49)) + list(range(54, 361, 6))


def k_to_f(a: np.ndarray) -> np.ndarray:
    return a * 9.0 / 5.0 - 459.67


def m_to_in(a: np.ndarray) -> np.ndarray:
    return a * 39.37007874


def ms_to_mph(a: np.ndarray) -> np.ndarray:
    return a * 2.23693629


def pa_to_hpa(a: np.ndarray) -> np.ndarray:
    return a / 100.0


def frac_to_pct(a: np.ndarray) -> np.ndarray:
    return a * 100.0


# NWS 2018 standard curves via Herbie paint hex lists. Bounds kept in
# the units we plot (°F, inches, mph) — not Herbie's C/mm/m/s conversion.
NWS_TMP = [
    "#91003f",
    "#ce1256",
    "#e7298a",
    "#df65b0",
    "#ff73df",
    "#ffbee8",
    "#ffffff",
    "#dadaeb",
    "#bcbddc",
    "#9e9ac8",
    "#756bb1",
    "#54278f",
    "#0d007d",
    "#0d3d9c",
    "#0066c2",
    "#299eff",
    "#4ac7ff",
    "#73d7ff",
    "#adffff",
    "#30cfc2",
    "#009996",
    "#125757",
    "#066d2c",
    "#31a354",
    "#74c476",
    "#a1d99b",
    "#d3ffbe",
    "#ffffb3",
    "#ffeda0",
    "#fed176",
    "#feae2a",
    "#fd8d3c",
    "#fc4e2a",
    "#e31a1c",
    "#b10026",
    "#800026",
    "#590042",
    "#280028",
]
NWS_DPT = [
    "#3b2204",
    "#543005",
    "#8c520a",
    "#bf812d",
    "#cca854",
    "#dfc27d",
    "#e6d9b5",
    "#d3ebe7",
    "#a9dbd3",
    "#72b8ad",
    "#318c85",
    "#01665f",
    "#003c30",
    "#002921",
]
NWS_PCP = [
    "#ffffff",
    "#c7e9c0",
    "#a1d99b",
    "#74c476",
    "#31a353",
    "#006d2c",
    "#fffa8a",
    "#ffcc4f",
    "#fe8d3c",
    "#fc4e2a",
    "#d61a1c",
    "#ad0026",
    "#700026",
    "#3b0030",
    "#4c0073",
    "#ffdbff",
]
NWS_WIND = [
    "#103f78",
    "#225ea8",
    "#1d91c0",
    "#41b6c4",
    "#7fcdbb",
    "#b4d79e",
    "#dfff9e",
    "#ffffa6",
    "#ffe873",
    "#ffc400",
    "#ffaa00",
    "#ff5900",
    "#ff0000",
    "#a80000",
    "#6e0000",
    "#ffbee8",
    "#ff73df",
]
NWS_CLOUD = [
    "#24a0f2",
    "#4eb0f2",
    "#80b7f8",
    "#a0c8ff",
    "#d2e1ff",
    "#e1e1e1",
    "#c9c9c9",
    "#a5a5a5",
    "#6e6e6e",
    "#505050",
]


def _slp_colors(n: int) -> list[str]:
    cmap = plt.get_cmap("RdBu_r")
    return [mcolors.to_hex(cmap(i / (n - 1))) for i in range(n)]


PALETTES: dict[str, dict] = {
    "tmp_f": {
        "colors": NWS_TMP,
        "bounds": np.linspace(-65, 125, len(NWS_TMP) + 1),
        "label": "°F",
        "ticks": np.arange(-60, 130, 10),
    },
    "dpt_f": {
        "colors": NWS_DPT,
        "bounds": np.array([-10, 0, 10, 20, 30, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85], dtype=float),
        "label": "°F",
    },
    "pcp_in": {
        "colors": NWS_PCP,
        "bounds": np.array(
            [0, 0.01, 0.1, 0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 10, 15, 20, 30, 50],
            dtype=float,
        ),
        "label": "inches",
    },
    "wind_mph": {
        "colors": NWS_WIND,
        "bounds": np.array(
            [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 100, 120, 140, 160],
            dtype=float,
        ),
        "label": "mph",
    },
    "cloud": {
        "colors": NWS_CLOUD,
        "bounds": np.linspace(0, 100, len(NWS_CLOUD) + 1),
        "label": "%",
    },
    "slp": {
        "colors": _slp_colors(16),
        "bounds": np.arange(980.0, 1048.0, 4.0),
        "label": "hPa",
        "ticks": np.arange(980, 1048, 8),
    },
}


def assert_palettes() -> None:
    for name, pal in PALETTES.items():
        n_c = len(pal["colors"])
        n_b = len(pal["bounds"])
        assert n_b == n_c + 1, f"{name}: {n_c} colors need {n_c + 1} bounds, got {n_b}"


# (id, label, zarr mean var, converter, palette, grid, accum_hours)
# accum_hours=6 means sum the last 6 hourly steps of that var.
FIELD_ROWS = [
    ("station_t", "Station 2 m temperature", "station_head_temperature_2m_mean", k_to_f, "tmp_f", "0p05", 0),
    ("station_td", "Station 2 m dewpoint", "station_head_dewpoint_temperature_2m_mean", k_to_f, "dpt_f", "0p05", 0),
    ("t2m", "Gridded 2 m temperature", "temperature_2m_mean", k_to_f, "tmp_f", "0p1", 0),
    ("td", "Gridded 2 m dewpoint", "dewpoint_temperature_2m_mean", k_to_f, "dpt_f", "0p1", 0),
    ("qpf6_imerg", "6-h IMERG QPF", "imerg_tp_1hr_mean", m_to_in, "pcp_in", "0p1", 6),
    ("qpf6_imerg_p90", "6-h IMERG QPF p90", "imerg_tp_1hr_p90", m_to_in, "pcp_in", "0p1", 6),
    ("qpf1_imerg", "1-h IMERG QPF", "imerg_tp_1hr_mean", m_to_in, "pcp_in", "0p1", 1),
    ("qpf1_model", "1-h model QPF", "total_precipitation_1hr_mean", m_to_in, "pcp_in", "0p1", 1),
    ("qpf1_exp", "1-h experimental QPF", "experimental_tp_1hr_mean", m_to_in, "pcp_in", "0p1", 1),
    ("slp", "Mean sea-level pressure", "mean_sea_level_pressure_mean", pa_to_hpa, "slp", "0p1", 0),
    ("wind10", "10 m wind speed", "wind_speed_10m_mean", ms_to_mph, "wind_mph", "0p1", 0),
    ("sst", "Sea-surface temperature", "sea_surface_temperature_mean", k_to_f, "tmp_f", "0p1", 0),
    ("cloud_total", "Total cloud cover", "total_cloud_cover_mean", frac_to_pct, "cloud", "0p1", 0),
    ("cloud_low", "Low cloud cover", "low_cloud_cover_mean", frac_to_pct, "cloud", "0p1", 0),
    ("cloud_mid", "Mid cloud cover", "medium_cloud_cover_mean", frac_to_pct, "cloud", "0p1", 0),
    ("cloud_high", "High cloud cover", "high_cloud_cover_mean", frac_to_pct, "cloud", "0p1", 0),
]
FIELDS = {row[0]: row for row in FIELD_ROWS}
CORE_IDS = ["station_t", "qpf6_imerg", "slp", "wind10"]


def hours_since(td) -> int:
    return int(np.asarray(td).astype("timedelta64[h]").astype(int))


def latest_synoptic(project_id: str) -> tuple[str, xr.Dataset]:
    last: Exception | None = None
    for prefix in candidate_prefixes():
        try:
            ds = open_stats(prefix, project_id)
            _ = ds.init_time.values
            leads = [hours_since(v) for v in ds.lead_time.values]
            if max(leads) < 300:
                print(f"skip interim {prefix}", flush=True)
                ds.close()
                continue
            return prefix, ds
        except ImportError:
            raise
        except Exception as exc:
            last = exc
            print(f"skip {prefix}: {exc}", file=sys.stderr, flush=True)
    raise SystemExit(f"Could not open a 360-h synoptic stats Zarr. Last error: {last}")


def crop(da: xr.DataArray) -> xr.DataArray:
    if "lat_0p05" in da.dims:
        return da.sel(lat_0p05=slice(LAT0, LAT1), lon_0p05=slice(LON0, LON1))
    return da.sel(lat_0p1=slice(LAT0, LAT1), lon_0p1=slice(LON0, LON1))


def load_retry(obj, tries: int = 4):
    last: Exception | None = None
    for n in range(tries):
        try:
            return obj.load()
        except Exception as exc:
            last = exc
            print(f"  load retry {n + 1}/{tries}: {type(exc).__name__}", flush=True)
            time.sleep(5 * (n + 1))
    assert last is not None
    raise last


def mesh(da: xr.DataArray) -> tuple[np.ndarray, np.ndarray]:
    if "lon_0p05" in da.dims:
        return np.asarray(da.lon_0p05), np.asarray(da.lat_0p05)
    return np.asarray(da.lon_0p1), np.asarray(da.lat_0p1)


def _fetch_ne(name: str) -> Path | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / NE_FILES[name]
    if path.exists() and path.stat().st_size > 1000:
        return path
    url = NE_BASE + NE_FILES[name]
    try:
        urllib.request.urlretrieve(url, path)
    except Exception as exc:
        print(f"coast skip {name}: {exc}", file=sys.stderr)
        return None
    return path if path.exists() else None


def _iter_rings(geom: dict):
    t = geom.get("type")
    coords = geom.get("coordinates")
    if not t or coords is None:
        return
    if t == "LineString":
        yield coords
    elif t == "MultiLineString":
        yield from coords
    elif t == "Polygon":
        yield coords[0]
    elif t == "MultiPolygon":
        for poly in coords:
            yield poly[0]


_NE_CACHE: list[tuple[np.ndarray, np.ndarray, dict]] | None = None


def _ne_lines() -> list[tuple[np.ndarray, np.ndarray, dict]]:
    # ponytail: parse NE once; re-reading 50m geojson per PNG is the slow part.
    global _NE_CACHE
    if _NE_CACHE is not None:
        return _NE_CACHE
    layers = (
        ("lakes", dict(color="0.45", lw=0.3, alpha=0.8)),
        ("coast", dict(color="0.12", lw=0.55)),
        ("border", dict(color="0.22", lw=0.4)),
        ("states", dict(color="0.32", lw=0.25)),
    )
    out: list[tuple[np.ndarray, np.ndarray, dict]] = []
    for name, kw in layers:
        path = _fetch_ne(name)
        if path is None:
            continue
        data = json.loads(path.read_text())
        for feat in data.get("features", []):
            geom = feat.get("geometry") or {}
            for ring in _iter_rings(geom):
                if len(ring) < 2:
                    continue
                lon = np.array([p[0] for p in ring], dtype=float)
                lat = np.array([p[1] for p in ring], dtype=float)
                lon = np.where(lon < 0, lon + 360.0, lon)
                jump = np.abs(np.diff(lon, prepend=lon[0])) > 180
                lon = lon.astype(float)
                lon[jump] = np.nan
                if np.nanmax(lat) < LAT0 or np.nanmin(lat) > LAT1:
                    continue
                if np.nanmax(lon) < LON0 or np.nanmin(lon) > LON1:
                    continue
                out.append((lon, lat, kw))
    _NE_CACHE = out
    return out


def add_boundaries(ax) -> None:
    # Domain 120–300 never crosses 0°, so plain lon/lat + NE lines.
    # Upgrade: cartopy 10m features if a 3.14 wheel appears.
    for lon, lat, kw in _ne_lines():
        ax.plot(lon, lat, **kw)


def save_map(
    path: Path,
    lon: np.ndarray,
    lat: np.ndarray,
    data: np.ndarray,
    *,
    title: str,
    palette: str,
    contours: np.ndarray | None = None,
) -> None:
    pal = PALETTES[palette]
    cmap = mcolors.ListedColormap(list(pal["colors"]))
    cmap.set_bad("#e8e8e8")
    cmap.set_under(pal["colors"][0])
    cmap.set_over(pal["colors"][-1])
    norm = mcolors.BoundaryNorm(pal["bounds"], cmap.N, clip=False)
    fig, ax = plt.subplots(figsize=(13.5, 6.4), dpi=110)
    ax.set_xlim(LON0, LON1)
    ax.set_ylim(LAT0, LAT1)
    pcm = ax.pcolormesh(lon, lat, data, cmap=cmap, norm=norm, shading="nearest", zorder=1)
    if contours is not None:
        cs = ax.contour(
            lon,
            lat,
            data,
            levels=contours,
            colors="k",
            linewidths=0.28,
            alpha=0.55,
            zorder=2,
        )
        ax.clabel(cs, contours[::2], fmt="%d", fontsize=6, inline=True)
    add_boundaries(ax)
    ax.set_facecolor("#f4f4f4")
    ax.grid(True, lw=0.3, color="0.55", alpha=0.45, zorder=4)
    ax.tick_params(labelsize=8)
    ax.set_xlabel("longitude (0–360)", fontsize=8)
    ax.set_ylabel("latitude", fontsize=8)
    ax.set_title(title, loc="left", fontsize=11)
    ticks = pal.get("ticks", pal["bounds"])
    fig.colorbar(pcm, ax=ax, shrink=0.78, label=pal["label"], pad=0.015, ticks=ticks, extend="both")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def parse_fields(arg: str) -> list[str]:
    if arg in ("all", ""):
        return [row[0] for row in FIELD_ROWS]
    if arg == "core":
        return list(CORE_IDS)
    ids = [x.strip() for x in arg.split(",") if x.strip()]
    unknown = [i for i in ids if i not in FIELDS]
    if unknown:
        raise SystemExit(f"unknown fields: {unknown}\nknown: {list(FIELDS)}")
    return ids


def write_manifest(
    out: Path,
    *,
    run: str,
    init: str,
    source: str,
    field_ids: list[str],
    frames: list[dict],
    extra: dict | None = None,
) -> None:
    manifest = {
        "run": run,
        "init": init,
        "domain": {"lat": [LAT0, LAT1], "lon_360": [LON0, LON1]},
        "source": source,
        "note": "Free stats Zarr, ensemble mean. Maps only — no downloadable grids.",
        "disclaimer": (
            "WeatherNext 3 experimental research data. Not an official forecast, "
            "watch, or warning, and not NWS. Do not use for life-and-property decisions."
        ),
        "keys": "← → step time · space play · Home/End ends",
        "variables": [
            {"id": fid, "label": FIELDS[fid][1], "units": PALETTES[FIELDS[fid][4]]["label"]}
            for fid in field_ids
        ],
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frames": frames,
    }
    if extra:
        manifest.update(extra)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="", help="YYYYMMDD_HHhr_01_preds; default = latest synoptic")
    p.add_argument("--fields", default="all", help="all | core | comma ids")
    p.add_argument("--leads", default="", help="comma hours; default = F01–48 hourly, F54–360 /6h")
    p.add_argument("--out", type=Path, default=SITE)
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def main() -> None:
    assert_palettes()
    leads = display_leads()
    assert leads[0] == 1 and leads[47] == 48 and leads[48] == 54 and leads[-1] == 360
    assert len(leads) == 100
    assert 49 not in leads and 53 not in leads

    args = parse_args()
    field_ids = parse_fields(args.fields)
    targets = [int(x) for x in args.leads.split(",") if x.strip()] if args.leads else leads
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if not project_id:
        sys.exit("Set GOOGLE_CLOUD_PROJECT (needed as the GCS billing header).")

    if args.run:
        prefix = f"{PREFIX_ROOT}/{args.run}/predictions.zarr"
        ds = open_stats(prefix, project_id)
        run = args.run
    else:
        prefix, ds = latest_synoptic(project_id)
        run = prefix.split("/")[-2]

    init = np.datetime64(ds.init_time.values, "s")
    lead_h = np.array([hours_since(v) for v in ds.lead_time.values])
    index = {int(h): i for i, h in enumerate(lead_h)}
    targets = [h for h in targets if h in index]
    if not targets:
        raise SystemExit("no matching lead times")

    specs = [FIELDS[i] for i in field_ids]
    precip_vars = sorted({s[2] for s in specs if s[6] >= 1})
    inst_01 = [s for s in specs if s[5] == "0p1" and s[6] == 0]
    inst_05 = [s for s in specs if s[5] == "0p05"]
    precip_hours: set[int] = set()
    for s in specs:
        if s[6] <= 1:
            continue
        for t in targets:
            precip_hours.update(range(max(1, t - (s[6] - 1)), t + 1))
    if any(s[6] == 1 for s in specs):
        precip_hours.update(targets)

    out = args.out
    frames_root = out / "frames"
    frames_root.mkdir(parents=True, exist_ok=True)
    source = f"gs://{BUCKET}/{prefix}"
    init_s = str(init) + "Z"
    print(
        f"run {run} init {init_s} fields {field_ids} frames {len(targets)}",
        flush=True,
    )

    precip_cache: dict[tuple[str, int], np.ndarray] = {}
    lon01 = lat01 = lon05 = lat05 = None
    done: list[dict] = []

    walk = sorted(set(targets) | precip_hours)
    for hour in walk:
        i = index[hour]
        if hour in precip_hours and precip_vars:
            missing = [v for v in precip_vars if (v, hour) not in precip_cache]
            if missing:
                sl = load_retry(crop(ds[missing].isel(lead_time=i)))
                lon01, lat01 = mesh(sl[missing[0]])
                for v in missing:
                    precip_cache[(v, hour)] = np.asarray(sl[v])

        if hour not in targets:
            continue

        valid = str(np.datetime64(ds.datetime.values[i], "s")) + "Z"
        tag = f"f{hour:03d}"
        files: dict[str, str] = {}
        loaded01 = None
        loaded05 = None

        if inst_01:
            need = [s[2] for s in inst_01]
            loaded01 = load_retry(crop(ds[need].isel(lead_time=i)))
            lon01, lat01 = mesh(loaded01[need[0]])
        if inst_05:
            need = [s[2] for s in inst_05]
            loaded05 = load_retry(crop(ds[need].isel(lead_time=i)))
            lon05, lat05 = mesh(loaded05[need[0]])

        for fid, label, var, conv, pal, grid, accum in specs:
            rel = f"frames/{fid}/{tag}.png"
            path = out / rel
            files[fid] = rel
            if path.exists() and not args.force:
                continue
            if accum >= 1:
                hours = range(max(1, hour - (accum - 1)), hour + 1)
                chunks = [precip_cache[(var, h)] for h in hours if (var, h) in precip_cache]
                if not chunks:
                    continue
                z = conv(np.sum(chunks, axis=0))
                lon, lat = lon01, lat01
            elif grid == "0p05":
                z = conv(np.asarray(loaded05[var]))
                lon, lat = lon05, lat05
            else:
                z = conv(np.asarray(loaded01[var]))
                lon, lat = lon01, lat01
            extra = ""
            if accum == 6 and hour < 6:
                extra = f"  ({hour}h window)"
            save_map(
                path,
                lon,
                lat,
                z,
                title=f"{label}{extra}   WN3 mean   valid {valid}   F+{hour:03d}",
                palette=pal,
                contours=np.arange(960, 1060, 4) if fid == "slp" else None,
            )

        for h in [h for v, h in precip_cache if h < hour - 6]:
            for v in precip_vars:
                precip_cache.pop((v, h), None)

        done.append({"lead": hour, "valid": valid, "files": files})
        write_manifest(out, run=run, init=init_s, source=source, field_ids=field_ids, frames=done)
        print(f"  {tag}  valid {valid}  n={len(done)}/{len(targets)}", flush=True)

    assert done, "no frames written"
    for fr in done:
        for fid, rel in fr["files"].items():
            p = out / rel
            assert p.exists() and p.stat().st_size > 1000, p
    print(f"manifest {out / 'manifest.json'}  n={len(done)}")


if __name__ == "__main__":
    main()
