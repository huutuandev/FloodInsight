from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .historical import HOUR

MEASURES = {
    "rainfall_mm": ("rain", Decimal("0"), Decimal("999999999.999"), "0.001"),
    "air_temperature_c": ("temperature_2m", Decimal("-100"), Decimal("70"), "0.01"),
    "relative_humidity_pct": ("relative_humidity_2m", Decimal("0"), Decimal("100"), "0.01"),
    "wind_speed_mps": ("wind_speed_10m", Decimal("0"), Decimal("99999.999"), "0.001"),
}


def transform_hours(raw: dict[datetime, dict], lower: datetime, upper: datetime):
    """Align preceding-hour rainfall with instantaneous values at interval start."""
    hourly = []
    expected = int((upper - lower) // HOUR)
    invalid: Counter = Counter()
    missing: Counter = Counter()
    missing_timestamps = sum(lower + i * HOUR not in raw for i in range(expected + 1))
    discarded = 0
    for index in range(expected):
        hour = lower + index * HOUR
        measures = {}
        for column, (variable, minimum, maximum, scale) in MEASURES.items():
            valid_at = hour + HOUR if column == "rainfall_mm" else hour
            value = raw.get(valid_at, {}).get(variable)
            if value is None:
                missing[column] += 1
                measures[column] = None
                continue
            number = Decimal(str(value))
            if not number.is_finite() or not minimum <= number <= maximum:
                invalid[column] += 1
                measures[column] = None
                continue
            measures[column] = number.quantize(Decimal(scale), rounding=ROUND_HALF_UP)
        if any(value is not None for value in measures.values()):
            hourly.append({"hour_start_utc": hour} | measures)
        else:
            discarded += 1

    report = {
        "expected_hours": expected,
        "loaded_hours": len(hourly),
        "discarded_hours": discarded,
        "missing_raw_timestamps": missing_timestamps,
        "missing_values": {column: missing[column] for column in MEASURES},
        "invalid_values": {column: invalid[column] for column in MEASURES},
        "rainfall_coverage_hours": expected - missing["rainfall_mm"] - invalid["rainfall_mm"],
    }
    return hourly, report

