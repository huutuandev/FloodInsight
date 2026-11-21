"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowUpRight, Clock3, CloudRain, Droplets, MapPin, ShieldAlert, Sprout, Thermometer, Waves } from "lucide-react";
import type { ReactNode } from "react";
import { Chart } from "./chart";
import {
  displayNumber, localTime, request, source, useCollection, useData,
  type Location, type Pattern, type Rain, type RainfallCoverage, type Scope, type Status, type Weather,
} from "./data";
import { latestRain, periods, rainfallOption, type Period } from "./rainfall";
import { Empty, Loading, Panel, QueryError, Resource, StatePill } from "./ui";
import type { Markers } from "./station-map";

type Theme = "dark" | "light";
const StationMap = dynamic<Markers>(() => import("./station-map"), {
  ssr: false, loading: () => <Loading />,
});

const chartTitles = {
  rainfall_vs_humidity: ["Tương quan Mưa & Độ ẩm", "Giá trị kết cặp theo giờ"],
  rainfall_vs_temperature: ["Tương quan Mưa & Nhiệt độ", "Giá trị kết cặp theo giờ"],
  rainfall_histogram: ["Phân bố lượng mưa", "Số giờ đo được theo phân khoảng lượng mưa"],
  monthly_trend: ["Xu hướng lượng mưa tháng", "Đường khớp tuyến tính qua các tháng"],
  monthly_seasonality: ["Tính mùa vụ lượng mưa", "Lượng mưa trung bình theo các tháng trong năm"],
  correlation: ["Ma trận tương quan khí tượng", "Hệ số tương quan Pearson giữa các biến"],
} as const;

export function RainfallPanel({ scope, theme, compact = false }: { scope: Scope; theme: Theme; compact?: boolean }) {
  const [period, setPeriod] = useState<Period>("daily");
  const query = useCollection<Rain>("rainfall/" + period, { ...scope, source }, Boolean(scope.location));
  return <Panel title={compact ? "Lịch sử lượng mưa" : "Diễn biến lượng mưa theo thời gian"}
    subtitle="Chuỗi thời gian tái phân tích ERA5 · Giờ ICT (UTC+7)" action={<div className="segmented" aria-label="Rainfall frequency">
      {periods.map((item) => <button key={item} type="button" aria-pressed={item === period}
        onClick={() => setPeriod(item)}>{item === "daily" ? "Theo ngày" : item === "weekly" ? "Theo tuần" : "Theo tháng"}</button>)}
    </div>}>
    {!scope.location ? <Empty title="Vui lòng chọn trạm quan trắc" detail="Dữ liệu lượng mưa sẽ hiển thị khi bạn chọn trạm trên bản đồ." />
      : <Resource query={query}>{(rows) => rows.some((r) => r.rainfall_total_mm !== null) ?
        <><Chart theme={theme} label={period + " rainfall"} option={rainfallOption(rows, scope, period)} compact={compact} />
          {rows.some((row) => row.rainfall_hours < row.expected_hours) &&
            <p className="chart-note">Một số mốc thời gian có độ bao phủ dữ liệu một phần.</p>}</>
        : <Empty title="Không có dữ liệu đo đạc" detail="Khoảng thời gian này chưa có bản ghi lượng mưa." />}</Resource>}
  </Panel>;
}

function Metric({ title, value, unit, subtitle, icon, tone, loading }: {
  title: string; value: string; unit?: string; subtitle: string; icon: ReactNode; tone: string; loading: boolean;
}) {
  return <article className="metric panel">
    <span className={"metric-icon " + tone}>{icon}</span>
    <span className="metric-label">{title}</span>
    {loading ? <span className="metric-placeholder" aria-label="Loading" /> :
      <strong>{value}{unit && value !== "—" ? <small> {unit}</small> : null}</strong>}
    <span className="metric-note">{subtitle}</span>
  </article>;
}

type AreaProps = {
  scope: Scope; theme: Theme; points: Location[]; weather: Weather[];
  onSelect: (code: string) => void;
};

export function Overview({ scope, theme, points, weather, onSelect, openMap, weatherLoading, weatherError }: AreaProps & {
  openMap: () => void; weatherLoading: boolean; weatherError: boolean;
}) {
  const rain = useCollection<Rain>("rainfall/daily", { ...scope, source }, Boolean(scope.location));
  const status = useData<Status>("system/status", undefined, true, 45_000);
  const model = weather.find((entry) => entry.location_code === scope.location);
  const captured = model?.received_at;
  const latest = useMemo(() => latestRain(rain.data ?? []), [rain.data]);
  const measured = (rain.data ?? []).filter((row) => row.rainfall_total_mm !== null);
  const total = measured.length ? measured.reduce((sum, row) => sum + (row.rainfall_total_mm ?? 0), 0) : null;
  const loading = Boolean(scope.location) && rain.isPending;

  // Open-Meteo Marine API: Vịnh Đà Nẵng (16.075N, 108.224E) - Free & No Key
  const marine = useQuery({
    queryKey: ["open-meteo-marine-danang"],
    staleTime: 10 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const res = await fetch(
        "https://marine-api.open-meteo.com/v1/marine?latitude=16.0748&longitude=108.224&current=wave_height,wave_direction,wave_period&timezone=Asia%2FBangkok",
        { signal }
      );
      if (!res.ok) throw new Error("Marine API unavailable");
      return await res.json();
    },
  });

  // Open-Meteo Soil Moisture API: Độ ẩm đất tầng mặt (0-1cm) - Free & No Key
  const soil = useQuery({
    queryKey: ["open-meteo-soil-danang", scope.location],
    staleTime: 10 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const loc = points.find((p) => p.code === scope.location) ?? points[0] ?? { latitude: 16.047, longitude: 108.205 };
      const res = await fetch(
        `https://api.open-meteo.com/v1/forecast?latitude=${loc.latitude}&longitude=${loc.longitude}&current=soil_moisture_0_to_1cm&timezone=Asia%2FBangkok`,
        { signal }
      );
      if (!res.ok) throw new Error("Soil moisture API unavailable");
      return await res.json();
    },
  });

  const waveHeight = marine.data?.current?.wave_height as number | undefined;
  const wavePeriod = marine.data?.current?.wave_period as number | undefined;
  const soilMoisture = soil.data?.current?.soil_moisture_0_to_1cm as number | undefined;

  // Compound Flood Risk Index (0 - 100) calculated from Precipitation + Soil Moisture + Wave/Tide
  const currentRain = model?.payload.values.precipitation ?? 0;
  const soilRatio = soilMoisture != null ? Math.min(1, soilMoisture / 0.5) : 0.4;
  const waveRatio = waveHeight != null ? Math.min(1, waveHeight / 2.5) : 0.3;
  const rainRatio = Math.min(1, currentRain / 50);

  const compoundScore = Math.round((rainRatio * 50) + (soilRatio * 30) + (waveRatio * 20));
  const compoundStatus = compoundScore >= 70
    ? { level: "Cấp 3: NGUY CƠ RẤT CAO", tone: "danger", desc: "Mưa lớn kết hợp đất bão hòa & sóng biển dâng cao. Nguy cơ ngập úng nghiêm trọng." }
    : compoundScore >= 45
    ? { level: "Cấp 2: NGUY CƠ CAO", tone: "warn", desc: "Độ ẩm đất cao và sóng biển gây cản trở thoát nước tại các cửa sông." }
    : compoundScore >= 25
    ? { level: "Cấp 1: CẦN THEO DÕI", tone: "neutral", desc: "Điều kiện thủy văn ổn định, dòng chảy tiêu thoát nước bình thường." }
    : { level: "Cấp 0: AN TOÀN", tone: "good", desc: "Đất có khả năng thẩm thấu tốt, mực nước biển ven bờ ổn định." };

  return <>
    {/* Hàng chỉ số khí tượng & thủy văn mở rộng */}
    <div className="metrics-grid grid">
      <Metric title="Tổng lượng mưa lọc" value={displayNumber(total)} unit="mm" loading={loading}
        subtitle={rain.error ? "Chưa có dữ liệu" : `${measured.length} ngày ghi nhận · ERA5`} icon={<CloudRain size={19} />} tone="teal" />
      <Metric title="Nhiệt độ hiện tại" value={displayNumber(model?.payload.values.temperature_2m)} unit="°C"
        subtitle={weatherError ? "Mất kết nối thời tiết" : "Mô hình Open-Meteo tức thời"} icon={<Thermometer size={19} />} tone="amber" loading={weatherLoading} />
      <Metric title="Độ ẩm không khí" value={displayNumber(model?.payload.values.relative_humidity_2m)} unit="%"
        subtitle={weatherError ? "Mất kết nối thời tiết" : "Độ ẩm tương đối tầng 2m"} icon={<Droplets size={19} />} tone="blue" loading={weatherLoading} />
      <Metric title="Sóng biển Vịnh Đà Nẵng" value={waveHeight != null ? waveHeight.toFixed(2) : "—"} unit="m"
        subtitle={wavePeriod ? `Chu kỳ sóng: ${wavePeriod}s · Open-Meteo Marine` : "Open-Meteo Marine (Ven vịnh)"} icon={<Waves size={19} />} tone="cyan" loading={marine.isPending} />
      <Metric title="Độ ẩm tầng đất mặt" value={soilMoisture != null ? soilMoisture.toFixed(3) : "—"} unit="m³/m³"
        subtitle={soilMoisture != null && soilMoisture > 0.4 ? "Đất bão hòa nước cao" : "Tầng đất mặt 0-1cm"} icon={<Sprout size={19} />} tone="teal" loading={soil.isPending} />
      <Metric title="Cập nhật gần nhất" value={localTime(captured)} loading={weatherLoading}
        subtitle={captured ? "Snapshot lưu trữ · Giờ ICT" : "Đang chờ dữ liệu mới"} icon={<Clock3 size={19} />} tone="purple" />
    </div>

    {/* Panel Đánh giá Nguy cơ Ngập lụt Đa yếu tố (Compound Flood Hazard) */}
    <Panel
      title="Đánh giá Nguy cơ Ngập Lụt Đô thị Đa Yếu Tố (Compound Flood Index)"
      subtitle="Tích hợp đồng thời: Lượng mưa cục bộ + Độ ẩm đất tầng mặt + Sóng triều dâng Vịnh Đà Nẵng"
      action={<span className={`pill ${compoundStatus.tone}`}>{compoundStatus.level}</span>}
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px", marginTop: "8px" }}>
        <div style={{ padding: "14px", borderRadius: "10px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--stroke)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
            <span style={{ fontSize: "12px", color: "var(--muted)" }}>Lượng mưa đo đạc</span>
            <strong style={{ color: "#38bdf8" }}>{displayNumber(currentRain)} mm/h</strong>
          </div>
          <div style={{ background: "rgba(255,255,255,0.08)", height: "6px", borderRadius: "3px", overflow: "hidden" }}>
            <div style={{ width: `${rainRatio * 100}%`, height: "100%", background: "#38bdf8" }} />
          </div>
          <span style={{ fontSize: "10.5px", color: "var(--faint)", display: "block", marginTop: "4px" }}>Yếu tố kích hoạt ngập lụt</span>
        </div>

        <div style={{ padding: "14px", borderRadius: "10px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--stroke)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
            <span style={{ fontSize: "12px", color: "var(--muted)" }}>Độ bão hòa nước đất</span>
            <strong style={{ color: "#2dd4bf" }}>{soilMoisture != null ? `${(soilRatio * 100).toFixed(0)}%` : "—"}</strong>
          </div>
          <div style={{ background: "rgba(255,255,255,0.08)", height: "6px", borderRadius: "3px", overflow: "hidden" }}>
            <div style={{ width: `${soilRatio * 100}%`, height: "100%", background: "#2dd4bf" }} />
          </div>
          <span style={{ fontSize: "10.5px", color: "var(--faint)", display: "block", marginTop: "4px" }}>Quyết định lượng nước ngấm hay chảy tràn</span>
        </div>

        <div style={{ padding: "14px", borderRadius: "10px", background: "rgba(255,255,255,0.02)", border: "1px solid var(--stroke)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
            <span style={{ fontSize: "12px", color: "var(--muted)" }}>Sóng & Triều ven bờ</span>
            <strong style={{ color: "#facc15" }}>{waveHeight != null ? `${waveHeight.toFixed(2)} m` : "—"}</strong>
          </div>
          <div style={{ background: "rgba(255,255,255,0.08)", height: "6px", borderRadius: "3px", overflow: "hidden" }}>
            <div style={{ width: `${waveRatio * 100}%`, height: "100%", background: "#facc15" }} />
          </div>
          <span style={{ fontSize: "10.5px", color: "var(--faint)", display: "block", marginTop: "4px" }}>Cản trở năng lực thoát nước cửa sông</span>
        </div>

        <div style={{ padding: "14px", borderRadius: "10px", background: "rgba(255,255,255,0.04)", border: "1px solid var(--accent-border)", display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
            <span style={{ fontSize: "24px", fontWeight: "bold", color: "var(--accent)" }}>{compoundScore}</span>
            <span style={{ fontSize: "12px", color: "var(--muted)" }}>/ 100 điểm chỉ số CFI</span>
          </div>
          <p style={{ margin: "4px 0 0", fontSize: "11.5px", color: "var(--text)" }}>{compoundStatus.desc}</p>
        </div>
      </div>
    </Panel>

    <div className="overview-grid grid">
      <RainfallPanel scope={scope} theme={theme} />
      <Panel title="Mạng lưới quan trắc Đà Nẵng" subtitle="5 trạm trọng điểm & Radar mây mưa thời gian thực"
        action={<button className="icon-button" onClick={openMap} aria-label="Mở bản đồ Đà Nẵng"><ArrowUpRight size={18} /></button>}>
        <StationMap compact points={points} selected={scope.location} onSelect={onSelect} latest={latest} weather={weather} />
        <div className="mini-map-footer">
          <MapPin size={15} /> {points.length} trạm quan trắc đô thị
          <button type="button" className="text-button" onClick={openMap}>Mở rộng bản đồ <ArrowUpRight size={14} /></button>
        </div>
      </Panel>
    </div>

    <Panel title="Tình trạng hệ thống vi dịch vụ" subtitle="Trạng thái kết nối Gateway, Warehouse ETL và các cổng phân tích" action={<Activity size={20} className="accent" />}>
      <Resource query={status}>{(value) => <div className="service-grid">
        {Object.entries(value.services).map(([key, check]) => <div key={key}>
          <span>{key === "postgres" ? "PostgreSQL (Kho dữ liệu)" : key}</span><StatePill status={check.status} />
        </div>)}
      </div>}</Resource>
    </Panel>
  </>;
}

export function Analytics({ scope, theme, coverage }: Pick<AreaProps, "scope" | "theme"> & {
  coverage: ReturnType<typeof useData<RainfallCoverage[]>>;
}) {
  const queryClient = useQueryClient();
  const params = { ...scope, source };
  const available = coverage.data?.some((row) => row.location === scope.location);
  const patterns = useData<Pattern[]>("analytics", params, Boolean(available));
  const generate = useMutation({
    mutationFn: async (selection: typeof params) => (await request<Pattern[]>("analytics/generate", undefined, undefined, selection)).data,
    onSuccess: (data, selection) => queryClient.setQueryData(["analytics", selection], data),
  });
  return <>
    <RainfallPanel scope={scope} theme={theme} />
    <Panel title="Mô hình thống kê & Tương quan khí tượng" subtitle="Quy luật lượng mưa lịch sử và mối liên hệ giữa các biến thời tiết"
      action={<button className="button primary" disabled={!available || generate.isPending} onClick={() => generate.mutate(params)}>
        {generate.isPending ? "Đang xử lý…" : "Phân tích quy luật"}</button>}>
      {generate.error && <QueryError error={generate.error} retry={() => generate.mutate(params)} />}
      {coverage.error ? <QueryError error={coverage.error} retry={() => void coverage.refetch()} /> :
        coverage.isPending ? <Loading /> : !available ? <Empty title="Chưa có dữ liệu lượng mưa lịch sử"
          detail="Hãy kích hoạt luồng ETL nạp dữ liệu cho trạm này để phân tích quy luật ERA5." /> :
        <Resource query={patterns} empty={<Empty title="Chưa có đồ thị quy luật đã lưu"
          detail="Bấm nút 'Phân tích quy luật' ở góc trên để chạy trích xuất đặc trưng." />}>
          {(value) => <div className="pattern-grid grid">{Object.entries(chartTitles).map(([name, [title, subtitle]]) => {
            const pattern = value.find((item) => item.name === name);
            return <Panel key={name} title={title} subtitle={subtitle}>
              {pattern?.status === "ready" ? <Chart option={pattern.option} label={title} theme={theme} />
                : <Empty title="Dữ liệu chưa đủ" detail="Khoảng ngày chọn có quá ít mốc thời gian hợp lệ để vẽ tương quan." />}
            </Panel>;
          })}</div>}
        </Resource>}
    </Panel>
  </>;
}

export function MapSection({ scope, theme, points, weather, onSelect }: AreaProps) {
  const [onlySelected, setOnlySelected] = useState(false);
  const visible = useMemo(() => onlySelected ? points.filter((p) => p.code === scope.location) : points,
    [onlySelected, points, scope.location]);
  const query = useCollection<Rain>("rainfall/daily", {
    start_date: scope.start_date, end_date: scope.end_date, source, location: onlySelected ? scope.location : undefined,
  });
  const latest = useMemo(() => latestRain(query.data ?? []), [query.data]);
  const selected = points.find((point) => point.code === scope.location);
  const selectedWeather = weather.find((item) => item.location_code === scope.location);

  return <>
    <div className="map-layout grid">
      <Panel
        title="Bản đồ không gian & Radar mây mưa thời gian thực"
        subtitle="Hiển thị lượng mưa tích lũy 24h kết hợp lớp phủ ảnh quét Radar RainViewer trực tiếp"
        action={<label className="checkbox"><input type="checkbox" checked={onlySelected}
          onChange={(event) => setOnlySelected(event.target.checked)} />Chỉ xem trạm đã chọn</label>}
      >
        <StationMap points={visible} selected={scope.location} onSelect={onSelect} latest={latest} weather={weather} />
        <div className="map-legend" aria-label="Chú giải lượng mưa">
          {[["#8fa2b4", "Chưa có dữ liệu"], ["#2dd4bf", "< 10 mm (Mưa nhẹ)"], ["#f59e0b", "10–25 mm (Mưa vừa)"], ["#ef4444", "≥ 25 mm (Mưa to/Ngập)"]]
            .map(([color, label]) => <span key={label}><i style={{ background: color }} />{label}</span>)}
        </div>
        {query.error && <QueryError error={query.error} retry={() => void query.refetch()} />}
      </Panel>

      <Panel title="Danh sách trạm quan trắc" subtitle="Bấm vào từng quận để kiểm tra điều kiện vi khí hậu">
        {points.length ? <div className="station-list">{points.map((point) =>
          <button key={point.code} type="button" aria-pressed={point.code === scope.location} onClick={() => onSelect(point.code)}>
            <MapPin size={16} /><span>{point.name}</span><strong>{displayNumber(latest[point.code]?.rainfall_total_mm)} mm</strong>
          </button>)}</div> : <Empty title="Không tìm thấy trạm quan trắc" detail="Trạm sẽ xuất hiện sau khi luồng thu thập Ingestion chạy." />}
        {selected && <div className="station-detail">
          <strong style={{ color: "#38bdf8", fontSize: "15px" }}>{selected.name} (TP. Đà Nẵng)</strong>
          <p style={{ opacity: 0.8, fontSize: "11px" }}>Snapshot tức thời · {localTime(selectedWeather?.valid_at)} ICT</p>
          <dl>
            <div><dt>Nhiệt độ</dt><dd>{displayNumber(selectedWeather?.payload.values.temperature_2m)} °C</dd></div>
            <div><dt>Độ ẩm tương đối</dt><dd>{displayNumber(selectedWeather?.payload.values.relative_humidity_2m)} %</dd></div>
            <div><dt>Tốc độ gió</dt><dd>{displayNumber(selectedWeather?.payload.values.wind_speed_10m)} m/s</dd></div>
            <div><dt>Lượng mưa tức thời</dt><dd>{displayNumber(selectedWeather?.payload.values.precipitation)} mm</dd></div>
          </dl>
          {selectedWeather?.payload.interval_seconds && <p style={{ fontSize: "11px", color: "var(--faint)", marginTop: "6px" }}>Khoảng cách lấy mẫu: {selectedWeather.payload.interval_seconds / 60} phút</p>}
        </div>}
      </Panel>
    </div>
    <RainfallPanel scope={scope} theme={theme} compact />
  </>;
}
