"""KR 신규 섹터 ETF 사전 검증 — pykrx OHLCV + portfolio 응답 확인.

실행: python scripts/check_kr_new_tickers.py
"""
from __future__ import annotations

import datetime as _dt

# .env 자동 로드 (KRX_ID/KRX_PW 등 환경변수 의존)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

NEW_TICKERS = {
    '401170': 'K-방산',
    '305720': '2차전지산업',
    '466920': '조선해운',
    '244620': '바이오',
    '228810': '미디어컨텐츠',
    '117700': '건설',
    '098560': '통신서비스',
    '445290': 'K-로봇액티브',
}


def _check_ohlcv(ticker: str) -> tuple[bool, str]:
    try:
        from pykrx import stock
        end = _dt.date.today().strftime('%Y%m%d')
        start = (_dt.date.today() - _dt.timedelta(days=30)).strftime('%Y%m%d')
        df = stock.get_etf_ohlcv_by_date(start, end, ticker)
        if df is None or df.empty:
            return False, 'empty result'
        return True, f'{len(df)} rows, latest close={df["종가"].iloc[-1]}'
    except Exception as e:
        return False, f'error: {e}'


def _check_per(ticker: str) -> tuple[bool, str]:
    try:
        from pykrx import stock
        today = _dt.date.today().strftime('%Y%m%d')
        df = stock.get_etf_portfolio_deposit_file(today, ticker)
        if df is None or df.empty:
            return False, 'empty portfolio'
        return True, f'{len(df)} holdings'
    except Exception as e:
        return False, f'error: {e}'


def main():
    print(f"{'Ticker':<8} {'Name':<14} {'OHLCV':<8} {'OHLCV detail':<40} {'Portfolio':<10} {'Portfolio detail'}")
    print('-' * 120)
    for ticker, name in NEW_TICKERS.items():
        ok_o, det_o = _check_ohlcv(ticker)
        ok_p, det_p = _check_per(ticker)
        print(f"{ticker:<8} {name:<14} {'OK' if ok_o else 'FAIL':<8} {det_o[:38]:<40} {'OK' if ok_p else 'FAIL':<10} {det_p[:50]}")


if __name__ == '__main__':
    main()
