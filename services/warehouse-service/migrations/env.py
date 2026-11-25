from alembic import context
from sqlalchemy import create_engine, pool

from floodinsight_warehouse.config import DatabaseSettings
from floodinsight_warehouse.repositories.models import Base

url = DatabaseSettings().url()


def include_object(obj, name, type_, reflected, compare_to):
    # Flood tables are owned by explicit SQL migrations, outside the weather ORM.
    return not (type_ == "table" and reflected and compare_to is None and name in {
        "flood_dataset_assets", "flood_events", "flood_observations", "flood_terrain_features",
        "flood_hydrology_observations", "flood_risk_assessments", "flood_probability_results",
        "forecast_snapshot_receipts",
    })


if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
