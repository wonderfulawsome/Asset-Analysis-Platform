// 엔드포인트 URL 상수화 — 타이포 방지 + 변경 시 한 곳만 수정.
// 백엔드 api/routers/real_estate.py 와 1:1 대응.
export const ENDPOINTS = {
  summary:    (sggCd: string, ym?: string) => q(`/api/realestate/summary`, { sgg_cd: sggCd, ym }),
  timeseries: (sggCd: string) => q(`/api/realestate/timeseries`, { sgg_cd: sggCd }),
  trades:     (sggCd: string, ym?: string) => q(`/api/realestate/trades`, { sgg_cd: sggCd, ym }),
  rents:      (sggCd: string, ym?: string) => q(`/api/realestate/rents`, { sgg_cd: sggCd, ym }),
  population: (sggCd: string, ym?: string) => q(`/api/realestate/population`, { sgg_cd: sggCd, ym }),
  household:  (sggCd: string, ym?: string) => q(`/api/realestate/household`, { sgg_cd: sggCd, ym }),
  mapping:    (sggCd: string, refYm?: string) => q(`/api/realestate/mapping`, { sgg_cd: sggCd, ref_ym: refYm }),
  geo:        (sggCd: string) => q(`/api/realestate/geo`, { sgg_cd: sggCd }),
  buySignal:        (sggCd: string) => q(`/api/realestate/signal`, { sgg_cd: sggCd }),
  buySignalHistory: (sggCd: string) => q(`/api/realestate/signal/history`, { sgg_cd: sggCd }),
  sggOverview:      (ym?: string) => q(`/api/realestate/sgg-overview`, { ym }),
  stdgDetail:       (stdgCd: string, ym?: string) => q(`/api/realestate/stdg-detail`, { stdg_cd: stdgCd, ym }),
  complexCompare:   (aptSeqs: string[], months?: number) =>
    q(`/api/realestate/complex-compare`, { apt_seqs: aptSeqs.join(","), months: months?.toString() }),
} as const;

// undefined 파라미터는 URLSearchParams에서 "undefined" 문자열이 되므로 직접 걸러낸다.
function q(path: string, params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (entries.length === 0) return path;
  return `${path}?${new URLSearchParams(entries as [string, string][]).toString()}`;
}
