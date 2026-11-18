"""Persist model evaluation, cluster coordinates, and class probabilities."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    for table, column in (
        ("model_versions", "training_metadata"),
        ("clustering_results", "details"),
        ("classification_results", "probabilities"),
    ):
        op.add_column(table, sa.Column(column, JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
        op.create_check_constraint(
            op.f(f"ck_{table}_{column}_object"), table, f"jsonb_typeof({column}) = 'object'"
        )


def downgrade():
    for table, column in (
        ("classification_results", "probabilities"),
        ("clustering_results", "details"),
        ("model_versions", "training_metadata"),
    ):
        op.drop_column(table, column)

