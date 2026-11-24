"""Support forecast snapshots without provider issue times."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


TABLE = "fact_weather_forecast_hourly"


def upgrade():
    op.add_column(
        TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
    )
    op.add_column(TABLE, sa.Column("snapshot_received_at", sa.DateTime(timezone=True)))
    op.drop_constraint(op.f("ck_fact_weather_forecast_hourly_issue_time"), TABLE, type_="check")
    op.drop_constraint(op.f("pk_fact_weather_forecast_hourly"), TABLE, type_="primary")
    op.alter_column(TABLE, "issued_at", nullable=True)
    op.create_primary_key(op.f("pk_fact_weather_forecast_hourly"), TABLE, ["id"])
    op.create_check_constraint(
        op.f("ck_fact_weather_forecast_hourly_forecast_identity"),
        TABLE,
        "(issued_at IS NOT NULL AND isfinite(issued_at) AND issued_at <= hour_start_utc "
        "AND snapshot_received_at IS NULL) OR "
        "(issued_at IS NULL AND snapshot_received_at IS NOT NULL "
        "AND isfinite(snapshot_received_at))",
    )
    op.create_index(
        "uq_fact_weather_forecast_hourly_issued",
        TABLE,
        ["location_id", "weather_source_id", "hour_start_utc", "issued_at"],
        unique=True,
        postgresql_where=sa.text("issued_at IS NOT NULL"),
    )
    op.create_index(
        "uq_fact_weather_forecast_hourly_snapshot",
        TABLE,
        ["location_id", "weather_source_id", "hour_start_utc", "snapshot_received_at"],
        unique=True,
        postgresql_where=sa.text("issued_at IS NULL"),
    )
    op.create_index(
        "ix_fact_weather_forecast_hourly_snapshot",
        TABLE,
        ["hour_start_utc", "snapshot_received_at"],
    )


def downgrade():
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM {TABLE}
                WHERE issued_at IS NULL OR snapshot_received_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Remove unissued forecast snapshots before downgrading';
            END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_fact_weather_forecast_hourly_snapshot", table_name=TABLE)
    op.drop_index("uq_fact_weather_forecast_hourly_snapshot", table_name=TABLE)
    op.drop_index("uq_fact_weather_forecast_hourly_issued", table_name=TABLE)
    op.drop_constraint(
        op.f("ck_fact_weather_forecast_hourly_forecast_identity"), TABLE, type_="check"
    )
    op.drop_constraint(op.f("pk_fact_weather_forecast_hourly"), TABLE, type_="primary")
    op.alter_column(TABLE, "issued_at", nullable=False)
    op.drop_column(TABLE, "snapshot_received_at")
    op.drop_column(TABLE, "id")
    op.create_primary_key(
        op.f("pk_fact_weather_forecast_hourly"),
        TABLE,
        ["location_id", "weather_source_id", "hour_start_utc", "issued_at"],
    )
    op.create_check_constraint(
        op.f("ck_fact_weather_forecast_hourly_issue_time"),
        TABLE,
        "isfinite(issued_at) AND issued_at <= hour_start_utc",
    )
