import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// VWorld (국토교통부) 타일 + Leaflet 폴리곤 렌더링.
// 카카오맵의 KakaoMap 인터페이스와 동일 props — MapScreen 교체 시 import 만 바꾸면 됨.

export interface MapMarker {
  sggCd: string;
  name: string;
  lat: number;
  lng: number;
  hasData: boolean;
}

export interface PolygonFeature {
  sggCd: string;
  name: string;
  paths: { lat: number; lng: number }[][];
  fillColor: string;
  changePct: number | null;
  subKey?: string;
  subName?: string | null;        // 폴리곤 중앙 보조 라벨 (예: 대표 법정동명)
}

interface Props {
  markers?: MapMarker[];
  onMarkerClick?: (sggCd: string) => void;
  polygons?: PolygonFeature[];
  onPolygonClick?: (sggCd: string, subKey?: string) => void;
  center?: { lat: number; lng: number };
  level?: number;          // VWorld zoom (Leaflet 7~18). Kakao level 과 호환되도록 변환.
  maxLevel?: number;       // Kakao "최대 줌아웃 레벨" → Leaflet minZoom 으로 매핑
}

// Kakao 의 level (1=최대확대, 14=최대축소) 와 Leaflet zoom (18=최대확대, 1=최대축소) 변환
function kakaoLevelToZoom(level: number): number {
  return Math.max(1, Math.min(18, 19 - level));
}

export default function VWorldMap({
  markers,
  onMarkerClick,
  polygons,
  onPolygonClick,
  center = { lat: 37.5665, lng: 126.978 },
  level = 9,
  maxLevel,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  // 1) 첫 마운트에서 config → 타일 키 fetch → Leaflet 지도 인스턴스 생성
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/realestate/config");
        const cfg = await r.json();
        const apiKey: string = cfg.vworld_api_key || "";
        if (cancelled || !containerRef.current) return;

        const initialZoom = kakaoLevelToZoom(level);
        const minZoom = maxLevel != null ? kakaoLevelToZoom(maxLevel) : 7;

        const map = L.map(containerRef.current, {
          center: [center.lat, center.lng],
          zoom: initialZoom,
          minZoom,
          maxZoom: 18,
          zoomControl: true,
          attributionControl: false,
        });

        // Prefer VWorld when configured; otherwise keep the map usable with a
        // keyless dark basemap so region polygons still render in production.
        const tileUrl = apiKey
          ? `https://api.vworld.kr/req/wmts/1.0.0/${apiKey}/midnight/{z}/{y}/{x}.png`
          : "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
        const attribution = apiKey ? "" : "&copy; OpenStreetMap &copy; CARTO";
        L.tileLayer(
          tileUrl,
          { maxZoom: 18, tileSize: 256, attribution }
        ).addTo(map);

        mapRef.current = map;
        setReady(true);

        // 컨테이너 크기 변할 때마다 invalidateSize 호출 (라우팅 복귀 시 0×0 방지)
        if (containerRef.current && "ResizeObserver" in window) {
          const ro = new ResizeObserver(() => mapRef.current?.invalidateSize());
          ro.observe(containerRef.current);
          (mapRef.current as any).__ro = ro;
        }
        requestAnimationFrame(() => mapRef.current?.invalidateSize());
      } catch (e: any) {
        if (!cancelled) setError(e.message ?? String(e));
      }
    })();
    return () => {
      cancelled = true;
      const ro = (mapRef.current as any)?.__ro;
      if (ro) ro.disconnect();
      mapRef.current?.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2) markers
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !markers || markers.length === 0) return;
    const created: L.Layer[] = [];
    markers.forEach((m) => {
      const icon = L.divIcon({
        className: "",
        html: `<div style="
          padding: 4px 10px; border-radius: 14px; font-size: 12px; font-weight: 600;
          background: ${m.hasData ? "#3b82f6" : "#374151"};
          color: #fff; box-shadow: 0 2px 6px rgba(0,0,0,0.25);
          white-space: nowrap; cursor: pointer;
          transform: translate(-50%, -130%);">${m.name}</div>`,
        iconSize: [0, 0],
      });
      const marker = L.marker([m.lat, m.lng], { icon });
      marker.on("click", () => onMarkerClick?.(m.sggCd));
      marker.addTo(map);
      created.push(marker);
    });
    return () => {
      created.forEach((l) => l.remove());
    };
  }, [markers, onMarkerClick, ready]);

  // 3) polygons — Leaflet path 는 SVG. interactive=true 명시 + bubblingMouseEvents=false
  // 로 click 이 다른 layer 로 흘러가지 않도록. 폴리곤 1개당 가장 큰 ring 의 centroid
  // 위치에 라벨 (시군구 · 동) 마커 1개 추가 — interactive:false 로 클릭은 폴리곤이 받음.
  // 줌 레벨 < LABEL_MIN_ZOOM 이면 모든 라벨 숨김 (수도권 전체 줌아웃 시 너무 빽빽).
  useEffect(() => {
    const mapInst = mapRef.current;
    if (!ready || !mapInst || !polygons || polygons.length === 0) return;
    const map: L.Map = mapInst;     // narrow non-null reference for closure usage
    const created: L.Layer[] = [];
    const labelMarkers: L.Marker[] = [];
    const LABEL_MIN_ZOOM = 9;       // 이 줌 미만이면 라벨 숨김 (수도권 overview 시 정리)

    function ringCentroid(ring: { lat: number; lng: number }[]) {
      let sLat = 0, sLng = 0;
      for (const p of ring) { sLat += p.lat; sLng += p.lng; }
      return { lat: sLat / ring.length, lng: sLng / ring.length };
    }

    polygons.forEach((poly) => {
      let largestRing: { lat: number; lng: number }[] | null = null;
      poly.paths.forEach((ring) => {
        if (!largestRing || ring.length > largestRing.length) largestRing = ring;
        const latlngs = ring.map((p) => [p.lat, p.lng] as [number, number]);
        const lpoly = L.polygon(latlngs, {
          color: "#111827",
          weight: 1,
          opacity: 0.8,
          fillColor: poly.fillColor,
          fillOpacity: 0.45,
          interactive: true,
          bubblingMouseEvents: false,
        });
        lpoly.on("click", (e) => {
          L.DomEvent.stop(e.originalEvent);
          onPolygonClick?.(poly.sggCd, poly.subKey);
        });
        lpoly.on("mouseover", () => lpoly.setStyle({ fillOpacity: 0.65 }));
        lpoly.on("mouseout", () => lpoly.setStyle({ fillOpacity: 0.45 }));
        lpoly.addTo(map);
        created.push(lpoly);
      });

      // 라벨 — 가장 큰 ring 의 centroid 위에 배치 (다중 ring 시 본체 폴리곤 위로).
      // 시군구명만 노출 (사용자 요청 — 동명 보조 라벨 제거).
      if (largestRing) {
        const c = ringCentroid(largestRing);
        const html = `
          <div style="
            font-family: 'JetBrains Mono', 'Pretendard Variable', monospace;
            font-size: 10.5px;
            font-weight: 700;
            letter-spacing: -0.2px;
            padding: 2px 6px;
            background: rgba(0,0,0,0.62);
            border: 1px solid rgba(255,140,0,0.32);
            border-radius: 3px;
            white-space: nowrap;
            text-shadow: 0 1px 2px rgba(0,0,0,0.9);
            transform: translate(-50%, -50%);
            user-select: none;
            color: #ffaa44;
          ">${poly.name}</div>`;
        const marker = L.marker([c.lat, c.lng], {
          icon: L.divIcon({ className: "polygon-label", html, iconSize: [0, 0] }),
          interactive: false,                 // 클릭은 아래 폴리곤이 받도록
          keyboard: false,
        });
        labelMarkers.push(marker);
      }
    });

    function applyLabelVisibility() {
      const visible = map.getZoom() >= LABEL_MIN_ZOOM;
      labelMarkers.forEach((m) => {
        const onMap = (m as any)._added === true;
        if (visible && !onMap) { m.addTo(map); (m as any)._added = true; }
        else if (!visible && onMap) { m.remove(); (m as any)._added = false; }
      });
    }
    applyLabelVisibility();
    map.on("zoomend", applyLabelVisibility);

    return () => {
      created.forEach((l) => l.remove());
      labelMarkers.forEach((m) => m.remove());
      map.off("zoomend", applyLabelVisibility);
    };
  }, [polygons, onPolygonClick, ready]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80 text-red-300 p-4 text-sm">
          지도 로드 실패: {error}
          <br />
          잠시 후 다시 시도해 주세요.
        </div>
      )}
    </div>
  );
}
