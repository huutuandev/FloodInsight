"use client";

import { displayNumber, localTime, source, useCollection, useData, type ProviderForecast, type Rain, type Weather } from "./data";
import { dailyTotals, feeds, hourMs, shiftDay, useRainfallClock } from "./provider-rainfall";
import { Empty, Panel, QueryError } from "./ui";

const pollMs = 5 * 60_000;
const clock = new Intl.DateTimeFormat("vi-VN", {
  timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit",
});

type GaugeRainfall = {
  station: { code: string; name: string; distance_km: number };
  days: { date: string; mm: number; intervals: number; through: string }[];
};

export function RecentRainfall({ location, name, weather }: {
  location: string; name: string; weather?: Weather;
}) {
  const { now, today } = useRainfallClock();
  const start = shiftDay(today, -7);
  const range = { location, start_date: start, end_date: today };
  const archive = useCollection<Rain>("rainfall/daily", { ...range, source }, Boolean(location), pollMs);
  const models = useCollection<ProviderForecast>("weather/forecasts", {
    ...range, end_date: shiftDay(today, 1),
  }, Boolean(location), pollMs);
  const showGauge = location === "hai-chau";
  const gauge = useData<GaugeRainfall>("rainfall/nearby-gauge", { location }, showGauge, pollMs);
  const gaugeByDate = new Map((gauge.data?.days ?? []).map((row) => [row.date, row]));
  const days = Array.from({ length: 8 }, (_, index) => shiftDay(today, -index));
  const byDate = new Map((archive.data ?? []).map((row) => [row.period_start, row]));
  const totals = dailyTotals(models.data ?? [], now);
  const todayStart = Date.parse(today + "T00:00:00+07:00");
  const elapsedHours = Math.floor((now - todayStart) / hourMs);
  const currentRain = weather?.payload.values.precipitation;
  const currentEnd = Date.parse(weather?.valid_at ?? "");
  const currentSeconds = weather?.payload.interval_seconds ?? 0;
  const hasCurrent = currentRain != null && Number.isFinite(currentRain) && currentRain >= 0
    && currentSeconds > 0 && currentEnd <= now && currentEnd - currentSeconds * 1_000 >= todayStart;

  return <Panel title="Lượng mưa hôm nay và 7 ngày gần đây" headingLabel="Recent rainfall"
    subtitle={`${name} · Giờ Việt Nam (ICT) · Cập nhật độc lập với bộ lọc lịch sử.`}>
    {!location ? <Empty title="Chọn điểm lấy mẫu để xem lượng mưa" /> : <>
      {hasCurrent && <p className="chart-note recent-rain-snapshot">
        Open-Meteo hiện tại · <strong>{displayNumber(currentRain)} mm</strong> trong {currentSeconds / 60} phút
        kết thúc lúc {clock.format(currentEnd)} ICT (ước tính mô hình).
      </p>}
      {archive.error && <QueryError error={archive.error} retry={() => void archive.refetch()} />}
      {models.error && <QueryError error={models.error} retry={() => void models.refetch()} />}
      {showGauge && gauge.error && <QueryError error={gauge.error} retry={() => void gauge.refetch()} />}
      <div className="table-wrap"><table>
        <thead><tr>
          <th scope="col">Ngày (ICT)</th>
          {showGauge && <th scope="col">Trạm Hồ Thạc Gián · Số đo</th>}
          <th scope="col">ERA5 · Mưa tái phân tích</th>
          {feeds.map((feed) => <th scope="col" key={feed.code}>{feed.name} · Ước tính</th>)}
        </tr></thead>
        <tbody>{days.map((date) => {
          const isToday = date === today;
          const historical = byDate.get(date);
          const measured = gaugeByDate.get(date);
          return <tr key={date} className={isToday ? "recent-rain-today" : undefined}>
            <th scope="row">{isToday ? <>Hôm nay <small>{date}</small></> : date}</th>
            {showGauge && <td>{measured ? <>
              {displayNumber(measured.mm)} mm <small>({measured.intervals}/144 kỳ 10 phút{isToday
                ? ` · đến ${clock.format(new Date(measured.through))}` : ""})</small>
            </> : gauge.isPending ? "Đang tải…" : gauge.error ? "Tải lỗi" : "Chưa có số đo"}</td>}
            <td>{historical?.rainfall_total_mm != null
              ? <>{displayNumber(historical.rainfall_total_mm)} mm <small>({historical.rainfall_hours}/{historical.expected_hours} giờ)</small></>
              : archive.isPending ? "Đang tải…" : archive.error ? "Tải lỗi" : "Chưa có ERA5"}</td>
            {feeds.map((feed) => {
              const total = totals.get(date)?.get(feed.code);
              return <td key={feed.code}>{total ? <>
                {displayNumber(total.mm)} mm <small>({total.hours}/24 giờ{isToday
                  ? ` · đến ${clock.format(total.through)}` : ""})</small>
              </> : models.isPending ? "Đang tải…" : models.error ? "Tải lỗi"
                : isToday && elapsedHours === 0 ? "Chưa kết thúc giờ đầu tiên" : "Chưa có dữ liệu"}</td>;
            })}
          </tr>;
        })}</tbody>
      </table></div>
      <p className="chart-note">
        ERA5 có độ trễ công bố khoảng 5 ngày. ECMWF IFS và NOAA GFS cộng lượng giáng thủy từ các giờ đã kết thúc.
        Số giờ trong ngoặc cho biết độ phủ mỗi ngày.
      </p>
      {showGauge && <p className="chart-note">
        Trạm Hồ Thạc Gián (430018, Thanh Khê) cách điểm mẫu Hải Châu khoảng 1,9 km.
        Tổng trạm cộng các kỳ 10 phút có số đo từ 00:00 ICT. <a href="https://muangap.danang.gov.vn/"
          target="_blank" rel="noreferrer">Nguồn: Bản đồ mưa ngập TP. Đà Nẵng</a>.
      </p>}
      {hasCurrent && <p className="chart-note">Nhận bản ghi ước tính lúc {localTime(weather?.received_at)} ICT.</p>}
    </>}
  </Panel>;
}
