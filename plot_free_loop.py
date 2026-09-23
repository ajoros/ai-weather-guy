#!/usr/bin/env python3
"""Free-tier WeatherNext 3 loop: SLP, 6-hr QPF, 10 m wind → web/frames."""

from __future__ import annotations

import argparse
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
import obstore
import xarray as xr
import zarr

PC = ccrs.PlateCarree()
# NA + northern Pacific only (120E → 50W). Centered so the basin is one map.
MAP = ccrs.PlateCarree(central_longitude=215)

BUCKET = "weathernext3_statistics_spatial"
PREFIX_ROOT = "weathernext_3_0_0_statistics/zarr/2026_to_present"
LAT0, LAT1 = 10.0, 75.0
LON0, LON1 = 120.0, 310.0  # 120E → 50W: full NP + North America, not Asia interior
VARS = ("slp", "qpf6", "wind10")


def hours_since(td) -> int:
    return int(np.asarray(td).astype("timedelta64[h]").astype(int))


def open_stats(run: str) -> xr.Dataset:
    prefix = f"{PREFIX_ROOT}/{run}/predictions.zarr"
    store = obstore.store.GCSStore(bucket=BUCKET, prefix=prefix)
    return xr.open_zarr(zarr.storage.ObjectStore(store), chunks=None)


def crop(da: xr.DataArray) -> xr.DataArray:
    return da.sel(lat_0p1=slice(LAT0, LAT1), lon_0p1=slice(LON0, LON1))


def load_retry(da: xr.DataArray, tries: int = 4) -> xr.DataArray:
    # ponytail: ADC tokens last ~1h; one retry loop beats restarting 60 frames.
    last: Exception | None = None
    for n in range(tries):
        try:
            return da.load()
        except Exception as exc:
            last = exc
            print(f"  load retry {n + 1}/{tries}: {type(exc).__name__}", flush=True)
            time.sleep(5 * (n + 1))
    assert last is not None
    raise last


def mesh(da: xr.DataArray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lon = np.asarray(da.lon_0p1)
    lat = np.asarray(da.lat_0p1)
    return lon, lat, np.asarray(da)


def add_boundaries(ax) -> None:
    ax.add_feature(
        cfeature.COASTLINE.with_scale("10m"), linewidth=0.5, edgecolor="0.1", zorder=3
    )
    ax.add_feature(
        cfeature.BORDERS.with_scale("10m"), linewidth=0.4, edgecolor="0.2", zorder=3
    )
    ax.add_feature(
        cfeature.NaturalEarthFeature(
            "cultural",
            "admin_1_states_provinces_lines",
            "10m",
            facecolor="none",
            edgecolor="0.28",
        ),
        linewidth=0.28,
        zorder=3,
    )
    ax.add_feature(
        cfeature.LAKES.with_scale("10m"),
        facecolor="none",
        edgecolor="0.25",
        linewidth=0.35,
        zorder=3,
    )


def save_map(
    path: Path,
    lon: np.ndarray,
    lat: np.ndarray,
    data: np.ndarray,
    *,
    title: str,
    cmap,
    vmin,
    vmax,
    cbar_label: str,
    contour_levels=None,
) -> None:
    fig, ax = plt.subplots(
        figsize=(13.5, 6.6), dpi=120, subplot_kw={"projection": MAP}
    )
    ax.set_extent([LON0, LON1, LAT0, LAT1], crs=PC)
    pcm = ax.pcolormesh(
        lon,
        lat,
        data,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        shading="nearest",
        transform=PC,
        zorder=1,
    )
    if contour_levels is not None:
        ax.contour(
            lon,
            lat,
            data,
            levels=contour_levels,
            colors="k",
            linewidths=0.3,
            alpha=0.5,
            transform=PC,
            zorder=2,
        )
    add_boundaries(ax)
    gl = ax.gridlines(
        draw_labels=True, linewidth=0.3, color="0.55", alpha=0.55, zorder=4
    )
    gl.top_labels = False
    gl.right_labels = False
    ax.set_title(title, loc="left", fontsize=11)
    fig.colorbar(pcm, ax=ax, shrink=0.78, label=cbar_label, pad=0.02)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="20260919_00hr_01_preds")
    p.add_argument("--step", type=int, default=6)
    p.add_argument("--start-lead", type=int, default=1)
    p.add_argument("--max-lead", type=int, default=360)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "web")
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out = args.out
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    ds = open_stats(args.run)
    init = np.datetime64(ds.init_time.values, "s")
    leads_h = np.array([hours_since(v) for v in ds.lead_time.values])
    targets = [h for h in range(args.step, args.max_lead + 1, args.step) if h in set(leads_h)]
    if not targets:
        raise SystemExit("no matching lead times")

    slp = ds["mean_sea_level_pressure_mean"]
    tp = ds["total_precipitation_1hr_mean"]
    wspd = ds["wind_speed_10m_mean"]

    index = {int(h): i for i, h in enumerate(leads_h)}
    qpf_window: deque[np.ndarray] = deque(maxlen=args.step)
    frames: list[dict] = []

    print(f"run {args.run} init {init} step {args.step}h frames {len(targets)}", flush=True)

    for hour in range(args.start, args.max_lead + 1):
        if hour not in index:
            continue
        i = index[hour]
        precip = crop(tp.isel(lead_time=i))
        precip = load_retry(precip) * 1000.0  # m → mm
        qpf_window.append(np.asarray(precip))

        if hour not in targets:
            continue
        if len(qpf_window) < args.step:
            continue

        valid = np.datetime64(ds.datetime.values[i], "s")
        tag = f"f{hour:03d}"
        slp_path = frames_dir / f"slp_{tag}.png"
        qpf_path = frames_dir / f"qpf6_{tag}.png"
        wind_path = frames_dir / f"wind10_{tag}.png"
        subtitle = (
            f"WeatherNext 3  stats mean  0.1°  |  init {init}Z  valid {valid}Z  "
            f"lead {hour:03d}h  |  free tier"
        )

        if args.force or not slp_path.exists():
            slp_hpa = load_retry(crop(slp.isel(lead_time=i))) / 100.0
            lon, lat, z = mesh(slp_hpa)
            save_map(
                slp_path,
                lon,
                lat,
                z,
                title=f"SLP (hPa)   {subtitle}",
                cmap="coolwarm",
                vmin=980,
                vmax=1040,
                cbar_label="hPa",
                contour_levels=np.arange(960, 1060, 4),
            )

        if args.force or not qpf_path.exists():
            qpf = np.sum(qpf_window, axis=0)
            lon, lat, _ = mesh(precip)
            save_map(
                qpf_path,
                lon,
                lat,
                qpf,
                title=f"6-hr QPF (mm)   {subtitle}",
                cmap="YlGnBu",
                vmin=0,
                vmax=25,
                cbar_label="mm / 6 h",
            )

        if args.force or not wind_path.exists():
            wind = load_retry(crop(wspd.isel(lead_time=i)))
            lon, lat, z = mesh(wind)
            save_map(
                wind_path,
                lon,
                lat,
                z,
                title=f"10 m wind (m/s)   {subtitle}",
                cmap="YlOrRd",
                vmin=0,
                vmax=25,
                cbar_label="m/s",
            )

        print(f"  wrote {tag}  valid {valid}", flush=True)

    frames = []
    for hour in targets:
        tag = f"f{hour:03d}"
        paths = {
            "slp": frames_dir / f"slp_{tag}.png",
            "qpf6": frames_dir / f"qpf6_{tag}.png",
            "wind10": frames_dir / f"wind10_{tag}.png",
        }
        if not all(p.exists() for p in paths.values()):
            continue
        valid = np.datetime64(ds.datetime.values[index[hour]], "s")
        frames.append(
            {
                "lead": hour,
                "valid": str(valid) + "Z",
                "files": {k: f"frames/{p.name}" for k, p in paths.items()},
            }
        )

    manifest = {
        "run": args.run,
        "init": str(init) + "Z",
        "step_hours": args.step,
        "max_lead": args.max_lead,
        "domain": {"lat": [LAT0, LAT1], "lon_360": [LON0, LON1]},
        "source": f"gs://{BUCKET}/{PREFIX_ROOT}/{args.run}/predictions.zarr",
        "note": "Free-tier stats Zarr. Spatial crop is display-only; chunks are global.",
        "variables": [
            {"id": "slp", "label": "SLP (mean)", "units": "hPa"},
            {"id": "qpf6", "label": "6-hr QPF (mean)", "units": "mm"},
            {"id": "wind10", "label": "10 m wind (mean)", "units": "m/s"},
        ],
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frames": frames,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    assert frames, "no frames written"
    assert all((out / fr["files"]["slp"]).exists() for fr in frames)
    print(f"manifest {out / 'manifest.json'}  n={len(frames)}")


if __name__ == "__main__":
    main()
