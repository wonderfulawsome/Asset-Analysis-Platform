import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";

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
    <div className="px-4 pt-4 pb-6">
      <h1 className="text-xl font-bold mb-1">수도권 랭킹</h1>
      <p className="text-xs text-gray-400 mb-4">
        {data?.updated_at && `업데이트 ${data.updated_at}`}
      </p>

      <Section title="📈 거래량 회복 TOP 5" subtitle="t-1 거래량 ÷ 직전 12개월 평균">
        {loading ? <SkeletonRows /> :
          data?.trade_recovery_top5?.length ? (
            data.trade_recovery_top5.map((r, i) => (
              <Row
                key={r.sgg_cd}
                rank={i + 1}
                name={r.sgg_nm}
                value={`${r.trade_vs_long_ratio.toFixed(2)}배`}
                sub={r.trade_count ? `${r.trade_count.toLocaleString()}건` : ""}
                accent="#10b981"
                onClick={() => navigate(`/region/${r.sgg_cd}`)}
              />
            ))
          ) : <Empty />
        }
      </Section>

      <Section title="🔥 가격 상승률 TOP 5" subtitle="3개월 변화율 (sgg-overview)">
        {loading ? <SkeletonRows /> :
          data?.price_top5?.length ? (
            data.price_top5.map((r, i) => (
              <Row
                key={r.sgg_cd}
                rank={i + 1}
                name={r.sgg_nm}
                value={`${r.change_pct_3m >= 0 ? "+" : ""}${r.change_pct_3m.toFixed(1)}%`}
                sub={r.median_price_per_py ? `평단가 ${r.median_price_per_py.toLocaleString()}만/평` : ""}
                accent={r.change_pct_3m >= 0 ? "#ef4444" : "#3b82f6"}
                onClick={() => navigate(`/region/${r.sgg_cd}`)}
              />
            ))
          ) : <Empty />
        }
      </Section>
    </div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h2 className="text-base font-semibold mb-1">{title}</h2>
      {subtitle && <p className="text-[11px] text-gray-500 mb-2">{subtitle}</p>}
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function Row({ rank, name, value, sub, accent, onClick }: {
  rank: number; name: string; value: string; sub?: string; accent: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full bg-gray-900 hover:bg-gray-800 border border-gray-800 rounded-xl px-4 py-3 flex items-center gap-3 transition"
    >
      <div className="text-base font-bold w-6 text-gray-500">{rank}</div>
      <div className="flex-1 min-w-0 text-left">
        <div className="text-sm font-semibold truncate">{name}</div>
        {sub && <div className="text-[11px] text-gray-500 mt-0.5">{sub}</div>}
      </div>
      <div className="text-base font-bold" style={{ color: accent }}>{value}</div>
    </button>
  );
}

function SkeletonRows() {
  return (
    <>
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 h-[58px] animate-pulse" />
      ))}
    </>
  );
}

function Empty() {
  return <div className="text-sm text-gray-500 text-center py-6">데이터 준비 중</div>;
}
