"use client";

import { useText } from "./language";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import type { GeoJsonObject } from "geojson";
import { Circle, CircleMarker, GeoJSON, MapContainer, Polyline, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import { latLngBounds } from "leaflet";
import type { Location, Rain, Weather } from "./data";
import { displayNumber, localTime } from "./data";
import "leaflet/dist/leaflet.css";

export type Markers = {
  points: Location[]; selected: string;
  onSelect: (code: string) => void; latest: Record<string, Rain>; weather: Weather[]; compact?: boolean;
  floodMarkers?: Record<string, { color: string; content: ReactNode; radius?: number }>;
  focused?: string;
  showAreas?: boolean;
  zones?: {
    id: string; name: string; center: [number, number];
    coreRadiusM: number; outerRadiusM: number;
    coreColor: string; outerColor: string;
    active: boolean; content: ReactNode;
  }[];
  roads?: {
    id: string; name: string; coordinates: [number, number];
    path?: [number, number][]; color: string; content: ReactNode;
    dashed?: boolean;
  }[];
  focusedRoad?: string;
  onSelectRoad?: (id: string) => void;
  expanded?: boolean;
  fitNonce?: number;
};
const center: [number, number] = [16.047, 108.205];

export const rainColors = ["#8fa2b4", "#30baad", "#f3bf62", "#f47d82"];
export function rainfallColor(rain?: Rain) {
  const value = rain?.rainfall_total_mm;
  return rainColors[value == null ? 0 : value < 10 ? 1 : value < 25 ? 2 : 3];
}

function View({ points, selected, compact, flood, roadPath, roadLat, roadLng, roadPositions, expanded, fitNonce }: Pick<Markers, "points" | "selected" | "compact" | "expanded" | "fitNonce"> & {
  flood: boolean; roadPath?: [number, number][]; roadLat?: number; roadLng?: number; roadPositions: [number, number][];
}) {
  const map = useMap();
  useEffect(() => {
    if (roadPath && roadPath.length >= 2) {
      map.fitBounds(latLngBounds(roadPath), { padding: [70, 70], maxZoom: 16, animate: true });
      return;
    }
    if (roadLat != null && roadLng != null) {
      map.setView([roadLat, roadLng], 15, { animate: true });
      return;
    }
    const focus = !compact && points.find((point) => point.code === selected);
    if (focus) map.setView([focus.latitude, focus.longitude], flood ? 14 : 13, { animate: true });
    else if (points.length || roadPositions.length) map.fitBounds(latLngBounds([...points.map((p): [number,number] => [p.latitude, p.longitude]), ...roadPositions]),
      { padding: [36, 36], maxZoom: flood ? 13 : compact ? 12 : 13, animate: false });
  }, [map, points, selected, compact, flood, roadPath, roadLat, roadLng, roadPositions, fitNonce]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (map.getPane("mapPane")?.isConnected) map.invalidateSize({ pan: false });
    }, 80);
    return () => window.clearTimeout(timer);
  }, [map, expanded]);
  useEffect(() => {
    const resize = new ResizeObserver(() => {
      if (map.getPane("mapPane")?.isConnected) map.invalidateSize({ pan: false });
    });
    resize.observe(map.getContainer());
    return () => resize.disconnect();
  }, [map]);
  return null;
}

export default function StationMap({ points, selected, focused, onSelect, latest, weather, compact, floodMarkers,
  showAreas, zones, roads, focusedRoad, onSelectRoad, expanded, fitNonce }: Markers) {
  const t = useText();
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
  const ordered = floodMarkers ? [...points.filter(p => p.code !== selected), ...points.filter(p => p.code === selected)] : points;
  const roadFocus = roads?.find(road => road.id === focusedRoad);
  // Freeze the coordinate set across horizon changes, which only alter styling.
  const roadBoundsKey = JSON.stringify(roads?.map(road => road.coordinates).sort(([a,b], [c,d]) => a-c || b-d) ?? []);
  const roadPositions = useMemo(() => JSON.parse(roadBoundsKey) as [number,number][], [roadBoundsKey]);
  const frameClass = (compact ? "map-frame compact-map" : "map-frame full-map")
    + (floodMarkers ? " flood-map-frame" : "")
    + (expanded ? " map-frame-expanded" : "");
  return <div className={frameClass}>
    {tileError && <span className="tile-note">{coast.data ? t("Offline coastline · Natural Earth") : t("Basemap tiles unavailable")}</span>}
    <MapContainer center={center} zoom={12} minZoom={10} maxZoom={18} scrollWheelZoom={!compact} zoomControl={!compact}>
      <TileLayer url={process.env.NEXT_PUBLIC_OSM_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png"}
        maxZoom={19} attribution={'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}
        eventHandlers={{ tileerror: () => setTileError(true), tileload: () => setTileError(false) }} />
      {tileError && coast.data && <GeoJSON data={coast.data} style={{
        className: "offline-coastline", color: "#71a5bb", weight: 2, opacity: .84, interactive: false,
      }} />}
      <View points={points} selected={floodMarkers ? focused ?? "" : selected} compact={compact}
        flood={Boolean(floodMarkers)} roadPath={roadFocus?.path} roadLat={roadFocus?.coordinates[0]} roadLng={roadFocus?.coordinates[1]}
        roadPositions={roadPositions} expanded={expanded} fitNonce={fitNonce} />
      {zones?.map(zone => (
        <div key={zone.id}>
          <Circle center={zone.center} radius={zone.outerRadiusM}
            pathOptions={{
              color: zone.outerColor, fillColor: zone.outerColor,
              fillOpacity: zone.active ? 0.14 : 0.06, weight: 1.5, dashArray: "5 5",
            }} interactive={false} />
          <Circle center={zone.center} radius={zone.coreRadiusM}
            pathOptions={{
              color: zone.coreColor, fillColor: zone.coreColor,
              fillOpacity: zone.active ? 0.28 : 0.12, weight: 2,
            }}>
            <Tooltip sticky>{zone.name}</Tooltip>
            <Popup maxHeight={260}>{zone.content}</Popup>
          </Circle>
        </div>
      ))}
      {showAreas && ordered.map(point => {
        const marker = floodMarkers?.[point.code];
        return marker?.radius ? <Circle key={point.code} center={[point.latitude, point.longitude]} radius={marker.radius}
          pathOptions={{ color: marker.color, fillColor: marker.color, fillOpacity: .14, dashArray: "6 6", weight: 1.5 }}
          interactive={false} /> : null;
      })}
      {ordered.map((point) => {
        const rain = latest[point.code];
        const now = weather.find((entry) => entry.location_code === point.code);
        const marker = floodMarkers?.[point.code];
        const color = marker?.color ?? rainfallColor(rain);
        const active = selected === point.code;
        return <CircleMarker key={point.code} center={[point.latitude, point.longitude]}
          eventHandlers={{ click: () => onSelect(point.code) }}
          radius={marker ? active ? 15 : 11 : active ? 11 : 8}
          pathOptions={{ color: "#fff", weight: active && marker ? 4 : 2, fillColor: color, fillOpacity: 1,
            className: marker ? active ? "flood-map-pin flood-map-pin-active" : "flood-map-pin" : undefined }}>
          {marker && <Tooltip key={active ? "selected" : "hover"} direction="top" offset={[0,-12]} permanent={active} className="flood-map-label">{point.name}</Tooltip>}
          <Popup autoPan={Boolean(marker)} maxHeight={marker ? 250 : undefined}>
            {marker ? marker.content : <><strong className="popup-name">{point.name}</strong>
            <div>{t("Daily rainfall:")} {displayNumber(rain?.rainfall_total_mm)} mm</div>
            {rain && <div>{rain.period_start} · {rain.rainfall_hours}/{rain.expected_hours} {t("h covered")}</div>}
            <div>{t("Modeled temperature:")} {displayNumber(now?.payload.values.temperature_2m)} °C</div>
            <div>{t("Modeled humidity:")} {displayNumber(now?.payload.values.relative_humidity_2m)}%</div>
            {now && <small>{localTime(now.valid_at)} ICT</small>}
            </>}
          </Popup>
        </CircleMarker>;
      })}
      {roads?.map(road => {
        const isFocused = road.id === focusedRoad;
        const startPt = road.path?.[0];
        const endPt = road.path && road.path.length >= 2 ? road.path[road.path.length - 1] : undefined;
        return <div key={road.id}>
          {road.path && road.path.length >= 2 && <>
            <Polyline positions={road.path} interactive={false}
              pathOptions={{ color: "#0f172a", weight: isFocused ? 13 : 9.5, opacity: isFocused ? 0.85 : 0.55, lineCap: "round", lineJoin: "round" }} />
            <Polyline positions={road.path}
              eventHandlers={onSelectRoad ? { click: () => onSelectRoad(road.id) } : undefined}
              pathOptions={{
                color: road.color, weight: isFocused ? 8.5 : 6, opacity: isFocused ? 1 : 0.94,
                lineCap: "round", lineJoin: "round", dashArray: road.dashed ? "8 6" : undefined,
              }}>
              <Tooltip sticky>{road.name}</Tooltip>
              <Popup maxHeight={320}>{road.content}</Popup>
            </Polyline>
          </>}
          {startPt && <CircleMarker center={startPt} radius={3.5} interactive={false}
            pathOptions={{ color: "#ffffff", weight: 1.5, fillColor: road.color, fillOpacity: 1 }} />}
          {endPt && <CircleMarker center={endPt} radius={3.5} interactive={false}
            pathOptions={{ color: "#ffffff", weight: 1.5, fillColor: road.color, fillOpacity: 1 }} />}
          <CircleMarker center={road.coordinates} radius={isFocused ? 9 : 5.5}
            eventHandlers={onSelectRoad ? { click: () => onSelectRoad(road.id) } : undefined}
            pathOptions={{ color: "#ffffff", weight: 2, fillColor: road.color, fillOpacity: 1, className: "flood-historical-pin" }}>
            <Tooltip key={isFocused ? "selected" : "hover"} permanent={isFocused} direction="top" offset={[0, -10]}>{road.name}</Tooltip>
            <Popup maxHeight={320}>{road.content}</Popup>
          </CircleMarker>
        </div>;
      })}
    </MapContainer>
  </div>;
}

