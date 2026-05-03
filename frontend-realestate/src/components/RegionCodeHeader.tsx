import { useNavigate } from "react-router-dom";

// 모킹 2 의 상단 ASCII 식 헤더 — `RGN 41610141 · 부천시오정구 · 역곡동` 코드+이름 라인.
// 좌측 ◄ back, 우측 페이지 탭 (DETAIL / SUMMARY / FEAT).
interface Props {
  code: string;            // sgg_cd 또는 stdg_cd
  parts: (string | null | undefined)[];   // [sgg_nm, stdg_nm] 등 — null/empty 자동 필터
  right?: string;          // 우측 메타 (예: "DETAIL-SUMMARY")
  back?: boolean;          // 뒤로가기 ◄ 표시
}

export default function RegionCodeHeader({ code, parts, right = "상세 요약", back = true }: Props) {
  const nav = useNavigate();
  const cleanParts = parts.filter((x): x is string => !!x && x.length > 0);
  return (
    <header className="flex items-center px-2 py-1.5 border-b border-term-border bg-black gap-2">
      {back && (
        <button
          type="button"
          onClick={() => nav(-1)}
          className="text-term-dim hover:text-term-orange text-sm font-bold leading-none"
          aria-label="back"
        >
          ◄
        </button>
      )}
      <span className="text-[10px] tracking-widest font-bold font-mono text-term-orange uppercase">
        ▓ 시군구 {code}
      </span>
      <span className="text-[10px] font-mono text-term-dim">·</span>
      <span className="text-[11px] font-mono text-term-text truncate flex-1">
        {cleanParts.join(" · ")}
      </span>
      <span className="text-[9px] text-term-dim font-mono tracking-widest shrink-0">
        {right}
      </span>
    </header>
  );
}
