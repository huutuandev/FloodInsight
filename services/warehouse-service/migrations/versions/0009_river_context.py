"""Record a same-day river observation with its local reference."""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE river_observations (
            station_or_site text NOT NULL, observed_date date NOT NULL,
            time_description text NOT NULL, level_m numeric NOT NULL,
            reference_level text NOT NULL, source_url text NOT NULL,
            PRIMARY KEY (station_or_site, observed_date, time_description, source_url)
        );
        INSERT INTO river_observations VALUES
          ('Sông Hàn, đường Bạch Đằng','2025-10-21','Đêm',-0.5,
           'mép vỉa hè đường Bạch Đằng',
           'https://dantri.com.vn/thoi-su/song-han-no-nuoc-song-bien-doi-manh-truoc-gio-bao-fengshen-ap-sat-20251022111625036.htm');
        INSERT INTO river_observations VALUES
          ('Sông Hàn, trạm Cẩm Lệ','2025-10-29','13:00 ICT',2.73,
           'mốc trạm theo bản tin thủy văn',
           'https://pctt.danang.gov.vn/Portals/0/DNAN_LULU_20251029_1530_signed_1.pdf');
    """)


def downgrade():
    op.drop_table("river_observations")
