import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import TerminalSection from "../components/TerminalSection";
import { useFavorites } from "../lib/favorites";

interface SearchResult {
  type: "sgg" | "stdg";
  code: string;
  name: string;
  sgg_nm: string;
  sgg_cd: string;
}

// 검색 탭 — 시군구 + 법정동 통합 검색. 입력 후 250ms debounce → /api/realestate/search.
// 결과 click → 시군구는 /region/:cd, 법정동은 /stdg/:cd 라우팅.
export default function SearchScreen() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { favorites, recents, pushRecent } = useFavorites();

  // auto-focus on mount
  useEffect(() => { inputRef.current?.focus(); }, []);

  // debounced fetch
  useEffect(() => {
    const term = q.trim();
    if (term.length === 0) {
      setResults([]);
      return;
    }
    setLoading(true);
    const id = setTimeout(() => {
      apiFetch<SearchResult[]>(ENDPOINTS.search(term))
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(id);
  }, [q]);

  function go(r: SearchResult) {
    pushRecent({ type: r.type, code: r.code, name: r.name, sgg_cd: r.sgg_cd, sgg_nm: r.sgg_nm });
    if (r.type === "sgg") nav(`/region/${r.code}`);
    else nav(`/stdg/${r.code}`);
  }

  return (
    <div className="px-2 pt-2 pb-6 font-mono space-y-2">
      {/* 검색 입력 */}
      <div className="bg-term-panel border border-term-border flex items-center gap-2 px-3 py-2.5">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-term-orange">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="시군구·법정동명 검색 (예: 강남, 옥길)"
          className="flex-1 bg-transparent outline-none text-[12px] text-term-text placeholder-term-dim"
        />
        {q && (
          <button onClick={() => setQ("")} className="text-term-dim hover:text-term-orange text-xs">✕</button>
        )}
      </div>

      {/* 결과 또는 빈 상태 */}
      {q.trim().length === 0 ? (
        <>
          {favorites.length > 0 && (
            <TerminalSection title="관심 지역" dense>
              <ResultList rows={favorites.map((f) => ({
                type: f.type as "sgg" | "stdg", code: f.code, name: f.name,
                sgg_nm: f.sgg_nm ?? "", sgg_cd: f.sgg_cd ?? "",
              }))} onTap={go} />
            </TerminalSection>
          )}
          {recents.length > 0 && (
            <TerminalSection title="최근 검색" dense>
              <ResultList rows={recents.map((r) => ({
                type: r.type as "sgg" | "stdg", code: r.code, name: r.name,
                sgg_nm: r.sgg_nm ?? "", sgg_cd: r.sgg_cd ?? "",
              }))} onTap={go} />
            </TerminalSection>
          )}
          {favorites.length === 0 && recents.length === 0 && (
            <div className="text-center text-term-dim text-[11px] py-10">
              · 시군구명(예: 강남, 부천)이나 법정동명(예: 옥길, 압구정)으로 검색
            </div>
          )}
        </>
      ) : loading ? (
        <div className="text-center text-term-dim text-[11px] py-10">· 검색 중…</div>
      ) : results.length === 0 ? (
        <div className="text-center text-term-dim text-[11px] py-10">· 검색 결과 없음</div>
      ) : (
        <TerminalSection title={`검색 결과 · ${results.length}건`} dense>
          <ResultList rows={results} onTap={go} />
        </TerminalSection>
      )}
    </div>
  );
}

function ResultList({ rows, onTap }: { rows: SearchResult[]; onTap: (r: SearchResult) => void }) {
  return (
    <ul className="divide-y divide-term-border">
      {rows.map((r) => (
        <li
          key={`${r.type}:${r.code}`}
          onClick={() => onTap(r)}
          className="flex items-center gap-2 py-2 px-1 cursor-pointer hover:bg-black/40 active:bg-black/60"
        >
          <span className={`text-[9px] tracking-widest font-bold w-9 text-center px-1 py-0.5 border ${
            r.type === "sgg" ? "text-term-orange border-term-orange" : "text-term-amber border-term-amber/60"
          }`}>
            {r.type === "sgg" ? "시군구" : "법정동"}
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-[12px] text-term-text font-bold truncate">{r.name}</div>
            {r.type === "stdg" && r.sgg_nm && (
              <div className="text-[10px] text-term-dim truncate">{r.sgg_nm}</div>
            )}
          </div>
          <span className="text-[9px] text-term-dim font-mono">{r.code}</span>
        </li>
      ))}
    </ul>
  );
}
