import { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

interface Props {
  title: string;
  subtitle?: string;
  // 뒤로가기 버튼 표시 여부 (기본 true — 상세 화면에서 사용)
  back?: boolean;
  right?: ReactNode;
}

// iOS 스타일 상단 네비 — 좌측 < 버튼, 중앙 타이틀, 우측 액션.
// 반투명 배경으로 스크롤 시 뒤 내용이 살짝 비침.
export default function NavBar({ title, subtitle, back = true, right }: Props) {
  const nav = useNavigate();
  return (
    <header className="sticky top-0 z-30 h-14
                      bg-gray-900/90 backdrop-blur-md border-b border-gray-800
                      flex items-center px-2 gap-2">
      {back ? (
        <button
          onClick={() => nav(-1)}
          className="w-10 h-10 flex items-center justify-center text-lg text-gray-300"
          aria-label="뒤로"
        >
          ‹
        </button>
      ) : (
        <div className="w-10" />
      )}
      <div className="flex-1 min-w-0 text-center">
        <div className="text-sm font-semibold truncate">{title}</div>
        {subtitle && <div className="text-[10px] text-gray-400 truncate">{subtitle}</div>}
      </div>
      <div className="w-10 flex items-center justify-center">{right}</div>
    </header>
  );
}
