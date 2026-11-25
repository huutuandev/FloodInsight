"use client";

import { displayNumber, localTime, locationName, useData, type Location } from "./data";
import { formatProbability, label, probabilityHelp, type Assessment, type FloodCoverage,
  type FloodMetrics, type FloodPrediction, type FloodProfiles } from "./flood-data";
import { Chart } from "./chart";
import { RiskBadge } from "./flood-panels";
import { Empty, Panel, Resource } from "./ui";

type Theme = "dark" | "light";

export function FloodMachineLearning({ locations, theme }: { locations: Location[]; theme: Theme }) {
  const predictions = useData<FloodPrediction[]>("flood-predictions/results", { limit: 30 }, true, 60_000);
  const metrics = useData<FloodMetrics>("flood-predictions/metrics", undefined, true, 60_000);
  const profiles = useData<FloodProfiles>("clustering/flood-profiles");

  return <>
    <Panel title="Flood probability predictions" subtitle="Approved model results and threshold-based flood classification">
      <Resource query={predictions} empty={<Empty title="No validated flood predictions"
        detail="A calibrated forecast appears here only when a model passes the evidence and release gates and its inputs are available." />}>
        {(rows) => <div className="table-wrap"><table className="flood-table"><thead><tr>
          <th>Point</th><th title={probabilityHelp}>Probability</th><th>Classification</th><th>Issued · ICT</th><th>Valid until · ICT</th><th>Version</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id ?? row.location + row.issued_at}><th scope="row">{locationName(row.location, locations)}</th>
            <td title={probabilityHelp}>{formatProbability(row.flood_probability)}</td><td>{label(row.risk_classification)}</td>
            <td>{localTime(row.issued_at)}</td><td>{localTime(row.valid_until)}</td><td>{row.model_version ?? "—"}</td></tr>)}</tbody></table></div>}
      </Resource>
    </Panel>
    <Panel title="Flood model evaluation" subtitle="Held-out performance and validation status">
      <Resource query={metrics}>{(data) => {
        const test = data.evaluation?.test;
        const confusion = test?.confusion;
        const calibration = test?.calibration_curve;
        const importance = Object.entries(data.evaluation?.feature_importance ?? {});
        return <>
          <p className="flood-notice">{label(data.status)}{data.version && <> · {data.version}</>}</p>
          {data.readiness.blocking_inventory.length > 0 && <p className="metric-note">Blocked by {data.readiness.blocking_inventory.map(label).join(", ")}.</p>}
          <div className="flood-context grid" aria-label="Flood training coverage">
            <div><span>Candidate flood observations</span><strong>{data.readiness.inventory.candidate_positive_observations ?? "—"}</strong></div>
            <div><span>Candidate dry observations</span><strong>{data.readiness.inventory.candidate_dry_observations ?? "—"}</strong></div>
            <div><span>Stored forecast snapshots</span><strong>{data.readiness.inventory.forecast_snapshots ?? "—"}</strong></div>
          </div>
          {test ? <div className="risk-counts flood-context">{[
            ["Precision", test.precision, "Share of alerts that matched a confirmed positive."],
            ["Recall", test.recall, "Share of confirmed positive examples that received an alert."],
            ["F1", test.f1, "Harmonic mean of precision and recall."],
            ["PR-AUC", test.pr_auc_average_precision, "Average precision summarizes precision at different recall levels."],
            ["ROC-AUC", test.roc_auc, "Ranking discrimination across decision thresholds."],
            ["Brier Score", test.brier, "Mean squared probability error. Lower is better."],
          ].map(([name, value, tip]) => <div key={name as string} title={tip as string}><span>{name}</span><strong>{displayNumber(value as number | null, 3)}</strong></div>)}</div>
            : <Empty title="Evaluation metrics unavailable" detail="Precision, recall, F1, PR-AUC, ROC-AUC and Brier Score require eligible labeled evaluation data." />}
          <div className="two-col grid">
            <Panel title="Confusion matrix" subtitle="Observed versus threshold-based classification">
              {confusion ? <Chart label="Flood confusion matrix" theme={theme} option={{
                xAxis: { type: "category", data: ["Dry", "Flood"] }, yAxis: { type: "category", data: ["Dry", "Flood"] },
                visualMap: { min: 0, max: Math.max(1, ...Object.values(confusion)) },
                series: [{ type: "heatmap", label: { show: true }, data: [[0, 0, confusion.tn], [1, 0, confusion.fp], [0, 1, confusion.fn], [1, 1, confusion.tp]] }],
              }} /> : <Empty title="No confusion matrix" detail="No labeled held-out results are available." />}
            </Panel>
            <Panel title="Calibration curve" subtitle="Predicted probability versus observed flood frequency">
              {calibration?.length ? <Chart label="Flood probability calibration" theme={theme} option={{
                xAxis: { type: "value", min: 0, max: 1, name: "Probability" }, yAxis: { type: "value", min: 0, max: 1, name: "Observed" },
                series: [{ type: "line", name: "Perfect calibration", data: [[0, 0], [1, 1]], lineStyle: { type: "dashed" } },
                  { type: "scatter", name: "Calibration bins", data: calibration.map((bin) => [bin.mean_probability, bin.positive_fraction, bin.count]) }],
              }} /> : <Empty title="Calibration unavailable" detail="Reliability bins require scored outcomes." />}
            </Panel>
            <Panel title="Model comparison" subtitle="Candidate selection-split evaluation">
              {data.evaluation?.candidates?.length ? <div className="table-wrap"><table className="flood-table"><thead><tr><th>Candidate</th><th>Calibration</th><th>Brier</th><th>Status</th></tr></thead>
                <tbody>{data.evaluation.candidates.map((candidate) => <tr key={candidate.candidate + candidate.method}>
                  <td>{label(candidate.candidate)}</td><td>{candidate.method}</td><td>{displayNumber(candidate.calibrated_selection?.brier, 3)}</td>
                  <td>{candidate.status ? label(candidate.status) : "Evaluated"}</td></tr>)}</tbody></table></div> :
                <Empty title="No evaluated candidates" detail="The training readiness gate blocks comparison until adequate evidence exists." />}
            </Panel>
            <Panel title="Feature importance" subtitle="Raw candidate · change in selection Brier loss after permutation">
              {importance.length ? <div className="risk-counts">{importance.sort((a, b) => b[1] - a[1]).map(([key, value]) =>
                <div key={key}><span>{label(key)}</span><strong>{displayNumber(value, 4)}</strong></div>)}</div> :
                <Empty title="Feature importance unavailable" detail="Requires an evaluated flood model." />}
            </Panel>
          </div>
        </>;
      }}</Resource>
    </Panel>
    <Panel title="Flood-related clustering" subtitle="Exploratory terrain profile groups without flood labels">
      <Resource query={profiles}>{(data) => <>
        <p className="metric-note">{data.interpretation} · {data.complete_points} complete points · silhouette {displayNumber(data.silhouette_in_sample, 3)}</p>
        <Chart label="Flood terrain profile groups" theme={theme} option={{
          xAxis: { type: "value", name: "Elevation (m)" }, yAxis: { type: "value", name: "Slope (°)" },
          series: [...new Set(data.assignments.map((row) => row.cluster_id))].map((id) => ({
            type: "scatter", name: "Group " + id, symbolSize: 12,
            data: data.assignments.filter((row) => row.cluster_id === id).map((row) => ({
              name: locationName(row.location, locations), value: [row.features.elevation_m, row.features.surface_slope_deg],
            })),
          })),
        }} />
      </>}</Resource>
    </Panel>
  </>;
}

export function FloodDataManagement({ locations }: { locations: Location[] }) {
  const coverage = useData<FloodCoverage>("flood-data/coverage");
  const readiness = useData<FloodMetrics>("flood-predictions/metrics", undefined, true, 60_000);
  const history = useData<Assessment[]>("flood-risk/history", { limit: 25 }, true, 60_000);
  return <>
    <Panel title="Flood dataset coverage" subtitle="Registered observations, features and provider coverage">
      <Resource query={coverage}>{(data) => <>
        <div className="flood-context flood-data-counts grid">{[
          ["Documented events", data.counts.flood_events],
          ["Confirmed flood labels", data.label_counts.flood_confirmed],
          ["Confirmed non-flood labels", data.label_counts.non_flood_confirmed],
          ["Recorded unknown labels", data.label_counts.unknown],
          ["Terrain features", data.counts.flood_terrain_features],
          ["Hydrological observations", data.counts.flood_hydrology_observations],
        ].map(([name, count]) => <div key={name}><span>{name}</span><strong>{count ?? "—"}</strong></div>)}</div>
        <p className="metric-note">Unobserved periods are also unknown and have no stored label.</p>
        <div className="two-col grid">
          <Panel title="Weather source coverage">
            {data.weather_daily.length ? <div className="risk-counts">{data.weather_daily.map((row) => <div key={row.location + row.source}>
              <span>{locationName(row.location, locations)} · {row.source}<br /><small>{row.first_date} to {row.last_date}</small></span>
              <span>{row.days_with_rainfall} days · {row.missing_days_between} gaps</span></div>)}</div> :
              <Empty title="No warehouse weather coverage" detail="Historical source rows appear after ETL." />}
            <details className="flood-disclosure"><summary>Raw provider coverage and missing values</summary>
              {!data.weather_provider_grids.some((row) => row.feed === "forecast") && <p>No stored raw forecast coverage.</p>}
              {data.weather_provider_grids.map((row, i) => <p key={row.point + row.source + i}>{row.point} · {row.source} · {row.rows} rows · {localTime(row.first_valid)} to {localTime(row.last_valid)} ICT</p>)}
              {Object.entries(data.weather_hourly_nulls[0] ?? {}).map(([key, count]) => <p key={key}>{label(key)} · {count}</p>)}
            </details>
          </Panel>
          <Panel title="Flood-event coverage">
            {data.events.length ? <div className="risk-counts">{data.events.map((row) =>
              <div key={row.event_key}><span>{row.locality_as_reported}<br /><small>{localTime(row.started_at)} to {localTime(row.ended_before)} ICT</small></span>
                <a href={row.source_ref} target="_blank" rel="noreferrer">Evidence</a></div>)}</div> :
              <Empty title="No registered flood events" detail="Only traceable event records are shown." />}
          </Panel>
          <Panel title="Terrain coverage">
            {data.terrain.length ? <div className="risk-counts">{[...new Set(data.terrain.map((row) => row.source))].map((source) => {
              const rows = data.terrain.filter((row) => row.source === source);
              return <div key={source}><span>{source}</span><span>{new Set(rows.map((row) => row.point)).size} points · {rows.length} features</span></div>;
            })}</div> : <Empty title="No terrain coverage" detail="Terrain appears after verified feature ingestion." />}
          </Panel>
          <Panel title="Hydrological coverage">
            {data.hydrology.length ? <div className="risk-counts">{data.hydrology.map((row) => <div key={row.station_key + row.variable + row.source}>
              <span>{row.station_key} · {label(row.variable)}<br /><small>{localTime(row.first_valid)} to {localTime(row.last_valid)} ICT</small></span>
              <span>{row.rows} rows · {row.missing_hours_between} missing hours</span></div>)}</div> :
              <Empty title="No hydrological coverage" detail="Hydrological observations appear when a verified source is loaded." />}
          </Panel>
        </div>
      </>}</Resource>
    </Panel>
    <Panel title="Model training readiness">
      <Resource query={readiness}>{({ readiness: report }) => <>
        <p className="flood-notice">{label(report.status)}</p>
        <div className="risk-counts">{Object.entries(report.inventory).map(([key, count]) => <div key={key}><span>{label(key)}</span><strong>{count}</strong></div>)}</div>
        {report.blocking_inventory.length > 0 && <p className="metric-note">Blocked by {report.blocking_inventory.map(label).join(", ")}.</p>}
      </>}</Resource>
    </Panel>
    <Panel title="Assessment history" subtitle="Latest persisted location assessments, including abstentions">
      <Resource query={history} empty={<Empty title="No assessment history" detail="Generate assessments from Flood Risk Forecast." />}>
        {(rows) => <div className="table-wrap"><table className="flood-table"><thead><tr><th>Point</th><th>Issued · ICT</th><th>Stored · ICT</th><th>Category at issue</th><th>Method</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id}><th scope="row">{locationName(row.location, locations)}</th><td>{localTime(row.issued_at)}</td>
            <td>{localTime(row.created_at)}</td><td><RiskBadge category={row.risk_category} /></td><td>{row.method_version}</td></tr>)}</tbody></table></div>}
      </Resource>
    </Panel>
  </>;
}
