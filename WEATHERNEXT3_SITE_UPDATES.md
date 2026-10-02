# WeatherNext 3 site updates

Written 2026-10-02. This is a record of the map, frame, and speed changes made on the Mac and pushed to GitHub. It does not change how the live pages look.

- Source repo: `https://github.com/ajoros/ai-weather-guy.git`, branch `main`
- Local source: `/Users/joros-minimacm4/ai-weather-guy`
- Notes copy: Dropbox `weathernext3/` (this file lives in both places)
- This file is tracked. Other `WEATHERNEXT3_*.md` notes stay local because `.gitignore` ignores them.
- Live site: `https://ajoros.github.io/ai-weather-guy`
- Published maps: GitHub branch `gh-pages`, updated by `deploy_pages.sh`, not by a commit on `main`
- Cooked PNGs stay on the Mac under `site/`. They are gitignored.

## What is already on GitHub

| Commit | What it did |
| --- | --- |
| `167db831` | California region, map-frame lock, Natural Earth borders, one ensemble tarball |
| `b1d0c70a` | Skip JPEGs that have not changed, cache each region's coastlines |
| this commit | Overlap the next ensemble read with the current draw, write the surface manifest once per lead, keep a standing `gh-pages` checkout |

`bench_vm_size.sh`, `serve_windy.py`, `site/windy.html`, and `site/zoom.html` are still untracked on purpose. They are experiments, not part of the live cook.

## Regions

Longitudes in the cook are 0–360. 145°W is 215, 110°W is 250.

| Page | Place | Lat | Lon | Thumb |
| --- | --- | --- | --- | --- |
| Wide | Pacific and North America | 10–75°N | 120–300 | 2100×759 |
| Pacific Northwest | Pacific Northwest | 40–55°N | 215–250 | 2100×900 |
| California | California | 27–45°N | 215–250 | 2100×1080 |

California is the same pattern as Pacific Northwest: a domain in `cook.py`, a nav button, `site/ca/index.html` as a symlink to `../index.html`, and `--ca-out` on the Earth Engine cook and the ensemble VM. The box label is `27–45°N, 145–110°W`.

Upper-air California frames fill on the next ensemble VM run. The surface California frames were cooked locally. Earth Engine surface cooks are free.

## Frame lock

A scheduled update once zoomed every region out to the whole world. Matplotlib autoscaled when the coastline was drawn after the weather image. `save_map` was already safe because it set the limits first. `wrap_thumb` was not.

The guard is in `cook.py` and `cook_ee.py`:

- Turn autoscale off and set the region limits before overlays.
- Plot coastlines with `scalex=False` and `scaley=False`.
- Drop outline points that fall outside the box, so a world ring cannot draw a chord across the map.
- Do not paint the Earth Engine country layer `USDOS/LSIB_SIMPLE/2017` onto thumbnails. That layer drew a false 1px line at 40°N across northern California. The real California–Oregon border is the gray state line at 42°N.
- `test_cook.py` asserts the California box, no 40°N chord, and that `add_boundaries` cannot expand the axes past the region. Do not delete that test.
- The same rule is in `.cursor/rules/map-frame.mdc`.

A full recook of wide, Pacific Northwest, and California was published after that fix. These later speed changes do not require another recook. Already published pixels stay as they are.

## Speed, without changing the pictures

Look, schedule, fields, pressure contours, and wind overlays are unchanged. JPEG quality stays 85.

### Already shipped (`b1d0c70a`)

- `stage_pages.py` converts a PNG to JPEG only when the JPEG is missing or older than the PNG. Orphan JPEGs that are not in the manifest are deleted. Pacific Northwest and California are updated in place.
- Coastline strokes are built once per region box and reused. Workers do not rebuild Natural Earth, and a cache hit does not call `apply_domain`.

### This commit

1. **Standing publish checkout** (`deploy_pages.sh`).  
   The old script cloned all of `gh-pages` into a temp directory and deleted it. It now keeps one shallow checkout at:

   `~/Library/Application Support/ai-weather-guy/gh-pages`

   Later publishes run `git fetch --depth 1` and `git reset --hard FETCH_HEAD`, then stage only what changed. The trap deletes the deploy lock, not this checkout. A failed publish is cleaned by the next reset. The push is still `git push origin HEAD:gh-pages`.

2. **Ensemble prefetch** (`cook_ensemble.py`).  
   The cook is still one Python loop on `wn3-ens-cook` (`e2-standard-4`, `us-east1-b`). While the current map is drawing, one background thread reads the next map that actually needs to be drawn. Skipped frames are not prefetched. The read uses a wide-box tuple captured on the main thread, then Pacific Northwest and California are cropped from those arrays. At most one extra field is in memory. The Zarr bytes are the same reads as before, overlapped with the draw.

3. **Surface manifest once per lead** (`cook_ee.py`).  
   The manifest used to be rewritten after every thumbnail. It is now rewritten when that region and lead hour have all of their fields. The finished JSON is the same. A crash can lose at most that one lead's manifest update instead of showing fields one by one.

`test_cook.py` was run after these edits: `ok 100 leads 11 palettes 25 fields`.

## Cost

No new Google charge.

- Same VM size. Prefetch does not add a second machine or extra Zarr bytes. If the cook finishes sooner, VM time goes down.
- Earth Engine stays on the free tier. Worker count stays 8. Do not raise it unless a timed run shows no 429s.
- Pressure and wind overlays still use the same `computePixels` resolution.
- The standing `gh-pages` checkout uses Mac disk about the size of the published site. That copy used to be deleted after every deploy. It is local disk, not a cloud bill.

Daily cost context, from `WEATHERNEXT3_COST_ANALYSIS.md`: about $1.50–2.00/day after the one-pull ensemble change, VM compute at $0.134/hour. These three edits do not add a line to that bill.

## What was left alone

- VM stays `e2-standard-4`. A one-off 8-core bench was faster, but not twice as fast, and that bench VM was deleted.
- Wide thumbnails are not cropped before Pacific Northwest and California are taken from them.
- No recook and no extra publish were run for this commit. The next scheduled `update_local.sh` and the next `deploy_pages.sh` pick the new behavior up.
