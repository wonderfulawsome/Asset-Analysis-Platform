"""NeuralProphet 기반 ETF 30일 주가 예측 (스케줄러 배치 실행용).

전체 파이프라인(3시간 주기)에서 16개 ETF 티커별로 NeuralProphet 모델을 학습하고,
30일 영업일 예측 결과를 DB에 저장한다.
NeuralProphet은 자동회귀(AR) 기능으로 최근 가격 패턴을 직접 학습하여
기존 Prophet보다 단기 예측 정확도가 높다.
"""

import datetime
import json
import time
import yfinance as yf
import pandas as pd

# 예측 대상 ETF 티커 (chart.py의 CHART_TICKERS와 동일)
CHART_TICKERS = ['SPY', 'QQQ', 'DIA', 'IWM', 'VTI', 'VOO', 'SOXX', 'SMH',
                 'XLK', 'XLF', 'XLE', 'XLV', 'ARKK', 'GLD', 'TLT', 'SCHD']


def run_chart_predict_single(ticker: str) -> dict | None:
    """단일 티커에 대해 NeuralProphet 30일 예측을 실행한다."""
    from neuralprophet import NeuralProphet, set_log_level
    set_log_level("ERROR")

    # 최근 5년 일봉 다운로드
    df = yf.download(ticker, period='5y', interval='1d',
                     auto_adjust=True, progress=False)
    if df.empty:
        return None

    if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
        df.columns = df.columns.get_level_values(0)

    # ds(날짜) y(종가) 형식으로 변환
    ndf = df[['Close']].reset_index()
    ndf.columns = ['ds', 'y']
    ndf['ds'] = pd.to_datetime(ndf['ds'])

    # NeuralProphet 모델
    # n_lags=30: 최근 30일 가격을 자동회귀 입력으로 사용 (Prophet에 없는 핵심 기능)
    # n_forecasts=30: 30 영업일 미래를 한번에 예측
    # quantiles: 80% 신뢰구간 (10%, 90% 분위수)
    model = NeuralProphet(
        n_lags=30,
        n_forecasts=30,
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoints_range=0.95,
        trend_reg=0.1,
        learning_rate=0.01,
        epochs=100,
        batch_size=64,
        quantiles=[0.1, 0.9],
    )

    model.fit(ndf, freq='B')
    forecast = model.predict(ndf)

    # 최근 30일 실제 종가
    recent = ndf.tail(30)
    actual = [{'date': str(r.ds.date()), 'close': round(float(r.y), 2)}
              for _, r in recent.iterrows()]

    # 마지막 행에서 30-step 예측 추출
    last_row = forecast.iloc[-1]
    last_date = pd.to_datetime(last_row['ds'])
    predicted = []

    for step in range(1, 31):
        col_yhat = f'yhat{step}'
        col_lower = f'yhat{step} 10.0%'
        col_upper = f'yhat{step} 90.0%'

        if col_yhat not in forecast.columns:
            break

        yhat = float(last_row[col_yhat])
        future_date = last_date + pd.tseries.offsets.BDay(step)

        # 신뢰구간: quantile 컬럼이 있으면 사용, 없으면 ±5% 추정
        if col_lower in forecast.columns and col_upper in forecast.columns:
            lower = float(last_row[col_lower])
            upper = float(last_row[col_upper])
        else:
            lower = yhat * 0.95
            upper = yhat * 1.05

        predicted.append({
            'date': str(future_date.date()),
            'yhat': round(yhat, 2),
            'lower': round(lower, 2),
            'upper': round(upper, 2),
        })

    del model

    return {
        'date': str(datetime.date.today()),
        'ticker': ticker,
        'actual': json.dumps(actual, ensure_ascii=False),
        'predicted': json.dumps(predicted, ensure_ascii=False),
    }


def run_chart_predict_all() -> list[dict]:
    """16개 ETF 티커 전체에 대해 NeuralProphet 예측을 실행한다."""
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