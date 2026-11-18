"""Track historical batches and expose weather aggregates."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warehouse_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("progress", postgresql.JSONB(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint("operation IN ('backfill', 'etl')", name=op.f("ck_warehouse_runs_operation")),
        sa.CheckConstraint("end_date >= start_date", name=op.f("ck_warehouse_runs_dates")),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) OR "
            "(status IN ('succeeded', 'failed') AND finished_at IS NOT NULL "
            "AND finished_at >= started_at)",
            name=op.f("ck_warehouse_runs_lifecycle"),
        ),
    )
    op.create_table(
        "historical_batches",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("location_code", sa.String(100), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("ingestion_run_id", sa.BigInteger(), nullable=False),
        sa.Column("backfill_run_id", sa.BigInteger(), sa.ForeignKey("warehouse_runs.id"), nullable=False),
        sa.Column("etl_run_id", sa.BigInteger(), sa.ForeignKey("warehouse_runs.id")),
        sa.Column("quality", postgresql.JSONB()),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id", "source_id"], ["ingestion_runs.id", "ingestion_runs.source_id"],
            name="fk_historical_batches_ingestion_run_id",
        ),
        sa.UniqueConstraint(
            "source_id", "location_code", "start_date", "end_date",
            name="uq_historical_batches_source_id",
        ),
        sa.CheckConstraint("end_date >= start_date", name=op.f("ck_historical_batches_dates")),
        sa.CheckConstraint(
            "(etl_run_id IS NULL) = (quality IS NULL)", name=op.f("ck_historical_batches_quality")
        ),
    )
    op.create_index("ix_historical_batches_date_range", "historical_batches", ["start_date", "end_date"])
    op.drop_constraint(op.f("ck_fact_rainfall_daily_hour_count"), "fact_rainfall_daily", type_="check")
    op.create_check_constraint(
        op.f("ck_fact_rainfall_daily_hour_count"), "fact_rainfall_daily",
        "hours_with_rainfall BETWEEN 1 AND 26",
    )

    # At a repeated midnight, choose the first UTC instant of the civil date.
    op.execute("""
        CREATE FUNCTION warehouse_local_day_start(day date)
        RETURNS timestamptz LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT min(candidate)
            FROM generate_series(0, 2) AS hours_earlier,
                 LATERAL (SELECT (day::timestamp AT TIME ZONE 'Asia/Ho_Chi_Minh')
                                  - hours_earlier * interval '1 hour' AS candidate) AS offsets
            WHERE (candidate AT TIME ZONE 'Asia/Ho_Chi_Minh')::date = day
        $$
    """)

    # Names and expressions are static and owned by this revision.
    for period, start, end in (
        ("daily", "t.local_date", "t.local_date + 1"),
        ("weekly", "date_trunc('week', t.local_date::timestamp)::date",
         "date_trunc('week', t.local_date::timestamp)::date + 7"),
        ("monthly", "date_trunc('month', t.local_date::timestamp)::date",
         "(date_trunc('month', t.local_date::timestamp) + interval '1 month')::date"),
    ):
        op.execute(f"""
            CREATE VIEW vw_weather_{period} AS
            WITH grouped AS (
                SELECT w.location_id, w.weather_source_id,
                       {start} AS period_start, {end} AS period_end,
                       sum(w.rainfall_mm) AS rainfall_total_mm,
                       count(w.rainfall_mm) AS rainfall_hours,
                       count(*) AS loaded_hours,
                       avg(w.air_temperature_c) AS mean_temperature_c,
                       avg(w.relative_humidity_pct) AS mean_humidity_pct,
                       avg(w.wind_speed_mps) AS mean_wind_speed_mps
                FROM fact_weather_hourly w JOIN dim_time t USING (hour_start_utc)
                GROUP BY w.location_id, w.weather_source_id, {start}, {end}
            )
            SELECT *,
                   (extract(epoch FROM (
                       warehouse_local_day_start(period_end) - warehouse_local_day_start(period_start)
                   )) / 3600)::integer AS expected_hours
            FROM grouped
        """)


def downgrade() -> None:
    for period in ("monthly", "weekly", "daily"):
        op.execute(f"DROP VIEW vw_weather_{period}")
    op.execute("DROP FUNCTION warehouse_local_day_start(date)")
    op.drop_constraint(op.f("ck_fact_rainfall_daily_hour_count"), "fact_rainfall_daily", type_="check")
    op.create_check_constraint(
        op.f("ck_fact_rainfall_daily_hour_count"), "fact_rainfall_daily",
        "hours_with_rainfall BETWEEN 1 AND 24",
    )
    op.drop_table("historical_batches")
    op.drop_table("warehouse_runs")
