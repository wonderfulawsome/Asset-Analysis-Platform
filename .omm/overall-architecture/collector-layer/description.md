외부 데이터 수집 레이어. 7개 모듈이 Yahoo Finance, FRED, CNN, CBOE, Shiller 등에서 시장 데이터를 수집한다. 각 모듈은 exponential backoff 재시도, 경량/전체 모드 분기, FRED 캐시 재사용 등을 지원한다.
