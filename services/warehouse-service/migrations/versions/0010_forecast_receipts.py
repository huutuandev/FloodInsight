"""Preserve complete forecast runs while deduplicating raw weather values."""

from alembic import op


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE forecast_snapshot_receipts (
            snapshot_id bigint NOT NULL REFERENCES raw_weather_forecasts (id) ON DELETE CASCADE,
            run_id bigint NOT NULL REFERENCES ingestion_runs (id) ON DELETE CASCADE,
            received_at timestamptz NOT NULL,
            PRIMARY KEY (snapshot_id, run_id)
        )
    """)
    op.execute("""
        INSERT INTO forecast_snapshot_receipts (snapshot_id, run_id, received_at)
        SELECT id, ingestion_run_id, received_at FROM raw_weather_forecasts
        WHERE payload->>'kind' = 'hourly'
    """)


def downgrade():
    op.drop_table("forecast_snapshot_receipts")
