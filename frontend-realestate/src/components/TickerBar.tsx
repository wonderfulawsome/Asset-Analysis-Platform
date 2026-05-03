import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";

// 모든 화면 상단 1줄 라이브 ticker — KOSPI + BASE (USD/KRW 제외, 사용자 결정).
// 60초 polling. cold-start 5s 부담 안 주려 fetch 실패 시 placeholder 유지 (—).
interface IndexQuote {
  date: string;
  ticker: string;
  close: number;
  change_pct: number | null;
  name: string | null;
}
interface MacroRow {
  date: string;
  base_rate: number | null;
}

// 모듈 캐시 — 라우팅 전환 시마다 재 fetch 안 하도록
let _cached: { kospi: IndexQuote | null; base: number | null } | null = null;

export default function TickerBar() {
  const [data, setData] = useState(_cached);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [idx, macro] = await Promise.all([
          apiFetch<IndexQuote[]>(ENDPOINTS.indexLatest("kr")).catch(() => []),
          apiFetch<MacroRow[]>(ENDPOINTS.macroRate()).catch(() => []),
        ]);
        // KOSPI200 ETF (069500 KODEX 200) 또는 첫 항목 — 한국 시장 대표
        const kospi = idx.find((x) => x.ticker === "069500") ?? idx[0] ?? null;
        // base_rate 가 채워진 가장 최근 row
        const baseRow = [...macro].reverse().find((x) => x.base_rate != null);
        const next = { kospi, base: baseRow?.base_rate ?? null };
        if (!cancelled) {
          _cached = next;
          setData(next);
        }
      } catch {
        // ignore
      }
    }
    load();
    const id = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return (
    <div
      className="flex items-center gap-4 px-3 py-1 text-[10px] font-mono tracking-wider
                 bg-black border-b border-term-border overflow-x-auto whitespace-nowrap"
    >
      <Item label="코스피" value={fmt(data?.kospi?.close)} delta={data?.kospi?.change_pct ?? null} />
      <Item label="기준금리" value={data?.base != null ? `${data.base.toFixed(2)}%` : "—"} delta={null} flat />
      <span className="ml-auto text-term-dim">{nowHHMM()}</span>
    </div>
  );
}

function Item({ label, value, delta, flat = false }: {
  label: string; value: string; delta: number | null; flat?: boolean;
}) {
  const color = delta == null
    ? "text-term-dim"
    : delta > 0 ? "text-term-up" : delta < 0 ? "text-term-down" : "text-term-dim";
  const sign = delta == null ? (flat ? "변동 없음" : "—") : `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}%`;
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-term-dim">{label}</span>
      <span className="text-term-text font-bold">{value}</span>
      <span className={color}>{sign}</span>
    </span>
  );
}

function fmt(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
function nowHHMM(): string {
  const d = new Date();
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}
function pad2(n: number): string { return n.toString().padStart(2, "0"); }
