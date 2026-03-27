### FRED 8개 매크로 지표 수집 + PMI 변환 + 파생변수 생성

import time                # 재시도 시 대기(sleep)용
import requests            # HTTP 요청으로 FRED 데이터 다운로드
import numpy as np         # 수치 계산 (clip 등)
import pandas as pd        # 데이터프레임 처리
from io import StringIO    # 문자열을 파일처럼 읽기 위한 래퍼

# FRED CSV 다운로드 기본 URL
FRED_BASE = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id='
# 웹 브라우저처럼 보이기 위한 HTTP 헤더 (차단 방지)
HEADERS   = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# FRED 시리즈 ID → 코드에서 사용할 컬럼명 매핑 (8개 지표)
FRED_SERIES = {
    'INDPRO':  'indpro',          # 산업생산지수
    'T10Y3M':  'yield_spread',    # 10년-3개월 장단기 금리차
    'ANFCI':   'anfci',           # 시카고 연준 금융상황지수
    'ICSA':    'icsa',            # 신규 실업수당 청구건수
    'PERMIT':  'permit',          # 건축허가 건수
    'RRSFS':   'real_retail',     # 실질 소매판매
    'ANDENO':  'capex_orders',    # 비국방 자본재 신규주문 (설비투자 선행지표)
    'W875RX1': 'real_income',     # 실질 개인소득 (이전지출 제외)
}

_fred_session = requests.Session()                       # FRED 전용 세션 (TCP 연결 재사용)
_fred_session.headers.update(HEADERS)


def _fetch_fred(series_id: str, col_name: str, retries: int = 5,
                timeout: tuple = (15, 60)) -> pd.DataFrame:
    """FRED CSV 다운로드 (지수 백오프 재시도, connect=15s/read=60s 타임아웃)"""
    url = FRED_BASE + series_id                          # 다운로드할 URL 생성
    for attempt in range(retries):                       # 최대 retries번 시도
        try:
            resp = _fred_session.get(url, timeout=timeout)  # 세션 기반 요청 (연결 재사용)
            resp.raise_for_status()                      # 4xx/5xx 에러 시 예외 발생
            df = pd.read_csv(StringIO(resp.text), index_col=0, parse_dates=True)  # CSV → DataFrame 변환
            df.columns = [col_name]                      # 컬럼명 설정
            df[col_name] = pd.to_numeric(df[col_name], errors='coerce')  # 숫자 변환
            return df                                    # 성공 시 반환
        except Exception as e:
            if attempt < retries - 1:                    # 마지막 시도 전이면
                wait = 5 * (2 ** attempt)                # 5초, 10초, 20초, 40초 대기
                print(f'  [{series_id}] 재시도 {attempt+1}/{retries} ({wait}초 대기) — {type(e).__name__}')
                time.sleep(wait)                         # 대기 후 재시도
            else:
                raise                                    # 최종 실패 시 예외
# -------------------------------------------------------------------
# 다운로드한 데이터를 전처리하는 함수(데이터프레임 변환, 이름변경, 숫자변환)
# -------------------------------------------------------------------

def fetch_sector_macro() -> pd.DataFrame:
    """8개 FRED 지표를 수집하고 피처 DataFrame을 반환합니다.
    컬럼: pmi, yield_spread, anfci, icsa_yoy, permit_yoy,
          real_retail_yoy, capex_yoy, real_income_yoy, pmi_chg3m, capex_yoy_chg3m
    """
    print('[SectorMacro] FRED 데이터 수집 중...')
    raw = {}                                             # 수집 결과를 담을 딕셔너리
    for sid, col in FRED_SERIES.items():                  # 8개 시리즈 순회
        raw[sid] = _fetch_fred(sid, col)                  # 각 시리즈를 다운로드하여 저장
        print(f'  ✓ {sid}')

    # ── INDPRO → PMI 유사 지수 변환 ──
    indpro_mom = raw['INDPRO']['indpro'].pct_change(3) * 100  # 3개월 전 대비 변화율(%)
    pmi_series = indpro_mom.rolling(120, min_periods=36).apply(  # 120개월(10년) 롤링 윈도우
        lambda x: np.clip(                               # 결과를 10~90 범위로 제한
            (x.iloc[-1] - x.mean()) / max(x.std(), 0.01) * 10 + 50,  # z-score → PMI 스케일 변환 (평균50, 표준편차10)
            10, 90
        ),
        raw=False                                        # Series 객체로 전달 (iloc 사용을 위해)
    )
    df_pmi = pmi_series.rename('pmi').dropna().to_frame()  # 시리즈 → DataFrame 변환, NaN 제거

    ### indpro를 3개월전 대비 변화율 -> 120개월 기간을 함수적용(결과를 10~90으로 제한, PMI 형식으로 스케일링)

    # ── 장단기 금리차 (일별 데이터 그대로 사용) ──
    df_yield = raw['T10Y3M']

    # ── ANFCI: 주별 → 월별 평균으로 리샘플링 ──
    df_anfci = raw['ANFCI'].resample('MS').mean()         # 월초('MS') 기준으로 평균

    # ── ICSA: 주별 → 월별 평균 → 전년 대비 변화율(YoY%) ──
    df_icsa = raw['ICSA'].resample('MS').mean()           # 주별 → 월별 평균
    df_icsa['icsa_yoy'] = df_icsa['icsa'].pct_change(12) * 100  # 12개월 전 대비 변화율
    df_icsa = df_icsa[['icsa_yoy']].dropna()              # YoY% 컬럼만 남기고 NaN 제거

    # ── PERMIT: 전년 대비 변화율(YoY%) ──
    df_permit = raw['PERMIT'].copy()                      # 원본 보존을 위해 복사
    df_permit['permit_yoy'] = df_permit['permit'].pct_change(12) * 100  # 12개월 전 대비 변화율
    df_permit = df_permit[['permit_yoy']].dropna()        # YoY% 컬럼만 남기고 NaN 제거

    # ── RRSFS (실질 소매판매): 전년 대비 변화율(YoY%) ──
    df_rrsfs = raw['RRSFS'].copy()
    df_rrsfs['real_retail_yoy'] = df_rrsfs['real_retail'].pct_change(12) * 100
    df_rrsfs = df_rrsfs[['real_retail_yoy']].dropna()

    # ── ANDENO (설비투자): 전년 대비 변화율(YoY%) ──
    df_capex = raw['ANDENO'].copy()
    df_capex['capex_yoy'] = df_capex['capex_orders'].pct_change(12) * 100
    df_capex = df_capex[['capex_yoy']].dropna()

    # ── W875RX1 (실질 개인소득): 전년 대비 변화율(YoY%) ──
    df_income = raw['W875RX1'].copy()
    df_income['real_income_yoy'] = df_income['real_income'].pct_change(12) * 100
    df_income = df_income[['real_income_yoy']].dropna()

    ### 각 지표의 전년대비 변화율 계산

    # ── 8개 지표를 날짜 기준으로 병합 ──
    macro = (df_pmi
             .join(df_yield,  how='outer')                # outer join: 한쪽에만 있는 날짜도 포함
             .join(df_anfci,  how='outer')
             .join(df_icsa,   how='outer')
             .join(df_permit, how='outer')
             .join(df_rrsfs,  how='outer')
             .join(df_capex,  how='outer')
             .join(df_income, how='outer'))
    macro = macro.resample('MS').last().dropna()          # 월초 기준 리샘플링 → 마지막 값 사용, NaN 행 제거

    # ── 파생 피처: 3개월 변화량 ──
    macro['pmi_chg3m']       = macro['pmi'].diff(3)       # PMI의 3개월 전 대비 변화량
    macro['capex_yoy_chg3m'] = macro['capex_yoy'].diff(3) # 설비투자 YoY%의 3개월 전 대비 변화량
    macro = macro.dropna()                                # 파생 피처 생성으로 인한 NaN 제거

    macro.index.name = 'date'                             # 인덱스 이름을 'date'로 설정
    print(f'[SectorMacro] 수집 완료: {macro.shape[0]}행 ({macro.index[0].date()} ~ {macro.index[-1].date()})')
    return macro                                          # 최종 매크로 피처 DataFrame 반환

# -------------------------------------------------------------------
    ### macro = 각 경제 지표를 병합(outer) 해서 누락없이 모든 데이터 병합
    ### macro 에 새로운 피처 생성
# -------------------------------------------------------------------

def to_sector_macro_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → Supabase upsert용 dict 리스트로 변환"""
    records = []                                          # 결과를 담을 리스트
    for date, row in df.iterrows():                       # 각 행(날짜)을 순회
        records.append({                                  # 딕셔너리로 변환하여 추가
            'date':             str(date.date()),         # 날짜를 문자열로 변환
            'pmi':              round(float(row['pmi']), 4),            # 소수점 4자리로 반올림
            'yield_spread':     round(float(row['yield_spread']), 4),
            'anfci':            round(float(row['anfci']), 4),
            'icsa_yoy':         round(float(row['icsa_yoy']), 4),
            'permit_yoy':       round(float(row['permit_yoy']), 4),
            'real_retail_yoy':  round(float(row['real_retail_yoy']), 4),
            'capex_yoy':        round(float(row['capex_yoy']), 4),
            'real_income_yoy':  round(float(row['real_income_yoy']), 4),
            'pmi_chg3m':        round(float(row['pmi_chg3m']), 4),
            'capex_yoy_chg3m':  round(float(row['capex_yoy_chg3m']), 4),
        })
    return records                                        # Supabase에 넣을 수 있는 dict 리스트 반환
# -------------------------------------------------------------------
# macro 를 딕셔너리로 변환하는 함수
# -------------------------------------------------------------------
