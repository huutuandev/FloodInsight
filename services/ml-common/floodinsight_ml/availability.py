"""Availability policy shared by rainfall and flood datasets."""

from datetime import timedelta

ERA5_DELAY = timedelta(days=6)


def archive_available_at(period_end, receipt, mode):
    if mode == "retrospective":
        return period_end + ERA5_DELAY
    return max(period_end, receipt) if receipt is not None else None
