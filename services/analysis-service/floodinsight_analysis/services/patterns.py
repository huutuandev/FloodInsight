from calendar import month_abbr

import numpy as np
import pandas as pd

from ..schemas.patterns import Pattern

CORE_COLUMNS = ["rainfall_mm", "relative_humidity_pct", "air_temperature_c", "wind_speed_mps"]
LABELS = {
    "rainfall_mm": "Rainfall (mm)",
    "relative_humidity_pct": "Relative humidity (%)",
    "air_temperature_c": "Temperature (°C)",
    "wind_speed_mps": "Wind speed (m/s)",
    "total_precipitation_mm": "Total precipitation (mm)",
}
SCATTER_LIMIT = 2000


def json_number(value):
    return float(value) if np.isfinite(value) else None


def rainfall_periods(hourly: pd.DataFrame, calendar: pd.DataFrame, frequency: str) -> pd.DataFrame:
    calendar = calendar.set_index(pd.to_datetime(calendar["local_date"]))
    rain = hourly.set_index(pd.to_datetime(hourly["local_date"]))["rainfall_mm"]
    daily = calendar[["expected_hours"]].copy()
    daily["rainfall_hours"] = rain.groupby(level=0).count().reindex(daily.index, fill_value=0)
    daily["rainfall_mm"] = rain.groupby(level=0).sum(min_count=1).reindex(daily.index)
    daily["days"] = 1
    grouped = daily.resample(frequency, label="left", closed="left")
    result = grouped[["expected_hours", "rainfall_hours", "days"]].sum()
    result["rainfall_mm"] = grouped["rainfall_mm"].sum(min_count=1)
    if frequency == "MS":
        full_days = result.index.days_in_month
    elif frequency == "W-MON":
        full_days = 7
    else:
        full_days = 1
    result["complete"] = (result["days"] == full_days) & (
        result["rainfall_hours"] == result["expected_hours"]
    )
    return result


def chart(x_name, y_name, rows, kind="line", category=True):
    series = {"type": kind, "encode": {"x": 0, "y": 1}}
    if kind == "line":
        series["connectNulls"] = False
    return {
        "dataset": {"dimensions": [x_name, y_name], "source": rows},
        "tooltip": {"trigger": "axis" if kind != "scatter" else "item"},
        "xAxis": {"type": "category" if category else "value", "name": x_name},
        "yAxis": {"type": "value", "name": y_name},
        "series": [series],
    }


def pattern(name, option, metadata, ready):
    return Pattern(
        name=name, status="ready" if ready else "insufficient_data",
        option=option, metadata=metadata,
    )


def rainfall_line(name, periods):
    rows = [[day.date().isoformat(), json_number(row.rainfall_mm)] for day, row in periods.iterrows()]
    coverage = [
        {
            "date": day.date().isoformat(),
            "hours": int(row.rainfall_hours),
            "expected_hours_in_selection": int(row.expected_hours),
            "complete_period": bool(row.complete),
        }
        for day, row in periods.iterrows()
    ]
    return pattern(name, chart("Period start", "Rainfall (mm)", rows), {"coverage": coverage},
                   periods["rainfall_mm"].notna().any())


def scatter(hourly, variable, name):
    pairs = hourly[[variable, "rainfall_mm"]].dropna()
    if len(pairs) > SCATTER_LIMIT:
        sample = pairs.iloc[np.linspace(0, len(pairs) - 1, SCATTER_LIMIT, dtype=int)]
    else:
        sample = pairs
    option = chart(LABELS[variable], LABELS["rainfall_mm"], sample.to_numpy().tolist(),
                   kind="scatter", category=False)
    return pattern(name, option, {"paired_hours": len(pairs), "plotted_hours": len(sample)}, len(pairs) > 0)


def histogram(hourly):
    rain = hourly["rainfall_mm"].dropna().to_numpy()
    bins = []
    if rain.size:
        if rain.min() == rain.max():
            counts, edges = np.histogram(rain, bins=[rain.min(), rain.min() + 1])
        else:
            counts, edges = np.histogram(rain, bins=min(20, max(2, int(np.sqrt(rain.size)))))
        bins = [
            {"lower_mm": float(edges[i]), "upper_mm": float(edges[i + 1]), "hours": int(count)}
            for i, count in enumerate(counts)
        ]
    rows = [[f"{b['lower_mm']:.6g}–{b['upper_mm']:.6g}", b["hours"]] for b in bins]
    return pattern("rainfall_histogram", chart("Rainfall bin (mm)", "Hours", rows, kind="bar"),
                   {"bins": bins, "observed_hours": int(rain.size)}, bool(rain.size))


def monthly_trend(monthly):
    complete = monthly["rainfall_mm"].where(monthly["complete"])
    good = complete.notna().to_numpy()
    offsets = np.arange(len(complete))
    fit = np.full(len(complete), np.nan)
    slope, r_squared = None, None
    if good.sum() >= 2:
        x, y = offsets[good], complete.to_numpy()[good]
        a, b = np.polyfit(x, y, 1)
        slope = float(a)
        inside = (offsets >= x[0]) & (offsets <= x[-1])
        fit[inside] = a * offsets[inside] + b
        tss = np.square(y - y.mean()).sum()
        if tss > 0:
            r_squared = float(1 - np.square(y - fit[good]).sum() / tss)
    rows = [
        [day.date().isoformat(), json_number(value), json_number(fitted)]
        for day, value, fitted in zip(complete.index, complete, fit)
    ]
    option = chart("Month start", "Rainfall (mm)", rows)
    option["dataset"]["dimensions"] = ["Month start", "Complete-month rainfall", "Linear fit"]
    option["series"][0]["name"] = "Complete-month rainfall"
    option["series"].append({"type": "line", "name": "Linear fit", "encode": {"x": 0, "y": 2}})
    option["legend"] = {}
    return pattern("monthly_trend", option, {
        "complete_months": int(good.sum()), "slope_mm_per_month": slope, "r_squared": r_squared,
    }, slope is not None)


def monthly_seasonality(monthly):
    complete = monthly.loc[monthly["complete"], "rainfall_mm"]
    groups = complete.groupby(complete.index.month)
    months = range(1, 13)
    means = groups.mean().reindex(months)
    counts = groups.count().reindex(months, fill_value=0)
    rows = [[month_abbr[i], json_number(means.loc[i])] for i in months]
    return pattern("monthly_seasonality", chart("Month of year", "Mean rainfall (mm)", rows, kind="bar"),
                   {"complete_month_counts": counts.tolist()}, not complete.empty)


def correlation(hourly):
    matrix = hourly.corr(method="pearson", min_periods=2)
    present = hourly.notna().astype(int)
    counts = present.T @ present
    values = [[json_number(value) for value in row] for row in matrix.to_numpy()]
    pairs = [[x, y, value] for y, row in enumerate(values) for x, value in enumerate(row) if value is not None]
    names = list(hourly.columns)
    labels = [LABELS[name] for name in names]
    option = {
        "tooltip": {},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "category", "data": labels},
        "visualMap": {"min": -1, "max": 1, "calculable": True},
        "series": [{"type": "heatmap", "data": pairs}],
    }
    return pattern("correlation", option, {
        "variables": names, "matrix": values, "pair_counts": counts.to_numpy().tolist(),
    }, any(x != y for x, y, _ in pairs))


def descriptive(hourly):
    rows = [
        [variable, int(values.count()), *map(json_number, (
            values.min(), values.max(), values.mean(), values.median(), values.std(ddof=1),
        ))]
        for variable, values in hourly.items()
    ]
    return pattern("descriptive_statistics", {"dataset": {
        "dimensions": ["variable", "count", "min", "max", "mean", "median", "std_dev"],
        "source": rows,
    }}, {"variables": {name: LABELS[name] for name in hourly.columns}, "std_dev_definition": "sample (ddof=1)"},
        any(row[1] for row in rows))


def calculate_patterns(hourly: pd.DataFrame, calendar: pd.DataFrame) -> list[Pattern]:
    columns = CORE_COLUMNS.copy()
    optional = "total_precipitation_mm"
    if optional in hourly and hourly[optional].notna().any():
        columns.append(optional)
    hourly = hourly.copy()
    hourly[columns] = hourly[columns].astype(float)
    hourly[columns] = hourly[columns].replace([np.inf, -np.inf], np.nan)
    daily = rainfall_periods(hourly, calendar, "D")
    weekly = rainfall_periods(hourly, calendar, "W-MON")
    monthly = rainfall_periods(hourly, calendar, "MS")
    return [
        rainfall_line("rainfall_daily", daily),
        rainfall_line("rainfall_weekly", weekly),
        rainfall_line("rainfall_monthly", monthly),
        scatter(hourly, "relative_humidity_pct", "rainfall_vs_humidity"),
        scatter(hourly, "air_temperature_c", "rainfall_vs_temperature"),
        histogram(hourly),
        monthly_trend(monthly),
        monthly_seasonality(monthly),
        correlation(hourly[columns]),
        descriptive(hourly[columns]),
    ]

