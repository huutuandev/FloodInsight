"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { GeoJsonObject } from "geojson";
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { latLngBounds } from "leaflet";
import { Radio } from "lucide-react";
import type { Location, Rain, Weather } from "./data";
import { displayNumber, localTime } from "./data";
import "leaflet/dist/leaflet.css";

export type Markers = {
  points: Location[]; selected: string;
  onSelect: (code: string) => void; latest: Record<string, Rain>; weather: Weather[]; compact?: boolean;
};
const center: [number, number] = [16.047, 108.205];

export const rainColors = ["#8fa2b4", "#2dd4bf", "#f59e0b", "#ef4444"];
export function rainfallColor(rain?: Rain) {
  const value = rain?.rainfall_total_mm;
  return rainColors[value == null ? 0 : value < 10 ? 1 : value < 25 ? 2 : 3];
}

function View({ points, selected, compact }: Pick<Markers, "points" | "selected" | "compact">) {
  const map = useMap();
  useEffect(() => {
    const focus = !compact && points.find((point) => point.code === selected);
    if (focus) map.setView([focus.latitude, focus.longitude], Math.max(map.getZoom(), 12), { animate: false });
    else if (points.length) map.fitBounds(latLngBounds(points.map((p) => [p.latitude, p.longitude])),
      { padding: [26, 26], maxZoom: compact ? 12 : 13, animate: false });
  }, [map, points, selected, compact]);
  useEffect(() => {
    const resize = new ResizeObserver(() => {
      if (map.getPane("mapPane")?.isConnected) map.invalidateSize({ pan: false });
    });
    resize.observe(map.getContainer());
    return () => resize.disconnect();
  }, [map]);
  return null;
}

type RainViewerResponse = {
  version: string;
  generated: number;
  host: string;
  radar: {
    past: { time: number; path: string }[];
    nowcast: { time: number; path: string }[];
  };
};

export default function StationMap({ points, selected, onSelect, latest, weather, compact }: Markers) {
  const [tileError, setTileError] = useState(false);
  const [radarEnabled, setRadarEnabled] = useState(true);

  // RainViewer Live Weather Radar (Free public API, CORS-enabled)
  const radar = useQuery<RainViewerResponse>({
    queryKey: ["rainviewer-weather-maps"],
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchInterval: 5 * 60 * 1000,
    queryFn: async ({ signal }) => {
      const res = await fetch("https://api.rainviewer.com/public/weather-maps.json", { signal });
      if (!res.ok) throw new Error("RainViewer API unavailable");
      return await res.json();
    },
  });

  const latestRadarFrame = useMemo(() => {
    if (!radar.data?.radar?.past?.length) return null;
    return radar.data.radar.past[radar.data.radar.past.length - 1];
  }, [radar.data]);

  const radarTileUrl = useMemo(() => {
    if (!radar.data?.host || !latestRadarFrame?.path) return null;
    return `${radar.data.host}${latestRadarFrame.path}/256/{z}/{x}/{y}/2/1_1.png`;
  }, [radar.data, latestRadarFrame]);

  const radarTimeStr = useMemo(() => {
    if (!latestRadarFrame?.time) return null;
    const date = new Date(latestRadarFrame.time * 1000);
    return date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok" });
  }, [latestRadarFrame]);

  const coast = useQuery({
    queryKey: ["da-nang-coastline"],
    enabled: tileError,
    staleTime: Infinity,
    queryFn: async ({ signal }) => {
      const response = await fetch("/da-nang-coastline.geojson", { signal });
      if (!response.ok) throw new Error("Offline coastline unavailable");
      return await response.json() as GeoJsonObject;
    },
  });

  return (
    <div className={compact ? "map-frame compact-map" : "map-frame full-map"}>
      {tileError && <span className="tile-note">{coast.data ? "Offline coastline · Natural Earth" : "Basemap tiles unavailable"}</span>}

      {/* Floating RainViewer Live Radar Control */}
      {!compact && (
        <div className="radar-overlay-controls" role="region" aria-label="RainViewer live radar control">
          <div className="radar-header">
            <span className="radar-title">
              <span className="radar-pulse-dot" />
              <Radio size={13} />
              Radar Mây Mưa
            </span>
            <button
              type="button"
              className={`radar-toggle-btn ${radarEnabled ? "active" : ""}`}
              onClick={() => setRadarEnabled(!radarEnabled)}
              title={radarEnabled ? "Tắt lớp phủ Radar" : "Bật lớp phủ Radar"}
            >
              {radarEnabled ? "Đang bật" : "Tắt"}
            </button>
          </div>

          {radarEnabled && (
            <>
              <div className="radar-meta">
                <span>Nguồn: RainViewer API</span>
                <span>{radarTimeStr ? `Quét: ${radarTimeStr} ICT` : "Đang cập nhật..."}</span>
              </div>
              <div className="radar-scale">
                <div className="radar-scale-bar" />
                <div className="radar-scale-labels">
                  <span>Mưa nhẹ</span>
                  <span>Mưa vừa</span>
                  <span>Mưa rất to</span>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      <MapContainer
        center={center}
        zoom={12}
        scrollWheelZoom={false}
        zoomControl={!compact}
        zoomAnimation={false}
        fadeAnimation={false}
        markerZoomAnimation={false}
      >
        <TileLayer
          url={process.env.NEXT_PUBLIC_OSM_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png"}
          maxZoom={19}
          attribution={'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}
          eventHandlers={{ tileerror: () => setTileError(true), tileload: () => setTileError(false) }}
        />

        {/* RainViewer Live Radar Tile Layer */}
        {radarEnabled && radarTileUrl && (
          <TileLayer
            key={radarTileUrl}
            url={radarTileUrl}
            opacity={0.65}
            zIndex={400}
            attribution={'Radar &copy; <a href="https://www.rainviewer.com/api.html">RainViewer</a>'}
          />
        )}

        {tileError && coast.data && (
          <GeoJSON
            data={coast.data}
            style={{
              className: "offline-coastline",
              color: "#71a5bb",
              weight: 2,
              opacity: 0.84,
              interactive: false,
            }}
          />
        )}

        <View points={points} selected={selected} compact={compact} />

        {points.map((point) => {
          const rain = latest[point.code];
          const now = weather.find((entry) => entry.location_code === point.code);
          const color = rainfallColor(rain);
          return (
            <CircleMarker
              key={point.code}
              center={[point.latitude, point.longitude]}
              eventHandlers={{ click: () => onSelect(point.code) }}
              radius={selected === point.code ? 11 : 8}
              pathOptions={{ color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 }}
            >
              <Popup autoPan={false}>
                <strong className="popup-name" style={{ color: "#38bdf8", fontSize: "14px" }}>{point.name}</strong>
                <div>Lượng mưa 24h: <strong>{displayNumber(rain?.rainfall_total_mm)} mm</strong></div>
                {rain && <div style={{ fontSize: "11px", opacity: 0.8 }}>{rain.period_start} · {rain.rainfall_hours}/{rain.expected_hours}h ghi nhận</div>}
                <div>Nhiệt độ quan trắc: <strong>{displayNumber(now?.payload.values.temperature_2m)} °C</strong></div>
                <div>Độ ẩm không khí: <strong>{displayNumber(now?.payload.values.relative_humidity_2m)}%</strong></div>
                {now && <small style={{ display: "block", marginTop: "4px", color: "var(--faint)" }}>{localTime(now.valid_at)} ICT</small>}
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
