import type { ReactNode } from "react";

// 한 가지 metric — 위 LABEL (uppercase dim mono) + 아래 VALUE (large bold mono).
// 옵션 delta (작게 우측), unit (작게 뒤). FeatureCard / RegionDetail / ScoreBox 공용.
interface Props {
  label: string;
  value: ReactNode;            // 숫자 또는 "—" / 로딩 spinner
  delta?: string | null;       // "+2.4%" 같은 보조 변화량
  unit?: string;               // "건" "만/평"
  valueColor?: string;         // hex 또는 tailwind 클래스에 안 맞을 때
  valueClass?: string;         // tailwind 색 (text-term-up 등)
  large?: boolean;             // ScoreBox 처럼 큰 메트릭
}

export default function TerminalMetric({
  label, value, delta, unit, valueColor, valueClass, large = false,
}: Props) {
  return (
    <div className="bg-black/40 border border-term-border px-2 py-1.5">
      <div className="text-[9px] text-term-dim uppercase tracking-widest mb-0.5">{label}</div>
      <div
        className={`font-bold font-mono ${large ? "text-2xl" : "text-base"} ${valueClass ?? ""}`}
        style={valueColor ? { color: valueColor } : undefined}
      >
        {value}
        {unit && <span className="text-[9px] text-term-dim ml-0.5 font-normal">{unit}</span>}
        {delta && <span className="ml-1 text-[10px] font-normal">{delta}</span>}
      </div>
    </div>
  );
}
