# WeatherNext data inventory

Compiled 18 September 2026 from Google’s approval email and the official WeatherNext developer docs.

**Status:** Access approved. One allowlist grant covers Earth Engine, BigQuery, and Google Cloud Storage for the Google Account used on the data-request form. You must be logged into that account.

**Recommended product for new work:** WeatherNext 3 (released August 2026). WeatherNext 2 datasets remain available. WeatherNext Gen and Graph forecast tables on Earth Engine / BigQuery were deprecated 29 July 2026.

This is experimental research data, not an official weather warning service. Defer to national meteorological services for life-and-property decisions.

---

## 1. How to get the data (after allowlist)

| Goal | Use | What you actually get |
| --- | --- | --- |
| Full 64-member ensemble, 3D atmosphere, 6-hour accumulations | GCS Zarr `gs://weathernext3_spatial/` | Raw members, all resolutions, pressure levels |
| Hourly surface stats without stacking `lead_subtime` | GCS Zarr `gs://weathernext3_statistics_spatial/` | `_mean`, `_p10`, `_p25`, `_p50`, `_p75`, `_p90` for 0.1° and 0.05° surface fields |
| SQL joins with stores / assets / GIS | BigQuery Analytics Hub listing | Same surface stats as EE, two tables |
| Maps, rasters, satellite fusion | Earth Engine ImageCollections | Same surface stats as BQ, two collections |
| On-demand custom inference (WN2 only) | Gemini Enterprise / Model Garden | You generate Zarr into *your* bucket; WN3 is not this path |
| Self-hosted research models | GitHub `google-deepmind/weathernext` | WN2 / Gen / Graph weights. **WN3 is not open source.** |

Practical first steps:

1. Sign into Cloud Console / Earth Engine / `gcloud` as the approved Google Account.
2. Create or pick a GCP project. Full-ensemble GCS is **Requester Pays** and lives in `us-east1` — run compute in that region if you can.
3. **BigQuery:** subscribe to the WeatherNext 3 Analytics Hub listing; tables land as `[PROJECT].[DATASET].weathernext_3_0_0_0p1deg` and `..._0p05deg`.
4. **Earth Engine:** open the two catalog collections below (same names as the BQ tables).
5. **GCS:** `pip install xarray zarr obstore`, then open Zarr lazily (recipes in §7).
6. If anything 403s, email [weathernext@google.com](mailto:weathernext@google.com).

Starter Colabs are linked from the [quick-start guide](https://developers.google.com/weathernext/guides/access-forecast):

- Zarr full ensemble
- Zarr statistics
- Earth Engine 0.1°
- Earth Engine 0.05°
- BigQuery 0.1°
- BigQuery 0.05°

---

## 2. WeatherNext 3 at a glance

| Attribute | Details |
| --- | --- |
| Release | August 2026 |
| Coverage | Global |
| Architecture | Functional Generative Network (FGN) mesh transformer |
| Paper | [arXiv:2609.03582](https://arxiv.org/abs/2609.03582) — *WeatherNext 3: Increasing resolution and performance of global weather models with raw observations* |
| Inputs | Live geostationary satellite mosaics + ECMWF HRES analysis |
| Training | ERA5 / HRES-fc0, IMERG, station observations, geostationary mosaics |
| Ensemble | 64 members |
| Inits | Every hour (24 per day) |
| Timestep | 1 hour |
| Spatial | 0.05° (~5 km) station heads · 0.1° (~10 km) gridded surface · 0.25° (~25 km) pressure levels |
| Horizon | **360 h (15 days)** on 00/06/12/18 UTC inits · **48 h** on interim hourly inits |
| Historical | Operational 2026–present. 2024 and 2025 archives are being backfilled on GCS. Earth Engine catalog currently lists availability from 2026-01-01. |

Key differences vs WeatherNext 2:

- Hourly refresh (satellite in the model), not 6-hourly.
- Multi-resolution output from one forward pass.
- Station-trained 2 m temperature and dew point at 0.05°.
- Three precipitation targets (model-native, IMERG, experimental satellite-radar).
- Cloud layers + solar irradiance (SSRD / FDIR) for energy.
- Variable names put height as a **suffix** (`temperature_2m`, not `2m_temperature`).
- Precipitation is **1-hour** accumulation in meters (WN2 was 6-hour).

---

## 3. Forecast cycles (what each init contains)

WeatherNext 3 has two cycle types. They are not the same product.

### 3.1 Synoptic 6-hour inits — 00, 06, 12, 18 UTC

- Horizon: **360 hours (15 days)**, hourly steps.
- All surface + station variables.
- **Plus** 0.25° 3D pressure-level fields (GCS full ensemble only).
- **Plus** 6-hour accumulation fields (GCS full ensemble only):
  - `surface_solar_radiation_downwards_6hr`
  - `total_sky_direct_solar_radiation_at_surface_6hr`
  - `total_precipitation_6hr`

### 3.2 Interim hourly inits — 01–05, 07–11, 13–17, 19–23 UTC

- Horizon: **48 hours**, hourly steps.
- Surface + station variables only.
- No pressure levels.
- No 6-hour accumulation fields.

On the **full-ensemble Zarr**, 6-hour inits store time as `lead_time` (6 h) × `lead_subtime` (6 hourly offsets). You must stack those two dims to get a continuous hourly series. The **statistics Zarr**, BigQuery, and Earth Engine already flatten this into a single 1-hour `lead_time` / `hours` / `forecast_hour` axis.

---

## 4. Dissemination (when data lands)

All times UTC. Typical variance ±15 minutes; occasionally ±60 minutes or more. Contact weathernext@google.com if a run is more than 60 minutes late.

### WeatherNext 3 — synoptic 15-day cycles

| Init (UTC) | Horizon | GCS full ensemble + stats Zarr | BigQuery & Earth Engine |
| --- | --- | --- | --- |
| 00:00 | 360 h | 07:45 | 08:10 |
| 06:00 | 360 h | 13:45 | 14:10 |
| 12:00 | 360 h | 19:45 | 20:10 |
| 18:00 | 360 h | 01:45 next day | 02:10 next day |

Latency vs init is about **+7 h 45 min** on GCS and **+8 h 10 min** on BQ/EE.

### WeatherNext 3 — interim 48-hour cycles

Target: **+7 h 10 min** on GCS, **+7 h 25 min** on BigQuery & Earth Engine.

GCS full ensemble is published first. The statistics Zarr is derived from that. BigQuery and Earth Engine ingest the statistics product shortly after.

### WeatherNext 2 (still published)

| Init (UTC) | GCS Zarr | BigQuery | Earth Engine |
| --- | --- | --- | --- |
| 00:00 | 06:50 | 07:30 | 07:30 |
| 06:00 | 12:50 | 13:30 | 13:30 |
| 12:00 | 18:50 | 19:30 | 19:30 |
| 18:00 | 00:50 next day | 01:30 next day | 01:30 next day |

---

## 5. Variable inventory — WeatherNext 3

### 5.1 Gridded surface (0.1° / ~10 km)

Available on **all inits** on GCS, BigQuery, and Earth Engine, unless noted.

| Variable | Description | Units | Notes |
| --- | --- | --- | --- |
| `temperature_2m` | 2 m air temperature | K | Subtract 273.15 for °C |
| `dewpoint_temperature_2m` | 2 m dew point | K | Gridded head, not the station head |
| `wind_speed_10m` | 10 m scalar wind | m/s | Derived √(u²+v²) |
| `wind_speed_100m` | 100 m scalar wind (hub height) | m/s | Derived √(u²+v²) |
| `u_component_of_wind_10m` | 10 m eastward wind | m/s | |
| `v_component_of_wind_10m` | 10 m northward wind | m/s | |
| `u_component_of_wind_100m` | 100 m eastward wind | m/s | |
| `v_component_of_wind_100m` | 100 m northward wind | m/s | |
| `surface_solar_radiation_downwards_1hr` | 1 h SSRD / GHI | J/m² | |
| `total_sky_direct_solar_radiation_at_surface_1hr` | 1 h FDIR / direct beam | J/m² | |
| `surface_solar_radiation_downwards_6hr` | 6 h SSRD / GHI | J/m² | **GCS full ensemble, 6-hour inits only** |
| `total_sky_direct_solar_radiation_at_surface_6hr` | 6 h FDIR | J/m² | **GCS full ensemble, 6-hour inits only** |
| `total_precipitation_1hr` | 1 h model-native precip | m | ×1000 = mm |
| `imerg_tp_1hr` | 1 h IMERG-calibrated precip | m | ×1000 = mm |
| `experimental_tp_1hr` | 1 h experimental satellite-radar precip | m | ×1000 = mm |
| `total_precipitation_6hr` | 6 h accumulated precip | m | **GCS full ensemble, 6-hour inits only** |
| `total_cloud_cover` | Total column cloud fraction | 0–1 | |
| `high_cloud_cover` | High cloud fraction | 0–1 | |
| `medium_cloud_cover` | Medium cloud fraction | 0–1 | |
| `low_cloud_cover` | Low cloud fraction | 0–1 | |
| `mean_sea_level_pressure` | Mean sea-level pressure | Pa | |
| `sea_surface_temperature` | Sea-surface temperature | K | |

The 19 fields that appear on **BQ / EE / GCS stats** are everything in the table except the three `*_6hr` accumulations. Those 19 × 6 stats = **114 metrics/bands**.

Precipitation is accumulated over the previous 1 hour (or 6 hours for `*_6hr`), in **meters**. Daily totals = sum of 24 hourly steps, not a single daily field.

### 5.2 Station observational heads (0.05° / ~5 km)

Trained on raw station measurements. Available on **all inits**, all three platforms.

| Variable | Description | Units |
| --- | --- | --- |
| `station_head_temperature_2m` | Station-calibrated 2 m temperature | K |
| `station_head_dewpoint_temperature_2m` | Station-calibrated 2 m dew point | K |

2 variables × 6 stats = **12 metrics/bands** on BQ/EE.

Use these, not the 0.1° `temperature_2m` / `dewpoint_temperature_2m`, when you want ground-truth-like 2 m values. Pixel size on Earth Engine: **5566 m**.

### 5.3 Atmospheric pressure levels (0.25° / ~25 km)

**GCS full-ensemble Zarr only.** **6-hour inits only** (00/06/12/18 UTC). Not on BigQuery, Earth Engine, or the statistics bucket.

13 levels: **50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000 hPa**.

| Pattern | Description | Units |
| --- | --- | --- |
| `geopotential_{level}` | Geopotential Φ | m²/s² — divide by 9.80665 for height in meters |
| `specific_humidity_{level}` | Specific humidity | kg/kg |
| `temperature_{level}` | Air temperature | K |
| `u_component_of_wind_{level}` | Eastward wind | m/s |
| `v_component_of_wind_{level}` | Northward wind | m/s |
| `vertical_velocity_{level}` | Vertical velocity ω | Pa/s |

Example flattened name: `geopotential_500`. In unflattened Zarr, these sit on a `level` coordinate.

6 variables × 13 levels = **78 3D fields**.

### 5.4 Ensemble statistics (BQ, EE, GCS stats bucket)

Every surface/station variable is published as:

| Suffix | Meaning |
| --- | --- |
| `_mean` | Ensemble mean |
| `_p10` | 10th percentile |
| `_p25` | 25th percentile |
| `_p50` | Median |
| `_p75` | 75th percentile |
| `_p90` | 90th percentile |

Example: `temperature_2m_mean`, `total_precipitation_1hr_p90`.

The **full-ensemble** bucket has a `sample` dimension (64 members). Compute your own percentiles there if you need something other than the six precomputed stats (e.g. p99, member tracks, exceedance counts).

### 5.5 What is *not* on BQ / EE

- Individual ensemble members
- Pressure-level / 3D atmosphere
- 6-hour accumulation fields (`*_6hr`)
- Custom percentiles beyond p10–p90

Those require `gs://weathernext3_spatial/`.

---

## 6. Access surfaces — WeatherNext 3

### 6.1 Google Cloud Storage (Zarr v3)

Two buckets:

| | Full ensemble | Precomputed statistics |
| --- | --- | --- |
| URI | `gs://weathernext3_spatial/weathernext_3_0_0/zarr/` | `gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/` |
| Contents | 64 members, all variables, 13 pressure levels | `_mean` / `_p10`–`_p90` for 0.1° and 0.05° surface only |
| Time axis | `lead_time` (6 h) + `lead_subtime` (1 h offsets) — stack for hourly | Flattened 1-hour `lead_time` |
| Horizon | 360 h synoptic / 48 h interim | Same |
| Storage class | Standard, auto-Nearline after 28 days | Standard |
| Requester Pays | **ON** — bill to your project | **OFF** |
| Region | `us-east1` | (not specified as Requester Pays) |

Directory layout (full ensemble; stats bucket is analogous):

```
gs://weathernext3_spatial/weathernext_3_0_0/zarr/
├── 2024/                            # historical — currently being backfilled
│   ├── 6hr_inits.zarr               # 00/06/12/18 UTC, all vars, 360 h
│   └── interim_1hr_inits.zarr       # surface only, 48 h
├── 2025/                            # historical — currently being backfilled
│   ├── 6hr_inits.zarr
│   └── interim_1hr_inits.zarr
└── 2026_to_present/                 # operational, updated hourly
    └── <YYYYMMDD_HHhr_XX_preds>/
        └── predictions.zarr
```

Example real-time prefix from the docs:

`weathernext_3_0_0/zarr/2026_to_present/20260826_00hr_01_preds/predictions.zarr`

**Longitude convention:** Zarr grids are **0°–360°**, not −180°–180°. New York ≈ 286.0°. Convert with `lon_360 = lon % 360`. Reverse: `lon = (lon + 180) % 360 - 180`. Crossing the prime meridian needs two slices concatenated.

Zarr coordinate names used in recipes:

- 0.05°: `lat_0p05`, `lon_0p05`
- 0.1°: `lat_0p1`, `lon_0p1`
- Ensemble: `sample`
- Time: `init_time`, `lead_time`, `lead_subtime` (ensemble store)

Python (full ensemble — pass billing project):

```python
import obstore
import xarray as xr
import zarr

gcs_store = obstore.store.GCSStore(
    bucket="weathernext3_spatial",
    prefix="weathernext_3_0_0/zarr/2026_to_present/20260826_00hr_01_preds/predictions.zarr",
    client_options={"default_headers": {"x-goog-user-project": "YOUR_PROJECT_ID"}},
)
ds = xr.open_zarr(zarr.storage.ObjectStore(gcs_store), chunks={})
```

Statistics store (no billing header):

```python
stats_store = obstore.store.GCSStore(
    bucket="weathernext3_statistics_spatial",
    prefix="weathernext_3_0_0_statistics/zarr/2026_to_present/20260826_00hr_01_preds/predictions.zarr",
)
ds_stats = xr.open_zarr(zarr.storage.ObjectStore(stats_store), chunks={})
```

Do not `.load()` a global 64-member run. Slice variable / region / time first. A full global ensemble is hundreds of GB.

### 6.2 BigQuery

Subscribe to the **WeatherNext 3 BigQuery Analytics Hub listing**. Tables are linked into your project:

| Table | Resolution | Contents |
| --- | --- | --- |
| `[PROJECT].[DATASET].weathernext_3_0_0_0p1deg` | 0.1° | 19 surface vars × 6 stats = 114 metrics |
| `[PROJECT].[DATASET].weathernext_3_0_0_0p05deg` | 0.05° | 2 station heads × 6 stats = 12 metrics |

Schema (both tables):

| Column | Type | Role |
| --- | --- | --- |
| `init_time` | TIMESTAMP | Partition key. Forecast initialization, UTC. Always filter this. |
| `geography` | GEOGRAPHY | Grid-cell center |
| `geography_polygon` | GEOGRAPHY | 0.1° or 0.05° cell polygon. Clustered. Use `ST_INTERSECTS` / `ST_DWITHIN`. |
| `forecast` | RECORD, REPEATED | One row per lead time |

Each `forecast` element:

| Field | Type | Meaning |
| --- | --- | --- |
| `time` | TIMESTAMP | Valid time UTC |
| `hours` | INTEGER | Lead time: 1–360 (synoptic) or 1–48 (interim) |
| `<var>_<stat>` | FLOAT | e.g. `temperature_2m_mean`, `total_precipitation_1hr_p90` |

BQ longitudes are standard **−180° to 180°** (GIS), unlike Zarr.

Always `WHERE init_time = TIMESTAMP('...')` or you scan the whole table. Unnest with `, t.forecast AS f`. Select named columns, not `SELECT *`.

### 6.3 Earth Engine

| Collection | Asset ID | Resolution | Bands |
| --- | --- | --- | --- |
| 0.1° gridded | `projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p1deg` | 0.1° (~11132 m) | B0–B113 (114) |
| 0.05° stations | `projects/gcp-public-data-weathernext/assets/weathernext_3_0_0_0p05deg` | 0.05° (~5566 m) | B0–B11 (12) |

Catalog availability (as of 18 Sep 2026): `2026-01-01T00:00:00Z` through about `2026-09-18T07:00:00Z` and growing.

Each image is one init × one lead time. Image properties:

| Property | Type | Meaning |
| --- | --- | --- |
| `start_time` | String | Init time, ISO 8601 UTC, e.g. `2026-05-01T00:00:00Z` |
| `end_time` | String | Valid time = start + forecast_hour |
| `forecast_hour` | Integer | 1–360 or 1–48 |
| `system:time_start` | Long | Valid time, ms since epoch |
| `ingestion_time_utc` | Double | When EE received the image |
| `B_` | String | Band-name order |

Filter `start_time` and `forecast_hour` (and `filterBounds`) before reducing. Use the precomputed `_*` bands; do not try to reduce over members (they are not in EE). Suggested `reduceRegion` scale: **5000** for 0.05°, **10000** for 0.1°.

Full 0.1° band list (each of these six suffixes: `_mean _p10 _p25 _p50 _p75 _p90`):

`dewpoint_temperature_2m`, `experimental_tp_1hr`, `high_cloud_cover`, `imerg_tp_1hr`, `low_cloud_cover`, `mean_sea_level_pressure`, `medium_cloud_cover`, `sea_surface_temperature`, `surface_solar_radiation_downwards_1hr`, `temperature_2m`, `total_cloud_cover`, `total_precipitation_1hr`, `total_sky_direct_solar_radiation_at_surface_1hr`, `u_component_of_wind_100m`, `u_component_of_wind_10m`, `v_component_of_wind_100m`, `v_component_of_wind_10m`, `wind_speed_100m`, `wind_speed_10m`

0.05° bands: `station_head_temperature_2m_*` and `station_head_dewpoint_temperature_2m_*` with the same six suffixes.

### 6.4 Other Google products

DeepMind’s landing page also lists **Google Maps Platform** as an enterprise surface. There is no separate developer-guide schema for it in the WeatherNext docs as of this writing. Search / Maps / Gemini consumer weather is a different product path from these datasets.

---

## 7. Platform comparison (what to pick)

| Need | Pick |
| --- | --- |
| Point/region time series of temp, wind, precip, solar | BigQuery or EE stats, or GCS stats Zarr |
| Join forecasts to store / asset tables | BigQuery GIS |
| Overlay on satellite / land cover | Earth Engine |
| Heat-risk / exceedance using p90 | BQ/EE `_p90` bands, or GCS ensemble quantiles |
| Custom percentile, member spread, worst-member | GCS full ensemble `sample` dim |
| 500 hPa heights, jet, humidity aloft | GCS full ensemble, 00/06/12/18 inits |
| 6-hour precip/solar accumulations | GCS full ensemble, 00/06/12/18 inits |
| Cheapest exploratory queries | BQ/EE (no Requester Pays on the stats Zarr either) |
| Avoid GCS egress | Compute in `us-east1`, or don’t use the ensemble bucket |

---

## 8. Units and conversions

| Quantity | Native | Convert |
| --- | --- | --- |
| Temperature, dew point, SST | K | °C = K − 273.15 |
| Precipitation (1 h or 6 h) | m | mm = m × 1000 |
| Wind | m/s | |
| Pressure | Pa | hPa = Pa / 100 |
| Cloud | fraction 0–1 | % = × 100 |
| Solar (SSRD, FDIR) | J/m² over the accumulation window | W/m² ≈ J/m² / seconds in window (3600 for 1 h, 21600 for 6 h) |
| Geopotential | m²/s² | height m = Φ / 9.80665 |

---

## 9. Licensing (read this before publishing)

Two regimes. Google’s **current WN3 developer docs** (updated early September 2026) use a **1-hour** cutoff. The **GDM Terms of Use PDF** (last modified 12 November 2025) and **WeatherNext 2 Earth Engine catalog** still describe a **48-hour** cutoff. The approval email does not pick a number; it just says historic = CC BY 4.0 and real-time = GDM terms. Use the WN3 docs for WN3, and keep the PDF linked; if you need a legal call, ask weathernext@google.com.

| Data | License |
| --- | --- |
| Relates to a time **less than 1 hour ago, or the future** (WN3 docs) | [GDM Real-Time Weather Forecasting Experimental Data Terms of Use](https://storage.googleapis.com/weathernext-public/terms-of-use.pdf) |
| Relates to a time **1 hour ago or more** (WN3 docs) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — real-time data auto-flips when it ages |

Not official forecasts, watches, or warnings. “As-is,” experimental.

**Historical CC BY citation** (Earth Engine 0.1° catalog wording):

> © 2026 DeepMind Technologies Limited's machine learning models used to create the experimental data made available at https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_3_0_0_0p1deg under CC BY 4.0 licence terms. This data is intended for experimental modelling only and is not intended, validated, or approved for real world use.

Use the matching catalog URL for the 0.05° collection. Real-time citation rules are in the GDM PDF.

Upstream data includes ECMWF products (ERA5 / HRES). Third-party terms still apply; see each catalog’s acknowledgements.

---

## 10. WeatherNext 2 (still available on this allowlist)

Use only if you need continuity with older pipelines. Google recommends WN3 for new work. After ECMWF IFS Cycle 50r1 (12 May 2026), WN2 may show some accuracy regression; WN3 was trained on post-update data.

| Attribute | WeatherNext 2 |
| --- | --- |
| Release | June 2025 |
| Resolution | 0.25° (~25 km / ~27830 m pixels) |
| Timestep | 6 hours |
| Horizon | 15 days |
| Inits | 00, 06, 12, 18 UTC only |
| Ensemble | 64 members |
| History | 2022–present |
| Architecture | FGN (graph transformer, noisy weights) |
| Inputs | HRES-fc0 |
| Paper | [arXiv:2506.10772](https://arxiv.org/abs/2506.10772) |

### WN2 access paths

| Surface | Path |
| --- | --- |
| GCS ensemble | `gs://weathernext/weathernext_2_0_0/zarr` |
| GCS mean | `gs://weathernext/weathernext_2_0_0_mean/zarr` |
| Earth Engine ensemble | `projects/gcp-public-data-weathernext/assets/weathernext_2_0_0` |
| Earth Engine mean | `projects/gcp-public-data-weathernext/assets/weathernext_2_0_0_mean` |
| BigQuery | WeatherNext 2 and WeatherNext 2 Mean Analytics Hub listings |

WN2 Mean launched 11 May 2026 (real-time + historical backfill 2022–present). EE images have `ensemble_member` as a string property.

### WN2 surface variables

| Name | Units |
| --- | --- |
| `2m_temperature` | K |
| `10m_u_component_of_wind` | m/s |
| `10m_v_component_of_wind` | m/s |
| `100m_u_component_of_wind` | m/s |
| `100m_v_component_of_wind` | m/s |
| `mean_sea_level_pressure` | Pa |
| `total_precipitation` / `total_precipitation_6hr` | m, 6-hour accumulation |
| `sea_surface_temperature` | K |

No dew point, no cloud layers, no solar, no IMERG precip, no 0.05° station heads, no scalar `wind_speed_*` (derive from u/v).

### WN2 atmosphere (13 levels, same as WN3)

`{level}_geopotential`, `{level}_specific_humidity`, `{level}_temperature`, `{level}_u_component_of_wind`, `{level}_v_component_of_wind`, `{level}_vertical_velocity` at 50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000 hPa.

On Earth Engine these **are** in the collection (unlike WN3, where 3D is GCS-only).

### WN2 → WN3 name map

| WeatherNext 2 | WeatherNext 3 |
| --- | --- |
| `2m_temperature` | `temperature_2m` |
| `2m_dewpoint_temperature` | `dewpoint_temperature_2m` (WN3 only as a published field) |
| `10m_u_component_of_wind` | `u_component_of_wind_10m` |
| `10m_v_component_of_wind` | `v_component_of_wind_10m` |
| `100m_u_component_of_wind` | `u_component_of_wind_100m` |
| `100m_v_component_of_wind` | `v_component_of_wind_100m` |
| `total_precipitation` (6 h) | `total_precipitation_1hr` (sum 6 steps) or GCS `total_precipitation_6hr` |
| `{level}_geopotential` | `geopotential_{level}` |

Names without a height prefix (`mean_sea_level_pressure`, `total_cloud_cover`, `geopotential`) stay the same.

---

## 11. Older / other products

| Product | Role | Data status |
| --- | --- | --- |
| WeatherNext 1 Gen (GenCast, Dec 2024) | 0.25°, 12-hourly, 50-member diffusion ensemble | EE/BQ datasets **deprecated 29 Jul 2026**. Code/weights still on GitHub. |
| WeatherNext 1 Graph (GraphCast, Nov 2023) | 0.25°, 6-hourly, deterministic GNN | Same deprecation. Code/weights still on GitHub. |
| WeatherNext 2 Mean | Ensemble-mean convenience product | Still available (GCS / EE / BQ), 2022–present. |
| WeatherNext 3 stats `_mean` | Deterministic-style surface mean | Use this instead of a separate “WN3 Mean” product. |
| Open-source WN2 / Cyclones / Mini | Self-hosted inference | [github.com/google-deepmind/weathernext](https://github.com/google-deepmind/weathernext). Weights on `gs://dm_graphcast`. Apache 2.0 code, CC BY 4.0 non-code. **WN3 is not in this repo.** |
| Gemini Enterprise / Model Garden | On-demand WN2 inference | Separate allowlist via Cloud account team. Custom ICs as `.zarr`. Output 0.25°, up to hourly if `enable_hourly_prediction`. |

Users previously allowlisted for Graph/Gen automatically get WN3, WN2, and WN2 Mean.

---

## 12. Model lineage (context only)

| Model | When | Type | Grid | Time | Ensemble |
| --- | --- | --- | --- | --- | --- |
| WeatherNext 3 | Aug 2026 | FGN mesh transformer + live satellites | 0.05 / 0.1 / 0.25° | 1 h, hourly inits | 64 |
| WeatherNext 2 | Jun 2025 | FGN | 0.25° | 6 h, 4 inits/day | 64 |
| WeatherNext 1 Gen | Dec 2024 | Diffusion (GenCast) | 0.25° | 12 h | 50 |
| WeatherNext 1 Graph | Nov 2023 | GNN (GraphCast) | 0.25° | 6 h | 1 (deterministic) |

WN3 evaluation highlights from Google: up to 50% lower Brier / CRPS vs NWP baselines on IMERG precip; ~5× spatial resolution vs WN2 for station temperature; independent live tracking on Brightband Operational WeatherBench.

---

## 13. Support

- Data / access / late runs: [weathernext@google.com](mailto:weathernext@google.com)
- Open-source model code: same address, plus the GitHub repo

---

## 14. Link catalog

Keep these. Sources for everything above.

### Approval / landing

- [deepmind.google/technologies/weathernext](https://deepmind.google/technologies/weathernext/) — email landing page
- [deepmind.google/science/weathernext](https://deepmind.google/science/weathernext/) — same product page under /science

### Core developer guides

- [WeatherNext 3 model](https://developers.google.com/weathernext/guides/models)
- [Quick start: access forecasts](https://developers.google.com/weathernext/guides/access-forecast)
- [GCS (Zarr)](https://developers.google.com/weathernext/guides/gcs)
- [BigQuery](https://developers.google.com/weathernext/guides/bigquery)
- [Earth Engine](https://developers.google.com/weathernext/guides/earth-engine)
- [Dissemination schedule](https://developers.google.com/weathernext/guides/dissemination)
- [Terms of service and disclaimers](https://developers.google.com/weathernext/guides/disclaimers)
- [Glossary](https://developers.google.com/weathernext/guides/glossary)
- [Model deprecation](https://developers.google.com/weathernext/guides/deprecation)
- [Research and benchmarks](https://developers.google.com/weathernext/guides/research)
- [WeatherNext 2 model (legacy data)](https://developers.google.com/weathernext/guides/models-wn2)
- [Open source models](https://developers.google.com/weathernext/guides/osmodel)
- [WN2 on Gemini Enterprise — access](https://developers.google.com/weathernext/guides/access-vmg)
- [WN2 on Gemini Enterprise — working with the model](https://developers.google.com/weathernext/guides/working-vmg)
- [WN2 model specs / schema (managed inference)](https://developers.google.com/weathernext/guides/model-specs-vmg)

### Earth Engine catalogs

- [WN3 0.1°](https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_3_0_0_0p1deg)
- [WN3 0.05°](https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_3_0_0_0p05deg)
- [WN2 ensemble](https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_2_0_0)
- [WN2 mean](https://developers.google.com/earth-engine/datasets/catalog/projects_gcp-public-data-weathernext_assets_weathernext_2_0_0_mean)

### Papers / blogs

- [WN3 paper, arXiv:2609.03582](https://arxiv.org/abs/2609.03582)
- [WN2 paper, arXiv:2506.10772](https://arxiv.org/abs/2506.10772)
- [WN2 tropical cyclones, Nature 2026](https://doi.org/10.1038/s41586-026-10953-2)

### Legal

- [GDM Real-Time Weather Forecasting Experimental Data Terms of Use (PDF)](https://storage.googleapis.com/weathernext-public/terms-of-use.pdf)
- [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

### Open source / weights

- [github.com/google-deepmind/weathernext](https://github.com/google-deepmind/weathernext)
- Public weights bucket referenced in the repo: `gs://dm_graphcast`

### Contact

- [weathernext@google.com](mailto:weathernext@google.com)
