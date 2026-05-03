import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import TerminalSection from "./TerminalSection";

// MARKET BRIEF — 모킹 1 의 상단 박스. 시군구 BUY/HOLD/주의 분포 + 기준금리 + LLM 요약.
// expanded=true 시 전체 텍스트, false 시 첫 줄만.

interface MarketSummaryResponse {
  summary: string;
  signal_distribution: { 매수: number; 관망: number; 주의: number };
  top_up: { sgg_cd: string; change_pct_3m: number; top_stdg_nm: string | null }[];
  top_down: { sgg_cd: string; change_pct_3m: number; top_stdg_nm: string | null }[];
  base_rate_latest: number | null;
  base_rate_drop_12m: number | null;
  as_of: string;
  cached: boolean;
}

export default function MarketSummaryCard() {
  const [data, setData] = useState<MarketSummaryResponse | null>(null);
  const [err, setErr] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    apiFetch<MarketSummaryResponse>(ENDPOINTS.marketSummary())
      .then(setData)
      .catch(() => setErr(true));
  }, []);

  if (err) return null;

  const today = new Date().toISOString().slice(0, 10);  // 2026-05-03
  const right = data ? `${data.as_of.slice(5)} · UPD` : `${today.slice(5)} · LOAD`;

  if (!data) {
    return (
      <TerminalSection title="MARKET BRIEF" right={right} dense>
        <div className="text-[11px] text-term-dim">· loading…</div>
      </TerminalSection>
    );
  }

  return (
    <TerminalSection title="MARKET BRIEF" right={right} dense>
      <div onClick={() => setExpanded((v) => !v)} className="cursor-pointer">
        {/* 시그널 분포 + 기준금리 chips — 같은 줄 */}
        <div className="flex gap-1 items-center text-[10px] font-mono uppercase tracking-wider mb-1.5">
          <Chip label="BUY"   count={data.signal_distribution.매수} color="text-term-green" />
          <Chip label="HOLD"  count={data.signal_distribution.관망} color="text-term-dim"   />
          <Chip label="WATCH" count={data.signal_distribution.주의} color="text-term-up"    />
          {data.base_rate_latest != null && (
            <span className="ml-auto text-term-dim">
              BASE <span className="text-term-text font-bold">{data.base_rate_latest.toFixed(3)}</span>
            </span>
          )}
        </div>

        {/* LLM 요약 — 첫 줄 또는 전체 */}
        <p className={`text-[11.5px] leading-snug text-term-text ${expanded ? "" : "line-clamp-2"}`}>
          {data.summary}
        </p>

        <div className="text-[9px] text-term-orange mt-1 font-bold tracking-widest uppercase">
          {expanded ? "▲ 접기" : "▼ 더 보기"}
        </div>
      </div>
    </TerminalSection>
  );
}

function Chip({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <span className="flex items-center gap-1 px-1.5 py-0.5 border border-term-border bg-term-bg">
      <span className={`${color} font-bold`}>{label}</span>
      <span className="text-term-text font-bold">{count}</span>
    </span>
  );
}
