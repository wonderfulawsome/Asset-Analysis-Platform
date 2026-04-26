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
// 축 라벨(시작·끝 월, min·max 값)만 간단히 붙임.
export default function TimeSeriesChart({
  data, label, format = (n) => n.toLocaleString(), color = "#3b82f6",
}: Props) {
  const valid = data.filter((d): d is { date: string; value: number } => d.value != null);
  if (valid.length < 2) {
    return (
      <div className="rounded-xl bg-gray-800/50 p-3">
        <div className="text-xs text-gray-400 mb-1">{label}</div>
        <div className="h-28 flex items-center justify-center text-[11px] text-gray-500">
          {valid.length === 1 ? `단일 월 (${format(valid[0].value)})` : "데이터 없음"}
        </div>
      </div>
    );
  }

  const W = 340, H = 120, PAD_X = 6, PAD_Y = 18;
  const values = valid.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, Math.abs(max) * 0.05 || 1);  // 변화가 0이면 5% 여백

  const points = valid.map((d, i) => {
    const x = PAD_X + ((W - 2 * PAD_X) * i) / (valid.length - 1);
    const y = H - PAD_Y - ((H - 2 * PAD_Y) * (d.value - min)) / range;
    return { x, y, ...d };
  });
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  // 하단 fill용 area path — 선 아래쪽에 투명한 색 채워 depth 표현
  const area = `${path} L${points[points.length - 1].x},${H - PAD_Y} L${points[0].x},${H - PAD_Y} Z`;

  const fmtYm = (ym: string) =>
    ym.length === 6 ? `${ym.slice(2, 4)}.${ym.slice(4)}` : ym;

  return (
    <div className="rounded-xl bg-gray-800/50 p-3">
      <div className="flex items-baseline justify-between mb-1">
        <div className="text-xs text-gray-400">{label}</div>
        <div className="text-[11px] text-gray-500">
          {fmtYm(valid[0].date)} → {fmtYm(valid[valid.length - 1].date)}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-28">
        <path d={area} fill={color} opacity="0.15" />
        <path d={path} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
        {points.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="2.5" fill={color} />
        ))}
      </svg>
      <div className="flex justify-between text-[10px] text-gray-500 mt-1">
        <span>최소 {format(min)}</span>
        <span className="text-gray-300 font-semibold">
          최근 {format(values[values.length - 1])}
        </span>
        <span>최대 {format(max)}</span>
      </div>
    </div>
  );
}
