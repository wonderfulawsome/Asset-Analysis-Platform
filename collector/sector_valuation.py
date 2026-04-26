"""12개 GICS 섹터 ETF의 PER·PBR 수집 (yfinance Ticker.info).

밸류에이션 히트맵용 일별 스냅샷. trailingPE / priceToBook 만 가져오면 충분.
None 안전 처리 (info 응답에서 키 누락 흔함).
"""
from datetime import date

import yfinance as yf


SECTOR_VALUATION_ETFS: dict[str, str] = {
    "XLK":  "Technology",
    "IGV":  "Software",                # iShares Expanded Tech-Software (Tech sub-sector)
    "SOXX": "Semiconductors",          # iShares Semiconductor ETF (PHLX 반도체)
    "XLF":  "Financials",
    "XLE":  "Energy",
    "XLV":  "Health Care",
    "XLY":  "Consumer Discretionary",
    "XLI":  "Industrials",
    "XLB":  "Materials",
    "XLU":  "Utilities",
    "XLRE": "Real Estate",
    "XLC":  "Communication",
    "XLP":  "Consumer Staples",
}


def fetch_sector_valuations(today: date) -> list[dict]:
    """12개 섹터 ETF 의 PER/PBR 스냅샷.

    반환: [{date, ticker, sector_name, per, pbr}, ...]
    """
    out: list[dict] = []
    for ticker, name in SECTOR_VALUATION_ETFS.items():
        try:
            info = yf.Ticker(ticker).info  # 내부적으로 1회 HTTP
        except Exception as e:
            print(f"[sector_valuation] {ticker} info 실패: {e}")
            info = {}
        # yfinance 키는 trailingPE / priceToBook (둘 다 None 가능)
        per = info.get("trailingPE")
        pbr = info.get("priceToBook")
        out.append({
            "date": today.isoformat(),
            "ticker": ticker,
            "sector_name": name,
            "per": float(per) if per is not None else None,
            "pbr": float(pbr) if pbr is not None else None,
        })
    return out
