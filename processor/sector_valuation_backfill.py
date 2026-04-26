"""sector_valuation 5년 월별 historical backfill.

yfinance 는 ETF 의 historical PER/PBR 을 직접 제공하지 않음 (Ticker.info 는 today 값만).
ETF 의 holdings 가중평균을 분기별로 reconstruct 하는 정확한 방법은 너무 복잡 →
**가격 비율 proxy** 로 시계열 추정:

    PER_t ≈ PER_today × (Close_t / Close_today)
    PBR_t ≈ PBR_today × (Close_t / Close_today)

가정: EPS / BVPS 가 5년 윈도우 내에서 비교적 안정적. 실제로는 EPS 가 성장하는 ETF 일수록
PER 시계열이 과대 변동 (실제 PER 보다 가격 영향만 반영) 하므로 정확도 한계 명확.
그래도 "오늘이 historical 평균 대비 비싼가/싼가" z-score 신호엔 충분.

월말 종가 기준 60개월 → 12 ETF 합계 720 행을 sector_valuation 테이블에 upsert.
"""
from datetime import date

import pandas as pd
import yfinance as yf

from collector.sector_valuation import SECTOR_VALUATION_ETFS
from database.repositories import upsert_sector_valuation


def backfill_sector_valuations(months: int = 60) -> int:
    """12 ETF 의 PER/PBR proxy 시계열을 월별로 sector_valuation 에 upsert.

    반환: 총 upsert 한 행 수.
    """
    period = f"{max(months // 12 + 1, 5)}y"   # 안전하게 1년 여유
    total_rows: list[dict] = []

    for ticker, sector_name in SECTOR_VALUATION_ETFS.items():
        try:
            yt = yf.Ticker(ticker)
            info = yt.info
            per_today = info.get("trailingPE")
            pbr_today = info.get("priceToBook")
            hist = yt.history(period=period, interval="1mo", auto_adjust=False)
        except Exception as e:
            print(f"[backfill] {ticker} 실패: {e}")
            continue

        if hist is None or hist.empty:
            print(f"[backfill] {ticker} 가격 시계열 없음")
            continue
        if per_today is None and pbr_today is None:
            print(f"[backfill] {ticker} info 에 PER/PBR 모두 None")
            continue

        # 마지막 행 = "today" 기준점. Close_today 로 나누어 비율 산출.
        close_today = float(hist["Close"].iloc[-1])
        if close_today <= 0:
            continue

        # 월말 행만 추출 (yfinance interval=1mo 는 이미 월별 첫날 기준 → resample 로 말일 통일)
        monthly = hist["Close"].dropna()
        # 마지막 60개월만
        monthly = monthly.iloc[-months:]

        for ts, close in monthly.items():
            close_f = float(close)
            if close_f <= 0:
                continue
            ratio = close_f / close_today
            per_t = float(per_today) * ratio if per_today is not None else None
            pbr_t = float(pbr_today) * ratio if pbr_today is not None else None
            d = (ts.date() if hasattr(ts, 'date') else ts).isoformat()
            total_rows.append({
                "date": d,
                "ticker": ticker,
                "sector_name": sector_name,
                "per": per_t,
                "pbr": pbr_t,
            })

    if not total_rows:
        print("[backfill] upsert 대상 0행 — 실패")
        return 0

    # 청크로 나눠 upsert (Supabase 의 한 번 요청 페이로드 제한 회피)
    CHUNK = 200
    for i in range(0, len(total_rows), CHUNK):
        upsert_sector_valuation(total_rows[i:i + CHUNK])

    print(f"[backfill] 총 {len(total_rows)} 행 upsert 완료 (12 ETF × ~{months}개월)")
    return len(total_rows)


if __name__ == "__main__":
    backfill_sector_valuations(months=60)
