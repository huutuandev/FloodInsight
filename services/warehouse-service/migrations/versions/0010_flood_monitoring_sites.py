"""Identify fixed observation sites across flood events."""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE flood_monitoring_sites (
            code text PRIMARY KEY, location text NOT NULL, name text NOT NULL
        );
        ALTER TABLE flood_reports ADD COLUMN site_code text REFERENCES flood_monitoring_sites(code);
        INSERT INTO flood_monitoring_sites VALUES
          ('hc-nttl','hai-chau','Giao lộ Núi Thành – Tiểu La'),
          ('hc-nt-segment','hai-chau','Đường Núi Thành, đoạn Tiểu La – Duy Tân'),
          ('hc-hd365','hai-chau','K365/15 Hoàng Diệu'),
          ('hc-pdl','hai-chau','Phan Đăng Lưu, đoạn Lê Thanh Nghị – Ngô Tất Tố'),
          ('hc-nn','hai-chau','Đường Như Nguyệt gần chân cầu Thuận Phước'),
          ('tk-dbp96','thanh-khe','Kiệt 96 Điện Biên Phủ');
        UPDATE flood_reports AS r SET site_code=m.site
        FROM (VALUES ('hc-20241105-nttl','hc-nttl'), ('hc-20250612-nttl','hc-nttl'),
                     ('hc-20181209-nt','hc-nt-segment'), ('hc-20250612-hd','hc-hd365'),
                     ('hc-20241105-pdl','hc-pdl'), ('hc-20251021-nn','hc-nn'),
                     ('tk-20241105-dbp','tk-dbp96')) AS m(report,site)
        WHERE r.id=m.report;
    """)


def downgrade():
    op.execute("ALTER TABLE flood_reports DROP COLUMN site_code")
    op.drop_table("flood_monitoring_sites")
