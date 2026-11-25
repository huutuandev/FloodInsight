import asyncio
import logging

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
            return result

    async def scheduled_run(self) -> None:
        try:
            await self.run("scheduled")
        except IngestionBusy:
            logger.info("Skipped Open-Meteo poll because ingestion is already running")
