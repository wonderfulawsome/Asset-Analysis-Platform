### Yahoo Finance API로 S&P500, VIX, 금리, 달러지수 등 거시지표 수집
# -------------------------------------------------------------------

import datetime        # 날짜/시간 처리
import requests        # HTTP 요청
import pandas as pd    # 데이터프레임 처리

# Yahoo Finance API 차단 방지용 브라우저 헤더
HEADERS = {'User-Agent': 'Mozilla/5.0'}

# 수집할 Yahoo Finance 티커 → 내부 별칭 매핑
SYMBOLS = {
    '^GSPC':    'sp500',   # S&P 500 지수
    '^VIX':     'vix',     # 변동성 지수
    '^TNX':     'tnx',     # 10년 국채 수익률
    '^IRX':     'irx',     # 3개월 국채 수익률
    '^NDX':     'ndx',     # 나스닥 100 지수
    '^SOX':     'sox',     # 필라델피아 반도체 지수
}


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI(상대강도지수) 계산 — 과매수/과매도 판단 지표 (0~100)."""
    delta = series.diff()                                  # 일별 가격 변화량
    gain  = delta.clip(lower=0).rolling(period).mean()     # 상승분의 14일 평균
    loss  = (-delta.clip(upper=0)).rolling(period).mean()  # 하락분의 14일 평균
    return 100 - (100 / (1 + gain / loss))                 # RSI 공식
# -------------------------------------------------------------------
# _rsi: rsi 계산 함수
# -------------------------------------------------------------------


def _fetch_df(ticker: str, from_ts: int, to_ts: int) -> pd.DataFrame:
    """Yahoo Finance v8 API로 종가/거래량 DataFrame을 반환합니다.
    100년치 요청 실패 시 50년 → 30년으로 기간을 줄여 재시도합니다."""
    fallback_days = [0, 365*50, 365*30]                    # 원본, 50년, 30년 순서로 시도
    for i, alt_days in enumerate(fallback_days):
        try:
            p1 = from_ts if alt_days == 0 else int(to_ts - alt_days * 86400)  # 대체 시작일 계산
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'  # API 엔드포인트
            params = {'interval': '1d', 'period1': p1, 'period2': to_ts}   # 일봉, 기간
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)  # HTTP 요청
            resp.raise_for_status()                            # 에러 시 예외 발생
            result = resp.json()['chart']['result'][0]         # JSON에서 차트 데이터 추출
            meta = result['meta']                              # 메타 정보 (최종 체결가 포함)
            timestamps = result['timestamp']                   # Unix 타임스탬프 배열
            closes  = result['indicators']['adjclose'][0]['adjclose']  # 수정 종가 배열
            volumes = result['indicators']['quote'][0]['volume']    # 거래량 배열
            index = pd.to_datetime(timestamps, unit='s').normalize()  # 타임스탬프 → 날짜 인덱스
            df = pd.DataFrame({'close': closes, 'volume': volumes}, index=index)  # DataFrame 생성
            df = df[~df.index.duplicated(keep='last')]           # 중복 날짜 제거 (마지막 값 유지)
            # 마지막 행의 종가가 None 또는 0이면 meta의 regularMarketPrice로 보정 (장 마감 후 대비)
            rmp = meta.get('regularMarketPrice')               # 최종 체결가 (장 중/장 후 모두 유효)
            last_close = df['close'].iloc[-1] if len(df) > 0 else None  # 마지막 종가
            if rmp and len(df) > 0 and (pd.isna(last_close) or last_close == 0):  # None 또는 0이면 보정
                df.iloc[-1, df.columns.get_loc('close')] = rmp  # None/0 → 최종 체결가로 대체
            if alt_days > 0:
                print(f'[Collector] {ticker}: 기간 축소 재시도 성공 ({alt_days//365}년)')  # 재시도 성공 로그
            return df
        except Exception as e:
            if i < len(fallback_days) - 1:                     # 마지막 시도가 아니면 재시도
                print(f'[Collector] {ticker}: 수집 실패, 기간 축소 재시도... ({e})')
            else:
                raise                                          # 마지막 시도도 실패하면 예외 전파

# -------------------------------------------------------------------
# _fetch_df: 티커별 종가 및 거래량 수집
# -------------------------------------------------------------------


def fetch_macro(days: int = 0) -> pd.DataFrame:
    """거시 지표를 Yahoo Finance API에서 수집하고 피처를 계산하여 DataFrame으로 반환합니다.
    days=0이면 100년치 전체, days>0이면 최근 N일치만 수집 (증분 모드).
    """
    today     = datetime.date.today()                      # 오늘 날짜
    # days가 0이면 100년치 전체, 아니면 최근 N일치만 수집 (RSI/MA 계산 여유분 포함)
    lookback  = 365 * 100 + 25 if days == 0 else days + 60  # 60일 여유분 (이동평균 계산용)
    from_date = today - datetime.timedelta(days=lookback)  # 시작일 계산
    epoch     = datetime.datetime(1970, 1, 1)              # Unix epoch 기준점
    from_ts   = int((datetime.datetime.combine(from_date, datetime.time()) - epoch).total_seconds())  # 시작 timestamp
    to_ts     = int((datetime.datetime.combine(today,     datetime.time()) - epoch).total_seconds())  # 종료 timestamp

    mode = '증분' if days > 0 else '전체'  # 수집 모드 표시
    print(f'[Collector] 거시 지표 수집 중... ({from_date} ~ {today}) [{mode}]')

    # 거시 지표 수집전 수집 날짜 정의

    # 6개 티커 데이터를 각각 수집
    raw = {}
    for ticker in SYMBOLS:
        raw[ticker] = _fetch_df(ticker, from_ts, to_ts)    # 티커별 API 호출
        if raw[ticker].empty:
            raise RuntimeError(f'[Collector] 데이터 수집 실패: {ticker}')
    # 티커 순회 하며 정의 한 날자에 맞춰 데이터 수집
    ### raw 에 데이터 저장

    # S&P 500 날짜를 기준 인덱스로 사용
    df = pd.DataFrame(index=raw['^GSPC'].index)

    # ── S&P 500 피처 ──
    sp500_c = raw['^GSPC']['close']                        # S&P 500 종가
    sp500_v = raw['^GSPC']['volume']                       # S&P 500 거래량
    df['sp500_close']     = sp500_c                        # 종가 원본
    df['sp500_return']    = sp500_c.pct_change(1)          # 일별 수익률
    df['sp500_vol_ratio'] = (sp500_v / sp500_v.rolling(20).mean()).fillna(1.0)  # 거래량 / 20일 평균 (상대 거래량)
    df['sp500_ma20_disp'] = sp500_c / sp500_c.rolling(20).mean()  # 종가 / 20일 이평선 (이격도)
    df['sp500_rsi']       = _rsi(sp500_c)                  # 14일 RSI

    # ── 거시 지표 ──
    df['vix']          = raw['^VIX']['close']              # VIX (공포지수)
    df['tnx']          = raw['^TNX']['close']              # 10년 국채 수익률
    df['irx']          = raw['^IRX']['close']              # 3개월 국채 수익률
    df['yield_spread'] = df['tnx'] - df['irx']            # 장단기 금리차 (10년 - 3개월)
    df['dxy_return']   = 0.0                                 # 달러지수 수익률 (DX-Y.NYB 제거, 미사용)

    # ── 나스닥 100 피처 ──
    ndx_c = raw['^NDX']['close']                           # 나스닥 100 종가
    ndx_v = raw['^NDX']['volume']                          # 나스닥 100 거래량
    df['ndx_return']    = ndx_c.pct_change(1)              # 일별 수익률
    df['ndx_vol_ratio'] = (ndx_v / ndx_v.rolling(20).mean()).fillna(1.0)  # 상대 거래량
    df['ndx_ma20_disp']  = ndx_c / ndx_c.rolling(20).mean()  # 20일 이격도
    df['ndx_rsi']       = _rsi(ndx_c)                      # 14일 RSI

    # ── 반도체 지수 피처 ──
    sox_c = raw['^SOX']['close']                           # SOX 종가
    sox_v = raw['^SOX']['volume']                          # SOX 거래량
    df['sox_return']    = sox_c.pct_change(1)              # 일별 수익률
    df['sox_vol_ratio'] = (sox_v / sox_v.rolling(20).mean()).fillna(1.0)  # 상대 거래량
    df['sox_ma20_disp']  = sox_c / sox_c.rolling(20).mean()  # 20일 이격도
    df['sox_rsi']       = _rsi(sox_c)                      # 14일 RSI

    df = df.drop(columns=['irx']).dropna()                 # irx는 spread 계산에만 사용했으므로 제거 + 결측 행 제거
    df.index.name = 'date'                                 # 인덱스 이름 설정

    print(f'[Collector] 수집 완료: {len(df)}행')
    return df

# -------------------------------------------------------------------
# fetch_macro: 수집할 날짜 기간 정의 및 raw 에 데이터 수집 저장/각 티커별 데이터 종가 및 지표 칼럼으로 나누기
# -------------------------------------------------------------------

def to_macro_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame을 Supabase upsert용 dict 리스트로 변환합니다."""
    cols = ['sp500_close', 'sp500_return', 'sp500_vol_ratio', 'vix', 'tnx', 'yield_spread', 'dxy_return', 'sp500_rsi']
    records = []
    for date, row in df[cols].iterrows():                  # 날짜별로 순회
        rec = {
            'date':            str(date.date()),           # 날짜 문자열
            'sp500_close':     round(float(row['sp500_close']),     4),  # S&P 500 종가
            'sp500_return':    round(float(row['sp500_return']),    6),  # S&P 500 일별 수익률
            'sp500_vol20':     round(float(row['sp500_vol_ratio']), 4),  # S&P 500 상대 거래량
            'vix':             round(float(row['vix']),             4),  # VIX
            'tnx':             round(float(row['tnx']),             4),  # 10년 금리
            'yield_spread':    round(float(row['yield_spread']),    4),  # 장단기 금리차
            'dxy_return':      round(float(row['dxy_return']),      6),  # 달러지수 수익률
        }
        # RSI 값이 있으면 추가 (초기 14일은 NaN)
        if pd.notna(row.get('sp500_rsi')):
            rec['sp500_rsi'] = round(float(row['sp500_rsi']), 2)
        records.append(rec)
    return records  # Supabase에 저장할 레코드 리스트 반환

# -------------------------------------------------------------------
# to_macro_records: sp500 의 정보들과 거시지표들을 순회하면서 date 다음에 각종지표들을 수집
# -------------------------------------------------------------------
