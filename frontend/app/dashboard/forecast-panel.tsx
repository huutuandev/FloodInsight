"use client";

import { displayNumber, localTime, useCollection, type ProviderForecast } from "./data";
import { dailyTotals, feeds, shiftDay, useRainfallClock, type DailyTotal } from "./provider-rainfall";
import { Empty, Panel, Resource } from "./ui";

function rainSignal(values: (DailyTotal | undefined)[]) {
  const complete = values.filter((value): value is DailyTotal => value?.hours === 24);
  if (complete.length < feeds.length) return "Thiếu dữ liệu so sánh";
  const wet = complete.filter((value) => value.mm >= 0.1).length;
  if (wet === complete.length) return "Cả hai dự báo có mưa";
  if (wet === 0) return "Cả hai dự báo dưới 0,1 mm";
  return "Hai mô hình chưa thống nhất";
}

export function ForecastPanel({ location }: { location: string }) {
  const { today } = useRainfallClock();
  const start = shiftDay(today, 1);
  const end = shiftDay(today, 7);
  const query = useCollection<ProviderForecast>("weather/forecasts", {
    location, start_date: start, end_date: shiftDay(end, 1),
  }, Boolean(location), 5 * 60_000);
  const days = Array.from({ length: 7 }, (_, index) => shiftDay(start, index));

  return <Panel title="Dự báo mưa 7 ngày tới"
    headingLabel="Provider rainfall forecast"
    subtitle="Lượng mưa theo ngày giờ Việt Nam. Tín hiệu có mưa dùng ngưỡng 0,1 mm/ngày và xét hai nguồn đủ 24 giờ.">
    {!location ? <Empty title="Chọn điểm lấy mẫu để xem lượng mưa" /> :
      <Resource query={query} empty={<Empty title="Chưa có dữ liệu mô hình cho kỳ này" />}>{(rows) => {
        const totals = dailyTotals(rows);
        if (!days.some((date) => totals.has(date))) {
          return <Empty title="Chưa có dữ liệu ECMWF hoặc GFS cho kỳ này" />;
        }
        const received = feeds.map((feed) => rows
          .filter((row) => row.source === feed.code)
          .reduce((latest, row) => Math.max(latest, Date.parse(row.received_at)), 0));
        return <>
          <div className="table-wrap"><table>
            <thead><tr><th>Ngày (ICT)</th>{feeds.map((feed) => <th key={feed.code}>{feed.name}</th>)}
              <th>Tín hiệu mưa</th></tr></thead>
            <tbody>{days.map((date) => {
              const models = totals.get(date);
              const values = feeds.map((feed) => models?.get(feed.code));
              return <tr key={date}><td>{date}</td>
                {values.map((value, index) => <td key={feeds[index].code}>
                  {value ? <>{displayNumber(value.mm)} mm <small>({value.hours}/24 giờ)</small></> : "—"}
                </td>)}
                <td>{rainSignal(values)}</td>
              </tr>;
            })}</tbody>
          </table></div>
          <p className="chart-note">
            Dữ liệu qua Open-Meteo. Giờ nhận bản ghi mới nhất (ICT) · {feeds.map((feed, index) =>
              `${feed.name}: ${received[index] ? localTime(new Date(received[index]).toISOString()) : "—"}`
            ).join(" · ")}.
          </p>
        </>;
      }}</Resource>}
    <p className="chart-note">
      <a href={location === "hai-chau"
        ? "https://nchmf.gov.vn/kttvsiteE/vi-VN/1/hai-chau-tp-da-nang-w55.html"
        : "https://kttvtrungbo.org.vn/category/tp-da-nang/"} target="_blank" rel="noreferrer">
        {location === "hai-chau" ? "Bản tin chính thức cho Hải Châu" : "Bản tin của Đài KTTV Trung Bộ"}
      </a>
    </p>
  </Panel>;
}
