// 작은 strip 차트 — RegionDetail 의 W/PY · MONTHLY VOL · JEONSE RATE 3종 row 용.
// TimeSeriesChart 와 별개 (라벨 없음, 높이 작음, 단일 색).
interface DataPoint {
  date: string;
  value: number | null;
}
interface Props {
  data: DataPoint[];
  color?: string;
  height?: number;
}

export default function MiniChart({ data, color = "#ff8800", height = 36 }: Props) {
  const valid = data.filter((d): d is { date: string; value: number } => d.value != null);
  if (valid.length < 2) {
    return <div style={{ height }} className="bg-black/40 border border-term-border" />;
  }
  const W = 100, H = height;
  const values = valid.map((d) => d.value);
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  const range = Math.max(dataMax - dataMin, Math.abs(dataMax) * 0.05 || 1);
  const yMin = dataMin - range * 0.1;
  const yRange = range * 1.2;
  const path = valid.map((d, i) => {
    const x = (W * i) / (valid.length - 1);
    const y = H - (H * (d.value - yMin)) / yRange;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}>
      <path d={path} fill="none" stroke={color} strokeWidth="1.2" />
    </svg>
  );
}
