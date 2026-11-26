import asyncio
import logging

import httpx

from ..repositories.ingestion import IngestionBusy, IngestionRepository
from ..schemas.ingestion import RunSummary, Trigger
from .open_meteo import OpenMeteoClient, ProviderError

logger = logging.getLogger(__name__)
JOB_ID = "open-meteo-ingestion"


class IngestionService:
    def __init__(self, repository: IngestionRepository, provider: OpenMeteoClient):
        self.repository = repository
        self.provider = provider

    async def run(self, trigger: Trigger) -> RunSummary:
        async with self.repository.exclusive_run() as conn:
            source_id, run_id = await self.repository.start(conn, trigger)
            try:
                snapshots = await self.provider.fetch()
                result = await self.repository.succeed(conn, source_id, run_id, snapshots)
            except ProviderError as error:
                logger.warning("Open-Meteo run %s failed: %s", run_id, error)
                return await self.repository.finish(conn, run_id, "failed", 0, str(error))
            except asyncio.CancelledError:
                await self.repository.finish(conn, run_id, "failed", 0, "Worker was interrupted")
                raise
            except Exception:
                logger.exception("Open-Meteo run %s could not store the batch", run_id)
                await self.repository.finish(conn, run_id, "failed", 0, "Storage failed")
                raise
            logger.info("Open-Meteo run %s added %s snapshots", run_id, result.records_inserted)
            await self.refresh_assessments()
            return result

    async def refresh_assessments(self) -> None:
        url = self.provider.settings.prediction_url
        if url is None:
            return
        try:
            base = str(url).rstrip("/")
            response = await self.provider.http.post(f"{base}/flood-risk/generate", json={}, timeout=30)
            response.raise_for_status()
            assessments = response.json()
            logger.info("Flood assessment refresh: %s scored of %s points",
                        sum(row["risk_index"] is not None for row in assessments), len(assessments))
            metrics = await self.provider.http.get(f"{base}/flood-prediction/metrics")
            metrics.raise_for_status()
            if metrics.json().get("status") == "approved":
                for row in assessments:
                    prediction = await self.provider.http.post(f"{base}/flood-prediction/predict",
                                                               json={"location": row["location"]}, timeout=30)
                    prediction.raise_for_status()
        except (httpx.HTTPError, KeyError, ValueError):
            logger.exception("Flood assessment or model refresh failed after weather was stored")

    async def refresh_delayed_soil(self) -> None:
        url = str(self.provider.settings.warehouse_url).rstrip("/")
        try:
            response = await self.provider.http.post(f"{url}/warehouse/flood-soil/refresh", timeout=120)
            response.raise_for_status()
            logger.info("Delayed soil archive refresh: %s", response.json())
        except (httpx.HTTPError, ValueError):
            logger.exception("Delayed soil archive refresh failed")

    async def scheduled_run(self) -> None:
        try:
            await self.run("scheduled")
        except IngestionBusy:
            logger.info("Skipped Open-Meteo poll because ingestion is already running")
