#!/usr/bin/env python3
"""64-member-mean upper-air maps from the paid ensemble Zarr.

Run this in us-east1 (same region as gs://weathernext3_spatial) so egress is $0.
6-hourly synoptic leads only. Do not use flattened hourly 500H — that is 6× the bytes.

    export GOOGLE_CLOUD_PROJECT=weathernext3-joros
    .venv/bin/python cook_ensemble.py --members 1 --leads 6 --fields h500
    .venv/bin/python cook_ensemble.py --merge-only
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import obstore
import xarray as xr
import zarr

import cook
from cook import (
    ENSEMBLE_IDS,
    FIELDS,
    LAT0,
    LAT1,
    LON0,
    LON1,
    SITE,
    RH_LEVEL,
    WIND_LEVEL,
    specific_humidity_to_rh,
    display_leads,
    dropbox_retry,
    hours_since,
    k_to_c,
    load_manifest,
    merge_manifest,
    ms_to_kt,
    page_field_ids,
    parse_fields,
    phi_to_dam,
    plot_title,
    save_map,
)
from plot_wn3_stats import PREFIX_ROOT, open_stats


class DropboxBusy(RuntimeError):
    """Newest ensemble prefix is locked; do not walk to an older run."""

ENS_BUCKET = "weathernext3_spatial"
ENS_ROOT = "weathernext_3_0_0/zarr/2026_to_present"
KT = 1.943844
# ponytail: leave two vCPUs for the reads and the OS. 6 on c4-standard-8, 2 on
# e2-standard-4. Ceiling: RAM (one map per worker) and how fast Cloud Storage answers.
DRAW_WORKERS = max(2, (os.cpu_count() or 2) - 2)
_WORKER_DS: xr.Dataset | None = None
_WORKER_STATS: xr.Dataset | None = None
# 1000–300 hPa. Reynolds et al. 2022, MWR: IVT = −(1/g) ∫_1000^300 q V dp.
# Ascending pressure makes the trapezoid the same number without the minus sign.
IVT_LEVELS_HPA = (300, 400, 500, 600, 700, 850, 925, 1000)
G = 9.80665


class FieldNotReady(RuntimeError):
    """A level or the pressure field is not written yet. Do not stamp the frame."""


def ivt_segment(flux0, flux1, p0_pa: float, p1_pa: float):
    """One trapezoid step of ∫ qV dp / g between two pressure levels."""
    return 0.5 * (flux0 + flux1) * (p1_pa - p0_pa) / G


def stats_prefix(ens_prefix: str) -> str:
    run = ens_prefix.strip("/").split("/")[-2]
    return f"{PREFIX_ROOT}/{run}/predictions.zarr"


def ens_prefixes() -> list[str]:
    now = datetime.now(timezone.utc) - timedelta(hours=8)
    hour = (now.hour // 6) * 6
    t = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    out: list[str] = []
    for _ in range(16):
        out.append(f"{ENS_ROOT}/{t:%Y%m%d}_{t:%H}hr_01_preds/predictions.zarr")
        t -= timedelta(hours=6)
    return out


def open_ens(prefix: str, project_id: str) -> xr.Dataset:
    store = obstore.store.GCSStore(
        bucket=ENS_BUCKET,
        prefix=prefix,
        client_options={"default_headers": {"x-goog-user-project": project_id}},
    )
    return xr.open_zarr(zarr.storage.ObjectStore(store), chunks={})


def latest_ens(project_id: str) -> tuple[str, xr.Dataset, str]:
    last: Exception | None = None
    for prefix in ens_prefixes():
        for n in range(6):
            try:
                ds = open_ens(prefix, project_id)
                _ = ds.init_time.values
                leads = [hours_since(v) for v in ds.lead_time.values]
                if max(leads) < 300:
                    ds.close()
                    break
                init = np.datetime64(ds.init_time.values, "s")
                init_s = str(init) + "Z"
                return prefix, ds, init_s
            except OSError as exc:
                last = exc
                if getattr(exc, "errno", None) == 11:
                    if n < 5:
                        time.sleep(0.5 * (n + 1))
                        continue
                    raise DropboxBusy(f"Dropbox busy opening {prefix}") from exc
                print(f"skip {prefix}: {exc}", file=sys.stderr, flush=True)
                break
            except Exception as exc:
                last = exc
                print(f"skip {prefix}: {exc}", file=sys.stderr, flush=True)
                break
    raise SystemExit(f"Could not open ensemble synoptic Zarr. Last error: {last}")


def crop25(da: xr.DataArray, box: tuple[float, float, float, float] | None = None) -> xr.DataArray:
    if box is None:
        lat0, lat1, lon0, lon1 = LAT0, LAT1, LON0, LON1
    else:
        lat0, lat1, lon0, lon1 = box
    return da.sel(lat_0p25=slice(lat0, lat1), lon_0p25=slice(lon0, lon1))


def mean_level(
    ds: xr.Dataset,
    var: str,
    hour: int,
    level: int,
    members: int,
    box: tuple[float, float, float, float] | None = None,
) -> xr.DataArray:
    sl = ds[var].sel(lead_time=np.timedelta64(hour, "h"), level=level)
    if members < int(ds.sizes.get("sample", 64)):
        sl = sl.isel(sample=slice(0, members))
    return crop25(sl.mean("sample"), box).load()


def ensemble_leads(limit: int = 360) -> list[int]:
    return [h for h in range(6, limit + 1, 6) if h in set(display_leads())]


def load_uv(ds: xr.Dataset, hour: int, lev: int, members: int, box=None):
    u = mean_level(ds, "u_component_of_wind", hour, lev, members, box)
    v = mean_level(ds, "v_component_of_wind", hour, lev, members, box)
    uu, vv = np.asarray(u), np.asarray(v)
    return np.asarray(u.lon_0p25), np.asarray(u.lat_0p25), uu, vv


def mean_2d(ds: xr.Dataset, var: str, hour: int, members: int):
    sl = ds[var].sel(lead_time=np.timedelta64(hour, "h"))
    if members < int(ds.sizes.get("sample", 64)):
        sl = sl.isel(sample=slice(0, members))
    sl = sl.mean("sample")
    lat_name = next(d for d in sl.dims if d.startswith("lat"))
    lon_name = next(d for d in sl.dims if d.startswith("lon"))
    sl = sl.sel({lat_name: slice(LAT0, LAT1), lon_name: slice(LON0, LON1)})
    return sl.load(), np.asarray(sl[lon_name]), np.asarray(sl[lat_name])


def slp_marks(lon: np.ndarray, lat: np.ndarray, slp: np.ndarray) -> list:
    # ponytail: stride local min/max; ceiling is missed weak centers. Upgrade: watershed.
    step = 5
    z = slp[::step, ::step]
    lo, la = lon[::step], lat[::step]
    out = []
    for i in range(1, z.shape[0] - 1):
        for j in range(1, z.shape[1] - 1):
            v = z[i, j]
            if not np.isfinite(v):
                continue
            nb = z[i - 1 : i + 2, j - 1 : j + 2]
            if v <= np.nanmin(nb) and v < 1012:
                out.append((float(lo[j]), float(la[i]), "L", float(v)))
            elif v >= np.nanmax(nb) and v > 1016:
                out.append((float(lo[j]), float(la[i]), "H", float(v)))
    lows = sorted((m for m in out if m[2] == "L"), key=lambda m: m[3])[:12]
    highs = sorted((m for m in out if m[2] == "H"), key=lambda m: -m[3])[:12]
    return lows + highs


def _read_stamp(path: Path) -> str:
    return dropbox_retry(lambda: path.read_text().strip())


def resolve_merge_init(forced: str, out: Path, field_ids: list[str]) -> str:
    """Use --init when we have it. Do not walk Dropbox stamps first — that can kill the run."""
    if forced:
        return forced
    for fid in field_ids:
        for hour in ensemble_leads():
            st = out / f"frames/{fid}/f{hour:03d}.init"
            if not st.exists():
                continue
            try:
                got = _read_stamp(st)
            except OSError:
                continue
            if got:
                return got
    return ""


def _fresh(dest: Path, start: str) -> bool:
    stamp = dest.with_suffix(".init")
    try:
        return (
            dest.exists()
            and dest.stat().st_size > 1000
            and stamp.exists()
            and _read_stamp(stamp) == start
        )
    except OSError:
        return False


def _save_crop(
    name: str,
    dest: Path,
    start: str,
    lon,
    lat,
    z,
    contour_z,
    barbs,
    title: str,
    pal,
    contours,
    contour_color: str,
    contour_label_color,
    streamlines,
    marks,
) -> None:
    # Same loaded arrays. Chunks are global, so a second .load() would re-read them.
    reg = cook.DOMAINS[name]
    box = (*reg["lat"], *reg["lon"])
    arrays = [z]
    if contour_z is not None:
        arrays.append(contour_z)
    if barbs is not None:
        arrays.extend([barbs[2], barbs[3]])
    parts = cook.subset_box(lon, lat, arrays, box)
    plon, plat = parts[0], parts[1]
    idx = 2
    pz = parts[idx]
    idx += 1
    pz_c = None
    if contour_z is not None:
        pz_c = parts[idx]
        idx += 1
    pbarbs = None
    if barbs is not None:
        pbarbs = (plon, plat, parts[idx], parts[idx + 1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    cook.apply_domain(name)
    try:
        save_map(
            dest,
            plon,
            plat,
            pz,
            title=title,
            palette=pal,
            contours=contours,
            contour_data=pz_c,
            contour_color=contour_color,
            contour_label_color=contour_label_color,
            barbs=pbarbs,
            streamlines=streamlines,
            marks=marks,
        )
    finally:
        cook.apply_domain("wide")
    if dest.stat().st_size < 1000:
        raise RuntimeError(f"tiny PNG {dest}")
    dest.with_suffix(".init").write_text(start + "\n")


def _member_level(ds: xr.Dataset, var: str, hour: int, level: int, members: int, box):
    sl = ds[var].sel(lead_time=np.timedelta64(hour, "h"), level=level)
    n = int(ds.sizes.get("sample", 64))
    if members < n:
        sl = sl.isel(sample=slice(0, members))
    return crop25(sl, box)


def _load_ivt(ds: xr.Dataset, hour: int, members: int, box):
    """Column IVT on the wide grid, one level at a time. Color is the mean of the 64 magnitudes."""
    if _WORKER_STATS is None:
        raise FieldNotReady("stats pressure file is not open")
    import dask

    acc_u = acc_v = None
    prev_qu = prev_qv = None
    prev_p = None
    lon = lat = None
    for lev in IVT_LEVELS_HPA:
        q = _member_level(ds, "specific_humidity", hour, lev, members, box)
        u = _member_level(ds, "u_component_of_wind", hour, lev, members, box)
        v = _member_level(ds, "v_component_of_wind", hour, lev, members, box)
        with dask.config.set(scheduler="threads"):
            q, u, v = dask.compute(q, u, v)
        qa, ua, va = np.asarray(q), np.asarray(u), np.asarray(v)
        if not (np.isfinite(qa).any() and np.isfinite(ua).any() and np.isfinite(va).any()):
            raise FieldNotReady(f"level {lev} hPa is not written yet")
        if lon is None:
            lon = np.asarray(q.lon_0p25)
            lat = np.asarray(q.lat_0p25)
        qu = qa * ua
        qv = qa * va
        p = float(lev) * 100.0
        if prev_qu is not None:
            seg_u = ivt_segment(prev_qu, qu, prev_p, p)
            seg_v = ivt_segment(prev_qv, qv, prev_p, p)
            acc_u = seg_u if acc_u is None else acc_u + seg_u
            acc_v = seg_v if acc_v is None else acc_v + seg_v
        prev_qu, prev_qv, prev_p = qu, qv, p
    if acc_u is None:
        raise FieldNotReady("IVT column is empty")
    try:
        slp = _WORKER_STATS["mean_sea_level_pressure_mean"].sel(lead_time=np.timedelta64(hour, "h"))
    except KeyError as exc:
        raise FieldNotReady(f"no sea-level pressure at F+{hour}") from exc
    lat0, lat1, lon0, lon1 = box
    slp = slp.sel(
        lat_0p1=slice(lat0 - 1.5, lat1 + 1.5),
        lon_0p1=slice(lon0 - 1.5, lon1 + 1.5),
    ).load()
    if not np.isfinite(np.asarray(slp)).any():
        raise FieldNotReady(f"sea-level pressure at F+{hour} is not written yet")
    # High terrain makes raw sea-level pressure noisy. Smooth ~1°, then put it on the 0.25° grid.
    slp_h = slp / 100.0
    for _ in range(2):
        slp_h = slp_h.rolling(lat_0p1=11, lon_0p1=11, center=True, min_periods=1).mean()
    slp_on = slp_h.interp(
        lat_0p1=xr.DataArray(lat, dims="lat_0p25"),
        lon_0p1=xr.DataArray(lon, dims="lon_0p25"),
    )
    mag = np.hypot(acc_u, acc_v).mean(axis=0)
    return {
        "ivt": True,
        "lon": lon,
        "lat": lat,
        "z": mag,
        "ivt_u": acc_u.mean(axis=0),
        "ivt_v": acc_v.mean(axis=0),
        "contour_z": np.asarray(slp_on),
        "contours": None,
        "barbs": None,
        "streamlines": None,
        "marks": None,
        "contour_color": "k",
        "contour_label_color": None,
        "title": "",
        "pal": "ivt",
    }


def save_ivt_map(path: Path, lon, lat, mag, mu, mv, slp, start: str, hour: int) -> None:
    """WeatherBell-style frame: IVT fill, transport streamlines, labeled 4 hPa contours."""
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt

    pal = cook.PALETTES["ivt"]
    cmap = mcolors.ListedColormap(list(pal["colors"]))
    cmap.set_over(pal["colors"][-1])
    cmap.set_under("white")
    norm = mcolors.BoundaryNorm(pal["bounds"], cmap.N)
    lon0, lon1, lat0, lat1 = float(cook.LON0), float(cook.LON1), float(cook.LAT0), float(cook.LAT1)
    fig = plt.figure(figsize=cook.FIG_SIZE, dpi=130)
    ax = fig.add_axes([0.012, 0.09, 0.976, 0.84])
    ax.set_autoscale_on(False)
    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    ax.set_facecolor("#f4f7fd")
    ax.contourf(lon, lat, mag, levels=pal["bounds"], cmap=cmap, norm=norm, extend="max", zorder=1)
    step = max(2, int(round(len(lon) / 48)))
    try:
        ax.streamplot(
            lon[::step], lat[::step],
            np.nan_to_num(mu[::step, ::step]), np.nan_to_num(mv[::step, ::step]),
            density=(2.2, 1.6), color="0.45", linewidth=0.45, arrowsize=0.55, arrowstyle="-|>",
            zorder=2,
        )
    except Exception as exc:
        print(f"ivt streamlines skipped: {exc}", flush=True)
    cook.add_boundaries(ax)
    span = max(lon1 - lon0, lat1 - lat0)
    grid = 10.0 if span > 50 else 5.0
    for x in np.arange(np.ceil(lon0 / grid) * grid, lon1, grid):
        ax.axvline(x, color="0.55", lw=0.4, ls=(0, (3, 4)), zorder=3)
        west = x > 180
        lon_txt = f"{int(round(360 - x if west else x))} {'W' if west else 'E'}"
        ax.text(x, lat1, lon_txt, ha="center", va="top", fontsize=7, zorder=6, clip_on=True)
    for y in np.arange(np.ceil(lat0 / grid) * grid, lat1, grid):
        ax.axhline(y, color="0.55", lw=0.4, ls=(0, (3, 4)), zorder=3)
        ax.text(lon1, y, f"{int(round(y))} N", ha="right", va="bottom", fontsize=7, zorder=6,
                clip_on=True)
    cs = ax.contour(lon, lat, slp, levels=np.arange(940, 1072, 4), colors="k", linewidths=0.7, zorder=4)
    ax.clabel(cs, fmt="%d", fontsize=7, inline=True, inline_spacing=3)
    for x, y, kind, val in slp_marks(lon, lat, slp):
        color = "#1a4fd6" if kind == "H" else "#d01010"
        ax.text(x, y, kind, color=color, fontsize=11, fontweight="bold", ha="center", va="center", zorder=7)
        ax.text(x, y - 0.6, f"{val:.0f}", color=color, fontsize=7, ha="center", va="top", zorder=7)
    ax.set_autoscale_on(False)
    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)
    ax.text(0.012, 0.012, "AI-Weather-Guy", transform=ax.transAxes, fontsize=9, fontweight="bold",
            color="0.45", style="italic", zorder=8)
    init = datetime.fromisoformat(start.replace("Z", "+00:00"))
    valid = init + timedelta(hours=hour)
    fig.text(
        0.012, 0.965,
        f"WN3 0.25° 64-mem mean • Init {init:%H}z {init.day} {init:%b %Y} • "
        "Integrated Vapor Transport (kg m$^{-1}$ s$^{-1}$) and MSLP (hPa)",
        fontsize=9, va="center",
    )
    fig.text(
        0.988, 0.965,
        f"Hour: {hour} • Valid: {valid:%H}z {valid:%a} {valid.day} {valid:%b %Y}",
        fontsize=9, fontweight="bold", ha="right", va="center",
    )
    cax = fig.add_axes([0.02, 0.028, 0.62, 0.018])
    cb = fig.colorbar(
        plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation="horizontal",
        ticks=pal["bounds"], extend="max",
    )
    cb.ax.xaxis.set_ticks_position("top")
    cb.ax.tick_params(labelsize=6, length=0, pad=1)
    cb.outline.set_linewidth(0.5)
    finite = mag[np.isfinite(mag)]
    if finite.size:
        fig.text(0.985, 0.034, f"Max: {finite.max():.1f}", fontsize=10, fontweight="bold",
                 ha="right", va="center")
    tmp = cook.staged_path(path.name)
    fig.savefig(tmp, facecolor="white", dpi=130)
    plt.close(fig)
    try:
        cook.publish_file(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _save_ivt_crop(name: str, dest: Path, start: str, hour: int, lon, lat, mag, mu, mv, slp) -> None:
    reg = cook.DOMAINS[name]
    plon, plat, pmag, pmu, pmv, pslp = cook.subset_box(lon, lat, [mag, mu, mv, slp], (*reg["lat"], *reg["lon"]))
    dest.parent.mkdir(parents=True, exist_ok=True)
    cook.apply_domain(name)
    try:
        save_ivt_map(dest, plon, plat, pmag, pmu, pmv, pslp, start, hour)
    finally:
        cook.apply_domain("wide")
    if dest.stat().st_size < 1000:
        raise RuntimeError(f"tiny PNG {dest}")
    dest.with_suffix(".init").write_text(start + "\n")


def _load_field(ds: xr.Dataset, start: str, hour: int, fid: str, members: int, box):
    """Read one wide-domain field. box is captured by the caller so a crop cannot change it."""
    if fid == "ivt":
        return _load_ivt(ds, hour, members, box)
    spec = FIELDS[fid]
    label, pal = spec[1], spec[4]
    valid_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=hour)
    contours = barbs = streamlines = None
    contour_z = None
    contour_color = "k"
    contour_label_color = None
    marks = None
    note = "  64-mean" if members >= 64 else f"  {members}-mem"
    if fid == "h500":
        # ponytail: Pivotal 500H = wind-speed fill (kt) + height contours, not vorticity.
        da = mean_level(ds, "geopotential", hour, 500, members, box)
        lon, lat, uu, vv = load_uv(ds, hour, 500, members, box)
        z = ms_to_kt(np.hypot(uu, vv))
        contour_z = phi_to_dam(np.asarray(da))
        contours = np.arange(468, 613, 3)
        barbs = (lon, lat, uu * KT, vv * KT)
        note += " + wind + 3 dam + barbs"
    elif fid == "t850":
        da = mean_level(ds, "temperature", hour, 850, members, box)
        lon, lat, uu, vv = load_uv(ds, hour, 850, members, box)
        z = k_to_c(np.asarray(da))
        contour_z = z
        contours = np.arange(-50, 51, 2)
        contour_color = "w"
        contour_label_color = "0.15"
        barbs = (lon, lat, uu * KT, vv * KT)
        note += " + isotherms + barbs"
    elif fid in RH_LEVEL:
        lev = RH_LEVEL[fid]
        q = mean_level(ds, "specific_humidity", hour, lev, members, box)
        t = mean_level(ds, "temperature", hour, lev, members, box)
        lon, lat = np.asarray(q.lon_0p25), np.asarray(q.lat_0p25)
        z = specific_humidity_to_rh(np.asarray(q), np.asarray(t), lev)
        note += " calculated"
    else:
        lon, lat, uu, vv = load_uv(ds, hour, WIND_LEVEL[fid], members, box)
        z = ms_to_kt(np.hypot(uu, vv))
        barbs = (lon, lat, uu * KT, vv * KT)
        note += " + barbs"
        if fid == "wind500":
            h = mean_level(ds, "geopotential", hour, 500, members, box)
            contour_z = phi_to_dam(np.asarray(h))
            contours = np.arange(468, 613, 6)
            note += " + 500H 6 dam"
    title = plot_title(label, note, valid_dt, start, hour)
    return {
        "lon": lon,
        "lat": lat,
        "z": z,
        "contour_z": contour_z,
        "contours": contours,
        "barbs": barbs,
        "streamlines": streamlines,
        "marks": marks,
        "contour_color": contour_color,
        "contour_label_color": contour_label_color,
        "title": title,
        "pal": pal,
    }


def plot_one(
    ds: xr.Dataset,
    start: str,
    hour: int,
    fid: str,
    dest: Path,
    members: int,
    force: bool,
    crops: list[tuple[str, Path, bool]] | None = None,
    loaded: dict | None = None,
) -> str:
    crops = crops or []
    need_wide = force or not _fresh(dest, start)
    need = [
        (name, crop_dest)
        for name, crop_dest, crop_force in crops
        if crop_force or not _fresh(crop_dest, start)
    ]
    if not need_wide and not need:
        return f"skip {fid} f{hour:03d}"
    if loaded is None:
        loaded = _load_field(ds, start, hour, fid, members, (LAT0, LAT1, LON0, LON1))
    lon = loaded["lon"]
    lat = loaded["lat"]
    z = loaded["z"]
    contour_z = loaded["contour_z"]
    contours = loaded["contours"]
    barbs = loaded["barbs"]
    streamlines = loaded["streamlines"]
    marks = loaded["marks"]
    contour_color = loaded["contour_color"]
    contour_label_color = loaded["contour_label_color"]
    title = loaded["title"]
    pal = loaded["pal"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    if loaded.get("ivt"):
        if need_wide:
            save_ivt_map(
                dest, lon, lat, z, loaded["ivt_u"], loaded["ivt_v"], contour_z, start, hour,
            )
            if dest.stat().st_size < 1000:
                raise RuntimeError(f"tiny PNG {dest}")
            dest.with_suffix(".init").write_text(start + "\n")
        for name, crop_dest in need:
            _save_ivt_crop(
                name, crop_dest, start, hour, lon, lat, z,
                loaded["ivt_u"], loaded["ivt_v"], contour_z,
            )
        return f"ok {fid} f{hour:03d}"
    if need_wide:
        save_map(
            dest,
            lon,
            lat,
            z,
            title=title,
            palette=pal,
            contours=contours,
            contour_data=contour_z,
            contour_color=contour_color,
            contour_label_color=contour_label_color,
            barbs=barbs,
            streamlines=streamlines,
            marks=marks,
        )
        if dest.stat().st_size < 1000:
            raise RuntimeError(f"tiny PNG {dest}")
        dest.with_suffix(".init").write_text(start + "\n")
    for name, crop_dest in need:
        _save_crop(
            name,
            crop_dest,
            start,
            lon,
            lat,
            z,
            contour_z,
            barbs,
            title,
            pal,
            contours,
            contour_color,
            contour_label_color,
            streamlines,
            marks,
        )
    return f"ok {fid} f{hour:03d}"


def merge_from_disk(out: Path, field_ids: list[str], init: str, extra: dict) -> None:
    done: dict[int, dict] = {}
    present: set[str] = set()
    for hour in ensemble_leads():
        files = {}
        for fid in field_ids:
            rel = f"frames/{fid}/f{hour:03d}.png"
            if (out / rel).exists():
                files[fid] = rel
        if not files:
            continue
        present.update(files)
        valid = (
            datetime.fromisoformat(init.replace("Z", "+00:00")) + timedelta(hours=hour)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        done[hour] = {"lead": hour, "valid": valid, "init": init, "files": files}
    old = load_manifest(out / "manifest.json") if (out / "manifest.json").exists() else {}
    extra = {
        "hourly_init": old.get("hourly_init") or old.get("init") or init,
        "synoptic_init": old.get("synoptic_init") or init,
        "note": old.get("note")
        or "Maps only — no downloadable grids.",
        **extra,
    }
    run = datetime.fromisoformat(init.replace("Z", "+00:00")).strftime("%Y%m%d_%Hhr_01_preds")
    surface_old = {
        **old,
        "variables": [v for v in old.get("variables") or [] if v.get("id") not in ENSEMBLE_IDS],
    }
    merge_manifest(
        out,
        run=old.get("run") or run,
        init=old.get("hourly_init") or old.get("init") or init,
        source=old.get("source") or f"ensemble:{ENS_BUCKET}",
        new_ids=page_field_ids(surface_old, [i for i in ENSEMBLE_IDS if i in present]),
        done_hours=done,
        extra=extra,
        keep_clock=True,
    )


def read_manifest_or_empty(path: Path) -> dict:
    """Empty Dropbox placeholders are missing manifests, not a reason to abort."""
    try:
        return load_manifest(path) if path.exists() else {}
    except (SystemExit, OSError):
        return {}


def _pngs_ready(out: Path, field_ids: list[str], leads: list[int]) -> bool:
    return all((out / f"frames/{fid}/f{h:03d}.png").exists() for fid in field_ids for h in leads)


def dest_is_live(out: Path) -> bool:
    """False for a missing/empty Dropbox placeholder — do not start the VM for that dest."""
    path = out / "manifest.json"
    try:
        if not path.exists() or path.stat().st_size < 10:
            return False
        m = read_manifest_or_empty(path)
    except (SystemExit, OSError):
        return False
    return bool(
        m.get("frames")
        or m.get("init")
        or m.get("hourly_init")
        or m.get("ensemble_init")
    )


def ensemble_current(
    out: Path,
    field_ids: list[str],
    init: str,
    *,
    domain: dict | None = None,
) -> bool:
    old = read_manifest_or_empty(out / "manifest.json")
    if old.get("ensemble_init") != init:
        return False
    if not _pngs_ready(out, field_ids, ensemble_leads()):
        return False
    if domain is not None and not cook.domain_matches_manifest(old, domain):
        return False
    return True


def _crop_extra(extra: dict, name: str) -> dict:
    reg = cook.DOMAINS[name]
    place = reg["place"]
    note = extra.get("note") or "Maps only — no downloadable grids."
    marker = f" {place}:"
    if marker in note:
        note = note.split(marker)[0]
    return {
        **extra,
        "domain": {"lat": list(reg["lat"]), "lon_360": list(reg["lon"])},
        "note": f"{note}{marker} {cook.domain_box_label(reg)}.",
    }


def _crop_outs(args: argparse.Namespace) -> list[tuple[str, Path]]:
    return [
        (name, out)
        for name, out in (("pnw", args.pnw_out), ("ca", args.ca_out), ("nepac", args.nepac_out))
        if out is not None
    ]


def _ens_worker_init(project_id: str, prefix: str) -> None:
    global _WORKER_DS, _WORKER_STATS
    _WORKER_DS = open_ens(prefix, project_id)
    try:
        _WORKER_STATS = open_stats(stats_prefix(prefix), project_id)
    except Exception as exc:
        _WORKER_STATS = None
        print(f"ivt: stats file not open ({exc})", flush=True)
    for name in cook.DOMAINS:
        cook.warm_boundaries(name)


def _ens_worker_draw(job: tuple) -> str:
    hour, fid, dest, members, force, crops, init, box = job
    if _WORKER_DS is None:
        raise RuntimeError("ensemble worker has no dataset")
    try:
        loaded = _load_field(_WORKER_DS, init, hour, fid, members, box)
    except FieldNotReady as exc:
        return f"skip {fid} f{hour:03d}: {exc}"
    crop_args = [(name, Path(path), flag) for name, path, flag in crops]
    return plot_one(
        _WORKER_DS, init, hour, fid, Path(dest), members, force, crop_args, loaded
    )


def _add_one(n: int) -> int:
    return n + 1


def _parallel_map(fn, items, workers, initializer=None, initargs=(), on_done=None):
    # ponytail: spawn, not fork. The parent already opened the GCS client; a fork
    # copies that client and the child can hang. Upgrade: a process pool per VM size.
    ctx = mp.get_context("spawn")
    kwargs = {"max_workers": workers, "mp_context": ctx}
    if initializer is not None:
        kwargs["initializer"] = initializer
        kwargs["initargs"] = initargs
    out = []
    with ProcessPoolExecutor(**kwargs) as pool:
        futures = [pool.submit(fn, item) for item in items]
        for fut in as_completed(futures):
            item = fut.result()
            out.append(item)
            if on_done is not None:
                on_done(item, len(out))
    return out


def _self_check() -> None:
    got = _parallel_map(_add_one, [1, 2, 3, 4, 5], DRAW_WORKERS)
    assert sorted(got) == [2, 3, 4, 5, 6], got
    assert 2 <= DRAW_WORKERS <= (os.cpu_count() or 2), DRAW_WORKERS
    # Constant 10 g/kg and 10 m/s from 1000 to 300 hPa is 713.8 kg m-1 s-1.
    qu = np.full(2, 0.1)
    one = ivt_segment(qu[0], qu[1], 30000.0, 100000.0)
    assert abs(float(one) - 7000.0 / G) < 1e-6, one
    parts = (
        ivt_segment(0.1, 0.1, 30000.0, 70000.0)
        + ivt_segment(0.1, 0.1, 70000.0, 100000.0)
    )
    assert abs(float(parts) - float(one)) < 1e-6, parts
    assert stats_prefix(
        "weathernext_3_0_0/zarr/2026_to_present/20261014_18hr_01_preds/predictions.zarr"
    ).endswith("20261014_18hr_01_preds/predictions.zarr")
    assert ENSEMBLE_IDS[0] == "ivt"
    print("ensemble parallel ok", DRAW_WORKERS)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--init", default="", help="ISO init UTC; default = latest synoptic ensemble")
    p.add_argument("--fields", default="ensemble")
    p.add_argument("--leads", default="")
    p.add_argument("--out", type=Path, default=SITE)
    p.add_argument(
        "--pnw-out",
        type=Path,
        default=None,
        help="also draw the pnw domain (40–55°N, 145–110°W) from the arrays already loaded",
    )
    p.add_argument(
        "--ca-out",
        type=Path,
        default=None,
        help="also draw the California domain (27–45°N, 145–110°W) from the arrays already loaded",
    )
    p.add_argument(
        "--nepac-out",
        type=Path,
        default=None,
        help="also draw the Northeast Pacific domain (16–55°N, 164–108°W) from the arrays already loaded",
    )
    p.add_argument("--members", type=int, default=64)
    p.add_argument("--force", action="store_true")
    p.add_argument("--merge-only", action="store_true")
    p.add_argument("--check", action="store_true", help="metadata only; no PNG reads")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    field_ids = [i for i in parse_fields(args.fields) if i in ENSEMBLE_IDS]
    if not field_ids:
        sys.exit("no ensemble fields")
    extra = {
        "ensemble_note": (
            "Upper air is the 64-member mean from the ensemble Zarr, "
            "6-hourly synoptic inits only (not the free stats mean)."
        ),
    }
    if args.check:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
        if not project_id:
            sys.exit("Set GOOGLE_CLOUD_PROJECT.")
        try:
            _p, ds, init = latest_ens(project_id)
        except DropboxBusy as exc:
            print("COOK_STATUS=noop", flush=True)
            print(f"dropbox busy: {exc}", flush=True)
            return
        ds.close()
        print(f"ENSEMBLE_INIT={init}", flush=True)
        if args.force:
            print("COOK_STATUS=needed", flush=True)
            return
        # Placeholder wide site must not force a VM start when a crop is already current.
        crops = _crop_outs(args)
        ok = True
        if dest_is_live(args.out) or not crops:
            ok = ok and ensemble_current(args.out, field_ids, init)
        for name, crop_out in crops:
            ok = ok and ensemble_current(
                crop_out, field_ids, init, domain=cook.DOMAINS[name]
            )
        print("COOK_STATUS=noop" if ok else "COOK_STATUS=needed", flush=True)
        return
    if args.merge_only:
        init = resolve_merge_init(args.init, args.out, field_ids)
        if not init:
            sys.exit("merge-only needs --init or .init stamps")
        extra["ensemble_init"] = init
        if args.out.name in cook.DOMAINS and cook.DOMAINS[args.out.name].get("place"):
            extra = _crop_extra(extra, args.out.name)
        merge_from_disk(args.out, field_ids, init, extra)
        print("COOK_STATUS=updated", flush=True)
        return

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
    if not project_id:
        sys.exit("Set GOOGLE_CLOUD_PROJECT.")
    if args.init:
        tag = datetime.fromisoformat(args.init.replace("Z", "+00:00")).strftime(
            "%Y%m%d_%Hhr_01_preds"
        )
        prefix = f"{ENS_ROOT}/{tag}/predictions.zarr"
        ds = open_ens(prefix, project_id)
        init = args.init
    else:
        try:
            prefix, ds, init = latest_ens(project_id)
        except DropboxBusy as exc:
            sys.exit(f"dropbox busy: {exc}")
    extra["ensemble_init"] = init
    print(f"ENSEMBLE_INIT={init}", flush=True)
    old_path = args.out / "manifest.json"
    old = read_manifest_or_empty(old_path)
    leads = (
        [int(x) for x in args.leads.split(",") if x.strip()] if args.leads else ensemble_leads()
    )
    leads = [h for h in leads if h in set(ensemble_leads())]
    ready = _pngs_ready(args.out, field_ids, leads)
    crop_force = {name: args.force for name, _out in _crop_outs(args)}
    for name, crop_out in _crop_outs(args):
        crop_old = read_manifest_or_empty(crop_out / "manifest.json")
        crop_force[name] = crop_force[name] or not cook.domain_matches_manifest(
            crop_old, cook.DOMAINS[name]
        )
        ready = ready and _pngs_ready(crop_out, field_ids, leads) and not crop_force[name]
    if not args.force and not args.leads and old.get("ensemble_init") == init and ready:
        print(f"already latest ensemble {init}", flush=True)
        print("COOK_STATUS=noop", flush=True)
        ds.close()
        return

    print(
        f"ensemble {init}  members {args.members}  fields {field_ids}  "
        f"frames {len(leads)}  workers {DRAW_WORKERS}",
        flush=True,
    )
    t0 = time.time()
    seq = [(hour, fid) for hour in leads for fid in field_ids]
    jobs = len(seq)
    wide_box = (float(LAT0), float(LAT1), float(LON0), float(LON1))

    def must_draw(hour: int, fid: str) -> bool:
        dest = args.out / f"frames/{fid}/f{hour:03d}.png"
        if args.force or not _fresh(dest, init):
            return True
        for _name, crop_out in _crop_outs(args):
            cdest = crop_out / f"frames/{fid}/f{hour:03d}.png"
            if crop_force[_name] or not _fresh(cdest, init):
                return True
        return False

    pending = []
    skipped = 0
    for hour, fid in seq:
        dest = args.out / f"frames/{fid}/f{hour:03d}.png"
        crops = [
            (name, str(crop_out / f"frames/{fid}/f{hour:03d}.png"), crop_force[name])
            for name, crop_out in _crop_outs(args)
        ]
        if not must_draw(hour, fid):
            skipped += 1
            continue
        pending.append(
            (hour, fid, str(dest), args.members, args.force, crops, init, wide_box)
        )
    if skipped:
        print(f"  skip {skipped} frames already stamped {init}", flush=True)
    ds.close()

    def _merge_all() -> None:
        merge_from_disk(args.out, field_ids, init, extra)
        for name, crop_out in _crop_outs(args):
            merge_from_disk(crop_out, field_ids, init, _crop_extra(extra, name))

    try:
        if pending:
            def _on_done(msg: str, n_done: int) -> None:
                print(
                    f"  {msg}  {skipped + n_done}/{jobs}  {time.time() - t0:.0f}s",
                    flush=True,
                )

            _parallel_map(
                _ens_worker_draw,
                pending,
                DRAW_WORKERS,
                initializer=_ens_worker_init,
                initargs=(project_id, prefix),
                on_done=_on_done,
            )
    finally:
        _merge_all()
    print(f"manifest {args.out / 'manifest.json'}  {time.time() - t0:.0f}s", flush=True)
    print("COOK_STATUS=updated", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        _self_check()
    else:
        main()
