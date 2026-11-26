import type { EChartsOption } from "echarts";
import type { DateRange, Rain } from "./data";

export type Period = "daily" | "weekly" | "monthly";
export const periods: Period[] = ["daily", "weekly", "monthly"];

export function rainfallOption(rows: Rain[], range: DateRange, period: Period, t: (text: string) => string = (text) => text): EChartsOption {
  const byDate = new Map(rows.map((row) => [row.period_start, row.rainfall_total_mm]));
  const cursor = new Date(range.start_date + "T00:00:00Z");
  const end = new Date(range.end_date + "T00:00:00Z");
  if (period === "weekly") cursor.setUTCDate(cursor.getUTCDate() - ((cursor.getUTCDay() + 6) % 7));
  if (period === "monthly") cursor.setUTCDate(1);
  const points: [string, number | null][] = [];
  while (cursor <= end) {
    const day = cursor.toISOString().slice(0, 10);
    points.push([day, byDate.get(day) ?? null]);
    if (period === "monthly") cursor.setUTCMonth(cursor.getUTCMonth() + 1);
    else cursor.setUTCDate(cursor.getUTCDate() + (period === "weekly" ? 7 : 1));
  }
  return {
    tooltip: { trigger: "axis" },
    dataset: { dimensions: [t("Date"), t("Rainfall (mm)")], source: points },
    xAxis: { type: "category", boundaryGap: false },
    yAxis: { type: "value", name: "mm" },
    series: [{ type: "line", name: t("Historical rainfall"), connectNulls: false, showSymbol: true,
      symbolSize: 5, lineStyle: { width: 2.5 }, areaStyle: { opacity: .12 }, encode: { x: 0, y: 1 } }],
  };
}

export function latestRain(rows: Rain[]) {
  const latest: Record<string, Rain> = Object.create(null);
  for (const row of rows) {
    if (!latest[row.location] || latest[row.location].period_start < row.period_start) latest[row.location] = row;
  }
  return latest;
}

