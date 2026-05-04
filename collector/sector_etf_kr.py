"""한국 섹터 ETF 가격·PER/PBR 수집기 (KODEX·TIGER 10종).

미국 SPDR 13개와 1:1 매핑은 어려워 안정적인 10개로 출발.
나머지(XLI/XLU/XLC) 는 한국 섹터 ETF 가 부족하거나 KOSPI200 흡수.
"""

from __future__ import annotations

import datetime as _dt
from datetime import date

import pandas as pd


# ── 미국 SPDR ↔ 한국 KODEX/TIGER 매핑 ─────────────────────────────
# 한국 섹터 ETF 는 ticker = 6자리 종목코드 (문자열).
# kr_name 은 화면 표시용 한국어, en_name 은 LLM 입력용 영문.
SECTOR_ETF_KR = {
    '139260': {'kr_name': 'IT',          'en_name': 'Technology',     'us_proxy': 'XLK'},   # TIGER 200 IT
    '091160': {'kr_name': '반도체',       'en_name': 'Semiconductor',  'us_proxy': 'SOXX'},  # KODEX 반도체
    '300610': {'kr_name': '게임산업',     'en_name': 'Software/Game',  'us_proxy': 'IGV'},   # KODEX 게임산업
    '091170': {'kr_name': '은행',        'en_name': 'Financials',     'us_proxy': 'XLF'},   # KODEX 은행
    '139250': {'kr_name': '에너지화학',    'en_name': 'Energy/Chemical','us_proxy': 'XLE'},   # TIGER 200 에너지화학
    '266420': {'kr_name': '헬스케어',     'en_name': 'Healthcare',     'us_proxy': 'XLV'},   # KODEX 헬스케어
    '091180': {'kr_name': '자동차',       'en_name': 'Auto',           'us_proxy': 'XLY'},   # KODEX 자동차
    '117680': {'kr_name': '철강',        'en_name': 'Steel/Materials','us_proxy': 'XLB'},   # KODEX 철강
    '341850': {'kr_name': '리츠',        'en_name': 'REIT',           'us_proxy': 'XLRE'},  # TIGER 리츠부동산인프라
    '227560': {'kr_name': '필수소비재',    'en_name': 'Staples',        'us_proxy': 'XLP'},   # TIGER 200 생활소비재
}

# KR 사용자 자주 보유 ETF — sector_cycle.holding_perf 산출용 (US 의 ALL_HOLDINGS 등가)
ALL_HOLDINGS_KR = [
    '069500',  # KODEX 200
    '102110',  # TIGER 200
    '226490',  # KODEX KOSPI
    '232080',  # TIGER 코스닥150
    '229200',  # KODEX 코스닥150
    '278530',  # KODEX 200TR
    '360750',  # TIGER 미국S&P500
    '252670',  # KODEX 200선물인버스2X
]


def _etf_ohlcv_dual_source(ticker: str, days: int) -> pd.DataFrame:
    """ETF OHLCV — pykrx 우선, 실패 시 FDR 폴백 (한글 컬럼 통일)."""
    try:
        from pykrx import stock
        end = _dt.date.today().strftime('%Y%m%d')
        start = (_dt.date.today() - _dt.timedelta(days=days * 2)).strftime('%Y%m%d')
        df = stock.get_etf_ohlcv_by_date(start, end, ticker)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    # FDR 폴백
    try:
        import FinanceDataReader as fdr
        end = _dt.date.today()
        start = end - _dt.timedelta(days=days * 2)
        df = fdr.DataReader(ticker, start, end)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.rename(columns={
            'Open': '시가', 'High': '고가', 'Low': '저가',
            'Close': '종가', 'Volume': '거래량',
        })
    except Exception as e:
        print(f"[SectorETF-KR] {ticker} FDR 폴백 실패: {e}")
        return pd.DataFrame()


def fetch_sector_etf_prices_kr(days: int = 252) -> dict[str, pd.DataFrame]:
    """10개 KODEX/TIGER 섹터 ETF 일별 OHLCV (pykrx → FDR 폴백)."""
    out = {}
    for ticker in SECTOR_ETF_KR.keys():
        df = _etf_ohlcv_dual_source(ticker, days)
        if df is not None and not df.empty:
            out[ticker] = df
    return out


def fetch_sector_etf_returns_kr(macro_start: str,
                                 etf_start: str = '2010-01-01'
                                 ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """KR 섹터 10종 + 사용자 보유 ETF 8종 월별 수익률.

    US fetch_sector_etf_returns 의 KR 등가. 차이: pykrx → FDR 폴백 + 한글 컬럼.

    Args:
        macro_start: macro DataFrame 의 시작일 (ISO 'YYYY-MM-DD')
        etf_start: ETF 데이터 시작 하한 (KR 일부 ETF 상장 후 < 5년)

    Returns: (sector_ret, holding_ret) — 월별 수익률 DataFrame 쌍 (월초 인덱스)
    """
    import datetime as _dt2

    sector_tickers = list(SECTOR_ETF_KR.keys())
    all_tickers = sector_tickers + ALL_HOLDINGS_KR

    start_str = max(macro_start, etf_start)
    start_date = _dt2.date.fromisoformat(start_str)
    end_date = _dt2.date.today()
    days = max(60, (end_date - start_date).days + 1)

    print(f'[SectorETF-KR] {len(all_tickers)}개 종목 다운로드 (시작: {start_str})')

    frames: dict[str, pd.Series] = {}
    for ticker in all_tickers:
        try:
            df = _etf_ohlcv_dual_source(ticker, days)
            if df is None or df.empty or '종가' not in df.columns:
                print(f'  ✗ {ticker}: 데이터 없음')
                continue
            close = df['종가'].astype(float)
            close.index = pd.to_datetime(close.index)
            if close.index.tz is not None:
                close.index = close.index.tz_localize(None)
            frames[ticker] = close
            print(f'  ✓ {ticker}: {len(close)}일')
        except Exception as e:
            print(f'  ✗ {ticker}: {e}')

    if not frames:
        print('[SectorETF-KR] 모든 종목 fetch 실패 — 빈 DF 반환')
        return pd.DataFrame(), pd.DataFrame()

    raw = pd.DataFrame(frames).sort_index()
    monthly_prices = raw.resample('MS').last()
    monthly_returns = monthly_prices.pct_change()

    sector_ret = monthly_returns[[c for c in sector_tickers if c in monthly_returns.columns]]
    holding_ret = monthly_returns[[c for c in ALL_HOLDINGS_KR if c in monthly_returns.columns]]

    print(f'[SectorETF-KR] 수집 완료: 섹터 {sector_ret.shape}, 보유 {holding_ret.shape}')
    return sector_ret, holding_ret


def _fetch_kospi_market_per_pbr() -> tuple[float | None, float | None]:
    """KOSPI 시장 평균 PER/PBR (fallback 용)."""
    try:
        from collector.market_data_kr import fetch_kospi_per_pbr
        df = fetch_kospi_per_pbr(days=14)
        if df is None or df.empty:
            return None, None
        per = float(df['PER'].dropna().iloc[-1]) if 'PER' in df.columns and not df['PER'].dropna().empty else None
        pbr = float(df['PBR'].dropna().iloc[-1]) if 'PBR' in df.columns and not df['PBR'].dropna().empty else None
        return per, pbr
    except Exception as e:
        print(f'[sector_valuation_kr] KOSPI PER/PBR fetch 실패: {e}')
        return None, None


def _fetch_all_stock_fundamentals(ref_date: str) -> dict:
    """KOSPI 전체 종목 PER/PBR 1회 호출 — pykrx.get_market_fundamental.

    Returns: {stock_code: {'per': float, 'pbr': float}, ...}
    적자(per≤0)/부재 종목은 dict 에 포함 안 됨 — 호출측에서 covered 비중으로 판단.
    """
    out = {}
    try:
        from pykrx import stock
        for market in ('KOSPI', 'KOSDAQ'):
            try:
                df = stock.get_market_fundamental(ref_date, market=market)
                if df is None or df.empty:
                    continue
                for code, row in df.iterrows():
                    try:
                        per = float(row.get('PER', 0))
                        pbr = float(row.get('PBR', 0))
                    except (TypeError, ValueError):
                        continue
                    entry = {}
                    if per > 0:
                        entry['per'] = per
                    if pbr > 0:
                        entry['pbr'] = pbr
                    if entry:
                        out[str(code)] = entry
            except Exception as e:
                print(f'[sector_valuation_kr] {market} fundamental fetch 실패: {e}')
    except Exception as e:
        print(f'[sector_valuation_kr] pykrx import 실패: {e}')
    return out


def _weighted_avg(holdings: list[dict], stock_fund: dict, key: str) -> tuple[float | None, float]:
    """비중 가중평균 (적자·부재 종목 제외 후 비중 재정규화).

    Returns: (weighted_value | None, coverage_ratio 0~1)
    """
    if not holdings:
        return None, 0.0
    total_w = sum(h.get('weight', 0) for h in holdings)
    if total_w <= 0:
        return None, 0.0
    valid_sum = 0.0      # Σ(w_i × value_i)
    valid_w = 0.0        # Σ(w_i for valid)
    for h in holdings:
        sc = h.get('stock_code')
        w = h.get('weight', 0)
        if w <= 0 or sc not in stock_fund or key not in stock_fund[sc]:
            continue
        valid_sum += w * stock_fund[sc][key]
        valid_w += w
    if valid_w <= 0:
        return None, 0.0
    return valid_sum / valid_w, valid_w / total_w


def fetch_sector_etf_per_pbr_kr(today: date | None = None) -> list[dict]:
    """각 KR 섹터 ETF 의 PDF 가중평균 PER/PBR.

    1) ETF holdings (주 1회 캐시) 로드 — collector/etf_holdings_kr
    2) KOSPI/KOSDAQ 전체 종목 PER/PBR 1회 fetch — pykrx.get_market_fundamental
    3) ETF 별 가중평균: Σ(w_i × per_i) / Σ(w_i) for valid i (적자/부재 제외 후 정규화)
    4) coverage < 50% 이거나 holdings 빈 ETF 는 KOSPI 평균 fallback (per_ticker fallback)

    Args:
        today: 기준일 (None=오늘)

    Returns:
        list of {date, ticker, sector_name, per, pbr}
    """
    today = today or date.today()
    today_str = today.isoformat()
    ref_date = today.strftime('%Y%m%d')

    # 1) holdings 캐시 (주 1회)
    try:
        from collector.etf_holdings_kr import fetch_etf_holdings_kr
        holdings_bundle = fetch_etf_holdings_kr()
    except Exception as e:
        print(f'[sector_valuation_kr] holdings 로드 실패: {e}')
        holdings_bundle = {}

    # 2) 전체 종목 PER/PBR 1회 fetch
    stock_fund = _fetch_all_stock_fundamentals(ref_date)
    print(f'[sector_valuation_kr] 종목 fundamental: {len(stock_fund)}개 종목')

    # 3) fallback 용 시장 평균
    market_per, market_pbr = _fetch_kospi_market_per_pbr()

    # 4) ETF 별 가중평균
    out = []
    coverage_list = []
    fallback_count = 0
    for ticker, meta in SECTOR_ETF_KR.items():
        holdings = holdings_bundle.get(ticker, []) if isinstance(holdings_bundle, dict) else []
        per_val, per_cov = _weighted_avg(holdings, stock_fund, 'per')
        pbr_val, pbr_cov = _weighted_avg(holdings, stock_fund, 'pbr')
        avg_cov = (per_cov + pbr_cov) / 2

        # coverage < 50% 또는 holdings 빈 → KOSPI 평균 fallback
        if avg_cov < 0.5 or per_val is None:
            per_val = market_per
            pbr_val = market_pbr
            fallback_count += 1
            print(f'[sector_valuation_kr] {ticker} fallback (coverage {avg_cov*100:.0f}%)')
        else:
            coverage_list.append(avg_cov)

        out.append({
            'date': today_str,
            'ticker': ticker,
            'sector_name': meta['en_name'],
            'per': round(per_val, 2) if per_val is not None else None,
            'pbr': round(pbr_val, 2) if pbr_val is not None else None,
        })

    avg_coverage = (sum(coverage_list) / len(coverage_list) * 100) if coverage_list else 0
    print(f'[sector_valuation_kr] {len(out)}건 적재 — '
          f'PDF 가중평균 {len(out)-fallback_count}건 (coverage avg {avg_coverage:.0f}%), '
          f'fallback {fallback_count}건')
    return out
