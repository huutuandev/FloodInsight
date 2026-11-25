"""Extend flood evidence with site-specific observations and mapped road segments."""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE flood_reports ADD COLUMN site_location text,
            ADD COLUMN road_geometry jsonb, ADD COLUMN context_note text,
            ADD COLUMN elevation_m numeric, ADD COLUMN elevation_source text;
        UPDATE flood_reports SET road_geometry =
            '{"type":"LineString","coordinates":[[108.2210973,16.0463888],[108.2210695,16.0465376],[108.2210302,16.0468135],[108.2209741,16.0472838],[108.2209276,16.0477029],[108.2208734,16.0480673],[108.2208543,16.048213],[108.2208253,16.0484348],[108.2208037,16.0486234],[108.2207517,16.0490867],[108.2207377,16.04922]]}',
            geometry_source='https://www.openstreetmap.org/node/8918601301'
            WHERE id='hc-20181209-nt';
        INSERT INTO flood_events VALUES
          ('hc-20250612','hai-chau','2025-06-12','Ngập đêm 11 đến rạng sáng 12/06/2025'),
          ('hc-20251021','hai-chau','2025-10-21','Nước dâng ven sông Hàn ngày 21/10/2025');
        INSERT INTO flood_reports (id,event_id,place,precision_level,status,depth_cm,latitude,longitude,
                                   geometry_source,site_location,context_note) VALUES
          ('hc-20250612-nttl','hc-20250612','Giao lộ Núi Thành – Tiểu La','intersection','flooded',25,
           16.0463888,108.2210973,'https://www.openstreetmap.org/node/1334170383','hai-chau',
           'Số liệu tháp báo ngập được báo chí dẫn lại trong khoảng 23h–0h.'),
          ('hc-20250612-hd','hc-20250612','K365/15 Hoàng Diệu','address','flooded',35,NULL,NULL,NULL,
           'hai-chau','Cập nhật lúc 00:00 ngày 12/06 (ICT).'),
          ('hc-20241105-pdl','hc-20241105','Phan Đăng Lưu, đoạn Lê Thanh Nghị – Ngô Tất Tố',
           'street_segment','flooded',NULL,NULL,NULL,NULL,'hai-chau','Người dân ghi nhận nước rút nhanh hơn các năm trước.'),
          ('tk-20241105-dbp','hc-20241105','Kiệt 96 Điện Biên Phủ','street_segment','confirmed_dry',
           NULL,NULL,NULL,NULL,'thanh-khe','Người dân xác nhận kiệt không ngập trong trận mưa ngày 05/11.'),
          ('hc-20251021-nn','hc-20251021','Đường Như Nguyệt gần chân cầu Thuận Phước','street_segment',
           'flooded',NULL,NULL,NULL,NULL,'hai-chau','Trưa 21/10, nước dâng và sóng tràn bờ gây ngập cục bộ.');
        UPDATE flood_reports SET elevation_m=5,
          elevation_source='https://api.open-meteo.com/v1/elevation?latitude=16.0463888&longitude=108.2210973'
          WHERE id IN ('hc-20241105-nttl','hc-20250612-nttl');
        INSERT INTO flood_report_sources (report_id,publisher,url)
          SELECT id,'Người Đưa Tin','https://www.nguoiduatin.vn/mua-lon-do-bao-so-1-nhieu-tuyen-pho-da-nang-ngap-cuc-bo-trong-dem-20425061121574087.htm'
          FROM flood_reports WHERE event_id='hc-20250612';
        INSERT INTO flood_report_sources (report_id,publisher,url)
          SELECT id,'Báo Đà Nẵng','https://baodanang.vn/nguoi-dan-gui-thu-cam-on-vi-giam-ngap-nuoc-thoat-nhanh-3161146.html'
          FROM flood_reports WHERE id IN ('hc-20241105-pdl','tk-20241105-dbp');
        INSERT INTO flood_report_sources VALUES
          ('hc-20251021-nn','Báo Đà Nẵng','https://baodanang.vn/mua-lon-gay-ngap-mot-so-doan-duong-o-da-nang-3306918.html');
    """)


def downgrade():
    op.execute("""
        DELETE FROM flood_report_sources WHERE report_id IN ('hc-20250612-nttl','hc-20250612-hd',
            'hc-20241105-pdl','tk-20241105-dbp','hc-20251021-nn');
        DELETE FROM flood_reports WHERE id IN ('hc-20250612-nttl','hc-20250612-hd',
            'hc-20241105-pdl','tk-20241105-dbp','hc-20251021-nn');
        DELETE FROM flood_events WHERE id IN ('hc-20250612','hc-20251021');
        UPDATE flood_reports SET geometry_source=NULL WHERE id='hc-20181209-nt';
        ALTER TABLE flood_reports DROP COLUMN site_location, DROP COLUMN road_geometry,
            DROP COLUMN context_note, DROP COLUMN elevation_m, DROP COLUMN elevation_source;
    """)
