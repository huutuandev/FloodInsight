"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, Database, Layers3 } from "lucide-react";
import type { EChartsOption } from "echarts";
import { Chart } from "./chart";
import {
  displayNumber, localDay, localTime, locationName, request, useCollection, useData,
  type Classification, type Cluster, type Evaluation, type Location, type Prediction, type ProviderForecast,
  type Quality, type Run, type Scope, type Warehouse,
} from "./data";
import { Empty, Loading, Pager, Panel, QueryError, Resource, StatePill } from "./ui";

type Theme = "dark" | "light";
const size = 8;

function usePage<T>(path: string, offset: number) {
  return useQuery({
    queryKey: [path, offset],
    queryFn: ({ signal }) => request<T[]>(path, { limit: size, offset }, signal),
  });
}

function clusterOption(rows: Cluster[]): EChartsOption {
  const groups = new Map<number, [number, number, string][]>();
  for (const row of rows) {
    if (row.details.pc1 == null || row.details.pc2 == null) continue;
    groups.set(row.cluster_label, [...(groups.get(row.cluster_label) ?? []),
      [row.details.pc1, row.details.pc2, row.location + " · " + localDay(row.window_start_utc)]]);
  }
  return {
    tooltip: { trigger: "item" }, xAxis: { name: "PC1", type: "value" }, yAxis: { name: "PC2", type: "value" },
    series: [...groups.entries()].sort(([a], [b]) => a - b)
      .map(([id, data]) => ({ type: "scatter", name: "Cluster " + id, data, symbolSize: 10 })),
  };
}

function Confusion({ labels, matrix, theme }: { labels: string[]; matrix: number[][]; theme: Theme }) {
  const cells = matrix.flatMap((row, y) => row.map((count, x) => [x, y, count]));
  return <Chart theme={theme} label="Rainfall classification confusion matrix" option={{
    tooltip: {}, xAxis: { type: "category", name: "Predicted", data: labels },
    yAxis: { type: "category", name: "Actual", data: labels },
    visualMap: { min: 0, max: Math.max(1, ...cells.map((cell) => cell[2])) },
    series: [{ type: "heatmap", data: cells, label: { show: true } }],
  }} />;
}

export function MachineLearning({ scope, filterForecasts, locations, theme }: { scope: Scope; filterForecasts: boolean; locations: Location[]; theme: Theme }) {
  const clusters = useData<Cluster[]>("clustering/results", { ...scope, limit: 500 });
  const providerForecasts = useCollection<ProviderForecast>("weather/forecasts", scope, Boolean(scope.location));
  const forecastQuery = filterForecasts ? scope : { location: scope.location };
  const predictions = useData<Prediction[]>("predictions/results", { ...forecastQuery, limit: 8 });
  const classification = useData<Classification[]>("classifications/results", { ...forecastQuery, limit: 8 });
  const clusterMetrics = useData<Evaluation>("clustering/metrics");
  const predictMetrics = useData<Evaluation>("predictions/metrics");
  const classMetrics = useData<Evaluation>("classifications/metrics");
  const dailyForecasts = new Map<string, Map<string, { total: number; hours: number }>>();
  const forecastModels = new Set<string>();
  for (const row of providerForecasts.data ?? []) {
    const rain = row.payload.values?.precipitation;
    if (rain == null) continue;
    const date = localDay(row.valid_at);
    const model = row.payload.model ?? row.source;
    forecastModels.add(model);
    const day = dailyForecasts.get(date) ?? new Map<string, { total: number; hours: number }>();
    const value = day.get(model) ?? { total: 0, hours: 0 };
    value.total += rain;
    value.hours += 1;
    day.set(model, value);
    dailyForecasts.set(date, day);
  }
  return <>
    <Panel title="Weather clusters" subtitle="Principal component projection from the trained K-means model · up to 500 results">
      <Resource query={clusters} missingModel>{(rows) => {
        const option = clusterOption(rows);
        return Array.isArray(option.series) && option.series.length
          ? <Chart theme={theme} option={option} label="Weather cluster projection" />
          : <Empty title="No PCA coordinates available" />;
      }}</Resource>
      <Resource query={clusterMetrics} missingModel>{(value) => <div className="metrics-inline">
        <span>Training samples <strong>{displayNumber(value.metrics.samples, 0)}</strong></span>
        <span>Silhouette score <strong>{displayNumber(value.metrics.silhouette_score, 3)}</strong></span>
      </div>}</Resource>
    </Panel>
      <Panel title="Provider rainfall forecast" subtitle="Daily precipitation from stored provider forecast runs. Availability depends on the selected dates and latest import.">
      <p className="chart-note">These are provider model outputs, not rain-gauge observations or certainty percentages. Daily totals sum the available hourly precipitation; the hour count is shown so incomplete days are identifiable.</p>
      <Resource query={providerForecasts}>
        {() => dailyForecasts.size ? <div className="table-wrap"><table>
          <thead><tr><th>Target date (ICT)</th>{[...forecastModels].sort().map((model) => <th key={model}>{forecastName(model)}</th>)}</tr></thead>
          <tbody>{[...dailyForecasts].sort(([a], [b]) => a.localeCompare(b)).map(([date, models]) => <tr key={date}>
            <td>{date}</td>{[...forecastModels].sort().map((model) => <td key={model}>{forecastCell(models.get(model))}</td>)}
          </tr>)}</tbody></table></div> : <Empty title="No provider forecasts for these dates"
            detail="Import the latest ECMWF/GFS forecast snapshots, then refresh. Provider forecasts usually cover only the coming days." />}
      </Resource>
    </Panel>
    <div className="two-col grid">
      <Panel title="ML next-day rainfall estimate" subtitle="Statistical model estimate for the next local day; not a multi-day forecast or an observation.">
        <Resource query={predictions} missingModel>{(rows) => <div className="table-wrap"><table>
          <thead><tr><th>Location</th><th>Target date</th><th>Predicted mm</th><th>Issued (ICT)</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.location + row.target_date + row.issued_at}>
            <td>{locationName(row.location, locations)}</td><td>{row.target_date}</td>
            <td>{displayNumber(row.rainfall_mm)}</td><td>{localTime(row.issued_at)}</td>
          </tr>)}</tbody></table></div>}</Resource>
      </Panel>
      <Panel title="Rainfall classification" subtitle="Latest stored rainfall intensity estimates">
        <Resource query={classification} missingModel>{(rows) => <div className="classification-list">
          {rows.map((row) => <details key={row.location + row.target_date + row.issued_at}>
            <summary><span>{locationName(row.location, locations)} · {row.target_date}</span>
              <strong>{row.label} {row.confidence == null ? "" : `· ${displayNumber(row.confidence * 100)}%`}</strong></summary>
            <p>Issued {localTime(row.issued_at)} ICT</p>
            {Object.entries(row.probabilities ?? {}).map(([name, value]) => <div className="probability" key={name}>
              <span>{name}</span><progress max={1} value={value} aria-label={name} /><span>{displayNumber(value * 100)}%</span>
            </div>)}
          </details>)}</div>}</Resource>
      </Panel>
    </div>
    <div className="two-col grid">
      <Panel title="Regression evaluation" subtitle="Held-out test set · error in millimeters">
        <Resource query={predictMetrics} missingModel>{(data) => {
          const test = data.metrics.test;
          return test?.random_forest ? <div className="table-wrap"><table>
            <caption>{data.scope?.availability ?? "Recorded"} evaluation</caption>
            <thead><tr><th>Model</th><th>MAE</th><th>RMSE</th></tr></thead>
            <tbody><tr><td>Random forest</td><td>{displayNumber(test.random_forest.mae_mm, 2)}</td>
              <td>{displayNumber(test.random_forest.rmse_mm, 2)}</td></tr>
              {test.lag_8_persistence && <tr><td>Persistence baseline</td><td>{displayNumber(test.lag_8_persistence.mae_mm, 2)}</td>
                <td>{displayNumber(test.lag_8_persistence.rmse_mm, 2)}</td></tr>}</tbody>
          </table></div> : <Empty title="No evaluation metrics" />;
        }}</Resource>
      </Panel>
      <Panel title="Classification evaluation" subtitle="Held-out test set · rainfall intensity">
        <Resource query={classMetrics} missingModel>{(data) => {
          const test = data.metrics.test;
          return test ? <>
            <div className="metrics-inline">
              <span>Macro F1 <strong>{displayNumber(test.f1_macro, 3)}</strong></span>
              <span>Precision <strong>{displayNumber(test.precision_macro, 3)}</strong></span>
              <span>Recall <strong>{displayNumber(test.recall_macro, 3)}</strong></span>
            </div>
            {data.scope?.availability && <p className="chart-note">{data.scope.availability} evaluation</p>}
            {test.confusion_matrix && data.class_order && <Confusion labels={data.class_order} matrix={test.confusion_matrix} theme={theme} />}
          </> : <Empty title="No evaluation metrics" />;
        }}</Resource>
      </Panel>
    </div>
  </>;
}

function forecastCell(value?: { total: number; hours: number }) {
  return value ? <>{displayNumber(value.total)} mm <small>({value.hours}/24 h)</small></> : "—";
}

function forecastName(model: string) {
  const names: Record<string, string> = {
    ecmwf_ifs025: "ECMWF IFS (mm)", gfs_seamless: "GFS Seamless (mm)",
    "open-meteo-forecast-api": "Open-Meteo forecast (mm)",
  };
  return names[model] ?? `${model} (mm)`;
}

function Runs({ rows, warehouse = false }: { rows: Run[]; warehouse?: boolean }) {
  return <div className="table-wrap"><table>
    <thead><tr><th>Run</th><th>{warehouse ? "Operation" : "Trigger"}</th><th>Status</th><th>Started (ICT)</th><th>{warehouse ? "Finished (ICT)" : "Inserted"}</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={row.id} title={row.error_message ?? undefined}>
      <td>#{row.id}</td><td>{(warehouse ? row.operation : row.trigger) ?? "—"}</td>
      <td><StatePill status={row.status} />{row.error_message && <small className="run-error">{row.error_message}</small>}</td>
      <td>{localTime(row.started_at)}</td><td>{warehouse ? localTime(row.finished_at) : displayNumber(row.records_inserted, 0)}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function DataManagement({ locations }: { locations: Location[] }) {
  const [historyOffset, setHistoryOffset] = useState(0);
  const [qualityOffset, setQualityOffset] = useState(0);
  const history = usePage<Run>("weather/ingestion/history", historyOffset);
  const ingestHistory = useData<Run[]>("weather/ingestion/history", { limit: 99 }, true, 45_000);
  const warehouse = useData<Warehouse>("weather/etl/status", undefined, true, 45_000);
  const quality = usePage<Quality>("weather/quality", qualityOffset);
  const manager = useQueryClient();
  const ingest = useMutation({
    mutationFn: async () => request<Run>("weather/ingestion/run", undefined, undefined, {}),
    onSuccess: () => {
      void manager.invalidateQueries({ queryKey: ["weather/ingestion/history"] });
      void manager.invalidateQueries({ queryKey: ["weather/latest"] });
    },
  });
  const success = ingestHistory.data?.find((row) => row.status === "succeeded");
  return <>
    <div className="data-grid grid">
      <Panel title="Last successful ingestion" subtitle="Within the most recent 99 runs" action={<Clock3 className="accent" size={19} />}>
        {ingestHistory.isPending ? <Loading compact /> : ingestHistory.error ?
          <QueryError error={ingestHistory.error} retry={() => void ingestHistory.refetch()} />
          : <div className="summary-value">{success ? localTime(success.finished_at) + " ICT" : "No successful runs"}</div>}
      </Panel>
      <Panel title="Downloaded batches" action={<Database className="accent" size={19} />}>
        {warehouse.isPending ? <Loading compact /> : <div className="summary-value">{displayNumber(warehouse.data?.downloaded_batches, 0)}</div>}
      </Panel>
      <Panel title="Loaded ETL batches" action={<Layers3 className="accent" size={19} />}>
        {warehouse.isPending ? <Loading compact /> : <div className="summary-value">{displayNumber(warehouse.data?.loaded_batches, 0)}</div>}
      </Panel>
    </div>
    <Panel title="Ingestion history" subtitle="Open-Meteo collection runs"
      action={<button className="button secondary" onClick={() => ingest.mutate()} disabled={ingest.isPending}>
        {ingest.isPending ? "Collecting…" : "Run ingestion"}</button>}>
      {ingest.error && <QueryError error={ingest.error} retry={() => ingest.mutate()} />}
      {ingest.isSuccess && <p className="chart-note" role="status">Run #{ingest.data.data.id} succeeded.</p>}
      <Resource query={history}>{(page) => page.data.length ? <Runs rows={page.data} /> : <Empty title="No ingestion runs on this page" />}</Resource>
      <Pager offset={historyOffset} limit={size} more={Boolean(history.data?.meta?.has_more)} setOffset={setHistoryOffset} />
    </Panel>
    <Panel title="Warehouse ETL" subtitle="Recent archive and transformation runs">
      <Resource query={warehouse}>{(data) => data.runs.length ? <Runs warehouse rows={data.runs} /> : <Empty title="No warehouse runs" />}</Resource>
    </Panel>
    <Panel title="Data quality" subtitle="Rainfall coverage from completed ETL batches">
      <Resource query={quality}>{(page) => page.data.length ? <div className="table-wrap"><table>
        <thead><tr><th>Location</th><th>Start</th><th>End</th><th>Rainfall coverage</th><th>Missing timestamps</th></tr></thead>
        <tbody>{page.data.map((row) => <tr key={row.id}><td>{locationName(row.location_code, locations)}</td>
          <td>{row.start_date}</td><td>{row.end_date}</td>
          <td>{displayNumber(row.quality.rainfall_coverage_hours, 0)} / {displayNumber(row.quality.expected_hours, 0)} h</td>
          <td>{displayNumber(row.quality.missing_raw_timestamps, 0)}</td></tr>)}</tbody></table></div>
        : <Empty title="No data-quality reports on this page" />}</Resource>
      <Pager offset={qualityOffset} limit={size} more={Boolean(quality.data?.meta?.has_more)} setOffset={setQualityOffset} />
    </Panel>
  </>;
}

