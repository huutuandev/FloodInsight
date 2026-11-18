# FloodInsight dashboard

The Next.js dashboard is available at `http://localhost:3000` after `docker compose up -d --build`. Browser requests go through the frontend's same-origin API adapter. The Next.js server forwards dashboard routes to `FLOODINSIGHT_API_URL`, which defaults to `http://127.0.0.1:8000` outside Compose and uses `api-service:8000` inside Compose.

The Overview, Rainfall Analytics, Machine Learning, and Da Nang Map sections share a sampling point and inclusive Vietnam-local date range. Current snapshots have their own valid and receipt times. Historical rainfall is sourced from ERA5, and machine-learning sections show stored outputs and evaluation metrics for the registered models. Data Management shows operational runs and batch coverage across the system. Generate patterns and Run ingestion delegate to the backend; viewing the dashboard performs no training.

The map uses OpenStreetMap raster tiles. The optional `NEXT_PUBLIC_OSM_TILE_URL` is set at frontend build time. When tiles cannot load, the map draws a simplified coastline from the bundled [Natural Earth 1:10m coastline](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-coastline/). Sampling markers continue to use coordinates and weather from the gateway. The header photo is [Da Nang Night Panorama 01 by Dragfyre](https://commons.wikimedia.org/wiki/File:Da_Nang_Night_Panorama_01.jpg), CC BY-SA 3.0, displayed with a color overlay and responsive crop. [OpenStreetMap tile policy](https://operations.osmfoundation.org/policies/tiles/)

## Verification

From `frontend/` run:

```sh
npm ci
npm run lint
npm run build
npm run typecheck
```

For the live Chromium smoke test, start the dashboard against an isolated gateway with real warehouse data. Load complete days for Hải Châu from June 2023 through February 2024 and use a live ingestion run to populate the sampling points. Set `DASHBOARD_TEST_URL` if using a different dashboard port. The test uses installed Google Chrome by default, or the executable at `DASHBOARD_BROWSER_PATH`. Run `npm run test:dashboard`. Set `DASHBOARD_EXPECT_MODELS=1` when the stack also has saved clusters, predictions, classifications, and model metrics.

The test verifies real API responses, rainfall chart painting, generation of statistical patterns, map markers and popups, map zoom and selection, mobile overflow, theme switching, and a network failure state. It can save screenshots when `DASHBOARD_DESKTOP_SCREENSHOT` and `DASHBOARD_MOBILE_SCREENSHOT` are set.

See the [dashboard recovery runbook](dashboard-recovery.md) for backfill, ETL, model registration, and live verification. Set `DASHBOARD_EXPECT_RECOVERY=1` to check that the default date selection matches warehouse coverage.

