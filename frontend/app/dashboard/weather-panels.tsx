"use client";

import { useText } from "./language";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowUpRight, Clock3, CloudRain, Droplets, MapPin, Thermometer } from "lucide-react";
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
  rainfall_vs_humidity: ["Rainfall vs. humidity", "Paired hourly values"],
  rainfall_vs_temperature: ["Rainfall vs. temperature", "Paired hourly values"],
  rainfall_histogram: ["Rainfall distribution", "Measured hours per rainfall bin"],
  monthly_trend: ["Monthly rainfall trend", "Linear fit across complete months"],
  monthly_seasonality: ["Seasonal rainfall", "Mean total by month of year"],
  correlation: ["Weather correlations", "Pairwise Pearson coefficients"],
} as const;

export function RainfallPanel({ scope, theme, compact = false }: { scope: Scope; theme: Theme; compact?: boolean }) {
  const t = useText();
  const [period, setPeriod] = useState<Period>("daily");
  const query = useCollection<Rain>("rainfall/" + period, { ...scope, source }, Boolean(scope.location));
  const coverage = useData<RainfallCoverage[]>("rainfall/coverage", { source });
  const hasArchive = coverage.data?.some((row) => row.location === scope.location);
  return <Panel title={compact ? t("Rainfall history") : t("Rainfall over time")}
    subtitle={t("Historical ERA5 reanalysis · ICT")} action={<div className="segmented" aria-label={t("Rainfall frequency")}>
      {periods.map((item) => <button key={item} type="button" aria-pressed={item === period}
        onClick={() => setPeriod(item)}>{t(item)}</button>)}
    </div>}>
    {!scope.location ? <Empty title={t("Select a sampling point")} detail={t("Rainfall history loads when a location is available.")} />
      : <Resource query={query} empty={hasArchive === false
        ? <Empty title={t("No historical rainfall collected")} detail={t("The ERA5 archive has no curated data for this sampling point.")} />
        : <Empty title={t("No rainfall for selected dates")} detail={t("Choose dates with warehouse coverage.")} />}>
        {(rows) => rows.some((r) => r.rainfall_total_mm !== null) ?
        <><Chart theme={theme} label={t("Rainfall over time")} option={rainfallOption(rows, scope, period, t)} compact={compact} />
          {rows.some((row) => row.rainfall_hours < row.expected_hours) &&
            <p className="chart-note">{t("Some periods have partial rainfall coverage.")}</p>}</>
        : <Empty title={t("No rainfall values")} detail={t("This selection contains missing rainfall readings.")} />}</Resource>}
  </Panel>;
}

function Metric({ title, value, unit, subtitle, icon, tone, loading }: {
  title: string; value: string; unit?: string; subtitle: string; icon: ReactNode; tone: string; loading: boolean;
}) {
  const t = useText();
  return <article className="metric panel">
    <span className={"metric-icon " + tone}>{icon}</span>
    <span className="metric-label">{title}</span>
    {loading ? <span className="metric-placeholder" aria-label={t("Loading")} /> :
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
  const t = useText();
  const rain = useCollection<Rain>("rainfall/daily", { ...scope, source }, Boolean(scope.location));
  const status = useData<Status>("system/status", undefined, true, 45_000);
  const model = weather.find((entry) => entry.location_code === scope.location);
  const captured = model?.received_at;
  const latest = useMemo(() => latestRain(rain.data ?? []), [rain.data]);
  const measured = (rain.data ?? []).filter((row) => row.rainfall_total_mm !== null);
  const total = measured.length ? measured.reduce((sum, row) => sum + (row.rainfall_total_mm ?? 0), 0) : null;
  const loading = Boolean(scope.location) && rain.isPending;
  return <>
    <div className="metrics-grid grid">
      <Metric title={t("Total rainfall")} value={displayNumber(total)} unit="mm" loading={loading}
        subtitle={rain.error ? t("Rainfall unavailable") : `${measured.length} ${t("days with rainfall data")} · ERA5`} icon={<CloudRain size={19} />} tone="teal" />
      <Metric title={t("Current temperature")} value={displayNumber(model?.payload.values.temperature_2m)} unit="°C"
        subtitle={weatherError ? t("Weather feed unavailable") : t("Open-Meteo modeled current")} icon={<Thermometer size={19} />} tone="amber" loading={weatherLoading} />
      <Metric title={t("Relative humidity")} value={displayNumber(model?.payload.values.relative_humidity_2m)} unit="%"
        subtitle={weatherError ? t("Weather feed unavailable") : t("Open-Meteo modeled current")} icon={<Droplets size={19} />} tone="blue" loading={weatherLoading} />
      <Metric title={t("Last weather receipt")} value={localTime(captured)} loading={weatherLoading}
        subtitle={captured ? t("Latest stored snapshot · ICT") : t("Awaiting weather data")} icon={<Clock3 size={19} />} tone="purple" />
    </div>
    <div className="overview-grid grid">
      <RainfallPanel scope={scope} theme={theme} />
      <Panel title={t("Monitoring network")} subtitle={t("Da Nang sampling points")}
        action={<button className="icon-button" onClick={openMap} aria-label={t("Open Da Nang map")}><ArrowUpRight size={18} /></button>}>
        <StationMap compact points={points} selected={scope.location} onSelect={onSelect} latest={latest} weather={weather} />
        <div className="mini-map-footer"><MapPin size={15} /> {points.length} {t(points.length === 1 ? "available sampling point" : "available sampling points")}
          <button type="button" className="text-button" onClick={openMap}>{t("Explore map")} <ArrowUpRight size={14} /></button></div>
      </Panel>
    </div>
    <Panel title={t("System status")} subtitle={t("Gateway, warehouse, and processing services")} action={<Activity size={20} className="accent" />}>
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
  const t = useText();
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
    <Panel title={t("Statistical patterns")} subtitle={t("Historical rainfall and hourly weather relationships")}
      action={<button className="button primary" disabled={!available || generate.isPending} onClick={() => generate.mutate(params)}>
        {generate.isPending ? t("Generating…") : t("Generate patterns")}</button>}>
      {generate.error && <QueryError error={generate.error} retry={() => generate.mutate(params)} />}
      {coverage.error ? <QueryError error={coverage.error} retry={() => void coverage.refetch()} /> :
        coverage.isPending ? <Loading /> : !available ? <Empty title={t("Historical rainfall has not been loaded")}
          detail={t("Run the archive backfill and warehouse ETL for this sampling point to enable ERA5 patterns.")} /> :
        <Resource query={patterns} empty={<Empty title={t("No saved patterns")}
          detail={t("Generate patterns for this location and date range.")} />}>
          {(value) => <div className="pattern-grid grid">{Object.entries(chartTitles).map(([name, [title, subtitle]]) => {
            const pattern = value.find((item) => item.name === name);
            return <Panel key={name} title={t(title)} subtitle={t(subtitle)}>
              {pattern?.status === "ready" ? <Chart option={pattern.option} label={t(title)} theme={theme} />
                : <Empty title={t("Insufficient data")} detail={t("The selected range has too few usable measurements.")} />}
            </Panel>;
          })}</div>}
        </Resource>}
    </Panel>
  </>;
}

export function MapSection({ scope, theme, points, weather, onSelect }: AreaProps) {
  const t = useText();
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
      <Panel title={t("Da Nang sampling map")} subtitle={t("Latest daily rainfall within the selected date range")}
        action={<label className="checkbox"><input type="checkbox" checked={onlySelected}
          onChange={(event) => setOnlySelected(event.target.checked)} />{t("Selected point only")}</label>}>
        <StationMap points={visible} selected={scope.location} onSelect={onSelect} latest={latest} weather={weather} />
        <div className="map-legend" aria-label={t("Daily rainfall intensity legend")}>
          {[["#8fa2b4", t("No data")], ["#30baad", "< 10 mm"], ["#f3bf62", "10–<25 mm"], ["#f47d82", "≥ 25 mm"]]
            .map(([color, label]) => <span key={label}><i style={{ background: color }} />{label}</span>)}
        </div>
        {query.error && <QueryError error={query.error} retry={() => void query.refetch()} />}
      </Panel>
      <Panel title={t("Sampling points")} subtitle={t("Select a point to inspect its weather")}>
        {points.length ? <div className="station-list">{points.map((point) =>
          <button key={point.code} type="button" aria-pressed={point.code === scope.location} onClick={() => onSelect(point.code)}>
            <MapPin size={16} /><span>{point.name}</span><span>{displayNumber(latest[point.code]?.rainfall_total_mm)} mm</span>
          </button>)}</div> : <Empty title={t("No sampling points available")} detail={t("Locations appear after ingestion or historical ETL.")} />}
        {selected && <div className="station-detail">
          <strong>{selected.name}</strong>
          <p>{t("Modeled current ·")} {localTime(selectedWeather?.valid_at)} ICT</p>
          <dl><div><dt>{t("Temperature")}</dt><dd>{displayNumber(selectedWeather?.payload.values.temperature_2m)} °C</dd></div>
            <div><dt>{t("Humidity")}</dt><dd>{displayNumber(selectedWeather?.payload.values.relative_humidity_2m)} %</dd></div>
            <div><dt>{t("Wind speed")}</dt><dd>{displayNumber(selectedWeather?.payload.values.wind_speed_10m)} m/s</dd></div>
            <div><dt>{t("Precipitation")}</dt><dd>{displayNumber(selectedWeather?.payload.values.precipitation)} mm</dd></div></dl>
          {selectedWeather?.payload.interval_seconds && <p>{t("Precipitation interval")} {selectedWeather.payload.interval_seconds / 60} min</p>}
        </div>}
      </Panel>
    </div>
    <RainfallPanel scope={scope} theme={theme} compact />
  </>;
}

