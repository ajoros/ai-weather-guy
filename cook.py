#!/usr/bin/env python3
"""Pre-render WeatherNext 3 stats maps for the local stacked viewer.

Free stats Zarr only. Latest synoptic init (00/06/12/18Z), hourly F01–48
then 6-hourly F54–360. NWS-style fixed bins. °F / inches / mph.

    export GOOGLE_CLOUD_PROJECT=weathernext3-joros
    .venv/bin/python cook.py                  # all free fields, 100 frames
    .venv/bin/python cook.py --fields core    # T / 1-h IMERG / run-total model QPF / SLP / wind
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
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from plot_wn3_stats import (
    BUCKET,
    PREFIX_ROOT,
    candidate_prefixes,
    open_stats,
)

# wide: North America + northern Pacific. pnw: 40–55°N, 135–100°W.
DOMAINS = {
    "wide": {
        "name": "wide",
        "lat": (10.0, 75.0),
        "lon": (120.0, 300.0),
        "fig": (18.0, 8.52),
        "thumb": (2100, 759),
    },
    "pnw": {
        "name": "pnw",
        "lat": (40.0, 55.0),
        "lon": (225.0, 260.0),
        "fig": (18.0, 7.71),
        "thumb": (2100, 900),
    },
}
LAT0, LAT1 = DOMAINS["wide"]["lat"]
LON0, LON1 = DOMAINS["wide"]["lon"]
FIG_SIZE = DOMAINS["wide"]["fig"]
CACHE = Path(__file__).resolve().parent / ".cache" / "naturalearth"


def apply_domain(name: str) -> dict:
    """Point coastlines and map axes at a named window."""
    global LAT0, LAT1, LON0, LON1, FIG_SIZE
    if name not in DOMAINS:
        raise SystemExit(f"unknown domain {name}; known: {list(DOMAINS)}")
    reg = DOMAINS[name]
    LAT0, LAT1 = reg["lat"]
    LON0, LON1 = reg["lon"]
    FIG_SIZE = reg["fig"]
    return reg


def subset_box(lon, lat, arrays, box):
    """Slice monotonic 1d lon/lat fields to an inclusive box. No second download."""
    lat0, lat1, lon0, lon1 = box
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    ii = np.flatnonzero((lat >= lat0) & (lat <= lat1))
    jj = np.flatnonzero((lon >= lon0) & (lon <= lon1))
    if ii.size == 0 or jj.size == 0:
        raise ValueError(f"empty subset {box}")
    i0, i1 = int(ii.min()), int(ii.max()) + 1
    j0, j1 = int(jj.min()), int(jj.max()) + 1
    out = [lon[j0:j1], lat[i0:i1]]
    for arr in arrays:
        out.append(np.asarray(arr)[i0:i1, j0:j1])
    return out
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


def ensemble_floor_lead(lead: int) -> int:
    """Hold the last 6-h upper-air frame; F+1–5 uses F+6."""
    return 6 if lead < 6 else (lead // 6) * 6


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


def k_to_c(a: np.ndarray) -> np.ndarray:
    return np.asarray(a, dtype=float) - 273.15


def ms_to_kt(a: np.ndarray) -> np.ndarray:
    return np.asarray(a, dtype=float) * 1.943844


def rel_vort_e5(lon: np.ndarray, lat: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Relative vorticity in 10^-5 s^-1. u,v in m/s; lat increasing."""
    r = 6371000.0
    dlat = np.deg2rad(float(np.mean(np.diff(lat))))
    dlon = np.deg2rad(float(np.mean(np.diff(lon))))
    dy = r * dlat
    dx = r * np.cos(np.deg2rad(lat))[:, None] * dlon
    dvdx = np.gradient(v, axis=1) / np.maximum(dx, 1.0)
    dudy = np.gradient(u, axis=0) / dy
    return (dvdx - dudy) * 1e5


def phi_to_dam(a: np.ndarray) -> np.ndarray:
    return a / 9.80665 / 10.0


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
    # Tropical Tidbits-ish upper air (cyclonic vort / 850 °C / jet kt).
    "vort_e5": {
        "colors": [
            "#ffffff",
            "#ffffcc",
            "#ffff66",
            "#ffcc00",
            "#ff9900",
            "#ff6600",
            "#ff3300",
            "#cc0000",
            "#990000",
            "#660000",
            "#330000",
        ],
        "bounds": np.array([0, 8, 12, 16, 20, 24, 28, 32, 36, 40, 45, 50], dtype=float),
        "label": "10^-5 s^-1",
        "ticks": np.array([0, 8, 16, 24, 32, 40, 50], dtype=float),
        "bad": "#ffffff",
    },
    "tmp_c": {
        "colors": [
            "#e050b8",
            "#48d8d8",
            "#c8e048",
            "#2d8c2d",
            "#38a038",
            "#50c050",
            "#88dc88",
            "#c8f0c0",
            "#ffffff",
            "#fff8dc",
            "#ffe680",
            "#ffc848",
            "#ffa020",
            "#f06810",
            "#d82810",
            "#b01010",
            "#8c0810",
            "#c04088",
        ],
        "bounds": np.array(
            [-52, -41, -35, -30, -25, -20, -15, -10, -5, 0, 5, 10, 15, 20, 25, 30, 35, 40, 48],
            dtype=float,
        ),
        "label": "°C",
        "ticks": np.array([-41, -30, -20, -10, 0, 10, 20, 30, 40, 48], dtype=float),
        "bad": "#ffffff",
    },
    "wind_kt": {
        "colors": [
            "#ffffff",
            "#e0f7ff",
            "#a8ecff",
            "#4fd0e0",
            "#2ec27a",
            "#7ae04a",
            "#d2f020",
            "#ffff00",
            "#ffd000",
            "#ff9000",
            "#ff5000",
            "#e00000",
            "#c00030",
            "#a00080",
            "#8000a0",
            "#600080",
            "#400060",
            "#200040",
        ],
        "bounds": np.array(
            [0, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 170, 190, 210, 250],
            dtype=float,
        ),
        "label": "kt",
        "ticks": np.array([0, 20, 40, 60, 80, 100, 120, 150, 190, 250], dtype=float),
        "bad": "#ffffff",
    },
    "wind_kt_ll": {
        "colors": [
            "#ffffff",
            "#f0fbff",
            "#d8f4ff",
            "#b0ebff",
            "#7ed8f0",
            "#40c8c8",
            "#40d070",
            "#80e040",
            "#d0f020",
            "#ffff00",
            "#ffc000",
            "#ff7000",
            "#e01010",
            "#b00060",
            "#700080",
        ],
        "bounds": np.array(
            [0, 7, 16, 25, 34, 40, 46, 52, 58, 64, 80, 96, 110, 125, 140, 155],
            dtype=float,
        ),
        "label": "kt",
        "ticks": np.array([0, 16, 34, 46, 64, 96, 125, 155], dtype=float),
        "bad": "#ffffff",
    },
    # Pivotal-style 500 mb wind shade (white → purple → magenta, kt).
    "wind_kt_pw": {
        "colors": [
            "#ffffff",
            "#f4f4fc",
            "#e8eaf8",
            "#d8dcf4",
            "#c4c6ec",
            "#b0b0e4",
            "#9a98da",
            "#8880d0",
            "#7a68c4",
            "#7858b8",
            "#8448ac",
            "#943898",
            "#a82888",
            "#c02078",
            "#d42070",
            "#e43068",
            "#ec4070",
            "#e84878",
            "#d04070",
            "#c03868",
            "#b03060",
            "#a02858",
            "#901850",
        ],
        "bounds": np.array(
            [0, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120, 125, 130],
            dtype=float,
        ),
        "label": "kt",
        "ticks": np.arange(20, 135, 10),
        "bad": "#ffffff",
    },
}


def assert_palettes() -> None:
    for name, pal in PALETTES.items():
        n_c = len(pal["colors"])
        n_b = len(pal["bounds"])
        assert n_b == n_c + 1, f"{name}: {n_c} colors need {n_c + 1} bounds, got {n_b}"


# (id, label, zarr mean var, converter, palette, grid, accum_hours)
# accum_hours=6 means sum the last 6 hourly steps of that var.
# accum_hours=-1 means run total: sum forecast hours 1 through this lead.
FIELD_ROWS = [
    ("station_t", "Station 2 m temperature", "station_head_temperature_2m_mean", k_to_f, "tmp_f", "0p05", 0),
    ("station_td", "Station 2 m dewpoint", "station_head_dewpoint_temperature_2m_mean", k_to_f, "dpt_f", "0p05", 0),
    ("t2m", "Gridded 2 m temperature", "temperature_2m_mean", k_to_f, "tmp_f", "0p1", 0),
    ("td", "Gridded 2 m dewpoint", "dewpoint_temperature_2m_mean", k_to_f, "dpt_f", "0p1", 0),
    ("qpf6_imerg", "6-h IMERG QPF", "imerg_tp_1hr_mean", m_to_in, "pcp_in", "0p1", 6),
    ("qpf6_imerg_p90", "6-h IMERG QPF p90", "imerg_tp_1hr_p90", m_to_in, "pcp_in", "0p1", 6),
    ("qpf1_imerg", "1-h IMERG QPF", "imerg_tp_1hr_mean", m_to_in, "pcp_in", "0p1", 1),
    ("qpf1_model", "1-h model QPF", "total_precipitation_1hr_mean", m_to_in, "pcp_in", "0p1", 1),
    ("qpf6_model", "6-h model QPF", "total_precipitation_1hr_mean", m_to_in, "pcp_in", "0p1", 6),
    ("qpf_acc", "Model QPF run total", "total_precipitation_1hr_mean", m_to_in, "pcp_in", "0p1", -1),
    ("qpf1_exp", "1-h experimental QPF", "experimental_tp_1hr_mean", m_to_in, "pcp_in", "0p1", 1),
    ("slp", "Mean sea-level pressure", "mean_sea_level_pressure_mean", pa_to_hpa, "slp", "0p1", 0),
    ("wind10", "10 m wind speed", "wind_speed_10m_mean", ms_to_mph, "wind_mph", "0p1", 0),
    ("wind10_p90", "10 m wind p90 (gust proxy)", "wind_speed_10m_p90", ms_to_mph, "wind_mph", "0p1", 0),
    ("h500", "500 mb height", "geopotential", phi_to_dam, "wind_kt_pw", "0p25", 0),
    ("t850", "850 mb temperature", "temperature", k_to_c, "tmp_c", "0p25", 0),
    ("wind925", "925 mb wind", "u_component_of_wind", ms_to_kt, "wind_kt", "0p25", 0),
    ("wind700", "700 mb wind", "u_component_of_wind", ms_to_kt, "wind_kt", "0p25", 0),
    ("wind500", "500 mb wind", "u_component_of_wind", ms_to_kt, "wind_kt", "0p25", 0),
    ("wind300", "300 mb wind", "u_component_of_wind", ms_to_kt, "wind_kt", "0p25", 0),
    ("sst", "Sea-surface temperature", "sea_surface_temperature_mean", k_to_f, "tmp_f", "0p1", 0),
    ("cloud_total", "Total cloud cover", "total_cloud_cover_mean", frac_to_pct, "cloud", "0p1", 0),
    ("cloud_low", "Low cloud cover", "low_cloud_cover_mean", frac_to_pct, "cloud", "0p1", 0),
    ("cloud_mid", "Mid cloud cover", "medium_cloud_cover_mean", frac_to_pct, "cloud", "0p1", 0),
    ("cloud_high", "High cloud cover", "high_cloud_cover_mean", frac_to_pct, "cloud", "0p1", 0),
]
FIELDS = {row[0]: row for row in FIELD_ROWS}
CORE_IDS = ["station_t", "qpf1_imerg", "qpf_acc", "slp", "wind10", "wind10_p90"]
ENSEMBLE_IDS = ["h500", "t850", "wind925", "wind700", "wind500", "wind300"]
PAGE_IDS = CORE_IDS + ENSEMBLE_IDS
WIND_LEVEL = {"wind925": 925, "wind700": 700, "wind500": 500, "wind300": 300}
PT = ZoneInfo("America/Los_Angeles")


def accum_hours(hour: int, accum: int) -> list[int]:
    """Forecast hours to include. accum=-1 is init→valid (1..hour), not last-N."""
    if accum < 0:
        return list(range(1, hour + 1))
    if accum:
        return list(range(max(1, hour - accum + 1), hour + 1))
    return [hour]


def parse_iso_z(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ampm(dt: datetime) -> str:
    h = dt.hour
    return f"{((h + 11) % 12) + 1}{'am' if h < 12 else 'pm'}"


def fmt_valid_clock(valid: datetime | str) -> str:
    utc = parse_iso_z(valid)
    pt = utc.astimezone(PT)
    return (
        f"{utc.strftime('%a')} {utc.day} {utc.strftime('%b')} "
        f"{utc.strftime('%H')}Z / {_ampm(pt)} {pt.tzname()}"
    )


def fmt_init_clock(init: datetime | str) -> str:
    utc = parse_iso_z(init)
    pt = utc.astimezone(PT)
    return f"{_ampm(pt)} {pt.tzname()} ({utc.strftime('%H')}Z)"


def plot_title(label: str, note: str, valid: datetime | str, init: str, hour: int) -> str:
    return (
        f"{label}{note}   valid {fmt_valid_clock(valid)}   "
        f"init {fmt_init_clock(init)}   F+{hour:03d}"
    )


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


_NE_CACHE: dict[tuple[float, float, float, float], list[tuple[np.ndarray, np.ndarray, dict]]] = {}


def _ne_lines() -> list[tuple[np.ndarray, np.ndarray, dict]]:
    # ponytail: parse NE once per domain; re-reading 50m geojson per PNG is the slow part.
    key = (float(LAT0), float(LAT1), float(LON0), float(LON1))
    hit = _NE_CACHE.get(key)
    if hit is not None:
        return hit
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
    _NE_CACHE[key] = out
    return out


def format_lon_axis(ax, lon0: float, lon1: float) -> None:
    # Narrow west-longitude window (the PNW page). The wide map stays 0–360.
    if lon0 < 180 or (lon1 - lon0) > 80:
        ax.set_xlabel("longitude (0–360)", fontsize=8)
        return
    ticks = np.arange(np.ceil(lon0 / 5.0) * 5.0, lon1 + 0.01, 5.0)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{int(round(360 - t))}°W" for t in ticks])
    ax.set_xlabel("longitude", fontsize=8)


WATERMARK = (
    "AI-Weather-Guy  ·  ajoros  ·  ajoros.github.io/ai-weather-guy  ·  "
    "Google WeatherNext 3 (experimental)"
)


def add_watermark(ax) -> None:
    ax.text(
        0.5,
        0.012,
        WATERMARK,
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9,
        color="0.12",
        zorder=6,
        path_effects=[pe.withStroke(linewidth=3.4, foreground="1", alpha=0.8)],
    )


def finish_map(fig, ax, mappable, pal, path: Path) -> None:
    # ponytail: default colorbar fraction=0.15 leaves a fat white strip on an 18" fig.
    add_watermark(ax)
    ticks = pal.get("ticks", pal["bounds"])
    fig.colorbar(
        mappable,
        ax=ax,
        fraction=0.022,
        pad=0.008,
        shrink=0.86,
        aspect=24,
        label=pal["label"],
        ticks=ticks,
        extend="both",
    )
    fig.tight_layout(pad=0.25)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white", bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


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
    contour_data: np.ndarray | None = None,
    contour_color: str = "k",
    contour_label_color: str | None = None,
    barbs=None,
    streamlines=None,
    marks=None,
) -> None:
    pal = PALETTES[palette]
    cmap = mcolors.ListedColormap(list(pal["colors"]))
    cmap.set_bad(pal.get("bad", "#e8e8e8"))
    cmap.set_under(pal["colors"][0])
    cmap.set_over(pal["colors"][-1])
    norm = mcolors.BoundaryNorm(pal["bounds"], cmap.N, clip=False)
    fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=130)
    ax.set_xlim(LON0, LON1)
    ax.set_ylim(LAT0, LAT1)
    pcm = ax.pcolormesh(lon, lat, data, cmap=cmap, norm=norm, shading="nearest", zorder=1)
    if contours is not None:
        cs = ax.contour(
            lon,
            lat,
            contour_data if contour_data is not None else data,
            levels=contours,
            colors=contour_color,
            linewidths=0.7,
            alpha=0.85,
            zorder=2,
        )
        ax.clabel(cs, contours[::2], fmt="%d", fontsize=7, inline=True)
        if contour_label_color:
            for t in getattr(cs, "labelTexts", []):
                t.set_color(contour_label_color)
    if streamlines is not None:
        lonb, latb, u, v = streamlines
        step = max(2, int(round(len(lonb) / 48)))
        ax.streamplot(
            lonb[::step],
            latb[::step],
            u[::step, ::step],
            v[::step, ::step],
            density=1.2,
            color="0.15",
            linewidth=0.45,
            arrowsize=0.7,
            zorder=3,
        )
    if barbs is not None:
        lonb, latb, u, v = barbs
        step = max(1, int(round(len(lonb) / 32)))
        xx, yy = np.meshgrid(lonb, latb)
        ax.barbs(
            xx[::step, ::step],
            yy[::step, ::step],
            u[::step, ::step],
            v[::step, ::step],
            length=5.4,
            linewidth=0.4,
            color="0.1",
            barb_increments={"half": 5, "full": 10, "flag": 50},
            zorder=3,
        )
    add_boundaries(ax)
    ax.set_facecolor(pal.get("bad", "#f4f4f4"))
    ax.grid(True, lw=0.3, color="0.55", alpha=0.45, zorder=4)
    if marks:
        for x, y, kind, val in marks:
            color = "#1a4fd6" if kind == "H" else "#d01010"
            ax.text(x, y, kind, color=color, fontsize=12, fontweight="bold", ha="center", va="center", zorder=5)
            ax.text(x, y - 1.8, f"{val:.0f}", color=color, fontsize=7, ha="center", va="top", zorder=5)
    ax.tick_params(labelsize=8)
    format_lon_axis(ax, LON0, LON1)
    ax.set_ylabel("latitude", fontsize=8)
    ax.set_title(title, loc="left", fontsize=11)
    finish_map(fig, ax, pcm, pal, path)


def parse_fields(arg: str) -> list[str]:
    if arg in ("all", ""):
        return [row[0] for row in FIELD_ROWS]
    if arg == "core":
        return list(CORE_IDS)
    if arg == "ensemble":
        return list(ENSEMBLE_IDS)
    if arg == "page":
        return list(PAGE_IDS)
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


def page_field_ids(old: dict, incoming: list[str]) -> list[str]:
    """Keep surface + upper-air ids across separate cooks."""
    have = {v.get("id") for v in old.get("variables") or []}
    want = set(incoming) | have
    return [i for i in PAGE_IDS if i in want]


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"variables": [], "frames": []}
    if path.stat().st_size == 0:
        raise SystemExit(
            f"{path} is an empty placeholder. Make that file available offline before cooking."
        )
    return json.loads(path.read_text())


def merge_manifest(
    out: Path,
    *,
    run: str,
    init: str,
    source: str,
    new_ids: list[str],
    done_hours: dict[int, dict],
    extra: dict | None = None,
    keep_clock: bool = False,
) -> list[dict]:
    path = out / "manifest.json"
    old = load_manifest(path)
    ids = page_field_ids(old, new_ids)
    by_lead = {fr["lead"]: fr for fr in old.get("frames", [])}
    for hour, fr in done_hours.items():
        cur = by_lead.get(hour)
        if cur is None:
            cur = {"lead": hour, "valid": fr["valid"], "files": {}}
            if fr.get("init"):
                cur["init"] = fr["init"]
        elif not keep_clock:
            cur["valid"] = fr["valid"]
            if fr.get("init"):
                cur["init"] = fr["init"]
        cur["files"].update(fr["files"])
        by_lead[hour] = cur
    for fr in by_lead.values():
        fr["files"] = {k: v for k, v in fr.get("files", {}).items() if k in ids}
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
    precip_vars = sorted({s[2] for s in specs if s[6]})
    inst_01 = [s for s in specs if s[5] == "0p1" and s[6] == 0]
    inst_05 = [s for s in specs if s[5] == "0p05"]
    precip_hours: set[int] = set()
    for s in specs:
        if not s[6]:
            continue
        for t in targets:
            precip_hours.update(accum_hours(t, s[6]))

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

    walk = sorted(h for h in (set(targets) | precip_hours) if h in index)
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
            if accum:
                hours = accum_hours(hour, accum)
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
                title=plot_title(label, extra, valid, init_s, hour),
                palette=pal,
                contours=np.arange(960, 1060, 4) if fid == "slp" else None,
            )

        retain = hour if any(s[6] < 0 for s in specs) else 6
        for h in [h for v, h in precip_cache if h < hour - retain]:
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
