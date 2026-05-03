interface DataPoint {
  date: string;  // YYYYMM 또는 YYYY-MM
  value: number | null;
}

interface Props {
  data: DataPoint[];
  label: string;
  // 숫자 포맷 — 평단가면 "1.2억", 비율이면 "75%" 등 상황별.
  format?: (n: number) => string;
  color?: string;
}

// 외부 차트 라이브러리 없이 순수 SVG — recharts 의존을 피해 번들 크기 최소화.
// 축 라벨(시작·끝 월, min·max 값)만 간단히 붙임. 터미널 스타일 (검정 panel + 오렌지 색).
export default function TimeSeriesChart({
  data, label, format = (n) => n.toLocaleString(), color = "#ff8800",
}: Props) {
  const valid = data.filter((d): d is { date: string; value: number } => d.value != null);
  if (valid.length < 2) {
    return (
      <div className="bg-term-panel border border-term-border p-2">
        <div className="text-[10px] tracking-widest text-term-orange font-bold mb-1">
          ▓ {label}
        </div>
        <div className="h-24 flex items-center justify-center text-[11px] text-term-dim font-mono">
          {valid.length === 1 ? `· 단일 월 (${format(valid[0].value)})` : "· 데이터 없음"}
        </div>
      </div>
    );
  }

  const W = 340, H = 120, PAD_X = 6, PAD_Y = 18;
  const values = valid.map((d) => d.value);
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  // 점이 차트 상하단에 닿지 않도록 데이터 범위의 15% 패딩 추가 (양쪽).
  // 변화 0 일 때는 절대값의 5% 또는 1 을 최소 범위로.
  const dataRange = Math.max(dataMax - dataMin, Math.abs(dataMax) * 0.05 || 1);
  const padding = dataRange * 0.15;
  const yMin = dataMin - padding;
  const range = dataRange + padding * 2;

  const points = valid.map((d, i) => {
    const x = PAD_X + ((W - 2 * PAD_X) * i) / (valid.length - 1);
    const y = H - PAD_Y - ((H - 2 * PAD_Y) * (d.value - yMin)) / range;
    return { x, y, ...d };
  });
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  // 하단 fill용 area path — 선 아래쪽에 투명한 색 채워 depth 표현
  const area = `${path} L${points[points.length - 1].x},${H - PAD_Y} L${points[0].x},${H - PAD_Y} Z`;

  const fmtYm = (ym: string) =>
    ym.length === 6 ? `${ym.slice(2, 4)}.${ym.slice(4)}` : ym;

  return (
    <div className="bg-term-panel border border-term-border p-2 font-mono">
      <div className="flex items-baseline justify-between mb-1">
        <div className="text-[10px] tracking-widest text-term-orange font-bold">
          ▓ {label}
        </div>
        <div className="text-[9px] text-term-dim tracking-wider">
          {fmtYm(valid[0].date)} → {fmtYm(valid[valid.length - 1].date)}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-24">
        <path d={area} fill={color} opacity="0.18" />
        <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="miter" />
        {points.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="2" fill={color} />
        ))}
      </svg>
      <div className="flex justify-between text-[9px] text-term-dim mt-1 tracking-wider">
        <span>최저 {format(dataMin)}</span>
        <span className="text-term-text font-bold">
          최근 {format(values[values.length - 1])}
        </span>
        <span>최고 {format(dataMax)}</span>
      </div>
    </div>
  );
}
