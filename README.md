# FloodInsight Đà Nẵng

FloodInsight là hệ thống thu thập, phân tích và dự báo lượng mưa tại Đà Nẵng. Người dùng có thể chọn điểm lấy mẫu, xem diễn biến thời tiết trên bản đồ, tra dự báo lượng mưa từng ngày và đối chiếu bản đã phát hành với trạm mưa. Hệ thống theo dõi chín điểm ở Đà Nẵng. Hải Châu là điểm triển khai đối chiếu thực đo đầu tiên, dùng trạm Hồ Thạc Gián cách điểm mẫu khoảng 1,9 km.

## Chạy dự án bằng Docker

Cần Docker với Compose v2. Từ thư mục gốc, nếu chưa có `.env`, sao chép `.env.example` thành `.env` rồi điền `POSTGRES_USER` và `POSTGRES_PASSWORD`. Giữ tệp này trên máy phát triển.

~~~sh
docker compose config --quiet
docker compose up -d --build
docker compose ps -a
~~~

Mở [dashboard](http://localhost:3000), [trạng thái API](http://localhost:8000/health) hoặc [Swagger UI](http://localhost:8000/docs). Các cổng dưới đây là giá trị mặc định trên máy local. Có thể đổi bằng biến môi trường trong Compose.

Khi khởi động lần đầu, `warehouse-migrate` tạo hoặc nâng cấp lược đồ rồi kết thúc. Để có dự báo trên kho mới, hãy nhập lịch sử ERA5 và chạy ETL. Trong dashboard, nút **Huấn luyện mô hình 7 ngày** tạo bảy mô hình theo hạn cho điểm đang chọn; sau đó người dùng có thể xem trước và phát hành các ngày đã chọn. Dự báo mới hỗ trợ tối đa bảy ngày tới. Tác vụ `forecast-refresh` tiếp tục bổ sung ERA5 tới ngày mới nhất mà API lịch sử chấp nhận. [Nhập lịch sử và chạy ETL](docs/historical-etl.md) · [Huấn luyện và quản lý mô hình](docs/machine-learning.md)

Trong **Bản đồ Đà Nẵng**, bảng **Theo dõi địa điểm qua các đợt ngập** so sánh các đợt có tư liệu cho khu vực đang chọn. Mỗi hàng dùng mã cố định từ `flood_monitoring_sites`. Khi nhập báo cáo mới cho cùng một địa điểm, dùng lại mã ở `flood_reports.site_code` để nối lịch sử dù cách viết tên đường thay đổi. Giao lộ và cả đoạn đường là hai phạm vi khảo sát riêng. Bảng giữ nguồn, số đo độ sâu và từng ghi nhận của mỗi đợt.

## Sử dụng dashboard

| Mục | Có thể làm gì |
| --- | --- |
| Tổng quan đô thị | Xem thời tiết, lượng mưa gần đây và tình trạng hệ thống. Nút **Xem dự báo mưa 7 ngày** mở dự báo từ ngày mai theo giờ Việt Nam. |
| Dự báo mưa & mô hình | Huấn luyện mô hình 7 hạn, chọn tối đa 7 ngày tới để xem trước/phát hành, hoặc chọn ngày để tra các bản phát hành trước. Mỗi dòng tương ứng một ngày mục tiêu. |
| Phân tích lượng mưa | Xem chuỗi thời gian, thống kê mô tả và tương quan giữa các biến thời tiết trong khoảng đã chọn. |
| Bản đồ Đà Nẵng | Xem vị trí các điểm lấy mẫu, lượng mưa theo ngày và lớp phủ radar. |
| Quản trị kho dữ liệu | Kiểm tra lịch sử nhập dữ liệu, trạng thái ETL, khoảng bao phủ và các mốc bị thiếu. |

## Nguồn và luồng dữ liệu

### Tra cứu sự kiện ngập lịch sử tại Hải Châu

Trong **Bản đồ Đà Nẵng**, chọn điểm **Hải Châu** rồi chọn **Đợt ngập lịch sử**. Bản đồ và biểu đồ mưa chuyển sang ngày của sự kiện. Chọn đợt 05/11/2024 để xem giao lộ Núi Thành – Tiểu La, bài ghi nhận hiện trường và nguồn tọa độ OpenStreetMap. Đợt 09/12/2018 có mô tả đoạn đường Núi Thành từ Tiểu La đến Duy Tân; giao diện giữ phạm vi mô tả theo nguồn. Lượng mưa ERA5 hiển thị theo điểm lấy mẫu. Độ sâu ngập có trường riêng và để trống khi nguồn chưa cung cấp số đo.

Tra cứu qua `GET /api/v1/flood-reports?location=hai-chau` hoặc các bảng `flood_events` (đợt), `flood_reports` (địa điểm, trạng thái, độ sâu, vị trí) và `flood_report_sources` (nguồn của từng ghi nhận). Một đợt có thể liên kết nhiều địa điểm và một địa điểm trong đợt có thể có nhiều nguồn. Những nơi chưa có báo cáo vẫn chưa rõ tình trạng ngập.

Đoạn Núi Thành năm 2018 được vẽ theo tim đường OpenStreetMap. Đợt 05/11/2024 có một điểm đối chứng ở kiệt 96 Điện Biên Phủ, xem bằng bộ lọc Thanh Khê. Đợt đêm 11–12/06/2025 có số liệu độ sâu do báo chí dẫn từ hệ thống giám sát đô thị. Cao độ GLO-90 là giá trị ô lưới 90 m tại giao lộ. Các quan sát sông Hàn trong `river_observations` có địa điểm, ngày, thời điểm và mốc cao độ riêng. Khi xem ngày 21/10/2025, bảng hiển thị quan sát tại Bạch Đằng cùng ngày với sự kiện Như Nguyệt.

Chạy thử nghiệm không gian và nguy cơ ngập bằng `docker compose exec -T prediction-service python -m floodinsight_prediction.services.flood_experiment`. Phân cụm so sánh hồ sơ ngập/khô của các địa điểm trong cùng tập trận đã khảo sát. Thử nghiệm hồi quy logistic dùng lượng mưa dự báo phát hành từ ngày trước và cao độ ô lưới; quy tắc đối chứng dùng ngưỡng 25 mm. Huấn luyện chỉ dùng các ngày trước ngày kiểm tra. Kết quả in số bản ghi đủ đặc trưng, số đợt kiểm tra, số lần bỏ sót và báo động nhầm khi tính được. Hiện các sự kiện lịch sử có trước kho bản phát hành của mô hình.

| Dữ liệu | Nguồn | Vai trò |
| --- | --- | --- |
| Lịch sử thời tiết | ERA5 qua Open-Meteo Historical Weather API | Dữ liệu tái phân tích theo ô lưới. Kho tổng hợp theo ngày địa phương để tạo đặc trưng huấn luyện và đầu vào dự báo. |
| Thời tiết hiện tại | Open-Meteo | Lưu ảnh chụp kết quả thời tiết mô hình tại điểm lấy mẫu, kèm thời điểm nhận. |
| Dự báo của nhà cung cấp | ECMWF IFS và NOAA GFS qua Open-Meteo | Lưu các lần thu nhận dự báo theo giờ để tham khảo. Mô hình bảy ngày của FloodInsight tự tính kết quả từ lịch sử ERA5. |
| Lượng mưa tại trạm | Cổng mưa ngập Đà Nẵng, trạm Hồ Thạc Gián, mã 430018 | Chuỗi mưa 10 phút dùng để đối chiếu tại Hải Châu. Tổng ngày đi kèm số kỳ hợp lệ và thời điểm quan trắc cuối. |

Các thời điểm được quy đổi sang múi giờ `Asia/Ho_Chi_Minh` (UTC+7) khi xác định ngày mục tiêu và ngày quan trắc. Ngày mới nhất trong kho, ngày cuối mô hình dùng và ngày dự báo có thể khác nhau. [Nguồn lịch sử Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) · [API gốc của trạm Hồ Thạc Gián](https://muangap-api.danang.gov.vn/v1/stations/afb37e83-2759-11ec-8ef9-06552145a11a)

## Dự báo và kiểm chứng

1. **Huấn luyện.** Một phiên bản dự báo bảy ngày gồm bảy mô hình hồi quy XGBoost, mỗi mô hình phụ trách một hạn từ 1 đến 7 ngày. Hệ thống chia dữ liệu theo thời gian và so sánh sai số với phương án dùng lượng mưa của ngày đầu vào gần nhất.
2. **Tạo dự báo.** Mỗi lần chạy dùng bảy ngày ERA5 hoàn chỉnh. Với ngày phát hành D, cửa sổ đầu vào hiện tại là D−13 đến D−7 và các ngày mục tiêu là D+1 đến D+7. Dịch vụ kiểm tra thời điểm dữ liệu thực sự được nhận và báo thiếu đầu vào nếu chưa đủ điều kiện.
3. **Phát hành.** Tác vụ `forecast-refresh` định kỳ nhập số đo trạm, thử cập nhật đầu vào ERA5 và phát hành dự báo Hải Châu. Bản phát hành lưu phiên bản mô hình, giờ phát hành, điểm và lượng mưa từng ngày. Dashboard cũng phân biệt bản xem trước và bản đã phát hành.
4. **Đọc mức mưa.** UI xếp mức theo tổng mưa dự đoán trong ngày: dưới 0,1 mm là không mưa, từ 0,1 đến dưới 10 mm là mưa nhẹ, từ 10 đến dưới 25 mm là mưa vừa và từ 25 mm là mưa to. Đây là ngưỡng quy ước của dự án. Kết quả từ bộ phân loại ngày kế tiếp, nếu có, hiển thị riêng kèm thời điểm tính.
5. **Đối chiếu.** Bảng độ chính xác dùng 90 ngày địa phương đã kết thúc, chọn bản phát hành mới nhất cho mỗi cặp ngày mục tiêu và hạn dự báo. Chỉ ngày có đủ 144 kỳ đo 10 phút tại trạm mới được tính. Bảng hiển thị số ngày có dự báo, số ngày đủ đối chiếu, MAE, sai lệch trung bình và số lần bỏ sót hoặc báo động nhầm mưa to. Sai lệch dương nghĩa là dự báo cao hơn thực đo. Dấu gạch ngang biểu thị chưa có mẫu để tính.

MAE trên tập kiểm thử ERA5 và MAE đối chiếu trạm dùng hai nguồn tham chiếu khác nhau. Khi đánh giá kết quả tại Hải Châu, hãy đọc cả số ngày đủ đối chiếu. Ví dụ, từ 18 đến 24/11/2026, API Hồ Thạc Gián chỉ trả 143 mốc mỗi ngày, thiếu mốc 00:00 kết thúc kỳ 23:50–00:00. Hệ thống giữ tổng từng phần và bỏ các ngày đó khỏi phép tính sai số.

## Kiến trúc và dịch vụ

Dashboard Next.js gọi các route cùng origin dưới `/api/backend/`. API gateway chuyển yêu cầu đến dịch vụ FastAPI tương ứng. PostgreSQL 16 lưu dữ liệu, lịch sử chạy và kết quả mô hình. Các dịch vụ ML lưu artifact Joblib trên volume riêng và liên kết với phiên bản trong cơ sở dữ liệu.

| Dịch vụ Compose | Cổng local | Trách nhiệm |
| --- | ---: | --- |
| frontend | 3000 | Dashboard Next.js, biểu đồ ECharts và bản đồ React Leaflet. |
| api-service | 8000 | REST gateway, kiểm tra phụ thuộc và chuẩn hóa phản hồi. |
| ingestion-service | 8001 | Nhận thời tiết mô hình, ghi nhật ký các lần nhập theo lịch hoặc thủ công. |
| warehouse-service | 8002 | Backfill ERA5, ETL, tổng hợp dữ liệu và kiểm tra chất lượng. |
| analysis-service | 8003 | Phân tích chuỗi thời gian và tạo các thống kê. |
| clustering-service | 8004 | Phân cụm K-Means, biểu diễn PCA và chỉ số silhouette. |
| prediction-service | 8005 | Huấn luyện, suy luận, phát hành và kiểm chứng dự báo lượng mưa. |
| classification-service | 8006 | Phân loại cường độ mưa ngày kế tiếp và đánh giá kết quả. |
| postgres | 5432 | Kho dữ liệu và kết quả dự báo. |
| warehouse-migrate, forecast-refresh | — | Nâng cấp lược đồ và chạy các tác vụ cập nhật định kỳ. |

Mã các dịch vụ nằm trong `services/`, phần ML dùng chung trong `services/ml-common/`, UI trong `frontend/app/`, tác vụ nhập trong `scripts/` và cấu hình chạy trong `docker-compose.yml`.

## Kiểm tra thủ công tại Hải Châu

**Qua API** — sau khi khởi động Docker với cổng mặc định, có thể mở trực tiếp [dự báo bảy ngày](http://localhost:8000/api/v1/predictions/outlook?location=hai-chau), [lịch sử bản phát hành trước một ngày](http://localhost:8000/api/v1/predictions/outlook/history?location=hai-chau&lead_days=1) và [kết quả kiểm chứng bảy hạn](http://localhost:8000/api/v1/predictions/outlook/verification?location=hai-chau). Khi tra lịch sử, truyền thêm `start_date` và `end_date` theo dạng `YYYY-MM-DD` để lọc ngày mục tiêu.

**Qua PostgreSQL** — từ thư mục dự án, mở phiên SQL bằng lệnh sau trong PowerShell hoặc shell có hỗ trợ dấu nháy đơn.

~~~sh
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
~~~

~~~sql
SELECT local_date, rainfall_mm, intervals, observed_through
FROM gauge_daily_observations
WHERE station_code = '430018'
ORDER BY local_date DESC
LIMIT 14;
~~~

| Muốn kiểm tra | Bảng trong kho |
| --- | --- |
| Lượng mưa trạm, số kỳ đã nhận | `gauge_daily_observations` |
| Giá trị thời tiết từng giờ và lượng mưa lịch sử đã tổng hợp | `fact_weather_hourly`, `fact_rainfall_daily` |
| Dự báo theo giờ do nhà cung cấp phát hành hoặc cung cấp | `raw_weather_forecasts`, `fact_weather_forecast_hourly` |
| Lượng mưa do FloodInsight dự báo, thời điểm và phiên bản | `prediction_results`, `model_versions`; dùng `dim_location`, `dim_time` để xác định điểm và ngày mục tiêu |
| Lịch sử tác vụ nhập | `ingestion_runs` |

## Phát triển và vận hành

Compose gắn mã ứng dụng vào container để FastAPI và Next.js nhận thay đổi khi phát triển. Khi thay dependency hoặc Dockerfile, build lại dịch vụ tương ứng. Có thể xem log và kiểm tra phiên bản migration bằng các lệnh sau.

~~~sh
docker compose logs --tail 100 forecast-refresh prediction-service
docker compose exec warehouse-service alembic current
docker compose down
~~~

Lệnh `down` giữ lại các named volume. Khi sao lưu hoặc chuyển máy, giữ cơ sở dữ liệu cùng các volume mô hình để bản ghi phiên bản vẫn khớp với artifact.

**Frontend** dùng Node.js 22 trở lên. Chạy trong `frontend/`:

~~~sh
npm ci
npm run typecheck
npm run build
~~~

**Backend** dùng Python 3.11. Trong môi trường ảo của dịch vụ cần kiểm tra, cài dependency phát triển và chạy bộ kiểm thử tương ứng:

~~~sh
python -m pip install -r requirements-dev.txt
python -m pytest
~~~

Tài liệu chuyên sâu: [Lược đồ kho và ERD](docs/warehouse-schema.md) · [Thu nhận dữ liệu](docs/ingestion.md) · [ETL lịch sử](docs/historical-etl.md) · [Phân tích chuỗi thời gian](docs/time-series-analysis.md) · [Mô hình ML](docs/machine-learning.md) · [API gateway](docs/api-gateway.md) · [Dashboard](docs/dashboard.md) · [Khôi phục dashboard](docs/dashboard-recovery.md).
