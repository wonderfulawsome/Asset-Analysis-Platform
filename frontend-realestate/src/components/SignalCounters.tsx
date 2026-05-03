import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";

// 모킹 1 의 BUY/HOLD/WATCH 카운터 — 시장 요약 API 의 signal_distribution 활용.
// BUY=매수 (term-green), HOLD=관망 (term-dim), WATCH=주의 (term-up: 빨강 — 위험 경보).
interface MarketSummary {
  signal_distribution?: {
    매수?: number;
    관망?: number;
    주의?: number;
  } | null;
}

export default function SignalCounters() {
  const [d, setD] = useState<MarketSummary["signal_distribution"]>(null);
  useEffect(() => {
    apiFetch<MarketSummary>(ENDPOINTS.marketSummary())
      .then((r) => setD(r.signal_distribution ?? null))
      .catch(() => {});
  }, []);
  const buy = d?.["매수"] ?? 0;
  const hold = d?.["관망"] ?? 0;
  const watch = d?.["주의"] ?? 0;
  return (
    <div className="flex items-stretch gap-1 text-[10px] font-mono uppercase tracking-widest">
      <Counter label="BUY"   value={buy}   color="text-term-green" />
      <Counter label="HOLD"  value={hold}  color="text-term-dim"   />
      <Counter label="WATCH" value={watch} color="text-term-up"    />
    </div>
  );
}

function Counter({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-1.5 px-2 py-0.5 border border-term-border bg-term-bg">
      <span className={`${color} font-bold`}>{label}</span>
      <span className="text-term-text font-bold">{value}</span>
    </div>
  );
}
