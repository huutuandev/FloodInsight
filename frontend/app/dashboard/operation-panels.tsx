"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, Database, Layers3, RefreshCw, Sparkles } from "lucide-react";
import type { EChartsOption } from "echarts";
import { Chart } from "./chart";
import { ForecastPanel } from "./forecast-panel";
import { OutlookHistory } from "./outlook-history";
import {
  displayNumber, localDay, localTime, locationName, request, useData,
  type Cluster, type Evaluation, type Location,
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

function clusterOption(rows: Cluster[], locations: Location[]): EChartsOption {
  const groups = new Map<number, [number, number, string, string][]>();
  for (const row of rows) {
    if (row.details.pc1 == null || row.details.pc2 == null) continue;
    const locName = locationName(row.location, locations);
    const dateStr = localDay(row.window_start_utc);
    groups.set(row.cluster_label, [...(groups.get(row.cluster_label) ?? []),
      [row.details.pc1, row.details.pc2, locName, dateStr]]);
  }

  const clusterColors = ["#2878B5", "#368F91", "#E9A23B", "#17365D", "#299D70", "#D9534F"];

  return {
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const p = params as { data?: [number, number, string, string]; seriesName?: string };
        const [pc1, pc2, loc, date] = p.data || [];
        return `<div style="font-size:12px; line-height:1.5;">
          <strong style="color:#17365D;">${loc ?? ""}</strong> · ${date ?? ""}<br/>
          <span style="color:#64748B;">Cụm / Cluster:</span> <b>${p.seriesName ?? ""}</b><br/>
          <span>PC1: <b>${displayNumber(pc1, 2)}</b> | PC2: <b>${displayNumber(pc2, 2)}</b></span>
        </div>`;
      },
    },
    color: clusterColors,
    xAxis: { name: "PC1", type: "value", splitLine: { show: true } },
    yAxis: { name: "PC2", type: "value", splitLine: { show: true } },
    series: [...groups.entries()].sort(([a], [b]) => a - b)
      .map(([id, data]) => ({
        type: "scatter",
        name: `Cụm ${id}`,
        data,
        symbolSize: 9,
        itemStyle: { opacity: 0.88 },
        emphasis: { itemStyle: { opacity: 1, borderWidth: 2 } },
      })),
  };
}

function Confusion({ labels, matrix, theme }: { labels: string[]; matrix: number[][]; theme: Theme }) {
  const cells = matrix.flatMap((row, y) => row.map((count, x) => [x, y, count]));
  const maxVal = Math.max(1, ...cells.map((cell) => cell[2]));
  return <Chart theme={theme} label="Rainfall classification confusion matrix" option={{
    tooltip: {
      formatter: (params: unknown) => {
        const p = params as { data: [number, number, number] };
        const [x, y, val] = p.data;
        return `Thực tế (Actual): <b>${labels[y]}</b><br/>Dự đoán (Predicted): <b>${labels[x]}</b><br/>Số mẫu: <b>${val}</b>`;
      },
    },
    xAxis: { type: "category", name: "Dự đoán (Predicted)", data: labels },
    yAxis: { type: "category", name: "Thực tế (Actual)", data: labels },
    visualMap: {
      min: 0,
      max: maxVal,
      calculable: true,
    },
    series: [{
      type: "heatmap",
      data: cells,
      label: { show: true, fontWeight: "bold" },
    }],
  }} />;
}

export function MachineLearning({ scope, filterForecasts, locations, theme }: { scope: Scope; filterForecasts: boolean; locations: Location[]; theme: Theme }) {
  const clusters = useData<Cluster[]>("clustering/results", { ...scope, limit: 500 });
  const clusterMetrics = useData<Evaluation>("clustering/metrics");
  const predictMetrics = useData<Evaluation>("predictions/metrics");
  const classMetrics = useData<Evaluation>("classifications/metrics");
  return <>
    <ForecastPanel location={scope.location}
      range={filterForecasts ? { start_date: scope.start_date, end_date: scope.end_date } : undefined} />
    <OutlookHistory location={scope.location} range={filterForecasts ? scope : undefined} />
    <Panel
      title="Phân cụm hình thế thời tiết (K-Means Clustering)"
      headingLabel="Weather clusters"
      subtitle="Chiếu không gian thành phần chính (PCA 2D) từ mô hình K-Means đã huấn luyện · Tối đa 500 kết quả"
      action={<Sparkles className="accent" size={19} />}
    >
      <Resource query={clusters} missingModel>{(rows) => {
        const option = clusterOption(rows, locations);
        return Array.isArray(option.series) && option.series.length
          ? <Chart theme={theme} option={option} label="Weather cluster projection" />
          : <Empty title="Chưa có tọa độ chiếu PCA" />;
      }}</Resource>
      <Resource query={clusterMetrics} missingModel>{(value) => <div className="metrics-inline">
        <span>Mẫu huấn luyện: <strong>{displayNumber(value.metrics.samples, 0)}</strong></span>
        <span>Hệ số Silhouette: <strong style={{ color: "var(--ocean)" }}>{displayNumber(value.metrics.silhouette_score, 3)}</strong></span>
        {value.version && <span>Phiên bản: <code>{value.version.slice(0, 10)}</code></span>}
      </div>}</Resource>
    </Panel>

    <div className="two-col grid">
      <Panel
        title="Đánh giá mô hình hồi quy (Regression Evaluation)"
        headingLabel="Regression evaluation"
        subtitle="Tập kiểm thử độc lập (Held-out test set) · Đơn vị sai số: milimét (mm)"
      >
        <Resource query={predictMetrics} missingModel>{(data) => {
          const test = data.metrics.test;
          const regression = test?.xgboost ?? test?.random_forest;
          const baseline = test?.lag_8_persistence ?? test?.lag_1_persistence;
          return regression ? <div className="table-wrap"><table>
            <caption>Đánh giá chế độ {data.scope?.availability ?? "Recorded"}</caption>
            <thead><tr><th>Mô hình</th><th>MAE (mm)</th><th>RMSE (mm)</th></tr></thead>
            <tbody>
              <tr>
                <td><strong>{test?.xgboost ? "XGBoost Regressor" : "Random Forest Regressor"}</strong></td>
                <td><strong style={{ color: "var(--ocean)" }}>{displayNumber(regression.mae_mm, 2)}</strong></td>
                <td><strong>{displayNumber(regression.rmse_mm, 2)}</strong></td>
              </tr>
              {baseline && <tr>
                <td>{test?.lag_8_persistence ? "Đối chứng: lượng mưa 8 ngày trước" : "Đối chứng: lượng mưa 1 ngày trước"}</td>
                <td>{displayNumber(baseline.mae_mm, 2)}</td>
                <td>{displayNumber(baseline.rmse_mm, 2)}</td>
              </tr>}
            </tbody>
          </table></div> : <Empty title="Chưa có chỉ số đánh giá mô hình" />;
        }}</Resource>
      </Panel>

      <Panel
        title="Đánh giá mô hình phân loại (Classification Evaluation)"
        headingLabel="Classification evaluation"
        subtitle="Tập kiểm thử độc lập · Độ đo phân loại cường độ mưa và Ma trận nhầm lẫn"
      >
        <Resource query={classMetrics} missingModel>{(data) => {
          const test = data.metrics.test;
          return test ? <>
            <div className="metrics-inline">
              <span>Macro F1: <strong>{displayNumber(test.f1_macro, 3)}</strong></span>
              <span>Precision: <strong>{displayNumber(test.precision_macro, 3)}</strong></span>
              <span>Recall: <strong>{displayNumber(test.recall_macro, 3)}</strong></span>
            </div>
            {data.scope?.availability && <p className="chart-note">Chế độ đánh giá: {data.scope.availability}</p>}
            {test.confusion_matrix && data.class_order && <Confusion labels={data.class_order} matrix={test.confusion_matrix} theme={theme} />}
          </> : <Empty title="Chưa có chỉ số đánh giá mô hình" />;
        }}</Resource>
      </Panel>
    </div>
  </>;
}

function Runs({ rows, warehouse = false }: { rows: Run[]; warehouse?: boolean }) {
  return <div className="table-wrap"><table>
    <thead>
      <tr>
        <th>Mã chạy</th>
        <th>{warehouse ? "Thao tác ETL" : "Kích hoạt"}</th>
        <th>Trạng thái</th>
        <th>Bắt đầu (ICT)</th>
        <th>{warehouse ? "Hoàn thành (ICT)" : "Số bản ghi nạp"}</th>
      </tr>
    </thead>
    <tbody>{rows.map((row) => <tr key={row.id} title={row.error_message ?? undefined}>
      <td><strong>#{row.id}</strong></td>
      <td>{(warehouse ? row.operation : row.trigger) ?? "—"}</td>
      <td><StatePill status={row.status} />{row.error_message && <small className="run-error">{row.error_message}</small>}</td>
      <td>{localTime(row.started_at)}</td>
      <td>{warehouse ? localTime(row.finished_at) : <strong>{displayNumber(row.records_inserted, 0)}</strong>}</td>
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
      <Panel title="Lần thu thập thành công gần nhất" headingLabel="Last successful ingestion" subtitle="Trong 99 phiên chạy gần nhất" action={<Clock3 className="accent" size={19} />}>
        {ingestHistory.isPending ? <Loading compact /> : ingestHistory.error ?
          <QueryError error={ingestHistory.error} retry={() => void ingestHistory.refetch()} />
          : <div className="summary-value">{success ? localTime(success.finished_at) + " ICT" : "Chưa có phiên thành công"}</div>}
      </Panel>
      <Panel title="Gói dữ liệu thô đã tải" headingLabel="Downloaded batches" subtitle="Lô lưu trữ từ Open-Meteo" action={<Database className="accent" size={19} />}>
        {warehouse.isPending ? <Loading compact /> : <div className="summary-value">{displayNumber(warehouse.data?.downloaded_batches, 0)}</div>}
      </Panel>
      <Panel title="Gói dữ liệu đã nạp ETL" headingLabel="Loaded ETL batches" subtitle="Đã chuẩn hóa vào Star Schema" action={<Layers3 className="accent" size={19} />}>
        {warehouse.isPending ? <Loading compact /> : <div className="summary-value">{displayNumber(warehouse.data?.loaded_batches, 0)}</div>}
      </Panel>
    </div>

    <Panel
      title="Lịch sử thu thập dữ liệu (Ingestion History)"
      headingLabel="Ingestion history"
      subtitle="Các phiên thu thập dữ liệu khí tượng từ Open-Meteo"
      action={<button className="button primary" aria-label="Run ingestion" onClick={() => ingest.mutate()} disabled={ingest.isPending}>
        <RefreshCw size={14} className={ingest.isPending ? "spin" : ""} />
        {ingest.isPending ? "Đang thu thập…" : "Thu thập ngay"}
      </button>}
    >
      {ingest.error && <QueryError error={ingest.error} retry={() => ingest.mutate()} />}
      {ingest.isSuccess && <p className="chart-note" role="status" style={{ color: "var(--success)" }}>✓ Phiên thu thập #{ingest.data.data.id} đã hoàn tất thành công.</p>}
      <Resource query={history}>{(page) => page.data.length ? <Runs rows={page.data} /> : <Empty title="Không có lịch sử thu thập trên trang này" />}</Resource>
      <Pager offset={historyOffset} limit={size} more={Boolean(history.data?.meta?.has_more)} setOffset={setHistoryOffset} />
    </Panel>

    <Panel title="Tiến trình kho dữ liệu ETL (Warehouse ETL)" headingLabel="Warehouse ETL" subtitle="Lịch sử lưu trữ và biến đổi dữ liệu vào bảng Fact & Dimension">
      <Resource query={warehouse}>{(data) => data.runs.length ? <Runs warehouse rows={data.runs} /> : <Empty title="Chưa có phiên chạy ETL" />}</Resource>
    </Panel>

    <Panel title="Chất lượng & độ bao phủ dữ liệu (Data Quality)" headingLabel="Data quality" subtitle="Độ bao phủ dữ liệu lượng mưa từ các lô ETL đã hoàn tất">
      <Resource query={quality}>{(page) => page.data.length ? <div className="table-wrap"><table>
        <thead>
          <tr>
            <th>Khu vực / Trạm</th>
            <th>Từ ngày</th>
            <th>Đến ngày</th>
            <th>Độ bao phủ lượng mưa</th>
            <th aria-label="Missing timestamps">Số mốc giờ thiếu</th>
          </tr>
        </thead>
        <tbody>{page.data.map((row) => {
          const expected = row.quality.expected_hours ?? 0;
          const covered = row.quality.rainfall_coverage_hours ?? 0;
          const pct = expected > 0 ? Math.min(100, (covered / expected) * 100) : 0;
          return <tr key={row.id}>
            <td><strong>{locationName(row.location_code, locations)}</strong></td>
            <td>{row.start_date}</td>
            <td>{row.end_date}</td>
            <td>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <div style={{ width: "54px", background: "var(--stroke)", height: "6px", borderRadius: "999px", overflow: "hidden" }}>
                  <div style={{ width: `${pct}%`, height: "100%", background: pct >= 95 ? "var(--success)" : "var(--warning)" }} />
                </div>
                <span>{displayNumber(covered, 0)} / {displayNumber(expected, 0)} h</span>
              </div>
            </td>
            <td>{displayNumber(row.quality.missing_raw_timestamps, 0)}</td>
          </tr>;
        })}</tbody>
      </table></div>
        : <Empty title="Không có báo cáo chất lượng dữ liệu trên trang này" />}</Resource>
      <Pager offset={qualityOffset} limit={size} more={Boolean(quality.data?.meta?.has_more)} setOffset={setQualityOffset} />
    </Panel>
  </>;
}
