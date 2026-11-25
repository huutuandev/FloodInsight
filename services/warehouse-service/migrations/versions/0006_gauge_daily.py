"""Persist daily station observations used for forecast verification."""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE gauge_daily_observations (
            station_code text NOT NULL,
            local_date date NOT NULL,
            rainfall_mm numeric NOT NULL CHECK (rainfall_mm >= 0),
            intervals integer NOT NULL CHECK (intervals BETWEEN 1 AND 144),
            observed_through timestamptz NOT NULL,
            PRIMARY KEY (station_code, local_date)
        )
    """)


def downgrade():
    op.drop_table("gauge_daily_observations")
