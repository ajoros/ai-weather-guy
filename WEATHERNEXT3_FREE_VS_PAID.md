# WeatherNext 3 — Mike’s maps: free vs paid

Reference for Andy / Mike Snyder / Matthew Pfab.
Last checked: 2026-09-18 (this Mac, project `weathernext3-joros`).

This Mac is already signed in:

- Account: `andrew.joros@gmail.com`
- Project: `weathernext3-joros` (billing **on**, account `01DCDF-C413AA-35EB1F`)
- Allowlisted: **yes** — both GCS buckets list
- Latest stats run seen: `20260919_00hr_01_preds` (00Z synoptic → 15-day)

---

## What Mike asked for

Domain: **North America + entire northern Pacific**.
Horizon: **out to 360 hours (15 days)**.
Use (Pfab): compare to Euro / GFS for storms and extratropical cyclone / windstorms **5–10+ days out**.

| Field | Requested | In WeatherNext 3? |
|---|---|---|
| 500 mb height | yes | yes — `geopotential` at 500 hPa, **0.25°**, synoptic inits only |
| 850 mb temp | yes | yes — `temperature` at 850 hPa, same |
| SLP | yes | yes — `mean_sea_level_pressure`, 0.1° |
| Precipitable water | yes | **no** — not a model field |
| 200 / 300 mb winds | yes | yes — `u`/`v` at 200 and 300 hPa, 0.25°, synoptic inits only |
| 6-hour QPF | yes | yes — sum of `total_precipitation_1hr`, or native `total_precipitation_6hr` on synoptic full-ensemble Zarr |
| Precip type | yes | **no** — rain/mix/snow would be a temp guess, labeled as a guess |

Two kinds of runs (this is not optional):

1. **00 / 06 / 12 / 18Z** — hourly frames to **360 h**. Only these have 500 / 850 / jet. Use these for Mike.
2. **Off-synoptic hourlies (01Z, 02Z, …)** — hourly to **48 h**, **surface only**. Useless for day 8–15 maps.

Latency: a run shows up ~**8 hours** after init. 00Z is usually mid-morning UTC, not at 00Z sharp.

Still open with Mike: hourly loops, 6-hourly loops, or hourly through day 2 then 6-hourly after that. 6-hourly to day 15 is 60 frames. Hourly is 360.

---

## Part 1 — free options

“Free” here means **no Requester Pays bill** and staying inside Google’s free tiers. The **data license is still not “public domain for anything.”** Real-time forecasts (< 1 hour old and the future) are GDM experimental terms. Older than 1 hour is CC BY 4.0.

You must be on the WeatherNext allowlist (this account already is). One form covers GCS + Earth Engine + BigQuery. Typical review: 5–7 business days. No paid GCP contract required to be allowlisted.

### 1. Statistics Zarr on this Mac (best free path)

Bucket (Requester Pays **OFF**):

```
gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/
```

Realtime runs:

```
.../zarr/2026_to_present/<YYYYMMDD_HHhr_XX_preds>/predictions.zarr
```

What you get:

- Precomputed `_mean`, `_p10`, `_p25`, `_p50`, `_p75`, `_p90`
- **Surface only** (0.1° grid + 0.05° station heads)
- Hourly `lead_time` already flattened (no `lead_subtime` stacking)
- 00/06/12/18Z → 360 h; off-synoptic → 48 h
- No billing header. `gcloud storage ls` and Python `obstore` just work with ADC.

What Mike can plot for **$0** from this bucket:

- SLP (ensemble mean or a percentile)
- 6-hour QPF = six `total_precipitation_1hr_*` steps added
- 10 m wind (storm / cyclone feel at the surface)
- 2 m temp / dewpoint
- Clouds, SST, 1-hour precip, solar — if useful later

What this bucket **cannot** do:

- 500 mb height
- 850 mb temp
- 200 / 300 mb winds
- True PWAT
- Precip type
- Raw 64 members (you get stats, not members)

Python open (no project header required):

```python
import obstore
import xarray as xr
import zarr

store = obstore.store.GCSStore(
    bucket="weathernext3_statistics_spatial",
    prefix="weathernext_3_0_0_statistics/zarr/2026_to_present/20260919_00hr_01_preds/predictions.zarr",
)
ds = xr.open_zarr(zarr.storage.ObjectStore(store), chunks={})
```

Slice the NA + North Pacific box **before** `.compute()`. Longitudes are **0–360** (e.g. 130°W = 230).

This is the same store as Google’s “Zarr Spatial Statistics” Colab, which is already copied into `colabs/`.

**Cost:** $0 egress, $0 compute if we plot on this laptop. Google is eating the bucket traffic.

### 2. Official stats Colab (also $0)

[WeatherNext 3 Starter Guide — Zarr (Spatial – Statistics)](https://developers.google.com/weathernext/guides/access-forecast)

Same data as option 1. Useful if we want a browser notebook. Free Colab is enough for stats. Do **not** point free Colab at the full ensemble bucket (that becomes paid / unpredictable; see Part 2).

### 3. Earth Engine (free for noncommercial / research)

Assets:

- `projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p1deg`
- `projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p05deg`

Same surface stats as the free Zarr (mean + percentiles). Nice for a clickable map. Same hole: **no pressure levels**. EE commercial / heavy export can leave the free lane — keep it to Code Editor / research quota and don’t batch-export giant GeoTIFFs.

Official Colabs: EE 0.1° and EE 0.05°.

### 4. BigQuery free query tier

Analytics Hub listing → tables `weathernext_3_0_0_0p1deg` and `_0p05deg` in **your** project.

Again: **surface stats only**. First **1 TB / month** of query bytes is free on the on-demand sandbox/free tier. After that it is paid (~$6.25 / TB — see Part 2).

A sloppy `SELECT *` on a global hourly 0.1° forecast will burn that 1 TB fast. A tight `WHERE init_time = … AND` lon/lat filter for one run is usually fine.

Good for: point extracts, “SLP at this lat/lon vs Euro,” dashboards. Bad for: drawing 60 full-domain map frames (use Zarr or EE for that).

### 5. What we can ship Mike for free, this week

A **surface storm pack** from the stats Zarr, 00Z (or 06/12/18Z), 6-hourly to 360 h, NA + North Pacific:

1. SLP (mean; optional p10/p90 spread)
2. 6-hour QPF (mean; optional p90)
3. Optional: 10 m wind barbs / speed

That covers Pfab’s “does the cyclone exist / where is the low / how wet” question. It does **not** cover 500 heights, 850 temps, or jet.

PWAT and precip type stay out, or we label a temperature-only precip-type guess as a guess.

---

## Part 2 — options we have to pay for

The thing we pay for is almost always **the full ensemble Zarr**, because that is the **only** place 500 / 850 / 200 / 300 live.

Bucket (Requester Pays **ON**, data in **`us-east1`**):

```
gs://weathernext3_spatial/weathernext_3_0_0/zarr/
```

Must send a billing project (this one):

```bash
gcloud storage ls --billing-project=weathernext3-joros \
  gs://weathernext3_spatial/weathernext_3_0_0/zarr/
```

```python
gcs_store = obstore.store.GCSStore(
    bucket="weathernext3_spatial",
    prefix="weathernext_3_0_0/zarr/2026_to_present/20260919_00hr_01_preds/predictions.zarr",
    client_options={"default_headers": {"x-goog-user-project": "weathernext3-joros"}},
)
```

Also paid-adjacent:

- BigQuery after 1 TB / month
- Earth Engine if we go commercial or export hard
- Any VM we stand up in `us-east1`

We do **not** pay Google a WeatherNext license fee. We pay **GCP usage**.

### What the paid bucket adds (Mike’s missing maps)

| Product | Field(s) | Grid | Notes |
|---|---|---|---|
| 500H | `geopotential` @ 500 | 0.25° | divide Φ by 9.80665 for meters |
| 850T | `temperature` @ 850 | 0.25° | Kelvin |
| 200/300 winds | `u`/`v` @ 200 and 300 | 0.25° | synoptic inits only |
| Native 6-hr QPF | `total_precipitation_6hr` | 0.1° | synoptic full Zarr only |
| Raw members | `sample` = 64 | — | spread, spaghetti, member maps |

Still not in the model: **PWAT**, **precip type**.

### How the bill is calculated

Requester Pays moves **request + retrieval + egress** onto `weathernext3-joros`. Storage stays on Google’s project.

Typical GCS rates (US, check live pricing if this is for a grant):

- Internet egress, first 1 TB: about **$0.12 / GB**
- GCS → another GCP region in North America: about **$0.02 / GB**
- Same region (`us-east1` → `us-east1` VM): **$0 egress**
- Class B GETs: about **$0.004 / 10k** (cheap next to egress)
- After ~28 days the ensemble objects go **Nearline** → extra **~$0.01 / GB retrieval** on old runs

Google’s own warning: do **not** `.load()` a global 64-member forecast. That is hundreds of GB.

GCS Always Free (us-west1 / us-central1 / us-east1, if the billing account still qualifies): about **100 GB / month egress** and a pile of Class A/B ops. A **careful** month of Mike loops can stay inside that. A sloppy month will not.

### Option A — pull ensemble to this MacBook (easy, can get expensive)

Laptop is **not** `us-east1`. Every chunk we actually read is internet egress.

Ballpark uncompressed size for **one** 00Z run, NA+NP box (~110°E–50°W, ~10–80°N), **6-hourly to 360 h (60 frames)**:

| What we read | ~Uncompressed | Why |
|---|---|---|
| 6 upper-air fields, **1 member** | ~0.3 GB | cheap scout |
| 6 upper-air fields, **64-member mean** | ~20 GB | have to read all members to average |
| SLP + 1-hr precip, 64-member mean, 0.1° | ~40 GB | fatter grid |
| Same, but **hourly 360 frames** | ×6 | don’t do this first |
| Global `.load()` of the run | 100s of GB | never |

Zarr is compressed; **chunk waste** can 2–10× that if we don’t slice first.

Money if it all leaves as internet egress at $0.12/GB (and we are past Always Free):

- Careful 6-hourly, ensemble-mean, sliced domain: **~$1–5 per run**
- One 00Z per day, all month: **~$30–150**
- Hourly 360-frame loops daily: **several hundred $ / month**
- One accidental global load: **tens of $ in a single job**

Use this only for a **one-off test** (one member, one lead, one field) to prove plots.

### Option B — compute in `us-east1`, ship PNGs home (the paid path we actually want)

Stand up a small Vertex / Compute Engine VM in **`us-east1`**. Read Zarr in-region (**$0 egress**). Write PNG/GIF loops. Download only the images (MB, not GB).

VM cost example: `e2-standard-4` is on the order of **$0.13 / hour**. A 20–40 minute map job is **cents**. A box left on 24/7 is **~$90 / month** — so stop the VM.

This is how we do 500H / 850T / jet for Mike without lighting money on fire.

### Option C — Colab pointed at the ensemble bucket

Colab VMs are usually **not** `us-east1`. Same egress problem as the laptop, plus less control. Fine for the **stats** notebook. Bad as a production path for 15-day upper-air loops.

### Option D — BigQuery past the free 1 TB

On-demand is about **$6.25 / TB scanned**. Partition/filter or this becomes the surprise bill. Still no 500/850/jet.

### Option E — Earth Engine commercial / heavy export

Interactive research use: treat as free. Batch export of 60 global frames, or a commercial EE account: budget separately. Still no upper air.

### PWAT / precip type (not a GCP SKU — a science cost)

- **PWAT:** no official field. Integrating `specific_humidity` on the 13 paid pressure levels is a **guess**, and reading those levels is paid ensemble traffic. Don’t offer this as “PWAT” unless Mike agrees it’s a crude column-q estimate.
- **Precip type:** no field. A 2 m / 850 T rain–mix–snow hatch is free **if** we already have those maps, and must be labeled **guess**.

---

## How to keep it free or really low

Checked against live Zarr metadata on `20260919_00hr` (this is the important part: **chunks are global**. Cropping NA+NP does **not** reduce bytes read).

Rules, in order:

1. **Surface (SLP, 6-hr QPF, 10 m wind) → stats Zarr only.** Requester Pays off. Hourly or 6-hourly is **$0**.
2. **Do not read SLP/QPF from the ensemble bucket.** One surface field, 64 members, 15 days is ~570 GB uncompressed. That is the expensive mistake.
3. **Upper air only from the ensemble, and only the fields Mike needs.** 500H, 850T, 200 u/v, 300 u/v. Nothing else.
4. **Prefer 6-hourly frames.** 850T and 200/300 winds are stored **6-hourly only** (3D `level` arrays have 60 leads, no `lead_subtime`). True hourly jet / 850T does not exist.
5. **One synoptic run per day (00Z)** unless a storm is on. Four runs/day is 4× the paid bytes.
6. **Ensemble mean for surface is already free** (`_mean` / `_p10` / `_p90` on stats). For upper air, start with **1 member** (control). 64-member mean is 64× paid reads.
7. **If we need 64-member upper-air means, compute in `us-east1` and download PNGs.** Same-region read is $0 egress. Stop the VM.
8. **Never** `.load()` a whole run. **Never** Colab on the ensemble bucket. **Never** offer PWAT as official (13 humidity levels, paid, still a guess).

GCS Always Free (if the billing account still qualifies): ~**100 GB/month** egress from us-east1. A careful 1-member upper-air habit stays under that. A daily 64-member laptop pull does not.

---

## Cost estimate for Mike’s request

Domain does not change the bill (global chunks). Horizon = 360 h from a **00/06/12/18Z** run.

**Mike pack**

| Field | Store | 6-hourly | Hourly |
|---|---|---|---|
| SLP | stats (free) | yes | yes |
| 6-hr QPF | stats (free), sum of 1-hr precip | yes | yes (1-hr + running 6-hr) |
| 10 m wind | stats (free) | yes | yes |
| 500 mb height | ensemble `geopotential` @ 500 or `geopotential_500hPa` | yes | yes (`geopotential_500hPa` only) |
| 850 mb temp | ensemble `temperature` @ 850 | yes | **no** (6-hourly only) |
| 200 / 300 mb winds | ensemble `u`/`v` @ those levels | yes | **no** (6-hourly only) |
| PWAT | none | no | no |
| Precip type | none | no | no |

Chunk sizes (uncompressed, float32, **one global map**):

| Array | One chunk | What it covers |
|---|---|---|
| Stats surface (`*_mean`) | **25 MB** | 1 hour, full globe, already a mean |
| Ensemble 3D upper air | **4.0 MB** | 1 member, 1 six-hour lead, 1 level, full globe |
| Ensemble flattened 500H | **24 MB** | 1 member, 6 hourly frames, full globe |
| Ensemble surface (SLP/precip) | **148 MB** | 1 member, 6 hourly frames, full globe — **do not use** |

Compression is zstd. Planning number: **~3×**, so paid GB ≈ uncompressed / 3. Internet egress if we read on this Mac: **~$0.12 / GB**. `us-east1` VM: **$0 egress**.

### Per one forecast run (one 00Z)

**A. Surface only** (SLP + QPF + optional 10 m wind) — what we can ship this week

| | 6-hourly (60 frames) | Hourly (360 frames) |
|---|---|---|
| Data source | stats Zarr | stats Zarr |
| Dollars | **$0** | **$0** |
| Bytes we read | ~3–10 GB uncompressed (still free) | ~20–30 GB uncompressed (still free) |
| Time / disk | fine on this Mac | heavier; more PNGs (360 vs 60) |

**B. Full Mike pack minus PWAT / precip type** — surface from stats (**$0**) + upper air from ensemble

| Upper-air choice | 6-hourly (60 frames) | Hourly |
|---|---|---|
| **1 member** (control) | ~1.4 GB uncomp → **~0.5 GB** on the wire. Laptop: **~$0.06** or **$0** under Always Free. | 500H can be hourly (~1.4 GB uncomp extra for 1 member). 850T + jet **stay 6-hourly**. Same order: **cents / $0**. |
| **64-member mean** | ~91 GB uncomp → **~30 GB** on the wire. Laptop: **~$3.60 / run**. `us-east1` VM: **$0 egress** + ~20–40 min compute (**cents**). | Hourly 500H mean is **~91 GB uncomp just for 500H**, plus 6-hourly 850/jet (~76 GB). Laptop: **~$6–8 / run**. VM: still **$0 egress**, longer job. |

**C. The expensive mistake** — SLP/QPF from the ensemble instead of stats

| | 6-hourly or hourly (same chunks) |
|---|---|
| 1 surface field, 64 members | ~570 GB uncompressed → **~$20+ / field / run** on this Mac |
| Don’t |

### Monthly, if we post every day

Assume one 00Z run per day, 30 days. Surface always $0.

| Product | Path | 6-hourly / month | Hourly / month |
|---|---|---|---|
| SLP + QPF + 10 m wind | stats, this Mac | **$0** | **$0** |
| + 500/850/jet, **1 member** | laptop or VM | **$0** (≈15 GB, inside Always Free) | **$0** (500H hourly; 850/jet still 6-hourly) |
| + 500/850/jet, **64-member mean**, laptop | ensemble egress | **~$110** | **~$180–240** |
| + 500/850/jet, **64-member mean**, `us-east1` VM then stop it | compute only | **~$2–5** | **~$5–10** |
| Same 64-member mean, **4 synoptic runs/day**, laptop | 4× bytes | **~$400** | **~$700+** |
| Same, 4×/day on VM | VM hours | **~$8–20** | **~$20–40** |
| VM left on 24/7 | `e2-standard-4` | **~$90** for the box, unused | same dumb |

### What to tell Mike / Pfab

- **$0:** SLP, 6-hr QPF, 10 m wind, hourly or 6-hourly, 15 days, NA+NP, including ensemble mean / p10 / p90.
- **$0 or cents:** add 500H / 850T / jet at **6-hourly**, **one member**, one 00Z/day.
- **Really low (~a few $/month):** same maps as **64-member mean**, but rendered on a **`us-east1` VM** we start and stop.
- **Not cheap on this Mac:** 64-member upper-air mean pulled here daily (~$100+/month at 6-hourly).
- **Cannot buy:** true hourly 850T or hourly 200/300 winds. PWAT and precip type are not in the model.

---

## What we should actually do

| Priority | Product | Path | Money |
|---|---|---|---|
| 1 | SLP + 6-hr QPF, 6-hourly to 360 h, NA+NP | stats Zarr on this Mac | **$0** |
| 2 | Optional 10 m wind on the same frames | stats Zarr | **$0** |
| 3 | 500H, 850T, 200/300 winds | ensemble Zarr on a **`us-east1` VM** | **cents–a few $/run** if we don’t leave the VM up |
| 4 | Ensemble spread (p10/p90 SLP or QPF) | free on stats; members on ensemble | $0 / paid |
| never first | Hourly 360-frame loops, laptop ensemble pulls, PWAT, precip type as “official” | — | waste or dishonest |

**This Mac right now** can do priority 1–2 with no further GCP setup. Priority 3 needs a `us-east1` VM (or a very small laptop test with eyes on the bill).

---

## Commands that already work here

```bash
gcloud config get-value account    # andrew.joros@gmail.com
gcloud config get-value project    # weathernext3-joros

# free
gcloud storage ls \
  gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/2026_to_present/

# paid listing only (tiny)
gcloud storage ls --billing-project=weathernext3-joros \
  gs://weathernext3_spatial/weathernext_3_0_0/zarr/
```

Python libs we still need locally for plots: `xarray`, `zarr`, `obstore`, plus cartopy/matplotlib. ADC is already at `~/.config/gcloud/application_default_credentials.json` with quota project `weathernext3-joros`.
