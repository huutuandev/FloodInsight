"use client";

import { useText } from "./language";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, Database, Layers3 } from "lucide-react";
import type { EChartsOption } from "echarts";
import { Chart } from "./chart";
import {
  displayNumber, localDay, localTime, locationName, request, useData,
  type Classification, type Cluster, type Evaluation, type Location, type Prediction,
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

function clusterOption(rows: Cluster[], t: (text: string) => string): EChartsOption {
  const groups = new Map<number, [number, number, string][]>();
  for (const row of rows) {
    if (row.details.pc1 == null || row.details.pc2 == null) continue;
    groups.set(row.cluster_label, [...(groups.get(row.cluster_label) ?? []),
      [row.details.pc1, row.details.pc2, row.location + " · " + localDay(row.window_start_utc)]]);
  }
  return {
    tooltip: { trigger: "item" }, xAxis: { name: "PC1", type: "value" }, yAxis: { name: "PC2", type: "value" },
    series: [...groups.entries()].sort(([a], [b]) => a - b)
      .map(([id, data]) => ({ type: "scatter", name: t("Cluster") + " " + id, data, symbolSize: 10 })),
  };
}

function Confusion({ labels, matrix, theme }: { labels: string[]; matrix: number[][]; theme: Theme }) {
  const t = useText();
  const cells = matrix.flatMap((row, y) => row.map((count, x) => [x, y, count]));
  return <Chart theme={theme} label={t("Rainfall classification confusion matrix")} option={{
    tooltip: {}, xAxis: { type: "category", name: t("Predicted"), data: labels.map(t) },
    yAxis: { type: "category", name: t("Actual"), data: labels.map(t) },
    visualMap: { min: 0, max: Math.max(1, ...cells.map((cell) => cell[2])) },
    series: [{ type: "heatmap", data: cells, label: { show: true } }],
  }} />;
}

export function MachineLearning({ scope, filterForecasts, locations, theme }: { scope: Scope; filterForecasts: boolean; locations: Location[]; theme: Theme }) {
  const t = useText();
  const clusters = useData<Cluster[]>("clustering/results", { ...scope, limit: 500 });
  const forecastQuery = filterForecasts ? scope : { location: scope.location };
  const predictions = useData<Prediction[]>("predictions/results", { ...forecastQuery, limit: 8 });
  const classification = useData<Classification[]>("classifications/results", { ...forecastQuery, limit: 8 });
  const clusterMetrics = useData<Evaluation>("clustering/metrics");
  const predictMetrics = useData<Evaluation>("predictions/metrics");
  const classMetrics = useData<Evaluation>("classifications/metrics");
  return <>
    <Panel title={t("Weather clusters")} subtitle={t("Principal component projection from the trained K-means model · up to 500 results")}>
      <Resource query={clusters} missingModel>{(rows) => {
        const option = clusterOption(rows, t);
        return Array.isArray(option.series) && option.series.length
          ? <Chart theme={theme} option={option} label={t("Weather cluster projection")} />
          : <Empty title={t("No PCA coordinates available")} />;
      }}</Resource>
      <Resource query={clusterMetrics} missingModel>{(value) => <div className="metrics-inline">
        <span>{t("Training samples")} <strong>{displayNumber(value.metrics.samples, 0)}</strong></span>
        <span>{t("Silhouette score")} <strong>{displayNumber(value.metrics.silhouette_score, 3)}</strong></span>
      </div>}</Resource>
    </Panel>
    <div className="two-col grid">
      <Panel title={t("Next-day rainfall")} subtitle={filterForecasts ? t("Stored ML predictions for the selected target dates") : t("Latest stored ML predictions")}>
        <Resource query={predictions} missingModel>{(rows) => <div className="table-wrap"><table>
          <thead><tr><th>{t("Location")}</th><th>{t("Target date")}</th><th>{t("Predicted mm")}</th><th>{t("Issued (ICT)")}</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.location + row.target_date + row.issued_at}>
            <td>{locationName(row.location, locations)}</td><td>{row.target_date}</td>
            <td>{displayNumber(row.rainfall_mm)}</td><td>{localTime(row.issued_at)}</td>
          </tr>)}</tbody></table></div>}</Resource>
      </Panel>
      <Panel title={t("Rainfall classification")} subtitle={t("Latest stored rainfall intensity estimates")}>
        <Resource query={classification} missingModel>{(rows) => <div className="classification-list">
          {rows.map((row) => <details key={row.location + row.target_date + row.issued_at}>
            <summary><span>{locationName(row.location, locations)} · {row.target_date}</span>
              <strong>{t(row.label)} {row.confidence == null ? "" : `· ${displayNumber(row.confidence * 100)}%`}</strong></summary>
            <p>{t("Issued")} {localTime(row.issued_at)} ICT</p>
            {Object.entries(row.probabilities ?? {}).map(([name, value]) => <div className="probability" key={name}>
              <span>{name}</span><progress max={1} value={value} aria-label={name} /><span>{displayNumber(value * 100)}%</span>
            </div>)}
          </details>)}</div>}</Resource>
      </Panel>
    </div>
    <div className="two-col grid">
      <Panel title={t("Regression evaluation")} subtitle={t("Held-out test set · error in millimeters")}>
        <Resource query={predictMetrics} missingModel>{(data) => {
          const test = data.metrics.test;
          return test?.random_forest ? <div className="table-wrap"><table>
            <caption>{data.scope?.availability ?? t("Recorded")} evaluation</caption>
            <thead><tr><th>{t("Model")}</th><th>MAE</th><th>RMSE</th></tr></thead>
            <tbody><tr><td>{t("Random forest")}</td><td>{displayNumber(test.random_forest.mae_mm, 2)}</td>
              <td>{displayNumber(test.random_forest.rmse_mm, 2)}</td></tr>
              {test.lag_8_persistence && <tr><td>{t("Persistence baseline")}</td><td>{displayNumber(test.lag_8_persistence.mae_mm, 2)}</td>
                <td>{displayNumber(test.lag_8_persistence.rmse_mm, 2)}</td></tr>}</tbody>
          </table></div> : <Empty title={t("No evaluation metrics")} />;
        }}</Resource>
      </Panel>
      <Panel title={t("Classification evaluation")} subtitle={t("Held-out test set · rainfall intensity")}>
        <Resource query={classMetrics} missingModel>{(data) => {
          const test = data.metrics.test;
          return test ? <>
            <div className="metrics-inline">
              <span title={t("Harmonic mean of precision and recall.")}>Macro F1 <strong>{displayNumber(test.f1_macro, 3)}</strong></span>
              <span title={t("Share of alerts that matched a confirmed positive.")}>Precision <strong>{displayNumber(test.precision_macro, 3)}</strong></span>
              <span title={t("Share of confirmed positive examples that received an alert.")}>Recall <strong>{displayNumber(test.recall_macro, 3)}</strong></span>
            </div>
            {data.scope?.availability && <p className="chart-note">{data.scope.availability} evaluation</p>}
            {test.confusion_matrix && data.class_order && <Confusion labels={data.class_order} matrix={test.confusion_matrix} theme={theme} />}
          </> : <Empty title={t("No evaluation metrics")} />;
        }}</Resource>
      </Panel>
    </div>
  </>;
}

function Runs({ rows, warehouse = false }: { rows: Run[]; warehouse?: boolean }) {
  const t = useText();
  return <div className="table-wrap"><table>
    <thead><tr><th>{t("Run")}</th><th>{warehouse ? t("Operation") : t("Trigger")}</th><th>{t("Status")}</th><th>{t("Started (ICT)")}</th><th>{warehouse ? t("Finished (ICT)") : t("Inserted")}</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={row.id} title={row.error_message ?? undefined}>
      <td>#{row.id}</td><td>{(warehouse ? row.operation : row.trigger) ?? "—"}</td>
      <td><StatePill status={row.status} />{row.error_message && <small className="run-error">{row.error_message}</small>}</td>
      <td>{localTime(row.started_at)}</td><td>{warehouse ? localTime(row.finished_at) : displayNumber(row.records_inserted, 0)}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function DataManagement({ locations }: { locations: Location[] }) {
  const t = useText();
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
      <Panel title={t("Last successful ingestion")} subtitle={t("Within the most recent 99 runs")} action={<Clock3 className="accent" size={19} />}>
        {ingestHistory.isPending ? <Loading compact /> : ingestHistory.error ?
          <QueryError error={ingestHistory.error} retry={() => void ingestHistory.refetch()} />
          : <div className="summary-value">{success ? localTime(success.finished_at) + " ICT" : t("No successful runs")}</div>}
      </Panel>
      <Panel title={t("Downloaded batches")} action={<Database className="accent" size={19} />}>
        {warehouse.isPending ? <Loading compact /> : <div className="summary-value">{displayNumber(warehouse.data?.downloaded_batches, 0)}</div>}
      </Panel>
      <Panel title={t("Loaded ETL batches")} action={<Layers3 className="accent" size={19} />}>
        {warehouse.isPending ? <Loading compact /> : <div className="summary-value">{displayNumber(warehouse.data?.loaded_batches, 0)}</div>}
      </Panel>
    </div>
    <Panel title={t("Ingestion history")} subtitle={t("Open-Meteo collection runs")}
      action={<button className="button secondary" onClick={() => ingest.mutate()} disabled={ingest.isPending}>
        {ingest.isPending ? t("Collecting…") : t("Run ingestion")}</button>}>
      {ingest.error && <QueryError error={ingest.error} retry={() => ingest.mutate()} />}
      {ingest.isSuccess && <p className="chart-note" role="status">{t("Run #")}{ingest.data.data.id} succeeded.</p>}
      <Resource query={history}>{(page) => page.data.length ? <Runs rows={page.data} /> : <Empty title={t("No ingestion runs on this page")} />}</Resource>
      <Pager offset={historyOffset} limit={size} more={Boolean(history.data?.meta?.has_more)} setOffset={setHistoryOffset} />
    </Panel>
    <Panel title={t("Warehouse ETL")} subtitle={t("Recent archive and transformation runs")}>
      <Resource query={warehouse}>{(data) => data.runs.length ? <Runs warehouse rows={data.runs} /> : <Empty title={t("No warehouse runs")} />}</Resource>
    </Panel>
    <Panel title={t("Data quality")} subtitle={t("Rainfall coverage from completed ETL batches")}>
      <Resource query={quality}>{(page) => page.data.length ? <div className="table-wrap"><table>
        <thead><tr><th>{t("Location")}</th><th>{t("Start")}</th><th>{t("End")}</th><th>{t("Rainfall coverage")}</th><th>{t("Missing timestamps")}</th></tr></thead>
        <tbody>{page.data.map((row) => <tr key={row.id}><td>{locationName(row.location_code, locations)}</td>
          <td>{row.start_date}</td><td>{row.end_date}</td>
          <td>{displayNumber(row.quality.rainfall_coverage_hours, 0)} / {displayNumber(row.quality.expected_hours, 0)} h</td>
          <td>{displayNumber(row.quality.missing_raw_timestamps, 0)}</td></tr>)}</tbody></table></div>
        : <Empty title={t("No data-quality reports on this page")} />}</Resource>
      <Pager offset={qualityOffset} limit={size} more={Boolean(quality.data?.meta?.has_more)} setOffset={setQualityOffset} />
    </Panel>
  </>;
}

