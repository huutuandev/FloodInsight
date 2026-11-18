from functools import wraps

import psycopg
from fastapi import HTTPException

from .storage import DataUnavailable, ModelUnavailable


def warehouse_errors(handler):
    @wraps(handler)
    def endpoint(*args, **kwargs):
        try:
            return handler(*args, **kwargs)
        except DataUnavailable as error:
            raise HTTPException(422, str(error)) from error
        except ModelUnavailable as error:
            raise HTTPException(404, str(error)) from error
        except (psycopg.Error, OSError) as error:
            raise HTTPException(503, "Warehouse or model storage unavailable") from error
    return endpoint

