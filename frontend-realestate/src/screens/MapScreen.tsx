import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import VWorldMap, { PolygonFeature } from "../components/VWorldMap";
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
let _cachedPolygons: PolygonFeature[] | null = null;          // 시군구 폴리곤 (~50)
let _cachedEmdPolygons: PolygonFeature[] | null = null;       // 행정동 폴리곤 (~1100, lazy)
let _cachedOverviews: Map<string, SggOverview> | null = null;
let _cachedGeoJson: any = null;
// emd-overview 의 row 단위 저장 — fillColor + click 시 stdg_cd 라우팅용.
type EmdRow = {
  sgg_cd: string;
  stdg_cd: string;
  stdg_nm: string;
  change_pct_1m: number | null;
  median_price_per_py: number | null;
};
let _cachedEmdLookup: Map<string, Map<string, EmdRow>> | null = null;  // sgg_cd → norm_name → row
let _emdLoadPromise: Promise<PolygonFeature[]> | null = null;
let _emdLookupPromise: Promise<Map<string, Map<string, EmdRow>>> | null = null;

const EMD_MIN_ZOOM = 11;                                      // Leaflet zoom ≥ 11 일 때 행정동 outline overlay 노출

// 행정동 ↔ 법정동 이름 정규화 — KOSTAT 행정동의 숫자 접미사 제거.
//   사직동 → 사직동, 신흥1동 → 신흥동, 왕십리2동 → 왕십리동, 화수1·화평동 → 화수·화평동
function normalizeStdgName(s: string): string {
  return s.replace(/\d+동/g, '동').replace(/\s+/g, '').trim();
}

async function fetchGeoJson() {
  if (_cachedGeoJson) return _cachedGeoJson;
  const res = await fetch("/static/realestate/geojson/metro-sgg.geojson");
  _cachedGeoJson = await res.json();
  return _cachedGeoJson;
}

// 법정동(stdg) 단위 lookup — EMD 폴리곤 색상 + 클릭 시 stdg 상세 라우팅용.
async function loadEmdLookup(): Promise<Map<string, Map<string, EmdRow>>> {
  if (_cachedEmdLookup) return _cachedEmdLookup;
  if (_emdLookupPromise) return _emdLookupPromise;
  _emdLookupPromise = (async () => {
    const res = await fetch("/api/realestate/emd-overview");
    const rows: EmdRow[] = await res.json();
    const lookup = new Map<string, Map<string, EmdRow>>();
    for (const r of rows) {
      if (!r.sgg_cd || !r.stdg_nm) continue;
      let bySgg = lookup.get(r.sgg_cd);
      if (!bySgg) { bySgg = new Map(); lookup.set(r.sgg_cd, bySgg); }
      bySgg.set(normalizeStdgName(r.stdg_nm), r);
    }
    _cachedEmdLookup = lookup;
    _emdLookupPromise = null;
    return lookup;
  })();
  return _emdLookupPromise;
}

// 행정동(읍·면·동) 폴리곤 lazy fetch + 변환.
// 색상 결정 우선순위:
//   1) emdLookup[mois_sgg_cd][정규화된 EMD 이름] → 법정동 단위 change_pct_1m (per-EMD distinct)
//   2) overviews[mois_sgg_cd].change_pct_1m → parent 시군구 색 fallback
//   3) 둘 다 없으면 fill 없음 (스트로크만)
async function loadEmdPolygons(
  overviews: Map<string, SggOverview>,
  emdLookup: Map<string, Map<string, EmdRow>>,
): Promise<PolygonFeature[]> {
  if (_cachedEmdPolygons) return _cachedEmdPolygons;
  if (_emdLoadPromise) return _emdLoadPromise;
  _emdLoadPromise = (async () => {
    const res = await fetch("/static/realestate/geojson/metro-emd.geojson");
    const geo = await res.json();
    const polys: PolygonFeature[] = [];
    let stdgMatched = 0, sggFallback = 0, noColor = 0;
    for (const feat of geo.features ?? []) {
      const code = feat.properties?.code as string | undefined;
      const name = feat.properties?.name as string | undefined;
      const moisSggCd = feat.properties?.mois_sgg_cd as string | undefined;
      if (!code || !name) continue;
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
      // 1) per-EMD 단위 (법정동 단위) — name 정규화 후 lookup, 매칭되면 stdg row 사용
      let change: number | null = null;
      let matchedStdgCd: string | undefined = undefined;
      if (moisSggCd) {
        const bySgg = emdLookup.get(moisSggCd);
        const stdgRow = bySgg?.get(normalizeStdgName(name));
        if (stdgRow) {
          matchedStdgCd = stdgRow.stdg_cd;            // 클릭 시 라우팅 키
          if (stdgRow.change_pct_1m != null) {
            change = stdgRow.change_pct_1m;
            stdgMatched++;
          }
        }
      }
      // 2) parent 시군구 fallback (색상만)
      if (change == null && moisSggCd) {
        const parentOv = overviews.get(moisSggCd);
        if (parentOv?.change_pct_1m != null) {
          change = parentOv.change_pct_1m;
          sggFallback++;
        }
      }
      const fillColor = change != null ? changePctColor(change) : "";
      if (!fillColor) noColor++;
      polys.push({
        sggCd: moisSggCd ?? code,
        name,
        paths: rings,
        fillColor,
        changePct: change,
        subKey: matchedStdgCd,           // 매칭된 stdg_cd → click 시 /stdg/{stdgCd} 라우팅
        // noLabel 제거 — VWorldMap 의 overlay 라벨 로직이 줌 13+ 에서만 노출하므로 밀도 안전.
      });
    }
    console.log(`[MapScreen] EMD coloring: stdgMatched=${stdgMatched}, sggFallback=${sggFallback}, noColor=${noColor}, total=${polys.length}`);
    _cachedEmdPolygons = polys;
    _emdLoadPromise = null;
    return polys;
  })();
  return _emdLoadPromise;
}

function fallbackOverviewsFromGeo(geo: any): SggOverview[] {
  const bySgg = new Map<string, SggOverview>();
  for (const feat of geo.features ?? []) {
    const sggCd = feat.properties?.sgg_cd as string | undefined;
    const name = feat.properties?.name as string | undefined;
    if (!sggCd || bySgg.has(sggCd)) continue;
    bySgg.set(sggCd, {
      sgg_cd: sggCd,
      sgg_nm: name ?? null,
      stats_ym: "",
      median_price_per_py: null,
      change_pct_3m: null,
      change_pct_1m: null,
      trade_count: 0,
      top_stdg_cd: null,
      top_stdg_nm: name ?? null,
    });
  }
  return [...bySgg.values()];
}

interface SelectedRegion {
  sggCd: string;
  sggNm: string;
  topStdgNm: string | null;
  topStdgCd: string | null;
  medianPricePerPy: number | null;
  changePct: number | null;        // FeatureCard 표시용 — 1개월(전월) 대비 변화
}

// GeoJSON FeatureCollection → VWorldMap 의 PolygonFeature[] 로 변환.
async function loadPolygons(overviews: Map<string, SggOverview>): Promise<PolygonFeature[]> {
  const geo = await fetchGeoJson();
  const polys: PolygonFeature[] = [];
  for (const feat of geo.features ?? []) {
    const sggCd = feat.properties?.sgg_cd as string | undefined;
    const name = feat.properties?.name as string | undefined;
    const subKey = feat.properties?.bucheon_sub as string | undefined;
    if (!sggCd || !name) continue;
    const ov = overviews.get(sggCd);
    // 폴리곤 색칠 = 전월(1개월) 대비 — 사용자 요청. 빨강=상승, 파랑=하락 (KR 증시 관례).
    const change = ov?.change_pct_1m ?? null;
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
    // 폴리곤 중앙 보조 라벨 — 부천(41194) 의 sub-area 폴리곤은 해당 sub_top 의 동명, 그 외엔 sgg 의 대표 동.
    const subTop = subKey ? ov?.bucheon_sub_top?.[subKey] : undefined;
    const subName = (subTop?.top_stdg_nm ?? ov?.top_stdg_nm) ?? null;
    polys.push({ sggCd, name, paths: rings, fillColor, changePct: change, subKey, subName });
  }
  return polys;
}

export default function MapScreen() {
  const navigate = useNavigate();
  // 모듈 캐시 hit 시 초기 state 가 즉시 채워져 첫 paint 부터 지도·색상 표시
  const [polygons, setPolygons] = useState<PolygonFeature[]>(_cachedPolygons ?? []);
  const [emdPolygons, setEmdPolygons] = useState<PolygonFeature[] | null>(_cachedEmdPolygons);
  const [zoom, setZoom] = useState<number>(0);     // 0 = 미초기화 (VWorldMap onZoomChange 가 첫 통지)
  const [overviews, setOverviews] = useState<Map<string, SggOverview>>(_cachedOverviews ?? new Map());
  const [selected, setSelected] = useState<SelectedRegion | null>(null);
  const [signal, setSignal] = useState<BuySignal | null>(null);
  const [topStdgSummary, setTopStdgSummary] = useState<RegionSummary | null>(null);
  const [loading, setLoading] = useState(false);    // FeatureCard fetch 진행 표시

  // 줌 ≥ EMD_MIN_ZOOM 첫 진입 시 행정동 폴리곤 lazy load.
  // overviews + emdLookup 둘 다 준비된 뒤에 진행 — fillColor 산출에 필요.
  useEffect(() => {
    if (zoom < EMD_MIN_ZOOM) return;
    if (emdPolygons !== null) return;
    if (overviews.size === 0) return;
    let cancelled = false;
    loadEmdLookup()
      .then((lookup) => loadEmdPolygons(overviews, lookup))
      .then((polys) => { if (!cancelled) setEmdPolygons(polys); })
      .catch((e) => console.error("[MapScreen] emd load fail", e));
    return () => { cancelled = true; };
  }, [zoom, emdPolygons, overviews]);

  // sgg 폴리곤은 항상 표시 (색상·클릭 보존). emd outline 은 줌 임계값 도달 시 overlay 로 추가.
  const overlayLayer: PolygonFeature[] | undefined =
    zoom >= EMD_MIN_ZOOM && emdPolygons ? emdPolygons : undefined;

  // EMD 폴리곤 클릭 핸들러 — 기존 sgg click 과 같은 패턴: FeatureCard modal 먼저 띄우고,
  // 사용자가 카드 탭 시 stdg detail (/stdg/{stdgCd}) 로 이동.
  // 매칭된 stdg 가 있으면 stdg 데이터로 채움, 없으면 부모 시군구 데이터로 폴백.
  function handleEmdClick(sggCd: string, name: string, stdgCd?: string) {
    if (!sggCd) return;
    // emdLookup 에서 매칭 row 가져오기 (cached module 변수 직접 참조 — 이미 로드됨)
    let emdRow: EmdRow | undefined = undefined;
    if (_cachedEmdLookup) {
      const bySgg = _cachedEmdLookup.get(sggCd);
      emdRow = bySgg?.get(normalizeStdgName(name));
    }
    const ov = overviews.get(sggCd);
    const next: SelectedRegion = {
      sggCd,
      sggNm: ov?.sgg_nm ?? sggCd,
      topStdgNm: name,                                  // 클릭한 EMD 이름
      topStdgCd: stdgCd ?? null,                        // 매칭된 stdg_cd (FeatureCard onTap 의 라우팅 키)
      medianPricePerPy: emdRow?.median_price_per_py ?? ov?.median_price_per_py ?? null,
      changePct: emdRow?.change_pct_1m ?? ov?.change_pct_1m ?? null,
    };
    setSelected(next);
    // signal + region_summary 병렬 fetch — 기존 handlePolygonClick 와 동일 흐름
    setSignal(null);
    setTopStdgSummary(null);
    setLoading(true);
    const tasks: Promise<unknown>[] = [];
    tasks.push(
      apiFetch<BuySignal | Record<string, never>>(ENDPOINTS.buySignal(sggCd))
        .then((s) => {
          if (s && typeof s === 'object' && Object.keys(s).length > 0) setSignal(s as BuySignal);
        })
        .catch(() => {})
    );
    if (stdgCd) {
      tasks.push(
        apiFetch<RegionSummary[]>(ENDPOINTS.summary(sggCd))
          .then((rows) => {
            const match = rows.find((r) => r.stdg_cd === stdgCd) ?? rows[0] ?? null;
            if (match) setTopStdgSummary(match);
          })
          .catch(() => {})
      );
    }
    Promise.all(tasks).finally(() => setLoading(false));
  }

  useEffect(() => {
    // 캐시 hit 면 fetch skip — detail 페이지에서 돌아왔을 때 즉시 표시
    if (_cachedPolygons && _cachedOverviews) return;
    let cancelled = false;
    apiFetch<SggOverview[]>(ENDPOINTS.sggOverview())
      .then(async (rows) => {
        if (cancelled) return;
        const geo = await fetchGeoJson();
        const sourceRows = rows.length > 0 ? rows : fallbackOverviewsFromGeo(geo);
        const map = new Map<string, SggOverview>();
        sourceRows.forEach((r) => map.set(r.sgg_cd, r));
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
    console.log("[MapScreen] handlePolygonClick", { sggCd, subKey, overviewsSize: overviews.size, polygonsLen: polygons.length });
    const ov = overviews.get(sggCd);
    const sggNm = polygons.find((p) => p.sggCd === sggCd && p.subKey === subKey)?.name
                  ?? polygons.find((p) => p.sggCd === sggCd)?.name
                  ?? sggCd;
    // 부천(41194) 만 — 폴리곤 sub_key (sosa/wonmi/ojeong) 와 매칭되는 sub_top 우선 사용.
    // sub 데이터 없으면 sgg 전체 top 폴백.
    const sub = subKey ? ov?.bucheon_sub_top?.[subKey] : undefined;
    const topStdgCd = sub?.top_stdg_cd ?? ov?.top_stdg_cd ?? null;
    const topStdgNm = sub?.top_stdg_nm ?? ov?.top_stdg_nm ?? sggNm;
    const medianPp = sub?.median_price_per_py ?? ov?.median_price_per_py ?? null;
    const next = {
      sggCd,
      sggNm,
      topStdgNm,
      topStdgCd,
      medianPricePerPy: medianPp,
      // FeatureCard 표시용 = 1개월 전 대비 (사용자 의도). 폴리곤 색칠은 3M 그대로.
      changePct: ov?.change_pct_1m ?? null,
    };
    console.log("[MapScreen] setSelected", next);
    setSelected(next);
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
    } else {
      setTopStdgSummary({
        sgg_cd: sggCd,
        stdg_cd: sggCd,
        stdg_nm: topStdgNm,
        stats_ym: ov?.stats_ym ?? '',
        trade_count: ov?.trade_count ?? 0,
        avg_price: null,
        median_price: null,
        median_price_per_py: ov?.median_price_per_py ?? null,
        jeonse_count: null,
        wolse_count: null,
        avg_deposit: null,
        population: null,
        solo_rate: null,
      } as RegionSummary);
    }
    Promise.all(tasks).finally(() => setLoading(false));
  }

  return (
    <div className="relative h-full w-full">
      <VWorldMap
        polygons={polygons}
        overlayPolygons={overlayLayer}
        onPolygonClick={handlePolygonClick}
        onOverlayClick={handleEmdClick}
        onZoomChange={setZoom}
        center={{ lat: 37.45, lng: 127.0 }}
        level={11}
        maxLevel={10}
      />

      {/* 플로팅 상단 — 터미널 스타일 검색 + MARKET BRIEF + CHOROPLETH 캡션 */}
      {/* outer wrapper pointer-events:none → 패널 사이 빈 공간 클릭이 지도(폴리곤)로 통과.
          inner 패널들만 pointer-events:auto 로 클릭 받음.
          z-[1000]: Leaflet 의 내장 panes (tilePane=200/overlayPane=400/markerPane=600/popupPane=700)
          위로 강제 — 기존 z-10 은 Leaflet 콘텐츠에 덮여 모바일에서 카드가 안 보였음. */}
      <div className="absolute top-2 left-2 right-2 z-[1000] space-y-1.5 pointer-events-none">
        {/* 검색 줄 — 모노 + 검정 패널 + 모노크롬 SVG */}
        <div className="bg-term-panel border border-term-border flex items-center gap-2 px-3 py-2 pointer-events-auto">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-term-dim">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            type="text"
            placeholder="지역 · 단지 · 지하철역 검색"
            className="flex-1 bg-transparent outline-none text-[11px] font-mono text-term-text placeholder-term-dim"
            onFocus={() => navigate("/search")}
            readOnly
          />
          <span className="text-[9px] text-term-dim font-mono tracking-widest">검색</span>
        </div>

        {/* MARKET BRIEF (시그널 분포 + LLM 요약) */}
        <div className="pointer-events-auto"><MarketSummaryCard /></div>

        {/* CHOROPLETH 캡션 + 색상 범례 — 한 줄. emd overlay 활성 시 동 boundary 표시 안내. */}
        <div className="flex items-center gap-2 text-[9px] font-mono tracking-widest
                        bg-term-panel border border-term-border px-2 py-1 pointer-events-auto">
          <span className="text-term-orange font-bold">시군구 색칠</span>
          <span className="text-term-dim">·</span>
          <span className="text-term-text">{polygons.length}개</span>
          <span className="text-term-dim">·</span>
          <span className="text-term-text">
            {overlayLayer ? `+ 동 ${overlayLayer.length}` : "전월 대비"}
          </span>
          <span className="ml-auto flex items-center gap-1.5">
            <Legend color="#dc2626" label="+5↑" />
            <Legend color="#f87171" label="+1" />
            <Legend color="#9ca3af" label="0" />
            <Legend color="#60a5fa" label="-1" />
            <Legend color="#2563eb" label="-5↓" />
          </span>
        </div>
      </div>

      <FeatureCard
        selected={selected}
        signal={signal}
        topStdgSummary={topStdgSummary}
        loading={loading}
        onTap={() => {
          // 매칭된 stdg 가 있으면 stdg 상세, 없으면 부모 시군구 상세로 폴백 — 거래건수
          // 데이터 없는 EMD 도 항상 detail 진입 가능하도록.
          if (selected?.topStdgCd) navigate(`/stdg/${selected.topStdgCd}`);
          else if (selected?.sggCd) navigate(`/region/${selected.sggCd}`);
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
    <span className="flex items-center gap-0.5">
      <span className="inline-block w-2 h-2" style={{ backgroundColor: color }} />
      <span className="text-term-dim">{label}</span>
    </span>
  );
}
