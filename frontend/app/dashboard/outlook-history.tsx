"use client";

import { useState } from "react";
import { displayNumber, localTime, useData } from "./data";
import { useRainfallClock } from "./provider-rainfall";
import { Empty, Panel, QueryError, Resource } from "./ui";

type IssuedForecast = {
  version: string; issued_at: string; target_date: string; rainfall_mm: number;
  input_start: string; input_end: string;
};
type GaugeDay = { date: string; mm: number; intervals: number };

export function OutlookHistory({ location }: { location: string }) {
  const [lead, setLead] = useState(1);
  const { today } = useRainfallClock();
  const supportsGauge = location === "hai-chau";
  const history = useData<IssuedForecast[]>("predictions/outlook/history",
    { location, lead_days: lead }, Boolean(location), 5 * 60_000);
  const gauge = useData<{ days: GaugeDay[] }>("rainfall/nearby-gauge", { location }, supportsGauge, 5 * 60_000);
  const actuals = new Map(gauge.data?.days.map((day) => [day.date, day]));

  return <Panel title="Lịch sử dự báo và đối chiếu thực đo"
    subtitle="Các bản đã phát hành có ngày mục tiêu trong vòng 7 ngày trước hoặc 7 ngày tới."
    action={<label>Mốc dự báo{" "}
      <select value={lead} onChange={(event) => setLead(Number(event.target.value))}>
        {Array.from({ length: 7 }, (_, i) => i + 1).map((day) =>
          <option value={day} key={day}>+{day} ngày</option>)}
      </select>
    </label>}>
    {!location ? <Empty title="Chọn điểm lấy mẫu để xem lịch sử" /> : <>
      {supportsGauge && gauge.error && <QueryError error={gauge.error} retry={() => void gauge.refetch()} />}
      <Resource query={history} empty={<Empty title="Chưa có bản phát hành cho mốc này"
        detail="Bản đã phát hành sẽ xuất hiện ở đây cùng giờ phát hành và dữ liệu đầu vào." />}>{(rows) =>
        <div className="table-wrap"><table>
          <thead><tr>
            <th scope="col">Ngày dự báo (ICT)</th><th scope="col">Phát hành (ICT)</th>
            <th scope="col">Phiên bản và đầu vào</th><th scope="col">Dự báo</th>
            <th scope="col">Số đo trạm</th><th scope="col">Dự báo trừ số đo trạm</th>
          </tr></thead>
          <tbody>{rows.map((row) => {
            const gaugeDay = actuals.get(row.target_date);
            const comparable = row.target_date < today && gaugeDay?.intervals === 144;
            return <tr key={row.version + row.target_date + row.issued_at}>
              <th scope="row">{row.target_date}</th><td>{localTime(row.issued_at)}</td>
              <td><code title={row.version}>{row.version.slice(0, 8)}</code><br />
                <small>{row.input_start} – {row.input_end}</small></td>
              <td>{displayNumber(row.rainfall_mm)} mm</td>
              <td>{!supportsGauge ? "Chưa có trạm đối chiếu" : row.target_date >= today ? "Chờ hết ngày"
                : gaugeDay ? `${displayNumber(gaugeDay.mm)} mm (${gaugeDay.intervals}/144 kỳ)`
                : gauge.isPending ? "Đang tải…" : "Chưa có số đo"}</td>
              <td>{comparable ? `${displayNumber(row.rainfall_mm - gaugeDay.mm)} mm` : "—"}</td>
            </tr>;
          })}</tbody>
        </table></div>
      }</Resource>
      {supportsGauge && <p className="chart-note">
        Trạm Hồ Thạc Gián cách điểm mẫu Hải Châu khoảng 1,9 km. Chỉ tính chênh lệch khi ngày đã kết thúc
        và trạm có đủ 144 kỳ đo 10 phút.
      </p>}
    </>}
  </Panel>;
}
