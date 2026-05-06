"""KR 섹터 ETF PER 10년 백필 — DART 사업보고서 + yfinance close 조합.

흐름:
1. ETF holdings (현재 캐시) 의 union 종목 list 추출
2. 종목별 yfinance .KS close 10년 시계열 (월말 resample)
3. 종목별 DART 사업보고서 net_income — 연도별 10년
4. 종목별 발행주식수 = yfinance sharesOutstanding (현재값, 과거 변동 무시)
5. 월별 종목별 PER = (close × shares) / 그 시점 가용 사업보고서 net_income
   - 4월 이전이면 2년 전 사업보고서, 4월 이후면 전년 사업보고서 (공시 lookahead 회피)
6. ETF 별 가중평균 PER (현재 holdings 비중 적용 — 과거 holdings 변동 무시)
7. DB sector_valuation 적재

한계 (단순화):
- 과거 holdings 변동 무시 (현재 캐시 사용)
- 과거 shares 변동 무시 (yfinance 현재값)
- PBR 은 후속 (PER 만)
- 비현실 PER (>100) 제외

사용:
    python -m scripts.backfill_kr_sector_valuation [--years 10] [--ticker 091160]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description='KR 섹터 ETF PER 10년 백필')
    parser.add_argument('--years', type=int, default=10)
    parser.add_argument('--ticker', type=str, default=None,
                        help='특정 ETF 만 백필 (예: 091160). 기본 전체.')
    parser.add_argument('--dry-run', action='store_true', help='DB 적재 X')
    args = parser.parse_args()

    print('═' * 60)
    print(f'  KR 섹터 ETF PER 백필 — {args.years}년')
    print('═' * 60)

    # 1) ETF holdings
    from collector.etf_holdings_kr import fetch_etf_holdings_kr
    from collector.sector_etf_kr import SECTOR_ETF_KR
    holdings = fetch_etf_holdings_kr()
    sector_etfs = [t for t in SECTOR_ETF_KR.keys()]
    if args.ticker:
        if args.ticker not in sector_etfs:
            print(f'[FATAL] {args.ticker} not in SECTOR_ETF_KR')
            return 1
        sector_etfs = [args.ticker]

    # 2) holdings union → 종목 set
    all_codes = set()
    for t in sector_etfs:
        h = holdings.get(t, [])
        if isinstance(h, list):
            for it in h:
                sc = it.get('stock_code')
                if sc:
                    all_codes.add(sc)
    all_codes = sorted(all_codes)
    print(f'[Backfill] holdings union: {len(all_codes)} 종목')
    if not all_codes:
        print('[FATAL] holdings 비어있음 — etf_holdings_kr.json 캐시 확인')
        return 1

    # 3) yfinance close + sharesOutstanding 한 번에 fetch
    end = date.today()
    start = end - timedelta(days=args.years * 365 + 30)
    close_df = pd.DataFrame()
    shares_dict = {}
    for sc in all_codes:
        try:
            ticker = yf.Ticker(f'{sc}.KS')
            df = ticker.history(start=start, end=end, auto_adjust=False)
            if df is not None and not df.empty:
                # tz-aware 인덱스 → naive 변환
                idx = df.index
                if hasattr(idx, 'tz') and idx.tz is not None:
                    df.index = idx.tz_localize(None)
                close_df[sc] = df['Close']
            info = ticker.info
            shares = info.get('sharesOutstanding')
            if shares and shares > 0:
                shares_dict[sc] = float(shares)
        except Exception as e:
            print(f'[Backfill] {sc} yfinance 실패: {e}')
    monthly_close = close_df.resample('MS').last() if not close_df.empty else pd.DataFrame()
    print(f'[Backfill] yfinance close: {monthly_close.shape[1]} 종목, {monthly_close.shape[0]} 월')
    print(f'[Backfill] shares: {len(shares_dict)} 종목')

    # 4) DART 사업보고서 — 종목별 × 연도별
    from collector.dart_fundamentals import (
        _load_corp_codes, _fetch_acnt, _extract_amount,
        _NI_NAMES, _REPRT_FY,
    )
    corp_codes = _load_corp_codes()
    dart_ni = {}   # {stock_code: {year: net_income}}
    target_years = list(range(end.year - args.years, end.year))
    print(f'[Backfill] DART 사업보고서 fetch — {len(all_codes)} 종목 × {len(target_years)} 연도 '
          f'= ~{len(all_codes) * len(target_years)} 호출 (수 분 소요)...')
    fetch_count = 0
    for sc in all_codes:
        cc = corp_codes.get(sc)
        if not cc:
            continue
        for year in target_years:
            items = _fetch_acnt(cc, year, _REPRT_FY, fs_div='CFS')
            if not items:
                items = _fetch_acnt(cc, year, _REPRT_FY, fs_div='OFS')
            fetch_count += 1
            if fetch_count % 100 == 0:
                print(f'  ... {fetch_count}/{len(all_codes) * len(target_years)} fetch')
            if not items:
                continue
            ni = _extract_amount(items, _NI_NAMES, 'IS')
            if ni is None:
                ni = _extract_amount(items, _NI_NAMES, 'CIS')
            if ni is not None and ni > 0:
                dart_ni.setdefault(sc, {})[year] = ni
            time.sleep(0.05)   # rate limit 보호 (일 20K 한도이지만 안전)
    print(f'[Backfill] DART net_income: {len(dart_ni)} 종목')

    # 5) 월별 종목별 PER
    per_by_stock = {}   # {stock_code: pd.Series(index=ym, val=per)}
    for sc in dart_ni.keys():
        if sc not in shares_dict or sc not in monthly_close.columns:
            continue
        per_series = {}
        for ym, close_val in monthly_close[sc].dropna().items():
            if pd.isna(close_val) or close_val <= 0:
                continue
            year = ym.year
            month = ym.month
            avail_year = year - 1 if month >= 4 else year - 2
            ni = dart_ni[sc].get(avail_year)
            if not ni or ni <= 0:
                continue
            cap = float(close_val) * shares_dict[sc]
            per = cap / ni
            if per <= 0 or per > 100:
                continue
            per_series[ym] = per
        if per_series:
            per_by_stock[sc] = pd.Series(per_series)
    print(f'[Backfill] 종목별 PER 시계열: {len(per_by_stock)} 종목')

    # 6) ETF 별 가중평균 PER 시계열
    from collector.sector_etf_kr import SECTOR_ETF_KR
    rows = []
    for etf_ticker in sector_etfs:
        h = holdings.get(etf_ticker, [])
        if not isinstance(h, list) or not h:
            continue
        # 종목별 PER 시계열 합집합 month index
        all_months = set()
        for it in h:
            sc = it.get('stock_code')
            if sc in per_by_stock:
                all_months.update(per_by_stock[sc].index)
        all_months = sorted(all_months)
        for ym in all_months:
            valid_sum = 0.0
            valid_w = 0.0
            for it in h:
                sc = it.get('stock_code')
                w = it.get('weight', 0)
                if w <= 0:
                    continue
                if sc not in per_by_stock or ym not in per_by_stock[sc].index:
                    continue
                per = float(per_by_stock[sc][ym])
                valid_sum += w * per
                valid_w += w
            if valid_w <= 0:
                continue
            etf_per = valid_sum / valid_w
            rows.append({
                'date': str(ym.date()),
                'ticker': etf_ticker,
                'sector_name': SECTOR_ETF_KR[etf_ticker]['en_name'],
                'per': round(etf_per, 2),
                'pbr': None,
            })
    print(f'[Backfill] 적재할 row: {len(rows)} (예: {rows[0] if rows else "없음"})')

    # 7) DB upsert
    if args.dry_run:
        print('[Backfill] --dry-run, DB 적재 건너뜀')
        return 0
    if not rows:
        print('[Backfill] row 0건, 적재 건너뜀')
        return 0
    from database.repositories import upsert_sector_valuation
    CHUNK = 200
    for i in range(0, len(rows), CHUNK):
        upsert_sector_valuation(rows[i:i + CHUNK], region='kr')
    print(f'[Backfill] DB 적재 완료 ({len(rows)}건)')

    # 8) app_cache 갱신
    from api.routers.sector_cycle import precompute_valuation
    precompute_valuation('kr')
    print('[Backfill] app_cache 갱신 완료')
    return 0


if __name__ == '__main__':
    sys.exit(main())
