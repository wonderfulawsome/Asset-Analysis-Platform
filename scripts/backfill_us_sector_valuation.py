"""US 13 SPDR ETF per_weighted 10년 백필 — yfinance close × shares × quarterly EPS.

KR backfill_kr_sector_valuation 패턴을 US 로 차용.
yfinance 의 미국 종목 fundamental 이 잘 동작 → DART 없이 yfinance 만으로:
  - close 시계열 (월말 resample)
  - sharesOutstanding (현재값, 과거 변동 무시)
  - quarterly_earnings → TTM EPS 시계열 (지난 4분기 합산)

흐름:
1. ETF holdings 캐시 (현재 — 과거 holdings 변동 무시)
2. unique 종목 list
3. 종목별 close 10년 + shares (yfinance)
4. 종목별 TTM EPS 시계열 (분기 EPS 4개 rolling sum, 4월 이전 lookahead 방어)
5. 종목별 시총 = close × shares
6. 종목별 PER 시계열 = 시총 / TTM EPS
7. ETF 별 가중평균 PER (현재 holdings 비중)
8. DB sector_valuation.per_weighted 컬럼 적재

한계: 과거 holdings 변동 무시, shares 현재값 고정, PER 100 cap.

사용:
    python -m scripts.backfill_us_sector_valuation [--years 10] [--ticker XLK]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description='US 섹터 ETF per_weighted 10년 백필')
    parser.add_argument('--years', type=int, default=10)
    parser.add_argument('--ticker', type=str, default=None)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print('═' * 60)
    print(f'  US 섹터 ETF per_weighted 백필 — {args.years}년')
    print('═' * 60)

    from collector.etf_holdings_us import fetch_etf_holdings_us, US_SECTOR_ETFS
    holdings = fetch_etf_holdings_us()
    sector_etfs = US_SECTOR_ETFS[:]
    if args.ticker:
        if args.ticker not in sector_etfs:
            print(f'[FATAL] {args.ticker} not in US_SECTOR_ETFS')
            return 1
        sector_etfs = [args.ticker]

    all_codes = set()
    for t in sector_etfs:
        h = holdings.get(t, [])
        if isinstance(h, list):
            for it in h:
                if it.get('stock_code'):
                    all_codes.add(it['stock_code'])
    all_codes = sorted(all_codes)
    print(f'[Backfill-US] holdings union: {len(all_codes)} 종목')
    if not all_codes:
        return 1

    end = date.today()
    start = end - timedelta(days=args.years * 365 + 30)

    # 1) 종목별 close + shares + quarterly earnings
    monthly_close = pd.DataFrame()
    shares_dict: dict[str, float] = {}
    eps_quarterly: dict[str, pd.DataFrame] = {}   # {sc: DataFrame(index=date, EPS)}
    for sc in all_codes:
        try:
            tk = yf.Ticker(sc)
            df = tk.history(start=start, end=end, auto_adjust=False)
            if df is not None and not df.empty:
                idx = df.index
                if hasattr(idx, 'tz') and idx.tz is not None:
                    df.index = idx.tz_localize(None)
                monthly_close[sc] = df['Close'].resample('MS').last()
            info = tk.info
            shares = info.get('sharesOutstanding')
            if shares and shares > 0:
                shares_dict[sc] = float(shares)
            # 분기 손익계산서 — 'Diluted EPS' 또는 'Basic EPS' 또는 net income/shares
            try:
                qe = tk.quarterly_income_stmt
                if qe is not None and not qe.empty:
                    # row: 'Diluted EPS', 'Basic EPS', 'Net Income' 등
                    eps_row = None
                    for k in ('Diluted EPS', 'Basic EPS'):
                        if k in qe.index:
                            eps_row = qe.loc[k]
                            break
                    if eps_row is None and 'Net Income' in qe.index and shares:
                        eps_row = qe.loc['Net Income'] / shares
                    if eps_row is not None:
                        eps_q = eps_row.dropna().sort_index()
                        if not eps_q.empty:
                            idx = eps_q.index
                            if hasattr(idx, 'tz') and idx.tz is not None:
                                eps_q.index = idx.tz_localize(None)
                            eps_quarterly[sc] = eps_q
            except Exception:
                pass
        except Exception as e:
            print(f'[Backfill-US] {sc} fetch 실패: {e}')

    print(f'[Backfill-US] yfinance close: {monthly_close.shape[1]} 종목, '
          f'{monthly_close.shape[0]} 월. shares: {len(shares_dict)}, EPS: {len(eps_quarterly)}')

    # 2) 종목별 PER 시계열 — 월별
    per_by_stock: dict[str, pd.Series] = {}
    for sc in eps_quarterly.keys():
        if sc not in shares_dict or sc not in monthly_close.columns:
            continue
        eps_q = eps_quarterly[sc]
        per_series = {}
        for ym, close_val in monthly_close[sc].dropna().items():
            if pd.isna(close_val) or close_val <= 0:
                continue
            # 그 시점 이전 가장 최근 4분기 합산 (TTM)
            past = eps_q[eps_q.index <= ym]
            if len(past) < 4:
                continue
            ttm_eps = float(past.tail(4).sum())
            if ttm_eps <= 0:
                continue
            per = float(close_val) / ttm_eps
            if per <= 0 or per > 100:
                continue
            per_series[ym] = per
        if per_series:
            per_by_stock[sc] = pd.Series(per_series)
    print(f'[Backfill-US] 종목별 PER 시계열: {len(per_by_stock)} 종목')

    # 3) ETF 별 가중평균 PER 시계열
    rows = []
    for etf in sector_etfs:
        h = holdings.get(etf, [])
        if not isinstance(h, list) or not h:
            continue
        all_months = set()
        for it in h:
            sc = it.get('stock_code')
            if sc in per_by_stock:
                all_months.update(per_by_stock[sc].index)
        for ym in sorted(all_months):
            valid_sum = 0.0
            valid_w = 0.0
            for it in h:
                sc = it.get('stock_code')
                w = it.get('weight', 0)
                if w <= 0 or sc not in per_by_stock or ym not in per_by_stock[sc].index:
                    continue
                valid_sum += w * float(per_by_stock[sc][ym])
                valid_w += w
            if valid_w <= 0:
                continue
            etf_per = valid_sum / valid_w
            rows.append({
                'date': str(ym.date()),
                'ticker': etf,
                'per_weighted': round(etf_per, 2),
            })
    print(f'[Backfill-US] 적재할 row: {len(rows)} (예: {rows[0] if rows else "없음"})')

    if args.dry_run:
        return 0
    if not rows:
        return 0

    # 4) DB upsert — sector_valuation 의 per_weighted 컬럼만 갱신
    # 기존 row 가 있어야 (date, ticker, region) UNIQUE 가 매칭. 없으면 sector_name 등 NULL 인 채로 새 row 생성.
    from database.repositories import upsert_sector_valuation
    # sector_name 채우기 위해 SECTOR_KR (SPDR 매핑) — 단순화: ticker 그대로
    enriched = [{'date': r['date'], 'ticker': r['ticker'],
                 'sector_name': r['ticker'],
                 'per_weighted': r['per_weighted']}
                for r in rows]
    CHUNK = 200
    for i in range(0, len(enriched), CHUNK):
        upsert_sector_valuation(enriched[i:i + CHUNK], region='us')
    print(f'[Backfill-US] DB 적재 완료 ({len(enriched)}건)')

    from api.routers.sector_cycle import precompute_valuation
    precompute_valuation('us')
    print('[Backfill-US] app_cache 갱신 완료')
    return 0


if __name__ == '__main__':
    sys.exit(main())
