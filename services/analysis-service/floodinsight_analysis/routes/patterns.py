from typing import Annotated

import psycopg
from fastapi import APIRouter, HTTPException, Query

from ..repositories.patterns import ScopeNotFound, regenerate, retrieve
from ..schemas.patterns import PatternQuery, PatternScope, StoredPattern

router = APIRouter(prefix="/analysis", tags=["time-series analysis"])


@router.post("/generate", response_model=list[StoredPattern])
def generate(scope: PatternScope):
    try:
        return regenerate(scope)
    except ScopeNotFound as exc:
        raise HTTPException(404, "Unknown warehouse location or weather source") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "Warehouse unavailable") from exc


@router.get("/patterns", response_model=list[StoredPattern])
def patterns(scope: Annotated[PatternQuery, Query()]):
    try:
        return retrieve(scope, scope.pattern)
    except ScopeNotFound as exc:
        raise HTTPException(404, "Unknown warehouse location or weather source") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "Warehouse unavailable") from exc

