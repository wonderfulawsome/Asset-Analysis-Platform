import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { apiFetch } from "../api/client";
import { ENDPOINTS } from "../api/endpoints";
import { changePctColor, formatPriceMan } from "../lib/color";
import type { StdgDetail } from "../types/api";

// "HOMELENS · DAILY" 신문 스타일 — 첨부 이미지 매칭.
// 기존 컴포넌트 (NavBar, AiInsightCard, MetricGrid 등) 사용 X — serif 신문 layout 직접 작성.
export default function StdgDetailScreen() {
  const { stdgCd } = useParams<{ stdgCd: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<StdgDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!stdgCd) return;
    let cancelled = false;
    apiFetch<StdgDetail>(ENDPOINTS.stdgDetail(stdgCd))
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setErr(String(e)));
    return () => { cancelled = true; };
  }, [stdgCd]);

  if (err) return <div className="p-6 text-red-400 text-sm">{err}</div>;
  if (!data) return <div className="p-10 text-center text-term-dim text-sm">로딩 중…</div>;

  const s = data.summary;
  if (!s) {
    return (
      <div className="min-h-full bg-term-bg text-term-text font-mono">
        <DailyHeader stdgCd={stdgCd ?? ""} ym={null} sggCd={null} />
        <div className="p-10 text-center text-term-dim text-sm">
          이번 달 집계된 데이터가 없습니다.
        </div>
      </div>
    );
  }

  const headline = buildHeadline(s, data.signal);
  const subhead = buildSubhead(s, data.signal);
  const body = buildBody(s, data.signal);
  const editorNote = buildEditorNote(s, data.signal);
  const ymLabel = formatYm(s.stats_ym);
  const issueNo = ymToIssueNo(s.stats_ym);

  return (
    <div className="min-h-full bg-term-bg text-term-text font-mono pb-24">
      <DailyHeader stdgCd={stdgCd ?? ""} ym={ymLabel} sggCd={s.sgg_cd ?? null} issueNo={issueNo} />

      {/* 큰 제목 + 부제 */}
      <section className="px-5 mt-6">
        <h1 className="text-[28px] leading-[1.2] font-bold tracking-tight text-white">
          {headline}
        </h1>
        <p className="text-[14px] italic text-term-dim mt-3 leading-relaxed">
          {subhead}
        </p>
      </section>

      {/* 본문 — 2단 컬럼 (신문 스타일) */}
      <section className="px-5 mt-6">
        <p className="text-[13px] leading-[1.7] text-term-text columns-2 gap-4">
          {body}
        </p>
      </section>

      {/* TABLE 01 — 핵심 지표 */}
      <section className="px-5 mt-8">
        <div className="border-t border-b border-term-border py-2 mb-2">
          <div className="text-[10px] tracking-[0.2em] text-term-dim font-bold">
            TABLE 01 · 핵심 지표
          </div>
        </div>
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-[10px] tracking-wider text-term-dim uppercase border-b border-term-border">
              <th className="text-left py-2 font-normal">METRIC</th>
              <th className="text-right py-2 font-normal">VALUE</th>
              <th className="text-right py-2 font-normal w-16">Δ 3M</th>
            </tr>
          </thead>
          <tbody>
            <Row
              label="평균 매매가"
              value={formatPriceMan(s.median_price ?? s.median_price_per_py)}
              delta={s.change_pct_3m}
            />
            <Row
              label="거래량"
              value={`${(s.trade_count_3m ?? s.trade_count ?? 0).toLocaleString()}건`}
              delta={data.signal?.feature_breakdown?.trade_chg_pct ?? null}
            />
            <Row
              label="전세가율"
              value={s.jeonse_rate != null ? `${(s.jeonse_rate * 100).toFixed(1)}%` : "-"}
              delta={null}
            />
            <Row
              label="순이동"
              value={s.net_flow != null
                ? `${s.net_flow >= 0 ? "+" : ""}${s.net_flow.toLocaleString()}명`
                : "-"}
              delta={data.signal?.flow_score ?? null}
              deltaIsRaw={true}
            />
            <Row
              label="평단가"
              value={s.median_price_per_py != null
                ? `${Math.round(s.median_price_per_py).toLocaleString()}만`
                : "-"}
              delta={s.change_pct_3m}
            />
          </tbody>
        </table>
      </section>

      {/* EDITOR'S NOTE */}
      <section className="px-5 mt-8">
        <div className="border-t-2 border-term-orange pt-3">
          <div className="text-[10px] tracking-[0.2em] text-term-orange font-bold mb-2">
            EDITOR'S NOTE
          </div>
          <p className="text-[13px] italic text-term-text leading-relaxed">
            "{editorNote}"
          </p>
        </div>
      </section>

      {/* 단지 리스트 (작게) */}
      {data.complexes.length > 0 && (
        <section className="px-5 mt-8">
          <div className="border-t border-b border-term-border py-2 mb-3">
            <div className="text-[10px] tracking-[0.2em] text-term-dim font-bold">
              TABLE 02 · 주요 단지
            </div>
          </div>
          <ul className="divide-y divide-term-border">
            {data.complexes.slice(0, 5).map((c) => (
              <li
                key={c.apt_seq}
                onClick={() =>
                  navigate(`/complex/${c.apt_seq}?sgg_cd=${(s.sgg_cd ?? stdgCd?.slice(0, 5)) ?? ""}`)
                }
                className="flex justify-between items-center py-3 cursor-pointer active:bg-term-panel"
              >
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold truncate text-term-text">{c.apt_nm ?? c.apt_seq}</div>
                  <div className="text-[10px] text-term-dim">
                    {c.build_year ? `${c.build_year}년` : ""}{c.build_year ? " · " : ""}거래 {c.trade_count}건
                  </div>
                </div>
                <div className="text-[13px] font-mono font-semibold text-term-text shrink-0 ml-3">
                  {Math.round(c.median_price_per_py).toLocaleString()}만/평
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="text-[10px] text-term-dim text-center mt-10 italic">
        ⚠️ 본 분석은 참고용이며 투자 권유가 아닙니다.
      </p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// 헤더 (HOMELENS · DAILY)
// ─────────────────────────────────────────────────────────────────────
function DailyHeader({
  ym, sggCd, issueNo,
}: { stdgCd: string; ym: string | null; sggCd: string | null; issueNo?: string }) {
  const navigate = useNavigate();
  const dayLabel = ym ? toDayLabel(ym) : "";
  const sggLabel = sggCd ? sggCdToName(sggCd) : "";
  return (
    <header className="px-5 pt-3 border-b border-term-border">
      <div className="flex items-center justify-between">
        <button onClick={() => navigate(-1)} className="text-term-dim text-base">‹</button>
        <div className="text-term-text">♡</div>
      </div>
      <div className="text-center mt-2">
        <div className="text-[10px] tracking-[0.4em] text-term-dim font-bold">
          HOMELENS · DAILY
        </div>
        <div className="text-[10px] tracking-[0.2em] text-term-dim mt-1">
          {dayLabel}{issueNo ? ` · ${issueNo}` : ""}{sggLabel ? ` · ${sggLabel.toUpperCase()}` : ""}
        </div>
      </div>
      <div className="h-2" />
    </header>
  );
}

function Row({
  label, value, delta, deltaIsRaw,
}: { label: string; value: string; delta: number | null; deltaIsRaw?: boolean }) {
  let deltaStr = "-";
  let deltaColor = "#6b7280";
  if (delta != null) {
    if (deltaIsRaw) {
      deltaStr = `${delta >= 0 ? "+" : ""}${Math.round(delta)}`;
      deltaColor = delta > 0 ? "#fca5a5" : delta < 0 ? "#93c5fd" : "#9ca3af";
    } else {
      deltaStr = `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`;
      deltaColor = changePctColor(delta);
    }
  }
  return (
    <tr className="border-b border-term-border">
      <td className="py-2.5 text-term-text">{label}</td>
      <td className="py-2.5 text-right font-mono text-term-text font-semibold">{value}</td>
      <td className="py-2.5 text-right font-mono text-[12px]" style={{ color: deltaColor }}>
        {deltaStr}
      </td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────────────
// 룰베이스 카피 생성 (LLM narrative 들어오면 대체)
// ─────────────────────────────────────────────────────────────────────
function buildHeadline(s: StdgDetail["summary"], signal: StdgDetail["signal"]) {
  if (!s) return "";
  const tradeChg = signal?.feature_breakdown?.trade_chg_pct;
  const priceMom = signal?.feature_breakdown?.price_mom_pct;
  const stdgNm = s.stdg_nm ?? "";
  if (tradeChg != null && priceMom != null) {
    if (tradeChg < 0 && priceMom > 0) return `${stdgNm}, 거래 줄어도 가격 반등`;
    if (tradeChg > 0 && priceMom > 0) return `${stdgNm}, 거래·가격 동반 상승`;
    if (tradeChg < 0 && priceMom < 0) return `${stdgNm}, 거래·가격 동반 위축`;
    if (tradeChg > 0 && priceMom < 0) return `${stdgNm}, 거래 늘어도 가격 약세`;
  }
  return `${stdgNm} 시장 동향`;
}

function buildSubhead(s: StdgDetail["summary"], signal: StdgDetail["signal"]) {
  if (!s) return "";
  const py = s.median_price_per_py != null ? `${Math.round(s.median_price_per_py).toLocaleString()}만` : "-";
  const chg = s.change_pct_3m != null ? `${s.change_pct_3m >= 0 ? "+" : ""}${s.change_pct_3m.toFixed(1)}%` : "-";
  const sigLabel = signal?.signal === "매수" ? "매수 우호 구간 진입"
                 : signal?.signal === "주의" ? "매수 심리 약한 구간"
                 : "관망 구간 유지";
  return `평단가 ${py} 원, 3M ${chg} — ${sigLabel}.`;
}

function buildBody(s: StdgDetail["summary"], signal: StdgDetail["signal"]) {
  if (!s) return "";
  const fb = signal?.feature_breakdown;
  const stdgNm = s.stdg_nm ?? "이 동";
  const py = s.median_price_per_py != null ? `${Math.round(s.median_price_per_py).toLocaleString()}` : "-";
  const tradeChg = fb?.trade_chg_pct;
  const priceMom = fb?.price_mom_pct;
  const popChg = fb?.pop_chg_pct;
  const tradeChgStr = tradeChg != null ? `${tradeChg >= 0 ? "+" : ""}${tradeChg.toFixed(1)}%` : "변동 없음";
  const priceMomStr = priceMom != null ? `${priceMom >= 0 ? "+" : ""}${priceMom.toFixed(1)}%` : "변동 없음";
  const tradeCnt = s.trade_count_3m ?? s.trade_count ?? 0;

  let body = `${stdgNm}의 3M 거래량은 직전 분기 대비 ${tradeChgStr} 변화했고, 평균 매매가는 ${py}만 원으로 ${priceMomStr} 움직였다. `;
  if (popChg != null) {
    body += `순이동은 ${popChg >= 0 ? "유입" : "유출"} ${Math.abs(popChg).toFixed(1)}% 흐름이 관찰됐고, `;
  }
  body += `전체 거래는 ${tradeCnt}건으로 집계됐다. `;
  if (s.jeonse_rate != null) {
    body += `전세가율은 ${(s.jeonse_rate * 100).toFixed(1)}%로 서울 평균과 비교된다. `;
  }
  if (signal?.signal) {
    const remark = signal.signal === "매수" ? "신호 점수는 매수 우위로 기록됐다."
                 : signal.signal === "주의" ? "신호 점수는 매수 심리 약화 구간으로 분류됐다."
                 : "신호 점수는 관망 구간으로 분류됐다.";
    body += remark;
  }
  return body;
}

function buildEditorNote(s: StdgDetail["summary"], signal: StdgDetail["signal"]) {
  if (!signal?.feature_breakdown) {
    return s?.stdg_nm ? `${s.stdg_nm} — 데이터 누적 중` : "데이터 누적 중";
  }
  const fb = signal.feature_breakdown;
  const trade = fb.trade_chg_pct != null ? `${fb.trade_chg_pct >= 0 ? "+" : ""}${fb.trade_chg_pct.toFixed(1)}%` : "-";
  const price = fb.price_mom_pct != null ? `${fb.price_mom_pct >= 0 ? "+" : ""}${fb.price_mom_pct.toFixed(1)}%` : "-";
  const pop = fb.pop_chg_pct != null ? `${fb.pop_chg_pct >= 0 ? "+" : ""}${fb.pop_chg_pct.toFixed(0)}` : "-";
  const sigLabel = signal.signal === "매수" ? "매수 우호 구간"
                 : signal.signal === "주의" ? "매수 주의 구간"
                 : "관망 구간";
  return `거래량 ${trade}, 가격 ${price} MoM, 인구 ${pop}명 → ${sigLabel}.`;
}

// ─────────────────────────────────────────────────────────────────────
// 헬퍼
// ─────────────────────────────────────────────────────────────────────
function formatYm(ym?: string | null): string | null {
  if (!ym || ym.length < 6) return null;
  return `${ym.slice(0, 4)}.${ym.slice(4, 6)}.01`;
}

function toDayLabel(ymd: string): string {
  // "2026.03.01" → "FRI · 2026.03.01"
  try {
    const [y, m, d] = ymd.split(".").map(Number);
    const dt = new Date(y, m - 1, d);
    const dow = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][dt.getDay()];
    return `${dow} · ${ymd}`;
  } catch {
    return ymd;
  }
}

function ymToIssueNo(ym?: string | null): string {
  if (!ym || ym.length < 6) return "VOL.01";
  const m = parseInt(ym.slice(4, 6), 10);
  return `VOL.${String(m).padStart(2, "0")} · NO.${ym.slice(2)}`;
}

function sggCdToName(sggCd: string): string {
  const map: Record<string, string> = {
    "11290": "SEONGBUK", "11680": "GANGNAM", "11710": "SONGPA", "11650": "SEOCHO",
    "11440": "MAPO", "11380": "EUNPYEONG", "11470": "YANGCHEON", "11500": "GANGSEO",
    "11530": "GURO", "11560": "YEONGDEUNGPO", "11200": "SEONGDONG", "11215": "GWANGJIN",
    "11230": "DONGDAEMUN", "11260": "JUNGNANG", "11305": "GANGBUK", "11320": "DOBONG",
    "11350": "NOWON", "11410": "SEODAEMUN", "11545": "GEUMCHEON", "11590": "DONGJAK",
    "11620": "GWANAK", "11740": "GANGDONG", "11110": "JONGNO", "11140": "JUNG",
    "11170": "YONGSAN",
  };
  return map[sggCd] ?? sggCd;
}
