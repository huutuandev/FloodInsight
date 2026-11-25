"use client";

import { useState } from "react";
import { displayNumber, localTime, useData, type DateRange } from "./data";
import { useRainfallClock } from "./provider-rainfall";
import { Empty, Panel, Resource } from "./ui";

type IssuedForecast = {
  version: string; issued_at: string; target_date: string; rainfall_mm: number;
  station_code: string | null; observed_mm: number | null; intervals: number | null; error_mm: number | null;
  missing_midnight?: string | null;
  input_start: string; input_end: string;
};


type LeadScore = {
  lead_days: number; forecast_days: number; verified_days: number;
  mae_mm: number | null; bias_mm: number | null; misses: number | null; false_alarms: number | null;
};

export function OutlookHistory({ location, range }: { location: string; range?: DateRange }) {
  const [lead, setLead] = useState(1);
  const { today } = useRainfallClock();
  const supportsGauge = location === "hai-chau";
  const scores = useData<LeadScore[]>("predictions/outlook/verification", { location }, supportsGauge, 5 * 60_000);
  const history = useData<IssuedForecast[]>("predictions/outlook/history",
    { location, ...range, lead_days: lead }, Boolean(location), 5 * 60_000);
  return <><Panel title="Lịch sử dự báo và đối chiếu thực đo"
    subtitle={range ? `Từ ${range.start_date} đến ${range.end_date} (ICT).` : "Các bản đã phát hành có ngày mục tiêu trong vòng 7 ngày trước hoặc 7 ngày tới."}
    action={<label>Mốc dự báo{" "}
      <select value={lead} onChange={(event) => setLead(Number(event.target.value))}>
        {Array.from({ length: 7 }, (_, i) => i + 1).map((day) =>
          <option value={day} key={day}>+{day} ngày</option>)}
      </select>
    </label>}>
    {!location ? <Empty title="Chọn điểm lấy mẫu để xem lịch sử" /> : <>
      <Resource query={history} empty={<Empty title="Chưa có bản phát hành cho mốc này"
        detail="Bản đã phát hành sẽ xuất hiện ở đây cùng giờ phát hành và dữ liệu đầu vào." />}>{(rows) =>
        <div className="table-wrap"><table>
          <thead><tr>
            <th scope="col">Ngày dự báo (ICT)</th><th scope="col">Phát hành (ICT)</th>
            <th scope="col">Phiên bản và đầu vào</th><th scope="col">Dự báo</th>
            <th scope="col">Số đo trạm</th><th scope="col">Dự báo trừ số đo trạm</th>
          </tr></thead>
          <tbody>{rows.map((row) => {
            return <tr key={row.version + row.target_date + row.issued_at}>
              <th scope="row">{row.target_date}</th><td>{localTime(row.issued_at)}</td>
              <td><code title={row.version}>{row.version.slice(0, 8)}</code><br />
                <small>{row.input_start} – {row.input_end}</small></td>
              <td>{displayNumber(row.rainfall_mm)} mm</td>
              <td>{!supportsGauge ? "Chưa có trạm đối chiếu" : row.target_date >= today ? "Chờ hết ngày"
                : row.observed_mm != null ? `${displayNumber(row.observed_mm)} mm (${row.intervals}/144 kỳ · trạm ${row.station_code})`
                : "Chưa có số đo"}
                {row.missing_midnight && <div><small>Thiếu kỳ 23:50–00:00 ICT</small></div>}</td>
              <td>{row.error_mm != null ? `${displayNumber(row.error_mm)} mm` : "—"}</td>
            </tr>;
          })}</tbody>
        </table></div>
      }</Resource>
      {supportsGauge && <p className="chart-note">
        Trạm Hồ Thạc Gián cách điểm mẫu Hải Châu khoảng 1,9 km. Chỉ tính chênh lệch khi ngày đã kết thúc
        và trạm có đủ 144 kỳ đo 10 phút.
      </p>}
    </>}
  </Panel>
  {supportsGauge && <Panel title="Độ chính xác theo hạn dự báo"
    subtitle="90 ngày đã kết thúc gần nhất (ICT) · Trạm Hồ Thạc Gián · Mỗi ngày mục tiêu lấy bản phát hành mới nhất ở từng hạn.">
    <Resource query={scores}>{(rows) => <>
      {!rows.some(row => row.verified_days > 0) && <p>Chưa có ngày vừa có dự báo đã phát hành vừa có đủ 144 kỳ đo để tính sai số.</p>}
      <div className="table-wrap"><table>
        <thead><tr>{["Dự báo trước", "Ngày có dự báo", "Ngày đủ đối chiếu", "MAE (mm)", "Sai lệch trung bình (mm)", "Bỏ sót mưa to", "Báo động nhầm"].map(text => <th scope="col" key={text}>{text}</th>)}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.lead_days}>
          <th scope="row">{row.lead_days} ngày</th><td>{row.forecast_days}</td><td>{row.verified_days}</td>
          <td>{row.mae_mm == null ? "—" : displayNumber(row.mae_mm, 2)}</td>
          <td>{row.bias_mm == null ? "—" : displayNumber(row.bias_mm, 2)}</td>
          <td>{row.misses ?? "—"}</td><td>{row.false_alarms ?? "—"}</td>
        </tr>)}</tbody>
      </table></div>
      <p className="chart-note">MAE là sai số tuyệt đối trung bình. Sai lệch dương nghĩa là dự báo cao hơn thực đo. Ngưỡng mưa to của dự án là 25 mm/ngày.</p>
    </>}</Resource>
  </Panel>}</>;
}
