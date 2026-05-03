import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import TerminalSection from "../components/TerminalSection";

interface TradeRow {
  sgg_cd: string;
  sgg_nm: string;
  trade_vs_long_ratio: number;
  trade_count: number | null;
  stats_ym: string;
}
interface PriceRow {
  sgg_cd: string;
  sgg_nm: string;
  change_pct_3m: number;
  median_price_per_py: number | null;
  stats_ym: string;
}
interface RankingPayload {
  trade_recovery_top5: TradeRow[];
  price_top5: PriceRow[];
  updated_at: string;
}

type SortKey = "rank" | "name" | "value";
type SortDir = "asc" | "desc";

export default function RankingScreen() {
  const navigate = useNavigate();
  const [data, setData] = useState<RankingPayload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiFetch<RankingPayload>(ENDPOINTS.ranking())
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => console.error("[RankingScreen]", e))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="px-2 pt-2 pb-6 font-mono">
      {/* SECTION 01 — 거래량 회복 */}
      <div className="mb-2">
        <TerminalSection
          title="TRADE RECOVERY · TOP 5"
          right={data?.updated_at ? `UPD ${data.updated_at.slice(5)}` : "LOADING"}
          dense
        >
          <p className="text-[9px] text-term-dim uppercase tracking-widest mb-1">
            t-1 거래량 ÷ 직전 12M 평균
          </p>
          {loading ? <SkeletonTable cols={4} /> : (
            <RankTable
              rows={(data?.trade_recovery_top5 ?? []).map((r, i) => ({
                rank: i + 1,
                sggCd: r.sgg_cd,
                name: r.sgg_nm,
                value: r.trade_vs_long_ratio,
                valueFmt: `${r.trade_vs_long_ratio.toFixed(2)}x`,
                sub: r.trade_count ? `${r.trade_count.toLocaleString()}건` : "—",
                color: r.trade_vs_long_ratio >= 1 ? "text-term-up" : "text-term-down",
              }))}
              valueLabel="RATIO"
              subLabel="VOL"
              onClick={(sggCd) => navigate(`/region/${sggCd}`)}
            />
          )}
        </TerminalSection>
      </div>

      {/* SECTION 02 — 가격 상승률 */}
      <TerminalSection
        title="PRICE 3M Δ · TOP 5"
        right={data?.updated_at ? `UPD ${data.updated_at.slice(5)}` : "LOADING"}
        dense
      >
        <p className="text-[9px] text-term-dim uppercase tracking-widest mb-1">
          3개월 변화율 (sgg-overview)
        </p>
        {loading ? <SkeletonTable cols={4} /> : (
          <RankTable
            rows={(data?.price_top5 ?? []).map((r, i) => ({
              rank: i + 1,
              sggCd: r.sgg_cd,
              name: r.sgg_nm,
              value: r.change_pct_3m,
              valueFmt: `${r.change_pct_3m >= 0 ? "+" : ""}${r.change_pct_3m.toFixed(1)}%`,
              sub: r.median_price_per_py ? `${r.median_price_per_py.toLocaleString()}만/평` : "—",
              color: r.change_pct_3m >= 0 ? "text-term-up" : "text-term-down",
            }))}
            valueLabel="3M Δ"
            subLabel="W/PY"
            onClick={(sggCd) => navigate(`/region/${sggCd}`)}
          />
        )}
      </TerminalSection>
    </div>
  );
}

interface RankRow {
  rank: number;
  sggCd: string;
  name: string;
  value: number;
  valueFmt: string;
  sub: string;
  color: string;
}

function RankTable({ rows, valueLabel, subLabel, onClick }: {
  rows: RankRow[];
  valueLabel: string;
  subLabel: string;
  onClick: (sggCd: string) => void;
}) {
  const [key, setKey] = useState<SortKey>("rank");
  const [dir, setDir] = useState<SortDir>("asc");

  const sorted = useMemo(() => {
    const sgn = dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      if (key === "rank") return (a.rank - b.rank) * sgn;
      if (key === "name") return a.name.localeCompare(b.name) * sgn;
      return (a.value - b.value) * sgn;
    });
  }, [rows, key, dir]);

  function toggle(k: SortKey) {
    if (key === k) setDir(dir === "asc" ? "desc" : "asc");
    else { setKey(k); setDir(k === "rank" ? "asc" : "desc"); }
  }

  if (rows.length === 0) {
    return <div className="text-[11px] text-term-dim text-center py-3">· no data</div>;
  }

  return (
    <table className="w-full text-[11px]">
      <thead>
        <tr className="text-[9px] uppercase tracking-widest text-term-dim border-b border-term-border">
          <Th onClick={() => toggle("rank")} active={key === "rank"} dir={dir}>#</Th>
          <Th onClick={() => toggle("name")} active={key === "name"} dir={dir} align="left">SGG</Th>
          <Th onClick={() => toggle("value")} active={key === "value"} dir={dir} align="right">{valueLabel}</Th>
          <th className="text-right py-1.5 pl-2 font-normal text-term-dim">{subLabel}</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
          <tr
            key={r.sggCd}
            onClick={() => onClick(r.sggCd)}
            className="border-b border-term-border cursor-pointer hover:bg-black/40 active:bg-black/60"
          >
            <td className="py-1.5 text-term-dim text-center w-6 font-bold">{r.rank}</td>
            <td className="py-1.5 text-term-text font-bold truncate">{r.name}</td>
            <td className={`py-1.5 text-right font-bold font-mono ${r.color}`}>{r.valueFmt}</td>
            <td className="py-1.5 text-right text-term-dim text-[10px]">{r.sub}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Th({ children, onClick, active, dir, align = "center" }: {
  children: React.ReactNode;
  onClick?: () => void;
  active?: boolean;
  dir?: SortDir;
  align?: "left" | "right" | "center";
}) {
  return (
    <th
      onClick={onClick}
      className={`py-1.5 font-normal cursor-pointer hover:text-term-orange ${
        align === "left" ? "text-left" : align === "right" ? "text-right" : "text-center"
      } ${active ? "text-term-orange font-bold" : ""}`}
    >
      {children}{active && (dir === "asc" ? " ▲" : " ▼")}
    </th>
  );
}

function SkeletonTable({ cols }: { cols: number }) {
  return (
    <div className="space-y-1">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="grid gap-1 animate-pulse" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
          {Array.from({ length: cols }).map((_, j) => (
            <div key={j} className="h-5 bg-term-border" />
          ))}
        </div>
      ))}
    </div>
  );
}
