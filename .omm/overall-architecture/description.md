6-레이어 아키텍처. 프론트엔드(Vanilla JS) → API(FastAPI) → DB(Supabase) 경로로 사용자 요청을 처리하고, 스케줄러(APScheduler)가 수집(collector) → 처리(processor) → DB 경로로 데이터 파이프라인을 주기적으로 실행한다. 모델은 pkl 파일로 models/에 저장.
