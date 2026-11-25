"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import type { GeoJsonObject } from "geojson";
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { latLngBounds } from "leaflet";
import type { Location, Rain, Weather } from "./data";
import { displayNumber, localTime } from "./data";
import "leaflet/dist/leaflet.css";

export type Markers = {
  points: Location[]; selected: string;
  onSelect: (code: string) => void; latest: Record<string, Rain>; weather: Weather[]; compact?: boolean;
  floodMarkers?: Record<string, { color: string; content: ReactNode }>;
};
const center: [number, number] = [16.047, 108.205];

export const rainColors = ["#8fa2b4", "#30baad", "#f3bf62", "#f47d82"];
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

export default function StationMap({ points, selected, onSelect, latest, weather, compact, floodMarkers }: Markers) {
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
  return <div className={compact ? "map-frame compact-map" : "map-frame full-map"}>
    {tileError && <span className="tile-note">{coast.data ? "Offline coastline · Natural Earth" : "Basemap tiles unavailable"}</span>}
    <MapContainer center={center} zoom={12} scrollWheelZoom={false} zoomControl={!compact} zoomAnimation={false} fadeAnimation={false} markerZoomAnimation={false}>
      <TileLayer url={process.env.NEXT_PUBLIC_OSM_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png"}
        maxZoom={19} attribution={'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}
        eventHandlers={{ tileerror: () => setTileError(true), tileload: () => setTileError(false) }} />
      {tileError && coast.data && <GeoJSON data={coast.data} style={{
        className: "offline-coastline", color: "#71a5bb", weight: 2, opacity: .84, interactive: false,
      }} />}
      <View points={points} selected={selected} compact={compact} />
      {points.map((point) => {
        const rain = latest[point.code];
        const now = weather.find((entry) => entry.location_code === point.code);
        const marker = floodMarkers?.[point.code];
        const color = marker?.color ?? rainfallColor(rain);
        return <CircleMarker key={point.code} center={[point.latitude, point.longitude]}
          eventHandlers={{ click: () => onSelect(point.code) }}
          radius={selected === point.code ? 11 : 8}
          pathOptions={{ color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 }}>
          <Popup autoPan={false} maxHeight={marker ? 250 : undefined}>
            {marker ? marker.content : <><strong className="popup-name">{point.name}</strong>
            <div>Daily rainfall: {displayNumber(rain?.rainfall_total_mm)} mm</div>
            {rain && <div>{rain.period_start} · {rain.rainfall_hours}/{rain.expected_hours} h covered</div>}
            <div>Modeled temperature: {displayNumber(now?.payload.values.temperature_2m)} °C</div>
            <div>Modeled humidity: {displayNumber(now?.payload.values.relative_humidity_2m)}%</div>
            {now && <small>{localTime(now.valid_at)} ICT</small>}
            </>}
          </Popup>
        </CircleMarker>;
      })}
    </MapContainer>
  </div>;
}

