"use client";

import { useLanguage, useText } from "./language";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownUp, MapPin, RefreshCw } from "lucide-react";
import { displayNumber, localTime, request, source, useCollection, useData, type Rain, type Scope, type Weather } from "./data";
import {
  activeAssessment, categories, floodZones, formatProbability, historicalRoads, historicalScenarios, indexHelp, label, mapEvidence, pointCategory, probabilityHelp, riskColors, riskRadius, roadScreening, scenarioFloodWindow,
  type Assessment, type FloodPrediction, type HistoricalScenarioId, type MapHorizon, type PointRisk, type RiskCategory,
} from "./flood-data";
import type { Markers } from "./station-map";
import { Empty, Loading, Panel, QueryError, Resource } from "./ui";
import { RainfallPanel } from "./weather-panels";

const StationMap = dynamic<Markers>(() => import("./station-map"), { ssr: false, loading: () => <Loading /> });
type Theme = "dark" | "light";

export function RiskBadge({ category }: { category: RiskCategory }) {
  const t = useText();
  const color = riskColors[category];
  return <span className="risk-badge" style={{ borderColor: color + "55", backgroundColor: color + "18", color }}>
    <i style={{ backgroundColor: color, color }} />{t(category)}
  </span>;
}

function EvidenceState({ row }: { row?: PointRisk }) {
  const t = useText();
  return <>{!row?.assessment ? t("No stored assessment") : !row.is_current ? t("Latest assessment expired") :
    row.assessment.risk_index == null ? t("Required inputs missing") : label(row.assessment.assessment_status)}</>;
}

function Facts({ assessment }: { assessment: Assessment }) {
  const t = useText();
  const latest = Object.values(assessment.data_freshness ?? {}).map((record) => record.available_at).sort().at(-1);
  return <dl className="flood-facts">
    <div><dt>{t("Issued")}</dt><dd>{localTime(assessment.issued_at)} ICT</dd></div>
    <div><dt>{t("Valid until")}</dt><dd>{localTime(assessment.valid_until)} ICT</dd></div>
    <div><dt>{t("Latest evidence available")}</dt><dd>{latest ? localTime(latest) + " ICT" : t("Unavailable")}</dd></div>
    <div><dt>{t("Method")}</dt><dd>{assessment.method_version}</dd></div>
  </dl>;
}

function useCurrentPredictions() {
  return useData<FloodPrediction[]>("flood-predictions/results", { current: "true", limit: 250 }, true, 60_000);
}

export function FloodOverview({ scope, theme, weather }: {
  scope: Scope; theme: Theme; weather: ReturnType<typeof useData<Weather[]>>;
}) {
  const t = useText();
  const risks = useData<PointRisk[]>("flood-risk/latest", undefined, true, 60_000);
  const predictions = useCurrentPredictions();
  const historical = useCollection<Rain>("rainfall/daily", { ...scope, source }, Boolean(scope.location));
  const rank = (row: PointRisk) => activeAssessment(row)?.risk_index ?? -1;
  return <>
    <Resource query={risks} empty={<Empty title={t("No flood monitoring points")} detail={t("Points appear after they are registered in the warehouse.")} />}>
      {(rows) => {
        const highest = rows.filter((row) => rank(row) >= 0).sort((a, b) => rank(b) - rank(a))[0];
        const selected = rows.find((row) => row.point.code === scope.location);
        const current = activeAssessment(selected);
        const absent = rows.filter((row) => pointCategory(row) === "Insufficient Data").length;
        const measured = (historical.data ?? []).filter((row) => row.rainfall_total_mm != null);
        const total = measured.length ? measured.reduce((sum, row) => sum + row.rainfall_total_mm!, 0) : null;
        return <>
          <div className="flood-overview grid">
            <Panel className="risk-lead" title={t("Highest current forecast risk")} subtitle={t("Flood Risk Index")}>
              {highest?.assessment ? <><strong className="risk-value" title={t(indexHelp)}>{displayNumber(highest.assessment.risk_index)} <small>/ 100</small></strong>
                <div className="risk-meter" aria-hidden="true"><div className="risk-meter-fill" style={{ width: `${Math.min(100, Math.max(0, highest.assessment.risk_index ?? 0))}%` }} /></div>
                <RiskBadge category={pointCategory(highest)} /><p style={{ marginTop: 8, fontWeight: 700, color: "var(--text)" }}>{highest.point.name}</p><Facts assessment={highest.assessment} /></> :
                <><strong className="risk-value">{t("Unavailable")}</strong><RiskBadge category="Insufficient Data" />
                  <p>{t("No current assessment has enough evidence for a score.")}</p></>}
            </Panel>
            <Panel title={t("Monitoring coverage")} subtitle={t("Current assessment categories")}>
              <div className="risk-counts">{categories.map((category) => <div key={category}><RiskBadge category={category} />
                <strong>{rows.filter((row) => pointCategory(row) === category).length}</strong></div>)}</div>
            </Panel>
            <Panel title={t("Validated flood predictions")} subtitle={t("Currently valid calibrated forecasts")}>
              {predictions.error ? <QueryError error={predictions.error} retry={() => void predictions.refetch()} /> :
                predictions.isPending ? <Loading compact /> :
                <><strong className="risk-value">{predictions.data?.length ?? 0}</strong><p title={t(probabilityHelp)}>{t("Available location forecasts")}</p>
                  {predictions.data?.[0] && <p className="metric-note">{t("Issued")} {localTime(predictions.data[0].issued_at)} · {t("Valid until")} {localTime(predictions.data[0].valid_until)} ICT</p>}</>}
            </Panel>
          </div>
          {absent > 0 && <p className="flood-notice" role="status">{absent}/{rows.length} {t("points have missing or expired assessment evidence. Gray indicates unknown risk.")}</p>}
          <Panel title={t("Rainfall context")} subtitle={selected?.point.name}>
            <div className="flood-context grid">
              <div><span>{t("Historical rainfall · selected archive dates")}</span>
                <strong>{historical.isFetching ? t("Loading…") : historical.error ? t("Unavailable") : total == null ? t("Unavailable") : displayNumber(total) + " mm"}</strong>
                <small>{!historical.isFetching && !historical.error && measured.length > 0 ?
                  measured.length + " " + t(measured.length === 1 ? "day with measurements" : "days with measurements") : ""}</small></div>
              <div><span>{t("Rainfall · preceding 24 h")}</span><strong>{current?.observed_rainfall?.rain_prev_24h_mm == null ? t("Unavailable") : displayNumber(current.observed_rainfall.rain_prev_24h_mm) + " mm"}</strong></div>
              {[6, 12, 24].map((hours) => {
                const rain = current?.forecast_rainfall?.[`forecast_rain_next_${hours}h_mm`];
                return <div key={hours}><span>{t("Forecast rain · next")} {hours} h</span>
                  <strong>{rain == null ? t("Unavailable") : displayNumber(rain) + " mm"}</strong></div>;
              })}
            </div>
            {selected?.assessment && <><p className="metric-note"><EvidenceState row={selected} /></p><Facts assessment={selected.assessment} /></>}
          </Panel>
        </>;
      }}
    </Resource>
    <Panel title={t("Current weather")} subtitle={t("Open-Meteo modeled conditions")}>
      <Resource query={weather} empty={<Empty title={t("No weather snapshots collected")} detail={t("Run weather ingestion from Data Management.")} />}>
        {(rows) => {
          const snapshot = rows.find((row) => row.location_code === scope.location);
          if (!snapshot) return <Empty title={t("Current weather unavailable for this point")}
            detail={t("The weather feed has no recent snapshot for this sampling point.")} />;
          const values = snapshot.payload.values;
          return <>
            <div className="flood-context grid">
              <div><span>{t("Temperature")}</span><strong>{values.temperature_2m == null ? t("Unavailable") : displayNumber(values.temperature_2m) + " °C"}</strong></div>
              <div><span>{t("Relative humidity")}</span><strong>{values.relative_humidity_2m == null ? t("Unavailable") : displayNumber(values.relative_humidity_2m) + " %"}</strong></div>
              <div><span>{t("Precipitation")}{snapshot.payload.interval_seconds ? " · " + snapshot.payload.interval_seconds / 60 + " min" : ""}</span>
                <strong>{values.precipitation == null ? t("Unavailable") : displayNumber(values.precipitation) + " mm"}</strong></div>
            </div>
            <p className="metric-note">{t("Valid")} {localTime(snapshot.valid_at)} · {t("Received")} {localTime(snapshot.received_at)} ICT</p>
          </>;
        }}
      </Resource>
    </Panel>
    <RainfallPanel scope={scope} theme={theme} />
  </>;
}

function RiskDetails({ code }: { code: string }) {
  const t = useText();
  const details = useData<PointRisk>("flood-risk/" + encodeURIComponent(code) + "/details", undefined, Boolean(code), 60_000);
  return <Panel title={t("Contributing factors and evidence")}>
    {!code ? <Empty title={t("Select a monitoring point")} detail={t("Choose a row to inspect its latest assessment.")} /> :
      <Resource query={details}>{(row) => row.assessment ? <AssessmentEvidence row={row} assessment={row.assessment} /> :
        <Empty title={t("No stored assessment")} detail={t("Assessment evidence is unavailable for") + " " + row.point.name + "."} />}</Resource>}
  </Panel>;
}

function AssessmentEvidence({ row, assessment }: { row: PointRisk; assessment: Assessment }) {
  const t = useText();
  const language = useLanguage();
  const context = assessment.inundation_detail;
  const actions = assessment.recommended_actions;
  const localized = Array.isArray(actions) ? actions : actions?.[language];
  const category = pointCategory(row);
  const advice = {
    Low: "Monitor rainfall and local updates.",
    Moderate: "Check low-lying routes before travelling.",
    High: "Avoid flooded and low-lying roads and follow local notices.",
    "Very High": "Avoid flooded areas and follow instructions from local authorities.",
    "Insufficient Data": "Check official updates before making travel decisions.",
  }[category];
  const describe = (key: string) => t(label(key));
  const threshold = context?.trigger_thresholds_mm?.["24h_mm"] ?? context?.rainfall_threshold_mm;
  const thresholdsKnown = typeof threshold === "number" && Number.isFinite(threshold);
  const observed = assessment.observed_rainfall?.rain_prev_24h_mm;
  const provenanceDetail = context?.data_provenance;
  const factorExplanation: Record<string, string> = {
    forecast_rainfall: "More forecast rain can increase runoff entering the drainage network.",
    recent_rainfall: "Recent rain can reduce the ground's remaining capacity to absorb water.",
    rainfall_intensity: "An intense hour can exceed local drainage capacity.",
    terrain: "Low elevation and built-up surfaces can favor runoff or water accumulation.",
    soil_wetness: "Wet soil generally absorbs less additional rainfall.",
  };
  return <>
    <strong>{row.point.name}</strong> <RiskBadge category={pointCategory(row)} />
    <p className="metric-note"><EvidenceState row={row} /> · {describe(assessment.validation_status)}</p>
    <Facts assessment={assessment} />
    {(context?.primary_driver || context?.confidence_level || thresholdsKnown) && <div className="detail-chips">
      {context?.primary_driver && <div className="detail-chip"><span>{t("Primary driver")}:</span><strong>{describe(context.primary_driver)}</strong></div>}
      {context?.confidence_level && <div className="detail-chip"><span>{t("Confidence level")}:</span><strong>{t(context.confidence_level)}</strong></div>}
      {thresholdsKnown && <div className="detail-chip"><span>{t("Flood-trigger rainfall threshold")}:</span><strong>{displayNumber(threshold)} mm / 24h</strong></div>}
    </div>}
    {provenanceDetail?.warning && <p className="flood-notice" role="status">{t(provenanceDetail.warning)}</p>}
    <h3 className="section-subhead">{t("Rainfall and risk by horizon")}</h3>
    <div className="horizon-grid">{[6, 12, 24].map(hours => {
      const entry = Array.isArray(assessment.horizon_breakdown)
        ? assessment.horizon_breakdown.find(item => (item?.horizon_hours ?? item?.hours) === hours)
        : undefined;
      const categoryAtHorizon = row.is_current ? entry?.risk_category ?? (hours === assessment.forecast_horizon_hours ? category : undefined) : undefined;
      const rain = entry?.rain_mm ?? entry?.rainfall_mm ?? assessment.forecast_rainfall?.[`forecast_rain_next_${hours}h_mm`];
      const horizonThreshold = entry?.threshold_mm ?? context?.trigger_thresholds_mm?.[`${hours}h_mm`];
      const pct = row.is_current && entry?.threshold_ratio != null ? Math.min(100, Math.max(0, entry.threshold_ratio * 100)) : 0;
      const barColor = pct >= 80 ? "#f47180" : pct >= 50 ? "#f29955" : pct >= 25 ? "#e8c658" : "#53ca89";
      return <div className="horizon-card" key={hours}>
        <div className="horizon-head">
          <strong>{hours} {t("hours")}</strong>
          {categoryAtHorizon && categories.includes(categoryAtHorizon) ? <RiskBadge category={categoryAtHorizon} /> : <span className="metric-note">{t("Unavailable")}</span>}
        </div>
        <div className="horizon-rain">{row.is_current ? displayNumber(rain) : "—"}<small>mm</small></div>
        <div className="horizon-bar" aria-hidden="true"><div className="horizon-bar-fill" style={{ width: `${pct}%`, backgroundColor: barColor }} /></div>
        <div className="horizon-meta">
          <span>{t("Trigger threshold (mm)")}: {horizonThreshold != null ? `${displayNumber(horizonThreshold)} mm` : "—"}</span>
          <span>{row.is_current && entry?.threshold_ratio != null ? `${displayNumber(entry.threshold_ratio * 100, 0)}%` : "—"}</span>
        </div>
      </div>;
    })}</div>
    <p className="metric-note">{t("Rainfall · preceding 24 h")}: <strong>{observed == null ? t("Unavailable") : `${displayNumber(observed)} mm`}</strong>
      {thresholdsKnown && observed != null && <> · {t("Difference from threshold")}: <strong>{displayNumber(observed - threshold)} mm</strong></>}</p>
    {row.is_current && context?.flood_window && <div className="advice-box" style={{ borderLeftColor: context.flood_window.status === "flood_window_expected" ? "#dc2626" : "#16a34a" }}>
      <h3>Khoảng thời gian ngập dự kiến (phân tích trượt theo giờ 24h tới)</h3>
      {context.flood_window.status === "flood_window_expected" && context.flood_window.onset_at ? (
        <div className="detail-chips">
          <div className="detail-chip"><span>Bắt đầu ngập:</span><strong>{localTime(context.flood_window.onset_at)} ICT</strong></div>
          {context.flood_window.peak_at && <div className="detail-chip"><span>Đỉnh ngập:</span><strong>{localTime(context.flood_window.peak_at)} ICT (~{context.flood_window.estimated_peak_depth_cm} cm)</strong></div>}
          {context.flood_window.recede_at && <div className="detail-chip"><span>Dự kiến rút:</span><strong>{localTime(context.flood_window.recede_at)} ICT ({displayNumber(context.flood_window.duration_hours, 1)} giờ)</strong></div>}
        </div>
      ) : (
        <p className="metric-note" style={{ margin: "0 0 .4rem" }}>Chưa phát hiện khung giờ vượt ngưỡng ngập trong 24 giờ tới.</p>
      )}
      <div className="detail-chips">
        <div className="detail-chip"><span>Mưa cực đại 1 giờ:</span><strong>{displayNumber(context.flood_window.max_rain_1h_mm)} mm</strong></div>
        <div className="detail-chip"><span>Mưa trượt 3 giờ:</span><strong>{displayNumber(context.flood_window.max_rain_3h_mm)} mm</strong></div>
        {context.flood_window.tide_level_m != null && <div className="detail-chip">
          <span>Mực triều ven biển:</span>
          <strong>{displayNumber(context.flood_window.tide_level_m, 2)} m ({context.flood_window.tide_impact === "high_tide_slows_drainage" ? "Triều cao, rút chậm" : "Thoát nước bình thường"})</strong>
        </div>}
      </div>
    </div>}
    {row.is_current && typeof context?.depth_cm === "number" && <p>{t("Estimated depth")} {displayNumber(context.depth_cm)} cm</p>}
    {row.is_current && typeof context?.starts_at === "string" && <p>{t("Estimated onset")} {localTime(context.starts_at)} ICT</p>}
    <div className="advice-box" style={{ borderLeftColor: riskColors[category] }}>
      <h3>{t("Recommended actions")}</h3>
      <ul>{(row.is_current && Array.isArray(localized) && localized.length ? localized : [advice]).map((action, index) =>
        <li key={index}>{t(action)}</li>)}</ul>
    </div>
    <div className="table-wrap"><table className="flood-table"><thead><tr><th scope="col">{t("Factor")}</th><th scope="col">{t("Inputs")}</th>
      <th scope="col" title={t(indexHelp)}>{t("Index points")}</th></tr></thead><tbody>
      {Object.entries(assessment.factors ?? {}).map(([factor, data]) => <tr key={factor}><th scope="row">{describe(factor)}</th>
        <td className="factor-inputs">{Object.entries(data.inputs).map(([key, value]) => <div key={key}>{describe(key)} · {displayNumber(value, 3)}</div>)}
          <small>{t(data.contribution_points == null ? "No index contribution" : factorExplanation[factor] ?? "Contribution reflects the configured weight and scaled inputs.")}</small></td>
        <td><div className="factor-bar-wrap"><strong>{displayNumber(data.contribution_points, 2)}</strong>
          {data.contribution_points != null && <span className="factor-bar" aria-hidden="true"><i style={{ width: `${Math.min(100, Math.max(2, data.contribution_points * 2))}%` }} /></span>}
        </div></td></tr>)}
    </tbody></table></div>
    {assessment.missing_features.length > 0 && <p className="flood-notice">{t("Missing inputs ·")} {assessment.missing_features.map(describe).join(", ")}</p>}
    <details className="flood-disclosure"><summary>{t("Sources, valid times and coverage limits")}</summary>
      {Object.entries({ ...assessment.source_references, ...assessment.data_provenance }).map(([code, info]) =>
        info && typeof info === "object" && <p key={code}>
          {typeof info.url === "string" && /^https?:\/\//i.test(info.url)
            ? <a href={info.url} target="_blank" rel="noreferrer">{code}</a> : code}
          {" · "}{describe(info.provenance_type ?? "Unspecified source type")}
          {info.resolution && <> · {t(info.resolution)}</>}
        </p>)}
      {Object.entries(assessment.data_freshness ?? {}).map(([key, info]) => <p key={key}>{describe(key)} · {t("Available at")} {localTime(info.available_at)} ICT
        {info.last_valid_at && <> · {t("Evidence valid through")} {localTime(info.last_valid_at)} ICT</>}</p>)}
      {Object.values(assessment.excluded_factors ?? {}).map((reason) => <p key={reason}>{t(reason)}</p>)}
    </details>
  </>;
}

type Column = "name" | "coordinates" | "index" | "probability" | "category" | "horizon" | "quality" | "version";
const columns: [Column, string][] = [["name", "Location"], ["coordinates", "Coordinates"], ["index", "Flood Risk Index"],
  ["probability", "Flood probability"], ["category", "Risk category"], ["horizon", "Horizon"], ["quality", "Evidence coverage"], ["version", "Version"]];

export function FloodForecast({ selected, select }: { selected: string; select: (code: string) => void }) {
  const t = useText();
  const [sort, setSort] = useState<{ key: Column; descending: boolean }>({ key: "index", descending: true });
  const client = useQueryClient();
  const risks = useData<PointRisk[]>("flood-risk/latest", undefined, true, 60_000);
  const predictions = useCurrentPredictions();
  const generate = useMutation({
    mutationFn: () => request<Assessment[]>("flood-risk/generate", undefined, undefined, {}),
    onSuccess: () => { void client.invalidateQueries({ predicate: ({ queryKey }) => String(queryKey[0]).startsWith("flood-risk/") }); },
  });
  const rows = useMemo(() => (risks.data ?? []).map((row) => {
    const assessment = activeAssessment(row);
    const prediction = predictions.data?.find((item) => item.location === row.point.code);
    const horizon = assessment?.forecast_horizon_hours ?? (prediction ?
      (Date.parse(prediction.valid_until) - Date.parse(prediction.issued_at)) / 3_600_000 : undefined);
    const columns = {
      name: row.point.name, coordinates: row.point.latitude, index: assessment?.risk_index,
      probability: prediction?.flood_probability, category: pointCategory(row),
      horizon, quality: assessment?.weight_coverage,
      version: assessment?.method_version ?? prediction?.model_version,
    };
    return { ...row, assessment, prediction, columns };
  }).sort((a, b) => {
    const left = a.columns[sort.key], right = b.columns[sort.key];
    if (left == null || right == null) return left == null && right == null ? a.point.name.localeCompare(b.point.name) : left == null ? 1 : -1;
    return (sort.descending ? -1 : 1) * (typeof left === "number" && typeof right === "number" ? left - right : String(left).localeCompare(String(right)));
  }), [risks.data, predictions.data, sort]);
  return <>
    <Panel title={t("Location comparison")} subtitle={t("Current assessments and independently validated probabilities")}
      action={<button className="button primary" disabled={generate.isPending} onClick={() => generate.mutate()}><RefreshCw size={15} />{generate.isPending ? t("Generating…") : t("Generate assessments")}</button>}>
      {generate.error && <QueryError error={generate.error} retry={() => generate.mutate()} />}
      {generate.isSuccess && <p className="metric-note" role="status">{generate.data.data.length} {t("assessment results returned.")}</p>}
      {predictions.error && <QueryError error={predictions.error} retry={() => void predictions.refetch()} />}
      <Resource query={risks} empty={<Empty title={t("No flood monitoring points")} detail={t("Register monitoring points before generating assessments.")} />}>{() =>
        <div className="table-wrap"><table className="flood-table"><thead><tr>{columns.map(([key, title]) =>
          <th key={key} scope="col" aria-sort={sort.key === key ? sort.descending ? "descending" : "ascending" : undefined}>
            <button className="sort-button" title={key === "index" ? t(indexHelp) : key === "probability" ? t(probabilityHelp) : undefined}
              onClick={() => setSort({ key, descending: sort.key === key ? !sort.descending : false })}>{t(title)}<ArrowDownUp size={13} /></button></th>)}</tr></thead>
          <tbody>{rows.map(({ point, assessment, prediction, ...row }) => <tr key={point.code} data-selected={point.code === selected}>
            <th scope="row"><button className="text-button" onClick={() => select(point.code)} aria-label={t("Inspect") + " " + point.name}>{point.name}</button></th>
            <td>{point.latitude.toFixed(5)}, {point.longitude.toFixed(5)}</td>
            <td title={t(indexHelp)}>{assessment?.risk_index == null ? "—" : displayNumber(assessment.risk_index) + " / 100"}</td>
            <td title={t(probabilityHelp)}>{predictions.isPending ? t("Loading…") : t(formatProbability(prediction?.flood_probability))}</td>
            <td><RiskBadge category={row.columns.category} /></td><td>{row.columns.horizon == null ? "—" : row.columns.horizon + " h"}</td>
            <td>{assessment ? displayNumber(assessment.weight_coverage * 100, 0) + "% " + t("factor weight") :
              prediction ? t("Validated forecast available") : <EvidenceState row={risks.data?.find((x) => x.point.code === point.code)} />}</td>
            <td>{[assessment?.method_version, prediction?.model_version].filter(Boolean).join(" · ") || "—"}</td>
          </tr>)}</tbody></table></div>}
      </Resource>
    </Panel>
    <RiskDetails code={selected} />
  </>;
}

export function FloodMap({ selected, select }: { selected: string; select: (code: string) => void }) {
  const t = useText();
  const [focused, setFocused] = useState("hai-chau");
  const [focusedRoad, setFocusedRoad] = useState("");
  const [horizon, setHorizon] = useState<MapHorizon>("summary");
  const [scenarioId, setScenarioId] = useState<HistoricalScenarioId>("live");
  const [showZones, setShowZones] = useState(true);
  const [showFloodRoads, setShowFloodRoads] = useState(true);
  const [showSafeRoads, setShowSafeRoads] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [fitNonce, setFitNonce] = useState(0);
  const risks = useData<PointRisk[]>("flood-risk/latest", undefined, true, 60_000);
  const predictions = useCurrentPredictions();
  const mappedPoints = useMemo(() => (risks.data ?? []).map(({point}) => point)
    .filter(point => Number.isFinite(point.latitude) && Math.abs(point.latitude) <= 90 &&
      Number.isFinite(point.longitude) && Math.abs(point.longitude) <= 180), [risks.data]);
  const activeScenario = historicalScenarios.find(s => s.id === scenarioId) ?? historicalScenarios[0];
  function focus(code: string) { setFocusedRoad(""); setFocused(code); select(code); }
  return <><Panel title="Bản đồ phân đoạn ngập lụt & lộ trình né ngập"
    subtitle="Hiển thị chuyển tiếp màu theo đoạn đường (Đỏ → Cam → Vàng → Xanh lá) kết hợp vùng trũng địa hình DEM 30m">
    {predictions.error && <QueryError error={predictions.error} retry={() => void predictions.refetch()} />}
    <Resource query={risks} empty={<Empty title={t("No flood monitoring points")} detail={t("Registered points will appear on the map.")} />}>
      {(rows) => {
        const assessments = new Map(rows.map(row => [row.point.code, row]));
        const getRain = (locationCode: string) => {
          if (scenarioId !== "live") {
            return activeScenario.rain24hByLocation[locationCode] ?? activeScenario.defaultRain24h;
          }
          return mapEvidence(assessments.get(locationCode), horizon).rain;
        };
        const activeHorizon: MapHorizon = scenarioId === "live" ? horizon : "summary";
        const roads = historicalRoads.map(road => {
          const rain = getRain(road.locationCode);
          const screening = roadScreening(rain, road.triggerMm24h, activeHorizon);
          return {...road, rain, screening};
        }).sort((a,b) => (a.locationCode === (focused || selected) ? -1 : 0) - (b.locationCode === (focused || selected) ? -1 : 0) || b.screening.rank - a.screening.rank);

        const mapRoads = roads.filter(r => (r.routeType === "safer_corridor" ? showSafeRoads : showFloodRoads));
        const visibleRoads = focused ? roads.filter(r => r.locationCode === focused) : roads;
        const floodRiskRoads = visibleRoads.filter(r => r.routeType === "flood_prone" && r.screening.rank >= 2);
        const saferAndLowRoads = visibleRoads.filter(r => r.routeType === "safer_corridor" || r.screening.rank <= 1);

        const formatFloodWindow = (locationCode: string, rank: number) => {
          if (scenarioId !== "live") {
            return scenarioFloodWindow(scenarioId, rank) ?? "Không ngập trong đợt mưa này (cao ráo / thoát nước tốt)";
          }
          const assessment = activeAssessment(assessments.get(locationCode));
          const fw = assessment?.inundation_detail?.flood_window;
          if (fw?.status === "flood_window_expected" && fw.onset_at && fw.recede_at) {
            const peakText = fw.peak_at ? ` · Đỉnh ${localTime(fw.peak_at)} (~${fw.estimated_peak_depth_cm} cm)` : "";
            return `${localTime(fw.onset_at)} → ${localTime(fw.recede_at)} ICT (${displayNumber(fw.duration_hours, 1)} giờ${peakText})`;
          }
          if (assessment) {
            const max1h = fw?.max_rain_1h_mm != null ? ` · Mưa đỉnh 1h: ${displayNumber(fw.max_rain_1h_mm)} mm` : "";
            return `Chưa có khung giờ ngập trong 24h tới (đến ${localTime(assessment.valid_until)} ICT${max1h})`;
          }
          return "Chưa có khung giờ ngập trong 24h tới";
        };

        const mapZones = showZones ? floodZones.map(zone => {
          const rain = getRain(zone.locationCode);
          const screening = roadScreening(rain, zone.triggerMm24h, activeHorizon);
          const coreColor = screening.rank >= 4 ? "#dc2626" : screening.rank === 3 ? "#f97316" : screening.rank === 2 ? "#eab308" : "#22c55e";
          const outerColor = screening.rank >= 4 ? "#f97316" : screening.rank === 3 ? "#eab308" : "#22c55e";
          const zoneWindow = formatFloodWindow(zone.locationCode, screening.rank);
          return {
            ...zone,
            coreColor,
            outerColor,
            active: screening.rank >= 2,
            content: <>
              <strong className="popup-name">{zone.name}</strong>
              <div style={{ fontWeight: 700, color: coreColor }}>{screening.label} ({screening.depth})</div>
              <div><strong>Khoảng thời gian ngập:</strong> <span style={{ color: coreColor, fontWeight: 700 }}>{zoneWindow}</span></div>
              <div>Lượng mưa tham chiếu: <strong>{displayNumber(rain)} mm</strong> · Ngưỡng: {zone.triggerMm24h} mm</div>
              <p style={{ margin: "6px 0 0" }}>{zone.elevationNote}</p>
            </>,
          };
        }) : undefined;
        const selectedRoadObj = roads.find(r => r.id === focusedRoad);

        return <>
        <div className="scenario-bar" role="group" aria-label="Chế độ xem dự báo hoặc đối chiếu lịch sử">
          {historicalScenarios.map(sc => (
            <button key={sc.id} type="button" className="scenario-pill"
              aria-pressed={scenarioId === sc.id}
              onClick={() => setScenarioId(sc.id)}>
              <strong>{sc.label}</strong>
              <small>{sc.dateLabel}</small>
            </button>
          ))}
        </div>
        {scenarioId !== "live" ? (
          <div className="scenario-banner" role="status">
            <div>
              <strong>Đối chiếu sự kiện lịch sử đã kiểm chứng — {activeScenario.label}:</strong> {activeScenario.summary}
            </div>
            {activeScenario.source && <a href={activeScenario.source} target="_blank" rel="noreferrer">Nguồn kiểm chứng</a>}
          </div>
        ) : (
          <div className="segmented flood-map-horizons" role="group" aria-label={t("Forecast window")}>
            {([["summary","Tổng hợp 24 giờ"],[6,"6 giờ tới"],[12,"12 giờ tới"],[24,"24 giờ tới"]] as const).map(([value, title]) =>
              <button type="button" key={value} aria-pressed={horizon === value} onClick={() => setHorizon(value)}>{title}</button>)}
          </div>
        )}
        <div className="flood-map-toolbar">
          <span>{mappedPoints.length}/{rows.length} điểm quan trắc</span>
          <label><input type="checkbox" checked={showFloodRoads} onChange={e => { setShowFloodRoads(e.target.checked); setFocusedRoad(""); }} /> Tuyến ngập</label>
          <label><input type="checkbox" checked={showSafeRoads} onChange={e => { setShowSafeRoads(e.target.checked); setFocusedRoad(""); }} /> Tuyến né ngập</label>
          <label><input type="checkbox" checked={showZones} onChange={e => setShowZones(e.target.checked)} /> Vùng trũng lan tỏa</label>
          <button className="button secondary" type="button" onClick={() => { setFocused(""); setFocusedRoad(""); setFitNonce(n => n + 1); }}>Xem toàn Đà Nẵng</button>
          <button className="button primary" type="button" onClick={() => setExpanded(v => !v)}>{expanded ? "Thu gọn bản đồ" : "Mở rộng toàn bản đồ"}</button>
        </div>
        <StationMap points={mappedPoints} selected={selected} focused={focused} onSelect={focus} latest={{}} weather={[]}
          showAreas={false} zones={mapZones} focusedRoad={focusedRoad} onSelectRoad={setFocusedRoad} expanded={expanded} fitNonce={fitNonce}
          roads={mapRoads.map(road => {
            const windowText = formatFloodWindow(road.locationCode, road.screening.rank);
            return {
              ...road,
              color: road.screening.color,
              dashed: road.routeType === "safer_corridor" && road.screening.rank === 1,
              content: <>
                <strong className="popup-name">{road.name}</strong>
                <div style={{ fontWeight: 700, color: road.screening.color, marginBottom: 4 }}>
                  {road.screening.label} · Ước tính: {road.screening.depth}
                </div>
                <div><strong>Khoảng thời gian ngập:</strong> <span style={{ color: road.screening.rank >= 2 ? road.screening.color : "inherit", fontWeight: 700 }}>{windowText}</span></div>
                <div><strong>Đoạn đường:</strong> {road.fromLabel} → {road.toLabel}</div>
                {road.elevationM != null && <div><strong>Cao độ địa hình (DEM):</strong> {road.elevationM} m</div>}
                <div><strong>Lượng mưa tham chiếu:</strong> {displayNumber(road.rain)} mm (ngưỡng đoạn: {road.triggerMm24h} mm/24h)</div>
                <div style={{ marginTop: 4 }}><strong>Đoạn nối tiếp / Gợi ý né:</strong> {road.connectedNext}</div>
                <p style={{ margin: "6px 0 4px" }}>{road.historicalNote}</p>
                <a href={road.source} target="_blank" rel="noreferrer">Nguồn kiểm chứng lịch sử</a>
              </>,
            };
          })}
          floodMarkers={Object.fromEntries(rows.map((row) => {
            const liveEv = mapEvidence(row, horizon);
            const rain = getRain(row.point.code);
            const category: RiskCategory = scenarioId === "live"
              ? liveEv.category
              : (rain ?? 0) >= 150 ? "Very High" : (rain ?? 0) >= 90 ? "High" : (rain ?? 0) >= 45 ? "Moderate" : "Low";
            const stationRank = category === "Very High" ? 4 : category === "High" ? 3 : category === "Moderate" ? 2 : 1;
            const stationWindow = formatFloodWindow(row.point.code, stationRank);
            const current = activeAssessment(row);
            return [row.point.code, { color: riskColors[category], radius: riskRadius[category], content: <>
              <strong className="popup-name">{row.point.name}</strong><div><RiskBadge category={category} /></div>
              <div><strong>Khoảng thời gian ngập:</strong> {stationWindow}</div>
              <div>Lượng mưa tham chiếu: <strong>{displayNumber(rain)} mm</strong></div>
              {scenarioId === "live" && horizon === "summary" && current?.risk_index != null && <div>Chỉ số rủi ro: <strong>{displayNumber(current.risk_index)} / 100</strong></div>}
              {scenarioId === "live" && current?.inundation_detail?.flood_window?.tide_level_m != null && (
                <div>Mực triều ven biển: <strong>{displayNumber(current.inundation_detail.flood_window.tide_level_m, 2)} m</strong></div>
              )}
              {scenarioId === "live" && row.assessment && <>
                <div>Phát hành: {localTime(row.assessment.issued_at)} ICT</div>
                <div>Hiệu lực đến: {localTime(row.assessment.valid_until)} ICT</div>
              </>}
            </> }];
          }))} />
        {selectedRoadObj && <div className="advice-box" style={{ borderLeftColor: selectedRoadObj.screening.color, marginTop: ".8rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: ".5rem", flexWrap: "wrap" }}>
            <h3 style={{ margin: 0 }}>Chi tiết tuyến đường đang chọn: {selectedRoadObj.name}</h3>
            <button type="button" className="button secondary" style={{ padding: ".25rem .6rem", fontSize: ".78rem" }} onClick={() => setFocusedRoad("")}>Đóng chi tiết</button>
          </div>
          <div className="detail-chips" style={{ marginTop: ".5rem" }}>
            <div className="detail-chip"><span>Trạng thái:</span><strong style={{ color: selectedRoadObj.screening.color }}>{selectedRoadObj.screening.label} ({selectedRoadObj.screening.depth})</strong></div>
            <div className="detail-chip"><span>Khoảng thời gian ngập:</span><strong style={{ color: selectedRoadObj.screening.rank >= 2 ? selectedRoadObj.screening.color : "inherit" }}>{formatFloodWindow(selectedRoadObj.locationCode, selectedRoadObj.screening.rank)}</strong></div>
            <div className="detail-chip"><span>Phạm vi đoạn:</span><strong>{selectedRoadObj.fromLabel} → {selectedRoadObj.toLabel}</strong></div>
            {selectedRoadObj.elevationM != null && <div className="detail-chip"><span>Cao độ DEM:</span><strong>{selectedRoadObj.elevationM} m</strong></div>}
          </div>
          <p className="metric-note" style={{ margin: ".35rem 0 0" }}><strong>Gợi ý di chuyển / đoạn nối tiếp:</strong> {selectedRoadObj.connectedNext}</p>
        </div>}
        <div className="corridor-legend" aria-label="Chú giải thang màu mức ngập theo đoạn đường">
          <span className="corridor-legend-item"><i style={{ backgroundColor: "#dc2626" }} />Ngập sâu (30–50+ cm) · Tránh đi qua</span>
          <span className="corridor-legend-item"><i style={{ backgroundColor: "#f97316" }} />Ngập trung bình (15–30 cm) · Hạn chế</span>
          <span className="corridor-legend-item"><i style={{ backgroundColor: "#eab308" }} />Ngập nhẹ (5–15 cm) · Đi chậm</span>
          <span className="corridor-legend-item"><i style={{ backgroundColor: "#16a34a" }} />Cao ráo (&lt; 5 cm) · Gợi ý né ngập</span>
        </div>
        <div className="road-groups">
          <div className="road-group-card">
            <h4><i className="road-dot" style={{ backgroundColor: "#dc2626" }} />Các đoạn đường có nguy cơ ngập ({floodRiskRoads.length})</h4>
            <div className="flood-stations">{floodRiskRoads.length ? floodRiskRoads.map(road => {
              const win = scenarioFloodWindow(scenarioId, road.screening.rank);
              return <button type="button" className="button secondary" key={road.id}
                aria-pressed={focusedRoad === road.id} onClick={() => { setFocused(road.locationCode); setFocusedRoad(road.id); }}>
                <MapPin size={15} style={{ color: road.screening.color, flexShrink: 0 }} />
                <span>{road.name}
                  <small style={{ color: road.screening.color }}>{road.screening.label} ({road.screening.depth}){win ? ` · ${win}` : ""}</small>
                </span>
              </button>;
            }) : <p className="chart-note">Với lượng mưa dự báo hiện tại, chưa có đoạn đường nào vượt ngưỡng ngập. Hãy chọn một sự kiện lịch sử phía trên để xem bản đồ chuyển màu & khung giờ ngập khi mưa lớn.</p>}</div>
          </div>
          <div className="road-group-card">
            <h4><i className="road-dot" style={{ backgroundColor: "#16a34a" }} />Tuyến cao ráo / Gợi ý né ngập ({saferAndLowRoads.length})</h4>
            <div className="flood-stations">{saferAndLowRoads.map(road => <button type="button" className="button secondary" key={road.id}
              aria-pressed={focusedRoad === road.id} onClick={() => { setFocused(road.locationCode); setFocusedRoad(road.id); }}>
              <MapPin size={15} style={{ color: road.screening.color, flexShrink: 0 }} />
              <span>{road.name}<small>{road.fromLabel} → {road.toLabel} · {road.screening.depth}</small></span>
            </button>)}</div>
          </div>
        </div>
        <div className="flood-stations">{rows.map((row) =>
          <button className="button secondary" key={row.point.code} type="button"
            onClick={() => mappedPoints.some(point => point.code === row.point.code) ? focus(row.point.code) : select(row.point.code)}
            aria-pressed={(focused || selected) === row.point.code}>
            <MapPin size={16} style={{color:riskColors[mapEvidence(row, horizon).category]}} />
            <span>{row.point.name}<small>{mappedPoints.some(point => point.code === row.point.code) ? t(mapEvidence(row, horizon).category) : t("Coordinates unavailable")}</small></span></button>)}</div>
      </>;}}
    </Resource>
  </Panel><RiskDetails code={selected} /></>;
}
