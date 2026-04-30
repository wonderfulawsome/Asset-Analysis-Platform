import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";

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
  if (!data) {
    return (
      <div className="bg-gray-900/95 backdrop-blur-md rounded-2xl border border-gray-800 px-4 py-3 mt-2">
        <div className="text-[10px] tracking-[0.2em] text-orange-400 font-bold mb-1">
          TODAY · 시장 요약
        </div>
        <div className="text-[12px] text-gray-500">로딩 중…</div>
      </div>
    );
  }

  const dist = data.signal_distribution;

  return (
    <div
      className="bg-gray-900/95 backdrop-blur-md rounded-2xl border border-gray-800 px-4 py-3 mt-2 cursor-pointer active:scale-[0.99] transition"
      onClick={() => setExpanded((v) => !v)}
    >
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] tracking-[0.2em] text-orange-400 font-bold">
          TODAY · 시장 요약
        </span>
        <span className="text-[9px] text-gray-500 font-mono">{data.as_of.slice(5)}</span>
      </div>

      {/* 시그널 분포 chips */}
      <div className="flex gap-1.5 mb-2">
        <Chip label="매수" count={dist.매수} color="#10b981" />
        <Chip label="관망" count={dist.관망} color="#9ca3af" />
        <Chip label="주의" count={dist.주의} color="#ef4444" />
        {data.base_rate_latest != null && (
          <span className="text-[10px] text-gray-400 ml-auto self-center">
            기준금리 {data.base_rate_latest}%
          </span>
        )}
      </div>

      {/* LLM 요약 */}
      <p
        className={`text-[12.5px] leading-relaxed text-gray-200 ${
          expanded ? "" : "line-clamp-2"
        }`}
      >
        {data.summary}
      </p>

      {/* 더 보기 */}
      <div className="text-[10px] text-orange-400 mt-1 font-semibold">
        {expanded ? "접기 ▲" : "더 보기 ▼"}
      </div>
    </div>
  );
}

function Chip({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <span
      className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
      style={{ backgroundColor: `${color}22`, color }}
    >
      {label} {count}
    </span>
  );
}
