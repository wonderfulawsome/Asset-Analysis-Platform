Yahoo Finance에서 S&P500, VIX, 10Y 금리, 3M 금리, Nasdaq 100, 반도체 지수를 수집. RSI(14), SMA(50/200), 5일 모멘텀 등 파생 피처 계산. 타임아웃 시 lookback을 100y→50y→30y로 축소하는 fallback 포함. 결과는 macro_raw 테이블에 저장.
