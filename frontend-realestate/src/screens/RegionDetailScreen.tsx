import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import NavBar from "../components/NavBar";
import TimeSeriesChart from "../components/TimeSeriesChart";
import SignalCard from "../components/SignalCard";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import type { RegionSummary, TimeseriesPoint, BuySignal } from "../types/api";

// 시군구 대시보드 — 헤더 요약 + 시계열 차트 + 법정동 리스트.
export default function RegionDetailScreen() {
  const { sggCd } = useParams<{ sggCd: string }>();
  const [rows, setRows] = useState<RegionSummary[] | null>(null);
  const [ts, setTs] = useState<TimeseriesPoint[] | null>(null);
  const [signal, setSignal] = useState<BuySignal | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!sggCd) return;
    let cancelled = false;
    // 최근월 법정동 + 시계열 + 매수 시그널 3개 병렬 조회
    Promise.all([
      apiFetch<RegionSummary[]>(ENDPOINTS.summary(sggCd)),
      apiFetch<TimeseriesPoint[]>(ENDPOINTS.timeseries(sggCd)),
      apiFetch<BuySignal | {}>(ENDPOINTS.buySignal(sggCd)).catch(() => ({})),
    ])
      .then(([s, t, sg]) => {
        if (cancelled) return;
        setRows(s);
        setTs(t);
        // 빈 객체({})면 시그널 없음 → null 처리
        setSignal((sg as BuySignal).signal ? (sg as BuySignal) : null);
      })
      .catch((e) => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
  }, [sggCd]);

  // 가장 최근월(시계열 마지막) 값 → 헤더 메트릭에 사용
  const latest = ts?.[ts.length - 1];

  return (
    <div className="min-h-full bg-gray-900">
      <NavBar
        title={sggCd ? `시군구 ${sggCd}` : "지역"}
        subtitle={rows ? `${rows.length}개 법정동` : undefined}
      />

      {err && <div className="p-4 text-red-400 text-sm">{err}</div>}
      {!rows && !err && (
        <div className="p-10 text-center text-gray-500 text-sm">로딩 중…</div>
      )}

      {latest && (
        <section className="p-3 space-y-3">
          {/* 매수 타이밍 시그널 카드 — 메트릭 위에 배치 */}
          <SignalCard signal={signal} />

          {/* 상단 요약 카드 4개 */}
          <div className="grid grid-cols-2 gap-2">
            <Metric label="평균 평단가" value={fmtMan(latest.median_price_per_py)} />
            <Metric label="거래량(월)" value={`${latest.trade_count.toLocaleString()}건`} />
            <Metric label="전세 / 월세" value={`${latest.jeonse_count} / ${latest.wolse_count}`} />
            <Metric label="전세가율" value={fmtPct(latest.jeonse_rate)} accent />
          </div>

          {/* 시계열 차트 4종 */}
          <div className="space-y-2">
            <TimeSeriesChart
              label="평단가 추이 (만원/평)"
              data={ts!.map((p) => ({ date: p.ym, value: p.median_price_per_py }))}
              format={(n) => `${Math.round(n).toLocaleString()}`}
              color="#3b82f6"
            />
            <TimeSeriesChart
              label="월별 거래량 (건)"
              data={ts!.map((p) => ({ date: p.ym, value: p.trade_count }))}
              format={(n) => n.toLocaleString()}
              color="#10b981"
            />
            <TimeSeriesChart
              label="전세가율 (%)"
              data={ts!.map((p) => ({ date: p.ym, value: p.jeonse_rate }))}
              format={(n) => `${(n * 100).toFixed(1)}%`}
              color="#f59e0b"
            />
            <TimeSeriesChart
              label="인구 (명)"
              data={ts!.map((p) => ({ date: p.ym, value: p.population }))}
              format={(n) => n.toLocaleString()}
              color="#a78bfa"
            />
          </div>
        </section>
      )}

      {rows && rows.length === 0 && !latest && (
        <div className="p-10 text-center text-gray-500 text-sm">
          이번 달 집계된 데이터가 없습니다.
        </div>
      )}

      {/* 법정동 리스트 */}
      {rows && rows.length > 0 && (
        <section className="px-3 pb-4">
          <h2 className="text-xs text-gray-400 px-1 my-2">법정동 순위 (평단가)</h2>
          <ul className="space-y-2">
            {rows.map((r, i) => (
              <li
                key={r.stdg_cd}
                className="rounded-2xl bg-gray-800/80 active:bg-gray-700
                           p-4 flex items-center gap-3 transition"
              >
                <div className="w-8 h-8 rounded-full bg-gray-700 flex items-center
                               justify-center text-xs font-bold text-gray-300">
                  {i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold truncate">{r.stdg_nm ?? r.stdg_cd}</div>
                  <div className="text-[11px] text-gray-400 mt-0.5">
                    거래 {r.trade_count ?? 0}건 · 인구 {fmt(r.population)} ·
                    1인가구 {fmtPct(r.solo_rate)}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[10px] text-gray-500">평단가</div>
                  <div className="font-mono text-base font-semibold">
                    {fmtMan(r.median_price_per_py)}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Metric({
  label, value, accent = false,
}: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`rounded-xl p-3 ${accent ? "bg-blue-500/15 border border-blue-500/30" : "bg-gray-800/80"}`}>
      <div className="text-[10px] text-gray-400">{label}</div>
      <div className="font-mono text-base font-semibold mt-0.5">{value}</div>
    </div>
  );
}

function fmt(n: number | null | undefined): string {
  return n == null ? "-" : n.toLocaleString();
}
function fmtMan(n: number | null | undefined): string {
  return n == null ? "-" : `${Math.round(n).toLocaleString()}만`;
}
function fmtPct(n: number | null | undefined): string {
  return n == null ? "-" : `${(n * 100).toFixed(1)}%`;
}
