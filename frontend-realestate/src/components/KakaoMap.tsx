import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    kakao: any;
  }
}

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
  // Kakao LatLng 변환 전 좌표 — outer/inner ring 모두 포함 가능 (MultiPolygon 평탄화)
  paths: { lat: number; lng: number }[][];
  fillColor: string;        // changePctColor() 결과
  changePct: number | null;
}

interface Props {
  markers?: MapMarker[];
  onMarkerClick?: (sggCd: string) => void;
  polygons?: PolygonFeature[];
  onPolygonClick?: (sggCd: string) => void;
  center?: { lat: number; lng: number };
  level?: number;
  maxLevel?: number;  // 최대 줌아웃 제한 — 작을수록 축소 못 함 (수도권만 보이도록 11~12 권장)
}

let sdkPromise: Promise<void> | null = null;

function loadKakaoSdk(appkey: string): Promise<void> {
  if (window.kakao?.maps) return Promise.resolve();
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${appkey}&autoload=false`;
    s.async = true;
    s.onload = () => window.kakao.maps.load(() => resolve());
    s.onerror = () => reject(new Error("카카오맵 SDK 로드 실패"));
    document.head.appendChild(s);
  });
  return sdkPromise;
}

export default function KakaoMap({
  markers,
  onMarkerClick,
  polygons,
  onPolygonClick,
  center = { lat: 37.5665, lng: 126.978 },
  level = 9,
  maxLevel,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  // 1) 첫 마운트에서 config → SDK 로드 → 지도 인스턴스 생성
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/realestate/config");
        const { kakao_js_key } = await r.json();
        if (!kakao_js_key) throw new Error("KAKAO_JS_KEY 미설정");
        await loadKakaoSdk(kakao_js_key);
        if (cancelled || !containerRef.current) return;
        const { kakao } = window;
        mapRef.current = new kakao.maps.Map(containerRef.current, {
          center: new kakao.maps.LatLng(center.lat, center.lng),
          level,
        });
        // 줌아웃 제한 — maxLevel 지정 시 사용자가 그 이상 축소 못 함 (수도권만 보이도록)
        if (maxLevel != null) {
          mapRef.current.setMaxLevel(maxLevel);
        }
        setReady(true);
      } catch (e: any) {
        if (!cancelled) setError(e.message ?? String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2) markers — 기존 호환
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !window.kakao || !markers || markers.length === 0) return;
    const { kakao } = window;
    const created: any[] = [];
    markers.forEach((m) => {
      const pos = new kakao.maps.LatLng(m.lat, m.lng);
      const marker = new kakao.maps.Marker({ position: pos, map });
      const label = new kakao.maps.CustomOverlay({
        position: pos,
        yAnchor: 2.4,
        content: `<div style="
          padding: 4px 10px; border-radius: 14px; font-size: 12px; font-weight: 600;
          background: ${m.hasData ? "#3b82f6" : "#374151"};
          color: #fff; box-shadow: 0 2px 6px rgba(0,0,0,0.25);
          white-space: nowrap; cursor: pointer;">${m.name}</div>`,
        map,
      });
      kakao.maps.event.addListener(marker, "click", () => onMarkerClick?.(m.sggCd));
      created.push(marker, label);
    });
    return () => {
      created.forEach((obj) => obj.setMap?.(null));
    };
  }, [markers, onMarkerClick, ready]);

  // 3) polygons — 신규. paths 가 [[ring1], [ring2]] 형식이라 각 폴리곤마다 Kakao Polygon 1개 생성.
  // MultiPolygon 의 여러 외곽 polygon 은 따로 그려야 정상 렌더 (kakao Polygon 은 단일 path 만 지원).
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !window.kakao || !polygons || polygons.length === 0) return;
    const { kakao } = window;
    const created: any[] = [];
    polygons.forEach((poly) => {
      poly.paths.forEach((ring) => {
        const path = ring.map((p) => new kakao.maps.LatLng(p.lat, p.lng));
        const kpoly = new kakao.maps.Polygon({
          map,
          path,
          fillColor: poly.fillColor,
          fillOpacity: 0.45,
          strokeWeight: 1,
          strokeColor: "#111827",
          strokeOpacity: 0.8,
        });
        kakao.maps.event.addListener(kpoly, "click", () => onPolygonClick?.(poly.sggCd));
        kakao.maps.event.addListener(kpoly, "mouseover", () => kpoly.setOptions({ fillOpacity: 0.65 }));
        kakao.maps.event.addListener(kpoly, "mouseout", () => kpoly.setOptions({ fillOpacity: 0.45 }));
        created.push(kpoly);
      });
    });
    return () => {
      created.forEach((p) => p.setMap?.(null));
    };
  }, [polygons, onPolygonClick, ready]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80 text-red-300 p-4 text-sm">
          지도 로드 실패: {error}
          <br />
          카카오 개발자 콘솔 JS 키에 현재 도메인이 등록되어 있는지 확인하세요.
        </div>
      )}
    </div>
  );
}
