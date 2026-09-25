#!/usr/bin/env python3
"""Self-check: lead list is 100 frames and NWS palettes line up."""

from datetime import datetime, timezone

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
from cook_ee import MIN_PNG_W, start_for_lead, synoptic_frames_current
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
    from cook_ensemble import slp_marks
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
