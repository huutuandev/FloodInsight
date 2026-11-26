# FloodInsight Đà Nẵng

FloodInsight là hệ thống nghiên cứu ngập đô thị tại các điểm quan trắc ở Đà Nẵng. Dự án thu nhận dữ liệu thời tiết và dữ liệu phục vụ nghiên cứu ngập, lưu vào PostgreSQL, rồi cung cấp đánh giá nguy cơ, dự báo xác suất khi đủ điều kiện kiểm định và công cụ đối chiếu trên bản đồ. Phân tích lượng mưa và các mô hình mưa ngày kế tiếp cung cấp thêm bối cảnh trước một đợt mưa.

## Chạy dự án

Cần Docker với Compose v2. Từ thư mục gốc, nếu chưa có `.env`, sao chép `.env.example` thành `.env` và điền `POSTGRES_USER`, `POSTGRES_PASSWORD`. Dùng lệnh sau trong PowerShell.

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# Cập nhật thông tin PostgreSQL trong .env trước khi chạy.
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps -a
```

Mở [dashboard](http://localhost:3000), [trạng thái API](http://localhost:8000/health) hoặc [Swagger UI](http://localhost:8000/docs). Có thể đổi cổng bằng `FRONTEND_PORT` và `API_PORT` trong `.env`. Tác vụ `warehouse-migrate` chạy migration sau khi PostgreSQL sẵn sàng. Các bảng dữ liệu được giữ trong volume `postgres-data` khi chạy `docker compose down`.

Sau khi dịch vụ sẵn sàng, từ thư mục gốc chạy lệnh dưới đây để thu nhận dữ liệu, nạp lịch sử và tạo đánh giá nguy cơ trên cùng stack. Script dùng các mốc lưu trong kho để tiếp tục các bước đã có dữ liệu. Khoảng nạp lịch sử có thể đặt bằng `--start` và `--end`.

```powershell
python scripts/bootstrap_floodinsight.py
docker compose logs --tail 100 api-service warehouse-service prediction-service
docker compose exec warehouse-service alembic current
```

Với Docker Desktop trên Windows, có thể truyền `--docker-host npipe:////./pipe/dockerDesktopLinuxEngine` nếu engine nằm ngoài ngữ cảnh Docker mặc định. Khi chạy stack riêng, đặt cả `--api` và `--project` để script trỏ đúng stack. [Hướng dẫn khôi phục](docs/dashboard-recovery.md) · [Báo cáo chạy thực tế](FLOODINSIGHT_RUNTIME_VERIFICATION.md)

## Các mục trên dashboard

| Mục | Nội dung |
| --- | --- |
| Tổng quan ngập lụt | Nguy cơ hiện tại tại các điểm, số lượng dự báo đã kiểm định còn hiệu lực, mưa lịch sử và dữ liệu thời tiết mô hình. |
| Dự báo nguy cơ ngập | So sánh địa điểm, chọn một dòng để xem mưa và mức nguy cơ theo hạn 6/12/24 giờ, đầu vào, điểm đóng góp, thời điểm hiệu lực và khuyến nghị. Nút **Tạo đánh giá** tạo các bản đánh giá từ dữ liệu hiện có. |
| Bản đồ ngập Đà Nẵng | Chọn hạn, bấm ghim hoặc chọn địa điểm trong danh sách để phóng đến vị trí. Có thể mở rộng bản đồ, hiện điểm lịch sử và bật vòng tham chiếu. |
| Phân tích lượng mưa | Xem diễn biến theo ngày, tuần hoặc tháng và các thống kê liên quan. |
| Học máy | Xem mức sẵn sàng, kết quả kiểm định ngập, phân cụm địa hình và phần đánh giá mô hình mưa. Tooltip giải thích Precision, Recall, F1, PR-AUC, ROC-AUC và Brier Score. |
| Quản lý dữ liệu | Kiểm tra độ phủ thời tiết, sự kiện ngập, địa hình, thủy văn, lịch sử đánh giá và các lượt thu nhận hoặc ETL. |

Dashboard mặc định dùng tiếng Việt. Chọn **VI/EN** trên topbar để đổi ngôn ngữ. Trình duyệt lưu lựa chọn trong `localStorage`. Ở các mục có bộ lọc lịch sử, mặc định dùng khoảng bao phủ của điểm đã chọn. Có các lựa chọn **30 ngày**, **90 ngày**, **1 năm**, **Toàn bộ** và ô nhập ngày. Dữ liệu ngày và giờ trên dashboard dùng giờ Việt Nam (ICT, UTC+7).

## Đọc bản đồ ngập

Chọn **Bản đồ ngập Đà Nẵng**, sau đó chọn **Tổng hợp 24h**, **6 giờ tới**, **12 giờ tới** hoặc **24 giờ tới**. Bấm ghim để xem báo cáo của điểm. Nút **Xem toàn bộ địa điểm** đưa bản đồ về góc nhìn tổng thể.

| Lớp | Cách đọc |
| --- | --- |
| Ghim điểm quan trắc | Màu thể hiện mức đánh giá còn hiệu lực ở phạm vi điểm. **Tổng hợp 24h** lấy mức tổng hợp của bản đánh giá. Các hạn cụ thể lấy mức tương ứng trong `horizon_breakdown` nếu có. Điểm thiếu mức cho hạn đã chọn hiển thị **Thiếu dữ liệu**, dù API vẫn có thể cung cấp lượng mưa. |
| Vòng ảnh hưởng tham chiếu | Mặc định tắt. Khi bật, vòng nét đứt có bán kính minh họa **500 / 900 / 1.400 / 1.800 m** tương ứng **Thấp / Trung bình / Cao / Rất cao**. Đánh giá hết hiệu lực hoặc thiếu mức rủi ro không có vòng. Bán kính dùng để đọc bản đồ, không biểu thị quãng đường nước lan. |
| Ghim tuyến và điểm lịch sử | Popup hiển thị vị trí tham chiếu, ghi nhận lịch sử, liên kết nguồn, lượng mưa dùng để sàng lọc và ngưỡng mưa cấu hình. Chọn một mục trong danh sách bên dưới để phóng đến ghim. Những tọa độ này đại diện cho vị trí hoặc khu vực được mô tả, chưa xác định hai đầu của phần đường ngập. |

Màu ở ghim tuyến biểu thị **sàng lọc theo mưa**. Mã hiện tại chia lượng mưa đầu vào cho ngưỡng mưa cấu hình. Mức xanh dưới 50%, cam từ 50% đến 85%, đỏ trên 85%, xám khi thiếu đầu vào. Ở chế độ tổng hợp, lượng mưa sàng lọc là giá trị lớn hơn giữa mưa 24 giờ qua và mưa dự báo 24 giờ, hoặc giá trị duy nhất có sẵn. Ở hạn 6 và 12 giờ, giao diện dùng hệ số ngưỡng lần lượt 0,5 và 0,7 so với cấu hình 24 giờ. Đây là quy tắc sàng lọc đang dùng trong ứng dụng. Màu xanh chỉ biểu thị dưới ngưỡng sàng lọc. Các ngưỡng cấu hình cần kiểm chứng tại từng tuyến trước khi dùng để ra quyết định giao thông.

**Phạm vi và độ sâu ngập theo đoạn đường vẫn chưa có trong kết quả hiện tại.** Bản đồ hiển thị ghim sàng lọc, tránh nối các tọa độ tham chiếu thành vệt nước liên tục. Để tô riêng từng đoạn từ ngập sâu đến ngập nông, API cần hình học đoạn đường hoặc vùng ngập, độ sâu và hạn hiệu lực tương ứng. Có thể tạo lớp đó bằng cách giao cắt mạng đường với bản đồ độ sâu đã kiểm định. Mô phỏng thủy lực cần cao độ mặt đường có mốc chuẩn, thông tin lưu vực, cống và cửa xả, mực nước sông hoặc triều, cùng quan trắc ngập thực địa để hiệu chỉnh.

## Đọc kết quả dự báo và độ phủ

| Kết quả | Diễn giải |
| --- | --- |
| Mưa dự báo | Tổng mưa tích lũy theo hạn tại điểm hoặc ô lưới nguồn, đơn vị mm. Có thể khác lượng mưa đo tại trạm hay trên một tuyến cụ thể. |
| Chỉ số nguy cơ | Điểm nghiên cứu từ 0 đến 100. Các yếu tố khả dụng gồm mưa dự báo, mưa gần đây, cường độ mưa, địa hình và độ ẩm đất. Khi thiếu đầu vào bắt buộc, hệ thống có thể để trống điểm. |
| Xác suất ngập | Đầu ra của mô hình có giám sát cho cửa sổ 24 giờ. Chỉ hiển thị khi mô hình đáp ứng điều kiện kiểm định, phát hành và đủ đầu vào. |
| Lịch sử ngập | Bằng chứng vị trí từng được báo cáo ngập. Khi đối chiếu, xem ngày, địa điểm và nguồn gốc của báo cáo. Khoảng thời gian chưa quan sát thuộc nhóm chưa xác định. |

Trong chi tiết đánh giá, mở **Nguồn, thời gian hiệu lực và giới hạn độ phủ** để xem loại nguồn, thời điểm dữ liệu có sẵn, thời điểm hiệu lực, độ phân giải và các yếu tố bị loại. Khi đọc chỉ số, kiểm tra cả giờ phát hành và phần đầu vào còn thiếu. [Phương pháp tính chỉ số](FLOOD_RISK_INDEX.md) · [Đặc trưng đầu vào](FLOOD_FEATURES.md) · [Kiểm định mô hình ngập](FLOOD_MODEL_EVALUATION.md)

## Dữ liệu và kiến trúc

Open-Meteo cung cấp các bản ghi thời tiết mô hình. ERA5 cung cấp lịch sử tái phân tích để nạp vào kho và tổng hợp theo ngày. Dự báo theo giờ được lưu cùng thời điểm hiệu lực và thời điểm hệ thống nhận, giữ giờ phát hành riêng khi nguồn cung cấp. Dữ liệu thực đo, địa hình, thủy văn và báo cáo ngập có nguồn và độ phủ riêng. [Danh mục nguồn](FLOOD_DATA_SOURCES.md) · [Thu nhận Open-Meteo](docs/ingestion.md) · [ETL lịch sử](docs/historical-etl.md)

```text
Nguồn thời tiết, địa hình, thủy văn và hồ sơ ngập
  → Thu nhận / nạp lịch sử / ETL
  → PostgreSQL
  → Dịch vụ phân tích, dự báo và đánh giá nguy cơ
  → API Gateway
  → Dashboard Next.js
```

| Thành phần | Cổng local mặc định | Trách nhiệm |
| --- | ---: | --- |
| `frontend` | 3000 | Next.js App Router, React Leaflet, ECharts và giao diện VI/EN. |
| `api-service` | 8000 | API Gateway và kiểm tra tình trạng dịch vụ. |
| `ingestion-service` | 8001 | Thu nhận và kiểm tra dữ liệu thời tiết. |
| `warehouse-service` | 8002 | Nạp lịch sử, chạy ETL, lưu và báo cáo độ phủ dữ liệu. |
| `analysis-service` | 8003 | Phân tích chuỗi thời gian và thống kê thời tiết. |
| `clustering-service` | 8004 | Phân cụm thời tiết và hồ sơ địa hình. |
| `prediction-service` | 8005 | Đánh giá nguy cơ, dự báo xác suất ngập và mô hình lượng mưa. |
| `classification-service` | 8006 | Phân loại cường độ mưa ngày kế tiếp. |
| `postgres` | 5432 | Kho PostgreSQL 16 với volume lưu trữ. |

Mã giao diện nằm trong `frontend/app/`. Thành phần bản đồ chính là `dashboard/station-map.tsx`, luồng đánh giá theo hạn nằm trong `dashboard/flood-panels.tsx`, cấu hình điểm tham chiếu và quy tắc sàng lọc nằm trong `dashboard/flood-data.ts`. Mã dịch vụ trong `services/`, logic ML dùng chung trong `services/ml-common/` và tác vụ chạy lại dữ liệu trong `scripts/`. [Lược đồ kho](docs/warehouse-schema.md) · [Hướng dẫn dashboard](docs/dashboard.md) · [Hướng dẫn API Gateway](docs/api-gateway.md)

## API để kiểm tra thủ công

Các đường dẫn sau dùng API Gateway trên cổng mặc định `8000`. Dashboard gọi các route tương ứng qua `/api/backend/`.

| Endpoint | Nội dung |
| --- | --- |
| `GET /api/v1/flood-risk/locations` | Danh mục điểm quan trắc ngập. |
| `GET /api/v1/flood-risk/latest` | Bản đánh giá mới nhất và trạng thái còn hiệu lực theo điểm. |
| `GET /api/v1/flood-risk/hai-chau/details` | Chi tiết bản đánh giá cho mã điểm Hải Châu. |
| `GET /api/v1/flood-risk/history` | Lịch sử các bản đánh giá đã lưu. |
| `GET /api/v1/flood-predictions/readiness` | Điều kiện dữ liệu để chạy mô hình ngập. |
| `GET /api/v1/flood-predictions/results?current=true` | Các dự báo mô hình còn hiệu lực. |
| `GET /api/v1/flood-data/coverage` | Độ phủ nhãn, sự kiện, địa hình, thủy văn và thời tiết. |
| `GET /api/v1/rainfall/coverage` | Khoảng ngày có số liệu mưa theo nguồn và điểm. |

## Phát triển và kiểm thử

Frontend dùng Node.js 22 trở lên. Trong `frontend/`, chạy:

```sh
npm ci
npm run lint
npx tsc --noEmit
npm run build
```

Dùng `npm run dev` để phát triển giao diện với API local. Docker mặc định dùng bản build tối ưu. Đặt `FLOODINSIGHT_FRONTEND_TARGET=development` trước khi dựng lại frontend để bật Fast Refresh. Với backend, dùng môi trường ảo Python 3.11 và chạy các lệnh sau trong thư mục dịch vụ cần kiểm tra:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

Các báo cáo về độ phủ và kết quả chạy đã công bố được lưu riêng theo thời điểm kiểm tra. Đọc báo cáo dữ liệu hiện tại từ API trước khi dùng số liệu cho phân tích. [Báo cáo dự án](FLOODINSIGHT_FINAL_REPORT.md) · [Báo cáo giao diện](FLOOD_DASHBOARD_REPORT.md)
