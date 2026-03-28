패시브 투자 비서 시스템의 전체 아키텍처. FastAPI 기반 웹 서버가 프론트엔드 HTML/JS를 서빙하고, APScheduler가 10분/3시간 주기로 데이터 수집·ML 모델 학습·예측을 수행한다. 수집된 데이터와 예측 결과는 Supabase PostgreSQL에 저장되며, REST API를 통해 프론트엔드에 제공된다.
