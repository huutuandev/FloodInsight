"use client";

import { useText } from "./language";

import { AlertCircle, ChartNoAxesCombined, ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "./data";

export function Panel({ title, subtitle, action, children, className = "" }: {
  title: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return <section className={"panel " + className}>
    <header className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</header>
    {children}
  </section>;
}

export function Empty({ title = "No records for this selection", detail = "Try another location or date range." }: {
  title?: string; detail?: string;
}) {
  const t = useText();
  return <div className="empty-state"><span className="empty-icon"><ChartNoAxesCombined size={23} /></span>
    <strong>{t(title)}</strong><p>{t(detail)}</p></div>;
}

export function Loading({ compact = false }: { compact?: boolean }) {
  const t = useText();
  return <div className={compact ? "loading compact" : "loading"} role="status" aria-label={t("Loading")}>
    <span /><span /><span />
  </div>;
}

export function QueryError({ error, retry }: { error: Error; retry: () => void }) {
  const t = useText();
  return <div className="error-state" role="alert"><AlertCircle size={18} />
    <div><strong>{t("Could not load data")}</strong><p>{t(error.message)}</p></div>
    <button className="button secondary" onClick={retry}>{t("Retry")}</button></div>;
}

export function Resource<T>({ query, children, empty, missingModel = false }: {
  query: { isPending: boolean; error: Error | null; data?: T; refetch: () => unknown };
  children: (data: T) => ReactNode; empty?: ReactNode; missingModel?: boolean;
}) {
  const t = useText();
  if (query.isPending) return <Loading />;
  if (query.error) {
    if (missingModel && query.error instanceof ApiError && query.error.status === 404
      && query.error.message === "Train or select an existing model version") {
      return <Empty title={t("No registered model")} detail={t("Results appear here when a trained model is registered in the gateway.")} />;
    }
    return <QueryError error={query.error} retry={() => void query.refetch()} />;
  }
  if (query.data === undefined || (Array.isArray(query.data) && !query.data.length)) return empty ?? <Empty />;
  return children(query.data);
}

export function Pager({ offset, limit, more, setOffset }: {
  offset: number; limit: number; more: boolean; setOffset: (value: number) => void;
}) {
  const t = useText();
  return <div className="pager">
    <button className="icon-button" aria-label={t("Previous page")} disabled={!offset}
      onClick={() => setOffset(Math.max(0, offset - limit))}><ChevronLeft size={16} /></button>
    <span>{t("Page")} {Math.floor(offset / limit) + 1}</span>
    <button className="icon-button" aria-label={t("Next page")} disabled={!more}
      onClick={() => setOffset(offset + limit)}><ChevronRight size={16} /></button>
  </div>;
}

export function StatePill({ status }: { status: string }) {
  const t = useText();
  const tone = ["ok", "succeeded"].includes(status) ? "good" :
    ["failed", "degraded", "unavailable"].includes(status) ? "warn" : "neutral";
  const label: Record<string, string> = { ok: t("Operational"), succeeded: t("Succeeded"),
    failed: t("Failed"), degraded: t("Degraded"), unavailable: t("Unavailable"), running: t("Running") };
  return <span className={"pill " + tone}><i />{label[status] ?? t(status)}</span>;
}
