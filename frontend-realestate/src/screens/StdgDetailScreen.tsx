import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import NavBar from "../components/NavBar";
import AiInsightCard from "../components/AiInsightCard";
import TimeSeriesChart from "../components/TimeSeriesChart";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import { changePctColor, formatPriceMan } from "../lib/color";
import type { StdgDetail } from "../types/api";

// 첨부 이미지 디자인 매칭:
//  헤더(시군구 + 법정동) → AI 카드 → 메트릭 4칸 → 12M 차트 → 단지 리스트.
export default function StdgDetailScreen() {
  const { stdgCd } = useParams<{ stdgCd: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<StdgDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // 비교 모드: true면 단지 카드에 체크박스 노출. 선택된 apt_seq Set.
  const [compareMode, setCompareMode] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  function togglePick(seq: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else if (next.size < 4) next.add(seq);  // 최대 4개
      return next;
    });
  }

  function startCompare() {
    if (picked.size < 2) return;
    const seqs = Array.from(picked).join(",");
    const sgg = data?.summary?.sgg_cd ?? stdgCd?.slice(0, 5) ?? "";
    navigate(`/compare?seqs=${seqs}&sgg=${sgg}`);
  }

  useEffect(() => {
    if (!stdgCd) return;
    let cancelled = false;
    apiFetch<StdgDetail>(ENDPOINTS.stdgDetail(stdgCd))
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
  }, [stdgCd]);

  if (err) return <div className="p-6 text-red-400 text-sm">{err}</div>;
  if (!data) return <div className="p-10 text-center text-gray-500 text-sm">로딩 중…</div>;

  const s = data.summary;
  if (!s) {
    return (
      <div className="min-h-full bg-gray-900">
        <NavBar title={`법정동 ${stdgCd}`} />
        <div className="p-10 text-center text-gray-500 text-sm">
          이번 달 집계된 데이터가 없습니다.
        </div>
      </div>
    );
  }

  // 헤더 배지: 변화율 + 시그널 조합
  const badge = signalBadge(data.signal?.signal, s.change_pct_3m);

  return (
    <div className="min-h-full bg-gray-900">
      <NavBar
        title={s.stdg_nm ?? stdgCd ?? ""}
        subtitle={`${s.stats_ym?.slice(0, 4)}.${s.stats_ym?.slice(4)} 업데이트`}
      />

      <section className="p-3 space-y-3">
        {/* 헤더 라인 — 큰 동명 + 배지 */}
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold tracking-tight">
            <span className="text-gray-400 text-base mr-1">
              {/* sgg_nm 은 region_summary 에 없어서 표시 생략 */}
            </span>
            {s.stdg_nm}
          </h1>
          <span
            className="text-xs font-semibold px-3 py-1 rounded-full"
            style={{ backgroundColor: badge.bg, color: badge.fg }}
          >
            {badge.label}
          </span>
        </div>

        {/* AI 카드 */}
        <AiInsightCard signal={data.signal} changePct={s.change_pct_3m} />

        {/* 메트릭 4칸 (2x2) */}
        <div className="grid grid-cols-2 gap-2">
          <Metric
            label="평균 매매가"
            value={formatPriceMan(s.median_price_per_py)}
            sub={s.change_pct_3m != null ? `3M ${pct(s.change_pct_3m)}` : undefined}
            subColor={s.change_pct_3m}
          />
          <Metric
            label="거래량 3M"
            value={`${(s.trade_count_3m ?? 0).toLocaleString()}건`}
          />
          <Metric
            label="전세가율"
            value={s.jeonse_rate != null ? `${(s.jeonse_rate * 100).toFixed(1)}%` : "-"}
          />
          <Metric
            label="순이동(시군구)"
            value={s.net_flow != null ? `${s.net_flow >= 0 ? "+" : ""}${s.net_flow.toLocaleString()}명` : "-"}
          />
        </div>

        {/* 12M 매매가 추이 */}
        <TimeSeriesChart
          label="매매가 추이 12M"
          data={data.timeseries.map((p) => ({
            date: p.stats_ym,
            value: p.median_price_per_py,
          }))}
          format={(n) => `${Math.round(n).toLocaleString()}만`}
          color="#3b82f6"
        />

        {/* 단지 리스트 */}
        <div>
          <div className="flex items-baseline justify-between px-1 my-2">
            <h2 className="text-xs text-gray-400">동 내 주요 단지 (평단가 순)</h2>
            <button
              onClick={() => { setCompareMode((v) => !v); setPicked(new Set()); }}
              className={`text-[11px] font-semibold px-2 py-1 rounded-md transition
                          ${compareMode ? "bg-blue-500 text-white" : "bg-gray-700 text-gray-300"}`}
            >
              {compareMode ? "비교 취소" : "비교"}
            </button>
          </div>
          {data.complexes.length === 0 ? (
            <div className="rounded-xl bg-gray-800/40 p-6 text-center text-xs text-gray-500">
              최근 거래된 단지가 없습니다.
            </div>
          ) : (
            <ul className="space-y-2">
              {data.complexes.map((c) => {
                const isPicked = picked.has(c.apt_seq);
                return (
                  <li
                    key={c.apt_seq}
                    onClick={() => {
                      if (compareMode) togglePick(c.apt_seq);
                      else navigate(`/complex/${c.apt_seq}?sgg_cd=${(s.sgg_cd ?? stdgCd?.slice(0, 5)) ?? ""}`);
                    }}
                    className={`rounded-xl p-4 flex justify-between items-center transition cursor-pointer
                                ${compareMode && isPicked
                                  ? "bg-blue-500/20 ring-2 ring-blue-500"
                                  : "bg-gray-800/80 active:bg-gray-700"}`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      {compareMode && (
                        <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold
                                           ${isPicked ? "bg-blue-500 text-white" : "border border-gray-600 text-gray-500"}`}>
                          {isPicked ? "✓" : ""}
                        </span>
                      )}
                      <div className="min-w-0">
                        <div className="font-semibold truncate">{c.apt_nm ?? c.apt_seq}</div>
                        <div className="text-[11px] text-gray-400">
                          {c.build_year ? `${c.build_year}년 · ` : ""}거래 {c.trade_count}건
                        </div>
                      </div>
                    </div>
                    <div className="font-mono text-base font-semibold ml-2 shrink-0">
                      {Math.round(c.median_price_per_py).toLocaleString()}만/평
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* 비교 시작 플로팅 버튼 — 비교 모드 + 2개 이상 선택 시 노출 */}
        {compareMode && picked.size >= 2 && (
          <button
            onClick={startCompare}
            className="fixed bottom-[calc(80px+env(safe-area-inset-bottom))] left-1/2 -translate-x-1/2
                       z-30 px-6 py-3 rounded-full bg-blue-500 text-white font-semibold shadow-2xl
                       active:bg-blue-600"
          >
            {picked.size}개 단지 비교 →
          </button>
        )}
      </section>
    </div>
  );
}

function Metric({
  label, value, sub, subColor,
}: { label: string; value: string; sub?: string; subColor?: number | null }) {
  return (
    <div className="rounded-xl bg-gray-800/80 p-3">
      <div className="text-[10px] text-gray-400">{label}</div>
      <div className="font-mono text-base font-semibold mt-0.5">{value}</div>
      {sub && (
        <div
          className="text-[10px] mt-0.5"
          style={{ color: subColor != null ? changePctColor(subColor) : "#6b7280" }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

function signalBadge(
  signal: "매수" | "관망" | "주의" | undefined,
  changePct: number | null,
): { label: string; bg: string; fg: string } {
  if (signal === "매수" || (changePct != null && changePct >= 1)) {
    return { label: "↑ 상승", bg: "#dc262633", fg: "#fca5a5" };
  }
  if (signal === "주의" || (changePct != null && changePct <= -1)) {
    return { label: "↓ 하락", bg: "#2563eb33", fg: "#93c5fd" };
  }
  return { label: "→ 보합", bg: "#6b728033", fg: "#d1d5db" };
}

function pct(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
}
