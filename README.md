# AI Weather Guy

A simple **WeatherNext 3** map loop for North America and the North Pacific.

**Live page:** [ajoros.github.io/ai-weather-guy](https://ajoros.github.io/ai-weather-guy/)

This is **experimental research** from Google’s WeatherNext 3 ensemble-mean statistics. It is **not** an official forecast, watch, or warning, and it is **not NWS**. Do not use it for life-and-property decisions.

## What you get

All maps share one clock. Step with the arrows or slider; space bar plays the loop.

- **Hours 1–48:** hourly frames from the latest hourly model run
- **Hours 54–360 (day 3–15):** 6-hourly frames from the latest 15-day synoptic run (00 / 06 / 12 / 18 UTC)
- **Domain:** about 10–75°N, 120°E–60°W

Fields on the page (NWS-style color bins; °F, inches, mph):

- Station and gridded 2 m temperature and dewpoint
- 1-hour and 6-hour QPF (IMERG, model, and experimental heads)
- 6-hour IMERG p90 (sum of hourly p90, not a true 6-hour p90)
- Mean sea-level pressure with 4 mb contours
- 10 m wind with barbs in knots
- SST and cloud cover (low / mid / high behind the aviation checkbox)

Maps only. No downloadable grids.

## What this is not

Upper-air fields (500 mb height, 850 mb temperature, jet, precipitable water), ensemble members, and 3D data are **not** on this page. Those sit on a different, paid WeatherNext path.

## How it is produced (high level)

Google runs WeatherNext 3 and publishes summary statistics. We pull the newest available run, draw a fixed set of regional maps with standard meteorological color scales, and post that snapshot to the live page. The browser only flips those maps in time — it does not run the model.

The live page checks for a newer Google run about twice an hour and republishes when one is in. If the loop looks stale, a refresh has not finished yet.

## License / terms

Real-time and future WeatherNext fields are under Google’s experimental data terms. Older valid times flip to CC BY. By using the page you agree to those terms and the experimental disclaimer above.
