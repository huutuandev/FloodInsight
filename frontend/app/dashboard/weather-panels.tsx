"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowUpRight, Clock3, CloudRain, Droplets, MapPin, Sprout, Thermometer, Waves } from "lucide-react";
import type { ReactNode } from "react";
import { Chart } from "./chart";
import {
  displayNumber, localTime, request, source, useCollection, useData,
  type Location, type Pattern, type Rain, type RainfallCoverage, type Scope, type Status, type Weather,
} from "./data";
import { latestRain, periods, rainfallOption, type Period } from "./rainfall";
import { Empty, Loading, Panel, QueryError, Resource, StatePill } from "./ui";
import type { FloodReport, Markers } from "./station-map";

type Theme = "dark" | "light";
const StationMap = dynamic<Markers>(() => import("./station-map"), {
  ssr: false, loading: () => <Loading />,
});

const chartTitles = {
  rainfall_vs_humidity: ["Tương quan Mưa & Độ ẩm", "Giá trị kết cặp theo giờ", "Rainfall vs. humidity"],
  rainfall_vs_temperature: ["Tương quan Mưa & Nhiệt độ", "Giá trị kết cặp theo giờ", "Rainfall vs. temperature"],
  rainfall_histogram: ["Phân bố lượng mưa", "Số giờ đo được theo phân khoảng lượng mưa", "Rainfall distribution"],
  monthly_trend: ["Xu hướng lượng mưa tháng", "Đường khớp tuyến tính qua các tháng", "Monthly rainfall trend"],
  monthly_seasonality: ["Tính mùa vụ lượng mưa", "Lượng mưa trung bình theo các tháng trong năm", "Seasonal rainfall"],
  correlation: ["Ma trận tương quan khí tượng", "Hệ số tương quan Pearson giữa các biến", "Weather correlations"],
} as const;

const periodLabels: Record<Period, string> = {
  daily: "Theo ngày",
  weekly: "Theo tuần",
  monthly: "Theo tháng",
};

export function RainfallPanel({ scope, theme, compact = false }: { scope: Scope; theme: Theme; compact?: boolean }) {
  const [period, setPeriod] = useState<Period>("daily");
  const query = useCollection<Rain>("rainfall/" + period, { ...scope, source }, Boolean(scope.location));
  return <Panel
    title={compact ? "Lịch sử lượng mưa" : "Diễn biến lượng mưa theo thời gian"}
    headingLabel={compact ? "Rainfall history" : "Rainfall over time"}
    subtitle="Chuỗi thời gian tái phân tích ERA5 · Giờ ICT (UTC+7)"
    action={<div className="segmented" aria-label="Rainfall frequency">
      {periods.map((item) => <button key={item} type="button" aria-label={item} aria-pressed={item === period}
        onClick={() => setPeriod(item)}>{periodLabels[item]}</button>)}
    </div>}>
    {!scope.location ? <Empty title="Select a sampling point" detail="Dữ liệu lượng mưa sẽ hiển thị khi bạn chọn trạm trên bản đồ." />
      : <Resource query={query}>{(rows) => rows.some((r) => r.rainfall_total_mm !== null) ?
        <><Chart theme={theme} label={period + " rainfall"} option={rainfallOption(rows, scope, period)} compact={compact} />
          {rows.some((row) => row.rainfall_hours < row.expected_hours) &&
            <p className="chart-note">Một số mốc thời gian có độ bao phủ dữ liệu một phần.</p>}</>
        : <Empty title="No records for this selection" detail="Khoảng thời gian này chưa có bản ghi lượng mưa hợp lệ." />}</Resource>}
  </Panel>;
}

function Metric({ title, value, unit, subtitle, icon, tone, loading }: {
  title: string; value: string; unit?: string; subtitle: string; icon: ReactNode; tone: string; loading: boolean;
}) {
  return <article className="metric panel">
    <div className="metric-head">
      <span className="metric-label">{title}</span>
      <span className={"metric-icon " + tone}>{icon}</span>
    </div>
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

  return <>
    <div className="metrics-grid grid">
      <Metric title="Tổng lượng mưa lọc" value={displayNumber(total)} unit="mm" loading={loading}
        subtitle={rain.error ? "Chưa có dữ liệu" : `${measured.length} ngày ghi nhận · ERA5`} icon={<CloudRain size={19} />} tone="blue" />
      <Metric title="Nhiệt độ hiện tại" value={displayNumber(model?.payload.values.temperature_2m)} unit="°C"
        subtitle={weatherError ? "Mất kết nối thời tiết" : "Mô hình Open-Meteo tức thời"} icon={<Thermometer size={19} />} tone="amber" loading={weatherLoading} />
      <Metric title="Độ ẩm không khí" value={displayNumber(model?.payload.values.relative_humidity_2m)} unit="%"
        subtitle={weatherError ? "Mất kết nối thời tiết" : "Độ ẩm tương đối tầng 2m"} icon={<Droplets size={19} />} tone="teal" loading={weatherLoading} />
      <Metric title="Sóng biển Vịnh Đà Nẵng" value={waveHeight != null ? waveHeight.toFixed(2) : "—"} unit="m"
        subtitle={wavePeriod ? `Chu kỳ sóng: ${wavePeriod}s · Marine API` : "Open-Meteo Marine (Ven vịnh)"} icon={<Waves size={19} />} tone="cyan" loading={marine.isPending} />
      <Metric title="Độ ẩm đất mặt (mô hình)" value={soilMoisture != null ? soilMoisture.toFixed(3) : "—"} unit="m³/m³"
        subtitle={soilMoisture != null && soilMoisture > 0.4 ? "Giá trị mô hình cao" : "Open-Meteo · lớp đất 0–1 cm"} icon={<Sprout size={19} />} tone="teal" loading={soil.isPending} />
      <Metric title="Cập nhật gần nhất" value={localTime(captured)} loading={weatherLoading}
        subtitle={captured ? "Snapshot lưu trữ · Giờ ICT" : "Đang chờ dữ liệu mới"} icon={<Clock3 size={19} />} tone="purple" />
    </div>

    <div className="overview-grid grid">
      <RainfallPanel scope={scope} theme={theme} />
      <Panel title="Các điểm lấy mẫu tại Đà Nẵng" headingLabel="Sampling network" subtitle="Mở bản đồ đầy đủ để xem radar mưa"
        action={<button className="icon-button" onClick={openMap} aria-label="Open Da Nang map"><ArrowUpRight size={18} /></button>}>
        <StationMap compact points={points} selected={scope.location} onSelect={onSelect} latest={latest} weather={weather} />
        <div className="mini-map-footer">
          <MapPin size={15} /> {points.length} điểm lấy mẫu
          <button type="button" className="text-button" onClick={openMap}>Mở rộng bản đồ <ArrowUpRight size={14} /></button>
        </div>
      </Panel>
    </div>

    <Panel title="Tình trạng hệ thống vi dịch vụ" headingLabel="System status" subtitle="Trạng thái kết nối API Gateway, Kho dữ liệu ETL và các cụm dịch vụ AI" action={<Activity size={20} className="accent" />}>
      <Resource query={status}>{(value) => <div className="service-grid">
        {Object.entries(value.services).map(([key, check]) => <div key={key}>
          <span>{key === "postgres" ? "PostgreSQL" : key}</span><StatePill status={check.status} />
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
    <Panel title="Mô hình thống kê & Tương quan khí tượng" headingLabel="Statistical patterns" subtitle="Quy luật lượng mưa lịch sử và mối liên hệ giữa các biến thời tiết theo giờ"
      action={<button className="button primary" aria-label="Generate patterns" disabled={!available || generate.isPending} onClick={() => generate.mutate(params)}>
        {generate.isPending ? "Đang tính toán…" : "Phân tích quy luật"}</button>}>
      {generate.error && <QueryError error={generate.error} retry={() => generate.mutate(params)} />}
      {coverage.error ? <QueryError error={coverage.error} retry={() => void coverage.refetch()} /> :
        coverage.isPending ? <Loading /> : !available ? <Empty title="Chưa có dữ liệu lượng mưa lịch sử"
          detail="Hãy chạy tiến trình backfill và ETL kho dữ liệu cho trạm này để kích hoạt phân tích quy luật ERA5." /> :
        <Resource query={patterns} empty={<Empty title="Chưa có đồ thị quy luật đã lưu"
          detail="Bấm nút 'Phân tích quy luật' ở góc trên để trích xuất tương quan cho trạm và khoảng ngày này." />}>
          {(value) => <div className="pattern-grid grid">{Object.entries(chartTitles).map(([name, [title, subtitle, englishLabel]]) => {
            const pattern = value.find((item) => item.name === name);
            return <Panel key={name} title={title} headingLabel={englishLabel} subtitle={subtitle}>
              {pattern?.status === "ready" ? <Chart option={pattern.option} label={englishLabel} theme={theme} />
                : <Empty title="Dữ liệu chưa đủ" detail="Khoảng ngày được chọn có quá ít phép đo hợp lệ để tính tương quan." />}
            </Panel>;
          })}</div>}
        </Resource>}
    </Panel>
  </>;
}

export function MapSection({ scope, theme, points, weather, onSelect }: AreaProps) {
  const [onlySelected, setOnlySelected] = useState(false);
  const [eventId, setEventId] = useState("");
  const archive = useCollection<FloodReport>("flood-reports", { location: scope.location }, Boolean(scope.location));
  const reports = (archive.data ?? []).filter(row => row.event_id === eventId);
  const event = reports[0];
  const mapScope = event ? { ...scope, start_date: event.event_date, end_date: event.event_date } : scope;
  const visible = useMemo(() => onlySelected ? points.filter((p) => p.code === scope.location) : points,
    [onlySelected, points, scope.location]);
  const query = useCollection<Rain>("rainfall/daily", {
    start_date: mapScope.start_date, end_date: mapScope.end_date, source, location: onlySelected ? scope.location : undefined,
  });
  const latest = useMemo(() => latestRain(query.data ?? []), [query.data]);
  const selected = points.find((point) => point.code === scope.location);
  const selectedWeather = weather.find((item) => item.location_code === scope.location);

  return <>
    <div className="map-layout grid">
      <Panel
        title="Bản đồ không gian GIS & Radar mây mưa Đà Nẵng"
        headingLabel="Da Nang sampling map"
        subtitle={event ? `Mưa ERA5 ngày ${event.event_date}. Ký hiệu tím đánh dấu vị trí ghi nhận có tọa độ.` : "Màu điểm theo ngày ERA5 gần nhất trong bộ lọc. RainViewer phát lại ảnh radar khoảng 2 giờ gần nhất."}
        action={<label className="checkbox"><input type="checkbox" aria-label="Selected point only" checked={onlySelected}
          onChange={(event) => setOnlySelected(event.target.checked)} />Chỉ xem trạm đã chọn</label>}
      >
        <label>Đợt ngập lịch sử{" "}
          <select value={event?.event_id ?? ""} onChange={e => setEventId(e.target.value)}>
            <option value="">Theo bộ lọc ngày và radar gần nhất</option>
            {[...new Map((archive.data ?? []).map(r => [r.event_id, r])).values()].map(r =>
              <option key={r.event_id} value={r.event_id}>{r.title}</option>)}
          </select>
        </label>
        {archive.error && <QueryError error={archive.error} retry={() => void archive.refetch()} />}
        {archive.data?.length === 0 && <p>Chưa có báo cáo lịch sử cho điểm đang chọn.</p>}
        {event?.river_context?.map(h => <p key={h.source_url}>Thủy văn cùng ngày · {h.station_or_site} · {h.time_description} · {h.level_m} m so với {h.reference_level}. <a href={h.source_url} target="_blank" rel="noreferrer">Nguồn quan sát</a></p>)}
        {reports.map(r => <p key={r.id}><strong>{r.place}</strong> · {r.status === "flooded" ? "Ghi nhận ngập" : r.status === "confirmed_dry" ? "Đã xác nhận không ngập" : "Chưa rõ"}
          {r.depth_cm == null ? " · Chưa có số đo độ sâu" : ` · ${r.depth_cm} cm`}
          {r.context_note && <> · {r.context_note}</>}
          {r.elevation_m != null && r.elevation_source && <> · <a href={r.elevation_source} target="_blank" rel="noreferrer">Cao độ ô lưới GLO-90: {r.elevation_m} m</a></>}
          {" · "}{r.sources.map(s => <a key={s.url} href={s.url} target="_blank" rel="noreferrer">{s.publisher} </a>)}
          {r.geometry_source && <> · <a href={r.geometry_source} target="_blank" rel="noreferrer">{r.road_geometry ? "Đối chiếu tuyến đường OSM" : "Tọa độ giao lộ"}</a></>}
        </p>)}
        {event && !query.isPending && !query.error && !latest[scope.location] && <p>Kho chưa có lượng mưa ERA5 cho điểm và ngày này.</p>}
        <StationMap points={visible} selected={scope.location} onSelect={onSelect} latest={latest} weather={event ? [] : weather}
          historical={Boolean(event)} reports={reports} />
        <div className="map-legend" aria-label="Daily rainfall intensity legend">
          {[
            ["#94A3B8", "Chưa có dữ liệu"],
            ["#299D70", "< 10 mm · Mưa nhỏ"],
            ["#E9A23B", "10–25 mm · Mưa vừa"],
            ["#E67E22", "25–50 mm · Mưa to"],
            ["#D9534F", "≥ 50 mm · Mưa rất to"],
          ].map(([color, label]) => <span key={label}><i style={{ background: color }} />{label}</span>)}
        </div>
        {query.error && <QueryError error={query.error} retry={() => void query.refetch()} />}
      </Panel>

      <Panel title="Danh sách điểm lấy mẫu" headingLabel="Sampling points" subtitle="Chọn một điểm để xem dữ liệu thời tiết và lượng mưa">
        {points.length ? <div className="station-list">{points.map((point) =>
          <button key={point.code} type="button" aria-pressed={point.code === scope.location} onClick={() => onSelect(point.code)}>
            <MapPin size={16} /><span>{point.name}</span><span>{displayNumber(latest[point.code]?.rainfall_total_mm)} mm</span>
          </button>)}</div> : <Empty title="Không có điểm lấy mẫu" detail="Danh sách điểm sẽ xuất hiện sau khi chạy thu thập hoặc ETL." />}
        {selected && !event && <div className="station-detail">
          <strong style={{ color: "var(--heading)", fontSize: "15px" }}>{selected.name}</strong>
          <p>Dữ liệu mô hình tức thời · {localTime(selectedWeather?.valid_at)} ICT</p>
          <dl>
            <div><dt>Nhiệt độ</dt><dd>{displayNumber(selectedWeather?.payload.values.temperature_2m)} °C</dd></div>
            <div><dt>Độ ẩm tương đối</dt><dd>{displayNumber(selectedWeather?.payload.values.relative_humidity_2m)} %</dd></div>
            <div><dt>Tốc độ gió</dt><dd>{displayNumber(selectedWeather?.payload.values.wind_speed_10m)} m/s</dd></div>
            <div><dt>Lượng mưa tức thời</dt><dd>{displayNumber(selectedWeather?.payload.values.precipitation)} mm</dd></div>
          </dl>
          {selectedWeather?.payload.interval_seconds && <p>Chu kỳ đo mưa: {selectedWeather.payload.interval_seconds / 60} phút</p>}
        </div>}
      </Panel>
    </div>
    <RainfallPanel scope={mapScope} theme={theme} compact />
  </>;
}
