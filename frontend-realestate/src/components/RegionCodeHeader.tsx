import { useNavigate } from "react-router-dom";
import { useFavorites, type FavoriteItem } from "../lib/favorites";

// 모킹 2 의 상단 ASCII 식 헤더 — `RGN 41610141 · 부천시오정구 · 역곡동` 코드+이름 라인.
// 좌측 ◄ back, 우측 ♡ 관심 토글 (선택) + 페이지 메타.
interface Props {
  code: string;            // sgg_cd 또는 stdg_cd
  parts: (string | null | undefined)[];   // [sgg_nm, stdg_nm] 등 — null/empty 자동 필터
  right?: string;          // 우측 메타 (예: "상세 요약")
  back?: boolean;          // 뒤로가기 ◄ 표시
  fav?: Omit<FavoriteItem, "addedAt">;    // 지정 시 ♡ 토글 표시
}

export default function RegionCodeHeader({ code, parts, right = "상세 요약", back = true, fav }: Props) {
  const nav = useNavigate();
  const { isFavorite, toggleFavorite } = useFavorites();
  const isFav = fav ? isFavorite(fav.type, fav.code) : false;
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
      {fav && (
        <button
          onClick={() => toggleFavorite(fav)}
          aria-label={isFav ? "관심 해제" : "관심 추가"}
          className={`text-sm leading-none px-1 shrink-0 ${isFav ? "text-term-up" : "text-term-dim hover:text-term-up"}`}
        >
          {isFav ? "♥" : "♡"}
        </button>
      )}
      <span className="text-[9px] text-term-dim font-mono tracking-widest shrink-0">
        {right}
      </span>
    </header>
  );
}
