import { useNavigate } from "react-router-dom";
import { useFavorites, type FavoriteItem } from "../lib/favorites";
import TerminalSection from "../components/TerminalSection";

// 관심 탭 — localStorage 의 fav + recent 표시. 카드별 ✕ 버튼으로 fav 해제,
// "최근 검색 비우기" 버튼으로 recent 일괄 삭제. 클릭 시 detail 페이지 이동.
export default function FavoriteScreen() {
  const nav = useNavigate();
  const { favorites, recents, toggleFavorite, clearRecents } = useFavorites();

  function go(item: FavoriteItem) {
    if (item.type === "sgg") nav(`/region/${item.code}`);
    else if (item.type === "stdg") nav(`/stdg/${item.code}`);
    else if (item.type === "apt" && item.sgg_cd) nav(`/complex/${item.code}?sgg_cd=${item.sgg_cd}`);
  }

  return (
    <div className="px-2 pt-2 pb-6 font-mono space-y-2">
      <TerminalSection
        title={`관심 지역 · ${favorites.length}건`}
        right={favorites.length > 0 ? "♥" : "비어있음"}
        dense
      >
        {favorites.length === 0 ? (
          <div className="text-center text-term-dim text-[11px] py-6">
            · 시군구·법정동 카드의 ♡ 를 눌러 관심에 추가
          </div>
        ) : (
          <ul className="divide-y divide-term-border">
            {favorites.map((f) => (
              <Row key={`fav:${f.type}:${f.code}`} item={f} onTap={go}
                onRemove={() => toggleFavorite({ type: f.type, code: f.code, name: f.name, sgg_cd: f.sgg_cd, sgg_nm: f.sgg_nm })} />
            ))}
          </ul>
        )}
      </TerminalSection>

      <TerminalSection
        title={`최근 검색 · ${recents.length}건`}
        right={recents.length > 0 ? <button onClick={clearRecents} className="hover:text-term-orange">비우기</button> : "비어있음"}
        dense
      >
        {recents.length === 0 ? (
          <div className="text-center text-term-dim text-[11px] py-6">
            · 검색 탭에서 결과 클릭 시 자동 적재
          </div>
        ) : (
          <ul className="divide-y divide-term-border">
            {recents.map((r) => (
              <Row key={`rc:${r.type}:${r.code}`} item={r} onTap={go} />
            ))}
          </ul>
        )}
      </TerminalSection>
    </div>
  );
}

function Row({ item, onTap, onRemove }: {
  item: FavoriteItem;
  onTap: (i: FavoriteItem) => void;
  onRemove?: () => void;
}) {
  const tagColor = item.type === "sgg" ? "text-term-orange border-term-orange"
                 : item.type === "stdg" ? "text-term-amber border-term-amber/60"
                 : "text-term-green border-term-green/60";
  const tagLabel = item.type === "sgg" ? "시군구" : item.type === "stdg" ? "법정동" : "단지";
  return (
    <li className="flex items-center gap-2 py-2 px-1">
      <span className={`text-[9px] tracking-widest font-bold w-9 text-center px-1 py-0.5 border ${tagColor}`}>
        {tagLabel}
      </span>
      <div className="flex-1 min-w-0 cursor-pointer" onClick={() => onTap(item)}>
        <div className="text-[12px] text-term-text font-bold truncate">{item.name}</div>
        {item.sgg_nm && (
          <div className="text-[10px] text-term-dim truncate">{item.sgg_nm}</div>
        )}
      </div>
      <span className="text-[9px] text-term-dim font-mono mr-1">{item.code}</span>
      {onRemove && (
        <button
          onClick={onRemove}
          aria-label="관심 해제"
          className="text-term-dim hover:text-term-up text-sm leading-none px-1"
        >
          ✕
        </button>
      )}
    </li>
  );
}
