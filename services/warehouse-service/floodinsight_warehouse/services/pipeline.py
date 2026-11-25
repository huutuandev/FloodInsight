import logging

import httpx

from ..repositories.historical import HistoricalRepository
from .historical import ArchiveClient, ArchiveError, POINTS, month_batches

logger = logging.getLogger(__name__)


class HistoricalPipeline:
    def __init__(self, settings, repository: HistoricalRepository):
        self.settings = settings
        self.repository = repository

    def run(self, operation, window):
        repo = self.repository
        with repo.exclusive() as conn:
            source_id, run_id, ingestion_id = repo.start(conn, operation, window)
            progress = {"batches_processed": 0}
            error = None
            try:
                checkpoints = repo.checkpoints(conn, source_id, window)
                if operation == "backfill":
                    existing = {(b["start_date"], b["end_date"], b["location_code"]) for b in checkpoints}
                    pending = [
                        (point, start, end)
                        for start, end in month_batches(window.start_date, window.end_date)
                        for point in POINTS
                        if (start, end, point.code) not in existing
                    ]
                    progress |= {"remaining_batches": len(pending), "raw_rows_inserted": 0}
                    self._record_progress(conn, run_id, progress)
                    with httpx.Client(timeout=self.settings.archive_timeout_seconds) as http:
                        archive = ArchiveClient(
                            http, str(self.settings.archive_url), self.settings.archive_attempts
                        )
                        for point, start, end in pending[:window.max_batches]:
                            try:
                                records = archive.fetch(point, start, end)
                            except ArchiveError as exc:
                                raise ArchiveError(f"{point.code} {start} to {end}: {exc}") from exc
                            progress = repo.save_batch(
                                conn, source_id, run_id, ingestion_id, point, start, end, records, progress
                            )
                else:
                    pending = [
                        batch for batch in checkpoints
                        if (window.reprocess or batch["etl_run_id"] is None)
                        and batch["id"] > window.after_batch_id
                    ]
                    progress |= {
                        "remaining_batches": len(pending),
                        "hourly_rows_loaded": 0,
                        "last_batch_id": window.after_batch_id,
                    }
                    self._record_progress(conn, run_id, progress)
                    for batch in pending[:window.max_batches]:
                        progress = repo.load_batch(conn, run_id, batch, progress)
            except ArchiveError as exc:
                error = str(exc)
                logger.warning("Historical run %s stopped: %s", run_id, error)
            except Exception:
                error = "Warehouse batch processing failed"
                logger.exception("Historical run %s stopped during warehouse processing", run_id)
            return repo.finish(conn, run_id, ingestion_id, progress, error)

    def _record_progress(self, conn, run_id, progress):
        with conn.begin():
            self.repository.save_progress(conn, run_id, progress)

