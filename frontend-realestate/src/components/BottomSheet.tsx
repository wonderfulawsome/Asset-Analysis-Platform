import { ReactNode } from "react";

type SnapLevel = "hidden" | "half" | "full";

interface Props {
  snap: SnapLevel;
  onSnapChange: (level: SnapLevel) => void;
  children: ReactNode;
}

// 3단 스냅 바텀시트 — hidden / half / full.
// 터치 제스처는 추후 framer-motion 으로 추가. 현재는 헤더 클릭으로 전환.
const TRANSLATE: Record<SnapLevel, string> = {
  hidden: "translate-y-full",
  half: "translate-y-[50%]",
  full: "translate-y-0",
};

export default function BottomSheet({ snap, onSnapChange, children }: Props) {
  const next: Record<SnapLevel, SnapLevel> = {
    hidden: "half",
    half: "full",
    full: "hidden",
  };
  return (
    <div
      className={`fixed bottom-0 left-0 right-0 h-[90vh] bg-white rounded-t-2xl shadow-2xl
                  transform transition-transform duration-300 ${TRANSLATE[snap]}`}
    >
      {/* 헤더 (드래그 핸들 겸 토글 버튼) */}
      <button
        onClick={() => onSnapChange(next[snap])}
        className="w-full flex justify-center py-2"
        aria-label="바텀시트 전환"
      >
        <span className="block h-1 w-10 rounded-full bg-gray-300" />
      </button>
      <div className="overflow-y-auto h-[calc(90vh-2rem)]">{children}</div>
    </div>
  );
}
