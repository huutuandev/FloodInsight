"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import type { FormEvent } from "react";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowUpRight, CalendarDays, CheckCircle2,
  CloudRain, Database, Info, LayoutDashboard, MapPinned, MapPin, Moon,
  RefreshCw, ShieldAlert, Sparkles, Sun, Waves
} from "lucide-react";
import {
  ApiError, recentCoveredRange, source, useData, withWeatherLocations,
  type DateRange, type Location, type RainfallCoverage, type Status, type Weather
} from "./data";
import { DataManagement, MachineLearning } from "./operation-panels";
import { Analytics, MapSection, Overview } from "./weather-panels";
import { QueryError, StatePill } from "./ui";

const navigation = [
  {
    name: "Overview",
    vietnamese: "Tổng quan đô thị",
    short: "Tổng quan",
    icon: LayoutDashboard,
    detail: "Theo dõi lượng mưa, thời tiết trực tiếp và tình trạng các trạm quan trắc tại Đà Nẵng.",
  },
  {
    name: "Da Nang Map",
    vietnamese: "Bản đồ ngập lụt",
    short: "Bản đồ",
    icon: MapPinned,
    detail: "Bản đồ không gian các trạm quan trắc, lớp phủ Radar mây mưa và phân vùng nguy cơ ngập lụt.",
  },
  {
    name: "Rainfall Analytics",
    vietnamese: "Phân tích lượng mưa",
    short: "Phân tích",
    icon: CloudRain,
    detail: "Phân tích chuỗi thời gian, thống kê mô tả lượng mưa và ma trận tương quan thời tiết.",
  },
  {
    name: "Machine Learning",
    vietnamese: "Khai phá dữ liệu & AI",
    short: "Mô hình AI",
    icon: Sparkles,
    detail: "Kết quả mô hình phân cụm K-Means, hồi quy dự báo lượng mưa và phân loại rủi ro ngập.",
  },
  {
    name: "Data Management",
    vietnamese: "Quản trị kho dữ liệu",
    short: "Kho dữ liệu",
    icon: Database,
    detail: "Giám sát tiến trình cào dữ liệu Open-Meteo, luồng ETL và độ bao phủ của kho dữ liệu.",
  },
] as const;

type Section = typeof navigation[number]["name"];
type Theme = "dark" | "light";

function subscribeTheme(callback: () => void) {
  window.addEventListener("floodinsight-theme", callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener("floodinsight-theme", callback);
    window.removeEventListener("storage", callback);
  };
}
function getTheme(): Theme {
  return localStorage.getItem("floodinsight-theme") === "light" ? "light" : "dark";
}
function serverTheme(): Theme { return "dark"; }

function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <Waves size={23} />
      </span>
      <span>
        <strong>Flood<span>Insight</span></strong>
        <small>ĐÀ NẴNG SMART CITY</small>
      </span>
    </div>
  );
}

function FloodAlertBanner({ weather }: { weather: Weather[] }) {
  const maxRain = useMemo(() => {
    if (!weather.length) return 0;
    return Math.max(...weather.map((w) => w.payload.values.precipitation ?? 0));
  }, [weather]);

  const level = useMemo(() => {
    if (maxRain >= 50) return {
      title: "CẤP 3: CẢNH BÁO NGUY HIỂM",
      detail: "Mưa rất to diện rộng (≥ 50 mm/h). Nguy cơ ngập sâu tại các tuyến đường trũng thấp (Mẹ Suốt, Hàm Nghi, Khe Cạn).",
      icon: ShieldAlert,
      badge: "NGUY HIỂM",
      tone: "danger",
    };
    if (maxRain >= 25) return {
      title: "CẤP 2: NGUY CƠ NGẬP CAO",
      detail: "Mưa lớn cục bộ (25–50 mm/h). Khả năng xuất hiện ngập úng cục bộ tại các nút giao trũng.",
      icon: AlertTriangle,
      badge: "CẢNH BÁO CAO",
      tone: "warn",
    };
    if (maxRain >= 10) return {
      title: "CẤP 1: CẢNH BÁO THEO DÕI",
      detail: "Mưa rào rải rác (10–25 mm/h). Hệ thống thoát nước đô thị đang vận hành ổn định.",
      icon: Info,
      badge: "THEO DÕI",
      tone: "warn",
    };
    return {
      title: "CẤP 0: TRẠNG THÁI ĐÔ THỊ AN TOÀN",
      detail: "Thời tiết ổn định, không ghi nhận mưa cực đoan trên địa bàn 5 quận trọng điểm TP. Đà Nẵng.",
      icon: CheckCircle2,
      badge: "AN TOÀN",
      tone: "good",
    };
  }, [maxRain]);

  const Icon = level.icon;

  return (
    <div className={`flood-alert-banner ${level.tone}`}>
      <div className="flood-alert-left">
        <div className="flood-alert-icon">
          <Icon size={20} />
        </div>
        <div className="flood-alert-text">
          <div className="flood-alert-title-row">
            <strong>{level.title}</strong>
            <span className={`pill ${level.tone}`}>{level.badge}</span>
          </div>
          <p>{level.detail}</p>
        </div>
      </div>
      <div className="flood-alert-right">
        <span style={{ fontSize: "11.5px", color: "var(--muted)" }}>
          Cực đại tức thời: <strong style={{ color: "var(--text)" }}>{maxRain.toFixed(1)} mm/h</strong>
        </span>
        <span className="pill good">
          <i /> Trực tuyến 24/7
        </span>
      </div>
    </div>
  );
}

function DashboardBody({ initialRange }: { initialRange: DateRange }) {
  const queryClient = useQueryClient();
  const [section, navigate] = useState<Section>("Overview");
  const [location, chooseLocation] = useState("");
  const [range, setRange] = useState<DateRange>();
  const [draft, setDraft] = useState<DateRange>();
  const [filterError, setFilterError] = useState("");
  const theme = useSyncExternalStore(subscribeTheme, getTheme, serverTheme);
  const locations = useData<Location[]>("locations");
  const weather = useData<Weather[]>("weather/latest", undefined, true, 60_000);
  const status = useData<Status>("system/status", undefined, true, 45_000);
  const points = useMemo(() => withWeatherLocations(locations.data ?? [], weather.data ?? []), [locations.data, weather.data]);
  const coverage = useData<RainfallCoverage[]>("rainfall/coverage", { source });
  const selected = points.some((point) => point.code === location) ? location :
    points.find((point) => coverage.data?.some((row) => row.location === point.code))?.code ?? points[0]?.code ?? "";
  const selectedCoverage = coverage.data?.find((row) => row.location === selected);
  const activeRange = range ?? recentCoveredRange(selectedCoverage, initialRange);
  const inputRange = draft ?? activeRange;
  const scope = { location: selected, ...activeRange };

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const days = (Date.parse(inputRange.end_date) - Date.parse(inputRange.start_date)) / 86_400_000;
    if (!Number.isFinite(days) || days < 0 || days >= 3660) {
      setFilterError("Khoảng thời gian phải hợp lệ và tối đa 3.660 ngày.");
      return;
    }
    setFilterError("");
    setRange(inputRange);
  }

  function setPreset(start: string, end: string) {
    const next = { start_date: start, end_date: end };
    setDraft(next);
    setRange(next);
    setFilterError("");
  }

  function go(next: Section) {
    navigate(next);
    window.scrollTo({ top: 0 });
  }

  const currentNav = navigation.find((item) => item.name === section);

  return (
    <div className="dashboard" data-theme={theme}>
      <aside className="sidebar" aria-label="Dashboard sidebar">
        <Brand />
        <nav aria-label="Dashboard sections">
          {navigation.map(({ name, vietnamese, short, icon: Icon }) => (
            <button
              key={name}
              type="button"
              aria-label={name}
              onClick={() => go(name)}
              aria-current={section === name ? "page" : undefined}
            >
              <Icon size={18} strokeWidth={1.85} />
              <span className="desktop-label">{vietnamese}</span>
              <span className="mobile-label">{short}</span>
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <MapPin size={18} />
          <div>
            <strong>Thành phố Đà Nẵng</strong>
            <span>Múi giờ Đông Dương · ICT (UTC+7)</span>
          </div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="mobile-brand"><Brand /></div>
          <div className="breadcrumbs">
            <span>FloodInsight</span>
            <span>/</span>
            <strong>{currentNav?.vietnamese ?? section}</strong>
          </div>
          <div className="top-actions">
            <StatePill status={status.error ? "unavailable" : status.data?.status ?? "Checking"} />
            <button
              className="icon-button"
              type="button"
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              title={theme === "dark" ? "Chuyển chế độ Sáng" : "Chuyển chế độ Tối"}
              onClick={() => {
                localStorage.setItem("floodinsight-theme", theme === "dark" ? "light" : "dark");
                window.dispatchEvent(new Event("floodinsight-theme"));
              }}
            >
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button
              className="icon-button"
              type="button"
              aria-label="Refresh dashboard data"
              title="Làm mới dữ liệu"
              onClick={() => { void queryClient.invalidateQueries(); }}
            >
              <RefreshCw size={17} />
            </button>
          </div>
        </header>

        <main className="dashboard-main" id="main">
          {section === "Overview" ? (
            <header className="hero">
              <div className="hero-content">
                <p className="hero-location">
                  <MapPin size={13} /> TP. ĐÀ NẴNG • QUAN TRẮC ĐÔ THỊ THÔNG MINH
                </p>
                <h1 aria-label="Environmental overview">Nền tảng Phân tích & Cảnh báo Ngập lụt Đô thị</h1>
                <p>
                  Hệ thống tích hợp dữ liệu khí tượng vệ tinh Open-Meteo, hải văn và kho dữ liệu chuỗi thời gian,
                  ứng dụng các thuật toán Khai phá dữ liệu (K-Means, Hồi quy, Phân loại) nhằm dự báo và giám sát nguy cơ ngập úng.
                </p>
                <div className="hero-actions">
                  <button type="button" className="button primary" onClick={() => go("Da Nang Map")}>
                    Mở Bản đồ Ngập lụt <ArrowUpRight size={16} />
                  </button>
                  <button type="button" className="button secondary" onClick={() => go("Machine Learning")}>
                    Xem Mô hình AI & Phân cụm <Sparkles size={15} />
                  </button>
                </div>
              </div>
              <a
                className="photo-credit"
                href="https://commons.wikimedia.org/wiki/File:Da_Nang_Night_Panorama_01.jpg"
                target="_blank"
                rel="noreferrer"
                title="Da Nang Night Panorama 01 by Dragfyre, CC BY-SA 3.0"
              >
                Ảnh: Dragfyre · CC BY-SA 3.0
              </a>
            </header>
          ) : (
            <header className="section-heading">
              <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                <h1>{currentNav?.vietnamese ?? section}</h1>
                <span className="pill neutral">{currentNav?.name}</span>
              </div>
              <p>{currentNav?.detail}</p>
            </header>
          )}

          {/* Banner Cảnh báo ngập lụt động */}
          <FloodAlertBanner weather={weather.data ?? []} />

          {/* Bộ lọc thời gian & điểm trạm */}
          {section !== "Data Management" && (
            <form className="filter-bar panel" onSubmit={apply}>
              <div className="filter-field location-field">
                <label htmlFor="point">
                  <MapPin size={14} /> Điểm trạm quan trắc
                </label>
                <select
                  id="point"
                  aria-label="Sampling point"
                  value={selected}
                  onChange={(event) => chooseLocation(event.target.value)}
                  disabled={!points.length}
                >
                  {!points.length && (
                    <option value="">
                      {locations.isPending || weather.isPending ? "Đang tải danh sách..." : "Không có trạm"}
                    </option>
                  )}
                  {points.map((point) => (
                    <option key={point.code} value={point.code}>
                      {point.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="filter-field">
                <label htmlFor="start">
                  <CalendarDays size={14} /> Từ ngày
                </label>
                <input
                  id="start"
                  aria-label="From"
                  type="date"
                  required
                  value={inputRange.start_date}
                  min="1900-01-01"
                  max="2200-12-30"
                  onChange={(event) => setDraft({ ...inputRange, start_date: event.target.value })}
                />
              </div>

              <div className="filter-field">
                <label htmlFor="end">Đến ngày</label>
                <input
                  id="end"
                  aria-label="To"
                  type="date"
                  required
                  value={inputRange.end_date}
                  min="1900-01-01"
                  max="2200-12-30"
                  onChange={(event) => setDraft({ ...inputRange, end_date: event.target.value })}
                />
              </div>

              <div className="filter-submit-wrap" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                <button className="button primary" type="submit" aria-label="Apply dates" style={{ width: "100%" }}>
                  Áp dụng lọc
                </button>
              </div>

              {/* Nút Preset chọn nhanh */}
              <div className="preset-bar">
                <span className="preset-label">Chọn nhanh:</span>
                <button
                  type="button"
                  className="button secondary preset-btn"
                  onClick={() => setPreset("2026-09-01", "2026-11-12")}
                >
                  Mùa mưa 2026 (Mới nhất)
                </button>
                <button
                  type="button"
                  className="button secondary preset-btn"
                  onClick={() => setPreset("2024-01-01", "2024-06-30")}
                >
                  Tập huấn luyện (2024)
                </button>
                <button
                  type="button"
                  className="button secondary preset-btn"
                  onClick={() => setPreset("2024-01-01", "2026-11-12")}
                >
                  Toàn bộ lịch sử (34.200 giờ)
                </button>
              </div>

              {filterError && <p role="alert" className="filter-error">{filterError}</p>}
            </form>
          )}

          {locations.error && !points.length && section !== "Data Management" && (
            <QueryError error={locations.error} retry={() => void locations.refetch()} />
          )}

          {section === "Overview" && (
            <Overview
              scope={scope}
              points={points}
              weather={weather.data ?? []}
              weatherLoading={weather.isPending}
              weatherError={Boolean(weather.error)}
              theme={theme}
              onSelect={chooseLocation}
              openMap={() => go("Da Nang Map")}
            />
          )}

          {section === "Rainfall Analytics" && (
            <Analytics scope={scope} theme={theme} coverage={coverage} />
          )}

          {section === "Machine Learning" && (
            <MachineLearning
              scope={scope}
              filterForecasts={Boolean(range)}
              locations={points}
              theme={theme}
            />
          )}

          {section === "Da Nang Map" && (
            <MapSection
              scope={scope}
              theme={theme}
              points={points}
              weather={weather.data ?? []}
              onSelect={chooseLocation}
            />
          )}

          {section === "Data Management" && <DataManagement locations={points} />}

          <footer className="main-footer">
            <span>FloodInsight Da Nang • Hệ thống Tích hợp & Khai phá dữ liệu Lượng mưa Đô thị</span>
            <span>Nguồn: Open-Meteo • Copernicus ERA5 • RainViewer Radar • OpenStreetMap</span>
          </footer>
        </main>
      </div>
    </div>
  );
}

export default function Dashboard({ initialRange }: { initialRange: DateRange }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (attempt, error) => attempt < 1 && (!(error instanceof ApiError) || error.status >= 500),
      },
    },
  }));

  return (
    <QueryClientProvider client={client}>
      <DashboardBody initialRange={initialRange} />
    </QueryClientProvider>
  );
}
