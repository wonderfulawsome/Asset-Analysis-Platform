import type { BuySignal } from "../types/api";
import TerminalSection from "./TerminalSection";

// 모킹 4 의 큰 SCORE / BUY 박스 + VOL/PRC/POP/RATE/Net Migr breakdown.
// SignalCard 의 더 콤팩트 버전이라 별개 컴포넌트로 둠 (RegionDetailScreen 헤더 위치).
interface Props {
  signal: BuySignal | null;
}

const META: Record<BuySignal["signal"], { en: string; color: string; copy: string }> = {
  매수: { en: "매수", color: "text-term-green", copy: "거래 · 가격 · 인구 · 금리 · 이동 종합" },
  관망: { en: "관망", color: "text-term-dim",   copy: "지표 혼조 · 추세 확인 필요" },
  주의: { en: "주의", color: "text-term-up",    copy: "거래 · 가격 · 인구 · 금리 · 이동 종합 약세" },
};

export default function ScoreBox({ signal }: Props) {
  if (!signal || !signal.signal) return null;
  const m = META[signal.signal];
  const fb = signal.feature_breakdown ?? {};
  return (
    <TerminalSection
      title="종합 신호"
      right={`점수 ${signal.score >= 0 ? "+" : ""}${signal.score.toFixed(1)}`}
    >
      {/* 큰 BUY/HOLD/WATCH 라벨 + 카피 */}
      <div className="flex items-baseline gap-3 mb-3">
        <div className={`text-3xl font-bold font-mono leading-none ${m.color}`}>{m.en}</div>
        <div className="text-[10px] text-term-dim uppercase tracking-widest">{m.copy}</div>
      </div>

      {/* 5-cell breakdown */}
      <div className="grid grid-cols-5 gap-1">
        <Cell label="거래" pct={fb.trade_chg_pct ?? null} />
        <Cell label="가격" pct={fb.price_mom_pct ?? null} />
        <Cell label="인구" pct={fb.pop_chg_pct ?? null} />
        <Cell label="금리" pct={fb.base_rate_drop_pct ?? null} />
        <Cell label="이동" raw={fb.net_flow ?? null} />
      </div>
    </TerminalSection>
  );
}

function Cell({ label, pct, raw }: { label: string; pct?: number | null; raw?: number | null }) {
  const v = pct ?? (raw != null ? raw / 1000 : null);
  const color = v == null ? "text-term-dim"
              : v > 0 ? "text-term-up"
              : v < 0 ? "text-term-down"
              : "text-term-dim";
  let display = "—";
  if (pct != null) display = `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}`;
  else if (raw != null) display = `${raw >= 0 ? "+" : ""}${raw.toLocaleString()}`;
  return (
    <div className="bg-black/40 border border-term-border px-1 py-1 text-center">
      <div className="text-[8px] text-term-dim uppercase tracking-widest">{label}</div>
      <div className={`text-sm font-bold font-mono ${color}`}>{display}</div>
    </div>
  );
}
