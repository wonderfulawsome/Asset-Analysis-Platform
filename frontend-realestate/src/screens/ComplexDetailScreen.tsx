import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import NavBar from "../components/NavBar";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import type { Trade } from "../types/api";

// 단지 상세 — 같은 시군구 매매 전량을 당겨 apt_seq 로 필터.
export default function ComplexDetailScreen() {
  const { aptSeq } = useParams<{ aptSeq: string }>();
  const [qs] = useSearchParams();
  const sggCd = qs.get("sgg_cd") ?? "";
  const [allTrades, setAllTrades] = useState<Trade[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!sggCd) {
      setErr("sgg_cd 쿼리 누락");
      return;
    }
    let cancelled = false;
    apiFetch<Trade[]>(ENDPOINTS.trades(sggCd))
      .then((d) => { if (!cancelled) setAllTrades(d); })
      .catch((e) => { if (!cancelled) setErr(String(e)); });
    return () => { cancelled = true; };
  }, [sggCd]);

  const trades = useMemo(
    () => (allTrades ?? []).filter((t) => t.apt_seq === aptSeq),
    [allTrades, aptSeq],
  );
  const first = trades[0];

  return (
    <div className="min-h-full bg-gray-900">
      <NavBar
        title={first?.apt_nm ?? aptSeq ?? "단지"}
        subtitle={first ? `${first.umd_nm ?? ""} · ${first.build_year ?? "?"}년` : undefined}
      />

      {err && <div className="p-4 text-red-400 text-sm">{err}</div>}
      {!allTrades && !err && (
        <div className="p-10 text-center text-gray-500 text-sm">로딩 중…</div>
      )}

      {allTrades && trades.length === 0 && (
        <div className="p-10 text-center text-gray-500 text-sm">
          이번 달 해당 단지 거래가 없습니다.
        </div>
      )}

      {trades.length > 0 && (
        <div className="p-3 space-y-2">
          {trades.map((t, i) => (
            <div key={i} className="rounded-xl bg-gray-800/80 p-4 flex justify-between items-center">
              <div>
                <div className="text-sm">{t.deal_date}</div>
                <div className="text-[11px] text-gray-400 mt-0.5">
                  전용 {t.exclu_use_ar.toFixed(1)}㎡ · {t.floor ?? "-"}층
                </div>
              </div>
              <div className="font-mono text-base font-semibold">
                {t.deal_amount.toLocaleString()}만
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
