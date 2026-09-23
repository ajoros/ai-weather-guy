# WeatherNext products — by spatial and temporal resolution

Catalog of every forecast product on this allowlist. Compiled 18 September 2026 from the official WeatherNext developer docs, Earth Engine catalogs, and a live open of the WN3 stats Zarr (`20260918_06hr` had **126** data variables).

Sister notes: `WEATHERNEXT3_DATA.md` (access paths, licensing links) · `WEATHERNEXT3_DOS_DONTS.md` (what you may publish).

**Use WeatherNext 3 for new work.** Other rows below are still on the same grant.

Not official NWS/NCEP guidance.

---

## How to read this

Three independent axes. A “product” here is one **variable** (or one packaged dataset) at a given **grid** and **time structure**.

| Axis | What it means |
| --- | --- |
| **Spatial** | Native output grid. WN3 emits three grids from one forward pass. |
| **Temporal** | Init frequency, output timestep, and forecast horizon. WN3 has **two cycle types**. |
| **Ensemble packaging** | Raw 64 members vs precomputed mean / p10 / p25 / p50 / p75 / p90. |

**Valid-time license clock:** valid time &lt; 1 h ago or future → [GDM terms](https://storage.googleapis.com/weathernext-public/terms-of-use.pdf). Valid time ≥ 1 h old → [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**Units you will trip on:** temperature in **K** (−273.15 = °C). Precip in **meters** (×1000 = mm). Solar in **J/m²** over the accumulation window (÷3600 ≈ W/m² for 1 h). Pressure in **Pa** (÷100 = hPa). Cloud is 0–1.

**Zarr longitudes** are 0–360°. BigQuery / Earth Engine use −180–180°.

---

## 1. Master matrix — every WN3 field

Sorted coarsest → finest would hide the station heads. Order here is **finest spatial first**, then surface, then upper air. Temporal columns: output step, which inits, horizon.

### 1.1 Spatial 0.05° (~5 km / EE pixel 5566 m) — station observational heads

Trained on raw station observations. **All 24 inits.** All of GCS (ensemble + stats), BigQuery `weathernext_3_0_0_0p05deg`, Earth Engine `…_0p05deg`.

Use these for 2 m T / Td that should look like a station. Do **not** substitute the 0.1° `temperature_2m` / `dewpoint_temperature_2m` if that is the goal.

| Variable | Description | Units | Output step | Inits | Horizon | Stats on BQ/EE/GCS-stats | Members / 3D |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `station_head_temperature_2m` | Station-calibrated 2 m temperature | K | 1 h | all 24 | 360 h synoptic / 48 h interim | mean, p10, p25, p50, p75, p90 | 64 members on ensemble Zarr |
| `station_head_dewpoint_temperature_2m` | Station-calibrated 2 m dew point | K | 1 h | all 24 | same | same 6 | same |

**12 published metrics** on BQ/EE (2 × 6). Zarr coordinates: `lat_0p05`, `lon_0p05`.

Documented quirks (benefits & limitations): jumps across 6 h windows; per-member global warm/cold bias that resets each 6 h when a new noise vector is drawn. Ensemble mean / quantiles are the intended use.

### 1.2 Spatial 0.1° (~10 km / EE pixel 11132 m) — gridded surface

**All 24 inits** except the three `*_6hr` rows. Platforms: GCS ensemble, GCS stats, BQ `weathernext_3_0_0_0p1deg`, EE `…_0p1deg`. The `*_6hr` rows are **GCS full ensemble + synoptic inits only**.

Zarr coordinates: `lat_0p1`, `lon_0p1`.

#### Instantaneous / state fields (valid at the forecast hour)

| Variable | Description | Units | Step | Inits | Horizon | BQ/EE/stats |
| --- | --- | --- | --- | --- | --- | --- |
| `temperature_2m` | 2 m air temperature (gridded head) | K | 1 h | all | 360 / 48 h | 6 stats |
| `dewpoint_temperature_2m` | 2 m dew point (gridded head) | K | 1 h | all | 360 / 48 h | 6 stats |
| `mean_sea_level_pressure` | MSLP | Pa | 1 h | all | 360 / 48 h | 6 stats |
| `sea_surface_temperature` | SST | K | 1 h | all | 360 / 48 h | 6 stats |
| `total_cloud_cover` | Total column cloud | 0–1 | 1 h | all | 360 / 48 h | 6 stats |
| `high_cloud_cover` | High cloud | 0–1 | 1 h | all | 360 / 48 h | 6 stats |
| `medium_cloud_cover` | Medium cloud | 0–1 | 1 h | all | 360 / 48 h | 6 stats |
| `low_cloud_cover` | Low cloud | 0–1 | 1 h | all | 360 / 48 h | 6 stats |
| `wind_speed_10m` | 10 m scalar wind √(u²+v²) | m/s | 1 h | all | 360 / 48 h | 6 stats |
| `wind_speed_100m` | 100 m scalar wind (hub height) | m/s | 1 h | all | 360 / 48 h | 6 stats |
| `u_component_of_wind_10m` | 10 m eastward | m/s | 1 h | all | 360 / 48 h | 6 stats |
| `v_component_of_wind_10m` | 10 m northward | m/s | 1 h | all | 360 / 48 h | 6 stats |
| `u_component_of_wind_100m` | 100 m eastward | m/s | 1 h | all | 360 / 48 h | 6 stats |
| `v_component_of_wind_100m` | 100 m northward | m/s | 1 h | all | 360 / 48 h | 6 stats |

#### 1-hour accumulations (previous 1 hour, ending at valid time)

| Variable | Description | Units | Step | Inits | Horizon | BQ/EE/stats |
| --- | --- | --- | --- | --- | --- | --- |
| `total_precipitation_1hr` | Model-native precip | m | 1 h accum | all | 360 / 48 h | 6 stats |
| `imerg_tp_1hr` | IMERG-calibrated precip | m | 1 h accum | all | 360 / 48 h | 6 stats |
| `experimental_tp_1hr` | Experimental satellite-radar precip | m | 1 h accum | all | 360 / 48 h | 6 stats |
| `surface_solar_radiation_downwards_1hr` | SSRD / GHI | J/m² | 1 h accum | all | 360 / 48 h | 6 stats |
| `total_sky_direct_solar_radiation_at_surface_1hr` | FDIR / direct beam | J/m² | 1 h accum | all | 360 / 48 h | 6 stats |

Daily precip = **sum of 24 hourly steps**. There is no native daily field.

`experimental_tp_1hr` members show hexagonal mesh artifacts (worse than IMERG; still visible in the mean, weaker in the median). Better for pooled / areal QPF than for a single-member “radar-like” image.

#### 6-hour accumulations (previous 6 hours)

| Variable | Description | Units | Step | Inits | Horizon | Where |
| --- | --- | --- | --- | --- | --- | --- |
| `total_precipitation_6hr` | 6 h precip | m | 6 h accum | **00/06/12/18 only** | 360 h | **GCS ensemble only** |
| `surface_solar_radiation_downwards_6hr` | 6 h SSRD / GHI | J/m² | 6 h accum | **00/06/12/18 only** | 360 h | **GCS ensemble only** |
| `total_sky_direct_solar_radiation_at_surface_6hr` | 6 h FDIR | J/m² | 6 h accum | **00/06/12/18 only** | 360 h | **GCS ensemble only** |

These three are **not** on BigQuery, Earth Engine, or the statistics Zarr. Sum six `*_1hr` steps if you are on the cheap path.

**BQ/EE/stats count:** 19 surface/station-adjacent 0.1° fields × 6 stats = **114 metrics**. Plus the 12 station-head metrics = **126** on the stats Zarr (matches the live open).

### 1.3 Spatial 0.25° (~25 km) — pressure-level atmosphere

**GCS full-ensemble Zarr only.** **Synoptic inits only** (00/06/12/18 UTC). Horizon **360 h**. Output stored as 6 h `lead_time` × 1 h `lead_subtime` (stack to get hourly). **Requester Pays, `us-east1`.**

Not on BQ, EE, or the statistics bucket.

13 levels (hPa): **50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000**.

| Pattern | Description | Units | Step (after stack) | Inits | Horizon |
| --- | --- | --- | --- | --- | --- |
| `geopotential_{level}` | Geopotential Φ | m²/s² (height m = Φ / 9.80665) | 1 h | synoptic | 360 h |
| `temperature_{level}` | Air temperature | K | 1 h | synoptic | 360 h |
| `specific_humidity_{level}` | Specific humidity | kg/kg | 1 h | synoptic | 360 h |
| `u_component_of_wind_{level}` | Eastward wind | m/s | 1 h | synoptic | 360 h |
| `v_component_of_wind_{level}` | Northward wind | m/s | 1 h | synoptic | 360 h |
| `vertical_velocity_{level}` | Omega | Pa/s | 1 h | synoptic | 360 h |

Example name: `geopotential_500`. Unflattened Zarr uses a `level` coordinate.

**78 fields** (6 × 13). 64 members on `sample`. No official p10–p90 product — compute your own.

---

## 2. Same products, sorted by temporal structure

### 2.1 Output timestep

| Timestep | Products |
| --- | --- |
| **1-hour instantaneous** | All 0.05° station heads; all 0.1° state fields (T, Td, winds, clouds, MSLP, SST); all 0.25° pressure-level fields (after stacking) |
| **1-hour accumulation** | `total_precipitation_1hr`, `imerg_tp_1hr`, `experimental_tp_1hr`, `surface_solar_radiation_downwards_1hr`, `total_sky_direct_solar_radiation_at_surface_1hr` |
| **6-hour accumulation** | `total_precipitation_6hr`, `surface_solar_radiation_downwards_6hr`, `total_sky_direct_solar_radiation_at_surface_6hr` (synoptic + ensemble Zarr only) |
| **No native daily / weekly field** | Build by summing or sampling hourly steps |

### 2.2 Initialization frequency

| Init set | Hours (UTC) | Count / day |
| --- | --- | --- |
| Synoptic | 00, 06, 12, 18 | 4 |
| Interim | 01–05, 07–11, 13–17, 19–23 | 20 |
| All | every hour | 24 |

WN3 is **hourly refresh** (live geo mosaic in the model). WN2 is 6-hourly only.

### 2.3 Horizon by cycle (this is the important split)

| Cycle | Inits | Horizon | Output step | 0.05° T/Td | 0.1° surface + 1 h accum | 0.1° `*_6hr` | 0.25° 3D |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Synoptic** | 00, 06, 12, 18 UTC | **360 h (15 days)** | 1 h | yes | yes | yes, ensemble Zarr only | yes, ensemble Zarr only |
| **Interim** | all other hours | **48 h** | 1 h | yes | yes | **no** | **no** |

Interim runs are a **different product**, not a short version of the same 15-day file.

### 2.4 How time is stored (do not mix these up)

| Surface | Time coordinates | Hourly series |
| --- | --- | --- |
| GCS **stats** Zarr | `init_time`, flattened 1 h `lead_time`, `datetime` (valid time) | Use as-is. Leads 1…360 or 1…48. |
| BigQuery | `init_time` (partition), `forecast.time`, `forecast.hours` | Unnest `forecast`. Always filter `init_time`. |
| Earth Engine | `start_time` (init), `forecast_hour`, `end_time` / `system:time_start` (valid) | One image per init × lead. Filter both. |
| GCS **ensemble** Zarr | `init_time`, 6 h `lead_time`, 1 h `lead_subtime` | Stack `lead_time` × `lead_subtime` for a continuous hourly axis. |

### 2.5 When a run lands (UTC)

Typical ±15 min; sometimes ±60 min. Mail weathernext@google.com if &gt; 60 min late.

**Synoptic (360 h)**

| Init | GCS (ensemble + stats) | BigQuery & Earth Engine |
| --- | --- | --- |
| 00 | 07:45 | 08:10 |
| 06 | 13:45 | 14:10 |
| 12 | 19:45 | 20:10 |
| 18 | 01:45 next day | 02:10 next day |

≈ **+7 h 45 min** GCS, **+8 h 10 min** BQ/EE.

**Interim (48 h):** target **+7 h 10 min** GCS, **+7 h 25 min** BQ/EE.

Publish order: full ensemble → stats Zarr → BQ/EE.

### 2.6 Archive depth

| Store | History |
| --- | --- |
| EE WN3 catalogs | From `2026-01-01T00:00:00Z` (growing) |
| GCS `2026_to_present/` | Operational, updated hourly |
| GCS `2024/`, `2025/` | Backfill in progress (`6hr_inits.zarr`, `interim_1hr_inits.zarr`) |

---

## 3. Ensemble packaging (applies to every surface/station field)

| Package | Dim / suffix | Where | Use |
| --- | --- | --- | --- |
| Ensemble mean | `_mean` | BQ, EE, GCS stats | Deterministic-style map / meteogram |
| Percentiles | `_p10` `_p25` `_p50` `_p75` `_p90` | BQ, EE, GCS stats | Spread, exceedance (p90 heat / wind / QPF) |
| Raw members | `sample` = 64 | GCS `weathernext3_spatial` only | p99, member tracks, custom thresholds, 3D |

There is no separate “WN3 Mean” dataset. Use `_mean`.

---

## 4. Where each WN3 product lives

| Product | Spatial | Temporal | GCS ensemble `weathernext3_spatial` | GCS stats `weathernext3_statistics_spatial` | BigQuery | Earth Engine |
| --- | --- | --- | --- | --- | --- | --- |
| Station T, Td | 0.05° | 1 h, all inits | yes (members) | yes (6 stats) | `…_0p05deg` | `…_0p05deg` |
| Gridded surface + 1 h accum | 0.1° | 1 h, all inits | yes | yes | `…_0p1deg` | `…_0p1deg` |
| 6 h precip / solar accum | 0.1° | 6 h, synoptic | **yes** | no | no | no |
| Pressure-level 3D | 0.25° | 1 h stacked, synoptic | **yes** | no | no | no |
| Custom percentiles / members | as source | as source | **yes** | no | no | no |

Paths:

```
gs://weathernext3_spatial/weathernext_3_0_0/zarr/2026_to_present/<YYYYMMDD_HHhr_XX_preds>/predictions.zarr
gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/2026_to_present/<YYYYMMDD_HHhr_XX_preds>/predictions.zarr
```

EE assets:

- `projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p1deg`
- `projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p05deg`

Requester Pays: **on** for the ensemble bucket (`us-east1` — run compute there). **Off** for the stats bucket (also `us-east1`).

This project’s GCP id for headers / quota: `weathernext3-joros`.

---

## 5. Other products on the same allowlist

### 5.1 WeatherNext 2 (legacy operational data)

Use only for continuity / 2022–2025 history. Google recommends WN3 for new work. Possible skill regression after IFS Cycle 50r1 (12 May 2026).

| | WN2 |
| --- | --- |
| Spatial | **0.25°** only (~25 km / EE ~27830 m) |
| Timestep | **6 hours** |
| Inits | 00, 06, 12, 18 UTC only |
| Horizon | 15 days |
| Ensemble | 64 members + separate Mean product |
| History | 2022–present |

**Surface (height-prefix names):** `2m_temperature`, `10m_u/v_component_of_wind`, `100m_u/v_component_of_wind`, `mean_sea_level_pressure`, `total_precipitation` / `total_precipitation_6hr` (m, **6 h** accum), `sea_surface_temperature`.

**Missing vs WN3:** no Td, no clouds, no solar, no IMERG / experimental precip, no 0.05° station heads, no scalar `wind_speed_*` (derive).

**Atmosphere:** same 13 levels, names `{level}_geopotential` etc. **On Earth Engine** (unlike WN3 3D).

| Surface | Path |
| --- | --- |
| GCS ensemble | `gs://weathernext/weathernext_2_0_0/zarr` |
| GCS mean | `gs://weathernext/weathernext_2_0_0_mean/zarr` |
| EE ensemble / mean | `projects/gcp-public-data-weathernext/assets/weathernext_2_0_0` and `…_2_0_0_mean` |
| BigQuery | WeatherNext 2 and WeatherNext 2 Mean Analytics Hub listings |

WN2 Mean launched 11 May 2026 (real-time + 2022–present backfill).

### 5.2 WeatherNext 2 on Gemini Enterprise / Model Garden

**On-demand inference**, not a static catalog. Separate project allowlist. You write Zarr to **your** bucket. Output **0.25°**; optional `enable_hourly_prediction`. Custom ICs, ensemble size, horizon. **WN3 is not this path.** Cloud terms: no competing model, no reverse-engineering.

### 5.3 Open-source models (not WN3)

[github.com/google-deepmind/weathernext](https://github.com/google-deepmind/weathernext) — code Apache 2.0, weights CC BY 4.0 on `gs://dm_graphcast`.

| Model | Spatial | Time | Type |
| --- | --- | --- | --- |
| WeatherNext 2 / Cyclones / Mini | 0.25° or 1° Mini | 6 h typical | FGN, self-hosted |
| WeatherNext 1 Gen (GenCast) | 0.25° | 12 h, 50 members | Diffusion. EE/BQ **deprecated 29 Jul 2026** |
| WeatherNext 1 Graph (GraphCast) | 0.25° | 6 h, deterministic | GNN. Same deprecation |

### 5.4 Weather Lab

Interactive site: global layers + tropical cyclone tracks. Download experimental cyclone tracks (CSV / ATCF), ~2023–present.

| Lab layer | Spatial (display) | Time step | Horizon |
| --- | --- | --- | --- |
| WN3 mean (T2m, TP, 10 m wind, SLP) | model native | 1 h | 15 d / 48 h |
| WN2 mean (same four) | 0.25° | 6 h | 15 d |
| Global MetNet precip | — | 15 min | 12 h |
| WN Cyclones vs ECMWF ENS/HRES | tracks | — | storm |

Same 1 h GDM / CC BY split on downloads.

### 5.5 Maps Platform / consumer weather

DeepMind lists Google Maps Platform as an enterprise surface. No developer-guide schema in the WN docs. Search / Maps / Gemini consumer weather is a **different product**, not these Zarr/EE/BQ tables.

---

## 6. Name map (WN2 → WN3)

| WeatherNext 2 | WeatherNext 3 | Notes |
| --- | --- | --- |
| `2m_temperature` | `temperature_2m` | Prefer `station_head_temperature_2m` at 0.05° |
| `2m_dewpoint_temperature` | `dewpoint_temperature_2m` | WN3 publishes Td; also `station_head_*` |
| `10m_u/v_component_of_wind` | `u/v_component_of_wind_10m` | Plus scalar `wind_speed_10m` |
| `100m_u/v_component_of_wind` | `u/v_component_of_wind_100m` | Plus scalar `wind_speed_100m` |
| `total_precipitation` (6 h) | `total_precipitation_1hr` (sum 6) or ensemble `total_precipitation_6hr` | |
| `{level}_geopotential` | `geopotential_{level}` | |

Unprefixed names (`mean_sea_level_pressure`, `total_cloud_cover`, `geopotential`) stay the same.

---

## 7. Suggested derived products (not published by Google)

Build these yourself from the fields above. Safe public GitHub.io path = historical valid times + graphics that are not a raw-grid dump.

| Derived product | Inputs | Spatial | Temporal |
| --- | --- | --- | --- |
| 2 m T / Td meteogram w/ p10–p90 | station heads | 0.05° point | hourly, 48 h or 15 d |
| 24 h / 6 h QPF | sum of `*_1hr` or ensemble `*_6hr` | 0.1° | accum |
| Triple-head QPF compare | native / IMERG / experimental | 0.1° | hourly or summed |
| Wind / hub-height meteogram | `wind_speed_10m` / `_100m` + p90 | 0.1° | hourly |
| Heat / exceedance | `*_p90` or member counts | 0.05° or 0.1° | hourly |
| Cloud / solar | cloud layers + SSRD/FDIR | 0.1° | 1 h (or 6 h ensemble) |
| 500 hPa height / vort / jet | 0.25° Φ, u, v | 0.25° | hourly stacked, synoptic only |
| Thickness / lapse | `geopotential_*`, `temperature_*` | 0.25° | synoptic only |

First local plots (stats Zarr, NYC): `plots/t2m_station_series.png`, `plots/t2m_map.png`. Script: `plot_wn3_stats.py`.

---

## 8. Counts (WN3)

| | Count |
| --- | --- |
| Spatial grids | 3 (0.05° / 0.1° / 0.25°) |
| Inits per day | 24 |
| Synoptic 15-day inits | 4 |
| Interim 48 h inits | 20 |
| Ensemble members | 64 |
| Station-head base fields | 2 |
| 0.1° fields on BQ/EE/stats | 19 |
| 0.1° `*_6hr` (ensemble, synoptic) | 3 |
| Pressure levels | 13 |
| 3D field types | 6 |
| 3D fields | 78 |
| Precomputed stats per field | 6 |
| BQ/EE 0.1° metrics | 114 |
| BQ/EE 0.05° metrics | 12 |
| Stats Zarr data_vars (live check) | 126 |

---

## 9. Official sources

- [WN3 model](https://developers.google.com/weathernext/guides/models)
- [Access / Colabs](https://developers.google.com/weathernext/guides/access-forecast)
- [GCS](https://developers.google.com/weathernext/guides/gcs) · [BigQuery](https://developers.google.com/weathernext/guides/bigquery) · [Earth Engine](https://developers.google.com/weathernext/guides/earth-engine)
- [Dissemination](https://developers.google.com/weathernext/guides/dissemination)
- [EE 0.1°](https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_3_0_0_0p1deg) · [EE 0.05°](https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_3_0_0_0p05deg)
- [Benefits / limitations](https://developers.google.com/weathernext/guides/benefits-limitations)
- Paper: [arXiv:2609.03582](https://arxiv.org/abs/2609.03582)
