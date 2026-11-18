from contextlib import asynccontextmanager
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..config import DatabaseSettings
from ..schemas.ingestion import LatestSnapshot, RunSummary, Snapshot, Trigger

SOURCE_CODE = "open-meteo-forecast-api"
# A stable, database-scoped PostgreSQL advisory lock for this feed.
LOCK_KEY = 0x464C4F4F444F4D31
RUN_COLUMNS = "id, run_key, trigger, status, started_at, finished_at, records_inserted, error_message"


class IngestionBusy(Exception):
    pass


class IngestionRepository:
    @asynccontextmanager
    async def connection(self):
        settings = DatabaseSettings()
        async with await psycopg.AsyncConnection.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.db,
            user=settings.user,
            password=settings.password.get_secret_value(),
            connect_timeout=5,
            options="-c timezone=UTC -c statement_timeout=15000",
            autocommit=True,
            row_factory=dict_row,
        ) as conn:
            yield conn

    @asynccontextmanager
    async def exclusive_run(self):
        async with self.connection() as conn:
            cursor = await conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (LOCK_KEY,))
            if not (await cursor.fetchone())["locked"]:
                raise IngestionBusy
            # Closing the dedicated connection always releases the session lock.
            yield conn

    async def start(self, conn, trigger: Trigger) -> tuple[int, int]:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO data_sources (code, provider, dataset, reference_url)
                VALUES (%s, 'Open-Meteo', 'Forecast API (best match)', 'https://open-meteo.com/en/docs')
                ON CONFLICT (code) DO NOTHING
                """,
                (SOURCE_CODE,),
            )
            cursor = await conn.execute("SELECT id FROM data_sources WHERE code = %s", (SOURCE_CODE,))
            source_id = (await cursor.fetchone())["id"]
            await conn.execute(
                """
                UPDATE ingestion_runs
                SET status = 'failed', finished_at = GREATEST(clock_timestamp(), started_at),
                    records_inserted = 0, error_message = 'Worker was interrupted'
                WHERE source_id = %s AND status = 'running'
                """,
                (source_id,),
            )
            cursor = await conn.execute(
                """
                INSERT INTO ingestion_runs (source_id, run_key, trigger)
                VALUES (%s, %s, %s) RETURNING id
                """,
                (source_id, uuid4().hex, trigger),
            )
            return source_id, (await cursor.fetchone())["id"]

    async def succeed(self, conn, source_id: int, run_id: int, snapshots: list[Snapshot]) -> RunSummary:
        async with conn.transaction():
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    """
                    INSERT INTO raw_weather_forecasts
                        (source_id, ingestion_run_id, source_location_key, valid_at,
                         received_at, snapshot_hash, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_id, source_location_key, valid_at, snapshot_hash)
                    WHERE snapshot_hash IS NOT NULL DO NOTHING
                    """,
                    [
                        (
                            source_id, run_id, row.location_code, row.valid_at,
                            row.received_at, row.digest, Jsonb(row.payload),
                        )
                        for row in snapshots
                    ],
                )
                inserted = cursor.rowcount
            return await self.finish(conn, run_id, "succeeded", inserted)

    async def finish(
        self, conn, run_id: int, status: str, count: int, error: str | None = None
    ) -> RunSummary:
        cursor = await conn.execute(
            f"""
            UPDATE ingestion_runs
            SET status = %s, records_inserted = %s, error_message = %s,
                finished_at = GREATEST(clock_timestamp(), started_at)
            WHERE id = %s RETURNING {RUN_COLUMNS}
            """,
            (status, count, error, run_id),
        )
        return RunSummary.model_validate(await cursor.fetchone())

    async def history(self, limit: int, offset: int) -> list[RunSummary]:
        async with self.connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT {RUN_COLUMNS} FROM ingestion_runs
                WHERE source_id = (SELECT id FROM data_sources WHERE code = %s)
                ORDER BY id DESC LIMIT %s OFFSET %s
                """,
                (SOURCE_CODE, limit, offset),
            )
            return [RunSummary.model_validate(row) for row in await cursor.fetchall()]

    async def latest(self) -> list[LatestSnapshot]:
        async with self.connection() as conn:
            cursor = await conn.execute(
                """
                SELECT DISTINCT ON (source_location_key) source_location_key AS location_code,
                    valid_at, issued_at, received_at, payload
                FROM raw_weather_forecasts
                WHERE source_id = (SELECT id FROM data_sources WHERE code = %s)
                  AND payload ->> 'kind' = 'current'
                ORDER BY source_location_key, valid_at DESC, received_at DESC, id DESC
                """,
                (SOURCE_CODE,),
            )
            return [LatestSnapshot.model_validate(row) for row in await cursor.fetchall()]
