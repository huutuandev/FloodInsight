"""Register canonical monitoring points on an empty or populated warehouse."""

from alembic import op


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO dim_location (code, name, latitude, longitude) VALUES
            ('hai-chau', 'Hải Châu', 16.076345, 108.221783),
            ('thanh-khe', 'Thanh Khê', 16.071259, 108.191634),
            ('lien-chieu', 'Liên Chiểu', 16.07272, 108.15815),
            ('cam-le', 'Cẩm Lệ', 16.0153, 108.2013),
            ('ngu-hanh-son', 'Ngũ Hành Sơn', 16.008333, 108.2525)
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade():
    # Sampling identities may be referenced by weather facts and flood evidence.
    pass
