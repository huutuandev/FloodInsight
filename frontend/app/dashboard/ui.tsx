"use client";

import { AlertCircle, ChartNoAxesCombined, ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "./data";

export function Panel({ title, subtitle, action, children, className = "", headingLabel }: {
  title: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string; headingLabel?: string;
}) {
  return <section className={"panel " + className}>
    <header className="panel-head">
      <div>
        <h2 aria-label={headingLabel}>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </header>
    {children}
  </section>;
}

export function Empty({ title = "No records for this selection", detail = "Vui lòng chọn trạm quan trắc hoặc khoảng thời gian khác." }: {
  title?: string; detail?: string;
}) {
  return <div className="empty-state"><span className="empty-icon"><ChartNoAxesCombined size={23} /></span>
    <strong>{title}</strong><p>{detail}</p></div>;
}

export function Loading({ compact = false }: { compact?: boolean }) {
  return <div className={compact ? "loading compact" : "loading"} role="status" aria-label="Loading">
    <span /><span /><span />
  </div>;
}

export function QueryError({ error, retry }: { error: Error; retry: () => void }) {
  return <div className="error-state" role="alert"><AlertCircle size={18} />
    <div><strong>Could not load data</strong><p>{error.message}</p></div>
    <button className="button secondary" onClick={retry}>Thử lại (Retry)</button></div>;
}

export function Resource<T>({ query, children, empty, missingModel = false }: {
  query: { isPending: boolean; error: Error | null; data?: T; refetch: () => unknown };
  children: (data: T) => ReactNode; empty?: ReactNode; missingModel?: boolean;
}) {
  if (query.isPending) return <Loading />;
  if (query.error) {
    if (missingModel && query.error instanceof ApiError && query.error.status === 404
      && query.error.message === "Train or select an existing model version") {
      return <Empty title="Chưa đăng ký phiên bản mô hình" detail="Kết quả sẽ hiển thị sau khi mô hình máy học được huấn luyện và lưu trong hệ thống." />;
    }
    return <QueryError error={query.error} retry={() => void query.refetch()} />;
  }
  if (query.data === undefined || (Array.isArray(query.data) && !query.data.length)) return empty ?? <Empty />;
  return children(query.data);
}

export function Pager({ offset, limit, more, setOffset }: {
  offset: number; limit: number; more: boolean; setOffset: (value: number) => void;
}) {
  return <div className="pager">
    <button className="icon-button" aria-label="Previous page" disabled={!offset}
      onClick={() => setOffset(Math.max(0, offset - limit))}><ChevronLeft size={16} /></button>
    <span>Trang {Math.floor(offset / limit) + 1}</span>
    <button className="icon-button" aria-label="Next page" disabled={!more}
      onClick={() => setOffset(offset + limit)}><ChevronRight size={16} /></button>
  </div>;
}

export function StatePill({ status }: { status: string }) {
  const tone = ["ok", "succeeded"].includes(status) ? "good" :
    ["failed", "degraded", "unavailable"].includes(status) ? "warn" : "neutral";
  const label: Record<string, string> = {
    ok: "Hoạt động tốt",
    succeeded: "Thành công",
    failed: "Thất bại",
    degraded: "Suy giảm",
    unavailable: "Không khả dụng",
    running: "Đang chạy",
  };
  return <span className={"pill " + tone}><i />{label[status] ?? status}</span>;
}
