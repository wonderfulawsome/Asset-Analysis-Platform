import type { BuySignal, RegionSummary } from "../types/api";

interface SelectedRegion {
  sggCd: string;
  sggNm: string;
  topStdgNm: string | null;
  topStdgCd: string | null;
  medianPricePerPy: number | null;
  changePct: number | null;
}

interface Props {
  selected: SelectedRegion | null;
  signal: BuySignal | null;
  topStdgSummary: RegionSummary | null;
  loading?: boolean;       // fetch 진행 중이면 "-" 대신 스피너 표시
  onTap: () => void;
  onClose: () => void;
}

function Spinner() {
  return (
    <svg className="inline-block animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
      <circle cx="12" cy="12" r="9" stroke="#374151" strokeOpacity="0.4" />
      <path d="M21 12a9 9 0 0 1-9 9" stroke="#9ca3af" strokeLinecap="round" />
    </svg>
  );
}

export default function FeatureCard({ selected, signal, topStdgSummary, loading, onTap, onClose }: Props) {
  if (!selected) return null;

  const change = selected.changePct;
  const changeStr = change != null ? `${change >= 0 ? "+" : ""}${change.toFixed(1)}%` : null;
  const changeColor = change != null
    ? change > 0 ? "#ef4444" : change < 0 ? "#3b82f6" : "#9ca3af"
    : "#9ca3af";

  const tradeCount = topStdgSummary?.trade_count ?? null;
  const signalLabel = signal?.signal ?? null;
  const signalColor = signalLabel === "매수" ? "#10b981"
                    : signalLabel === "주의" ? "#ef4444"
                    : "#9ca3af";

  const summary = buildSummary(selected, signal, topStdgSummary);

  const ymLabel = signal?.stats_ym
    ? `${signal.stats_ym.slice(0, 4)}.${signal.stats_ym.slice(4, 6)}`
    : new Date().toISOString().slice(0, 7).replace("-", ".");

  return (
    <>
      {/* backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-30"
        onClick={onClose}
      />
      {/* card */}
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 w-[90%] max-w-md">
        <div
          className="bg-gray-950 rounded-2xl shadow-2xl border border-gray-800 p-5 cursor-pointer hover:border-gray-700 active:scale-[0.99] transition"
          onClick={onTap}
        >
          {/* 헤더 */}
          <div className="flex justify-between items-center text-[10px] uppercase tracking-wider text-gray-500 mb-3">
            <span className="font-semibold">FEATURES · 요약</span>
            <span>{ymLabel} · UPD</span>
          </div>

          {/* 동 이름 */}
          <h2 className="text-2xl font-bold mb-3 text-white">
            {selected.topStdgNm ?? selected.sggNm}
          </h2>

          {/* 요약 문장 */}
          <p className="text-sm text-gray-300 leading-relaxed mb-4 min-h-[3em]">
            {loading && !signal && !topStdgSummary ? (
              <span className="inline-flex items-center gap-2 text-gray-500"><Spinner /> 데이터 불러오는 중…</span>
            ) : summary}
          </p>

          {/* 메트릭 3개 */}
          <div className="grid grid-cols-3 gap-3 mb-4">
            <Metric
              label="거래량"
              value={tradeCount != null ? tradeCount.toLocaleString() : null}
              unit={tradeCount != null ? "건" : undefined}
              loading={loading && tradeCount == null}
            />
            <Metric
              label="3M 변화"
              value={changeStr}
              valueColor={changeColor}
              loading={loading && changeStr == null}
            />
            <Metric
              label="신호"
              value={signalLabel}
              valueColor={signalColor}
              loading={loading && signalLabel == null}
            />
          </div>

          {/* CTA */}
          <div className="border-t border-gray-800 pt-3 flex justify-between items-center">
            <span className="text-sm text-gray-400">전체 분석 읽기</span>
            <span className="text-orange-400 font-semibold text-sm tracking-wide">
              READ →
            </span>
          </div>
        </div>
      </div>
    </>
  );
}

function Metric({
  label,
  value,
  unit,
  valueColor,
  loading,
}: {
  label: string;
  value: string | null;
  unit?: string;
  valueColor?: string;
  loading?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] text-gray-500 uppercase tracking-wide mb-1">{label}</div>
      <div className="text-base font-bold" style={{ color: valueColor ?? "#fff" }}>
        {loading ? <Spinner /> : (value ?? "-")}
        {unit && !loading && <span className="text-[10px] text-gray-400 ml-0.5 font-normal">{unit}</span>}
      </div>
    </div>
  );
}

// 요약 문장 룰베이스 — narrative 가 LLM 으로 채워지면 그걸 쓰도록 변경
function buildSummary(
  selected: SelectedRegion,
  signal: BuySignal | null,
  summary: RegionSummary | null
): string {
  const change = selected.changePct;
  const tradeChg = signal?.feature_breakdown?.trade_chg_pct;
  const priceMom = signal?.feature_breakdown?.price_mom_pct;
  const sigLabel = signal?.signal;

  // narrative LLM 결과가 있으면 우선
  // (현재 BuySignal 타입에 narrative 없으나, scheduler 가 채우면 추가 예정)

  const parts: string[] = [];
  if (tradeChg != null) {
    const dir = tradeChg >= 0 ? "증가했고" : "위축됐지만";
    parts.push(`거래량은 ${tradeChg >= 0 ? "+" : ""}${tradeChg.toFixed(1)}% ${dir}`);
  }
  if (priceMom != null) {
    const dir = priceMom >= 0 ? "반등" : "하락";
    parts.push(`가격은 ${priceMom >= 0 ? "+" : ""}${priceMom.toFixed(1)}% ${dir}`);
  } else if (change != null) {
    const dir = change >= 0 ? "상승" : "하락";
    parts.push(`3M 변화율 ${change >= 0 ? "+" : ""}${change.toFixed(1)}% ${dir}`);
  }
  if (sigLabel) {
    const meaning = sigLabel === "매수" ? "매수 우위 신호"
                  : sigLabel === "주의" ? "매수 심리 약한 신호"
                  : "관망 구간";
    parts.push(meaning);
  }
  if (parts.length === 0) {
    return "데이터 수집 중입니다. 잠시 후 다시 확인해 주세요.";
  }
  return parts.join(", ") + ".";
}
