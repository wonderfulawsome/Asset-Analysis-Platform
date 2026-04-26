// 변화율 → 색상 매핑. 폴리곤 fillColor·BottomBar 배지·상세페이지 헤더 동시에 사용.
export function changePctColor(pct: number | null | undefined): string {
  if (pct == null) return "#374151"; // 데이터 없음 — 회색
  if (pct >= 5) return "#dc2626";    // 진빨강 +5% 이상
  if (pct >= 1) return "#f87171";    // 빨강 +1~5%
  if (pct >= -1) return "#9ca3af";   // 보합 (±1% 이내)
  if (pct >= -5) return "#60a5fa";   // 파랑 -1~-5%
  return "#2563eb";                  // 진파랑 -5% 이하
}

// 부호 따른 텍스트 색상 (밝은 톤 — 어두운 배경에 가독성)
export function changePctTextColor(pct: number | null | undefined): string {
  if (pct == null) return "text-gray-400";
  if (pct > 0) return "text-red-300";
  if (pct < 0) return "text-blue-300";
  return "text-gray-400";
}

// 매매가 표기: ≥10000만원 → "X.X억", 아니면 "X,XXX만"
export function formatPrice(man: number | null | undefined): string {
  if (man == null) return "-";
  if (man >= 10000) return `${(man / 10000).toFixed(1)}억`;
  return `${Math.round(man).toLocaleString()}만`;
}

// 평단가도 동일 포맷터 사용
export const formatPriceMan = formatPrice;
