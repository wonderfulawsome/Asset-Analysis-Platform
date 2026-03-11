# ================================ 폴더 역할
외부 데이터 소소에서 시장 데이터를 수집하고 전처리하는 폴더, scheduler/job.py의 파이프라인에서 3시간마다 자동 호출됨.

# ================================ 파일 설명
market_data.py: 야후 파이낸스 API로 7개 거시지표를 수집하고 RSI 이격도 상대거래량 피처률 계산

index_price.py: 31개 ETF의 전일 대비 등략률을 야후 파이낸스 API로 수집

sector_etf.py 야후파이낸스 라이브러리로 섹터 ETF 10개 + 보유 종목 22개의 월별 수익률을 계산

sector_macro.py: FRED API로 8개 경제지표를 수집하고 PMI  변환등 파생 피처를 생성

noise_regime_data.py: shiller cape, fred, yfinance 에서 장기 데이터를 HMM용 8개 피처를 생성

# ================================ 파일 간 연결
scheduler/job.py (데이터 수집 함수 호출 파일) -> job.py는 스케줄러로서 파이프라인을 돌릴때 시작점 역할을 한다.

market_data.fetch_macro() -> processor/feature3_tail.py, feature4_crash.py 
    - (job.py에서 market_data파일에 있는  fetch_macro 함수를 실행하라고 시키고 그 결과 데이터를 feature3_tail.py와 feature4_crash.py로 보낸다)

market_data.to_macro_records() -> database/repository.py 
    - job.py에서 market_data 파일에 있는 to_macro_records() 함수를 실행하라고 호출하고 그 결과 데이터를 datasbase폴더의 repository.py로 보냄

index_price.fetch_index_prices() → database/repositories.py (Supabase 저장)

sector_etf.fetch_sector_etf_returns() → processor/feature2_sector_cycle.py

sector_macro.fetch_sector_macro()     → processor/feature2_sector_cycle.py

fear_greed.fetch_fear_greed()         → database/repositories.py (Supabase 저장)

noise_regime_data.fetch_noise_regime_data() → processor/feature1_regime.py

- collector 끼리는 직접 import 하지는 않음
- 모든 함수는 scheduler/job.py가 순서대로 호출
- 수집 결과는 DataFrame 또는 dict/list로 반환 -> processor 또는 DB로 전달

# ================================ 주요 함수/로직
    market_dat.py
        - _rsi(series, period=14): RSI 계산(상승평균/하락평균 비율)
        - _fetch_df(ticker, from_ts, to_ts): Yahoo v8 API로 증가 + 거래량 DataFrame 반환
        - fetch_macro(): 7개 티커수집->S&P500/NDX/SOX 피처(수익률·이격도·RSI·상대거래량) + 거시지표(VIX·금리·금리차·달러) 계산
        - to_macro_records(df): DataFrame -> Supabase upsert 용 dict 리스트 변환

    index_price.py
        - fetch_index_prices() — 31개 ETF의 최근 10일 종가를 Yahoo API로 수집, 전일 대비 등락률(%) 계산

    sector_etf.py
        - fetch_sector_etf_returns(macro_start, etf_start) — 32개 ETF 종가를 yfinance로 다운로드 → 월초 리샘플링 → 월별 수익률 → 섹터/보유 분리 반환

    sector_macro.py
        - _fetch_fred(series_id, start, retries=4) — FRED CSV 다운로드 (지수 백오프 재시도)
        - fetch_sector_macro(start) — 8개 FRED 지표 수집 → PMI 변환(INDPRO z-score × 10 + 50) + YoY% + 파생 피처 생성
        - to_sector_macro_records(df) — DataFrame → Supabase upsert용 dict 리스트

    fear_greed.py
        - fetch_fear_greed() — CNN API 호출 (Chrome 위장) → 점수 + 한글 등급 반환
    
    noise_regime_data.py
        - fetch_noise_regime_data() — Shiller CAPE + FRED(금리·실업률·CPI) + yfinance(S&P500·금) 수집 → 8개 월별 피처(CAPE·금리차·실업률변화·CPI YoY·S&P 모멘텀·변동성·금수익률·밸류에이션) 생성

# ================================ 데이터 흐름 # ================================
외부 API                    collector 함수              출력 형태
─────────                   ──────────────              ─────────
Yahoo Finance v8 API   →  market_data.fetch_macro()   → DataFrame (16개 피처 컬럼)
Yahoo Finance v8 API   →  index_price.fetch_index_prices() → list[dict] (종가+등락률)
yfinance 라이브러리     →  sector_etf.fetch_sector_etf_returns() → (DataFrame, DataFrame) 튜플
FRED CSV API           →  sector_macro.fetch_sector_macro() → DataFrame (경제지표+파생피처)
CNN Fear & Greed API   →  fear_greed.fetch_fear_greed() → dict (점수+등급)
Shiller/FRED/yfinance  →  noise_regime_data.fetch_noise_regime_data() → DataFrame (8개 월별 피처)

# ================================ 왜 이 구조를 쓰는지
파일별 1개 API 소스 분리: market_data.py는 Yahoo, sector_macro.py는 FRED, fear_greed.py는 CNN만 담당. 한 파일이 하나의 외부 소스만 책임지므로 API가 바뀌어도 해당 파일만 수정하면 됨 -> 유지/보수의 유리

collector끼리 import 없음: 각 파일이 독립적이라 하나가 고장나도 나머지에 영향 없음 -> 유지/보수에 유리

수집과 변환을 같은 파일에 배치: fetch_macro()와 to_macro_records()가 같은 market_data.py에 있음. 수집한 데이터의 컬럼 구조를 가장 잘 아는 곳에서 변환까지 처리 -> market_data.py: 수집 및 전처리

티커 목록을 상수로 파일 상단에 정의: SECTOR_ETFS, ALL_HOLDINGS, TICKERS, SYMBOLS 등을 파일 맨 위에 놓아서 어떤 데이터를 수집하는지 파일 열자마자 바로 확인 가능 -> 한눈에 파악 가능

개별 티커 순회 + try/except: for문으로 하나씩 수집하고 실패 시 continue. 하나가 실패해도 나머지는 계속 수집 가능 -> 개별로 수집을 하기때문에, 오류없이 실행가능

### 현재 구조의 한계
중복 티커 정의: SOXX가 sector_etf.py와 index_price.py에 각각 하드코딩됨. 티커를 추가/제거할 때 여러 파일을 수동으로 맞춰야 함

에러 처리 불균일: sector_macro.py만 재시도(retry) 로직이 있고, 나머지는 try/except + print만 함. 파일마다 에러 처리 수준이 다름
반환 타입 불통일: fetch_macro()는 DataFrame, fetch_index_prices()는 list[dict], fetch_fear_greed()는 dict. 호출하는 job.py가 각각의 반환 타입을 알고 있어야 함

로깅이 print문: 파일별로 print(f'[SectorETF]...'), print(f'[IndexPrice]...') 형식이 제각각. 통합 로그 관리가 안 됨

noise_regime_data.py의 역할이 애매: 수집 + 피처 엔지니어링을 한 파일에서 함. 다른 파일은 수집만 하고 피처 계산은 processor에서 하는데, 이 파일만 예외