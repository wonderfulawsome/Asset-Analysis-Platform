import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import KakaoMap, { PolygonFeature } from "../components/KakaoMap";
import FeatureCard from "../components/FeatureCard";
import MarketSummaryCard from "../components/MarketSummaryCard";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import { changePctColor } from "../lib/color";
import type { SggOverview, BuySignal, RegionSummary } from "../types/api";

// 수도권(서울+경기+인천) 시군구 폴리곤. scripts/build_metro_geojson.py 가
// southkorea-maps(2013) 데이터를 행안부 LAWD_CD(5자리)로 변환해
// metro-sgg.geojson 으로 저장하므로, properties.sgg_cd 를 직접 읽어서 매칭.

// 모듈 레벨 캐시 — 라우팅으로 MapScreen unmount 후 재마운트 시 fetch 재실행 회피.
// 첫 마운트만 비동기 fetch, 이후 마운트는 캐시값으로 즉시 setState.
let _cachedPolygons: PolygonFeature[] | null = null;
let _cachedOverviews: Map<string, SggOverview> | null = null;
let _cachedGeoJson: any = null;

async function fetchGeoJson() {
  if (_cachedGeoJson) return _cachedGeoJson;
  const res = await fetch("/static/realestate/geojson/metro-sgg.geojson");
  _cachedGeoJson = await res.json();
  return _cachedGeoJson;
}

interface SelectedRegion {
  sggCd: string;
  sggNm: string;
  topStdgNm: string | null;
  topStdgCd: string | null;
  medianPricePerPy: number | null;
  changePct: number | null;        // FeatureCard 표시용 — 1개월(전월) 대비 변화
}

// GeoJSON FeatureCollection → KakaoMap 의 PolygonFeature[] 로 변환.
async function loadPolygons(overviews: Map<string, SggOverview>): Promise<PolygonFeature[]> {
  const geo = await fetchGeoJson();
  const polys: PolygonFeature[] = [];
  for (const feat of geo.features ?? []) {
    const sggCd = feat.properties?.sgg_cd as string | undefined;
    const name = feat.properties?.name as string | undefined;
    const subKey = feat.properties?.bucheon_sub as string | undefined;
    if (!sggCd || !name) continue;
    const ov = overviews.get(sggCd);
    const change = ov?.change_pct_3m ?? null;
    const fillColor = changePctColor(change);

    // GeoJSON 좌표 = [lng, lat]. 카카오는 LatLng(lat, lng) 라 변환 필요.
    const geom = feat.geometry;
    const rings: { lat: number; lng: number }[][] = [];
    if (geom.type === "MultiPolygon") {
      for (const poly of geom.coordinates) {
        for (const ring of poly) {
          rings.push(ring.map(([lng, lat]: [number, number]) => ({ lat, lng })));
        }
      }
    } else if (geom.type === "Polygon") {
      for (const ring of geom.coordinates) {
        rings.push(ring.map(([lng, lat]: [number, number]) => ({ lat, lng })));
      }
    }
    polys.push({ sggCd, name, paths: rings, fillColor, changePct: change, subKey });
  }
  return polys;
}

export default function MapScreen() {
  const navigate = useNavigate();
  // 모듈 캐시 hit 시 초기 state 가 즉시 채워져 첫 paint 부터 지도·색상 표시
  const [polygons, setPolygons] = useState<PolygonFeature[]>(_cachedPolygons ?? []);
  const [overviews, setOverviews] = useState<Map<string, SggOverview>>(_cachedOverviews ?? new Map());
  const [selected, setSelected] = useState<SelectedRegion | null>(null);
  const [signal, setSignal] = useState<BuySignal | null>(null);
  const [topStdgSummary, setTopStdgSummary] = useState<RegionSummary | null>(null);
  const [loading, setLoading] = useState(false);    // FeatureCard fetch 진행 표시

  useEffect(() => {
    // 캐시 hit 면 fetch skip — detail 페이지에서 돌아왔을 때 즉시 표시
    if (_cachedPolygons && _cachedOverviews) return;
    let cancelled = false;
    apiFetch<SggOverview[]>(ENDPOINTS.sggOverview())
      .then(async (rows) => {
        if (cancelled) return;
        const map = new Map<string, SggOverview>();
        rows.forEach((r) => map.set(r.sgg_cd, r));
        _cachedOverviews = map;
        setOverviews(map);
        const polys = await loadPolygons(map);
        if (!cancelled) {
          _cachedPolygons = polys;
          setPolygons(polys);
        }
      })
      .catch((e) => console.error("[MapScreen] load fail", e));
    return () => { cancelled = true; };
  }, []);

  function handlePolygonClick(sggCd: string, subKey?: string) {
    const ov = overviews.get(sggCd);
    const sggNm = polygons.find((p) => p.sggCd === sggCd && p.subKey === subKey)?.name
                  ?? polygons.find((p) => p.sggCd === sggCd)?.name
                  ?? sggCd;
    // 부천(41194) 만 — 폴리곤 sub_key (sosa/wonmi/ojeong) 와 매칭되는 sub_top 우선 사용.
    // sub 데이터 없으면 sgg 전체 top 폴백.
    const sub = subKey ? ov?.bucheon_sub_top?.[subKey] : undefined;
    const topStdgCd = sub?.top_stdg_cd ?? ov?.top_stdg_cd ?? null;
    const topStdgNm = sub?.top_stdg_nm ?? ov?.top_stdg_nm ?? null;
    const medianPp = sub?.median_price_per_py ?? ov?.median_price_per_py ?? null;
    setSelected({
      sggCd,
      sggNm,
      topStdgNm,
      topStdgCd,
      medianPricePerPy: medianPp,
      // FeatureCard 표시용 = 1개월 전 대비 (사용자 의도). 폴리곤 색칠은 3M 그대로.
      changePct: ov?.change_pct_1m ?? null,
    });
    // 시그널 + 대표 법정동 summary 병렬 fetch — 끝날 때까지 loading=true
    setSignal(null);
    setTopStdgSummary(null);
    setLoading(true);
    const tasks: Promise<unknown>[] = [];
    tasks.push(
      apiFetch<BuySignal | Record<string, never>>(ENDPOINTS.buySignal(sggCd))
        .then((s) => {
          if (s && (s as BuySignal).signal) setSignal(s as BuySignal);
        })
        .catch(() => {})
    );
    if (sub) {
      // 부천 sub-area — raw 집계라 region_summary 에 그 동 row 가 없을 수 있어
      // backend 가 준 trade_count 를 직접 가짜 RegionSummary 로 set (FeatureCard 거래량 표기용).
      setTopStdgSummary({
        sgg_cd: sggCd,
        stdg_cd: sub.top_stdg_cd,
        stdg_nm: sub.top_stdg_nm,
        stats_ym: ov?.stats_ym ?? '',
        trade_count: sub.trade_count,
        avg_price: null, median_price: null,
        median_price_per_py: sub.median_price_per_py,
        jeonse_count: null, wolse_count: null, avg_deposit: null,
        population: null, solo_rate: null,
      } as RegionSummary);
    } else if (topStdgCd) {
      tasks.push(
        apiFetch<RegionSummary[]>(ENDPOINTS.summary(sggCd))
          .then((rows) => {
            const match = rows.find((r) => r.stdg_cd === topStdgCd) ?? rows[0] ?? null;
            if (match) setTopStdgSummary(match);
          })
          .catch(() => {})
      );
    }
    Promise.all(tasks).finally(() => setLoading(false));
  }

  return (
    <div className="relative h-full w-full">
      <KakaoMap
        polygons={polygons}
        onPolygonClick={handlePolygonClick}
        center={{ lat: 37.45, lng: 127.0 }}
        level={11}
        maxLevel={11}
      />

      {/* 플로팅 상단 검색바 */}
      <div className="absolute top-3 left-3 right-3 z-10">
        <div className="bg-gray-900/95 backdrop-blur-md rounded-2xl shadow-xl
                        border border-gray-800 flex items-center gap-2 px-4 py-3">
          <span className="text-gray-400">🔍</span>
          <input
            type="text"
            placeholder="지역·단지·지하철역 검색"
            className="flex-1 bg-transparent outline-none text-sm placeholder-gray-500"
            onFocus={() => navigate("/search")}
            readOnly
          />
        </div>
        {/* 오늘의 시장 요약 LLM 카드 */}
        <MarketSummaryCard />

        {/* 색상 범례 */}
        <div className="mt-2 flex items-center gap-2 text-[10px] text-gray-300
                        bg-gray-900/80 backdrop-blur rounded-lg px-3 py-1.5 w-fit">
          <span>3M 변화율:</span>
          <Legend color="#dc2626" label="+5↑" />
          <Legend color="#f87171" label="+1~5" />
          <Legend color="#9ca3af" label="±1" />
          <Legend color="#60a5fa" label="-1~-5" />
          <Legend color="#2563eb" label="-5↓" />
        </div>
      </div>

      <FeatureCard
        selected={selected}
        signal={signal}
        topStdgSummary={topStdgSummary}
        loading={loading}
        onTap={() => {
          if (selected?.topStdgCd) navigate(`/stdg/${selected.topStdgCd}`);
        }}
        onTapSgg={() => {
          if (selected?.sggCd) navigate(`/region/${selected.sggCd}`);
        }}
        onClose={() => {
          setSelected(null);
          setSignal(null);
          setTopStdgSummary(null);
        }}
      />
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}
