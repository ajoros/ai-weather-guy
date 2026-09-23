#!/usr/bin/env python3
"""Pull one WeatherNext 3 stats-Zarr slice and write two plots.

Uses gs://weathernext3_statistics_spatial/ (precomputed mean / p10–p90).
Needs Application Default Credentials and a GCP project (billing header).

    gcloud auth application-default login
    export GOOGLE_CLOUD_PROJECT=your-project-id
    .venv/bin/python plot_wn3_stats.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import obstore
import xarray as xr
import zarr

# Edit these.
LAT, LON = 40.71, -74.01  # NYC; lon is converted to 0–360 for Zarr
BBOX_DEG = 0.4
LEAD_HOURS_SERIES = 24
LEAD_HOUR_MAP = 24
OUT_DIR = Path(__file__).resolve().parent / "plots"

BUCKET = "weathernext3_statistics_spatial"
PREFIX_ROOT = "weathernext_3_0_0_statistics/zarr/2026_to_present"
DOCS_FALLBACK = f"{PREFIX_ROOT}/20260826_00hr_01_preds/predictions.zarr"


def lon360(lon: float) -> float:
    return lon % 360.0


def candidate_prefixes() -> list[str]:
    now = datetime.now(timezone.utc) - timedelta(hours=8)
    hour = (now.hour // 6) * 6
    t = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    out: list[str] = []
    for _ in range(16):
        out.append(f"{PREFIX_ROOT}/{t:%Y%m%d}_{t:%H}hr_01_preds/predictions.zarr")
        t -= timedelta(hours=6)
    if DOCS_FALLBACK not in out:
        out.append(DOCS_FALLBACK)
    return out


def open_stats(prefix: str, project_id: str) -> xr.Dataset:
    gcs_store = obstore.store.GCSStore(
        bucket=BUCKET,
        prefix=prefix,
        client_options={"default_headers": {"x-goog-user-project": project_id}},
    )
    return xr.open_zarr(zarr.storage.ObjectStore(gcs_store), chunks={})


def first_openable(project_id: str) -> tuple[str, xr.Dataset]:
    last_err: Exception | None = None
    for prefix in candidate_prefixes():
        try:
            ds = open_stats(prefix, project_id)
            _ = ds.init_time.values  # force a metadata read
            return prefix, ds
        except ImportError:
            raise
        except ValueError as exc:
            if "dask" in str(exc).lower():
                raise
            last_err = exc
            print(f"skip {prefix}: {exc}", file=sys.stderr)
        except Exception as exc:  # ponytail: only retry missing inits
            last_err = exc
            print(f"skip {prefix}: {exc}", file=sys.stderr)
    raise SystemExit(
        "Could not open any stats Zarr.\n"
        "1) gcloud auth application-default login  (approved Google Account)\n"
        "2) export GOOGLE_CLOUD_PROJECT=your-project-id\n"
        f"Last error: {last_err}"
    )


def bbox():
    lon = lon360(LON)
    return (
        LAT - BBOX_DEG,
        LAT + BBOX_DEG,
        lon - BBOX_DEG,
        lon + BBOX_DEG,
    )


def plot_series(ds: xr.Dataset, path: Path) -> None:
    min_lat, max_lat, min_lon, max_lon = bbox()
    vars_ = [
        "station_head_temperature_2m_mean",
        "station_head_temperature_2m_p10",
        "station_head_temperature_2m_p90",
    ]
    region = ds[vars_].sel(
        lat_0p05=slice(min_lat, max_lat),
        lon_0p05=slice(min_lon, max_lon),
    )
    leads = [np.timedelta64(h, "h") for h in range(1, LEAD_HOURS_SERIES + 1)]
    sl = region.sel(lead_time=leads).load()
    mean = sl["station_head_temperature_2m_mean"].mean(("lat_0p05", "lon_0p05")) - 273.15
    p10 = sl["station_head_temperature_2m_p10"].mean(("lat_0p05", "lon_0p05")) - 273.15
    p90 = sl["station_head_temperature_2m_p90"].mean(("lat_0p05", "lon_0p05")) - 273.15
    times = sl["datetime"].values
    assert np.isfinite(mean.values).any(), "series is all-NaN"

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(times, p10, p90, color="0.75", label="p10–p90")
    ax.plot(times, mean, color="C3", lw=2, label="ensemble mean")
    ax.set_ylabel("2 m temperature (°C)")
    ax.set_xlabel("valid time (UTC)")
    init = np.datetime_as_string(ds.init_time.values, unit="m")
    ax.set_title(f"WN3 station-head T  {LAT:.2f},{LON:.2f}  init {init}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %Hz"))
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_map(ds: xr.Dataset, path: Path) -> None:
    min_lat, max_lat, min_lon, max_lon = bbox()
    field = (
        ds["temperature_2m_mean"].sel(lead_time=np.timedelta64(LEAD_HOUR_MAP, "h")) - 273.15
    )
    sl = field.sel(lat_0p1=slice(min_lat, max_lat), lon_0p1=slice(min_lon, max_lon)).load()
    assert sl.size > 0, "map slice empty"
    sl.plot(figsize=(7, 6), cmap="coolwarm")
    plt.title(f"temperature_2m_mean +{LEAD_HOUR_MAP}h (°C)")
    plt.tight_layout()
    plt.savefig(path, dpi=140)
    plt.close()


def main() -> None:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if not project_id:
        sys.exit("Set GOOGLE_CLOUD_PROJECT to a GCP project ID (needed as the billing header).")

    OUT_DIR.mkdir(exist_ok=True)
    prefix, ds = first_openable(project_id)
    print("opened", prefix)
    print("init_time", ds.init_time.values)
    print("data_vars", len(ds.data_vars))

    series_path = OUT_DIR / "t2m_station_series.png"
    map_path = OUT_DIR / "t2m_map.png"
    plot_series(ds, series_path)
    plot_map(ds, map_path)
    print("wrote", series_path)
    print("wrote", map_path)
    assert series_path.stat().st_size > 1000
    assert map_path.stat().st_size > 1000


if __name__ == "__main__":
    main()
