interface Point {
  date: string;       // YYYYMM
  value: number | null;
}

export interface Series {
  label: string;
  color: string;
  data: Point[];
}

interface Props {
  title: string;
  series: Series[];
  format?: (n: number) => string;
}

// 2~4개 시리즈를 같은 좌표계에 overlay 라인으로 그림 — 단지 비교 전용.
// TimeSeriesChart 와 같은 SVG 방식 (외부 차트 라이브러리 없음).
// 모든 시리즈의 date 합집합을 X 축으로, value 합집합으로 Y 축 정규화.
export default function MultiSeriesChart({
  title, series, format = (n) => n.toLocaleString(),
}: Props) {
  // X축: 모든 시리즈의 ym 합집합 (정렬)
  const allDates = Array.from(new Set(series.flatMap((s) => s.data.map((p) => p.date)))).sort();
  // Y축: 모든 valid value 의 min/max
  const allValues = series
    .flatMap((s) => s.data.map((p) => p.value))
    .filter((v): v is number => v != null);
  if (allValues.length < 2 || allDates.length < 2) {
    return (
      <div className="rounded-xl bg-gray-800/50 p-3">
        <div className="text-xs text-gray-400 mb-1">{title}</div>
        <div className="h-32 flex items-center justify-center text-[11px] text-gray-500">
          비교 가능한 데이터가 부족합니다.
        </div>
      </div>
    );
  }

  const W = 360, H = 160, PAD_X = 8, PAD_Y = 18;
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const range = Math.max(max - min, Math.abs(max) * 0.05 || 1);

  function pointToXY(date: string, value: number): { x: number; y: number } {
    const i = allDates.indexOf(date);
    const x = PAD_X + ((W - 2 * PAD_X) * i) / Math.max(allDates.length - 1, 1);
    const y = H - PAD_Y - ((H - 2 * PAD_Y) * (value - min)) / range;
    return { x, y };
  }

  const fmtYm = (ym: string) => (ym.length === 6 ? `${ym.slice(2, 4)}.${ym.slice(4)}` : ym);

  return (
    <div className="rounded-xl bg-gray-800/50 p-3">
      <div className="flex items-baseline justify-between mb-1">
        <div className="text-xs text-gray-400">{title}</div>
        <div className="text-[11px] text-gray-500">
          {fmtYm(allDates[0])} → {fmtYm(allDates[allDates.length - 1])}
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-36">
        {series.map((s, si) => {
          const valid = s.data.filter((p): p is { date: string; value: number } => p.value != null);
          if (valid.length < 2) return null;
          const points = valid.map((p) => pointToXY(p.date, p.value));
          const path = points.map((pt, i) => `${i === 0 ? "M" : "L"}${pt.x},${pt.y}`).join(" ");
          return (
            <g key={si}>
              <path d={path} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" />
              {points.map((pt, i) => (
                <circle key={i} cx={pt.x} cy={pt.y} r="2.5" fill={s.color} />
              ))}
            </g>
          );
        })}
      </svg>

      {/* 범례 + 최근값 */}
      <div className="flex flex-wrap gap-3 mt-2 text-[10px]">
        {series.map((s, si) => {
          const last = [...s.data].reverse().find((p) => p.value != null);
          return (
            <div key={si} className="flex items-center gap-1.5">
              <span className="inline-block w-3 h-3 rounded" style={{ backgroundColor: s.color }} />
              <span className="text-gray-300 font-medium truncate max-w-[120px]">{s.label}</span>
              <span className="text-gray-500">{last?.value != null ? format(last.value) : "-"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
