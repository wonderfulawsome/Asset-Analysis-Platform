import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import type { Trade } from "../types/api";

// HOMELENS · DOSSIER 신문 스타일 — 거래 타임라인이 메인.
export default function ComplexDetailScreen() {
  const { aptSeq } = useParams<{ aptSeq: string }>();
  const navigate = useNavigate();
  const [qs] = useSearchParams();
  const sggCd = qs.get("sgg_cd") ?? "";
  const [allTrades, setAllTrades] = useState<Trade[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!sggCd) {
      setErr("sgg_cd 쿼리 누락");
      return;
    }
    let cancelled = false;
    apiFetch<Trade[]>(ENDPOINTS.trades(sggCd))
      .then((d) => !cancelled && setAllTrades(d))
      .catch((e) => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
  }, [sggCd]);

  const trades = useMemo(
    () => (allTrades ?? [])
      .filter((t) => t.apt_seq === aptSeq)
      .sort((a, b) => (b.deal_date ?? "").localeCompare(a.deal_date ?? "")),  // 최신순
    [allTrades, aptSeq],
  );
  const first = trades[0];

  const aptNm = first?.apt_nm ?? aptSeq ?? "단지";
  const umdNm = first?.umd_nm ?? "";
  const buildYear = first?.build_year;
  const issueNo = aptSeq ? `P.${aptSeq.slice(-3)}` : "P.000";

  // 첫/마지막 거래 날짜 + 건수
  const dateRange = trades.length > 0
    ? `${formatDealDate(trades[trades.length - 1].deal_date)} ~ ${formatDealDate(trades[0].deal_date)}`
    : null;
  const monthLabel = trades.length > 0
    ? `${parseInt(trades[0].deal_date.slice(5, 7), 10)}월`
    : "최근";

  return (
    <div className="min-h-full bg-term-bg text-term-text font-mono pb-24">
      {/* 헤더 */}
      <header className="px-5 pt-3 border-b border-term-border">
        <div className="flex items-center justify-between">
          <button onClick={() => navigate(-1)} className="text-term-dim text-base">‹</button>
          <div className="text-[10px] tracking-[0.3em] text-term-dim font-bold">
            {issueNo} · 거래 타임
          </div>
          <div className="text-term-text">♡</div>
        </div>
        <div className="h-2" />
      </header>

      {/* 타이틀 영역 */}
      <section className="px-5 mt-6">
        <div className="text-[10px] tracking-[0.25em] text-term-orange font-bold mb-2">
          DOSSIER{buildYear ? ` · 골목 · ${buildYear}` : ""}
        </div>
        <h1 className="text-[28px] leading-[1.2] font-bold tracking-tight text-term-text">
          {aptNm}
        </h1>
        {umdNm && (
          <p className="text-[14px] italic text-term-dim mt-2">
            {umdNm}
          </p>
        )}
      </section>

      {err && <div className="px-5 mt-6 text-red-400 text-sm">{err}</div>}
      {!allTrades && !err && (
        <div className="px-5 mt-10 text-center text-term-dim text-sm">로딩 중…</div>
      )}

      {allTrades && trades.length === 0 && (
        <div className="px-5 mt-10 text-center text-term-dim text-sm">
          이번 달 해당 단지 거래가 없습니다.
        </div>
      )}

      {/* 거래 메타 */}
      {trades.length > 0 && (
        <>
          <div className="px-5 mt-5 flex items-center justify-between text-[11px] text-term-dim">
            <span>
              {monthLabel}의 거래 <span className="text-term-text font-semibold">{trades.length}건</span>
            </span>
            <span className="font-mono">{dateRange}</span>
          </div>

          {/* 타임라인 */}
          <section className="px-5 mt-6 relative">
            {/* 세로 라인 (왼쪽) */}
            <div className="absolute left-[26px] top-2 bottom-2 w-px bg-term-panel" />

            <ul className="space-y-1">
              {trades.map((t, i) => (
                <li
                  key={i}
                  className="relative pl-12 py-3 border-b border-term-border flex justify-between items-center"
                >
                  {/* 점 (왼쪽) */}
                  <span
                    className="absolute left-[20px] top-[22px] w-3 h-3 rounded-full border-2"
                    style={{ borderColor: "#fca5a5", backgroundColor: "transparent" }}
                  />
                  {/* 날짜 + 면적/층 */}
                  <div>
                    <div className="text-[13px] text-term-text font-mono">
                      {formatDealDate(t.deal_date)}
                    </div>
                    <div className="text-[11px] text-term-dim mt-0.5">
                      전용 {t.exclu_use_ar.toFixed(1)}㎡ · {t.floor ?? "-"}층
                    </div>
                  </div>
                  {/* 가격 (억 단위) */}
                  <div className="text-right">
                    <span className="text-[20px] font-bold text-term-text tracking-tight">
                      {(t.deal_amount / 10000).toFixed(2)}
                    </span>
                    <span className="text-[11px] text-term-dim ml-0.5">억</span>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      <p className="text-[10px] text-term-dim text-center mt-10 italic">
        ⚠️ 본 분석은 참고용이며 투자 권유가 아닙니다.
      </p>
    </div>
  );
}

function formatDealDate(d: string): string {
  // "2026-03-30" → "26.03.30"
  if (!d || d.length < 10) return d ?? "";
  return `${d.slice(2, 4)}.${d.slice(5, 7)}.${d.slice(8, 10)}`;
}
