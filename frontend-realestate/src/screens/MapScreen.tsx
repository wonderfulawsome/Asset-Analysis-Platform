import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import KakaoMap, { PolygonFeature } from "../components/KakaoMap";
import BottomBar from "../components/BottomBar";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import { changePctColor } from "../lib/color";
import type { SggOverview } from "../types/api";

// GeoJSON name → 우리 sgg_cd 5자리 매핑. southkorea-maps 의 code(11010 등)는
// 우리 행안부 코드(11110 등)와 다른 체계라 name 으로 매칭한다.
const SGG_NAME_TO_CD: Record<string, string> = {
  종로구: "11110", 중구: "11140", 용산구: "11170", 성동구: "11200", 광진구: "11215",
  동대문구: "11230", 중랑구: "11260", 성북구: "11290", 강북구: "11305", 도봉구: "11320",
  노원구: "11350", 은평구: "11380", 서대문구: "11410", 마포구: "11440", 양천구: "11470",
  강서구: "11500", 구로구: "11530", 금천구: "11545", 영등포구: "11560", 동작구: "11590",
  관악구: "11620", 서초구: "11650", 강남구: "11680", 송파구: "11710", 강동구: "11740",
};

interface SelectedRegion {
  sggCd: string;
  sggNm: string;
  topStdgNm: string | null;
  topStdgCd: string | null;
  medianPricePerPy: number | null;
  changePct: number | null;
}

// GeoJSON FeatureCollection → KakaoMap 의 PolygonFeature[] 로 변환.
async function loadPolygons(overviews: Map<string, SggOverview>): Promise<PolygonFeature[]> {
  const res = await fetch("/static/realestate/geojson/seoul-sgg.geojson");
  const geo = await res.json();
  const polys: PolygonFeature[] = [];
  for (const feat of geo.features ?? []) {
    const name = feat.properties?.name as string | undefined;
    if (!name) continue;
    const sggCd = SGG_NAME_TO_CD[name];
    if (!sggCd) continue;
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
    polys.push({ sggCd, name, paths: rings, fillColor, changePct: change });
  }
  return polys;
}

export default function MapScreen() {
  const navigate = useNavigate();
  const [polygons, setPolygons] = useState<PolygonFeature[]>([]);
  const [overviews, setOverviews] = useState<Map<string, SggOverview>>(new Map());
  const [selected, setSelected] = useState<SelectedRegion | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<SggOverview[]>(ENDPOINTS.sggOverview())
      .then(async (rows) => {
        if (cancelled) return;
        const map = new Map<string, SggOverview>();
        rows.forEach((r) => map.set(r.sgg_cd, r));
        setOverviews(map);
        const polys = await loadPolygons(map);
        if (!cancelled) setPolygons(polys);
      })
      .catch((e) => console.error("[MapScreen] load fail", e));
    return () => { cancelled = true; };
  }, []);

  function handlePolygonClick(sggCd: string) {
    const ov = overviews.get(sggCd);
    // GeoJSON name → SGG_NAME_TO_CD 매핑의 역 — name 찾기
    const sggNm = Object.entries(SGG_NAME_TO_CD).find(([, c]) => c === sggCd)?.[0] ?? sggCd;
    setSelected({
      sggCd,
      sggNm,
      topStdgNm: ov?.top_stdg_nm ?? null,
      topStdgCd: ov?.top_stdg_cd ?? null,
      medianPricePerPy: ov?.median_price_per_py ?? null,
      changePct: ov?.change_pct_3m ?? null,
    });
  }

  return (
    <div className="relative h-full w-full">
      <KakaoMap polygons={polygons} onPolygonClick={handlePolygonClick} />

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

      <BottomBar
        selected={selected}
        onTap={(stdg) => navigate(`/stdg/${stdg}`)}
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
