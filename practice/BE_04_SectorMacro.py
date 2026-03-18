# ============================================================
# BE_04_SectorMacro — FRED 8개 매크로 지표 수집 빈칸 연습
# 원본: collector/sector_macro.py
# 총 빈칸: 50개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

# Q1~Q5: 필요한 모듈 임포트
import ___                                              # Q1: 재시도 대기용 모듈
import ___                                              # Q2: HTTP 요청 라이브러리
import numpy as ___                                     # Q3: numpy 관례적 별칭
import pandas as ___                                    # Q4: pandas 관례적 별칭
from io import ___                                      # Q5: 문자열을 파일처럼 읽는 클래스

##########################
import time
import requests
import numpy as np
import pandas as pd
from io import StringP #문자열을 파일처럼 읽는 클래스
################################

# Q6: FRED CSV 다운로드 기본 URL
FRED_BASE = '___'                                       # Q6: FRED CSV 다운로드 전체 URL (시리즈 ID 앞부분)
HEADERS   = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
################
FRED_BASE = '' # FRED CSV 다운로드 전체 URL

# Q7~Q14: FRED 시리즈 ID → 컬럼명 매핑
FRED_SERIES = {
    '___':  'indpro',                                   # Q7: 산업생산지수 FRED 시리즈 ID
    '___':  'yield_spread',                             # Q8: 장단기 금리차 FRED 시리즈 ID (10년-3개월)
    '___':   'anfci',                                   # Q9: 시카고 연준 금융상황지수 시리즈 ID
    '___':    'icsa',                                   # Q10: 신규 실업수당 청구건수 시리즈 ID
    '___':  'permit',                                   # Q11: 건축허가건수 시리즈 ID
    '___':   'real_retail',                             # Q12: 실질 소매판매 시리즈 ID
    '___':  'capex_orders',                             # Q13: 비국방 자본재 주문 시리즈 ID
    '___': 'real_income',                               # Q14: 실질 개인소득(이전지출 제외) 시리즈 ID
}

def _fetch_fred(series_id: str, col_name: str, retries: int = ___, timeout: int = ___) -> pd.DataFrame:  # Q15~Q16: 재시도 횟수 기본값, 요청 제한시간(초) 기본값
    """FRED CSV 다운로드 (지수 백오프 재시도)"""
    url = FRED_BASE + ___                               # Q17: URL에 이어붙일 시리즈 ID 매개변수
    for attempt in range(___):                          # Q18: 최대 재시도 횟수만큼 반복할 변수
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            df = pd.___(StringIO(resp.text), index_col=0, parse_dates=True)  # Q19: CSV 텍스트를 DataFrame으로 읽는 pandas 함수
            df.columns = [___]                          # Q20: 컬럼명을 지정된 이름으로 변경할 변수
            df[col_name] = pd.to_numeric(df[col_name], errors='___')  # Q21: 변환 불가 값을 NaN 처리하는 옵션
            return df
        except Exception:
            if attempt < retries - 1:
                wait = ___ ** attempt                    # Q22: 지수 백오프의 밑(base) 숫자
                time.___(wait)                          # Q23: 지정 초만큼 대기하는 함수
            else:
                ___                                     # Q24: 예외를 다시 상위로 전파하는 키워드
#########################
def _fetch_fred(series_id: str, retries: int = 4, timeout: int = 30) -> pd.DataFrame:
    # FRED CSV 다운로드
    url = FRED_BASE + series
    for attempt in range (retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp = raise_for_status()
            df = pd.read_csv(StringIO(resp.text), index_col=0, parse_dates=True)
            df.columns=[col_name]
            df[col_name]=pd.to_numeric(df[col_name],errors='coerce')
            return df
        except Exception:
            
            if attempt < retries - 1:
                wait=2**attempt
                time.sleep(wait)
            else:
                raise    
#######################

def fetch_sector_macro() -> pd.DataFrame:
    """8개 FRED 지표를 수집하고 피처 DataFrame을 반환합니다."""
    print('[SectorMacro] FRED 데이터 수집 중...')
    raw = {}
    for sid, col in FRED_SERIES.___():                  # Q25: 딕셔너리의 키-값 쌍을 순회하는 메서드
        raw[sid] = _fetch_fred(sid, col)

    # ── INDPRO → PMI 유사 지수 변환 ──
    indpro_mom = raw['INDPRO']['indpro'].___( 3) * 100  # Q26: 이전 대비 변화율을 구하는 메서드
    pmi_series = indpro_mom.rolling(___, min_periods=36).apply(  # Q27: 10년치 월별 롤링 윈도우 크기
        lambda x: np.___(                              # Q28: 값을 상한·하한 범위로 제한하는 numpy 함수
            (x.iloc[-1] - x.___()) / max(x.std(), 0.01) * 10 + 50,  # Q29: 평균값을 구하는 메서드
            10, 90
        ),
        raw=___                                         # Q30: numpy 배열이 아닌 Series로 전달하는 옵션 (bool)
    )
    df_pmi = pmi_series.rename('pmi').dropna().to_frame()

    # ── 장단기 금리차 ──
    df_yield = raw['___']                               # Q31: 장단기 금리차 FRED 시리즈 ID 키

    # ── ANFCI: 주별 → 월별 평균 ──
    df_anfci = raw['ANFCI'].resample('___').mean()       # Q32: 월초 기준 리샘플링 주기 코드

    # ── ICSA: YoY 변화율 ──
    df_icsa = raw['ICSA'].resample('MS').mean()
    df_icsa['icsa_yoy'] = df_icsa['icsa'].pct_change(___) * 100  # Q33: YoY(전년 대비)에 해당하는 월 수
    df_icsa = df_icsa[['icsa_yoy']].___()               # Q34: 결측치 행을 제거하는 메서드

    # ── PERMIT: YoY 변화율 ──
    df_permit = raw['PERMIT'].___()                     # Q35: DataFrame 복사본을 만드는 메서드
    df_permit['permit_yoy'] = df_permit['permit'].pct_change(12) * 100
    df_permit = df_permit[['permit_yoy']].dropna()

    # ── RRSFS: YoY 변화율 ──
    df_rrsfs = raw['RRSFS'].copy()
    df_rrsfs['real_retail_yoy'] = df_rrsfs['real_retail'].pct_change(___) * 100  # Q36: YoY(전년 대비)에 해당하는 월 수
    df_rrsfs = df_rrsfs[['real_retail_yoy']].dropna()

    # ── ANDENO: YoY 변화율 ──
    df_capex = raw['___'].copy()                        # Q37: 비국방 자본재 주문 FRED 시리즈 ID 키
    df_capex['capex_yoy'] = df_capex['capex_orders'].pct_change(12) * 100
    df_capex = df_capex[['capex_yoy']].dropna()

    # ── W875RX1: YoY 변화율 ──
    df_income = raw['W875RX1'].copy()
    df_income['real_income_yoy'] = df_income['___'].pct_change(12) * 100  # Q38: 실질 개인소득 컬럼명
    df_income = df_income[['real_income_yoy']].dropna()

    # ── 8개 지표를 날짜 기준으로 병합 ──
    macro = (df_pmi
             .join(df_yield,  how='___')                # Q39: 모든 인덱스를 유지하는 조인 방식
             .join(df_anfci,  how='outer')
             .join(df_icsa,   how='outer')
             .join(df_permit, how='outer')
             .join(df_rrsfs,  how='outer')
             .join(df_capex,  how='outer')
             .join(df_income, how='outer'))
    macro = macro.resample('MS').___().dropna()          # Q40: 각 구간의 마지막 값을 취하는 메서드

    # ── 파생 피처 ──
    macro['pmi_chg3m']       = macro['pmi'].___( 3)      # Q41: 이전 값과의 차이를 구하는 메서드
    macro['capex_yoy_chg3m'] = macro['capex_yoy'].diff(3)
    macro = macro.dropna()

    macro.index.name = '___'                             # Q42: 인덱스 이름으로 사용할 날짜 문자열
    return macro
#####################################
# 8개 지표를 수집하고 피처 DataFrame으로 반환
def fetch_sector_macro() -> pd.DataFrame:
    print('데이터 수집 중')
    raw = {}
    for sid, col in FRED_SERIES.items():
        raw[sid] = _fetch_fred(sid,col)

    # indpro 를 pmi 유사 지수로 변환
    indpro_mom = raw['INDPRO']['indpro'].pct_change(3) *100
    pmi_series = indpro_mom.rolling(120, min_periods=36).apply(
        lambda x:np.clip(
            (x.ilock[-1]-x.mean())/max(x.std(),0.01) * 10+50,
            10,90
    ),
    raw=False
)
df_pmi = pmi_series.rename('pmi').dropna().to_frame()

# ── 장단기 금리차 ──
df_yield = raw['T10Y3M']                               # 10년-3개월 금리차 데이터

# ── ANFCI: 주별 → 월별 평균 ──
df_anfci = raw['ANFCI'].resample('MS').mean()           # 월초 기준으로 주간 데이터를 월평균 변환

# ── ICSA: YoY 변화율 ──
df_icsa = raw['ICSA'].resample('MS').mean()
df_icsa['icsa_yoy'] = df_icsa['icsa'].pct_change(12) * 100  # 12개월 전 대비 변화율
df_icsa = df_icsa[['icsa_yoy']].dropna()               # 결측치 행 제거

# ── PERMIT: YoY 변화율 ──
df_permit = raw['PERMIT'].copy()                       # 원본 보호를 위해 복사
df_permit['permit_yoy'] = df_permit['permit'].pct_change(12) * 100
df_permit = df_permit[['permit_yoy']].dropna()

# ── RRSFS: YoY 변화율 ──
df_rrsfs = raw['RRSFS'].copy()
df_rrsfs['real_retail_yoy'] = df_rrsfs['real_retail'].pct_change(12) * 100  # 12개월 전 대비 변화율
df_rrsfs = df_rrsfs[['real_retail_yoy']].dropna()

# ── ANDENO: YoY 변화율 ──
df_capex = raw['ANDENO'].copy()                        # 비국방 자본재 주문 데이터
df_capex['capex_yoy'] = df_capex['capex_orders'].pct_change(12) * 100
df_capex = df_capex[['capex_yoy']].dropna()

# ── W875RX1: YoY 변화율 ──
df_income = raw['W875RX1'].copy()
df_income['real_income_yoy'] = df_income['real_income'].pct_change(12) * 100  # 실질 개인소득 YoY
df_income = df_income[['real_income_yoy']].dropna()

# 8개 지표를 날짜 기준으로 병합
macro = (df_pmi
             .join(df_yield,  how='___')                # Q39: 모든 인덱스를 유지하는 조인 방식
             .join(df_anfci,  how='outer')
             .join(df_icsa,   how='outer')
             .join(df_permit, how='outer')
             .join(df_rrsfs,  how='outer')
             .join(df_capex,  how='outer')
             .join(df_income, how='outer'))

macro=macro.resample('MS').last().dropna()

# 파생 피처
macro['pmi_chg3m'] = macro['pmi'] = macro['pmi'].pct_change(3)
macro['capex_yoy_chg3m']=macro['capex_yoy'].gdiff(3)
macro=macro.dropna()

#######################################

def to_sector_macro_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → Supabase upsert용 dict 리스트로 변환"""
    records = []
    for date, row in df.___():                          # Q43: DataFrame 행을 순회하는 메서드
        records.append({
            'date':             str(date.___()),          # Q44: datetime에서 날짜 부분만 추출하는 메서드
            'pmi':              round(float(row['___']), 4),  # Q45: PMI 지수 컬럼명
            'yield_spread':     round(float(row['yield_spread']), 4),
            'anfci':            round(float(row['anfci']), 4),
            'icsa_yoy':         round(float(row['icsa_yoy']), 4),
            'permit_yoy':       round(float(row['___']), 4),  # Q46: 건축허가 YoY 변화율 컬럼명
            'real_retail_yoy':  round(float(row['real_retail_yoy']), 4),
            'capex_yoy':        round(float(row['___']), 4),  # Q47: 자본재 주문 YoY 변화율 컬럼명
            'real_income_yoy':  round(float(row['real_income_yoy']), 4),
            'pmi_chg3m':        round(float(row['pmi_chg3m']), 4),
            'capex_yoy_chg3m':  round(float(row['___']), 4),  # Q48: 자본재 YoY 3개월 변화 컬럼명
        })
    return ___                                           # Q49: 변환 완료된 레코드 리스트 변수


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | import ___                    | time                   |
# | Q2 | import ___                    | requests               |
# | Q3 | as ___                        | np                     |
# | Q4 | as ___                        | pd                     |
# | Q5 | from io import ___            | StringIO               |
# | Q6 | FRED_BASE = '___'             | https://fred.stlouisfed.org/graph/fredgraph.csv?id= |
# | Q7 | '___': 'indpro'               | INDPRO                 |
# | Q8 | '___': 'yield_spread'         | T10Y3M                 |
# | Q9 | '___': 'anfci'                | ANFCI                  |
# | Q10| '___': 'icsa'                 | ICSA                   |
# | Q11| '___': 'permit'               | PERMIT                 |
# | Q12| '___': 'real_retail'          | RRSFS                  |
# | Q13| '___': 'capex_orders'         | ANDENO                 |
# | Q14| '___': 'real_income'          | W875RX1                |
# | Q15| retries: int = ___            | 4                      |
# | Q16| timeout: int = ___            | 30                     |
# | Q17| FRED_BASE + ___               | series_id              |
# | Q18| range(___)                    | retries                |
# | Q19| pd.___                        | read_csv               |
# | Q20| [___]                         | col_name               |
# | Q21| errors='___'                  | coerce                 |
# | Q22| ___ ** attempt                | 2                      |
# | Q23| time.___                      | sleep                  |
# | Q24| ___                           | raise                  |
# | Q25| .___()                        | items                  |
# | Q26| .___( 3)                      | pct_change             |
# | Q27| .rolling(___)                 | 120                    |
# | Q28| np.___                        | clip                   |
# | Q29| x.___()                       | mean                   |
# | Q30| raw=___                       | False                  |
# | Q31| raw['___']                    | T10Y3M                 |
# | Q32| .resample('___')              | MS                     |
# | Q33| .pct_change(___)              | 12                     |
# | Q34| .___()                        | dropna                 |
# | Q35| .___()                        | copy                   |
# | Q36| .pct_change(___) * 100        | 12                     |
# | Q37| raw['___']                    | ANDENO                 |
# | Q38| ['___']                       | real_income            |
# | Q39| how='___'                     | outer                  |
# | Q40| .___().dropna()               | last                   |
# | Q41| .___( 3)                      | diff                   |
# | Q42| .name = '___'                 | date                   |
# | Q43| df.___()                      | iterrows               |
# | Q44| date.___()                    | date                   |
# | Q45| row['___']                    | pmi                    |
# | Q46| row['___']                    | permit_yoy             |
# | Q47| row['___']                    | capex_yoy              |
# | Q48| row['___']                    | capex_yoy_chg3m        |
# | Q49| return ___                    | records                |
# ============================================================
