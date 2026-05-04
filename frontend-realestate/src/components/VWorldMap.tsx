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
        if (!apiKey) throw new Error("VWORLD_API_KEY 미설정");
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

        // VWorld 야간(midnight) 타일 — 터미널 검정 테마와 매칭
        L.tileLayer(
          `https://api.vworld.kr/req/wmts/1.0.0/${apiKey}/midnight/{z}/{y}/{x}.png`,
          { maxZoom: 18, tileSize: 256 }
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
  // 로 click 이 다른 layer 로 흘러가지 않도록.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !polygons || polygons.length === 0) return;
    const created: L.Layer[] = [];
    polygons.forEach((poly) => {
      poly.paths.forEach((ring) => {
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
          // Leaflet click event — DomEvent.stop 으로 map click 으로 안 전파
          L.DomEvent.stop(e.originalEvent);
          console.log("[VWorldMap] polygon click", poly.sggCd, poly.subKey);
          onPolygonClick?.(poly.sggCd, poly.subKey);
        });
        lpoly.on("mouseover", () => lpoly.setStyle({ fillOpacity: 0.65 }));
        lpoly.on("mouseout", () => lpoly.setStyle({ fillOpacity: 0.45 }));
        lpoly.addTo(map);
        created.push(lpoly);
      });
    });
    return () => {
      created.forEach((l) => l.remove());
    };
  }, [polygons, onPolygonClick, ready]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80 text-red-300 p-4 text-sm">
          지도 로드 실패: {error}
          <br />
          VWorld 개발자 콘솔에서 API 키 발급 + 도메인 등록을 확인하세요.
        </div>
      )}
    </div>
  );
}
