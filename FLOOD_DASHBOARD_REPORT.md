# Phase 5 flood dashboard and API report

Flood Overview opens by default. The navigation includes Flood Risk Forecast, Rainfall Analytics, Machine Learning, Da Nang Flood Map and Data Management. The dashboard retains the FloodInsight identity, responsive dark/light layout, ECharts and the existing Leaflet basemap and coastline fallback.

## API contracts

| Gateway route under `/api/v1` | Data source and behavior |
| --- | --- |
| GET `/flood-risk/latest` | Every registered point with its latest stored assessment, explicit validity and a server-computed current flag. Unassessed points return a null assessment. |
| GET `/flood-risk/locations` | Warehouse point codes, names and coordinates. |
| GET `/flood-risk/history` | Stored assessments including abstentions. Supports optional `location` and bounded `limit`. |
| GET `/flood-risk/{location}/details` | Latest point evidence, timestamps, data sources, factors, contribution points and missing inputs. Unknown point codes return 404. |
| POST `/flood-risk/generate` | Generate for all registered points or a selected `location`, with optional `issued_at`. Identical evidence and issue reuse the stored record. |
| POST `/flood-predictions/train` | Accepts an optional documented Phase 4 study. Runs the readiness/training gate and can register only a review-required candidate. The DB advisory lock prevents concurrent candidate training. Approval stays with the separate operator procedure. |
| POST `/flood-predictions/predict` | Stored approved-model inference, with the original singular route retained as an alias. |
| GET `/flood-predictions/results` | Approved, persisted calibrated forecasts. `current=true` returns the most recent still-valid result per point. Optional location and limit. |
| GET `/flood-predictions/metrics` | Recorded registry evaluation, validation status and readiness. Evaluation is null when no evaluation exists. |
| GET `/flood-predictions/readiness` | Candidate evidence counts and explicit blockers. |
| GET `/flood-data/coverage` | Warehouse weather grid/date coverage, terrain, hydrology, event and label counts and data-quality summaries. |

Existing rainfall API paths and the Phase 3 assessment paths remain compatible. The Next proxy allows dashboard reads, assessment generation and prediction requests. Candidate training uses the gateway directly and stays outside the browser allowlist. The existing same-origin POST checks remain in place.

## Presentation and data boundaries

- **Flood Overview** separates current index evidence from available calibrated predictions, shows category counts, validity and evidence dates, and preserves the historical rainfall chart and date filters.
- **Flood Risk Forecast** sorts all comparison columns and opens point evidence without treating expired assessments as current. Index values use the 0–100 scale. Only calibrated probabilities use percentage formatting. Factor-weight coverage is explicitly labeled.
- **Da Nang Flood Map** reuses Leaflet point markers. Colors are green, yellow, orange and red for Low through Very High and gray for unavailable or expired evidence. Popups show issued and valid times, contribution points, missing inputs and resolution limits. The view adds no flood extent or street-level overlay.
- **Machine Learning** exposes calibrated predictions and classifications, evidence and training status, confusion and calibration charts where available, candidate comparisons, feature importance and exploratory terrain clusters. Legacy rainfall evaluation is an explicitly labeled secondary panel. Future evaluated models store raw-candidate permutation importance measured on the selection split, outside final-test selection.
- **Data Management** displays weather and flood coverage, confirmed and recorded unknown labels, terrain, hydrology, quality, readiness and persisted assessment history. Existing weather ingestion and ETL history remain available. Missing surveillance periods have no stored label and are explained separately from the recorded unknown count.

The dashboard labels the product as experimental research and directs people to local authorities for official warnings. Values come from the gateway. The isolated warehouse has no approved flood model or persisted calibrated forecasts, so model metrics and probabilities remain unavailable. Tests exercise those empty states without adding simulated production predictions or evaluations.

## Phase 5 file inventory

| File | Phase 5 change |
| --- | --- |
| `frontend/app/dashboard/dashboard.tsx` | Flood-first navigation, primary panel wiring and secondary rainfall ML controls |
| `frontend/app/dashboard/flood-data.ts` | Typed flood API data, category presentation and display helpers |
| `frontend/app/dashboard/flood-panels.tsx` | Overview, sorted comparison, evidence details and flood map |
| `frontend/app/dashboard/flood-operations.tsx` | Model evaluation, terrain clustering and data operations panels |
| `frontend/app/dashboard/station-map.tsx` | Optional flood marker content and colors on the existing map |
| `frontend/app/globals.css` | Responsive flood view, state, table and evidence styling |
| `frontend/app/layout.tsx` | Flood dashboard page description |
| `frontend/app/api/backend/[...path]/route.ts` | Flood proxy routes and bounded point detail matching |
| `frontend/package.json` | Flood API test script |
| `frontend/tests/flood-api.mjs` | Live gateway and proxy contract checks |
| `frontend/tests/dashboard.mjs` | Live browser regression for six sections, rainfall and safe empty states |
| `services/api-service/floodinsight_api/schemas/flood.py` | Typed flood requests and gateway responses |
| `services/api-service/floodinsight_api/routes/gateway.py` | Flood gateway routes and backward-compatible aliases |
| `services/prediction-service/floodinsight_prediction/routes/flood_risk.py` | Point inventory, current/read/history/detail contracts and batch assessment generation |
| `services/prediction-service/floodinsight_prediction/routes/flood_prediction.py` | Candidate train gate, approved stored results and actual model metrics |
| `services/prediction-service/floodinsight_prediction/flood_training.py` | Shared typed study input and advisory lock for candidate training |
| `services/ml-common/floodinsight_ml/flood_models.py` | Permutation importance for future evaluated candidates |
| `services/warehouse-service/floodinsight_warehouse/routes/flood_coverage.py` | Read-only coverage audit endpoint |
| `services/warehouse-service/floodinsight_warehouse/main.py` | Coverage router registration |

This report is the Phase 5 handover. Earlier phase files and data artifacts remain in the checkout.

## Verification

| Check | Result |
| --- | --- |
| `npm run typecheck` | Passed |
| `npm run lint` | Passed |
| `npm run build` | Passed on Next.js standalone output |
| `npm run test:flood-api` | Passed against the gateway and Next proxy, including typed coverage, risk generation and replay, point detail, stored history, training gate, probability abstention and legacy rainfall reads |
| `npm run test:dashboard` | Passed in Chrome against development and standalone production servers. Covered the six sections, evidence inspection, table sorting, daily/weekly/monthly rainfall charts, pattern generation, Leaflet popups and zoom, terrain grouping, legacy ML disclosure, theme switching, 390 px mobile layout and network-error handling. The final mobile check verified all monitoring markers fit on first load. |
| Existing flood-model tests | Seven passed against the isolated stack, including the live gateway test for withholding probability and retaining the risk-index route |

Visual QA confirmed the retained dark branding and light mobile layout. When external map tiles were unavailable, Leaflet rendered the existing offline coastline and all warehouse-backed point markers. The isolated stack showed five monitoring points, no approved calibrated flood forecasts and missing rainfall inputs for current numeric scores. Positive-probability and populated model-evaluation rendering therefore had no live examples in this verification. The research dashboard was tested locally.

To repeat the connected checks, start the backend services against the retained migrated database and serve Next.js. In `frontend`, set `FLOOD_TEST_GATEWAY` and `DASHBOARD_TEST_URL` if the services use non-default ports, set `DASHBOARD_BROWSER_PATH` if Chrome needs an explicit executable, then run the commands above. The browser regression uses a real point with historical rainfall and enough complete terrain profiles to run exploratory clustering.
