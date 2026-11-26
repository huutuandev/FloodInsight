"use client";

import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";

export type Location = { code: string; name: string; latitude: number; longitude: number };
export type Weather = {
  location_code: string; valid_at: string; received_at: string;
  payload: {
    location?: Location;
    values: Record<string, number | null>;
    interval_seconds?: number;
  };
};
export type Rain = {
  location: string; source: string; period_start: string; period_end: string;
  rainfall_total_mm: number | null; rainfall_hours: number; expected_hours: number;
};
export type Pattern = {
  name: string; status: string; option: EChartsOption; generated_at: string;
};
export type Cluster = {
  location: string; window_start_utc: string; cluster_label: number;
  details: { pc1?: number; pc2?: number };
};
export type Prediction = { location: string; target_date: string; issued_at: string; rainfall_mm: number };
export type Classification = {
  location: string; target_date: string; issued_at: string; label: string;
  confidence: number | null; probabilities: Record<string, number>;
};
export type ProviderForecast = {
  location: string; source: string; valid_at: string; issued_at: string | null;
  received_at: string; payload: { model?: string; values?: Record<string, number | null> };
};
export type Evaluation = {
  version: string;
  scope?: { availability?: string };
  metrics: {
    samples?: number; silhouette_score?: number;
    test?: {
      random_forest?: { mae_mm: number; rmse_mm: number };
      lag_8_persistence?: { mae_mm: number; rmse_mm: number };
      f1_macro?: number; precision_macro?: number; recall_macro?: number;
      confusion_matrix?: number[][];
    };
  };
  class_order?: string[];
};
export type Run = {
  id: number; status: string; started_at: string; finished_at: string | null;
  records_inserted?: number | null; operation?: string; trigger?: string | null;
  error_message?: string | null;
};
export type Warehouse = { runs: Run[]; downloaded_batches: number; loaded_batches: number };
export type Quality = {
  id: number; location_code: string; start_date: string; end_date: string;
  quality: { rainfall_coverage_hours?: number; expected_hours?: number; missing_raw_timestamps?: number };
};
export type Status = { status: string; services: Record<string, { status: string }> };
export type DateRange = { start_date: string; end_date: string };
export type Scope = DateRange & { location: string };
type Params = Record<string, string | number | undefined>;
type Envelope<T> = { data: T; meta?: { has_more?: boolean }; error?: { message?: string } };

export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

export async function request<T>(path: string, params?: Params, signal?: AbortSignal, body?: object) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const response = await fetch("/api/backend/" + path + (query.size ? "?" + query : ""), {
    signal,
    ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
  });
  const json = await response.json().catch(() => null) as Envelope<T> | null;
  if (!response.ok || !json || !("data" in json)) {
    throw new ApiError(response.status, json?.error?.message || "Unable to load this resource.");
  }
  return json;
}

export function useData<T>(path: string, params?: Params, enabled = true, poll?: number) {
  return useQuery({
    queryKey: [path, params],
    queryFn: async ({ signal }) => (await request<T>(path, params, signal)).data,
    enabled,
    refetchInterval: poll,
  });
}

export function useCollection<T>(path: string, params: Params, enabled = true) {
  return useQuery({
    queryKey: [path, params, "all"],
    enabled,
    queryFn: async ({ signal }) => {
      const all: T[] = [];
      const limit = 500;
      const windows = path.startsWith("rainfall/") && typeof params.start_date === "string" && typeof params.end_date === "string"
        ? rainfallWindows({ start_date: params.start_date, end_date: params.end_date }) : [params];
      for (const window of windows) {
        for (let offset = 0; ; offset += limit) {
          if (offset > 1_000_000) throw new Error("Select a smaller date range to load this collection.");
          const page = await request<T[]>(path, { ...params, ...window, limit, offset }, signal);
          all.push(...page.data);
          if (!page.meta?.has_more) break;
        }
      }
      return windows.length === 1 ? all : [...new Map(all.map(row => {
        const rain = row as Rain;
        return [JSON.stringify([rain.location, rain.source, rain.period_start]), row];
      })).values()];
    },
  });
}

export const source = "open-meteo-archive-era5";
export const vietnam = "Asia/Ho_Chi_Minh";
export function displayNumber(value: number | null | undefined, digits = 1) {
  return value == null ? "—" : new Intl.NumberFormat("en", { maximumFractionDigits: digits }).format(value);
}
export function localTime(timestamp?: string | null) {
  return timestamp ? new Intl.DateTimeFormat("en-GB", {
    timeZone: vietnam, dateStyle: "medium", timeStyle: "short",
  }).format(new Date(timestamp)) : "—";
}
export function localDay(timestamp: string) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: vietnam, year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(timestamp));
}
export function locationName(code: string, locations: Location[]) {
  return locations.find((location) => location.code === code)?.name ?? code;
}
export function withWeatherLocations(locations: Location[], weather: Weather[]) {
  const known = new Map(locations.map((location) => [location.code, location]));
  for (const point of weather) {
    const location = point.payload.location;
    if (location && !known.has(location.code)) known.set(location.code, location);
  }
  return [...known.values()].sort((a, b) => a.name.localeCompare(b.name, "vi"));
}

export type RainfallCoverage = { location: string; source: string; first_date: string; last_date: string };

export function recentCoveredRange(coverage: RainfallCoverage | undefined, fallback: DateRange): DateRange {
  if (!coverage) return fallback;
  return {
    start_date: coverage.first_date || fallback.start_date,
    end_date: coverage.last_date || fallback.end_date,
  };
}

export function coveredPreset(coverage: DateRange, days: number): DateRange {
  const start = new Date(coverage.end_date + "T00:00:00Z");
  start.setUTCDate(start.getUTCDate() - days + 1);
  return { start_date: [coverage.start_date, start.toISOString().slice(0, 10)].sort()[1], end_date: coverage.end_date };
}

function rainfallWindows(range: DateRange): DateRange[] {
  const windows: DateRange[] = [];
  let remainder = range;
  while ((Date.parse(remainder.end_date) - Date.parse(remainder.start_date)) / 86_400_000 >= 3660) {
    const window = coveredPreset(remainder, 3660);
    windows.push(window);
    const priorDay = new Date(Date.parse(window.start_date) - 86_400_000);
    remainder = { ...range, end_date: priorDay.toISOString().slice(0, 10) };
  }
  return [...windows, remainder];
}
