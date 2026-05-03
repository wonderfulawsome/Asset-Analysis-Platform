import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import RegionCodeHeader from "../components/RegionCodeHeader";
import TerminalSection from "../components/TerminalSection";
import TerminalMetric from "../components/TerminalMetric";
import TimeSeriesChart from "../components/TimeSeriesChart";
import MiniChart from "../components/MiniChart";
import ScoreBox from "../components/ScoreBox";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import type { RegionSummary, TimeseriesPoint, BuySignal } from "../types/api";

// 시군구 대시보드 — 모킹 2 매칭. RGN 헤더 + sub-region 그리드 + 큰 detail 카드 (narrative + TXNS/MoM Δ/SIG)
// + SignalCard + 시계열 차트 4종.
export default function RegionDetailScreen() {
  const { sggCd } = useParams<{ sggCd: string }>();
  const navigate = useNavigate();
  const [rows, setRows] = useState<RegionSummary[] | null>(null);
  const [ts, setTs] = useState<TimeseriesPoint[] | null>(null);
  const [signal, setSignal] = useState<BuySignal | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!sggCd) return;
    let cancelled = false;
    apiFetch<{ summary: RegionSummary[]; timeseries: TimeseriesPoint[]; signal: BuySignal | null }>(
      ENDPOINTS.regionDetail(sggCd)
    )
      .then((d) => {
        if (cancelled) return;
        setRows(d.summary || []);
        setTs(d.timeseries || []);
        setSignal(d.signal && (d.signal as BuySignal).signal ? d.signal : null);
      })
      .catch((e) => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
  }, [sggCd]);

  const latest = ts?.[ts.length - 1];
  const top = rows && rows.length > 0
    ? [...rows].sort((a, b) => (b.median_price_per_py ?? 0) - (a.median_price_per_py ?? 0))[0]
    : null;

  // narrative — 가장 비싼 stdg 의 변화 + signal 종합
  const narrative = buildNarrative(top, latest, signal);

  return (
    <div className="bg-term-bg min-h-full font-mono">
      <RegionCodeHeader
        code={sggCd ?? "—"}
        parts={[top?.stdg_nm ?? null]}
        right="상세 요약"
      />

      {err && <div className="p-3 text-term-up text-[11px]">{err}</div>}
      {!rows && !err && (
        <div className="p-10 text-center text-term-dim text-[11px]">· 데이터 불러오는 중…</div>
      )}

      {/* 매수 시그널 카드 — 모킹 4 의 큰 SCORE / BUY 박스 + breakdown */}
      {signal && <div className="p-2"><ScoreBox signal={signal} /></div>}

      {/* 메인 detail 카드 — 모킹 2 의 큰 박스 (narrative + TXNS / MoM Δ / SIG) */}
      {top && latest && (
        <div className="px-2 pb-2">
          <TerminalSection
            title={`법정동 ${top.stdg_cd} · ${top.stdg_nm ?? ""}`}
            right="요약"
          >
            <p className="text-[12px] text-term-text leading-relaxed mb-3">
              {narrative}
            </p>
            <div className="grid grid-cols-3 gap-2">
              <TerminalMetric label="거래량" value={(top.trade_count ?? 0).toLocaleString()} unit="건" />
              <TerminalMetric
                label="전월 대비"
                value={signal?.feature_breakdown?.price_mom_pct != null
                  ? `${signal.feature_breakdown.price_mom_pct >= 0 ? "+" : ""}${signal.feature_breakdown.price_mom_pct.toFixed(1)}%`
                  : "—"}
                valueClass={
                  signal?.feature_breakdown?.price_mom_pct == null ? "text-term-dim"
                  : signal.feature_breakdown.price_mom_pct >= 0 ? "text-term-up"
                  : "text-term-down"
                }
              />
              <TerminalMetric
                label="신호"
                value={signal?.signal ?? "—"}
                valueClass={
                  signal?.signal === "매수" ? "text-term-green"
                  : signal?.signal === "주의" ? "text-term-up"
                  : "text-term-dim"
                }
              />
            </div>
          </TerminalSection>
        </div>
      )}

      {/* 상단 요약 카드 4개 — 시계열 마지막 월 */}
      {latest && (
        <section className="px-2 pb-2">
          <div className="grid grid-cols-2 gap-2">
            <TerminalMetric label="평균 평단가" value={fmtMan(latest.median_price_per_py)} />
            <TerminalMetric label="월 거래량" value={`${latest.trade_count.toLocaleString()}`} unit="건" />
            <TerminalMetric label="전세 / 월세" value={`${latest.jeonse_count}/${latest.wolse_count}`} />
            <TerminalMetric label="전세가율" value={fmtPct(latest.jeonse_rate)} valueClass="text-term-amber" />
          </div>
        </section>
      )}

      {/* MiniChart strip — 평단가/거래량/전세가율 3종 row */}
      {latest && ts && ts.length >= 2 && (
        <section className="px-2 pb-2 grid grid-cols-3 gap-1">
          <MiniSlot label="평단가 만원/평" data={ts.map((p) => ({ date: p.ym, value: p.median_price_per_py }))}
            color="#ff8800" last={ts[ts.length - 1].median_price_per_py} fmt={(n) => Math.round(n).toLocaleString()} />
          <MiniSlot label="월 거래량" data={ts.map((p) => ({ date: p.ym, value: p.trade_count }))}
            color="#00cc66" last={ts[ts.length - 1].trade_count} fmt={(n) => n.toLocaleString()} />
          <MiniSlot label="전세가율" data={ts.map((p) => ({ date: p.ym, value: p.jeonse_rate }))}
            color="#ffaa00" last={ts[ts.length - 1].jeonse_rate} fmt={(n) => `${(n * 100).toFixed(1)}%`} />
        </section>
      )}

      {/* 인구 — 큰 차트 별도 (위 3종은 MiniChart 로 압축) */}
      {latest && (
        <section className="px-2 pb-3">
          <TimeSeriesChart
            label="인구 추이"
            data={ts!.map((p) => ({ date: p.ym, value: p.population }))}
            format={(n) => n.toLocaleString()}
            color="#4488ff"
          />
        </section>
      )}

      {rows && rows.length === 0 && !latest && (
        <div className="p-10 text-center text-term-dim text-[11px]">
          · 이번 달 집계된 데이터가 없습니다.
        </div>
      )}

      {/* sub-region 리스트 — 법정동 순위 */}
      {rows && rows.length > 0 && (
        <section className="px-2 pb-4">
          <TerminalSection title="법정동 · 평단가 순위" dense>
            <ul className="divide-y divide-term-border">
              {rows.map((r, i) => (
                <li
                  key={r.stdg_cd}
                  onClick={() => navigate(`/stdg/${r.stdg_cd}`)}
                  className="flex items-center gap-2 py-1.5 px-1 cursor-pointer hover:bg-black/40 active:bg-black/60 text-[11px]"
                >
                  <span className="w-5 text-term-dim font-bold text-right">{i + 1}</span>
                  <span className="flex-1 text-term-text truncate font-bold">{r.stdg_nm ?? r.stdg_cd}</span>
                  <span className="text-term-dim text-[10px] mr-2">
                    거래 {r.trade_count ?? 0}
                  </span>
                  <span className="font-bold text-term-text">
                    {fmtMan(r.median_price_per_py)}
                  </span>
                </li>
              ))}
            </ul>
          </TerminalSection>
        </section>
      )}
    </div>
  );
}

// 시군구 detail narrative — "매매가 +8.1% 전월 대비 반등. 거래량 12개월 평균 이상. 신호: 매수."
function buildNarrative(top: RegionSummary | null, latest: TimeseriesPoint | undefined,
                        signal: BuySignal | null): string {
  if (!top) return "데이터 수집 중";
  const parts: string[] = [];
  const fb = signal?.feature_breakdown;
  if (fb?.price_mom_pct != null) {
    const dir = fb.price_mom_pct >= 0 ? "반등" : "하락";
    parts.push(`매매가 ${fb.price_mom_pct >= 0 ? "+" : ""}${fb.price_mom_pct.toFixed(1)}% 전월 대비 ${dir}`);
  }
  if (fb?.trade_vs_long_ratio != null) {
    const r = fb.trade_vs_long_ratio;
    parts.push(r >= 1.15 ? "거래량 12개월 평균 이상" : r <= 0.85 ? "거래량 12개월 평균 이하" : "거래량 12개월 평균 수준");
  }
  if (signal?.signal) {
    parts.push(`신호: ${signal.signal}`);
  } else if (latest?.trade_count) {
    parts.push(`최근 ${latest.trade_count}건 체결`);
  }
  return parts.join(". ") + (parts.length ? "." : "");
}

function fmtMan(n: number | null | undefined): string {
  return n == null ? "—" : `${Math.round(n).toLocaleString()}만`;
}
function fmtPct(n: number | null | undefined): string {
  return n == null ? "—" : `${(n * 100).toFixed(1)}%`;
}

// MiniChart + 라벨 + LAST 한 줄 조합 — 3-column strip row 안의 한 칸.
function MiniSlot({ label, data, color, last, fmt }: {
  label: string;
  data: { date: string; value: number | null }[];
  color: string;
  last: number | null;
  fmt: (n: number) => string;
}) {
  return (
    <div className="bg-term-panel border border-term-border p-1.5 font-mono">
      <div className="text-[8px] uppercase tracking-widest text-term-orange font-bold truncate">
        ▓ {label}
      </div>
      <MiniChart data={data} color={color} height={28} />
      <div className="text-[9px] text-term-text font-bold text-right">
        {last != null ? fmt(last) : "—"}
      </div>
    </div>
  );
}
