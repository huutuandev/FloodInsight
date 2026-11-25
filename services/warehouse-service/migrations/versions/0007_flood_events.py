"""Historical flood evidence at Hai Chau."""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE flood_events (
            id text PRIMARY KEY, location text NOT NULL, event_date date NOT NULL,
            title text NOT NULL
        );
        CREATE TABLE flood_reports (
            id text PRIMARY KEY, event_id text NOT NULL REFERENCES flood_events(id),
            place text NOT NULL, precision_level text NOT NULL,
            status text NOT NULL CHECK (status IN ('flooded','confirmed_dry','unknown')),
            depth_cm numeric CHECK (depth_cm >= 0),
            latitude double precision CHECK (latitude BETWEEN -90 AND 90),
            longitude double precision CHECK (longitude BETWEEN -180 AND 180),
            geometry_source text,
            CHECK ((latitude IS NULL) = (longitude IS NULL)),
            CHECK (latitude IS NULL OR geometry_source IS NOT NULL)
        );
        CREATE TABLE flood_report_sources (
            report_id text REFERENCES flood_reports(id), publisher text NOT NULL,
            url text NOT NULL, PRIMARY KEY (report_id, url)
        );
        INSERT INTO flood_events VALUES
          ('hc-20241105','hai-chau','2024-11-05','Mưa ngập sáng 05/11/2024'),
          ('hc-20181209','hai-chau','2018-12-09','Ngập đô thị sáng 09/12/2018');
        INSERT INTO flood_reports VALUES
          ('hc-20241105-nttl','hc-20241105','Giao lộ Núi Thành – Tiểu La','intersection',
           'flooded',NULL,16.0463888,108.2210973,'https://www.openstreetmap.org/node/1334170383'),
          ('hc-20181209-nt','hc-20181209','Đường Núi Thành, đoạn Tiểu La – Duy Tân','street_segment',
           'flooded',NULL,NULL,NULL,NULL);
        INSERT INTO flood_report_sources VALUES
          ('hc-20241105-nttl','Dân trí','https://dansinh.dantri.com.vn/dien-dan-dan-sinh/da-nang-mua-lon-nhieu-tuyen-duong-ngap-sau-hoc-sinh-nghi-hoc-20241105101609887.htm'),
          ('hc-20181209-nt','Người Lao Động','https://tuoitre.vn/nld/thoi-su/duong-pho-da-nang-bien-thanh-song-sau-tran-mua-lon-keo-dai-nhieu-gio-20181209090531484.htm');
    """)


def downgrade():
    op.drop_table("flood_report_sources")
    op.drop_table("flood_reports")
    op.drop_table("flood_events")
