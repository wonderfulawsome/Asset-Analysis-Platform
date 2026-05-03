import type { BuySignal } from "../types/api";
import TerminalSection from "./TerminalSection";

interface Props {
  signal: BuySignal | null;
}

// 시그널별 라벨 + 색 (KR 관례: 매수=파랑, 주의=빨강 — 폴리곤과 다름. 신호 자체는 색이 다른 의미)
// 모킹 4 의 BUY 박스가 빨강이 아니라 별도. 매수=긍정으로 term-green 사용.
const STYLE: Record<BuySignal["signal"], { color: string; en: string; copy: string }> = {
  매수: { color: "text-term-green", en: "BUY",   copy: "거래·가격·인구·금리·이동 종합" },
  관망: { color: "text-term-dim",   en: "HOLD",  copy: "지표 혼조 · 추세 확인 필요" },
  주의: { color: "text-term-up",    en: "WATCH", copy: "거래·가격·인구·금리·이동 종합 약세" },
};

export default function SignalCard({ signal }: Props) {
  if (!signal || !signal.signal) {
    return (
      <TerminalSection title="COMPOSITE SIGNAL" right="EMPTY" dense>
        <div className="text-[11px] text-term-dim text-center">
          시그널 산출에 필요한 시계열 데이터가 부족합니다.
        </div>
      </TerminalSection>
    );
  }
  const s = STYLE[signal.signal];
  const score = signal.score;
  return (
    <TerminalSection title="COMPOSITE SIGNAL" right={`SCORE ${score >= 0 ? "+" : ""}${score.toFixed(1)}`}>
      {/* 큰 BUY/HOLD/WATCH 박스 + 카피 */}
      <div className="flex items-baseline gap-3 mb-3">
        <div className={`text-3xl font-bold font-mono ${s.color}`}>{s.en}</div>
        <div className="text-[11px] text-term-dim flex-1">{s.copy}</div>
      </div>

      {/* 부동산 3 + 거시 2 = 5 셀 breakdown */}
      <div className="grid grid-cols-5 gap-1">
        <Cell label="VOL"  score={signal.trade_score} pct={signal.feature_breakdown?.trade_chg_pct} />
        <Cell label="PRC"  score={signal.price_score} pct={signal.feature_breakdown?.price_mom_pct} />
        <Cell label="POP"  score={signal.pop_score}   pct={signal.feature_breakdown?.pop_chg_pct}   />
        <Cell label="RATE" score={signal.rate_score ?? null}
              extra={signal.feature_breakdown?.base_rate != null
                ? `${signal.feature_breakdown.base_rate.toFixed(2)}` : null} />
        <Cell label="FLOW" score={signal.flow_score ?? null}
              extra={signal.feature_breakdown?.net_flow != null
                ? `${signal.feature_breakdown.net_flow >= 0 ? "+" : ""}${signal.feature_breakdown.net_flow.toLocaleString()}` : null} />
      </div>
    </TerminalSection>
  );
}

function Cell({ label, score, pct, extra }: {
  label: string;
  score: number | null;
  pct?: number | null;
  extra?: string | null;
}) {
  const empty = score == null;
  const color = empty ? "text-term-dim"
              : score > 0 ? "text-term-up"
              : score < 0 ? "text-term-down"
              : "text-term-dim";
  return (
    <div className="bg-black/40 border border-term-border px-1 py-1 text-center">
      <div className="text-[8px] text-term-dim uppercase tracking-widest">{label}</div>
      <div className={`text-sm font-bold font-mono ${color}`}>
        {empty ? "—" : `${score > 0 ? "+" : ""}${score.toFixed(1)}`}
      </div>
      {pct != null && (
        <div className="text-[8px] text-term-dim">
          {pct >= 0 ? "+" : ""}{pct.toFixed(1)}%
        </div>
      )}
      {extra && (
        <div className="text-[8px] text-term-dim truncate">{extra}</div>
      )}
    </div>
  );
}
