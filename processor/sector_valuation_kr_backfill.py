"""KR sector_valuation 5년 월별 historical backfill.

US sector_valuation_backfill 의 KR 등가. 차이:
- yfinance ETF.info → KOSPI 시장 평균 PER/PBR (collector/sector_etf_kr 의 1차 fallback)
- yfinance history → pykrx ETF OHLCV (이미 _etf_ohlcv_dual_source 재사용)

PER/PBR proxy 공식 (US 와 동일):
    PER_t ≈ PER_today × (Close_t / Close_today)
    PBR_t ≈ PBR_today × (Close_t / Close_today)

⚠️ 1차 fallback (KOSPI 시장 평균 동일 적용) 의 한계:
   ticker별 PER 변별력이 약함 (모든 섹터 같은 today PER × 가격 비율). z-score는 가격 비율의 순수
   상대값으로만 의미. 정확한 ticker별 가중평균은 Stage 2 (pykrx ETF holdings) 로 분리.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from collector.sector_etf_kr import (
    SECTOR_ETF_KR, _etf_ohlcv_dual_source, fetch_sector_etf_per_pbr_kr,
)
from database.repositories import upsert_sector_valuation


def backfill_sector_valuations_kr(months: int = 60) -> int:
    """10 KR sector ETF 의 PER/PBR proxy 시계열을 월별로 sector_valuation 에 upsert (region='kr').

    반환: 총 upsert 한 행 수.
    """
    # 1) 오늘 기준 KR 시장 평균 PER/PBR (모든 섹터 동일 today값)
    today_rows = fetch_sector_etf_per_pbr_kr()
    if not today_rows:
        print('[KR-backfill] today PER/PBR fetch 실패 — backfill 중단')
        return 0
    # ticker → today PER/PBR 매핑
    today_map = {r['ticker']: (r.get('per'), r.get('pbr'), r.get('sector_name'))
                 for r in today_rows}

    days = months * 31 + 60
    total_rows: list[dict] = []

    for ticker in SECTOR_ETF_KR.keys():
        per_today, pbr_today, sector_name = today_map.get(
            ticker, (None, None, SECTOR_ETF_KR[ticker]['en_name']))
        if per_today is None and pbr_today is None:
            print(f"[KR-backfill] {ticker} today PER/PBR 둘 다 None — skip")
            continue

        try:
            df = _etf_ohlcv_dual_source(ticker, days)
        except Exception as e:
            print(f"[KR-backfill] {ticker} OHLCV 실패: {e}")
            continue
        if df is None or df.empty or '종가' not in df.columns:
            print(f"[KR-backfill] {ticker} 가격 시계열 없음")
            continue

        close = df['종가'].astype(float).dropna()
        close.index = pd.to_datetime(close.index)
        if close.index.tz is not None:
            close.index = close.index.tz_localize(None)

        # 월말 종가만
        monthly = close.resample('MS').last().dropna().tail(months)
        if monthly.empty:
            continue

        close_today = float(monthly.iloc[-1])
        if close_today <= 0:
            continue

        for ts, c in monthly.items():
            cf = float(c)
            if cf <= 0:
                continue
            ratio = cf / close_today
            per_t = float(per_today) * ratio if per_today is not None else None
            pbr_t = float(pbr_today) * ratio if pbr_today is not None else None
            total_rows.append({
                "date": ts.date().isoformat(),
                "ticker": ticker,
                "sector_name": sector_name,
                "per": round(per_t, 2) if per_t is not None else None,
                "pbr": round(pbr_t, 2) if pbr_t is not None else None,
            })

    if not total_rows:
        print("[KR-backfill] upsert 대상 0행")
        return 0

    CHUNK = 200
    for i in range(0, len(total_rows), CHUNK):
        upsert_sector_valuation(total_rows[i:i + CHUNK], region='kr')

    print(f"[KR-backfill] 총 {len(total_rows)} 행 upsert 완료 (10 ETF × ~{months}개월)")
    return len(total_rows)


if __name__ == "__main__":
    backfill_sector_valuations_kr(months=60)
