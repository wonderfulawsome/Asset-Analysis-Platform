import type { BuySignal } from "../types/api";

interface Props {
  signal: BuySignal | null;
  changePct?: number | null;
}

// AI 해설 카드 — Step D 미구현이라 룰베이스 placeholder.
// signal.narrative 가 채워지면 그 값 우선 사용.
export default function AiInsightCard({ signal, changePct }: Props) {
  // signal 이 없는 경우는 카드 자체를 숨기지 않고 안내만
  const hasSignal = !!signal?.signal;
  const narrative = signal?.narrative || (hasSignal ? generatePlaceholder(signal!) : null);
  const { strengths, risks } = generatePros(signal);

  return (
    <div className="rounded-2xl bg-gradient-to-br from-blue-500/10 to-purple-500/10
                    ring-1 ring-blue-500/20 p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-500/30 text-blue-100">
          AI 분석
        </span>
        {changePct != null && (
          <span className="text-[11px] text-term-dim">
            3M {changePct >= 0 ? "+" : ""}{changePct.toFixed(1)}%
          </span>
        )}
      </div>
      <p className="text-sm leading-relaxed text-term-text">
        {narrative ?? "시그널 산출에 필요한 데이터가 누적되면 AI 해설이 표시됩니다."}
      </p>
      {(strengths.length > 0 || risks.length > 0) && (
        <div className="grid grid-cols-2 gap-2 mt-3">
          <div className="rounded-lg bg-blue-500/10 p-2.5">
            <div className="text-[10px] text-blue-300 font-semibold mb-1">강점</div>
            <div className="text-[11px] text-term-text leading-tight">
              {strengths.length ? strengths.join(", ") : "—"}
            </div>
          </div>
          <div className="rounded-lg bg-red-500/10 p-2.5">
            <div className="text-[10px] text-red-300 font-semibold mb-1">리스크</div>
            <div className="text-[11px] text-term-text leading-tight">
              {risks.length ? risks.join(", ") : "—"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function generatePlaceholder(s: BuySignal): string {
  const fb = s.feature_breakdown ?? ({} as any);
  const parts: string[] = [];
  if (fb.trade_chg_pct != null) {
    parts.push(`거래량 ${pct(fb.trade_chg_pct)}`);
  }
  if (fb.price_mom_pct != null) {
    parts.push(`가격 ${pct(fb.price_mom_pct)} MoM`);
  }
  if (fb.net_flow != null) {
    parts.push(`순이동 ${fb.net_flow >= 0 ? "+" : ""}${fb.net_flow.toLocaleString()}명`);
  }
  const summary = parts.join(", ");
  const verdict =
    s.signal === "매수" ? "매수 우호 구간"
    : s.signal === "주의" ? "수요 약세, 보수적 접근"
    : "추세 확인 필요";
  return summary ? `${summary} → ${verdict}` : verdict;
}

function generatePros(s: BuySignal | null): { strengths: string[]; risks: string[] } {
  if (!s) return { strengths: [], risks: [] };
  const strengths: string[] = [];
  const risks: string[] = [];
  // 점수 부호로 단순 분류
  if ((s.trade_score ?? 0) > 5) strengths.push("거래량 증가");
  if ((s.trade_score ?? 0) < -5) risks.push("거래량 위축");
  if ((s.price_score ?? 0) > 5) strengths.push("가격 상승");
  if ((s.price_score ?? 0) < -5) risks.push("가격 하락");
  if ((s.pop_score ?? 0) > 5) strengths.push("인구 유입");
  if ((s.pop_score ?? 0) < -5) risks.push("인구 유출");
  if ((s.flow_score ?? 0) > 5) strengths.push("순유입세");
  if ((s.flow_score ?? 0) < -5) risks.push("순유출세");
  if ((s.rate_score ?? 0) > 10) strengths.push("금리 우호");
  if ((s.rate_score ?? 0) < -10) risks.push("금리 부담");
  return { strengths, risks };
}

function pct(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
}
