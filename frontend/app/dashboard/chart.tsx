"use client";

import { useEffect, useRef } from "react";
import { init, use as registerCharts, type ECharts } from "echarts/core";
import type { EChartsOption } from "echarts";
import { BarChart, HeatmapChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent, DatasetComponent, DataZoomComponent, GridComponent, LegendComponent,
  TooltipComponent, VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

registerCharts([BarChart, HeatmapChart, LineChart, ScatterChart, AriaComponent, DatasetComponent,
  DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, CanvasRenderer]);

type Theme = "dark" | "light";

export function Chart({ option, label, theme, compact = false }: {
  option: EChartsOption; label: string; theme: Theme; compact?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  useEffect(() => {
    if (!host.current) return;
    const instance = init(host.current);
    chart.current = instance;
    const resize = new ResizeObserver(() => instance.resize());
    resize.observe(host.current);
    return () => { resize.disconnect(); instance.dispose(); chart.current = null; };
  }, []);
  useEffect(() => {
    const dark = theme === "dark";
    const muted = dark ? "#94A8BE" : "#64748B";
    const grid = dark ? "#263F5D" : "#E2E8F0";
    const series = option.series as { type?: string; name?: string }[] | undefined;
    const heatmap = series?.some((item) => item.type === "heatmap");
    const zoom = series?.some((item) => item.type === "line" || item.type === "scatter");
    const axis = (value: unknown) => ({
      axisLabel: { color: muted, hideOverlap: true },
      nameTextStyle: { color: muted },
      axisLine: { lineStyle: { color: grid } },
      splitLine: { lineStyle: { color: grid } },
      ...(value as object ?? {}),
    });
    chart.current?.setOption({
      ...option,
      aria: { enabled: true, label: { description: label } },
      animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
      animationDuration: 360,
      color: ["#2878B5", "#368F91", "#E9A23B", "#17365D", "#299D70"],
      textStyle: { color: muted, fontFamily: "Manrope Variable, system-ui" },
      grid: { top: 44, right: 24, bottom: zoom && !compact ? 74 : 45,
              left: heatmap ? 104 : 60, containLabel: true },
      xAxis: axis(option.xAxis),
      yAxis: axis(option.yAxis),
      legend: { top: 4, textStyle: { color: muted }, ...(option.legend as object ?? {}) },
      tooltip: {
        confine: true,
        renderMode: "richText",
        trigger: zoom ? "axis" : "item",
        backgroundColor: dark ? "#16283E" : "#FFFFFF",
        borderColor: dark ? "#263F5D" : "#E2E8F0",
        textStyle: { color: dark ? "#E8EFF7" : "#243449" },
        ...(option.tooltip as object ?? {}),
      },
      ...(heatmap ? { visualMap: { ...(option.visualMap as object), bottom: 0, left: "center",
        orient: "horizontal", textStyle: { color: muted },
        inRange: { color: dark ? ["#1C324C", "#2878B5", "#368F91"] : ["#EBF3FA", "#5B9BD5", "#17365D"] } } } : {}),
      ...(zoom ? { dataZoom: [{ type: "inside", xAxisIndex: 0, zoomOnMouseWheel: "ctrl" },
        ...(!compact ? [{ type: "slider", height: 18, bottom: 8, xAxisIndex: 0,
                         textStyle: { color: muted }, borderColor: grid }] : [])] } : {}),
    }, { notMerge: true });
  }, [compact, label, option, theme]);
  return <div ref={host} role="img" aria-label={label} className={compact ? "chart chart-compact" : "chart"} />;
}
