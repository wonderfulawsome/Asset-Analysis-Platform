"""부동산 API 라우터 — 프론트엔드(realestate SPA) 용 엔드포인트.

모든 쿼리는 database.repositories 함수를 그대로 감싼다 (비즈니스 로직 없음).
ym 파라미터는 미지정 시 당월(%Y%m) 기본값 사용 → 프론트는 단순 호출 가능.
"""
import os
from datetime import date, timedelta

from fastapi import APIRouter, Query

from database.repositories import (
    fetch_region_summary, fetch_region_timeseries, fetch_re_trades, fetch_re_rents,
    fetch_mois_population, fetch_mois_household,
    fetch_stdg_admm_mapping, fetch_geo_stdg,
    fetch_buy_signal, fetch_buy_signal_history,
    fetch_macro_rate_kr, fetch_region_migration,
    fetch_region_by_stdg_cd, fetch_region_timeseries_by_stdg, fetch_complex_summary_by_stdg,
    fetch_complex_compare,
)


router = APIRouter()


# 쿼리 ym 미지정 시 사용할 기본값(전월 YYYYMM) 생성
# MOIS 인구통계가 당월엔 미집계(1~2개월 lag)라 스케줄러도 전월 기준이라
# 프론트가 ym 생략 시 가장 최신 데이터를 받도록 맞춘다.
def _default_ym() -> str:
    today = date.today()
    prev = today.replace(day=1) - timedelta(days=1)
    return prev.strftime('%Y%m')


# GET /summary — 지도·카드 메인용: 시군구 단위 법정동별 집계 반환
@router.get('/summary')
def get_summary(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """시군구 단위 지역 집계 (법정동별 평단가·거래건수·인구·1인가구비율 등)."""
    return fetch_region_summary(sgg_cd, ym or _default_ym())


# GET /trades — 상세화면 드릴다운용: 매매 실거래 원본 목록
@router.get('/trades')
def get_trades(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """매매 실거래 원본 목록 (지역 상세 화면 드릴다운용)."""
    return fetch_re_trades(sgg_cd, ym or _default_ym())


# GET /rents — 상세화면 드릴다운용: 전월세 실거래 원본 목록
@router.get('/rents')
def get_rents(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """전월세 실거래 원본 목록 (monthly_rent=0 → 전세)."""
    return fetch_re_rents(sgg_cd, ym or _default_ym())


# GET /population — 인구 차트용: 법정동별 총인구·세대수·성비
@router.get('/population')
def get_population(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """법정동별 인구·세대수 (MOIS)."""
    return fetch_mois_population(sgg_cd, ym or _default_ym())


# GET /household — 1인가구 분석용: 행정동별 세대원수 분포 + solo_rate
@router.get('/household')
def get_household(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """행정동별 세대원수 분포 + solo_rate (MOIS)."""
    return fetch_mois_household(sgg_cd, ym or _default_ym())


# GET /mapping — 조인 참조용: 법정동↔행정동 매핑 테이블
@router.get('/mapping')
def get_mapping(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ref_ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """법정동↔행정동 매핑 테이블."""
    return fetch_stdg_admm_mapping(sgg_cd, ref_ym or _default_ym())


# GET /geo — 지도 마커용: 법정동 좌표 (lat, lng) 조회 (기간 무관)
@router.get('/geo')
def get_geo(sgg_cd: str = Query(..., description='시군구 코드 5자리')):
    """법정동 좌표 (지도 마커용, 기간과 무관)."""
    return fetch_geo_stdg(sgg_cd)


# GET /timeseries — 시계열 차트용: 시군구의 월별 집계 시리즈 (과거→최근)
#    프론트에서 월별 평단가/거래량/인구/전세가율을 라인차트로 렌더
@router.get('/timeseries')
def get_timeseries(sgg_cd: str = Query(..., description='시군구 코드 5자리')):
    """시군구 월별 집계 배열 (법정동별이 아닌 구 전체 월별 rollup).

    주: region_summary 는 법정동 단위라, 같은 ym 내 법정동들을 합산/평균해야
    '구 전체' 월별 지표가 나온다. 프론트에서 집계하거나 여기서 전처리 가능.
    간단하게는 법정동 배열을 월별로 묶어 반환 → 프론트가 원하는 지표로 집계.
    """
    rows = fetch_region_timeseries(sgg_cd)
    # 월별 rollup
    by_ym: dict[str, dict] = {}
    for r in rows:
        ym = r['stats_ym']
        d = by_ym.setdefault(ym, {
            'ym': ym, 'trade_count': 0, 'jeonse_count': 0, 'wolse_count': 0,
            'population': 0, '_price_sum': 0.0, '_price_n': 0,
            'avg_deposit_sum': 0, 'avg_deposit_n': 0,
            'avg_price_sum': 0, 'avg_price_n': 0,
        })
        d['trade_count']   += r.get('trade_count') or 0
        d['jeonse_count']  += r.get('jeonse_count') or 0
        d['wolse_count']   += r.get('wolse_count') or 0
        d['population']    += r.get('population') or 0
        if r.get('median_price_per_py'):
            d['_price_sum'] += r['median_price_per_py']
            d['_price_n'] += 1
        if r.get('avg_deposit'):
            d['avg_deposit_sum'] += r['avg_deposit']
            d['avg_deposit_n'] += 1
        if r.get('avg_price'):
            d['avg_price_sum'] += r['avg_price']
            d['avg_price_n'] += 1
    # 정리: 평균 계산 후 정렬
    out = []
    for ym in sorted(by_ym):
        d = by_ym[ym]
        avg_pp = d['_price_sum'] / d['_price_n'] if d['_price_n'] else None
        avg_dep = d['avg_deposit_sum'] / d['avg_deposit_n'] if d['avg_deposit_n'] else None
        avg_pr = d['avg_price_sum'] / d['avg_price_n'] if d['avg_price_n'] else None
        # 전세가율 = 전세보증금 / 매매가 (만원 기준, 둘 다 같은 단위)
        jeonse_rate = (avg_dep / avg_pr) if (avg_dep and avg_pr) else None
        out.append({
            'ym': ym,
            'trade_count': d['trade_count'],
            'jeonse_count': d['jeonse_count'],
            'wolse_count': d['wolse_count'],
            'population': d['population'],
            'median_price_per_py': round(avg_pp, 0) if avg_pp else None,
            'avg_deposit': round(avg_dep, 0) if avg_dep else None,
            'avg_price': round(avg_pr, 0) if avg_pr else None,
            'jeonse_rate': round(jeonse_rate, 4) if jeonse_rate else None,
        })
    return out


# GET /config — 프론트가 카카오맵 SDK 로드할 때 필요한 JS 키 전달
# .env 에만 두고 HTML 에 하드코딩 안 하는 이유: 키가 바뀌어도 rebuild 불필요
@router.get('/config')
def get_config():
    """프론트용 설정값 (카카오맵 JS 키)."""
    return {'kakao_js_key': os.getenv('KAKAO_JS_KEY', '')}


# GET /signal — 매수 타이밍 시그널 (최신 1건). ym 지정 시 해당월.
@router.get('/signal')
def get_signal(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 최신'),
):
    """시군구의 매수/관망/주의 시그널 + 점수 breakdown."""
    return fetch_buy_signal(sgg_cd, ym or None) or {}


# GET /signal/history — 시그널 시계열 (월별 변화 추적용)
@router.get('/signal/history')
def get_signal_history(sgg_cd: str = Query(..., description='시군구 코드 5자리')):
    """시군구의 시그널 시계열 (과거 → 최근)."""
    return fetch_buy_signal_history(sgg_cd)


# GET /macro-rate — 한국은행 ECOS 거시금리 시계열 (전국 공통)
@router.get('/macro-rate')
def get_macro_rate(months: int = Query(default=24, description='최근 N개월')):
    """기준금리·주담대 금리·잔액 시계열."""
    return fetch_macro_rate_kr(months=months)


# GET /migration — KOSIS 시군구 인구이동 시계열
@router.get('/migration')
def get_migration(sgg_cd: str = Query(..., description='시군구 코드 5자리')):
    """시군구의 월별 전입·전출·순이동 시계열."""
    return fetch_region_migration(sgg_cd)


# GET /sgg-overview — 지도 폴리곤 색칠용: 시군구 단위 rollup + 변화율
# region_summary 가 법정동 단위라 시군구 합산이 필요. top_stdg_* 는 BottomBar 표기용.
@router.get('/sgg-overview')
def get_sgg_overview(ym: str = Query(default='', description='YYYYMM, 미지정 시 최신')):
    """서울 시군구별 매매가 + 3개월 변화율 + 대표 법정동."""
    target_ym = ym or _default_ym()
    # 모든 행 한 번에 가져와 Python 측에서 그룹핑 (region_summary는 작아 비용 낮음)
    from database.supabase_client import get_client
    client = get_client()
    response = client.table('region_summary').select(
        'sgg_cd,stdg_cd,stdg_nm,stats_ym,median_price_per_py,trade_count'
    ).execute()
    rows = response.data
    # 시군구·월별로 평균 평단가 + 거래수 합 계산
    by_sm: dict[tuple, dict] = {}
    for r in rows:
        key = (r['sgg_cd'], r['stats_ym'])
        d = by_sm.setdefault(key, {'_ps': 0.0, '_pn': 0, 'trade_count': 0})
        if r.get('median_price_per_py'):
            d['_ps'] += r['median_price_per_py']
            d['_pn'] += 1
        d['trade_count'] += r.get('trade_count') or 0
    # 시군구별 최신월(target_ym) 평균 + 3개월 전 평균 → 변화율
    out = []
    sgg_cds = sorted({r['sgg_cd'] for r in rows})
    for sgg_cd in sgg_cds:
        # 사용 가능한 월 정렬
        yms = sorted(ym for (s, ym) in by_sm if s == sgg_cd)
        if not yms:
            continue
        # target_ym 또는 가장 가까운 과거
        latest_ym = target_ym if target_ym in yms else yms[-1]
        # 3개월 전 (없으면 가장 오래된 월)
        try:
            li = yms.index(latest_ym)
        except ValueError:
            continue
        prev_ym = yms[max(0, li - 3)]
        latest = by_sm[(sgg_cd, latest_ym)]
        prev = by_sm[(sgg_cd, prev_ym)]
        latest_avg = latest['_ps'] / latest['_pn'] if latest['_pn'] else None
        prev_avg = prev['_ps'] / prev['_pn'] if prev['_pn'] else None
        change_pct = None
        if latest_avg and prev_avg and latest_ym != prev_ym:
            change_pct = round((latest_avg / prev_avg - 1) * 100, 2)
        # 대표 법정동 — target_ym 의 법정동 중 평단가 1위
        top_stdg = max(
            (r for r in rows if r['sgg_cd'] == sgg_cd and r['stats_ym'] == latest_ym),
            key=lambda x: x.get('median_price_per_py') or 0,
            default=None,
        )
        out.append({
            'sgg_cd': sgg_cd,
            'sgg_nm': None,  # region_summary 에 sgg_nm 컬럼 없음 — 프론트에서 시군구 dictionary 별도 매핑
            'stats_ym': latest_ym,
            'median_price_per_py': round(latest_avg, 0) if latest_avg else None,
            'change_pct_3m': change_pct,
            'trade_count': latest['trade_count'],
            'top_stdg_cd': top_stdg['stdg_cd'] if top_stdg else None,
            'top_stdg_nm': top_stdg.get('stdg_nm') if top_stdg else None,
        })
    return out


# GET /complex-compare — 단지(apt_seq) 2~4개 나란히 비교용 12개월 시계열
@router.get('/complex-compare')
def get_complex_compare(
    apt_seqs: str = Query(..., description='apt_seq 콤마구분 (최대 4개)'),
    months: int = Query(default=12, description='최근 N개월'),
):
    """단지별 평단가·거래량·전세가율 시계열 — 비교 화면용."""
    seqs = [s.strip() for s in apt_seqs.split(',') if s.strip()][:4]
    return fetch_complex_compare(seqs, months=months)


# GET /stdg-detail — 법정동 상세 페이지용 통합 응답
@router.get('/stdg-detail')
def get_stdg_detail(
    stdg_cd: str = Query(..., description='법정동 코드 10자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 최신'),
):
    """법정동 단일 + 12M 시계열 + 단지 TOP 10 + 시군구 시그널 통합."""
    target_ym = ym or _default_ym()
    summary = fetch_region_by_stdg_cd(stdg_cd, target_ym)
    timeseries = fetch_region_timeseries_by_stdg(stdg_cd, months=12)
    complexes = fetch_complex_summary_by_stdg(stdg_cd, target_ym, top=10)

    # 변화율 — timeseries 기반 (3개월 전 대비). 데이터가 부족하면 None.
    change_pct_3m = None
    trade_count_3m = None
    if len(timeseries) >= 2:
        latest = timeseries[-1]
        prev_idx = max(0, len(timeseries) - 4)  # 3개월 전 (없으면 첫 점)
        prev = timeseries[prev_idx]
        if latest.get('median_price_per_py') and prev.get('median_price_per_py') and prev_idx != len(timeseries)-1:
            change_pct_3m = round(
                (latest['median_price_per_py'] / prev['median_price_per_py'] - 1) * 100, 2
            )
        trade_count_3m = sum(p.get('trade_count') or 0 for p in timeseries[-3:])

    # 전세가율 = avg_deposit / avg_price (둘 다 만원 단위)
    jeonse_rate = None
    if summary and summary.get('avg_deposit') and summary.get('avg_price'):
        jeonse_rate = round(summary['avg_deposit'] / summary['avg_price'], 4)

    # 시군구 단위 시그널·인구이동
    sgg_cd = summary['sgg_cd'] if summary else stdg_cd[:5]
    signal = fetch_buy_signal(sgg_cd, target_ym)
    migration = fetch_region_migration(sgg_cd)
    net_flow = None
    if migration:
        latest_mig = next((m for m in reversed(migration) if m['stats_ym'] <= target_ym), None)
        net_flow = latest_mig.get('net_flow') if latest_mig else None

    return {
        'summary': {
            **(summary or {}),
            'change_pct_3m': change_pct_3m,
            'trade_count_3m': trade_count_3m,
            'jeonse_rate': jeonse_rate,
            'net_flow': net_flow,
        } if summary else None,
        'timeseries': timeseries,
        'complexes': complexes,
        'signal': signal or None,
    }
