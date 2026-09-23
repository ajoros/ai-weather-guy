#!/usr/bin/env python3
"""Self-check: lead list is 100 frames and NWS palettes line up."""

from cook import PALETTES, assert_palettes, display_leads, parse_fields, FIELD_ROWS, CORE_IDS
from cook_ee import start_for_lead


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
    assert parse_fields("all") == [row[0] for row in FIELD_ROWS]
    ids = [row[0] for row in FIELD_ROWS]
    assert ids[ids.index("qpf6_imerg") + 1] == "qpf6_imerg_p90"
    assert start_for_lead(1, "H", "S") == "H"
    assert start_for_lead(48, "H", "S") == "H"
    assert start_for_lead(54, "H", "S") == "S"
    assert start_for_lead(360, "H", "S") == "S"
    print("ok", len(leads), "leads", len(PALETTES), "palettes", len(FIELD_ROWS), "fields")


if __name__ == "__main__":
    main()
