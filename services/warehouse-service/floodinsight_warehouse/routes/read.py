from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from ..repositories.read import read_page
from ..schemas.read import CoverageFilters, Filters, LocationFilters

router = APIRouter(prefix="/warehouse", tags=["warehouse reads"])


def page(kind, filters, period=None):
    try:
        return read_page(kind, filters, period)
    except SQLAlchemyError as error:
        raise HTTPException(503, "Warehouse database unavailable") from error


@router.get("/locations")
def locations(filters: Annotated[LocationFilters, Query()]):
    return page("locations", filters)


@router.get("/weather/observations")
def observations(filters: Annotated[Filters, Query()]):
    return page("observations", filters)


@router.get("/weather/forecasts")
def forecasts(filters: Annotated[Filters, Query()]):
    return page("forecasts", filters)


@router.get("/rainfall/coverage")
def coverage(filters: Annotated[CoverageFilters, Query()]):
    return page("rainfall_coverage", filters)


@router.get("/rainfall/{period}")
def rainfall(period: Literal["daily", "weekly", "monthly"], filters: Annotated[Filters, Query()]):
    return page("rainfall", filters, period)
