import { NextResponse } from "next/server";

const stationId = "afb37e83-2759-11ec-8ef9-06552145a11a";
const stationName = "Hồ Thạc Gián";
const intervalSeconds = 600;
const calendar = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Ho_Chi_Minh", year: "numeric", month: "2-digit", day: "2-digit",
});

type DailyGauge = { date: string; mm: number; intervals: number; through: string };

export async function GET(request: Request) {
  if (new URL(request.url).searchParams.get("location") !== "hai-chau") {
    return NextResponse.json({ error: { message: "Chưa có trạm đối chiếu cho điểm này." } }, { status: 404 });
  }

  const end = Math.floor(Date.now() / (intervalSeconds * 1_000)) * intervalSeconds;
  const today = calendar.format(new Date(end * 1_000));
  const start = Date.parse(today + "T00:00:00+07:00") / 1_000 - 7 * 86_400;
  const url = new URL(`https://muangap-api.danang.gov.vn/v1/stations/${stationId}`);
  url.searchParams.set("start_time", String(start));
  url.searchParams.set("end_time", String(end));

  try {
    const response = await fetch(url, {
      signal: AbortSignal.timeout(12_000), next: { revalidate: 60 },
    });
    if (!response.ok) throw new Error("Gauge upstream HTTP " + response.status);
    const result = await response.json();
    const logs = result?.data?.stats_logs;
    if (result?.status !== "success" || result?.data?.station_name !== stationName || !Array.isArray(logs)) {
      throw new Error("Unexpected gauge response");
    }

    // A station record represents the preceding ten minutes. Keep zero
    // rainfall, keep gaps missing, and discard conflicting duplicate slots.
    const unique = new Map<number, number | null>();
    for (const row of logs) {
      const time = row?.time_point;
      const mm = row?.depth;
      if (typeof time !== "number" || !Number.isInteger(time) || time % intervalSeconds
          || time <= start || time > end || typeof mm !== "number" || !Number.isFinite(mm) || mm < 0) continue;
      unique.set(time, unique.has(time) && unique.get(time) !== mm ? null : mm);
    }

    const days = new Map<string, DailyGauge>();
    for (const [time, mm] of unique) {
      if (mm == null) continue;
      const date = calendar.format(new Date((time - intervalSeconds) * 1_000));
      const through = new Date(time * 1_000).toISOString();
      const daily = days.get(date) ?? { date, mm: 0, intervals: 0, through };
      daily.mm += mm;
      daily.intervals += 1;
      if (through > daily.through) daily.through = through;
      days.set(date, daily);
    }
    return NextResponse.json({
      data: {
        station: { code: "430018", name: stationName, distance_km: 1.94 },
        days: [...days.values()].sort((a, b) => b.date.localeCompare(a.date)),
      },
    });
  } catch {
    return NextResponse.json({
      error: { message: "Không lấy được số đo từ cổng mưa ngập Đà Nẵng." },
    }, { status: 502 });
  }
}
