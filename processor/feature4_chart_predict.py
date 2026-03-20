"""Prophet 기반 ETF 30일 주가 예측 (스케줄러 배치 실행용).

전체 파이프라인(3시간 주기)에서 16개 ETF 티커별로 Prophet 모델을 학습하고,
30일 영업일 예측 결과를 DB에 저장한다.
"""

import datetime
import json
import time
import numpy as np
import yfinance as yf

# 예측 대상 ETF 티커 (chart.py의 CHART_TICKERS와 동일)
CHART_TICKERS = ['SPY', 'QQQ', 'DIA', 'IWM', 'VTI', 'VOO', 'SOXX', 'SMH',
                 'XLK', 'XLF', 'XLE', 'XLV', 'ARKK', 'GLD', 'TLT', 'SCHD']


def run_chart_predict_single(ticker: str) -> dict | None:
    """단일 티커에 대해 Prophet 30일 예측을 실행한다."""
    from prophet import Prophet
    import pandas as pd

    # 최근 5년 일봉 다운로드 (상승/하락 사이클 포함 + 최근 추세 반영)
    df = yf.download(ticker, period='5y', interval='1d',
                     auto_adjust=True, progress=False)
    if df.empty:
        return None

    if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
        df.columns = df.columns.get_level_values(0)

    # ds(날짜) y(종가) 형식으로 변환
    prophet_df = df[['Close']].reset_index()
    prophet_df.columns = ['ds', 'y']

    # 로그 변환: 주가의 곱셈적 특성 반영
    prophet_df['y'] = np.log(prophet_df['y'])

    # Prophet 모델 학습
    model = Prophet(
        daily_seasonality=False,
        yearly_seasonality=True,
        weekly_seasonality=False,
        changepoint_prior_scale=0.15,
        n_changepoints=50,
        seasonality_mode='multiplicative',
    )
    model.fit(prophet_df)

    # 30 영업일 예측
    future = model.make_future_dataframe(periods=30, freq='B')
    forecast = model.predict(future)

    # 로그 역변환
    forecast['yhat'] = np.exp(forecast['yhat'])
    forecast['yhat_lower'] = np.exp(forecast['yhat_lower'])
    forecast['yhat_upper'] = np.exp(forecast['yhat_upper'])
    prophet_df['y'] = np.exp(prophet_df['y'])

    # 최근 30일 실제 종가
    recent = prophet_df.tail(30)
    actual = [{'date': str(r.ds.date()), 'close': round(float(r.y), 2)}
              for _, r in recent.iterrows()]

    # 예측 30일
    pred = forecast.tail(30)
    predicted = [{'date': str(r.ds.date()),
                  'yhat': round(float(r.yhat), 2),
                  'lower': round(float(r.yhat_lower), 2),
                  'upper': round(float(r.yhat_upper), 2)}
                 for _, r in pred.iterrows()]

    # 메모리 정리
    del model

    return {
        'date': str(datetime.date.today()),
        'ticker': ticker,
        'actual': json.dumps(actual, ensure_ascii=False),
        'predicted': json.dumps(predicted, ensure_ascii=False),
    }


def run_chart_predict_all() -> list[dict]:
    """16개 ETF 티커 전체에 대해 Prophet 예측을 실행한다."""
    results = []
    for i, ticker in enumerate(CHART_TICKERS):
        try:
            print(f'  [{i+1}/{len(CHART_TICKERS)}] {ticker} 예측 중...')
            rec = run_chart_predict_single(ticker)
            if rec:
                results.append(rec)
                print(f'  [{i+1}/{len(CHART_TICKERS)}] {ticker} 완료')
            else:
                print(f'  [{i+1}/{len(CHART_TICKERS)}] {ticker} 데이터 없음, 건너뜀')
        except Exception as e:
            print(f'  [{i+1}/{len(CHART_TICKERS)}] {ticker} 실패: {e}')
        # yfinance 속도 제한 방지
        if i < len(CHART_TICKERS) - 1:
            time.sleep(1)
    return results
