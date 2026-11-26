import type { Location } from "./data";

export const categories = ["Low", "Moderate", "High", "Very High", "Insufficient Data"] as const;
export type RiskCategory = typeof categories[number];
export const riskColors: Record<RiskCategory, string> = {
  Low: "#53ca89", Moderate: "#e8c658", High: "#f29955", "Very High": "#f47180", "Insufficient Data": "#93a0af",
};
export const riskRadius: Partial<Record<RiskCategory, number>> = {
  Low: 500, Moderate: 900, High: 1400, "Very High": 1800,
};
export type MapHorizon = "summary" | 6 | 12 | 24;
export type HistoricalScenarioId = "live" | "son-ca-2022" | "monsoon-2023" | "trami-2024" | "cloudburst-2024-11";
export type HistoricalScenario = {
  id: HistoricalScenarioId;
  label: string;
  dateLabel: string;
  rain24hByLocation: Record<string, number>;
  defaultRain24h: number;
  summary: string;
  source: string;
};
export const historicalScenarios: HistoricalScenario[] = [
  {
    id: "live",
    label: "Dự báo hiện tại",
    dateLabel: "Thời gian thực",
    rain24hByLocation: {},
    defaultRain24h: 0,
    summary: "Hiển thị nguy cơ ngập dựa trên dự báo mưa và mô hình hiện hành.",
    source: "",
  },
  {
    id: "monsoon-2023",
    label: "Đợt mưa 14/10/2023",
    dateLabel: "14/10/2023 · V-Rain",
    rain24hByLocation: {
      "hai-chau": 78, "thanh-khe": 85, "lien-chieu": 125, "cam-le": 72,
      "son-tra": 65, "ngu-hanh-son": 68, "hoa-vang": 95,
    },
    defaultRain24h: 75,
    summary: "Đợt mưa lớn tháng 10/2023 gây ngập cục bộ tại các trục trũng Hải Châu (Hàm Nghi, Lê Duẩn, Núi Thành) trong khi tuyến ven sông Bạch Đằng – 2 Tháng 9 vẫn lưu thông được.",
    source: "https://baodanang.vn/nhieu-tuyen-duong-moi-mua-da-ngap-3281789.html",
  },
  {
    id: "trami-2024",
    label: "Bão Trami (27/10/2024)",
    dateLabel: "27/10/2024 · V-Rain",
    rain24hByLocation: {
      "hai-chau": 118, "thanh-khe": 124, "lien-chieu": 168, "cam-le": 112,
      "son-tra": 135, "ngu-hanh-son": 98, "hoa-vang": 152,
    },
    defaultRain24h: 115,
    summary: "Hoàn lưu bão Trami (số 6) gây mưa lớn diện rộng, các điểm trũng nội đô ngập 0.3–0.5m, lan sang các đoạn đường nối tiếp.",
    source: "https://baodanang.vn/tang-cuong-luc-luong-ho-tro-di-doi-dan-vung-ngap-lut-3308691.html",
  },
  {
    id: "cloudburst-2024-11",
    label: "Mưa cực đoan 05/11/2024",
    dateLabel: "05/11/2024 · Hòa Cường Nam 281mm",
    rain24hByLocation: {
      "hai-chau": 215, "thanh-khe": 165, "lien-chieu": 145, "cam-le": 175,
      "son-tra": 120, "ngu-hanh-son": 140, "hoa-vang": 110,
    },
    defaultRain24h: 140,
    summary: "Trạm Hòa Cường Nam (Hải Châu) ghi nhận 281 mm ngày 05/11/2024, gây ngập sâu 0.5–1.0 m khu Núi Thành – Hàm Nghi – Lê Duẩn.",
    source: "https://dansinh.dantri.com.vn/dien-dan-dan-sinh/da-nang-mua-lon-nhieu-tuyen-duong-ngap-sau-hoc-sinh-nghi-hoc-20241105101609887.htm",
  },
  {
    id: "son-ca-2022",
    label: "Bão Sơn Ca (14/10/2022)",
    dateLabel: "14/10/2022 · Lịch sử >500mm",
    rain24hByLocation: {
      "hai-chau": 380, "thanh-khe": 410, "lien-chieu": 520, "cam-le": 360,
      "son-tra": 340, "ngu-hanh-son": 310, "hoa-vang": 420,
    },
    defaultRain24h: 350,
    summary: "Trận mưa lịch sử bão Sơn Ca (14–15/10/2022), lượng mưa cực đoan gây ngập sâu trên diện rộng khắp trung tâm Đà Nẵng.",
    source: "https://baodanang.vn/giam-tai-cho-he-thong-thoat-nuoc-de-chong-ngap-3159050.html",
  },
];

export type FloodZone = {
  id: string;
  name: string;
  locationCode: string;
  center: [number, number];
  coreRadiusM: number;
  outerRadiusM: number;
  triggerMm24h: number;
  elevationNote: string;
};
export const floodZones: FloodZone[] = [
  { id: "zone-thac-gian", name: "Vùng trũng Hồ Thạc Gián – Hàm Nghi", locationCode: "hai-chau", center: [16.0636, 108.2112], coreRadiusM: 280, outerRadiusM: 540, triggerMm24h: 38, elevationNote: "Lõi trũng quanh hồ điều tiết Thạc Gián, thoát nước chậm khi mưa cường suất lớn." },
  { id: "zone-le-duan", name: "Vùng trũng Lê Duẩn – BV Đà Nẵng", locationCode: "hai-chau", center: [16.0719, 108.2138], coreRadiusM: 260, outerRadiusM: 520, triggerMm24h: 40, elevationNote: "Mật độ bê tông hóa >68%, thường ứ đọng nước từ Hoàng Hoa Thám đến Lý Thái Tổ." },
  { id: "zone-hoa-cuong", name: "Vùng trũng Hòa Cường Nam – Núi Thành", locationCode: "hai-chau", center: [16.0432, 108.2201], coreRadiusM: 320, outerRadiusM: 620, triggerMm24h: 40, elevationNote: "Khu vực thấp trũng phía nam Hải Châu, tâm điểm mưa 281mm ngày 05/11/2024." },
  { id: "zone-me-suot", name: "Rốn ngập Mẹ Suốt – Hòa Khánh Nam", locationCode: "lien-chieu", center: [16.0655, 108.1515], coreRadiusM: 380, outerRadiusM: 760, triggerMm24h: 45, elevationNote: "Hứng nước sườn đồi đổ xuống, ngập lịch sử tới 2m trận 14/10/2022." },
  { id: "zone-lo-voi", name: "Vùng trũng Cống Lò Vôi – CMT8", locationCode: "cam-le", center: [16.0215, 108.2060], coreRadiusM: 300, outerRadiusM: 600, triggerMm24h: 55, elevationNote: "Điểm trũng ven sông Cẩm Lệ, dễ ngập khi mưa kết hợp triều cường." },
];

export type HistoricalRoad = {
  id: string;
  name: string;
  corridorGroup: string;
  fromLabel: string;
  toLabel: string;
  connectedNext: string;
  locationCode: string;
  coordinates: [number, number];
  path: [number, number][];
  routeType: "flood_prone" | "safer_corridor";
  triggerMm24h: number;
  historicalNote: string;
  source: string;
};

const localFloods = "https://baodanang.vn/nhieu-tuyen-duong-moi-mua-da-ngap-3281789.html";
const drainage = "https://baodanang.vn/ba-du-an-thoat-nuoc-kip-thoi-giup-giam-ngap-trung-tam-do-thi-da-nang-3351930.html";
export const historicalRoads: HistoricalRoad[] = [
  // === HẢI CHÂU — Trục 1: Hàm Nghi → Nguyễn Văn Linh → Cầu Rồng (chuyển tiếp Đỏ → Cam → Vàng → Xanh) ===
  { id: "ham-nghi-core", name: "Hàm Nghi (Tản Đà → Nguyễn Văn Linh)", corridorGroup: "Trục Hàm Nghi – Nguyễn Văn Linh",
    fromLabel: "Ngã tư Tản Đà", toLabel: "Nút giao Nguyễn Văn Linh",
    connectedNext: "Nối tiếp ra Nguyễn Văn Linh (ngập giảm dần) → Rẽ Trần Phú / Bạch Đằng để né ngập.",
    locationCode: "hai-chau", coordinates: [16.0638, 108.2112],
    path: [[16.0666, 108.2108], [16.0648, 108.2111], [16.0630, 108.2113], [16.0607, 108.2116]],
    routeType: "flood_prone", triggerMm24h: 36,
    historicalNote: "Tâm trũng quanh hồ Thạc Gián, ngập sâu 0.3–0.5m ngày 05/11/2024.", source: drainage },
  { id: "nvl-mid", name: "Nguyễn Văn Linh (Hàm Nghi → Phan Châu Trinh)", corridorGroup: "Trục Hàm Nghi – Nguyễn Văn Linh",
    fromLabel: "Nút giao Hàm Nghi", toLabel: "Ngã tư Phan Châu Trinh",
    connectedNext: "Đoạn nối liền vùng trũng Hàm Nghi, nước giảm dần về hướng Cầu Rồng.",
    locationCode: "hai-chau", coordinates: [16.0608, 108.2160],
    path: [[16.0607, 108.2116], [16.0607, 108.2145], [16.0608, 108.2178], [16.0609, 108.2202]],
    routeType: "flood_prone", triggerMm24h: 55,
    historicalNote: "Đoạn nối tiếp nút giao Hoàng Diệu – Hàm Nghi, ngập trung bình khi mưa vượt 55mm.", source: drainage },
  { id: "nvl-east", name: "Nguyễn Văn Linh (Phan Châu Trinh → Cầu Rồng)", corridorGroup: "Trục Hàm Nghi – Nguyễn Văn Linh",
    fromLabel: "Ngã tư Phan Châu Trinh", toLabel: "Đầu Cầu Rồng (Bạch Đằng)",
    connectedNext: "Thoát nước nhanh ra sông Hàn, nối trực tiếp với trục an toàn Trần Phú & Bạch Đằng.",
    locationCode: "hai-chau", coordinates: [16.0610, 108.2224],
    path: [[16.0609, 108.2202], [16.0610, 108.2225], [16.0611, 108.2244]],
    routeType: "flood_prone", triggerMm24h: 95,
    historicalNote: "Đoạn mép ngoài gần sông Hàn, chỉ ứ đọng nhẹ khi mưa rất lớn.", source: drainage },

  // === HẢI CHÂU — Trục 2: Lê Duẩn → Bạch Đằng (chuyển tiếp Đỏ → Cam → Vàng → Xanh) ===
  { id: "le-duan-core", name: "Lê Duẩn (Hoàng Hoa Thám → Lý Thái Tổ)", corridorGroup: "Trục Lê Duẩn – Sông Hàn",
    fromLabel: "Ngã tư Hoàng Hoa Thám", toLabel: "Ngã tư Lý Thái Tổ",
    connectedNext: "Nối tiếp đoạn Lý Thái Tổ → Nguyễn Chí Thanh (ngập thấp hơn), ưu tiên né qua Quang Trung/Trần Phú.",
    locationCode: "hai-chau", coordinates: [16.0721, 108.2125],
    path: [[16.0725, 108.2098], [16.0721, 108.2125], [16.0718, 108.2152]],
    routeType: "flood_prone", triggerMm24h: 38,
    historicalNote: "Điểm trũng lịch sử trước BV Đà Nẵng, ngập 0.3–0.6m các đợt 14/10/2022 & 05/11/2024.", source: localFloods },
  { id: "le-duan-mid", name: "Lê Duẩn (Lý Thái Tổ → Nguyễn Chí Thanh)", corridorGroup: "Trục Lê Duẩn – Sông Hàn",
    fromLabel: "Ngã tư Lý Thái Tổ", toLabel: "Ngã tư Nguyễn Chí Thanh",
    connectedNext: "Nối liền đoạn đầu sông Hàn (ngập nhẹ), có thể rẽ phải vào Trần Phú để tránh.",
    locationCode: "hai-chau", coordinates: [16.0715, 108.2178],
    path: [[16.0718, 108.2152], [16.0715, 108.2178], [16.0713, 108.2202]],
    routeType: "flood_prone", triggerMm24h: 58,
    historicalNote: "Đoạn chuyển tiếp từ vùng trũng Lê Duẩn hướng ra sông Hàn, ngập nhẹ đến trung bình.", source: localFloods },
  { id: "le-duan-east", name: "Lê Duẩn (Nguyễn Chí Thanh → Bạch Đằng)", corridorGroup: "Trục Lê Duẩn – Sông Hàn",
    fromLabel: "Ngã tư Nguyễn Chí Thanh", toLabel: "Nút giao Bạch Đằng (Cầu Sông Hàn)",
    connectedNext: "Nối thẳng ra trục ven sông Bạch Đằng cao ráo, thoát nước nhanh.",
    locationCode: "hai-chau", coordinates: [16.0711, 108.2224],
    path: [[16.0713, 108.2202], [16.0711, 108.2224], [16.0710, 108.2245]],
    routeType: "flood_prone", triggerMm24h: 95,
    historicalNote: "Gần cửa xả sông Hàn, hiếm khi ngập sâu trừ mưa lịch sử.", source: drainage },

  // === HẢI CHÂU — Trục 3: Quang Trung – Hải Phòng ===
  { id: "quang-trung-core", name: "Quang Trung – Hải Phòng (Ông Ích Khiêm → Nguyễn Chí Thanh)", corridorGroup: "Trục Quang Trung – Hải Phòng",
    fromLabel: "Ngã tư Ông Ích Khiêm", toLabel: "Ngã tư Nguyễn Chí Thanh",
    connectedNext: "Nối tiếp đoạn Quang Trung → Bạch Đằng (ít ngập hơn).",
    locationCode: "hai-chau", coordinates: [16.0752, 108.2165],
    path: [[16.0750, 108.2130], [16.0752, 108.2165], [16.0754, 108.2198]],
    routeType: "flood_prone", triggerMm24h: 48,
    historicalNote: "Khu vực nội đô bê tông hóa >68%, thoát nước chậm khi mưa lớn kéo dài.", source: localFloods },
  { id: "quang-trung-east", name: "Quang Trung (Nguyễn Chí Thanh → Bạch Đằng)", corridorGroup: "Trục Quang Trung – Hải Phòng",
    fromLabel: "Ngã tư Nguyễn Chí Thanh", toLabel: "Ngã ba Bạch Đằng",
    connectedNext: "Nối trực tiếp ra tuyến tránh ngập Trần Phú và Bạch Đằng.",
    locationCode: "hai-chau", coordinates: [16.0756, 108.2222],
    path: [[16.0754, 108.2198], [16.0756, 108.2222], [16.0758, 108.2242]],
    routeType: "flood_prone", triggerMm24h: 90,
    historicalNote: "Đoạn gần bờ sông Hàn, mức ngập nhẹ hơn rõ rệt so với phía tây.", source: drainage },

  // === HẢI CHÂU — Trục 4: Núi Thành – Hòa Cường Nam ===
  { id: "nui-thanh-core", name: "Núi Thành (Tiểu La → Duy Tân)", corridorGroup: "Trục Núi Thành – Hòa Cường",
    fromLabel: "Ngã tư Tiểu La", toLabel: "Ngã tư Duy Tân",
    connectedNext: "Nối sang đoạn Duy Tân → Xô Viết Nghệ Tĩnh (ngập ít hơn), ưu tiên đi song song đường 2 Tháng 9.",
    locationCode: "hai-chau", coordinates: [16.0455, 108.2204],
    path: [[16.0485, 108.2208], [16.0455, 108.2204], [16.0425, 108.2200]],
    routeType: "flood_prone", triggerMm24h: 40,
    historicalNote: "Trạm Hòa Cường Nam ghi nhận 281mm ngày 05/11/2024, ngập sâu đến 0.8–1.0m.",
    source: "https://dansinh.dantri.com.vn/dien-dan-dan-sinh/da-nang-mua-lon-nhieu-tuyen-duong-ngap-sau-hoc-sinh-nghi-hoc-20241105101609887.htm" },
  { id: "nui-thanh-south", name: "Núi Thành (Duy Tân → Xô Viết Nghệ Tĩnh)", corridorGroup: "Trục Núi Thành – Hòa Cường",
    fromLabel: "Ngã tư Duy Tân", toLabel: "Nút giao Xô Viết Nghệ Tĩnh",
    connectedNext: "Rẽ đông sang đường 2 Tháng 9 để di chuyển an toàn.",
    locationCode: "hai-chau", coordinates: [16.0392, 108.2196],
    path: [[16.0425, 108.2200], [16.0392, 108.2196], [16.0360, 108.2192]],
    routeType: "flood_prone", triggerMm24h: 65,
    historicalNote: "Đoạn nối tiếp phía nam Hòa Cường, ngập nhẹ đến trung bình.", source: localFloods },

  // === HẢI CHÂU — Các tuyến cao ráo / gợi ý lộ trình né ngập (🟢) ===
  { id: "hc-bach-dang", name: "Bạch Đằng (Quang Trung → Cầu Rồng)", corridorGroup: "Lộ trình né ngập Hải Châu",
    fromLabel: "Ngã ba Quang Trung", toLabel: "Đầu Cầu Rồng",
    connectedNext: "Kết nối thẳng sang đường 2 Tháng 9 đi về phía nam mà không qua điểm trũng.",
    locationCode: "hai-chau", coordinates: [16.0685, 108.2247],
    path: [[16.0758, 108.2242], [16.0710, 108.2245], [16.0660, 108.2248], [16.0611, 108.2244]],
    routeType: "safer_corridor", triggerMm24h: 180,
    historicalNote: "Tuyến ven sông có cửa xả trực tiếp ra sông Hàn, ít ngập nhất khu vực trung tâm.", source: drainage },
  { id: "hc-tran-phu", name: "Trần Phú (Quang Trung → Cầu Rồng)", corridorGroup: "Lộ trình né ngập Hải Châu",
    fromLabel: "Ngã tư Quang Trung", toLabel: "Nút giao Nguyễn Văn Linh",
    connectedNext: "Tuyến song song Bạch Đằng giúp né toàn bộ điểm ngập Lê Duẩn – Hàm Nghi.",
    locationCode: "hai-chau", coordinates: [16.0686, 108.2225],
    path: [[16.0756, 108.2222], [16.0711, 108.2224], [16.0662, 108.2226], [16.0610, 108.2225]],
    routeType: "safer_corridor", triggerMm24h: 155,
    historicalNote: "Trục trung tâm cốt nền cao hơn khu phía tây, thuận lợi di chuyển khi mưa lớn.", source: drainage },
  { id: "hc-2-thang-9", name: "Đường 2 Tháng 9 (Cầu Rồng → Công viên Châu Á)", corridorGroup: "Lộ trình né ngập Hải Châu",
    fromLabel: "Nút giao Cầu Rồng", toLabel: "Công viên Châu Á",
    connectedNext: "Tuyến thay thế trực tiếp cho trục Núi Thành – Tiểu La khi Hòa Cường Nam ngập.",
    locationCode: "hai-chau", coordinates: [16.0480, 108.2244],
    path: [[16.0595, 108.2242], [16.0525, 108.2243], [16.0455, 108.2245], [16.0365, 108.2246]],
    routeType: "safer_corridor", triggerMm24h: 170,
    historicalNote: "Trục rộng cốt nền cao, hệ thống cống lớn thoát nhanh ra sông Hàn.", source: drainage },

  // === Các quận/huyện khác của Đà Nẵng ===
  { id: "hung-vuong", name: "Hùng Vương (Ông Ích Khiêm → Chi Lăng)", corridorGroup: "Thanh Khê",
    fromLabel: "Ngã tư Ông Ích Khiêm", toLabel: "Ngã tư Chi Lăng",
    connectedNext: "Giảm ngập dần về phía ngã năm Hoàng Diệu.",
    locationCode: "thanh-khe", coordinates: [16.0678, 108.2080],
    path: [[16.0681, 108.2025], [16.0678, 108.2080], [16.0674, 108.2145]],
    routeType: "flood_prone", triggerMm24h: 50,
    historicalNote: "Ghi nhận ngập cục bộ 0.3–0.5m trong các đợt mưa lớn 2022–2024.", source: "https://vnexpress.net/duong-pho-trung-tam-da-nang-ngap-sau-sau-mua-4651644.html" },
  { id: "dien-bien-phu", name: "Điện Biên Phủ (Công viên 29/3 → Ngã ba Huế)", corridorGroup: "Thanh Khê",
    fromLabel: "Công viên 29/3", toLabel: "Hầm chui Ngã ba Huế",
    connectedNext: "Nên vòng qua Nguyễn Tri Phương hoặc Nguyễn Tất Thành khi mưa lớn.",
    locationCode: "thanh-khe", coordinates: [16.0655, 108.1985],
    path: [[16.0662, 108.1915], [16.0655, 108.1985], [16.0650, 108.2045]],
    routeType: "flood_prone", triggerMm24h: 55,
    historicalNote: "Khu vực công viên 29/3 từng phải bơm tiêu thoát ngập khẩn cấp.", source: localFloods },
  { id: "me-suot", name: "Mẹ Suốt (Hòa Khánh Nam – Liên Chiểu)", corridorGroup: "Liên Chiểu",
    fromLabel: "Khu dân cư Mẹ Suốt", toLabel: "Nút giao Hoàng Văn Thái",
    connectedNext: "Tránh đi vào kiệt sâu, ưu tiên trục Nguyễn Lương Bằng cao hơn.",
    locationCode: "lien-chieu", coordinates: [16.0655, 108.1515],
    path: [[16.0695, 108.1505], [16.0655, 108.1515], [16.0615, 108.1525]],
    routeType: "flood_prone", triggerMm24h: 45,
    historicalNote: "Rốn lũ lịch sử Liên Chiểu, ngập sâu gần 2m trận 14/10/2022.", source: "https://baodanang.vn/giam-tai-cho-he-thong-thoat-nuoc-de-chong-ngap-3159050.html" },
  { id: "ton-duc-thang", name: "Tôn Đức Thắng (Cống Đa Cô → Ngã ba Huế)", corridorGroup: "Liên Chiểu",
    fromLabel: "Cống Đa Cô", toLabel: "Ngã ba Huế",
    connectedNext: "Nước giảm dần khi qua khỏi nút thắt cống Đa Cô.",
    locationCode: "lien-chieu", coordinates: [16.0690, 108.1620],
    path: [[16.0715, 108.1555], [16.0690, 108.1620], [16.0668, 108.1690]],
    routeType: "flood_prone", triggerMm24h: 55,
    historicalNote: "Nút thắt thoát nước cống Đa Cô khi mưa lớn từ sườn đồi đổ xuống.", source: "https://baodanang.vn/giam-tai-cho-he-thong-thoat-nuoc-de-chong-ngap-3159050.html" },
  { id: "cmt8", name: "Cách Mạng Tháng Tám (Cống Lò Vôi – Cẩm Lệ)", corridorGroup: "Cẩm Lệ",
    fromLabel: "Khu vực Cống Lò Vôi", toLabel: "Cầu Cẩm Lệ",
    connectedNext: "Ưu tiên di chuyển qua trục Thăng Long / Võ Chí Công.",
    locationCode: "cam-le", coordinates: [16.0215, 108.2060],
    path: [[16.0265, 108.2095], [16.0215, 108.2060], [16.0160, 108.2025]],
    routeType: "flood_prone", triggerMm24h: 60,
    historicalNote: "Điểm ngập trũng lặp lại ven sông Cẩm Lệ khi mưa kéo dài.", source: localFloods },
  { id: "le-tan-trung", name: "Lê Tấn Trung (Thọ Quang – Sơn Trà)", corridorGroup: "Sơn Trà",
    fromLabel: "Ngã tư Ngô Quyền", toLabel: "Khu dân cư Thọ Quang",
    connectedNext: "Thoát nhanh hơn về phía trục Võ Nguyên Giáp / Ngô Quyền.",
    locationCode: "son-tra", coordinates: [16.0920, 108.2500],
    path: [[16.0945, 108.2465], [16.0920, 108.2500], [16.0895, 108.2535]],
    routeType: "flood_prone", triggerMm24h: 60,
    historicalNote: "Tuyến đường thường ứ đọng nước khi mưa lớn kéo dài.", source: "https://baodanang.vn/duong-le-tan-trung-bi-ngap-3281266.html" },
  { id: "tran-dai-nghia", name: "Trần Đại Nghĩa (Ngũ Hành Sơn)", corridorGroup: "Ngũ Hành Sơn",
    fromLabel: "Nút giao Mai Đăng Chơn", toLabel: "Khu Đô thị FPT",
    connectedNext: "Có thể vòng ra trục Võ Chí Công / Lê Văn Hiến.",
    locationCode: "ngu-hanh-son", coordinates: [15.9820, 108.2440],
    path: [[15.9910, 108.2410], [15.9820, 108.2440], [15.9730, 108.2470]],
    routeType: "flood_prone", triggerMm24h: 65,
    historicalNote: "Khu vực trũng thấp từng ghi nhận ngập cục bộ khi mưa lớn.", source: localFloods },
  { id: "tuy-loan", name: "Túy Loan (Hòa Phong – Hòa Vang)", corridorGroup: "Hòa Vang",
    fromLabel: "Chợ Túy Loan", toLabel: "Cầu Túy Loan",
    connectedNext: "Chú ý mực nước sông Túy Loan khi có lũ thượng nguồn.",
    locationCode: "hoa-vang", coordinates: [15.9950, 108.1380],
    path: [[16.0020, 108.1350], [15.9950, 108.1380], [15.9870, 108.1415]],
    routeType: "flood_prone", triggerMm24h: 70,
    historicalNote: "Khu vực ven sông Túy Loan chịu ảnh hưởng lũ thượng nguồn (2020, 2022, 2023).", source: "https://baodanang.vn/tang-cuong-luc-luong-ho-tro-di-doi-dan-vung-ngap-lut-3308691.html" },
];
export const indexHelp = "Experimental score from 0 to 100. It measures the index factors on their configured scale.";
export const probabilityHelp = "Estimated chance of inundation within the 24-hour forecast window from an approved calibrated flood model.";

type Numbers = Record<string, number | null>;
export type Assessment = {
  id: number; location: string; issued_at: string; valid_until: string; created_at: string;
  risk_category: RiskCategory; risk_index: number | null; method_version: string; forecast_horizon_hours: number;
  assessment_status: string; validation_status: string; weight_coverage: number; missing_features: string[];
  factors: Record<string, { weight: number; inputs: Numbers; normalized: number | null; contribution_points: number | null }>;
  observed_rainfall: Numbers; forecast_rainfall: Numbers;
  source_references: Record<string, {url: string; resolution: string; provenance_type?: string}>;
  horizon_breakdown?: {
    horizon_hours?: number;
    hours?: number;
    rain_mm?: number | null;
    rainfall_mm?: number | null;
    threshold_mm?: number | null;
    threshold_ratio?: number | null;
    risk_category?: RiskCategory | null;
    risk_index?: number | null;
    status?: string;
  }[] | null;
  inundation_detail?: {
    primary_driver?: string | null;
    trigger_thresholds_mm?: Record<string, number> | null;
    rainfall_threshold_mm?: number | null;
    forecast_vs_threshold_24h_ratio?: number | null;
    confidence_level?: string | null;
    depth_cm?: number | null;
    starts_at?: string | null;
    data_provenance?: {
      types?: string[];
      has_verified_in_situ?: boolean;
      warning?: string | null;
    } | null;
  } | null;
  recommended_actions?: string[] | Partial<Record<"vi" | "en", string[]>> | null;
  data_provenance?: Assessment["source_references"] | null;
  data_freshness: Record<string, {available_at: string; last_valid_at?: string | null}>;
  excluded_factors: Record<string, string>;
};
export type PointRisk = { point: Location; assessment: Assessment | null; is_current: boolean };
export type FloodPrediction = {
  id?: number; location: string; issued_at: string; valid_until: string; flood_probability: number | null;
  risk_classification: string; model_version: string | null; model_validation_status: string;
  feature_contributions?: Record<string, {probability_change_from_median_probe: number}> | null;
};
export type Readiness = { status: string; inventory: Record<string, number>; blocking_inventory: string[] };
type Evaluation = {
  precision: number | null; recall: number | null; f1: number | null; pr_auc_average_precision: number | null;
  roc_auc: number | null; brier: number | null; confusion?: {tn: number; fp: number; fn: number; tp: number};
  calibration_curve?: {mean_probability: number; positive_fraction: number; count: number}[];
};
export type FloodMetrics = {
  status: string; version: string | null; readiness: Readiness;
  evaluation: {
    winner?: string; calibration?: string; test?: Evaluation;
    candidates?: {candidate: string; method: string; status?: string; calibrated_selection?: Evaluation}[];
    feature_importance?: Record<string, number>;
  } | null;
};
export type FloodProfiles = {
  complete_points: number; excluded_points: number; silhouette_in_sample: number; interpretation: string;
  assignments: {location: string; cluster_id: number; features: Record<string, number>}[];
};
export type FloodCoverage = {
  counts: Record<string, number>; label_counts: Record<string, number>;
  weather_daily: {location: string; source: string; first_date: string; last_date: string; days_with_rainfall: number; missing_days_between: number | string}[];
  weather_provider_grids: {feed: string; source: string; point: string; rows: number; first_valid: string; last_valid: string}[];
  weather_hourly_nulls: Record<string, number>[];
  terrain: {point: string; source: string; feature: string}[];
  hydrology: {station_key: string; variable: string; source: string; rows: number; first_valid: string; last_valid: string; missing_hours_between: number | string}[];
  events: {event_key: string; locality_as_reported: string; started_at: string; ended_before: string; source_ref: string}[];
};

export const label = (value?: string | null) => value?.replaceAll("_", " ") ?? "Unavailable";
export const activeAssessment = (row?: PointRisk) => row?.is_current ? row.assessment : null;
export const pointCategory = (row?: PointRisk): RiskCategory => activeAssessment(row)?.risk_category ?? "Insufficient Data";
export function mapEvidence(row: PointRisk | undefined, horizon: MapHorizon) {
  const assessment = activeAssessment(row);
  const hours = horizon === "summary" ? 24 : horizon;
  const breakdown = Array.isArray(assessment?.horizon_breakdown)
    ? assessment.horizon_breakdown.find(entry => (entry?.horizon_hours ?? entry?.hours) === hours) : undefined;
  const risk = horizon === "summary" ? assessment?.risk_category : breakdown?.risk_category;
  const forecastRain = breakdown?.rain_mm ?? breakdown?.rainfall_mm ?? assessment?.forecast_rainfall?.[`forecast_rain_next_${hours}h_mm`] ?? null;
  const prevRain = horizon === "summary" ? (assessment?.observed_rainfall?.rain_prev_24h_mm ?? null) : null;
  const rain = prevRain != null && forecastRain != null ? Math.max(prevRain, forecastRain) : (forecastRain ?? prevRain);
  return {
    category: risk && categories.includes(risk) ? risk : "Insufficient Data" as const,
    rain,
  };
}

export function roadScreening(rain: number | null, threshold: number | null, horizon: MapHorizon) {
  if (rain == null || !Number.isFinite(rain) || rain < 0 ||
      threshold == null || !Number.isFinite(threshold) || threshold <= 0) {
    return { label: "Chưa có dữ liệu mưa", depth: "—", color: "#93a0af", rank: 0, status: "unknown" as const };
  }
  const scale = horizon === 6 ? 0.5 : horizon === 12 ? 0.72 : 1;
  const ratio = rain / (threshold * scale);
  if (ratio >= 1.15) return { label: "Ngập sâu — Tránh đi qua", depth: "30–50+ cm", color: "#dc2626", rank: 4, status: "deep" as const };
  if (ratio >= 0.75) return { label: "Ngập trung bình — Hạn chế qua", depth: "15–30 cm", color: "#f97316", rank: 3, status: "moderate" as const };
  if (ratio >= 0.45) return { label: "Ngập nhẹ / Ứ cục bộ", depth: "5–15 cm", color: "#eab308", rank: 2, status: "light" as const };
  return { label: "Cao ráo / An toàn — Gợi ý né ngập", depth: "< 5 cm", color: "#16a34a", rank: 1, status: "safe" as const };
}
export const formatProbability = (value: number | null | undefined) => value == null ? "Unavailable" :
  new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 1 }).format(value);
