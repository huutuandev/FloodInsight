"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { GeoJsonObject } from "geojson";
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { latLngBounds } from "leaflet";
import { RainRadar } from "./rain-radar";
import type { Location, Rain, Weather } from "./data";
import { displayNumber, localTime } from "./data";
import "leaflet/dist/leaflet.css";

export type Markers = {
  historical?: boolean; reports?: FloodReport[];
  points: Location[]; selected: string;
  onSelect: (code: string) => void; latest: Record<string, Rain>; weather: Weather[]; compact?: boolean;
};
export type FloodReport = {
  river_context: {station_or_site: string; time_description: string; level_m: number; reference_level: string; source_url: string}[] | null;
  road_geometry: import("geojson").LineString | null;
  context_note: string | null; elevation_m: number | null; elevation_source: string | null;
  id: string; event_id: string; event_date: string; title: string; place: string;
  location: string; latitude: number | null; longitude: number | null;
  status: "flooded" | "confirmed_dry" | "unknown"; depth_cm: number | null;
  geometry_source: string | null; sources: { publisher: string; url: string }[];
};
export const reportStatus = { flooded: "Ghi nhận ngập", confirmed_dry: "Đã xác nhận khô ráo", unknown: "Chưa rõ" };
const center: [number, number] = [16.047, 108.205];

// Daily rainfall intensity colors; these do not represent a validated flood-risk scale.
export const rainColors = ["#94A3B8", "#299D70", "#E9A23B", "#E67E22", "#D9534F"];
export function rainfallColor(rain?: Rain) {
  const value = rain?.rainfall_total_mm;
  if (value == null) return rainColors[0];
  if (value < 10) return rainColors[1];
  if (value < 25) return rainColors[2];
  if (value < 50) return rainColors[3];
  return rainColors[4];
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

export default function StationMap({ points, selected, onSelect, latest, weather, compact, historical, reports }: Markers) {
  const [tileError, setTileError] = useState(false);
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

        {!compact && !historical && <RainRadar center={center} />}

        {tileError && coast.data && (
          <GeoJSON
            data={coast.data}
            style={{
              className: "offline-coastline",
              color: "#2878B5",
              weight: 2,
              opacity: 0.85,
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
              pathOptions={{ color: "#17365D", weight: 2, fillColor: color, fillOpacity: 0.95 }}
            >
              <Popup autoPan={false}>
                <strong className="popup-name" style={{ fontSize: "14px" }}>{point.name}</strong>
                <div>Mưa ERA5: <strong>{rain?.rainfall_total_mm == null ? "—" : `${displayNumber(rain.rainfall_total_mm)} mm`}</strong></div>
                {rain && <div style={{ fontSize: "11px", opacity: 0.8 }}>{rain.period_start} · {rain.rainfall_hours}/{rain.expected_hours} giờ dữ liệu</div>}
                {!historical && <div>Nhiệt độ mô hình: <strong>{displayNumber(now?.payload.values.temperature_2m)} °C</strong></div>}
                {!historical && <div>Độ ẩm không khí: <strong>{displayNumber(now?.payload.values.relative_humidity_2m)}%</strong></div>}
                {now && <small style={{ display: "block", marginTop: "4px", color: "#64748B" }}>{localTime(now.valid_at)} ICT</small>}
              </Popup>
            </CircleMarker>
          );
        })}
        {reports?.map(r => r.road_geometry && <GeoJSON key={r.id} data={r.road_geometry} style={{color:"#8b45a5", weight:5}}>
          <Popup>{r.place} · {reportStatus[r.status]}</Popup>
        </GeoJSON>)}
        {reports?.map(r => r.latitude != null && r.longitude != null &&
          <CircleMarker key={r.id} center={[r.latitude, r.longitude]} radius={8}
            pathOptions={{color: "#42205c", fillColor: "#ba77dc", fillOpacity: 1}}>
            <Popup><strong>{r.place}</strong><div>{r.event_date} · {reportStatus[r.status]}</div></Popup>
          </CircleMarker>)}
      </MapContainer>
    </div>
  );
}
