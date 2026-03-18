# ============================================================
# BE_01_MarketData — Yahoo Finance 거시지표 수집 빈칸 연습
# 원본: collector/market_data.py
# 총 빈칸: 60개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

# Q1~Q3: 필요한 모듈 임포트
import ___                                              # Q1: 날짜/시간 처리 모듈
import ___                                              # Q2: HTTP 요청 라이브러리
import ___ as pd                                        # Q3: 데이터 분석 라이브러리 (별칭 pd)

# Q4: Yahoo Finance API 차단 방지용 브라우저 헤더
HEADERS = {'___': 'Mozilla/5.0'}                        # Q4: HTTP 요청 시 브라우저 식별 헤더 키

# Q5~Q11: 수집할 Yahoo Finance 티커 → 내부 별칭 매핑
SYMBOLS = {
    '___':    'sp500',                                  # Q5: S&P 500 지수 티커
    '___':     'vix',                                   # Q6: 변동성 지수 티커
    '___':     'tnx',                                   # Q7: 10년 국채 수익률 티커
    '___':     'irx',                                   # Q8: 3개월 국채 수익률 티커
    '___': 'dxy',                                       # Q9: 달러 인덱스 티커
    '___':     'ndx',                                   # Q10: 나스닥 100 지수 티커
    '___':     'sox',                                   # Q11: 필라델피아 반도체 지수 티커
}


def _rsi(series: pd.Series, period: int = ___) -> pd.Series:   # Q12: RSI 기본 기간 값
    """RSI(상대강도지수) 계산 — 과매수/과매도 판단 지표 (0~100)."""
    delta = series.___()                                # Q13: 일별 가격 변화량 계산 메서드
    gain  = delta.clip(lower=0).rolling(period).___()   # Q14: 이동 평균 계산 메서드
    loss  = (-delta.clip(upper=0)).rolling(period).___()# Q15: 이동 평균 계산 메서드
    return 100 - (100 / (1 + ___ / ___))                # Q16~Q17: RSI 공식의 상승평균 / 하락평균


def _fetch_df(ticker: str, from_ts: int, to_ts: int) -> pd.___:  # Q18: pandas의 표 형태 자료구조 클래스
    """Yahoo Finance v8 API로 종가/거래량 DataFrame을 반환합니다."""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{___}'  # Q19: URL에 삽입할 티커 변수
    params = {'interval': '1d', '___': from_ts, '___': to_ts}        # Q20~Q21: Yahoo Finance API의 시작/종료 기간 파라미터명
    resp = requests.___(url, params=params, headers=HEADERS, timeout=15)  # Q22: HTTP GET 요청 메서드
    resp.___()                                          # Q23: HTTP 에러 시 예외 발생 메서드
    result = resp.___()['chart']['result'][0]           # Q24: 응답을 JSON으로 파싱하는 메서드
    timestamps = result['___']                          # Q25: Unix 타임스탬프 배열 키
    closes  = result['indicators']['adjclose'][0]['___']  # Q26: 수정 종가 배열 키
    volumes = result['indicators']['quote'][0]['___']    # Q27: 거래량 배열 키
    index = pd.to_datetime(timestamps, unit='___').normalize()  # Q28: 타임스탬프 단위 (초)
    df = pd.DataFrame({'close': closes, 'volume': volumes}, index=index)
    df = df[~df.index.___(keep='last')]                 # Q29: 중복 인덱스 검출 메서드
    return df


def fetch_macro(days: int = ___) -> pd.DataFrame:       # Q30: 전체 기간 수집을 의미하는 기본값
    """거시 지표를 Yahoo Finance API에서 수집하고 피처를 계산하여 DataFrame으로 반환합니다."""
    today     = datetime.date.___()                      # Q31: 오늘 날짜를 가져오는 메서드
    lookback  = 365 * 100 + 25 if days == 0 else days + ___  # Q32: 이동평균 등 보조지표 안정화를 위한 추가 여유 일수
    from_date = today - datetime.timedelta(days=___)     # Q33: 조회 시작일 계산에 사용할 변수
    epoch     = datetime.datetime(1970, 1, 1)            # Unix epoch 기준점
    from_ts   = int((datetime.datetime.combine(from_date, datetime.time()) - epoch).___())  # Q34: timedelta를 초 단위로 변환하는 메서드
    to_ts     = int((datetime.datetime.combine(today,     datetime.time()) - epoch).total_seconds())

    # 7개 티커 데이터를 각각 수집
    raw = {}
    for ticker in ___:                                   # Q35: 티커-별칭 매핑 딕셔너리
        raw[ticker] = _fetch_df(ticker, from_ts, to_ts)  # 티커별 API 호출
        if raw[ticker].___:                              # Q36: DataFrame이 비어있는지 확인하는 속성
            raise RuntimeError(f'[Collector] 데이터 수집 실패: {ticker}')

    # S&P 500 날짜를 기준 인덱스로 사용
    df = pd.DataFrame(index=raw['___'].index)            # Q37: S&P 500 지수의 Yahoo Finance 티커

    # ── S&P 500 피처 ──
    sp500_c = raw['^GSPC']['___']                        # Q38: 종가 컬럼명
    sp500_v = raw['^GSPC']['volume']
    df['sp500_close']     = sp500_c
    df['sp500_return']    = sp500_c.___( 1)              # Q39: 전일 대비 수익률 계산 메서드
    df['sp500_vol_ratio'] = (sp500_v / sp500_v.rolling(___).mean()).fillna(1.0)  # Q40: 이동평균 기간 (거래일 기준)
    df['sp500_ma20_disp'] = sp500_c / sp500_c.rolling(20).___()  # Q41: 이동 평균 계산 메서드
    df['sp500_rsi']       = _rsi(___)                    # Q42: S&P 500 종가 시리즈 변수

    # ── 거시 지표 ──
    df['vix']          = raw['^VIX']['close']
    df['tnx']          = raw['^TNX']['close']
    df['irx']          = raw['^IRX']['close']
    df['yield_spread'] = df['___'] - df['___']           # Q43~Q44: 장기 국채 수익률에서 단기 국채 수익률을 뺀 스프레드
    df['dxy_return']   = raw['DX-Y.NYB']['close'].pct_change(___)  # Q45: 달러 인덱스 변화율 계산 기간 (거래일)

    # ── 나스닥 100 피처 ──
    ndx_c = raw['___']['close']                          # Q46: 나스닥 100 지수의 Yahoo Finance 티커
    ndx_v = raw['^NDX']['volume']
    df['ndx_return']    = ndx_c.pct_change(1)
    df['ndx_vol_ratio'] = (ndx_v / ndx_v.rolling(20).mean()).fillna(1.0)
    df['ndx_ma20_disp'] = ndx_c / ndx_c.rolling(20).mean()
    df['ndx_rsi']       = _rsi(ndx_c)

    # ── 반도체 지수 피처 ──
    sox_c = raw['___']['close']                          # Q47: 반도체 지수의 Yahoo Finance 티커
    sox_v = raw['^SOX']['volume']
    df['sox_return']    = sox_c.pct_change(1)
    df['sox_vol_ratio'] = (sox_v / sox_v.rolling(20).mean()).fillna(1.0)
    df['sox_ma20_disp'] = sox_c / sox_c.rolling(20).mean()
    df['sox_rsi']       = _rsi(sox_c)

    df = df.drop(columns=['___']).dropna()               # Q48: 최종 결과에서 제외할 단기 국채 수익률 컬럼명
    df.index.name = '___'                                # Q49: 인덱스 이름 (날짜)
    return df


def to_macro_records(df: pd.DataFrame) -> list[___]:     # Q50: 파이썬 내장 딕셔너리 타입
    """DataFrame을 Supabase upsert용 dict 리스트로 변환합니다."""
    cols = ['sp500_close', 'sp500_return', 'sp500_vol_ratio', 'vix', 'tnx', 'yield_spread', 'dxy_return', 'sp500_rsi']
    records = []
    for date, row in df[cols].___():                     # Q51: DataFrame 행 순회 메서드
        rec = {
            'date':            str(date.___()),           # Q52: Timestamp에서 날짜만 추출하는 메서드
            'sp500_close':     round(float(row['sp500_close']),     4),
            'sp500_return':    round(float(row['sp500_return']),    6),
            'sp500_vol20':     round(float(row['sp500_vol_ratio']), 4),
            'vix':             round(float(row['___']),             4),  # Q53: 변동성 지수 컬럼명
            'tnx':             round(float(row['tnx']),             4),
            'yield_spread':    round(float(row['yield_spread']),    4),
            'dxy_return':      round(float(row['___']),      6),  # Q54: 달러 인덱스 수익률 컬럼명
        }
        # Q55~Q56: RSI 값이 있으면 추가
        if pd.___(row.get('sp500_rsi')):                 # Q55: 값이 결측치가 아닌지 확인하는 함수
            rec['sp500_rsi'] = round(float(row['___']), 2)  # Q56: S&P 500 RSI 컬럼명
        records.___(rec)                                 # Q57: 리스트에 항목을 추가하는 메서드
    return records


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | import ___                    | datetime               |
# | Q2 | import ___                    | requests               |
# | Q3 | import ___ as pd              | pandas                 |
# | Q4 | {'___': ...}                  | User-Agent             |
# | Q5 | '___': 'sp500'               | ^GSPC                  |
# | Q6 | '___': 'vix'                 | ^VIX                   |
# | Q7 | '___': 'tnx'                 | ^TNX                   |
# | Q8 | '___': 'irx'                 | ^IRX                   |
# | Q9 | '___': 'dxy'                 | DX-Y.NYB               |
# | Q10| '___': 'ndx'                 | ^NDX                   |
# | Q11| '___': 'sox'                 | ^SOX                   |
# | Q12| period: int = ___             | 14                     |
# | Q13| series.___()                  | diff                   |
# | Q14| .rolling(period).___()        | mean                   |
# | Q15| .rolling(period).___()        | mean                   |
# | Q16| ___ / ___                     | gain                   |
# | Q17| ___ / ___                     | loss                   |
# | Q18| pd.___                        | DataFrame              |
# | Q19| {___}                         | ticker                 |
# | Q20| '___': from_ts                | period1                |
# | Q21| '___': to_ts                  | period2                |
# | Q22| requests.___                  | get                    |
# | Q23| resp.___()                    | raise_for_status       |
# | Q24| resp.___()                    | json                   |
# | Q25| result['___']                 | timestamp              |
# | Q26| ['___']                       | adjclose               |
# | Q27| ['___']                       | volume                 |
# | Q28| unit='___'                    | s                      |
# | Q29| .index.___                    | duplicated             |
# | Q30| days: int = ___               | 0                      |
# | Q31| datetime.date.___()           | today                  |
# | Q32| days + ___                    | 60                     |
# | Q33| timedelta(days=___)           | lookback               |
# | Q34| .___()                        | total_seconds          |
# | Q35| for ticker in ___             | SYMBOLS                |
# | Q36| .___                          | empty                  |
# | Q37| raw['___'].index              | ^GSPC                  |
# | Q38| ['___']                       | close                  |
# | Q39| .___( 1)                      | pct_change             |
# | Q40| .rolling(___)                 | 20                     |
# | Q41| .rolling(20).___()            | mean                   |
# | Q42| _rsi(___)                     | sp500_c                |
# | Q43| df['___']                     | tnx                    |
# | Q44| - df['___']                   | irx                    |
# | Q45| .pct_change(___)              | 5                      |
# | Q46| raw['___']                    | ^NDX                   |
# | Q47| raw['___']                    | ^SOX                   |
# | Q48| columns=['___']               | irx                    |
# | Q49| .name = '___'                 | date                   |
# | Q50| list[___]                     | dict                   |
# | Q51| df[cols].___()                | iterrows               |
# | Q52| date.___()                    | date                   |
# | Q53| row['___']                    | vix                    |
# | Q54| row['___']                    | dxy_return             |
# | Q55| pd.___                        | notna                  |
# | Q56| row['___']                    | sp500_rsi              |
# | Q57| records.___                   | append                 |
# ============================================================
