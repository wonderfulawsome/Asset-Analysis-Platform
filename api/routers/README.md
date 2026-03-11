### 이 폴더가 하는 역할 (routers)
외부 http 요청을 받아(사용자의 브라우저 접속 -> index.html -> main.js -> 4개의 API에 요청(/api/index/latest 라는 url 이름으로 main.js가 fastapi에 요청을 보내고 app.py가 받아 경로를 나눠주어 각 파일에 요청을 보내고 fastapi가 함수를 실행한뒤 결과값을 json 응답을 main.js에 돌려줌)) 적절한 DB 조회 함수를 호추랗고 결과 JSON으로 반환하는 FastAPI 라우터 엔드포인트들을 정의하는 폴더

라우터 = URL 경로를 함수에 연결하는 규칙
엔드포인트 = 요청을 받을 수 있는 특정 URL 주소

라우터 엔드포인트: 요청을 받고 응답을 보내는 쪽

### 주요 파일 설명
index_feed.py [/api/index/latest]: 최신 ETF가격/등락률 조회

macro.py [/api/macro/latest, /api/macro/fear-greed]: 거시경제 지표, Fear & Greed 지수 조회

regime.py [/api/regime/current, /api/regime/history]: 노이즈 vs 시그널 국면 현재/이력 조회

sector_cycle.py [/api/sector-cycle/current, /api/sector-cycle/holdings, /api/sector-cycle/history]: 경기국면, 보유종목 성과, 이력 조회

### 파일 간 연결
app.py (FastAPI 메인) (경로를 나눔) (main.js가 app.py로 저 경로들을 보내고 그걸 보고 app.py가 경로에 따라 파일로 요청을 분배)
/api/regime -> regime.py
/api/macro -> macro.py
/api/index -> index_feed.py
/api/sector-cycle -> sector_cycle.py

### 관련 함수/로직
모든 라우터는 database/repositories.py의 함수를 import 하여 호출 (repositories.py에 함수들이 코딩되어있음)

index_feed.py:	fetch_index_prices_latest()
macro.py:	fetch_macro_latest(), fetch_fear_greed_latest()
regime.py:	fetch_regime_current_all(), fetch_regime_history()
sector_cycle.py:	fetch_sector_cycle_latest(), get_holdings_perf(), get_history()

### 데이터 흐름
1. 프론트엔드에서 fetch()로 API 호출
2. 라우터가 요청을 받아 repositories.py DB 조회 함수 발생
3. Supabase에서 데이터를 가져와 dict/list로 반환
4. FastAPI가 자동으로 JSON 변환하여 응답
5. 프론트엔드가 JSON을 받아 화면에 표시