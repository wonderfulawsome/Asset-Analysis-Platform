import type { BuySignal } from "../types/api";

interface Props {
  signal: BuySignal | null;
}

const STYLE: Record<BuySignal["signal"], { bg: string; ring: string; icon: string; copy: string }> = {
  매수: { bg: "bg-blue-500/15",  ring: "ring-blue-500/40",  icon: "↑", copy: "거래·가격·인구·금리·이동 종합 상승 신호" },
  관망: { bg: "bg-gray-500/15",  ring: "ring-gray-500/40",  icon: "→", copy: "지표 혼조 — 추세 확인 필요" },
  주의: { bg: "bg-red-500/15",   ring: "ring-red-500/40",   icon: "↓", copy: "거래·가격·인구·금리·이동 종합 약세" },
};

// 시그널 결과를 헤더 + 5개 점수 breakdown 으로 시각화.
// rate/flow 는 Step B/C 에서 들어오므로 null 일 수 있음 — 그 때만 카드 숨김.
export default function SignalCard({ signal }: Props) {
  if (!signal || !signal.signal) {
    return (
      <div className="rounded-2xl bg-gray-800/60 p-4 text-center text-xs text-gray-500">
        시그널 산출에 필요한 시계열 데이터가 부족합니다.
      </div>
    );
  }

  const s = STYLE[signal.signal];
  return (
    <div className={`rounded-2xl p-4 ring-1 ${s.bg} ${s.ring}`}>
      <div className="flex items-center gap-3">
        <div className="text-3xl leading-none">{s.icon}</div>
        <div className="flex-1">
          <div className="flex items-baseline gap-2">
            <span className="text-xl font-bold">{signal.signal}</span>
            <span className="text-xs text-gray-400">
              종합점수 {signal.score >= 0 ? "+" : ""}
              {signal.score}
            </span>
          </div>
          <div className="text-[11px] text-gray-400">{s.copy}</div>
        </div>
      </div>

      {/* 부동산 3지표 */}
      <div className="grid grid-cols-3 gap-2 mt-3">
        <SubMetric label="거래량" score={signal.trade_score}
          pct={signal.feature_breakdown?.trade_chg_pct} suffix="%" />
        <SubMetric label="가격" score={signal.price_score}
          pct={signal.feature_breakdown?.price_mom_pct} suffix="%" />
        <SubMetric label="인구" score={signal.pop_score}
          pct={signal.feature_breakdown?.pop_chg_pct} suffix="%" />
      </div>

      {/* 거시 2지표 — Step B/C — null 시 카드 숨김 */}
      {(signal.rate_score != null || signal.flow_score != null) && (
        <div className="grid grid-cols-2 gap-2 mt-2">
          {signal.rate_score != null && (
            <SubMetric label="금리" score={signal.rate_score}
              extra={signal.feature_breakdown?.base_rate != null
                ? `기준 ${signal.feature_breakdown.base_rate}%`
                : undefined} />
          )}
          {signal.flow_score != null && (
            <SubMetric label="순이동" score={signal.flow_score}
              extra={signal.feature_breakdown?.net_flow != null
                ? `${signal.feature_breakdown.net_flow >= 0 ? "+" : ""}${signal.feature_breakdown.net_flow.toLocaleString()}명`
                : undefined} />
          )}
        </div>
      )}
    </div>
  );
}

function SubMetric({
  label, score, pct, extra, suffix,
}: {
  label: string; score: number;
  pct?: number; extra?: string; suffix?: string;
}) {
  const sign = score > 0 ? "+" : "";
  const color = score > 0 ? "text-blue-300" : score < 0 ? "text-red-300" : "text-gray-400";
  return (
    <div className="rounded-lg bg-gray-900/60 p-2 text-center">
      <div className="text-[10px] text-gray-500">{label}</div>
      <div className={`font-mono text-sm font-semibold ${color}`}>
        {sign}
        {score}
      </div>
      {pct != null && (
        <div className="text-[10px] text-gray-500 mt-0.5">
          {pct >= 0 ? "+" : ""}
          {pct.toFixed(1)}{suffix ?? ""}
        </div>
      )}
      {extra && (
        <div className="text-[10px] text-gray-500 mt-0.5 truncate">{extra}</div>
      )}
    </div>
  );
}
