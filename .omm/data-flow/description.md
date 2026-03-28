시스템 전체 데이터 흐름. 5개 외부 소스(Yahoo, FRED, CNN, CBOE, Shiller)에서 원시 데이터를 수집하고, 수집기가 피처를 계산하여 Supabase에 저장한다. 처리기가 ML 모델을 학습하고 예측 결과를 DB에 저장하면, API 레이어가 DB를 조회하여 프론트엔드에 JSON으로 제공한다.
