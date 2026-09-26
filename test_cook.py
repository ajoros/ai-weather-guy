#!/usr/bin/env python3
"""Self-check: lead list is 100 frames and NWS palettes line up."""

import json
from datetime import datetime, timezone

import cook
from cook import (
    PALETTES,
    CORE_IDS,
    ENSEMBLE_IDS,
    FIELD_ROWS,
    FIELDS,
    PAGE_IDS,
    accum_hours,
    assert_palettes,
    display_leads,
    ensemble_floor_lead,
    fmt_init_clock,
    fmt_valid_clock,
    page_field_ids,
    parse_fields,
    plot_title,
    WATERMARK,
    rel_vort_e5,
)
from cook_ee import (
    MIN_PNG_W,
    frame_matches,
    stale_leads,
    start_for_lead,
    synoptic_frames_current,
)
from serve_windy import lon360, parse_tile_path


def main() -> None:
    leads = display_leads()
    assert leads[:4] == [1, 2, 3, 4]
    assert leads[47] == 48
    assert leads[48] == 54
    assert leads[-1] == 360
    assert 49 not in leads and 53 not in leads
    assert len(leads) == 100
    assert_palettes()
    for name, pal in PALETTES.items():
        assert len(pal["colors"]) + 1 == len(pal["bounds"]), name
    assert parse_fields("core") == CORE_IDS
    assert CORE_IDS == ["station_t", "qpf1_imerg", "qpf_acc", "slp", "wind10", "wind10_p90"]
    assert parse_fields("ensemble") == ENSEMBLE_IDS
    assert parse_fields("page") == PAGE_IDS
    assert page_field_ids({"variables": [{"id": "slp"}]}, ["h500"]) == ["slp", "h500"]
    # 500H overlay uses a separate height field, not wind-speed contours.
    import inspect
    from cook import save_map
    assert "contour_data" in inspect.signature(save_map).parameters
    assert FIELDS["h500"][6] == 0 and FIELDS["wind10_p90"][2] == "wind_speed_10m_p90"
    assert "AI-Weather-Guy" in WATERMARK and "ajoros.github.io" in WATERMARK
    assert "WeatherNext 3" in WATERMARK
    assert FIELDS["h500"][4] == "wind_kt_pw" and FIELDS["t850"][4] == "tmp_c"
    assert FIELDS["wind300"][4] == FIELDS["wind925"][4] == FIELDS["wind700"][4] == FIELDS["wind500"][4] == "wind_kt"
    assert ensemble_floor_lead(1) == 6
    assert ensemble_floor_lead(5) == 6
    assert ensemble_floor_lead(6) == 6
    assert ensemble_floor_lead(7) == 6
    assert ensemble_floor_lead(11) == 6
    assert ensemble_floor_lead(12) == 12
    assert ensemble_floor_lead(360) == 360
    import numpy as np
    lat = np.linspace(30.0, 40.0, 21)
    lon = np.linspace(240.0, 250.0, 21)
    u = np.ones((21, 21))
    v = np.zeros((21, 21))
    assert abs(float(np.nanmean(rel_vort_e5(lon, lat, u, v)))) < 1.0
    wlat, wlon = cook.DOMAINS["wide"]["lat"], cook.DOMAINS["wide"]["lon"]
    plat, plonb = cook.DOMAINS["pnw"]["lat"], cook.DOMAINS["pnw"]["lon"]
    assert wlat[0] <= plat[0] <= plat[1] <= wlat[1]
    assert wlon[0] <= plonb[0] <= plonb[1] <= wlon[1]
    assert plat == (40.0, 55.0) and plonb == (225.0, 260.0)
    lon_g = np.linspace(120.0, 300.0, 181)
    lat_g = np.linspace(75.0, 10.0, 66)
    grid = np.arange(lat_g.size * lon_g.size).reshape(lat_g.size, lon_g.size)
    slon, slat, sz = cook.subset_box(lon_g, lat_g, [grid], (*plat, *plonb))
    assert slon[0] >= 225 and slon[-1] <= 260
    assert float(slat.min()) >= 40 and float(slat.max()) <= 55
    assert sz.shape == (slat.size, slon.size) and sz.size > 0
    cook.apply_domain("pnw")
    assert cook.LAT0 == 40.0 and cook.LON0 == 225.0 and cook.FIG_SIZE[1] < 8
    cook.apply_domain("wide")
    assert cook.LAT0 == 10.0 and cook.LON1 == 300.0
    from pathlib import Path
    from cook_ensemble import resolve_merge_init, slp_marks
    assert resolve_merge_init("2026-09-26T06:00:00Z", Path("/tmp"), ["h500"]) == "2026-09-26T06:00:00Z"
    xx, yy = np.meshgrid(lon, lat)
    slp = 1020.0 + 0.2 * ((xx - 245.0) ** 2 + (yy - 35.0) ** 2)
    slp[10, 10] = 990.0
    marks = slp_marks(lon, lat, slp)
    assert any(m[2] == "L" and m[3] < 1000 for m in marks)
    assert "qpf6_model" not in CORE_IDS and "qpf6_imerg" not in CORE_IDS
    acc = FIELDS["qpf_acc"]
    assert acc[1] == "Model QPF run total"
    assert acc[2] == "total_precipitation_1hr_mean"
    assert acc[4] == "pcp_in"
    assert acc[6] == -1
    assert accum_hours(48, -1) == list(range(1, 49))
    assert accum_hours(48, 6) == list(range(43, 49))
    assert parse_fields("all") == [row[0] for row in FIELD_ROWS]
    ids = [row[0] for row in FIELD_ROWS]
    assert ids[ids.index("qpf6_imerg") + 1] == "qpf6_imerg_p90"
    assert start_for_lead(1, "H", "S") == "H"
    assert start_for_lead(48, "H", "S") == "H"
    assert start_for_lead(54, "H", "S") == "S"
    assert start_for_lead(360, "H", "S") == "S"
    assert not synoptic_frames_current({}, "S")
    assert not synoptic_frames_current(
        {"frames": [{"lead": 54, "init": "OLD"}]}, "S"
    )
    assert synoptic_frames_current(
        {"frames": [{"lead": 1, "init": "H"}, {"lead": 54, "init": "S"}]}, "S"
    )
    from pathlib import Path
    import tempfile
    from PIL import Image
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        out = Path(tmp)
        dest = out / "frames/slp/f001.png"
        dest.parent.mkdir(parents=True)
        Image.new("RGB", (1900, 400), (30, 80, 140)).save(dest)
        dest.with_suffix(".init").write_text("H\n")
        assert frame_matches(out, "slp", 1, "H")
        assert not frame_matches(out, "slp", 1, "S")
        assert stale_leads(out, ["slp"], [1, 54], "H", "S") == [54]
        assert stale_leads(out, ["slp"], [1], "NEW", "S") == [1]
    from runs_status import collect_runs, _want
    assert _want("slp", set(range(1, 49))) == 48
    assert _want("slp", set(range(54, 361, 6))) == 52
    assert _want("h500", set(range(6, 361, 6))) == 60
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        root = Path(tmp)
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "frames": [
                        {"lead": 1, "init": "2026-09-25T17:00:00Z", "files": {"slp": "x"}},
                        {"lead": 2, "init": "2026-09-25T17:00:00Z", "files": {"slp": "x"}},
                    ]
                }
            )
        )
        slp = next(f for f in collect_runs(root)["fields"] if f["id"] == "slp")
        assert slp["inits"]["2026-09-25T17:00:00Z"] == {"n": 2, "want": 48}
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "frames": [
                        {"lead": 6, "init": "2026-09-25T17:00:00Z", "files": {"h500": "x"}},
                        {"lead": 6, "init": "2026-09-25T12:00:00Z", "files": {"h500": "x"}},
                    ]
                }
            )
        )
        h500 = next(f for f in collect_runs(root)["fields"] if f["id"] == "h500")
        assert "2026-09-25T17:00:00Z" not in h500["inits"]
        assert h500["inits"]["2026-09-25T12:00:00Z"]["n"] == 1
        from runs_status import merge_log
        now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
        kept = merge_log(
            {
                "fields": [
                    {
                        "id": "slp",
                        "label": "SLP",
                        "inits": {"2026-09-26T10:00:00Z": {"n": 48, "want": 48}},
                    }
                ]
            },
            {
                "fields": [
                    {
                        "id": "slp",
                        "label": "SLP",
                        "inits": {"2026-09-26T11:00:00Z": {"n": 48, "want": 48}},
                    }
                ]
            },
            now,
        )
        slp_log = next(f for f in kept["fields"] if f["id"] == "slp")["inits"]
        assert "2026-09-26T10:00:00Z" in slp_log and "2026-09-26T11:00:00Z" in slp_log
    assert lon360(-122.2) == 237.8
    assert lon360(200.0) == 200.0
    assert parse_tile_path("/ee/tiles/slp/54/5/4/10") == ("slp", 54, 5, 4, 10)
    assert parse_tile_path("/ee/tiles/slp/1/5/4/10.png") == ("slp", 1, 5, 4, 10)
    assert parse_tile_path("/nope") is None
    assert MIN_PNG_W >= 1800
    from pathlib import Path
    import tempfile
    from PIL import Image
    lon = np.linspace(120.0, 300.0, 36)
    lat = np.linspace(10.0, 75.0, 24)
    data = np.broadcast_to(lat[:, None], (24, 36))
    sizes = set()
    with tempfile.TemporaryDirectory() as tmp:
        for pal in ("tmp_f", "pcp_in", "slp"):
            png = Path(tmp) / f"{pal}.png"
            save_map(png, lon, lat, data, title="gap check", palette=pal)
            im = Image.open(png)
            sizes.add(im.size)
            arr = np.asarray(im)
            content = (arr[:, :, :3] < 248).any(axis=2).any(axis=0)
            last = int(np.where(content)[0][-1])
            assert arr.shape[1] - last < 40, (pal, arr.shape[1], last)
    assert len(sizes) == 1, sizes
    pdt = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)
    assert fmt_init_clock(pdt) == "8am PDT (15Z)"
    assert fmt_init_clock("2026-09-24T15:00:00Z") == "8am PDT (15Z)"
    assert fmt_valid_clock("2026-09-24T14:00:00Z") == "Thu 24 Sep 14Z / 7am PDT"
    pst = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)
    assert fmt_init_clock(pst) == "7am PST (15Z)"
    title = plot_title("10 m wind speed", " + barbs (kt)", "2026-09-24T14:00:00Z", "2026-09-24T15:00:00Z", 1)
    assert "WN3 mean" not in title
    assert "valid Thu 24 Sep 14Z / 7am PDT" in title
    assert "init 8am PDT (15Z)" in title
    assert title.endswith("F+001")
    print("ok", len(leads), "leads", len(PALETTES), "palettes", len(FIELD_ROWS), "fields")


if __name__ == "__main__":
    main()
