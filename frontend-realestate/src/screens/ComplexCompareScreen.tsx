import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import NavBar from "../components/NavBar";
import MultiSeriesChart, { Series } from "../components/MultiSeriesChart";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import type { ComplexCompareItem } from "../types/api";

// 단지별 라인 색상 (시리즈 인덱스 기반)
const SERIES_COLORS = ["#3b82f6", "#f59e0b", "#10b981", "#a78bfa"];

// /compare?seqs=A,B&sgg=11680
//  - apt_seq 콤마구분, 시군구 코드는 단지 클릭 시 ComplexDetail 이동에 사용
export default function ComplexCompareScreen() {
  const [qs] = useSearchParams();
  const navigate = useNavigate();
  const seqsParam = qs.get("seqs") ?? "";
  const sggCd = qs.get("sgg") ?? "";
  const seqs = seqsParam.split(",").filter(Boolean).slice(0, 4);

  const [items, setItems] = useState<ComplexCompareItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (seqs.length < 2) {
      setErr("비교할 단지 2개 이상 선택 필요");
      return;
    }
    let cancelled = false;
    apiFetch<ComplexCompareItem[]>(ENDPOINTS.complexCompare(seqs, 12))
      .then((d) => !cancelled && setItems(d))
      .catch((e) => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seqsParam]);

  if (err) return <div className="p-6 text-red-400 text-sm">{err}</div>;
  if (!items) return <div className="p-10 text-center text-term-dim text-sm">로딩 중…</div>;

  // 시리즈 변환 — 각 metric 마다 모든 단지의 라인을 합쳐 하나의 차트
  const priceSeries: Series[] = items.map((it, i) => ({
    label: it.apt_nm ?? it.apt_seq,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    data: it.timeseries.map((p) => ({ date: p.ym, value: p.median_price_per_py })),
  }));
  const tradeSeries: Series[] = items.map((it, i) => ({
    label: it.apt_nm ?? it.apt_seq,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    data: it.timeseries.map((p) => ({ date: p.ym, value: p.trade_count || null })),
  }));
  const jeonseSeries: Series[] = items.map((it, i) => ({
    label: it.apt_nm ?? it.apt_seq,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    data: it.timeseries.map((p) => ({ date: p.ym, value: p.jeonse_rate })),
  }));

  return (
    <div className="min-h-full bg-term-panel">
      <NavBar title="단지 비교" subtitle={`${items.length}개 단지 · 12M`} />

      <section className="p-3 space-y-3">
        {/* 상단 단지 카드 — 클릭 시 단지 상세로 */}
        <div className="grid grid-cols-2 gap-2">
          {items.map((it, i) => (
            <button
              key={it.apt_seq}
              onClick={() =>
                navigate(`/complex/${it.apt_seq}?sgg_cd=${sggCd || it.sgg_cd || ""}`)
              }
              className="bg-term-panel border border-term-border active:border-term-orange p-3 text-left"
            >
              <div className="flex items-center gap-1 mb-1">
                <span
                  className="inline-block w-2.5 h-2.5 rounded"
                  style={{ backgroundColor: SERIES_COLORS[i % SERIES_COLORS.length] }}
                />
                <span className="text-[10px] text-term-dim">{it.umd_nm ?? ""}</span>
              </div>
              <div className="font-semibold text-sm truncate">{it.apt_nm ?? it.apt_seq}</div>
              <div className="text-[10px] text-term-dim">
                {it.build_year ? `${it.build_year}년` : ""}
              </div>
            </button>
          ))}
        </div>

        {/* 3종 overlay 차트 */}
        <MultiSeriesChart
          title="평단가 추이 (만원/평)"
          series={priceSeries}
          format={(n) => Math.round(n).toLocaleString()}
        />
        <MultiSeriesChart
          title="월별 거래량 (건)"
          series={tradeSeries}
          format={(n) => n.toLocaleString()}
        />
        <MultiSeriesChart
          title="전세가율 (%)"
          series={jeonseSeries}
          format={(n) => `${(n * 100).toFixed(1)}%`}
        />
      </section>
    </div>
  );
}
