# Time-series analysis and regeneration

The analysis service reads the warehouse hourly fact for one location, one source, and an inclusive range of Vietnam calendar dates. It calculates ten patterns with Pandas and NumPy. Each pattern is stored in the existing `analysis_results` table under a `timeseries:v1:` key scoped to the location, source, and UTC window. Other analysis keys and model tables are outside that write scope.

## REST API

Run `docker compose up -d --build warehouse-service analysis-service`. By default the analysis service is at `http://127.0.0.1:8003`. Load the desired dates first using the [historical ETL API](historical-etl.md).

| Method | Endpoint | Behavior |
| --- | --- | --- |
| POST | `/analysis/generate` | Recalculate and replace all ten patterns for the requested scope, and return the saved results. |
| GET | `/analysis/patterns` | Retrieve saved results for the matching scope. Pass `pattern` to select one pattern by name. |

Both endpoints accept `location`, `start_date`, `end_date`, and optional `source`, which defaults to `open-meteo-archive-era5`. The inclusive range limit is 3,660 days. Use the warehouse location code, such as `hai-chau`. If no patterns are stored, the GET endpoint returns an empty list. If the scope exists but lacks enough measurements, generation saves `insufficient_data` and returns explicit nulls or empty data.

```sh
curl -X POST http://127.0.0.1:8003/analysis/generate \
  -H 'Content-Type: application/json' \
  -d '{"location":"hai-chau","start_date":"2022-10-01","end_date":"2023-11-30"}'

curl 'http://127.0.0.1:8003/analysis/patterns?location=hai-chau&start_date=2022-10-01&end_date=2023-11-30&pattern=monthly_trend'
```

Each result supplies `name`, `status`, `generated_at`, an ECharts `option` object, and `metadata` for coverage and calculation details. The descriptive statistics result supplies an ECharts dataset suitable for a table or client-selected chart. [ECharts dataset format](https://echarts.apache.org/handbook/en/concepts/dataset/)

## Calculation rules

| Pattern | Method |
| --- | --- |
| `rainfall_daily`, `rainfall_weekly`, `rainfall_monthly` | Sum observed liquid rainfall in local periods. Weeks start Monday. Keep periods without rainfall readings as null and mark partial periods in the coverage metadata. |
| `rainfall_vs_humidity`, `rainfall_vs_temperature` | Pair values from the same hourly fact. Report the complete-pair count and plot a deterministic chronological sample of up to 2,000 pairs. |
| `rainfall_histogram` | Bin observed hourly rainfall, including measured zero. Metadata gives numeric bin edges and counts. |
| `monthly_trend` | Fit ordinary least squares to complete monthly totals against elapsed calendar months, including gaps in the time axis. Return slope in mm/month and R² where defined. Require at least two complete months. |
| `monthly_seasonality` | Average complete monthly totals by month of year. Report the number of contributing months for each bucket. |
| `correlation` | Pairwise Pearson correlation with valid-pair counts. Coefficients with fewer than two pairs or constant inputs are null. ERA5 total precipitation is included when present, using the same interval-ending alignment as rainfall. |
| `descriptive_statistics` | Count, minimum, maximum, mean, median, and sample standard deviation for each variable. Standard deviation is null with fewer than two values. |

A complete period has selected dates covering the entire calendar period and valid rainfall at every expected hour. Vietnam timezone transitions use the warehouse's calendar functions. The line charts show partial totals with coverage, and the trend and seasonal calculations use only complete months. [Pandas resampling](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.resample.html)

## Demo recovery

After the lecturer removes processed rows from `analysis_results`, GET the same scope to confirm the rows are absent, then POST `/analysis/generate` with that scope. The service rebuilds the patterns in one transaction from warehouse facts and available raw precipitation. It performs no ingestion or model training. Repeating generation for the same scope replaces the existing pattern set.

The database test uses real Hải Châu data for October 2022, October 2023, and November 2023, with gaps between loaded months. Set `FLOODINSIGHT_RUN_ANALYSIS_DB_TESTS=1` only against an isolated database named `floodinsight_analysis_test` with those dates backfilled and loaded. The test removes only the targeted processed pattern rows, then checks their regeneration and compares upstream and model row counts.

