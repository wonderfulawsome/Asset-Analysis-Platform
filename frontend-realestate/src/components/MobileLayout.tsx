import { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";

interface Props {
  children: ReactNode;
}

type Tab = { id: string; label: string; icon: string; path: string };

const TABS: Tab[] = [
  { id: "map",      label: "지도",   icon: "🗺️", path: "/" },
  { id: "search",   label: "검색",   icon: "🔍", path: "/search" },
  { id: "favorite", label: "찜",     icon: "❤", path: "/favorite" },
  { id: "ranking",  label: "랭킹",   icon: "🏆", path: "/ranking" },
];

// 폰 프레임 래퍼. 데스크톱에서는 가운데 정렬된 428px 컨테이너,
// 모바일에서는 전체 화면. 하단 탭바는 경로와 무관하게 고정 노출.
export default function MobileLayout({ children }: Props) {
  const nav = useNavigate();
  const { pathname } = useLocation();
  const activeId =
    pathname === "/" ? "map"
    : pathname.startsWith("/search") ? "search"
    : pathname.startsWith("/favorite") ? "favorite"
    : pathname.startsWith("/ranking") ? "ranking"
    : "map"; // /region, /complex 는 지도 탭의 하위 화면으로 간주

  return (
    <div className="min-h-screen w-full flex justify-center bg-black">
      {/* 폰 프레임 — 데스크톱에서 428px 고정, 모바일(max-w-none)에서 풀 */}
      <div className="relative w-full max-w-[428px] bg-gray-900 text-gray-100
                      min-h-screen flex flex-col overflow-hidden shadow-2xl">
        {/* 상단 safe area (노치 시뮬) */}
        <div className="h-[env(safe-area-inset-top)] shrink-0" />

        {/* 화면 콘텐츠 — 탭바 높이(64px)만큼 아래 padding */}
        <main className="flex-1 relative pb-16 overflow-y-auto">{children}</main>

        {/* 하단 탭바 — 고정 */}
        <nav className="absolute bottom-0 left-0 right-0 h-16
                        bg-gray-950/95 backdrop-blur border-t border-gray-800
                        flex justify-around items-center pb-[env(safe-area-inset-bottom)]">
          {TABS.map((t) => {
            const isActive = t.id === activeId;
            return (
              <button
                key={t.id}
                onClick={() => nav(t.path)}
                className={`flex flex-col items-center justify-center flex-1 h-full gap-0.5
                            ${isActive ? "text-blue-400" : "text-gray-500"}`}
              >
                <span className="text-xl leading-none">{t.icon}</span>
                <span className="text-[10px] font-medium">{t.label}</span>
              </button>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
