"""Create the raw, dimensional, fact, and analytics tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'data_sources',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=200), nullable=False),
        sa.Column('dataset', sa.String(length=200), nullable=False),
        sa.Column('reference_url', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_data_sources')),
        sa.UniqueConstraint('code', name=op.f('uq_data_sources_code')),
    )
    op.create_table(
        'dim_date',
        sa.Column('local_date', sa.Date(), nullable=False),
        sa.CheckConstraint('isfinite(local_date)', name=op.f('ck_dim_date_finite_date')),
        sa.PrimaryKeyConstraint('local_date', name=op.f('pk_dim_date')),
    )
    op.create_table(
        'dim_location',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=False),
        sa.CheckConstraint('latitude BETWEEN -90 AND 90', name=op.f('ck_dim_location_latitude_range')),
        sa.CheckConstraint('longitude BETWEEN -180 AND 180', name=op.f('ck_dim_location_longitude_range')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dim_location')),
        sa.UniqueConstraint('code', name=op.f('uq_dim_location_code')),
    )
    op.create_table(
        'model_versions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('model_name', sa.String(length=100), nullable=False),
        sa.Column('version', sa.String(length=80), nullable=False),
        sa.Column('artifact_uri', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("kind IN ('clustering', 'prediction', 'classification')", name=op.f('ck_model_versions_kind')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_model_versions')),
        sa.UniqueConstraint('id', 'kind', name=op.f('uq_model_versions_id')),
        sa.UniqueConstraint('kind', 'model_name', 'version', name=op.f('uq_model_versions_kind')),
    )
    op.create_table(
        'dim_time',
        sa.Column('hour_start_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('local_date', sa.Date(), sa.Computed("(hour_start_utc AT TIME ZONE 'Asia/Ho_Chi_Minh')::date", persisted=True), nullable=False),
        sa.Column('local_hour', sa.SmallInteger(), sa.Computed("EXTRACT(HOUR FROM hour_start_utc AT TIME ZONE 'Asia/Ho_Chi_Minh')", persisted=True), nullable=False),
        sa.CheckConstraint("isfinite(hour_start_utc) AND date_trunc('hour', hour_start_utc AT TIME ZONE 'UTC') = hour_start_utc AT TIME ZONE 'UTC'", name=op.f('ck_dim_time_utc_hour_boundary')),
        sa.ForeignKeyConstraint(['local_date'], ['dim_date.local_date'], name=op.f('fk_dim_time_local_date')),
        sa.PrimaryKeyConstraint('hour_start_utc', name=op.f('pk_dim_time')),
    )
    op.create_index('ix_dim_time_local_date_hour', 'dim_time', ['local_date', 'hour_start_utc'], unique=False)
    op.create_table(
        'dim_weather_source',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('data_source_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'], name=op.f('fk_dim_weather_source_data_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dim_weather_source')),
        sa.UniqueConstraint('data_source_id', name=op.f('uq_dim_weather_source_data_source_id')),
    )
    op.create_table(
        'ingestion_runs',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('source_id', sa.BigInteger(), nullable=False),
        sa.Column('run_key', sa.String(length=200), nullable=False),
        sa.Column('status', sa.String(length=16), server_default=sa.text("'running'"), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(status = 'running' AND finished_at IS NULL) OR (status IN ('succeeded', 'failed') AND finished_at IS NOT NULL AND finished_at >= started_at)", name=op.f('ck_ingestion_runs_lifecycle')),
        sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], name=op.f('fk_ingestion_runs_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ingestion_runs')),
        sa.UniqueConstraint('id', 'source_id', name=op.f('uq_ingestion_runs_id')),
        sa.UniqueConstraint('source_id', 'run_key', name=op.f('uq_ingestion_runs_source_id')),
    )
    op.create_table(
        'analysis_results',
        sa.Column('analysis_key', sa.String(length=200), nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('window_start_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('location_id', sa.BigInteger(), nullable=False),
        sa.Column('weather_source_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("jsonb_typeof(result) = 'object'", name=op.f('ck_analysis_results_result_object')),
        sa.CheckConstraint('isfinite(window_start_utc) AND isfinite(window_end_utc) AND window_start_utc < window_end_utc', name=op.f('ck_analysis_results_window_order')),
        sa.ForeignKeyConstraint(['location_id'], ['dim_location.id'], name=op.f('fk_analysis_results_location_id')),
        sa.ForeignKeyConstraint(['weather_source_id'], ['dim_weather_source.id'], name=op.f('fk_analysis_results_weather_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_analysis_results')),
        sa.UniqueConstraint('analysis_key', 'location_id', 'weather_source_id', 'window_start_utc', 'window_end_utc', name=op.f('uq_analysis_results_analysis_key')),
    )
    op.create_index('ix_analysis_results_location_window', 'analysis_results', ['location_id', 'window_start_utc'], unique=False)
    op.create_table(
        'classification_results',
        sa.Column('model_version_id', sa.BigInteger(), nullable=False),
        sa.Column('model_kind', sa.String(length=16), server_default=sa.text("'classification'"), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('confidence', sa.Numeric(precision=7, scale=6), nullable=True),
        sa.Column('target_hour_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('location_id', sa.BigInteger(), nullable=False),
        sa.Column('weather_source_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("model_kind = 'classification'", name=op.f('ck_classification_results_model_kind')),
        sa.CheckConstraint('confidence BETWEEN 0 AND 1', name=op.f('ck_classification_results_confidence')),
        sa.CheckConstraint('isfinite(issued_at)', name=op.f('ck_classification_results_issue_time')),
        sa.ForeignKeyConstraint(['location_id'], ['dim_location.id'], name=op.f('fk_classification_results_location_id')),
        sa.ForeignKeyConstraint(['model_version_id', 'model_kind'], ['model_versions.id', 'model_versions.kind'], name=op.f('fk_classification_results_model_version_id')),
        sa.ForeignKeyConstraint(['target_hour_utc'], ['dim_time.hour_start_utc'], name=op.f('fk_classification_results_target_hour_utc')),
        sa.ForeignKeyConstraint(['weather_source_id'], ['dim_weather_source.id'], name=op.f('fk_classification_results_weather_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_classification_results')),
        sa.UniqueConstraint('model_version_id', 'location_id', 'weather_source_id', 'target_hour_utc', 'issued_at', name=op.f('uq_classification_results_model_version_id')),
    )
    op.create_index('ix_classification_results_location_hour', 'classification_results', ['location_id', 'target_hour_utc'], unique=False)
    op.create_table(
        'clustering_results',
        sa.Column('model_version_id', sa.BigInteger(), nullable=False),
        sa.Column('model_kind', sa.String(length=16), server_default=sa.text("'clustering'"), nullable=False),
        sa.Column('cluster_label', sa.Integer(), nullable=False),
        sa.Column('window_start_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('location_id', sa.BigInteger(), nullable=False),
        sa.Column('weather_source_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("model_kind = 'clustering'", name=op.f('ck_clustering_results_model_kind')),
        sa.CheckConstraint('isfinite(window_start_utc) AND isfinite(window_end_utc) AND window_start_utc < window_end_utc', name=op.f('ck_clustering_results_window_order')),
        sa.ForeignKeyConstraint(['location_id'], ['dim_location.id'], name=op.f('fk_clustering_results_location_id')),
        sa.ForeignKeyConstraint(['model_version_id', 'model_kind'], ['model_versions.id', 'model_versions.kind'], name=op.f('fk_clustering_results_model_version_id')),
        sa.ForeignKeyConstraint(['weather_source_id'], ['dim_weather_source.id'], name=op.f('fk_clustering_results_weather_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_clustering_results')),
        sa.UniqueConstraint('model_version_id', 'location_id', 'weather_source_id', 'window_start_utc', 'window_end_utc', name=op.f('uq_clustering_results_model_version_id')),
    )
    op.create_index('ix_clustering_results_location_window', 'clustering_results', ['location_id', 'window_start_utc'], unique=False)
    op.create_table(
        'fact_rainfall_daily',
        sa.Column('local_date', sa.Date(), nullable=False),
        sa.Column('rainfall_total_mm', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('hours_with_rainfall', sa.SmallInteger(), nullable=False),
        sa.Column('location_id', sa.BigInteger(), nullable=False),
        sa.Column('weather_source_id', sa.BigInteger(), nullable=False),
        sa.CheckConstraint("rainfall_total_mm >= 0 AND rainfall_total_mm <> 'NaN'::numeric", name=op.f('ck_fact_rainfall_daily_rainfall')),
        sa.CheckConstraint('hours_with_rainfall BETWEEN 1 AND 24', name=op.f('ck_fact_rainfall_daily_hour_count')),
        sa.ForeignKeyConstraint(['local_date'], ['dim_date.local_date'], name=op.f('fk_fact_rainfall_daily_local_date')),
        sa.ForeignKeyConstraint(['location_id'], ['dim_location.id'], name=op.f('fk_fact_rainfall_daily_location_id')),
        sa.ForeignKeyConstraint(['weather_source_id'], ['dim_weather_source.id'], name=op.f('fk_fact_rainfall_daily_weather_source_id')),
        sa.PrimaryKeyConstraint('location_id', 'weather_source_id', 'local_date', name=op.f('pk_fact_rainfall_daily')),
    )
    op.create_index('ix_fact_rainfall_daily_date', 'fact_rainfall_daily', ['local_date'], unique=False)
    op.create_table(
        'fact_weather_forecast_hourly',
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('hour_start_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('location_id', sa.BigInteger(), nullable=False),
        sa.Column('weather_source_id', sa.BigInteger(), nullable=False),
        sa.Column('rainfall_mm', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('air_temperature_c', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('relative_humidity_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('wind_speed_mps', sa.Numeric(precision=8, scale=3), nullable=True),
        sa.CheckConstraint("air_temperature_c <> 'NaN'::numeric", name=op.f('ck_fact_weather_forecast_hourly_finite_temperature')),
        sa.CheckConstraint("rainfall_mm >= 0 AND rainfall_mm <> 'NaN'::numeric", name=op.f('ck_fact_weather_forecast_hourly_rainfall')),
        sa.CheckConstraint("wind_speed_mps >= 0 AND wind_speed_mps <> 'NaN'::numeric", name=op.f('ck_fact_weather_forecast_hourly_wind')),
        sa.CheckConstraint('isfinite(issued_at) AND issued_at <= hour_start_utc', name=op.f('ck_fact_weather_forecast_hourly_issue_time')),
        sa.CheckConstraint('num_nonnulls(rainfall_mm, air_temperature_c, relative_humidity_pct, wind_speed_mps) > 0', name=op.f('ck_fact_weather_forecast_hourly_has_measurement')),
        sa.CheckConstraint('relative_humidity_pct BETWEEN 0 AND 100', name=op.f('ck_fact_weather_forecast_hourly_humidity')),
        sa.ForeignKeyConstraint(['hour_start_utc'], ['dim_time.hour_start_utc'], name=op.f('fk_fact_weather_forecast_hourly_hour_start_utc')),
        sa.ForeignKeyConstraint(['location_id'], ['dim_location.id'], name=op.f('fk_fact_weather_forecast_hourly_location_id')),
        sa.ForeignKeyConstraint(['weather_source_id'], ['dim_weather_source.id'], name=op.f('fk_fact_weather_forecast_hourly_weather_source_id')),
        sa.PrimaryKeyConstraint('location_id', 'weather_source_id', 'hour_start_utc', 'issued_at', name=op.f('pk_fact_weather_forecast_hourly')),
    )
    op.create_index('ix_fact_weather_forecast_hourly_hour', 'fact_weather_forecast_hourly', ['hour_start_utc', 'issued_at'], unique=False)
    op.create_table(
        'fact_weather_hourly',
        sa.Column('hour_start_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('location_id', sa.BigInteger(), nullable=False),
        sa.Column('weather_source_id', sa.BigInteger(), nullable=False),
        sa.Column('rainfall_mm', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('air_temperature_c', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('relative_humidity_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('wind_speed_mps', sa.Numeric(precision=8, scale=3), nullable=True),
        sa.CheckConstraint("air_temperature_c <> 'NaN'::numeric", name=op.f('ck_fact_weather_hourly_finite_temperature')),
        sa.CheckConstraint("rainfall_mm >= 0 AND rainfall_mm <> 'NaN'::numeric", name=op.f('ck_fact_weather_hourly_rainfall')),
        sa.CheckConstraint("wind_speed_mps >= 0 AND wind_speed_mps <> 'NaN'::numeric", name=op.f('ck_fact_weather_hourly_wind')),
        sa.CheckConstraint('num_nonnulls(rainfall_mm, air_temperature_c, relative_humidity_pct, wind_speed_mps) > 0', name=op.f('ck_fact_weather_hourly_has_measurement')),
        sa.CheckConstraint('relative_humidity_pct BETWEEN 0 AND 100', name=op.f('ck_fact_weather_hourly_humidity')),
        sa.ForeignKeyConstraint(['hour_start_utc'], ['dim_time.hour_start_utc'], name=op.f('fk_fact_weather_hourly_hour_start_utc')),
        sa.ForeignKeyConstraint(['location_id'], ['dim_location.id'], name=op.f('fk_fact_weather_hourly_location_id')),
        sa.ForeignKeyConstraint(['weather_source_id'], ['dim_weather_source.id'], name=op.f('fk_fact_weather_hourly_weather_source_id')),
        sa.PrimaryKeyConstraint('location_id', 'weather_source_id', 'hour_start_utc', name=op.f('pk_fact_weather_hourly')),
    )
    op.create_index('ix_fact_weather_hourly_hour', 'fact_weather_hourly', ['hour_start_utc'], unique=False)
    op.create_table(
        'prediction_results',
        sa.Column('model_version_id', sa.BigInteger(), nullable=False),
        sa.Column('model_kind', sa.String(length=16), server_default=sa.text("'prediction'"), nullable=False),
        sa.Column('rainfall_mm', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('target_hour_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('location_id', sa.BigInteger(), nullable=False),
        sa.Column('weather_source_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("model_kind = 'prediction'", name=op.f('ck_prediction_results_model_kind')),
        sa.CheckConstraint("rainfall_mm >= 0 AND rainfall_mm <> 'NaN'::numeric", name=op.f('ck_prediction_results_rainfall')),
        sa.CheckConstraint('isfinite(issued_at) AND issued_at <= target_hour_utc', name=op.f('ck_prediction_results_issue_time')),
        sa.ForeignKeyConstraint(['location_id'], ['dim_location.id'], name=op.f('fk_prediction_results_location_id')),
        sa.ForeignKeyConstraint(['model_version_id', 'model_kind'], ['model_versions.id', 'model_versions.kind'], name=op.f('fk_prediction_results_model_version_id')),
        sa.ForeignKeyConstraint(['target_hour_utc'], ['dim_time.hour_start_utc'], name=op.f('fk_prediction_results_target_hour_utc')),
        sa.ForeignKeyConstraint(['weather_source_id'], ['dim_weather_source.id'], name=op.f('fk_prediction_results_weather_source_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_prediction_results')),
        sa.UniqueConstraint('model_version_id', 'location_id', 'weather_source_id', 'target_hour_utc', 'issued_at', name=op.f('uq_prediction_results_model_version_id')),
    )
    op.create_index('ix_prediction_results_location_hour', 'prediction_results', ['location_id', 'target_hour_utc'], unique=False)
    op.create_table(
        'raw_weather_forecasts',
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('source_id', sa.BigInteger(), nullable=False),
        sa.Column('ingestion_run_id', sa.BigInteger(), nullable=False),
        sa.Column('source_location_key', sa.String(length=200), nullable=False),
        sa.Column('valid_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f('ck_raw_weather_forecasts_payload_object')),
        sa.CheckConstraint('isfinite(valid_at) AND isfinite(issued_at) AND issued_at <= valid_at', name=op.f('ck_raw_weather_forecasts_forecast_instants')),
        sa.ForeignKeyConstraint(['ingestion_run_id', 'source_id'], ['ingestion_runs.id', 'ingestion_runs.source_id'], name=op.f('fk_raw_weather_forecasts_ingestion_run_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_raw_weather_forecasts')),
        sa.UniqueConstraint('source_id', 'source_location_key', 'valid_at', 'issued_at', name=op.f('uq_raw_weather_forecasts_source_id')),
    )
    op.create_index('ix_raw_weather_forecasts_run', 'raw_weather_forecasts', ['ingestion_run_id', 'source_id'], unique=False)
    op.create_table(
        'raw_weather_observations',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('source_id', sa.BigInteger(), nullable=False),
        sa.Column('ingestion_run_id', sa.BigInteger(), nullable=False),
        sa.Column('source_location_key', sa.String(length=200), nullable=False),
        sa.Column('valid_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f('ck_raw_weather_observations_payload_object')),
        sa.CheckConstraint('isfinite(valid_at)', name=op.f('ck_raw_weather_observations_valid_instant')),
        sa.ForeignKeyConstraint(['ingestion_run_id', 'source_id'], ['ingestion_runs.id', 'ingestion_runs.source_id'], name=op.f('fk_raw_weather_observations_ingestion_run_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_raw_weather_observations')),
        sa.UniqueConstraint('source_id', 'source_location_key', 'valid_at', name=op.f('uq_raw_weather_observations_source_id')),
    )
    op.create_index('ix_raw_weather_observations_run', 'raw_weather_observations', ['ingestion_run_id', 'source_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_raw_weather_observations_run', table_name='raw_weather_observations')
    op.drop_table('raw_weather_observations')
    op.drop_index('ix_raw_weather_forecasts_run', table_name='raw_weather_forecasts')
    op.drop_table('raw_weather_forecasts')
    op.drop_index('ix_prediction_results_location_hour', table_name='prediction_results')
    op.drop_table('prediction_results')
    op.drop_index('ix_fact_weather_hourly_hour', table_name='fact_weather_hourly')
    op.drop_table('fact_weather_hourly')
    op.drop_index('ix_fact_weather_forecast_hourly_hour', table_name='fact_weather_forecast_hourly')
    op.drop_table('fact_weather_forecast_hourly')
    op.drop_index('ix_fact_rainfall_daily_date', table_name='fact_rainfall_daily')
    op.drop_table('fact_rainfall_daily')
    op.drop_index('ix_clustering_results_location_window', table_name='clustering_results')
    op.drop_table('clustering_results')
    op.drop_index('ix_classification_results_location_hour', table_name='classification_results')
    op.drop_table('classification_results')
    op.drop_index('ix_analysis_results_location_window', table_name='analysis_results')
    op.drop_table('analysis_results')
    op.drop_table('ingestion_runs')
    op.drop_table('dim_weather_source')
    op.drop_index('ix_dim_time_local_date_hour', table_name='dim_time')
    op.drop_table('dim_time')
    op.drop_table('model_versions')
    op.drop_table('dim_location')
    op.drop_table('dim_date')
    op.drop_table('data_sources')
