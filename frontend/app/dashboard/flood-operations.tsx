"use client";

import { useText } from "./language";

import { displayNumber, localTime, locationName, useData, type Location } from "./data";
import { formatProbability, label, probabilityHelp, type Assessment, type FloodCoverage,
  type FloodMetrics, type FloodPrediction, type FloodProfiles } from "./flood-data";
import { Chart } from "./chart";
import { RiskBadge } from "./flood-panels";
import { Empty, Panel, Resource } from "./ui";

type Theme = "dark" | "light";

export function FloodMachineLearning({ locations, theme }: { locations: Location[]; theme: Theme }) {
  const t = useText();
  const predictions = useData<FloodPrediction[]>("flood-predictions/results", { limit: 30 }, true, 60_000);
  const metrics = useData<FloodMetrics>("flood-predictions/metrics", undefined, true, 60_000);
  const profiles = useData<FloodProfiles>("clustering/flood-profiles");

  const hasBinaryPredictions = (predictions.data?.length ?? 0) > 0;
  const hasBinaryEvaluation = Boolean(metrics.data?.evaluation?.test);

  return <>
    <Panel title={t("Terrain-based flood risk clustering")} subtitle={t("Terrain and built-up clustering across 9 Da Nang stations")}>
      <Resource query={profiles}>{(data) => <>
        <p className="metric-note">{data.complete_points} {t("points")} · Silhouette {displayNumber(data.silhouette_in_sample, 3)}</p>
        <Chart label={t("Flood terrain profile groups")} theme={theme} option={{
          xAxis: { type: "value", name: t("Elevation (m)") }, yAxis: { type: "value", name: t("Slope (°)") },
          series: [...new Set(data.assignments.map((row) => row.cluster_id))].map((id) => ({
            type: "scatter", name: t("Group") + " " + id, symbolSize: 12,
            data: data.assignments.filter((row) => row.cluster_id === id).map((row) => ({
              name: locationName(row.location, locations), value: [row.features.elevation_m, row.features.surface_slope_deg],
            })),
          })),
        }} />
      </>}</Resource>
    </Panel>
    {hasBinaryPredictions && <Panel title={t("Flood probability predictions")} subtitle={t("Approved model results and threshold-based flood classification")}>
      <Resource query={predictions}>
        {(rows) => <div className="table-wrap"><table className="flood-table"><thead><tr>
          <th>{t("Point")}</th><th title={t(probabilityHelp)}>{t("Probability")}</th><th>{t("Classification")}</th><th>{t("Issued · ICT")}</th><th>{t("Valid until · ICT")}</th><th>{t("Version")}</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id ?? row.location + row.issued_at}><th scope="row">{locationName(row.location, locations)}</th>
            <td title={t(probabilityHelp)}>{t(formatProbability(row.flood_probability))}</td><td>{t(label(row.risk_classification))}</td>
            <td>{localTime(row.issued_at)}</td><td>{localTime(row.valid_until)}</td><td>{row.model_version ?? "—"}</td></tr>)}</tbody></table></div>}
      </Resource>
    </Panel>}
    {hasBinaryEvaluation && <Panel title={t("Flood model evaluation")} subtitle={t("Held-out performance and validation status")}>
      <Resource query={metrics}>{(data) => {
        const test = data.evaluation?.test;
        const confusion = test?.confusion;
        const calibration = test?.calibration_curve;
        const importance = Object.entries(data.evaluation?.feature_importance ?? {});
        return <>
          <p className="flood-notice">{t(label(data.status))}{data.version && <> · {data.version}</>}</p>
          {test && <div className="risk-counts flood-context">{[
            ["Precision", test.precision, t("Share of alerts that matched a confirmed positive.")],
            ["Recall", test.recall, t("Share of confirmed positive examples that received an alert.")],
            ["F1", test.f1, t("Harmonic mean of precision and recall.")],
            ["PR-AUC", test.pr_auc_average_precision, t("Average precision summarizes precision at different recall levels.")],
            ["ROC-AUC", test.roc_auc, t("Ranking discrimination across decision thresholds.")],
            ["Brier Score", test.brier, t("Mean squared probability error. Lower is better.")],
          ].map(([name, value, tip]) => <div key={name as string} title={tip as string}><span>{name}</span><strong>{displayNumber(value as number | null, 3)}</strong></div>)}</div>}
          <div className="two-col grid">
            {confusion && <Panel title={t("Confusion matrix")} subtitle={t("Observed versus threshold-based classification")}>
              <Chart label={t("Flood confusion matrix")} theme={theme} option={{
                xAxis: { type: "category", data: [t("Dry"), t("Flood")] }, yAxis: { type: "category", data: [t("Dry"), t("Flood")] },
                visualMap: { min: 0, max: Math.max(1, ...Object.values(confusion)) },
                series: [{ type: "heatmap", label: { show: true }, data: [[0, 0, confusion.tn], [1, 0, confusion.fp], [0, 1, confusion.fn], [1, 1, confusion.tp]] }],
              }} />
            </Panel>}
            {calibration?.length ? <Panel title={t("Calibration curve")} subtitle={t("Predicted probability versus observed flood frequency")}>
              <Chart label={t("Flood probability calibration")} theme={theme} option={{
                xAxis: { type: "value", min: 0, max: 1, name: t("Probability") }, yAxis: { type: "value", min: 0, max: 1, name: t("Observed") },
                series: [{ type: "line", name: t("Perfect calibration"), data: [[0, 0], [1, 1]], lineStyle: { type: "dashed" } },
                  { type: "scatter", name: t("Calibration bins"), data: calibration.map((bin) => [bin.mean_probability, bin.positive_fraction, bin.count]) }],
              }} />
            </Panel> : null}
            {data.evaluation?.candidates?.length ? <Panel title={t("Model comparison")} subtitle={t("Candidate selection-split evaluation")}>
              <div className="table-wrap"><table className="flood-table"><thead><tr><th>{t("Candidate")}</th><th>{t("Calibration")}</th><th>Brier</th><th>{t("Status")}</th></tr></thead>
                <tbody>{data.evaluation.candidates.map((candidate) => <tr key={candidate.candidate + candidate.method}>
                  <td>{t(label(candidate.candidate))}</td><td>{candidate.method}</td><td>{displayNumber(candidate.calibrated_selection?.brier, 3)}</td>
                  <td>{candidate.status ? label(candidate.status) : t("Evaluated")}</td></tr>)}</tbody></table></div>
            </Panel> : null}
            {importance.length ? <Panel title={t("Feature importance")} subtitle={t("Raw candidate · change in selection Brier loss after permutation")}>
              <div className="risk-counts">{importance.sort((a, b) => b[1] - a[1]).map(([key, value]) =>
                <div key={key}><span>{t(label(key))}</span><strong>{displayNumber(value, 4)}</strong></div>)}</div>
            </Panel> : null}
          </div>
        </>;
      }}</Resource>
    </Panel>}
  </>;
}

export function FloodDataManagement({ locations }: { locations: Location[] }) {
  const t = useText();
  const coverage = useData<FloodCoverage>("flood-data/coverage");
  const readiness = useData<FloodMetrics>("flood-predictions/metrics", undefined, true, 60_000);
  const history = useData<Assessment[]>("flood-risk/history", { limit: 25 }, true, 60_000);
  return <>
    <Panel title={t("Flood dataset coverage")} subtitle={t("Registered observations, features and provider coverage")}>
      <Resource query={coverage}>{(data) => <>
        <div className="flood-context flood-data-counts grid">{[
          [t("Documented events"), data.counts.flood_events],
          [t("Confirmed flood labels"), data.label_counts.flood_confirmed],
          [t("Confirmed non-flood labels"), data.label_counts.non_flood_confirmed],
          [t("Recorded unknown labels"), data.label_counts.unknown],
          [t("Terrain features"), data.counts.flood_terrain_features],
          [t("Hydrological observations"), data.counts.flood_hydrology_observations],
        ].map(([name, count]) => <div key={name}><span>{name}</span><strong>{count ?? "—"}</strong></div>)}</div>
        <div className="two-col grid">
          <Panel title={t("Weather source coverage")}>
            {data.weather_daily.length ? <div className="risk-counts">{data.weather_daily.map((row) => <div key={row.location + row.source}>
              <span>{locationName(row.location, locations)} · {row.source}<br /><small>{row.first_date} {t("to")} {row.last_date}</small></span>
              <span>{row.days_with_rainfall} {t("days")} · {row.missing_days_between} {t("gaps")}</span></div>)}</div> :
              <Empty title={t("No warehouse weather coverage")} detail={t("Historical source rows appear after ETL.")} />}
            <details className="flood-disclosure"><summary>{t("Raw provider coverage and missing values")}</summary>
              {!data.weather_provider_grids.some((row) => row.feed === "forecast") && <p>{t("No stored raw forecast coverage.")}</p>}
              {data.weather_provider_grids.map((row, i) => <p key={row.point + row.source + i}>{row.point} · {row.source} · {row.rows} {t("rows")} · {localTime(row.first_valid)} {t("to")} {localTime(row.last_valid)} ICT</p>)}
              {Object.entries(data.weather_hourly_nulls[0] ?? {}).map(([key, count]) => <p key={key}>{t(label(key))} · {count}</p>)}
            </details>
          </Panel>
          <Panel title={t("Flood-event coverage")}>
            {data.events.length ? <div className="risk-counts">{data.events.map((row) =>
              <div key={row.event_key}><span>{row.locality_as_reported}<br /><small>{localTime(row.started_at)} {t("to")} {localTime(row.ended_before)} ICT</small></span>
                <a href={row.source_ref} target="_blank" rel="noreferrer">{t("Evidence")}</a></div>)}</div> :
              <Empty title={t("No registered flood events")} detail={t("Only traceable event records are shown.")} />}
          </Panel>
          <Panel title={t("Terrain coverage")}>
            {data.terrain.length ? <div className="risk-counts">{[...new Set(data.terrain.map((row) => row.source))].map((source) => {
              const rows = data.terrain.filter((row) => row.source === source);
              return <div key={source}><span>{source}</span><span>{new Set(rows.map((row) => row.point)).size} {t("points")} · {rows.length} {t("features")}</span></div>;
            })}</div> : <Empty title={t("No terrain coverage")} detail={t("Terrain appears after verified feature ingestion.")} />}
          </Panel>
          <Panel title={t("Hydrological coverage")}>
            {data.hydrology.length ? <div className="risk-counts">{data.hydrology.map((row) => <div key={row.station_key + row.variable + row.source}>
              <span>{row.station_key} · {t(label(row.variable))}<br /><small>{localTime(row.first_valid)} {t("to")} {localTime(row.last_valid)} ICT</small></span>
              <span>{row.rows} {t("rows")} · {row.missing_hours_between} {t("missing hours")}</span></div>)}</div> :
              <Empty title={t("No hydrological coverage")} detail={t("Hydrological observations appear when a verified source is loaded.")} />}
          </Panel>
        </div>
      </>}</Resource>
    </Panel>
    <Panel title={t("Historical training dataset summary")}>
      <Resource query={readiness}>{({ readiness: report }) => <>
        <div className="risk-counts">{Object.entries(report.inventory).map(([key, count]) => <div key={key}><span>{t(label(key))}</span><strong>{count}</strong></div>)}</div>
      </>}</Resource>
    </Panel>
    <Panel title={t("Assessment history")} subtitle={t("Latest persisted location assessments")}>
      <Resource query={history} empty={<Empty title={t("No assessment history")} detail={t("Generate assessments from Flood Risk Forecast.")} />}>
        {(rows) => <div className="table-wrap"><table className="flood-table"><thead><tr><th>{t("Point")}</th><th>{t("Issued · ICT")}</th><th>{t("Stored · ICT")}</th><th>{t("Category at issue")}</th><th>{t("Method")}</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id}><th scope="row">{locationName(row.location, locations)}</th><td>{localTime(row.issued_at)}</td>
            <td>{localTime(row.created_at)}</td><td><RiskBadge category={row.risk_category} /></td><td>{row.method_version}</td></tr>)}</tbody></table></div>}
      </Resource>
    </Panel>
  </>;
}
