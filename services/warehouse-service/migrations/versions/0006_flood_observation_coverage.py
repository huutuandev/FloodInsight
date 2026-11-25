"""Allow reviewed dry observations to declare a bounded coverage interval."""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("flood_observations", sa.Column("coverage_start", sa.DateTime(timezone=True)))
    op.add_column("flood_observations", sa.Column("coverage_end", sa.DateTime(timezone=True)))
    op.add_column("flood_observations", sa.Column("coverage_radius_m", sa.Float()))
    op.create_check_constraint(
        "ck_flood_observations_coverage_interval", "flood_observations",
        """(coverage_start IS NULL AND coverage_end IS NULL AND coverage_radius_m IS NULL) OR
           (coverage_start IS NOT NULL AND coverage_end IS NOT NULL AND coverage_radius_m IS NOT NULL
            AND isfinite(coverage_start) AND isfinite(coverage_end)
            AND coverage_radius_m > 0 AND coverage_radius_m < 'Infinity'
            AND coverage_start < coverage_end AND label = 'non_flood_confirmed'
            AND observed_at >= coverage_end)""",
    )


def downgrade():
    op.drop_constraint("ck_flood_observations_coverage_interval", "flood_observations", type_="check")
    op.drop_column("flood_observations", "coverage_radius_m")
    op.drop_column("flood_observations", "coverage_end")
    op.drop_column("flood_observations", "coverage_start")
