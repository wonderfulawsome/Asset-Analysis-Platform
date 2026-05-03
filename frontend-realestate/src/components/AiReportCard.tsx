interface Props {
  sggCd: string;
}

// LLM 해설 카드 — /api/real-estate/report 폴링 + 로딩·에러 상태 처리.
export default function AiReportCard({ sggCd }: Props) {
  // TODO: fetch + 스켈레톤 로더 + 에러 retry
  return <div className="rounded-xl bg-term-panel p-4" />;
}
