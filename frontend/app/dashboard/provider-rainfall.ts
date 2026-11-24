import { useEffect, useState } from "react";
import { localDay, type ProviderForecast } from "./data";

export const feeds = [
  { code: "open-meteo-ecmwf-ifs", name: "ECMWF IFS" },
  { code: "open-meteo-gfs-seamless", name: "NOAA GFS" },
] as const;
export const hourMs = 3_600_000;
const dayMs = 24 * hourMs;
const sourceCodes = new Set<string>(feeds.map((feed) => feed.code));

export function useRainfallClock() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return { now, today: localDay(new Date(now).toISOString()) };
}

export function shiftDay(day: string, offset: number) {
  return new Date(Date.parse(day + "T00:00:00Z") + offset * dayMs).toISOString().slice(0, 10);
}

export type DailyTotal = { mm: number; hours: number; through: number };

export function dailyTotals(rows: ProviderForecast[], cutoff = Infinity) {
  const totals = new Map<string, Map<string, DailyTotal>>();
  const hours = new Set<string>();
  for (const row of rows) {
    if (!sourceCodes.has(row.source)) continue;
    const end = Date.parse(row.valid_at);
    const rain = row.payload.values?.precipitation;
    const interval = row.payload.interval_seconds ?? 3600;
    if (!Number.isFinite(end) || end % hourMs || interval !== 3600
        || rain == null || !Number.isFinite(rain) || rain < 0 || end > cutoff) continue;
    const key = row.source + ":" + end;
    if (hours.has(key)) continue;
    hours.add(key);

    // Open-Meteo labels rain by the end of the preceding hour. A reading
    // labeled 00:00 ICT therefore belongs to the previous day's final hour.
    const day = localDay(new Date(end - hourMs).toISOString());
    const models = totals.get(day) ?? new Map<string, DailyTotal>();
    const total = models.get(row.source) ?? { mm: 0, hours: 0, through: 0 };
    total.mm += rain;
    total.hours += 1;
    total.through = Math.max(total.through, end);
    models.set(row.source, total);
    totals.set(day, models);
  }
  return totals;
}
