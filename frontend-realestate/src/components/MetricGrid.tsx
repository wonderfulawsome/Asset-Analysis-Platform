interface Metric {
  label: string;
  value: string | number;
  unit?: string;
}

interface Props {
  metrics: Metric[];
}

// 평균가·평단가·거래량 등 숫자 지표를 격자 형태로 표시.
export default function MetricGrid({ metrics }: Props) {
  return (
    <div className="grid grid-cols-2 gap-3 p-4">
      {metrics.map((m) => (
        <div key={m.label} className="rounded-lg bg-gray-50 p-3">
          <p className="text-xs text-gray-500">{m.label}</p>
          <p className="text-lg font-semibold">
            {m.value}
            {m.unit && <span className="text-sm font-normal text-gray-400"> {m.unit}</span>}
          </p>
        </div>
      ))}
    </div>
  );
}
