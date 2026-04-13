차트 데이터 API (/api/chart). /ohlc?ticker=SPY&interval=1d로 OHLCV 캔들 데이터 제공, /predict?ticker=SPY로 5모델 앙상블 30일 예측 결과 제공. 예측 데이터가 없으면 백그라운드 스레드로 재생성 후 최대 120초 폴링 대기. _sanitize_floats로 NaN/Inf 방어.
