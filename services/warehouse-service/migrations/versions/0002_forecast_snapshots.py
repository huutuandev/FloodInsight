"""Record ingestion outcomes and support forecasts without provider issuance."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_runs", sa.Column("trigger", sa.String(16)))
    op.add_column("ingestion_runs", sa.Column("records_inserted", sa.Integer()))
    op.add_column("ingestion_runs", sa.Column("error_message", sa.Text()))
    op.create_check_constraint(
        op.f("ck_ingestion_runs_trigger"), "ingestion_runs", "trigger IN ('manual', 'scheduled')"
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_record_count"), "ingestion_runs", "records_inserted >= 0"
    )
    op.create_index("ix_ingestion_runs_source_history", "ingestion_runs", ["source_id", "id"])

    op.add_column("raw_weather_forecasts", sa.Column("snapshot_hash", sa.String(64)))
    op.alter_column("raw_weather_forecasts", "issued_at", nullable=True)
    op.drop_constraint(
        op.f("ck_raw_weather_forecasts_forecast_instants"), "raw_weather_forecasts", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_raw_weather_forecasts_snapshot_or_issue"),
        "raw_weather_forecasts",
        "isfinite(valid_at) AND ("
        "(issued_at IS NOT NULL AND isfinite(issued_at) AND issued_at <= valid_at "
        "AND snapshot_hash IS NULL) OR "
        "(issued_at IS NULL AND snapshot_hash IS NOT NULL "
        "AND snapshot_hash ~ '^[0-9a-f]{64}$'))",
    )
    op.create_index(
        "uq_raw_weather_forecasts_snapshot",
        "raw_weather_forecasts",
        ["source_id", "source_location_key", "valid_at", "snapshot_hash"],
        unique=True,
        postgresql_where=sa.text("snapshot_hash IS NOT NULL"),
    )
    op.create_index(
        "ix_raw_weather_forecasts_current",
        "raw_weather_forecasts",
        ["source_id", "source_location_key", "valid_at", "received_at"],
        postgresql_where=sa.text("payload ->> 'kind' = 'current'"),
    )


def downgrade() -> None:
    # The old schema cannot represent snapshots without an issue timestamp.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM raw_weather_forecasts WHERE issued_at IS NULL) THEN
                RAISE EXCEPTION 'Export and remove unissued snapshots before downgrading to 0001';
            END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_raw_weather_forecasts_current", table_name="raw_weather_forecasts")
    op.drop_index("uq_raw_weather_forecasts_snapshot", table_name="raw_weather_forecasts")
    op.drop_constraint(
        op.f("ck_raw_weather_forecasts_snapshot_or_issue"), "raw_weather_forecasts", type_="check"
    )
    op.alter_column("raw_weather_forecasts", "issued_at", nullable=False)
    op.drop_column("raw_weather_forecasts", "snapshot_hash")
    op.create_check_constraint(
        op.f("ck_raw_weather_forecasts_forecast_instants"),
        "raw_weather_forecasts",
        "isfinite(valid_at) AND isfinite(issued_at) AND issued_at <= valid_at",
    )
    op.drop_index("ix_ingestion_runs_source_history", table_name="ingestion_runs")
    op.drop_constraint(op.f("ck_ingestion_runs_record_count"), "ingestion_runs", type_="check")
    op.drop_constraint(op.f("ck_ingestion_runs_trigger"), "ingestion_runs", type_="check")
    op.drop_column("ingestion_runs", "error_message")
    op.drop_column("ingestion_runs", "records_inserted")
    op.drop_column("ingestion_runs", "trigger")
