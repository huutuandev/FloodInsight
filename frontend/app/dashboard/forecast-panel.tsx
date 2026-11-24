"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, displayNumber, localTime, request, useCollection, useData, type Classification, type DateRange, type Prediction } from "./data";
import { shiftDay } from "./provider-rainfall";
import { Empty, Loading, Panel, QueryError } from "./ui";

type Outlook = {
  version: string;
  issued_at: string;
  input_start: string;
  input_end: string;
  published: boolean;
  availability: "retrospective" | "recorded";
  predictions: {
    lead_days: number; target_date: string; rainfall_mm: number;
    test_mae_mm: number; baseline_mae_mm: number;
  }[];
};

type DailyForecast = {
  target_date: string; rainfall_mm: number; issued_at: string;
  test_mae_mm?: number; baseline_mae_mm?: number; preview?: boolean;
};

function intensity(mm: number) {
  if (mm >= 25) return "Mưa to";
  if (mm >= 10) return "Mưa vừa";
  if (mm >= 0.1) return "Mưa nhẹ";
  return "Không mưa";
}

const labels: Record<string, string> = {
  "No Rain": "Không mưa", "Light Rain": "Mưa nhẹ", "Moderate Rain": "Mưa vừa",
  "Heavy Rain": "Mưa to", "Moderate/Heavy Rain": "Mưa vừa hoặc to",
};

export function ForecastPanel({ location, range }: { location: string; range?: DateRange }) {
  const query = useData<Outlook>("predictions/outlook", { location }, Boolean(location), 5 * 60_000);
  const scope = { location, ...range };
  const historical = useData<DailyForecast[]>("predictions/outlook/history", scope, Boolean(location && range));
  const legacyRain = useCollection<Prediction>("predictions/results", scope, Boolean(location && range));
  const legacyClasses = useCollection<Classification>("classifications/results", scope, Boolean(location && range));
  const client = useQueryClient();
  const publish = useMutation({
    mutationFn: (point: string) => request("predictions/outlook/publish", undefined, undefined, { location: point }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["predictions/outlook"] });
      void client.invalidateQueries({ queryKey: ["predictions/outlook/history"] });
    },
  });
  const rain = new Map<string, DailyForecast>();
  const classes = new Map<string, Classification>();
  const within = (date: string) => !range || (date >= range.start_date && date <= range.end_date);
  function add(row: DailyForecast) {
    const previous = rain.get(row.target_date);
    if (within(row.target_date) && (!previous || Date.parse(row.issued_at) > Date.parse(previous.issued_at))) {
      rain.set(row.target_date, row);
    }
  }
  for (const row of historical.data ?? []) add(row);
  for (const row of legacyRain.data ?? []) add(row);
  const data = query.data;
  for (const row of data?.predictions ?? []) {
    if (data && (data.published || !rain.has(row.target_date))) {
      add({ ...row, issued_at: data.issued_at, preview: !data.published });
      const current = rain.get(row.target_date);
      if (current?.issued_at === data.issued_at) {
        rain.set(row.target_date, {
          ...current, test_mae_mm: row.test_mae_mm, baseline_mae_mm: row.baseline_mae_mm,
        });
      }
    }
  }
  for (const row of legacyClasses.data ?? []) {
    if (within(row.target_date) && !classes.has(row.target_date)) classes.set(row.target_date, row);
  }
  const selectedDays = range ? Math.round((Date.parse(range.end_date) - Date.parse(range.start_date)) / 86_400_000) + 1 : 0;
  const dates = range && selectedDays > 0 && selectedDays <= 31
    ? Array.from({ length: selectedDays }, (_, index) => shiftDay(range.start_date, index))
    : [...new Set([...rain.keys(), ...classes.keys()])].sort();
  const pending = query.isPending || Boolean(range && (historical.isPending || legacyRain.isPending || legacyClasses.isPending));
  const issues = range ? [historical, legacyRain, legacyClasses, query] : [query];

  return <Panel title={range ? "Dự báo lượng mưa và phân loại theo ngày" : "Mô hình FloodInsight: Dự báo mưa 7 ngày tới"}
    headingLabel="FloodInsight rainfall forecast"
    subtitle={range ? `Khoảng ngày áp dụng: ${range.start_date} đến ${range.end_date} (ICT).`
      : "Mô hình XGBoost dự báo từng ngày từ lịch sử ERA5 đã lưu."}
    action={query.data && !query.data.published && <button className="button secondary" type="button"
      disabled={publish.isPending} onClick={() => publish.mutate(location)}>Phát hành dự báo</button>}>
    {publish.error && publish.variables === location &&
      <QueryError error={publish.error} retry={() => publish.mutate(location)} />}
    {!location ? <Empty title="Chọn điểm lấy mẫu để xem dự báo" /> : <>
      {issues.map((item, index) => item.error
        && (!(item.error instanceof ApiError) || item.error.status !== 404)
        && <QueryError key={index} error={item.error} retry={() => void item.refetch()} />)}
      {data && <p className="chart-note">
          Đầu vào ERA5: {data.input_start} đến {data.input_end} · {localTime(data.issued_at)} ICT.
          {" "}Bản 7 ngày hiện tại: {data.published ? "đã phát hành." : "xem trước."}
      </p>}
      {!dates.length ? pending ? <Loading /> : <Empty title="Chưa có dự báo trong khoảng ngày đã chọn" /> :
        <div className="table-wrap"><table>
          <thead><tr>
            <th scope="col">Ngày (ICT)</th><th scope="col" aria-label="Predicted mm">Lượng mưa dự đoán</th>
            <th scope="col">Phân loại cường độ</th><th scope="col">Phát hành (ICT)</th>
            <th scope="col">MAE mô hình</th><th scope="col">MAE đối chứng</th>
          </tr></thead>
          <tbody>{dates.map((date) => {
            const row = rain.get(date);
            const label = classes.get(date);
            return <tr key={date}>
              <th scope="row">{date}</th>
              <td>{row ? `${displayNumber(row.rainfall_mm)} mm` : pending ? "Đang tải…" : "Chưa có dự báo"}</td>
              <td>{label ? <details>
                <summary>{labels[label.label] ?? label.label} <small>· Bộ phân loại ngày kế tiếp</small></summary>
                <small>Tính lúc {localTime(label.issued_at)} ICT.</small>
                {Object.entries(label.probabilities ?? {}).map(([key, value]) => <div key={key}>
                  {labels[key] ?? key}: {displayNumber(value * 100)} điểm trên 100
                </div>)}
              </details>
                : row ? <>{intensity(row.rainfall_mm)} <small>· Theo ngưỡng mm</small></>
                : pending ? "Đang tải…" : "Chưa có phân loại"}</td>
              <td>{row ? <>{localTime(row.issued_at)}{row.preview && <small> · Xem trước</small>}</>
                : label ? localTime(label.issued_at) : "—"}</td>
              <td>{row?.test_mae_mm != null ? `${displayNumber(row.test_mae_mm, 2)} mm` : "—"}</td>
              <td>{row?.baseline_mae_mm != null ? `${displayNumber(row.baseline_mae_mm, 2)} mm` : "—"}</td>
            </tr>;
          })}</tbody>
        </table></div>}
        <p className="chart-note">
          Phân loại theo lượng mưa dự báo dùng các ngưỡng 0,1 / 10 / 25 mm mỗi ngày.
          MAE đo sai số trung bình trên tập kiểm tra ERA5. Đối chứng dùng lượng mưa của ngày đầu vào gần nhất.
          {data?.availability === "retrospective" && " Kiểm tra hồi cứu giả định ERA5 có độ trễ sáu ngày."}
        </p>
    </>}
  </Panel>;
}
