import type { ReactNode } from "react";

// 블룸버그 터미널 식 섹션 헤더 — 오렌지 라인 + 대문자 제목 + 우측 슬롯 (날짜·메타).
// 본문 children 은 검정 패널 위에 mono 폰트로 렌더.
interface Props {
  title: string;
  right?: ReactNode;
  children?: ReactNode;
  className?: string;
  dense?: boolean;  // 패딩 작게 (지도 위 floating 패널 등)
}

export default function TerminalSection({ title, right, children, className = "", dense = false }: Props) {
  return (
    <section className={`bg-term-panel border border-term-border ${className}`}>
      {/* 헤더 줄 — 오렌지 ▓ + 제목 (대문자) + 우측 메타 */}
      <header className="flex items-center justify-between px-2 py-1 border-b border-term-border bg-black/40">
        <div className="flex items-center gap-2 text-[10px] tracking-widest font-mono uppercase">
          <span className="text-term-orange">▓</span>
          <span className="text-term-orange font-bold">{title}</span>
        </div>
        {right && (
          <div className="text-[10px] text-term-dim font-mono uppercase tracking-wider">
            {right}
          </div>
        )}
      </header>
      {/* 본문 — dense 면 패딩 작게 */}
      {children && (
        <div className={dense ? "px-2 py-1.5" : "px-3 py-2.5"}>
          {children}
        </div>
      )}
    </section>
  );
}
