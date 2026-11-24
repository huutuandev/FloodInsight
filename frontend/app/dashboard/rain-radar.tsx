"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DomEvent, type LatLngTuple } from "leaflet";
import { Radio } from "lucide-react";
import { Pane, TileLayer, useMap } from "react-leaflet";
import { localTime } from "./data";

const metadataUrl = "https://api.rainviewer.com/public/weather-maps.json";
const tileHost = "https://tilecache.rainviewer.com";
const tileGrid = "512/{z}/{x}/{y}";
const maxNativeZoom = 7;
const attribution = '<a href="https://www.rainviewer.com/">Radar © RainViewer</a>';

type Frame = { time: number; path: string };
type TileState = "loading" | "ready" | "partial" | "failed";

async function fetchFrames(signal: AbortSignal) {
  const response = await fetch(metadataUrl, { signal });
  if (!response.ok) throw new Error("Không tải được danh sách ảnh radar.");
  const value = await response.json();
  if (value?.host !== tileHost || !Array.isArray(value?.radar?.past)) {
    throw new Error("Nguồn radar trả về dữ liệu không hợp lệ.");
  }
  const frames = new Map<number, Frame>();
  for (const frame of value.radar.past) {
    if (Number.isSafeInteger(frame?.time) && frame.time > 0 && frame.time < 4_102_444_800
        && typeof frame.path === "string" && /^\/v2\/radar\/[a-z0-9]+$/i.test(frame.path)) {
      frames.set(frame.time, { time: frame.time, path: frame.path });
    }
  }
  return [...frames.values()].sort((a, b) => a.time - b.time);
}

function RadarTiles({ url, onStatus }: { url: string; onStatus: (status: TileState) => void }) {
  const attempts = useRef({ loaded: 0, failed: 0 });
  return <TileLayer url={url} maxNativeZoom={maxNativeZoom} maxZoom={19}
    opacity={0.8} zIndex={2} noWrap attribution={attribution}
    eventHandlers={{
      loading: () => {
        attempts.current = { loaded: 0, failed: 0 };
        onStatus("loading");
      },
      tileload: () => { attempts.current.loaded += 1; },
      tileerror: () => { attempts.current.failed += 1; },
      load: () => {
        const { loaded, failed } = attempts.current;
        onStatus(failed ? (loaded ? "partial" : "failed") : "ready");
      },
    }} />;
}

export function RainRadar({ center }: { center: LatLngTuple }) {
  const map = useMap();
  const controls = useRef<HTMLDivElement>(null);
  const [enabled, setEnabled] = useState(true);
  const [coverage, setCoverage] = useState(false);
  const [coverageError, setCoverageError] = useState(false);
  const [selectedTime, setSelectedTime] = useState<number>();
  const [playing, setPlaying] = useState(false);
  const [retry, setRetry] = useState(0);
  const [lastTileStatus, setLastTileStatus] = useState<{ key: string; state: TileState }>();
  const query = useQuery({
    queryKey: ["rainviewer-weather-maps"],
    queryFn: ({ signal }) => fetchFrames(signal),
    enabled,
    staleTime: 2 * 60_000,
    refetchInterval: 2 * 60_000,
    retry: 1,
  });
  const frames = query.data ?? [];
  const latest = frames.at(-1);
  const selectedIndex = frames.findIndex((frame) => frame.time === selectedTime);
  const frameIndex = selectedIndex < 0 ? frames.length - 1 : selectedIndex;
  const frame = frames[frameIndex];
  const url = frame && `${tileHost}${frame.path}/${tileGrid}/2/1_0.png`;
  const layerKey = `${url}:${retry}`;
  const tileState = lastTileStatus?.key === layerKey ? lastTileStatus.state : "loading";
  const stale = latest && Date.now() - latest.time * 1000 > 30 * 60_000;

  useEffect(() => {
    if (!controls.current) return;
    DomEvent.disableClickPropagation(controls.current);
    DomEvent.disableScrollPropagation(controls.current);
  }, []);

  const nextTime = frames[(frameIndex + 1) % frames.length]?.time;
  useEffect(() => {
    if (!enabled || !playing || nextTime == null || (tileState !== "ready" && tileState !== "partial")) return;
    const timer = window.setTimeout(() => setSelectedTime(nextTime), 900);
    return () => window.clearTimeout(timer);
  }, [enabled, playing, nextTime, tileState, layerKey]);

  const status = query.isError ? "Không cập nhật được danh sách ảnh radar."
    : query.isPending ? "Đang tải danh sách ảnh radar…"
    : !frame ? "RainViewer chưa có ảnh radar."
    : tileState === "failed" ? "Không tải được ảnh radar."
    : tileState === "partial" ? "Một phần ảnh radar chưa tải được."
    : tileState === "loading" ? "Đang tải ảnh radar…"
    : stale ? "Khung mới nhất đã hơn 30 phút."
    : "";

  return <>
    <div ref={controls} className="radar-overlay-controls" role="region" aria-label="Điều khiển radar mưa">
      <div className="radar-header">
        <strong className="radar-title"><Radio size={15} /> Radar mưa</strong>
        <button type="button" className="radar-button" aria-pressed={enabled} onClick={() => {
          setEnabled(!enabled);
          setPlaying(false);
          if (!enabled) setRetry((value) => value + 1);
        }}>{enabled ? "Tắt radar" : "Bật radar"}</button>
      </div>
      {enabled && <>
        <div className="radar-meta">
          {frame ? <>Khung ảnh {localTime(new Date(frame.time * 1000).toISOString())} ICT</> : "Nguồn ảnh RainViewer"}
        </div>
        {frames.length > 1 && <>
          <input className="radar-timeline" type="range" min={0} max={frames.length - 1} step={1}
            value={frameIndex} aria-label="Khung thời gian radar"
            aria-valuetext={localTime(new Date(frame.time * 1000).toISOString()) + " ICT"}
            onChange={(event) => {
              setPlaying(false);
              setSelectedTime(frames[Number(event.target.value)]?.time);
            }} />
          <div className="radar-actions">
            <button type="button" className="radar-button" onClick={() => {
              if (!playing && frameIndex === frames.length - 1) setSelectedTime(frames[0].time);
              setPlaying(!playing);
            }}>{playing ? "Tạm dừng" : "Phát"}</button>
            <button type="button" className="radar-button" onClick={() => {
              setPlaying(false);
              setSelectedTime(undefined);
            }}>Mới nhất</button>
          </div>
        </>}
        <div className="radar-actions">
          <button type="button" className="radar-button" onClick={() => map.setView(center, 8)}>Xem toàn vùng</button>
          <button type="button" className="radar-button" aria-pressed={coverage}
            onClick={() => { setCoverageError(false); setCoverage(!coverage); }}>Vùng phủ</button>
        </div>
        {coverage && <div className="radar-meta">
          {coverageError ? "Không tải được mặt nạ vùng phủ." : "Vùng tô tối nằm ngoài vùng phủ ước tính."}
        </div>}
        {status && <div className="radar-meta" role="status">{status}</div>}
        {(query.isError || tileState === "failed" || tileState === "partial" || (!query.isPending && !frame)) && (
          <button type="button" className="radar-button" onClick={() => {
            setRetry((value) => value + 1);
            if (query.isError || !frame) void query.refetch();
          }}>Tải lại ảnh radar</button>
        )}
      </>}
    </div>
    <Pane name="rainviewer" style={{ zIndex: 250, pointerEvents: "none" }}>
      {enabled && coverage && <TileLayer url={`${tileHost}/v2/coverage/0/${tileGrid}/0/0_0.png`}
        opacity={0.32} zIndex={1} maxNativeZoom={maxNativeZoom} maxZoom={19} noWrap attribution={attribution}
        eventHandlers={{ tileerror: () => setCoverageError(true) }} />}
      {enabled && url && <RadarTiles key={layerKey} url={url}
        onStatus={(state) => setLastTileStatus({ key: layerKey, state })} />}
    </Pane>
  </>;
}
