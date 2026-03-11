from fastapi import APIRouter
import yfinance as yf
from database.repositories import (
    fetch_fear_greed_latest,
    fetch_index_prices_latest,
    fetch_macro_latest,
)

# 마켓 오버뷰 API 라우터
router = APIRouter()


def _calc_rsi(period: int = 14) -> float:
    """SPY 종가 기반 RSI(14) 실시간 계산."""
    try:
        # 최근 30거래일 데이터로 RSI 계산
        df = yf.download('SPY', period='2mo', progress=False)
        close = df['Close'].squeeze()
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(float(rsi.iloc[-1]), 1)
    except Exception:
        return 0


@router.get('/today')
def get_market_summary_today():
    # CNN 공포·탐욕 지수 최신 1건 조회
    fg = fetch_fear_greed_latest()
    # 최근 거래일 ETF 가격 전체 조회
    prices = fetch_index_prices_latest()

    # Fear & Greed 점수와 등급 추출
    score = fg.get('score', 0) if fg else 0
    rating = fg.get('rating', '-') if fg else '-'

    # SPY(S&P500), QQQ(NASDAQ100), DIA(다우존스) 평균 일일수익률 계산
    target = {'SPY', 'QQQ', 'DIA'}
    changes = [p['change_pct'] for p in prices if p['ticker'] in target]
    avg_return = sum(changes) / len(changes) if changes else 0

    # DB에서 RSI 가져오기, 없으면 실시간 계산
    macro = fetch_macro_latest()
    rsi = macro.get('sp500_rsi') if macro else None
    if not rsi:
        rsi = _calc_rsi()
    else:
        rsi = round(float(rsi), 1)

    return {
        # CNN 공포탐욕지수
        'fear_greed': {'score': round(score), 'rating': rating},
        # 주요 3대 지수 평균 수익률
        'market_return': {'value': round(avg_return, 2)},
        # S&P500 RSI (14일)
        'rsi': rsi,
    }
