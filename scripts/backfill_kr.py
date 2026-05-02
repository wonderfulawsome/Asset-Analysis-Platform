"""한국 시장 30일 macro_raw + index_price_raw 백필 스크립트.

사용:
    python -m scripts.backfill_kr               # 30일 백필
    python -m scripts.backfill_kr --days 90     # 사용자 지정

실행 후 region='kr' 행이 macro_raw 와 index_price_raw 에 적재됨.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from collector.market_data_kr import (
    compute_kr_macro_history, fetch_kr_index_prices_today,
)
from collector.sector_etf_kr import fetch_sector_etf_prices_kr, SECTOR_ETF_KR
from collector.valuation_signal_kr import backfill_valuation_signal_kr
from database.repositories import (
    upsert_macro, upsert_index_prices, upsert_valuation_signal_bulk,
)


def backfill_macro(days: int):
    print(f'[KR-Backfill] macro {days}일 적재 시작...')
    records = compute_kr_macro_history(days=days)
    if not records:
        print('[KR-Backfill] macro 데이터 없음')
        return 0
    upsert_macro(records, region='kr')
    print(f'[KR-Backfill] macro {len(records)}건 적재 완료')
    return len(records)


def backfill_index_prices_today():
    """오늘자 KR 주요 ETF 가격 (KODEX 200, TIGER 200 등)."""
    print('[KR-Backfill] index_price_raw 적재 시작...')
    rows = fetch_kr_index_prices_today()
    if not rows:
        print('[KR-Backfill] index 데이터 없음')
        return 0
    upsert_index_prices(rows, region='kr')
    print(f'[KR-Backfill] index_price {len(rows)}건 적재 완료')
    return len(rows)


def backfill_sector_etfs_today():
    """오늘자 KODEX/TIGER 10종 섹터 ETF 가격 → index_price_raw 적재 (name/volume 컬럼 없음)."""
    print('[KR-Backfill] sector ETF 적재 시작...')
    by_ticker = fetch_sector_etf_prices_kr(days=10)
    if not by_ticker:
        print('[KR-Backfill] 섹터 ETF 데이터 없음')
        return 0
    rows = []
    for ticker, df in by_ticker.items():
        if df is None or df.empty or len(df) < 2:
            continue
        try:
            last = df.iloc[-1]
            prev = df.iloc[-2]
            close = float(last['종가'])
            change_pct = round((close - float(prev['종가'])) / float(prev['종가']) * 100, 2)
            rows.append({
                'date': df.index[-1].strftime('%Y-%m-%d'),
                'ticker': ticker,
                'close': close,
                'change_pct': change_pct,
            })
        except Exception as e:
            print(f"[KR-Backfill-Sector] {ticker} 처리 실패: {e}")
    if not rows:
        return 0
    upsert_index_prices(rows, region='kr')
    print(f'[KR-Backfill] sector ETF {len(rows)}건 적재 완료')
    return len(rows)


def backfill_valuation(days: int):
    """valuation_signal 시계열 backfill — composite z 기반 라벨 포함."""
    print(f'[KR-Backfill] valuation_signal {days}일 적재 시작...')
    rows = backfill_valuation_signal_kr(days=days)
    if not rows:
        print('[KR-Backfill] valuation_signal 데이터 없음')
        return 0
    upsert_valuation_signal_bulk(rows, region='kr')
    print(f'[KR-Backfill] valuation_signal {len(rows)}건 적재 완료')
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description='KR 시장 데이터 백필')
    parser.add_argument('--days', type=int, default=90, help='백필 일수 (default 90 — valuation 차트 90일 매칭)')
    args = parser.parse_args()

    macro_n = backfill_macro(args.days)
    idx_n = backfill_index_prices_today()
    sec_n = backfill_sector_etfs_today()
    val_n = backfill_valuation(args.days)

    print(f'\n[KR-Backfill 완료] macro={macro_n}, index={idx_n}, sector={sec_n}, valuation={val_n}')


if __name__ == '__main__':
    main()
