APScheduler 기반 파이프라인 스케줄러. FastAPI lifespan에서 BackgroundScheduler를 시작하여 두 가지 파이프라인을 주기적으로 실행: 경량 파이프라인(10분 주기, 최근 데이터 갱신 + 실시간 예측)과 전체 파이프라인(3시간 주기, 100년치 수집 + 모델 학습). RUN_SCHEDULER 환경변수로 ON/OFF 제어.
