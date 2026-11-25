"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownUp, MapPin, RefreshCw } from "lucide-react";
import { displayNumber, localTime, request, source, useCollection, useData, type Rain, type Scope, type Weather } from "./data";
import {
  activeAssessment, categories, formatProbability, indexHelp, label, pointCategory, probabilityHelp, riskColors,
  type Assessment, type FloodPrediction, type PointRisk, type RiskCategory,
} from "./flood-data";
import type { Markers } from "./station-map";
import { Empty, Loading, Panel, QueryError, Resource } from "./ui";
import { RainfallPanel } from "./weather-panels";

const StationMap = dynamic<Markers>(() => import("./station-map"), { ssr: false, loading: () => <Loading /> });
type Theme = "dark" | "light";

export function RiskBadge({ category }: { category: RiskCategory }) {
  return <span className="risk-badge"><i style={{ backgroundColor: riskColors[category] }} />{category}</span>;
}

function EvidenceState({ row }: { row?: PointRisk }) {
  return <>{!row?.assessment ? "No stored assessment" : !row.is_current ? "Latest assessment expired" :
    row.assessment.risk_index == null ? "Required inputs missing" : label(row.assessment.assessment_status)}</>;
}

function Facts({ assessment }: { assessment: Assessment }) {
  const latest = Object.values(assessment.data_freshness ?? {}).map((record) => record.available_at).sort().at(-1);
  return <dl className="flood-facts">
    <div><dt>Issued</dt><dd>{localTime(assessment.issued_at)} ICT</dd></div>
    <div><dt>Valid until</dt><dd>{localTime(assessment.valid_until)} ICT</dd></div>
    <div><dt>Latest evidence available</dt><dd>{latest ? localTime(latest) + " ICT" : "Unavailable"}</dd></div>
    <div><dt>Method</dt><dd>{assessment.method_version}</dd></div>
  </dl>;
}

function useCurrentPredictions() {
  return useData<FloodPrediction[]>("flood-predictions/results", { current: "true", limit: 250 }, true, 60_000);
}

export function FloodOverview({ scope, theme, weather }: {
  scope: Scope; theme: Theme; weather: ReturnType<typeof useData<Weather[]>>;
}) {
  const risks = useData<PointRisk[]>("flood-risk/latest", undefined, true, 60_000);
  const predictions = useCurrentPredictions();
  const historical = useCollection<Rain>("rainfall/daily", { ...scope, source }, Boolean(scope.location));
  const rank = (row: PointRisk) => activeAssessment(row)?.risk_index ?? -1;
  return <>
    <Resource query={risks} empty={<Empty title="No flood monitoring points" detail="Points appear after they are registered in the warehouse." />}>
      {(rows) => {
        const highest = rows.filter((row) => rank(row) >= 0).sort((a, b) => rank(b) - rank(a))[0];
        const selected = rows.find((row) => row.point.code === scope.location);
        const current = activeAssessment(selected);
        const absent = rows.filter((row) => pointCategory(row) === "Insufficient Data").length;
        const measured = (historical.data ?? []).filter((row) => row.rainfall_total_mm != null);
        const total = measured.length ? measured.reduce((sum, row) => sum + row.rainfall_total_mm!, 0) : null;
        return <>
          <div className="flood-overview grid">
            <Panel className="risk-lead" title="Highest current forecast risk" subtitle="Flood Risk Index">
              {highest?.assessment ? <><strong className="risk-value" title={indexHelp}>{displayNumber(highest.assessment.risk_index)} <small>/ 100</small></strong>
                <RiskBadge category={pointCategory(highest)} /><p>{highest.point.name}</p><Facts assessment={highest.assessment} /></> :
                <><strong className="risk-value">Unavailable</strong><RiskBadge category="Insufficient Data" />
                  <p>No current assessment has enough evidence for a score.</p></>}
            </Panel>
            <Panel title="Monitoring coverage" subtitle="Current assessment categories">
              <div className="risk-counts">{categories.map((category) => <div key={category}><RiskBadge category={category} />
                <strong>{rows.filter((row) => pointCategory(row) === category).length}</strong></div>)}</div>
            </Panel>
            <Panel title="Validated flood predictions" subtitle="Currently valid calibrated forecasts">
              {predictions.error ? <QueryError error={predictions.error} retry={() => void predictions.refetch()} /> :
                predictions.isPending ? <Loading compact /> :
                <><strong className="risk-value">{predictions.data?.length ?? 0}</strong><p title={probabilityHelp}>Available location forecasts</p>
                  {predictions.data?.[0] && <p className="metric-note">Issued {localTime(predictions.data[0].issued_at)} · valid until {localTime(predictions.data[0].valid_until)} ICT</p>}</>}
            </Panel>
          </div>
          {absent > 0 && <p className="flood-notice" role="status">{absent} of {rows.length} points have missing or expired assessment evidence. Gray indicates unknown risk.</p>}
          <Panel title="Rainfall context" subtitle={selected?.point.name}>
            <div className="flood-context grid">
              <div><span>Historical rainfall · selected archive dates</span>
                <strong>{historical.isFetching ? "Loading…" : historical.error ? "Unavailable" : total == null ? "Unavailable" : displayNumber(total) + " mm"}</strong>
                <small>{!historical.isFetching && !historical.error && measured.length > 0 ?
                  measured.length + (measured.length === 1 ? " day with measurements" : " days with measurements") : ""}</small></div>
              <div><span>Observed rain · preceding 24 h</span><strong>{current?.observed_rainfall?.rain_prev_24h_mm == null ? "Unavailable" : displayNumber(current.observed_rainfall.rain_prev_24h_mm) + " mm"}</strong></div>
              {[6, 12, 24].map((hours) => {
                const rain = current?.forecast_rainfall?.[`forecast_rain_next_${hours}h_mm`];
                return <div key={hours}><span>Forecast rain · next {hours} h</span>
                  <strong>{rain == null ? "Unavailable" : displayNumber(rain) + " mm"}</strong></div>;
              })}
            </div>
            {selected?.assessment && <><p className="metric-note"><EvidenceState row={selected} /></p><Facts assessment={selected.assessment} /></>}
          </Panel>
        </>;
      }}
    </Resource>
    <Panel title="Current weather" subtitle="Open-Meteo modeled conditions">
      <Resource query={weather} empty={<Empty title="No weather snapshots collected" detail="Run weather ingestion from Data Management." />}>
        {(rows) => {
          const snapshot = rows.find((row) => row.location_code === scope.location);
          if (!snapshot) return <Empty title="Current weather unavailable for this point"
            detail="The weather feed has no recent snapshot for this sampling point." />;
          const values = snapshot.payload.values;
          return <>
            <div className="flood-context grid">
              <div><span>Temperature</span><strong>{values.temperature_2m == null ? "Unavailable" : displayNumber(values.temperature_2m) + " °C"}</strong></div>
              <div><span>Relative humidity</span><strong>{values.relative_humidity_2m == null ? "Unavailable" : displayNumber(values.relative_humidity_2m) + " %"}</strong></div>
              <div><span>Precipitation{snapshot.payload.interval_seconds ? " · " + snapshot.payload.interval_seconds / 60 + " min" : ""}</span>
                <strong>{values.precipitation == null ? "Unavailable" : displayNumber(values.precipitation) + " mm"}</strong></div>
            </div>
            <p className="metric-note">Valid {localTime(snapshot.valid_at)} · received {localTime(snapshot.received_at)} ICT</p>
          </>;
        }}
      </Resource>
    </Panel>
    <RainfallPanel scope={scope} theme={theme} />
  </>;
}

function RiskDetails({ code }: { code: string }) {
  const details = useData<PointRisk>("flood-risk/" + encodeURIComponent(code) + "/details", undefined, Boolean(code), 60_000);
  return <Panel title="Contributing factors and evidence">
    {!code ? <Empty title="Select a monitoring point" detail="Choose a row to inspect its latest assessment." /> :
      <Resource query={details}>{(row) => row.assessment ? <AssessmentEvidence row={row} assessment={row.assessment} /> :
        <Empty title="No stored assessment" detail={"Assessment evidence is unavailable for " + row.point.name + "."} />}</Resource>}
  </Panel>;
}

function AssessmentEvidence({ row, assessment }: { row: PointRisk; assessment: Assessment }) {
  return <>
    <strong>{row.point.name}</strong> <RiskBadge category={pointCategory(row)} />
    <p className="metric-note"><EvidenceState row={row} /> · {label(assessment.validation_status)}</p>
    <Facts assessment={assessment} />
    <div className="table-wrap"><table className="flood-table"><thead><tr><th scope="col">Factor</th><th scope="col">Inputs</th>
      <th scope="col" title={indexHelp}>Index points</th></tr></thead><tbody>
      {Object.entries(assessment.factors ?? {}).map(([factor, data]) => <tr key={factor}><th scope="row">{label(factor)}</th>
        <td className="factor-inputs">{Object.entries(data.inputs).map(([key, value]) => <div key={key}>{label(key)} · {displayNumber(value, 3)}</div>)}</td>
        <td>{displayNumber(data.contribution_points, 2)}</td></tr>)}
    </tbody></table></div>
    {assessment.missing_features.length > 0 && <p className="flood-notice">Missing inputs · {assessment.missing_features.map(label).join(", ")}</p>}
    <details className="flood-disclosure"><summary>Sources, valid times and coverage limits</summary>
      {Object.entries(assessment.source_references ?? {}).map(([code, info]) => <p key={code}><a href={info.url} target="_blank" rel="noreferrer">{code}</a> · {info.resolution}</p>)}
      {Object.entries(assessment.data_freshness ?? {}).map(([key, info]) => <p key={key}>{label(key)} · available {localTime(info.available_at)} ICT
        {info.last_valid_at && <> · evidence valid through {localTime(info.last_valid_at)} ICT</>}</p>)}
      {Object.values(assessment.excluded_factors ?? {}).map((reason) => <p key={reason}>{reason}</p>)}
    </details>
  </>;
}

type Column = "name" | "coordinates" | "index" | "probability" | "category" | "horizon" | "quality" | "version";
const columns: [Column, string][] = [["name", "Location"], ["coordinates", "Coordinates"], ["index", "Flood Risk Index"],
  ["probability", "Flood probability"], ["category", "Risk category"], ["horizon", "Horizon"], ["quality", "Evidence coverage"], ["version", "Version"]];

export function FloodForecast({ selected, select }: { selected: string; select: (code: string) => void }) {
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
    <Panel title="Location comparison" subtitle="Current assessments and independently validated probabilities"
      action={<button className="button primary" disabled={generate.isPending} onClick={() => generate.mutate()}><RefreshCw size={15} />{generate.isPending ? "Generating…" : "Generate assessments"}</button>}>
      {generate.error && <QueryError error={generate.error} retry={() => generate.mutate()} />}
      {generate.isSuccess && <p className="metric-note" role="status">{generate.data.data.length} assessment results returned.</p>}
      {predictions.error && <QueryError error={predictions.error} retry={() => void predictions.refetch()} />}
      <Resource query={risks} empty={<Empty title="No flood monitoring points" detail="Register monitoring points before generating assessments." />}>{() =>
        <div className="table-wrap"><table className="flood-table"><thead><tr>{columns.map(([key, title]) =>
          <th key={key} scope="col" aria-sort={sort.key === key ? sort.descending ? "descending" : "ascending" : undefined}>
            <button className="sort-button" title={key === "index" ? indexHelp : key === "probability" ? probabilityHelp : undefined}
              onClick={() => setSort({ key, descending: sort.key === key ? !sort.descending : false })}>{title}<ArrowDownUp size={13} /></button></th>)}</tr></thead>
          <tbody>{rows.map(({ point, assessment, prediction, ...row }) => <tr key={point.code} data-selected={point.code === selected}>
            <th scope="row"><button className="text-button" onClick={() => select(point.code)} aria-label={"Inspect " + point.name}>{point.name}</button></th>
            <td>{point.latitude.toFixed(5)}, {point.longitude.toFixed(5)}</td>
            <td title={indexHelp}>{assessment?.risk_index == null ? "—" : displayNumber(assessment.risk_index) + " / 100"}</td>
            <td title={probabilityHelp}>{predictions.isPending ? "Loading…" : formatProbability(prediction?.flood_probability)}</td>
            <td><RiskBadge category={row.columns.category} /></td><td>{row.columns.horizon == null ? "—" : row.columns.horizon + " h"}</td>
            <td>{assessment ? displayNumber(assessment.weight_coverage * 100, 0) + "% factor weight" :
              prediction ? "Validated forecast available" : <EvidenceState row={risks.data?.find((x) => x.point.code === point.code)} />}</td>
            <td>{[assessment?.method_version, prediction?.model_version].filter(Boolean).join(" · ") || "—"}</td>
          </tr>)}</tbody></table></div>}
      </Resource>
    </Panel>
    <RiskDetails code={selected} />
  </>;
}

export function FloodMap({ selected, select }: { selected: string; select: (code: string) => void }) {
  const [focused, setFocused] = useState("");
  const risks = useData<PointRisk[]>("flood-risk/latest", undefined, true, 60_000);
  const predictions = useCurrentPredictions();
  function focus(code: string) { setFocused(code); select(code); }
  return <Panel title="Point-level flood risk" subtitle="Sampling points · no modeled inundation extent">
    {predictions.error && <QueryError error={predictions.error} retry={() => void predictions.refetch()} />}
    <Resource query={risks} empty={<Empty title="No flood monitoring points" detail="Registered points will appear on the map." />}>
      {(rows) => <>
        <StationMap points={rows.map(({ point }) => point)} selected={focused} onSelect={focus} latest={{}} weather={[]}
          floodMarkers={Object.fromEntries(rows.map((row) => {
            const category = pointCategory(row), current = activeAssessment(row);
            const forecast = predictions.data?.find((item) => item.location === row.point.code);
            return [row.point.code, { color: riskColors[category], content: <>
              <strong className="popup-name">{row.point.name}</strong><div>{category}</div>
              {current?.risk_index != null && <div>Index {displayNumber(current.risk_index)} / 100</div>}
              <div><EvidenceState row={row} /></div>
              {row.assessment && <><div>Issued {localTime(row.assessment.issued_at)} ICT</div>
                <div>Valid until {localTime(row.assessment.valid_until)} ICT</div>
                {Object.entries(row.assessment.factors ?? {}).map(([name, factor]) =>
                  <div key={name}>{label(name)} · {factor.contribution_points == null ? "no index contribution" : displayNumber(factor.contribution_points, 2) + " points"}</div>)}
                {!!row.assessment.missing_features.length && <div>Missing · {row.assessment.missing_features.map(label).join(", ")}</div>}</>}
              {forecast?.flood_probability != null && <><div title={probabilityHelp}>Calibrated probability · {formatProbability(forecast.flood_probability)}</div>
                <div>Model forecast valid until {localTime(forecast.valid_until)} ICT</div></>}
              <small>Point and provider-grid evidence. Street-level conditions are unverified.</small>
            </> }];
          }))} />
        <div className="map-legend flood-legend">{categories.map((category) => <RiskBadge category={category} key={category} />)}</div>
        <div className="flood-stations">{rows.map((row) =>
          <button className="button secondary" key={row.point.code} onClick={() => focus(row.point.code)} aria-pressed={selected === row.point.code}>
            <MapPin size={14} />{row.point.name}</button>)}</div>
      </>}
    </Resource>
  </Panel>;
}
