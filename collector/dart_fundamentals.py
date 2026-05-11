"""DART OPEN API — 한국 상장사 재무제표 기반 종목별 PER/PBR 산출.

KIS Developers (재배포 금지) / KRX OPEN API (PER 미제공) / yfinance (KR 데이터 부족)
대안으로 도입. 공시 데이터 = 공개 재배포 가능.

산출 방식 (TTM, Trailing Twelve Months):
  TTM 순이익 = 직전 사업보고서(연간) + 올해 누적 분기 - 작년 동일 분기 누적
  TTM 자본총계 = 가장 최근 분기 자본총계 (스냅샷)
  PER = 시가총액 / TTM 순이익
  PBR = 시가총액 / 자본총계

핵심 endpoint:
  - corp_code 매핑: GET /api/corpCode.xml?crtfc_key={KEY} (zip → XML)
  - 단일 회사 전체 재무: GET /api/fnlttSinglAcntAll.json
      ?crtfc_key={KEY}&corp_code={CODE}&bsns_year={Y}&reprt_code={C}&fs_div=CFS
  - 발행주식수: GET /api/stockTotqty.json (not used — 시총은 yfinance / KRX 시장가)

API 한도: 일 20,000 호출 (충분). corp_code 1년 캐시. 종목별 metrics 90일 캐시.
"""

from __future__ import annotations

import io
import json
import os
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta
from typing import Optional

import requests

# .env 자동 로드 — standalone 호출 (스케줄러 / scripts) 에서도 DART_API_KEY 인식
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


_BASE = 'https://opendart.fss.or.kr/api'
_TIMEOUT = (10, 30)

# 캐시 파일 — corp_code 매핑 + 종목별 metrics
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
_CORP_CACHE_PATH = os.path.join(_CACHE_DIR, 'dart_corp_codes.json')
_METRICS_CACHE_PATH = os.path.join(_CACHE_DIR, 'dart_kr_metrics.json')
_CORP_TTL_DAYS = 365
_METRICS_TTL_DAYS = 90

# 분기 보고서 코드
_REPRT_Q1 = '11013'   # 1분기
_REPRT_H1 = '11012'   # 반기
_REPRT_Q3 = '11014'   # 3분기
_REPRT_FY = '11011'   # 사업보고서 (연간)

# 재무제표 account_nm 매핑 — DART 응답 한글명 (영문 account_id 보다 안정적)
_NI_NAMES = {'당기순이익', '당기순이익(손실)', '연결당기순이익', '연결당기순이익(손실)'}
_EQ_NAMES = {'자본총계', '자본 총계'}


def _api_key() -> str:
    k = os.getenv('DART_API_KEY', '').strip()
    if not k:
        raise RuntimeError('DART_API_KEY 환경변수 미설정')
    return k


# ── corp_code 매핑 ─────────────────────────────────────────

def _load_corp_codes(force: bool = False) -> dict:
    """DART corp_code 전체 매핑. {stock_code: corp_code} (상장 종목만).

    1년 TTL JSON 캐시. cache miss → DART corpCode.xml zip 다운로드 → 파싱.
    """
    if not force and os.path.exists(_CORP_CACHE_PATH):
        try:
            with open(_CORP_CACHE_PATH) as f:
                cache = json.load(f)
            updated = datetime.fromisoformat(cache.get('updated_at', '2000-01-01'))
            if (datetime.now() - updated).days < _CORP_TTL_DAYS:
                return cache.get('mapping', {})
        except Exception:
            pass

    print('[DART] corp_code 다운로드 (zip ~5MB)...')
    r = requests.get(f'{_BASE}/corpCode.xml',
                     params={'crtfc_key': _api_key()},
                     timeout=_TIMEOUT)
    r.raise_for_status()
    # zip → XML 파싱
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    xml_data = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_data)
    mapping = {}
    for item in root.findall('list'):
        sc = (item.findtext('stock_code') or '').strip()
        cc = (item.findtext('corp_code') or '').strip()
        if sc and cc:
            mapping[sc] = cc
    print(f'[DART] corp_code 매핑 {len(mapping)} 종목 로드')
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_CORP_CACHE_PATH, 'w') as f:
        json.dump({'updated_at': datetime.now().isoformat(),
                   'mapping': mapping}, f, indent=2)
    return mapping


# ── 단일 보고서 fetch ───────────────────────────────────────

def _fetch_acnt(corp_code: str, year: int, reprt_code: str,
                fs_div: str = 'CFS') -> list[dict]:
    """fnlttSinglAcntAll — 단일 회사 전체 재무제표.

    fs_div: CFS=연결, OFS=별도. CFS 우선 (연결 기준이 표준).
    응답 status='000' 정상, '013' 데이터 없음, '020' 키 오류 등.
    """
    r = requests.get(f'{_BASE}/fnlttSinglAcntAll.json',
                     params={'crtfc_key': _api_key(),
                             'corp_code': corp_code,
                             'bsns_year': str(year),
                             'reprt_code': reprt_code,
                             'fs_div': fs_div},
                     timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get('status') != '000':
        return []
    return data.get('list', []) or []


def _extract_amount(items: list[dict], names: set[str], sj_div: str) -> float | None:
    """item list 에서 account_nm 매칭 + sj_div (재무제표 종류) 필터 후 thstrm_amount 반환.

    sj_div: 'IS'=손익계산서, 'BS'=재무상태표, 'CIS'=포괄손익, 'CF'=현금흐름.
    """
    for it in items:
        if it.get('sj_div') != sj_div:
            continue
        nm = (it.get('account_nm') or '').strip()
        if nm in names:
            try:
                amt = it.get('thstrm_amount') or '0'
                amt = amt.replace(',', '').replace('-', '-').strip()
                if not amt or amt == '-':
                    continue
                return float(amt)
            except (ValueError, AttributeError):
                continue
    return None


# ── 단일 종목 PER/PBR (사업보고서 우선, TTM은 후속) ────────────────

def fetch_metrics_dart(stock_code: str) -> dict | None:
    """단일 종목의 가장 최근 연간 순이익 + 자본총계.

    TTM 정공법은 _fetch_ttm_metrics 후속 함수에 — 이 함수는 사업보고서(연간) 만 사용.
    Returns: {'net_income': float, 'equity': float, 'year': int, 'reprt': '11011'} 또는 None.
    """
    mapping = _load_corp_codes()
    corp_code = mapping.get(stock_code)
    if not corp_code:
        return None

    # 가장 최근 사업보고서 (전년) — 매년 3월 말~4월 초 공시
    today = date.today()
    target_year = today.year - 1   # 작년 사업보고서
    # 4월 이전이면 2년 전 사업보고서가 가장 최근 (3월 31일 마감)
    if today.month <= 3:
        target_year = today.year - 2

    items = _fetch_acnt(corp_code, target_year, _REPRT_FY, fs_div='CFS')
    if not items:
        # 연결 없으면 별도
        items = _fetch_acnt(corp_code, target_year, _REPRT_FY, fs_div='OFS')
    if not items:
        return None

    ni = _extract_amount(items, _NI_NAMES, 'IS')   # 손익계산서 — 당기순이익
    if ni is None:
        ni = _extract_amount(items, _NI_NAMES, 'CIS')   # 포괄손익계산서 fallback
    eq = _extract_amount(items, _EQ_NAMES, 'BS')   # 재무상태표 — 자본총계
    if ni is None or eq is None:
        return None

    return {
        'net_income': ni,
        'equity': eq,
        'year': target_year,
        'reprt': _REPRT_FY,
    }


# ── 다종목 TTM PER/PBR (캐시) ───────────────────────────────

def _load_metrics_cache() -> dict:
    if not os.path.exists(_METRICS_CACHE_PATH):
        return {}
    try:
        with open(_METRICS_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_metrics_cache(cache: dict) -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_METRICS_CACHE_PATH, 'w') as f:
        json.dump(cache, f, indent=2)


def fetch_per_pbr_dart(stock_codes: list[str], market_caps: dict[str, float],
                       force_refresh: bool = False) -> dict[str, dict]:
    """다종목 PER/PBR 산출 — 사업보고서 기준 (TTM 은 후속).

    Args:
        stock_codes: 6자리 종목코드 list (ETF holdings union).
        market_caps: {stock_code: market_cap_won}. yfinance 또는 pykrx 시총.
        force_refresh: True 면 캐시 무시.

    Returns:
        {stock_code: {'per': float, 'pbr': float, 'year': int}, ...}
        시총·재무 fetch 실패한 종목은 미포함.
    """
    cache = _load_metrics_cache() if not force_refresh else {}
    cache_updated = datetime.fromisoformat(
        cache.get('updated_at', '2000-01-01')) if 'updated_at' in cache else datetime(2000, 1, 1)
    cache_fresh = (datetime.now() - cache_updated).days < _METRICS_TTL_DAYS
    metrics_cache = cache.get('metrics', {}) if cache_fresh else {}

    out = {}
    new_metrics = {}
    for sc in stock_codes:
        # 1) 캐시 hit
        m = metrics_cache.get(sc) or new_metrics.get(sc)
        if not m:
            try:
                m = fetch_metrics_dart(sc)
            except Exception as e:
                print(f'[DART] {sc} fetch 실패: {e}')
                continue
            if not m:
                continue
            new_metrics[sc] = m
        # 2) 시총
        cap = market_caps.get(sc)
        if not cap or cap <= 0:
            continue
        # 3) PER/PBR + 비현실값 cap (적자 회복기 종목 PER 폭증 방지)
        ni = m.get('net_income')
        eq = m.get('equity')
        per = cap / ni if ni and ni > 0 else None
        pbr = cap / eq if eq and eq > 0 else None
        # PER 100 초과 / PBR 20 초과는 비현실값으로 보고 제외 (가중평균 왜곡 방지)
        if per is not None and per > 100:
            per = None
        if pbr is not None and pbr > 20:
            pbr = None
        if per is None and pbr is None:
            continue
        out[sc] = {'per': per, 'pbr': pbr, 'year': m.get('year')}

    # 캐시 갱신 (새로 fetch 한 항목 추가)
    if new_metrics:
        merged = {**metrics_cache, **new_metrics}
        _save_metrics_cache({'updated_at': datetime.now().isoformat(),
                             'metrics': merged})
    return out


# ── KOSPI 시장 평균 PER/PBR (시총 가중평균) ─────────────────────
# pykrx KRX 차단 시 valuation_signal_kr 의 fallback 으로 사용.

_MARKET_PER_TTL_SEC = 86400                                  # 24시간 캐시
_MARKET_PER_KEY = 'kospi200_market_per'


def _market_cap_yf(stock_code: str) -> float | None:
    """yfinance 6자리.KS 로 종목 시총 (info.marketCap) 가져오기.

    KOSPI 종목은 .KS, KOSDAQ 은 .KQ — 우선 .KS 시도, 실패 시 .KQ. 둘 다 실패면 None.
    """
    for suffix in ('.KS', '.KQ'):
        try:
            import yfinance as yf
            t = yf.Ticker(f'{stock_code}{suffix}')
            info = t.info or {}
            cap = info.get('marketCap')
            if cap and cap > 0:
                return float(cap)
        except Exception:
            continue
    return None


def _fetch_kospi200_codes() -> list[str]:
    """KOSPI200 구성종목 6자리 코드 list.

    pykrx 가 막힌 환경에서는 기존 KR 25종목 proxy 로 fallback 한다.
    """
    try:
        from pykrx import stock
        codes = stock.get_index_portfolio_deposit_file('1028')  # KOSPI200
        codes = [str(c).zfill(6) for c in codes if str(c).strip()]
        if len(codes) >= 50:
            return codes
        print(f'[DART] KOSPI200 구성종목 부족 ({len(codes)}건) → 25종목 proxy fallback')
    except Exception as e:
        print(f'[DART] KOSPI200 구성종목 fetch 실패 → 25종목 proxy fallback: {e}')

    from collector.noise_regime_data_kr import ALL_STOCKS_KR
    return list(ALL_STOCKS_KR)


def _market_caps_pykrx(stock_codes: list[str]) -> dict[str, float]:
    """pykrx KOSPI 시총. 최근 거래일을 최대 14일 뒤로 탐색."""
    wanted = {str(sc).zfill(6) for sc in stock_codes}
    if not wanted:
        return {}
    try:
        from pykrx import stock
        for i in range(14):
            d = (date.today() - timedelta(days=i)).strftime('%Y%m%d')
            df = stock.get_market_cap_by_ticker(d, market='KOSPI')
            if df is None or df.empty or '시가총액' not in df.columns:
                continue
            out: dict[str, float] = {}
            for sc in wanted:
                if sc not in df.index:
                    continue
                try:
                    cap = float(df.loc[sc, '시가총액'])
                    if cap > 0:
                        out[sc] = cap
                except (TypeError, ValueError):
                    continue
            if out:
                print(f'[DART] pykrx KOSPI 시총 {len(out)}/{len(wanted)}건 사용 ({d})')
                return out
    except Exception as e:
        print(f'[DART] pykrx KOSPI 시총 fetch 실패 → yfinance 보강: {e}')
    return {}


def compute_kospi_market_per_dart(stock_codes: list[str] | None = None,
                                    force_refresh: bool = False) -> dict | None:
    """KOSPI 시장 평균 PER/PBR — KOSPI200 시총 가중평균.

    pykrx KRX 차단 환경에서 [valuation_signal_kr.py](collector/valuation_signal_kr.py)
    의 PER fallback 체인 (pykrx → DART → 캐시 → 14.0) 의 2단계로 사용.

    공식:
        market_per = Σ(market_cap_i) / Σ(net_income_i)   # 음수 NI 제외
        market_pbr = Σ(market_cap_i) / Σ(equity_i)       # 음수 EQ 제외

    Args:
        stock_codes: 종목 리스트. None 이면 pykrx KOSPI200 구성종목을 사용.
                     pykrx 차단 시에만 noise_regime_data_kr.ALL_STOCKS_KR
                     (5섹터 × 5 = 25 종목) proxy 로 fallback.
        force_refresh: 캐시(24h) 무시하고 재계산.

    Returns: {'per', 'pbr', 'coverage', 'n_stocks', 'n_per', 'n_pbr', 'updated_at'}
             또는 모든 fetch 실패 시 None.
    """
    if stock_codes is None:
        stock_codes = _fetch_kospi200_codes()
    stock_codes = [str(sc).zfill(6) for sc in stock_codes]

    # 일별 캐시 (TTL 24h) — 빈번 호출 방지
    cache = _load_metrics_cache()
    cached = cache.get(_MARKET_PER_KEY)
    if not force_refresh and cached:
        try:
            updated = datetime.fromisoformat(cached.get('updated_at', '2000-01-01'))
            if (datetime.now() - updated).total_seconds() < _MARKET_PER_TTL_SEC:
                return cached
        except Exception:
            pass

    # 1) 시총 fetch: pykrx KRX 시총 우선, 누락분만 yfinance 로 보강
    market_caps = _market_caps_pykrx(stock_codes)
    missing = [sc for sc in stock_codes if sc not in market_caps]
    if missing:
        for sc in missing:
            cap = _market_cap_yf(sc)
            if cap:
                market_caps[sc] = cap
        if len(market_caps) > 0:
            print(f'[DART] yfinance 시총 보강 후 {len(market_caps)}/{len(stock_codes)}건')

    if not market_caps:
        print('[DART] KOSPI 시장 PER — 시총 0건 → 산출 불가')
        return None

    # 2) DART 로 재무 metrics fetch (시총 있는 종목만)
    metrics = fetch_per_pbr_dart(list(market_caps.keys()), market_caps,
                                  force_refresh=force_refresh)
    if not metrics:
        print('[DART] KOSPI 시장 PER — DART metrics 0건')
        return None

    # 3) 시총 가중평균 — market_per = Σcap / Σni (NI = cap/per 로 역산)
    total_cap_per = total_ni = 0.0
    total_cap_pbr = total_eq = 0.0
    n_per = n_pbr = 0
    for sc, m in metrics.items():
        cap = market_caps.get(sc)
        per = m.get('per')
        pbr = m.get('pbr')
        if cap and per and per > 0:                          # 음수 NI 제외
            total_cap_per += cap
            total_ni += cap / per
            n_per += 1
        if cap and pbr and pbr > 0:                          # 음수 EQ 제외
            total_cap_pbr += cap
            total_eq += cap / pbr
            n_pbr += 1

    market_per = (total_cap_per / total_ni) if total_ni > 0 else None
    market_pbr = (total_cap_pbr / total_eq) if total_eq > 0 else None
    coverage = max(n_per, n_pbr) / len(stock_codes) if stock_codes else 0.0

    if market_per is None and market_pbr is None:
        return None

    result = {
        'per': round(market_per, 2) if market_per else None,
        'pbr': round(market_pbr, 2) if market_pbr else None,
        'coverage': round(coverage, 2),
        'n_stocks': len(stock_codes),
        'n_per': n_per,
        'n_pbr': n_pbr,
        'updated_at': datetime.now().isoformat(),
    }

    # 캐시 갱신 (기존 metrics 와 병합)
    cache[_MARKET_PER_KEY] = result
    _save_metrics_cache(cache)

    print(f"[DART] KOSPI 시장 PER {result['per']} / PBR {result['pbr']} "
          f"(cov {coverage*100:.0f}%, n={n_per}/{len(stock_codes)})")
    return result


# ── KOSPI 47사 net_income 시계열 (fundamental_gap 산출용) ─────
_EPS_HISTORY_PATH = os.path.join(_CACHE_DIR, 'kospi200_eps_history.json')
_TTM_HISTORY_PATH = os.path.join(_CACHE_DIR, 'kospi200_ttm_quarterly.json')
_EPS_HISTORY_TTL_DAYS = 30
_TTM_TTL_DAYS = 30


def _quarter_end_date(year: int, reprt_code: str) -> date:
    """분기 보고서 코드 → 해당 분기 종료일."""
    return {
        _REPRT_Q1: date(year, 3, 31),
        _REPRT_H1: date(year, 6, 30),
        _REPRT_Q3: date(year, 9, 30),
        _REPRT_FY: date(year, 12, 31),
    }[reprt_code]


def fetch_kospi200_ttm_quarterly(years: int = 5, force_refresh: bool = False) -> dict:
    """KOSPI 47사 분기별 TTM (Trailing Twelve Months) net_income 합산.

    DART 분기 보고서는 회계연도 누적 (Q1=Jan-Mar, H1=Jan-Jun, Q3=Jan-Sep, FY=Jan-Dec).
    단일 분기 NI = 누적 - 이전 누적. TTM = 최근 4개 단일 분기 합.

    47 corps × ~4분기 × N년 = ~940 호출 (5년 기준). ~3~5분.
    Returns: {'YYYY-MM-DD': ttm_net_income, ...} (분기 종료일 기준)
    """
    if not force_refresh and os.path.exists(_TTM_HISTORY_PATH):
        try:
            with open(_TTM_HISTORY_PATH) as f:
                cached = json.load(f)
            updated = datetime.fromisoformat(cached.get('updated_at', '2000-01-01'))
            if (datetime.now() - updated).days < _TTM_TTL_DAYS:
                return {k: float(v) for k, v in cached.get('ttm_by_quarter', {}).items()}
        except Exception:
            pass

    if not _api_key():
        print('[DART] DART_API_KEY 미설정 — TTM 시계열 fetch 불가')
        return {}

    cache = _load_metrics_cache()
    corps = list(cache.get('metrics', {}).keys())
    if not corps:
        print('[DART] dart_kr_metrics.json metrics 비어있음')
        return {}

    mapping = _load_corp_codes()
    today = date.today()
    year_range = list(range(today.year - years - 1, today.year + 1))
    quarter_codes = [_REPRT_Q1, _REPRT_H1, _REPRT_Q3, _REPRT_FY]

    print(f'[DART] KOSPI {len(corps)}사 × {len(year_range)}년 × 4분기 TTM fetch...')

    # corp 별 분기 누적 NI 수집
    corp_cumul: dict[str, dict[date, float]] = {}     # {corp: {quarter_end_date: cumul_ni}}
    api_calls = 0
    for cc in corps:
        corp_code = mapping.get(cc)
        if not corp_code:
            continue
        corp_cumul[cc] = {}
        for y in year_range:
            for rep in quarter_codes:
                qend = _quarter_end_date(y, rep)
                if qend > today:
                    continue
                try:
                    items = _fetch_acnt(corp_code, y, rep, fs_div='CFS')
                    if not items:
                        items = _fetch_acnt(corp_code, y, rep, fs_div='OFS')
                    api_calls += 1
                    if not items:
                        continue
                    ni = _extract_amount(items, _NI_NAMES, 'IS')
                    if ni is None:
                        ni = _extract_amount(items, _NI_NAMES, 'CIS')
                    if ni is not None:
                        corp_cumul[cc][qend] = ni
                except Exception:
                    continue

    print(f'[DART] {api_calls} DART API 호출 완료')

    # 각 corp 의 단일 분기 NI 도출 (Q1=Q1cumul; Q2=H1-Q1; Q3=Q3cumul-H1; Q4=FY-Q3cumul)
    # 같은 연도 내 분기 순서: Q1 < H1 < Q3 < FY
    corp_single_q: dict[str, dict[date, float]] = {}   # {corp: {qend: single_q_ni}}
    for cc, cumul in corp_cumul.items():
        single = {}
        for y in year_range:
            q1_end, h1_end, q3_end, fy_end = (_quarter_end_date(y, c) for c in quarter_codes)
            q1 = cumul.get(q1_end)
            h1 = cumul.get(h1_end)
            q3 = cumul.get(q3_end)
            fy = cumul.get(fy_end)
            if q1 is not None:
                single[q1_end] = q1
            if h1 is not None and q1 is not None:
                single[h1_end] = h1 - q1
            if q3 is not None and h1 is not None:
                single[q3_end] = q3 - h1
            if fy is not None and q3 is not None:
                single[fy_end] = fy - q3
        corp_single_q[cc] = single

    # 모든 corp 의 단일분기 NI 를 quarter_end 별로 합산
    all_qends = sorted({q for d in corp_single_q.values() for q in d.keys()})
    agg_single: dict[date, float] = {}
    n_corps_per_q: dict[date, int] = {}
    for q in all_qends:
        total = 0.0
        n = 0
        for cc, single in corp_single_q.items():
            v = single.get(q)
            if v is not None:
                total += v
                n += 1
        agg_single[q] = total
        n_corps_per_q[q] = n

    # 각 quarter end 시점의 TTM = 최근 4개 단일분기 합 (해당 분기 포함)
    sorted_q = sorted(agg_single.keys())
    ttm_by_quarter: dict[str, float] = {}
    for i, q in enumerate(sorted_q):
        if i < 3:
            continue   # 최소 4개 분기 필요
        last4 = sorted_q[i - 3: i + 1]
        ttm = sum(agg_single[x] for x in last4)
        ttm_by_quarter[q.strftime('%Y-%m-%d')] = ttm

    # 캐시 저장
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_TTM_HISTORY_PATH, 'w') as f:
            json.dump({
                'updated_at': datetime.now().isoformat(),
                'ttm_by_quarter': ttm_by_quarter,
                'n_corps_per_q': {q.strftime('%Y-%m-%d'): n for q, n in n_corps_per_q.items()},
                'n_corps_total': len(corps),
            }, f, indent=2)
    except Exception as e:
        print(f'[DART] TTM 캐시 저장 실패: {e}')

    if ttm_by_quarter:
        last_q = sorted(ttm_by_quarter)[-1]
        first_q = sorted(ttm_by_quarter)[0]
        print(f'[DART] TTM: {len(ttm_by_quarter)} 분기 ({first_q} ~ {last_q}) '
              f'/ 최신 {ttm_by_quarter[last_q]/1e12:.2f}조')
    return ttm_by_quarter


def fetch_kospi200_annual_ni(years: int = 5, force_refresh: bool = False) -> dict[int, float]:
    """KOSPI 200 (DART 47사) 의 연간 net_income 합산 시계열.

    각 corp 의 사업보고서(연간) 를 years 년치 fetch → 합산.
    Returns: {year(int): total_net_income(float)}

    47 corps × years 호출. 5년이면 235 호출 ~2분.
    30일 캐시 (kospi200_eps_history.json).
    """
    # 캐시 확인
    if not force_refresh and os.path.exists(_EPS_HISTORY_PATH):
        try:
            with open(_EPS_HISTORY_PATH) as f:
                cached = json.load(f)
            updated = datetime.fromisoformat(cached.get('updated_at', '2000-01-01'))
            if (datetime.now() - updated).days < _EPS_HISTORY_TTL_DAYS:
                return {int(k): float(v) for k, v in cached.get('annual_ni', {}).items()}
        except Exception:
            pass

    if not _api_key():
        print('[DART] DART_API_KEY 미설정 — annual_ni 시계열 fetch 불가')
        return {}

    # 기존 metrics 캐시에서 47 corps 가져옴
    cache = _load_metrics_cache()
    corps = list(cache.get('metrics', {}).keys())
    if not corps:
        print('[DART] dart_kr_metrics.json metrics 비어있음 — fetch_per_pbr_dart 먼저 호출 필요')
        return {}

    mapping = _load_corp_codes()
    today = date.today()
    annual_ni: dict[int, float] = {}
    n_corps_per_year: dict[int, int] = {}

    # years 년치 + 추가 1년 (12개월 diff 산출용)
    year_range = list(range(today.year - years - 1, today.year))

    print(f'[DART] KOSPI {len(corps)}사 × {len(year_range)}년 annual_ni fetch...')
    for cc in corps:
        corp_code = mapping.get(cc)
        if not corp_code:
            continue
        for y in year_range:
            try:
                items = _fetch_acnt(corp_code, y, _REPRT_FY, fs_div='CFS')
                if not items:
                    items = _fetch_acnt(corp_code, y, _REPRT_FY, fs_div='OFS')
                if not items:
                    continue
                ni = _extract_amount(items, _NI_NAMES, 'IS')
                if ni is None:
                    ni = _extract_amount(items, _NI_NAMES, 'CIS')
                if ni is None:
                    continue
                annual_ni[y] = annual_ni.get(y, 0.0) + ni
                n_corps_per_year[y] = n_corps_per_year.get(y, 0) + 1
            except Exception:
                continue

    if not annual_ni:
        print('[DART] annual_ni 모든 corp 실패')
        return {}

    # 캐시 저장
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_EPS_HISTORY_PATH, 'w') as f:
            json.dump({
                'updated_at': datetime.now().isoformat(),
                'annual_ni': {str(k): v for k, v in annual_ni.items()},
                'n_corps_per_year': {str(k): v for k, v in n_corps_per_year.items()},
                'n_corps_total': len(corps),
            }, f, indent=2)
    except Exception as e:
        print(f'[DART] annual_ni 캐시 저장 실패: {e}')

    summary = ' / '.join(f"{y}={annual_ni[y]/1e12:.1f}T" for y in sorted(annual_ni))
    print(f'[DART] annual_ni: {summary}')
    return annual_ni
