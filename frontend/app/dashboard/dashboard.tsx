"use client";

import { LanguageContext, useText, type Language } from "./language";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { FormEvent } from "react";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { Activity, CalendarDays, ChartNoAxesCombined, CloudRain, Database, LayoutDashboard,
  MapPinned, MapPin, Moon, RefreshCw, Sun, Waves } from "lucide-react";
import { ApiError, recentCoveredRange, coveredPreset, source, useData, withWeatherLocations,
  type DateRange, type Location, type RainfallCoverage, type Status, type Weather } from "./data";
import { DataManagement, MachineLearning } from "./operation-panels";
import { Analytics } from "./weather-panels";
import { FloodForecast, FloodMap, FloodOverview } from "./flood-panels";
import { FloodDataManagement, FloodMachineLearning } from "./flood-operations";
import { QueryError, StatePill } from "./ui";

const navigation = [
  { name: "Flood Overview", short: "Overview", icon: LayoutDashboard, detail: "Current flood assessments, available forecasts, and rainfall context for Da Nang." },
  { name: "Flood Risk Forecast", short: "Forecast", icon: Activity, detail: "Compare current evidence and inspect the factors behind each location assessment." },
  { name: "Rainfall Analytics", short: "Rainfall", icon: CloudRain, detail: "Explore historical rainfall patterns and weather relationships." },
  { name: "Machine Learning", short: "ML", icon: ChartNoAxesCombined, detail: "Review flood model readiness, validated predictions and exploratory terrain profiles." },
  { name: "Da Nang Flood Map", short: "Map", icon: MapPinned, detail: "Explore the flood evidence at registered monitoring points." },
  { name: "Data Management", short: "Data", icon: Database, detail: "Track flood dataset coverage, assessment history and weather collection." },
] as const;
type Section = typeof navigation[number]["name"];
type Theme = "dark" | "light";

function subscribeTheme(callback: () => void) {
  window.addEventListener("floodinsight-theme", callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener("floodinsight-theme", callback);
    window.removeEventListener("storage", callback);
  };
}
function getTheme(): Theme { return localStorage.getItem("floodinsight-theme") === "light" ? "light" : "dark"; }
function serverTheme(): Theme { return "dark"; }

function Brand() {
  const t = useText();
  return <div className="brand"><span className="brand-mark"><Waves size={23} /></span>
    <span><strong>Flood<span>Insight</span></strong><small>{t("DA NANG MONITORING")}</small></span>
  </div>;
}

const languageKey = "floodinsight-language";
const getLanguage = (): Language => localStorage.getItem(languageKey) === "en" ? "en" : "vi";
const serverLanguage = (): Language => "vi";
function subscribeLanguage(callback: () => void) {
  window.addEventListener(languageKey, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(languageKey, callback);
    window.removeEventListener("storage", callback);
  };
}

function DashboardBody({ initialRange, language }: { initialRange: DateRange; language: Language }) {
  const t = useText();
  const queryClient = useQueryClient();
  const [section, navigate] = useState<Section>("Flood Overview");
  const [location, chooseLocation] = useState("");
  const [range, setRange] = useState<DateRange>();
  const [draft, setDraft] = useState<DateRange>();
  const [filterError, setFilterError] = useState("");
  const theme = useSyncExternalStore(subscribeTheme, getTheme, serverTheme);
  const locations = useData<Location[]>("locations");
  const floodLocations = useData<Location[]>("flood-risk/locations");
  const weather = useData<Weather[]>("weather/latest", undefined, true, 60_000);
  const status = useData<Status>("system/status", undefined, true, 45_000);
  const points = useMemo(() => withWeatherLocations(locations.data ?? [], weather.data ?? []), [locations.data, weather.data]);
  const coverage = useData<RainfallCoverage[]>("rainfall/coverage", { source });
  const selected = points.some((point) => point.code === location) ? location :
    points.find((point) => coverage.data?.some((row) => row.location === point.code))?.code ?? points[0]?.code ?? "";
  const selectedCoverage = coverage.data?.find((row) => row.location === selected);
  const floodPoints = floodLocations.data ?? [];
  const floodSelected = floodPoints.some((point) => point.code === location) ? location :
    floodPoints.find((point) => point.code === selected)?.code ?? floodPoints[0]?.code ?? "";
  const activeRange = range ?? recentCoveredRange(selectedCoverage, initialRange);
  const inputRange = draft ?? activeRange;
  const scope = { location: selected, ...activeRange };
  const showFilters = section === "Flood Overview" || section === "Rainfall Analytics" || section === "Machine Learning";

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const days = (Date.parse(inputRange.end_date) - Date.parse(inputRange.start_date)) / 86_400_000;
    if (!Number.isFinite(days) || days < 0 || days >= 3660) {
      setFilterError("Choose an ordered date range of up to 3,660 days.");
      return;
    }
    setFilterError("");
    setRange(inputRange);
    setDraft(undefined);
  }
  function go(next: Section) {
    navigate(next);
    window.scrollTo({ top: 0 });
  }
  const detail = t(navigation.find((item) => item.name === section)?.detail ?? "");

  return <div className="dashboard" data-theme={theme} lang={language}>
    <aside className="sidebar" aria-label={t("Dashboard sidebar")}>
      <Brand />
      <nav aria-label={t("Dashboard sections")}>
        {navigation.map(({ name, short, icon: Icon }) => <button key={name} type="button" aria-label={t(name)} onClick={() => go(name)}
          aria-current={section === name ? "page" : undefined}><Icon size={18} strokeWidth={1.8} /><span className="desktop-label">{t(name)}</span><span className="mobile-label">{t(short)}</span></button>)}
      </nav>
      <div className="side-foot"><MapPin size={17} /><div><strong>{t("Da Nang, Vietnam")}</strong><span>{t("Indochina Time · UTC+7")}</span></div></div>
    </aside>

    <div className="workspace">
      <header className="topbar">
        <div className="mobile-brand"><Brand /></div>
        <div className="breadcrumbs"><span>{t("Dashboard")}</span><span>/</span><strong>{t(section)}</strong></div>
        <div className="top-actions">
          <select className="button secondary" aria-label={t("Language")} value={language} onChange={(event) => {
            localStorage.setItem(languageKey, event.target.value);
            window.dispatchEvent(new Event(languageKey));
          }}><option value="vi">VI</option><option value="en">EN</option></select>
          <StatePill status={status.error ? "unavailable" : status.data?.status ?? t("Checking services")} />
          <button className="icon-button" type="button" aria-label={theme === "dark" ? t("Switch to light theme") : t("Switch to dark theme")}
            onClick={() => { localStorage.setItem("floodinsight-theme", theme === "dark" ? "light" : "dark");
              window.dispatchEvent(new Event("floodinsight-theme")); }}>
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button className="icon-button" type="button" aria-label={t("Refresh dashboard")}
            onClick={() => { void queryClient.invalidateQueries(); }}>
            <RefreshCw size={17} />
          </button>
        </div>
      </header>
      <main className="dashboard-main" id="main">
        {section === "Flood Overview" ? <header className="hero">
          <div className="hero-content"><p className="hero-location"><MapPin size={15} /> {t("DA NANG, VIETNAM")}</p>
            <h1>{t("Flood Overview")}</h1><p>{detail}</p>
            <button type="button" className="button primary" onClick={() => go("Flood Risk Forecast")}>
              {t("Compare locations")}</button>
          </div>
          <a className="photo-credit" href="https://commons.wikimedia.org/wiki/File:Da_Nang_Night_Panorama_01.jpg"
            title="Da Nang Night Panorama 01 by Dragfyre, CC BY-SA 3.0">Photo by Dragfyre · CC BY-SA 3.0</a>
        </header> : <header className="section-heading"><h1>{t(section)}</h1><p>{detail}</p></header>}

        <p className="research-note">{t("Experimental research tool. For official warnings, consult local authorities.")}</p>
        {showFilters && <form className="filter-bar panel" onSubmit={apply}>
          <div className="filter-field location-field"><label htmlFor="point"><MapPin size={15} /> {t("Sampling point")}</label>
            <select id="point" value={selected} onChange={(event) => chooseLocation(event.target.value)} disabled={!points.length}>
              {!points.length && <option value="">{locations.isPending || weather.isPending ? t("Loading…") : t("No locations available")}</option>}
              {points.map((point) => <option key={point.code} value={point.code}>{point.name}</option>)}
            </select></div>
          <div className="filter-field"><label htmlFor="start"><CalendarDays size={15} /> {t("From")}</label>
            <input id="start" type="date" required value={inputRange.start_date} min="1900-01-01" max="2200-12-30"
              onChange={(event) => setDraft({ ...inputRange, start_date: event.target.value })} /></div>
          <div className="filter-field"><label htmlFor="end">{t("To")}</label>
            <input id="end" type="date" required value={inputRange.end_date} min="1900-01-01" max="2200-12-30"
              onChange={(event) => setDraft({ ...inputRange, end_date: event.target.value })} /></div>
          <button className="button secondary" type="submit">{t("Apply dates")}</button>
          <div className="date-presets" role="group" aria-label={t("Quick dates")}>
            {([["30 days",30],["90 days",90],["1 year",365],["All history",undefined]] as const).map(([name,days]) =>
              <button key={name} type="button" className="button secondary" onClick={() => {
                const fullRange = recentCoveredRange(selectedCoverage, initialRange);
                setRange(days === undefined ? fullRange : coveredPreset(fullRange, days));
                setDraft(undefined);
                setFilterError("");
              }}>{t(name)}</button>)}
          </div>
          {filterError && <p role="alert" className="filter-error">{t(filterError)}</p>}
        </form>}

        {locations.error && !points.length && showFilters &&
          <QueryError error={locations.error} retry={() => void locations.refetch()} />}
        {section === "Flood Overview" && <FloodOverview scope={scope} theme={theme} weather={weather} />}
        {section === "Flood Risk Forecast" && <FloodForecast selected={floodSelected} select={chooseLocation} />}
        {section === "Rainfall Analytics" && <Analytics scope={scope} theme={theme} coverage={coverage} />}
        {section === "Machine Learning" && <>
          <MachineLearning scope={scope} filterForecasts={Boolean(range)} locations={points} theme={theme} />
          <FloodMachineLearning locations={floodPoints} theme={theme} />
        </>}
        {section === "Da Nang Flood Map" && <FloodMap selected={floodSelected} select={chooseLocation} />}
        {section === "Data Management" && <><FloodDataManagement locations={floodPoints} /><DataManagement locations={points} /></>}
        <footer className="main-footer"><span>FloodInsight Da Nang</span><span>Open-Meteo · ERA5 · OpenStreetMap</span></footer>
      </main>
    </div>
  </div>;
}

export default function Dashboard({ initialRange }: { initialRange: DateRange }) {
  const language = useSyncExternalStore(subscribeLanguage, getLanguage, serverLanguage);
  useEffect(() => { document.documentElement.lang = language; }, [language]);
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: {
    staleTime: 30_000,
    retry: (attempt, error) => attempt < 1 && (!(error instanceof ApiError) || error.status >= 500),
  } } }));
  return <LanguageContext.Provider value={language}><QueryClientProvider client={client}><DashboardBody initialRange={initialRange} language={language} /></QueryClientProvider></LanguageContext.Provider>;
}
