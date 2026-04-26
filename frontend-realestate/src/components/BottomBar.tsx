import { changePctColor, formatPriceMan } from "../lib/color";

interface SelectedRegion {
  sggCd: string;
  sggNm: string;
  topStdgNm: string | null;
  topStdgCd: string | null;
  medianPricePerPy: number | null;
  changePct: number | null;
}

interface Props {
  selected: SelectedRegion | null;
  onTap: (stdgCd: string) => void;
}

// 폴리곤 클릭 → 하단 슬라이드인. 탭하면 법정동 상세 페이지로 이동.
// MobileLayout 의 64px 탭바 위에 위치하도록 bottom calc.
export default function BottomBar({ selected, onTap }: Props) {
  const visible = selected != null;
  const disabled = !selected?.topStdgCd;
  const change = selected?.changePct ?? null;

  return (
    <div
      className={`absolute left-0 right-0 z-20
                  bottom-[calc(64px+env(safe-area-inset-bottom))]
                  px-3 transition-transform duration-300
                  ${visible ? "translate-y-0" : "translate-y-[150%]"}`}
    >
      <button
        disabled={disabled}
        onClick={() => selected?.topStdgCd && onTap(selected.topStdgCd)}
        className="w-full bg-gray-900/95 backdrop-blur-md ring-1 ring-gray-700
                   rounded-2xl shadow-xl px-4 py-3 flex items-center gap-3
                   active:bg-gray-800 transition disabled:opacity-50"
      >
        <div className="flex-1 min-w-0 text-left">
          <div className="text-sm font-semibold truncate">
            {selected?.sggNm}
            {selected?.topStdgNm && (
              <span className="text-gray-400 ml-1">· {selected.topStdgNm}</span>
            )}
          </div>
          <div className="text-[11px] text-gray-400 mt-0.5">
            {selected?.medianPricePerPy != null
              ? `평단가 ${formatPriceMan(selected.medianPricePerPy)}`
              : "데이터 없음"}
          </div>
        </div>
        {change != null && (
          <span
            className="text-xs font-semibold px-2 py-1 rounded-full shrink-0"
            style={{
              backgroundColor: changePctColor(change) + "33",
              color: changePctColor(change),
            }}
          >
            {change >= 0 ? "+" : ""}
            {change.toFixed(1)}%
          </span>
        )}
        <span className="text-gray-400 text-lg">›</span>
      </button>
    </div>
  );
}
