from ..config import DatabaseSettings
from ..repositories.forecasts import ForecastRepository
from ..schemas.historical import ForecastETLRequest


def materialize_forecasts(window: ForecastETLRequest):
    return ForecastRepository(DatabaseSettings()).materialize(
        window.start_date, window.end_date
    )
