XGBoost 폭락/급등 전조 탐지. SPY + 8 FRED + 4 Yahoo + 5 CBOE 데이터에서 44개 피처를 생성하고, XGBClassifier(3-class)를 Optuna 50회 튜닝으로 학습. Platt Scaling 보정 후 백분위 점수(0-100) 산출. SHAP 피처 중요도 분석. Step 3의 FRED 캐시를 재사용.
