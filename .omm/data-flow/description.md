전체 데이터 흐름. 5개 외부 소스(Yahoo, FRED, Shiller, CNN, CBOE) → 7개 수집 모듈(collector/) → 4개 처리 모듈(processor/) → Supabase 10개 테이블 → 8개 API 엔드포인트 → 프론트엔드 대시보드. FRED 캐시(pkl)로 경량 파이프라인 최적화.
