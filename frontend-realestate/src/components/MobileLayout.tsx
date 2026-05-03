import { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import TickerBar from "./TickerBar";

interface Props {
  children: ReactNode;
}

type Tab = { id: string; label: string; path: string; icon: (active: boolean) => JSX.Element };

// 모노크롬 라인 아이콘 — 16×16, currentColor stroke. 비활성/활성 동일 모양.
function IconMap(_active: boolean) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square">
      <path d="M3 6 9 4l6 2 6-2v14l-6 2-6-2-6 2V6z" />
      <path d="M9 4v16M15 6v16" />
    </svg>
  );
}
function IconSearch(_a: boolean) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}
function IconHeart(_a: boolean) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter">
      <path d="M12 21s-7-4.5-9-9.5a5 5 0 0 1 9-3 5 5 0 0 1 9 3c-2 5-9 9.5-9 9.5z" />
    </svg>
  );
}
function IconRanking(_a: boolean) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square">
      <path d="M4 20h4V10H4zM10 20h4V4h-4zM16 20h4v-7h-4z" />
    </svg>
  );
}

const TABS: Tab[] = [
  { id: "map",      label: "MAP",   path: "/",         icon: IconMap },
  { id: "search",   label: "SRCH",  path: "/search",   icon: IconSearch },
  { id: "favorite", label: "WTCH",  path: "/favorite", icon: IconHeart },
  { id: "ranking",  label: "RANK",  path: "/ranking",  icon: IconRanking },
];

export default function MobileLayout({ children }: Props) {
  const nav = useNavigate();
  const { pathname } = useLocation();
  const activeId =
    pathname === "/" ? "map"
    : pathname.startsWith("/search") ? "search"
    : pathname.startsWith("/favorite") ? "favorite"
    : pathname.startsWith("/ranking") ? "ranking"
    : "map";

  return (
    <div className="min-h-screen w-full flex justify-center bg-term-bg font-mono">
      {/* 폰 프레임 — 데스크톱 428px / 모바일 풀폭 */}
      <div className="relative w-full max-w-[428px] bg-term-bg text-term-text
                      min-h-screen flex flex-col overflow-hidden border-x border-term-border">
        {/* 상단 safe area (노치 시뮬) */}
        <div className="h-[env(safe-area-inset-top)] shrink-0" />

        {/* 라이브 ticker bar — 모든 화면 상단 */}
        <TickerBar />

        {/* 화면 콘텐츠 — 탭바 높이(56px)만큼 하단 padding */}
        <main className="flex-1 relative pb-14 overflow-y-auto">{children}</main>

        {/* 하단 탭바 — 터미널 스타일 (검정 + 오렌지 활성) */}
        <nav className="absolute bottom-0 left-0 right-0 h-14
                        bg-black border-t border-term-border
                        flex justify-around items-stretch
                        pb-[env(safe-area-inset-bottom)]">
          {TABS.map((t, i) => {
            const isActive = t.id === activeId;
            return (
              <button
                key={t.id}
                onClick={() => nav(t.path)}
                className={`relative flex flex-col items-center justify-center flex-1 gap-0.5
                            text-[10px] tracking-widest font-bold
                            ${isActive ? "text-term-orange" : "text-term-dim"}
                            ${i > 0 ? "border-l border-term-border" : ""}
                            hover:text-term-text transition-colors`}
              >
                {t.icon(isActive)}
                <span>{`${i + 1}·${t.label}`}</span>
                {isActive && (
                  <span className="absolute top-0 left-0 right-0 h-0.5 bg-term-orange" />
                )}
              </button>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
