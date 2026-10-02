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
import os
import sys
import time
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
    WIND_LEVEL,
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


class DropboxBusy(RuntimeError):
    """Newest ensemble prefix is locked; do not walk to an older run."""

ENS_BUCKET = "weathernext3_spatial"
ENS_ROOT = "weathernext_3_0_0/zarr/2026_to_present"
KT = 1.943844


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


def crop25(da: xr.DataArray) -> xr.DataArray:
    return da.sel(lat_0p25=slice(LAT0, LAT1), lon_0p25=slice(LON0, LON1))


def mean_level(ds: xr.Dataset, var: str, hour: int, level: int, members: int) -> xr.DataArray:
    sl = ds[var].sel(lead_time=np.timedelta64(hour, "h"), level=level)
    if members < int(ds.sizes.get("sample", 64)):
        sl = sl.isel(sample=slice(0, members))
    return crop25(sl.mean("sample")).load()


def ensemble_leads(limit: int = 360) -> list[int]:
    return [h for h in range(6, limit + 1, 6) if h in set(display_leads())]


def load_uv(ds: xr.Dataset, hour: int, lev: int, members: int):
    u = mean_level(ds, "u_component_of_wind", hour, lev, members)
    v = mean_level(ds, "v_component_of_wind", hour, lev, members)
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


def plot_one(
    ds: xr.Dataset,
    start: str,
    hour: int,
    fid: str,
    dest: Path,
    members: int,
    force: bool,
    crops: list[tuple[str, Path, bool]] | None = None,
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
    spec = FIELDS[fid]
    label, pal = spec[1], spec[4]
    valid_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=hour)
    dest.parent.mkdir(parents=True, exist_ok=True)
    contours = barbs = streamlines = None
    contour_z = None
    contour_color = "k"
    contour_label_color = None
    marks = None
    note = "  64-mean" if members >= 64 else f"  {members}-mem"
    if fid == "h500":
        # ponytail: Pivotal 500H = wind-speed fill (kt) + height contours, not vorticity.
        da = mean_level(ds, "geopotential", hour, 500, members)
        lon, lat, uu, vv = load_uv(ds, hour, 500, members)
        z = ms_to_kt(np.hypot(uu, vv))
        contour_z = phi_to_dam(np.asarray(da))
        contours = np.arange(468, 613, 3)
        barbs = (lon, lat, uu * KT, vv * KT)
        note += " + wind + 3 dam + barbs"
    elif fid == "t850":
        da = mean_level(ds, "temperature", hour, 850, members)
        lon, lat, uu, vv = load_uv(ds, hour, 850, members)
        z = k_to_c(np.asarray(da))
        contour_z = z
        contours = np.arange(-50, 51, 2)
        contour_color = "w"
        contour_label_color = "0.15"
        barbs = (lon, lat, uu * KT, vv * KT)
        note += " + isotherms + barbs"
    else:
        lon, lat, uu, vv = load_uv(ds, hour, WIND_LEVEL[fid], members)
        z = ms_to_kt(np.hypot(uu, vv))
        barbs = (lon, lat, uu * KT, vv * KT)
        note += " + barbs"
        if fid == "wind500":
            h = mean_level(ds, "geopotential", hour, 500, members)
            contour_z = phi_to_dam(np.asarray(h))
            contours = np.arange(468, 613, 6)
            note += " + 500H 6 dam"
    title = plot_title(label, note, valid_dt, start, hour)
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
        for name, out in (("pnw", args.pnw_out), ("ca", args.ca_out))
        if out is not None
    ]


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
        ds = open_ens(f"{ENS_ROOT}/{tag}/predictions.zarr", project_id)
        init = args.init
    else:
        try:
            _prefix, ds, init = latest_ens(project_id)
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
        f"ensemble {init}  members {args.members}  fields {field_ids}  frames {len(leads)}",
        flush=True,
    )
    t0 = time.time()
    n = 0
    jobs = len(leads) * len(field_ids)
    for hour in leads:
        for fid in field_ids:
            dest = args.out / f"frames/{fid}/f{hour:03d}.png"
            crops = [
                (name, crop_out / f"frames/{fid}/f{hour:03d}.png", crop_force[name])
                for name, crop_out in _crop_outs(args)
            ]
            msg = plot_one(ds, init, hour, fid, dest, args.members, args.force, crops)
            n += 1
            print(f"  {msg}  {n}/{jobs}  {time.time() - t0:.0f}s", flush=True)
        merge_from_disk(args.out, field_ids, init, extra)
        for name, crop_out in _crop_outs(args):
            merge_from_disk(crop_out, field_ids, init, _crop_extra(extra, name))
    ds.close()
    print(f"manifest {args.out / 'manifest.json'}  {time.time() - t0:.0f}s", flush=True)
    print("COOK_STATUS=updated", flush=True)


if __name__ == "__main__":
    main()
