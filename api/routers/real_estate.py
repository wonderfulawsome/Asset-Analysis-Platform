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


# 쿼리 ym 미지정 시 사용할 기본값 — "직전 완성월" (= 오늘 기준 2개월 전).
# 이유: 전월(t-1)도 ① MOIS 인구통계 미집계(1~2개월 lag) ② MOLIT 거래도 신고
# 지연으로 부분 집계 → 노이즈. 전전월(t-2)부터 모든 지표 안정 적재 보장.
# ex 5월 2일 → 202603 (3월), 5월 31일 → 202603, 6월 → 202604
def _default_ym() -> str:
    today = date.today()
    prev1 = today.replace(day=1) - timedelta(days=1)      # 전월 마지막일
    prev2 = prev1.replace(day=1) - timedelta(days=1)      # 전전월 마지막일
    return prev2.strftime('%Y%m')


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


SGG_OVERVIEW_CACHE_KEY = 'sgg_overview'


def compute_sgg_overview(ym: str = '') -> list[dict]:
    """sgg-overview 본 계산 — region_summary 4000+ 행 페이지네이션 + 시군구 그룹핑.

    스케줄러가 매일 호출해 app_cache 에 적재. endpoint 는 cache 만 select.
    cache miss 안전망용으로 endpoint 도 직접 호출 가능 (첫 호출 ~12초).
    """
    target_ym = ym or _default_ym()
    from database.supabase_client import get_client
    client = get_client()
    PAGE = 1000
    offset = 0
    rows: list[dict] = []
    while True:
        chunk_resp = (
            client.table('region_summary')
            .select('sgg_cd,stdg_cd,stdg_nm,stats_ym,median_price_per_py,trade_count')
            .order('id', desc=False)
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        chunk = chunk_resp.data or []
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE
    # 시군구·월별로 평균 평단가 + 거래수 합 계산
    by_sm: dict[tuple, dict] = {}
    for r in rows:
        key = (r['sgg_cd'], r['stats_ym'])
        d = by_sm.setdefault(key, {'_ps': 0.0, '_pn': 0, 'trade_count': 0})
        if r.get('median_price_per_py'):
            d['_ps'] += r['median_price_per_py']
            d['_pn'] += 1
        d['trade_count'] += r.get('trade_count') or 0
    # 시군구별 최신월(target_ym) 평균 + 3개월/1개월 전 평균 → 변화율 둘 다
    out = []
    sgg_cds = sorted({r['sgg_cd'] for r in rows})
    for sgg_cd in sgg_cds:
        # 사용 가능한 월 정렬
        yms = sorted(ym for (s, ym) in by_sm if s == sgg_cd)
        if not yms:
            continue
        # target_ym 또는 가장 가까운 과거
        latest_ym = target_ym if target_ym in yms else yms[-1]
        try:
            li = yms.index(latest_ym)
        except ValueError:
            continue
        prev3_ym = yms[max(0, li - 3)]    # 3개월 전 (지도 폴리곤 색칠용)
        prev1_ym = yms[max(0, li - 1)]    # 1개월 전 (FeatureCard 표시용 — 사용자 의도)
        latest = by_sm[(sgg_cd, latest_ym)]
        prev3 = by_sm[(sgg_cd, prev3_ym)]
        prev1 = by_sm[(sgg_cd, prev1_ym)]
        latest_avg = latest['_ps'] / latest['_pn'] if latest['_pn'] else None
        prev3_avg = prev3['_ps'] / prev3['_pn'] if prev3['_pn'] else None
        prev1_avg = prev1['_ps'] / prev1['_pn'] if prev1['_pn'] else None
        change_pct = None
        if latest_avg and prev3_avg and latest_ym != prev3_ym:
            change_pct = round((latest_avg / prev3_avg - 1) * 100, 2)
        change_pct_1m = None
        if latest_avg and prev1_avg and latest_ym != prev1_ym:
            change_pct_1m = round((latest_avg / prev1_avg - 1) * 100, 2)
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
            'change_pct_3m': change_pct,           # 3개월 전 대비 (지도 폴리곤 색칠용)
            'change_pct_1m': change_pct_1m,        # 1개월 전 대비 (FeatureCard 표시용)
            'trade_count': latest['trade_count'],
            'top_stdg_cd': top_stdg['stdg_cd'] if top_stdg else None,
            'top_stdg_nm': top_stdg.get('stdg_nm') if top_stdg else None,
        })
    return out


@router.get('/sgg-overview')
def get_sgg_overview(ym: str = Query(default='', description='YYYYMM, 미지정 시 최신')):
    """app_cache 에서 사전 계산된 결과 select. miss 시 fallback 으로 직접 계산 + 적재.

    cache_key 'sgg_overview' 는 ym 미지정 (= 최신) 결과만. ym 지정 시는 직접 계산.
    """
    # ym 지정된 경우는 ad-hoc 호출 — cache 안 씀
    if ym:
        return compute_sgg_overview(ym)

    from database.supabase_client import get_client
    client = get_client()
    try:
        r = (
            client.table('app_cache')
            .select('payload,updated_at')
            .eq('cache_key', SGG_OVERVIEW_CACHE_KEY)
            .limit(1)
            .execute()
        )
        if r.data:
            return r.data[0]['payload']
    except Exception as e:
        print(f'[sgg-overview] cache read 실패: {e}')

    # cache miss 안전망 — 직접 계산 후 적재 (다음 호출부터 빠름)
    payload = compute_sgg_overview('')
    try:
        client.table('app_cache').upsert(
            {'cache_key': SGG_OVERVIEW_CACHE_KEY, 'payload': payload},
            on_conflict='cache_key',
        ).execute()
    except Exception as e:
        print(f'[sgg-overview] cache write 실패: {e}')
    return payload


# ─────────────────────────────────────────────────────────
# /ranking — 수도권 시군구 랭킹 카드 2종 (거래량 회복 + 가격 상승)
# ─────────────────────────────────────────────────────────
RANKING_CACHE_KEY = 'ranking'

# 시군구 코드 → 한국어 표시명 (간단 매핑, 부족분은 '시군구' 라벨 그대로)
_SGG_KO_NAMES: dict[str, str] = {
    # 서울
    '11110': '종로구', '11140': '중구', '11170': '용산구', '11200': '성동구',
    '11215': '광진구', '11230': '동대문구', '11260': '중랑구', '11290': '성북구',
    '11305': '강북구', '11320': '도봉구', '11350': '노원구', '11380': '은평구',
    '11410': '서대문구', '11440': '마포구', '11470': '양천구', '11500': '강서구',
    '11530': '구로구', '11545': '금천구', '11560': '영등포구', '11590': '동작구',
    '11620': '관악구', '11650': '서초구', '11680': '강남구', '11710': '송파구',
    '11740': '강동구',
    # 인천
    '28110': '중구(인천)', '28140': '동구(인천)', '28177': '미추홀구',
    '28185': '연수구', '28200': '남동구', '28237': '부평구', '28245': '계양구',
    '28260': '서구(인천)', '28710': '강화군', '28720': '옹진군',
    # 경기 단일
    '41150': '의정부시', '41194': '부천시', '41210': '광명시', '41220': '평택시',
    '41250': '동두천시', '41290': '과천시', '41310': '구리시', '41360': '남양주시',
    '41370': '오산시', '41390': '시흥시', '41410': '군포시', '41430': '의왕시',
    '41450': '하남시', '41480': '파주시', '41500': '이천시', '41550': '안성시',
    '41570': '김포시', '41590': '화성시', '41610': '광주시(경기)', '41630': '양주시',
    '41650': '포천시', '41670': '여주시', '41800': '연천군', '41820': '가평군',
    '41830': '양평군',
    # 경기 일반구
    '41111': '수원시 장안구', '41113': '수원시 권선구', '41115': '수원시 팔달구',
    '41117': '수원시 영통구',
    '41131': '성남시 수정구', '41133': '성남시 중원구', '41135': '성남시 분당구',
    '41171': '안양시 만안구', '41173': '안양시 동안구',
    '41271': '안산시 상록구', '41273': '안산시 단원구',
    '41281': '고양시 덕양구', '41285': '고양시 일산동구', '41287': '고양시 일산서구',
    '41461': '용인시 처인구', '41463': '용인시 기흥구', '41465': '용인시 수지구',
}


def compute_ranking() -> dict:
    """수도권 시군구 랭킹 2종.

    - trade_recovery_top: trade_vs_long_ratio 내림차순 TOP 5 (거래량 회복)
    - price_top: change_pct_3m 내림차순 TOP 5 (가격 상승)
    출처: buy_signal_result.feature_breakdown + sgg_overview cache.
    """
    from database.supabase_client import get_client
    client = get_client()

    # 1) buy_signal_result 의 최신 row per sgg
    r = client.table('buy_signal_result').select('sgg_cd,stats_ym,signal,feature_breakdown').execute()
    latest_per_sgg: dict[str, dict] = {}
    for row in r.data or []:
        sgg = row['sgg_cd']
        if sgg not in latest_per_sgg or (row.get('stats_ym') or '') > (latest_per_sgg[sgg].get('stats_ym') or ''):
            latest_per_sgg[sgg] = row

    # 2) sgg_overview cache 의 change_pct_3m
    r2 = client.table('app_cache').select('payload').eq('cache_key', SGG_OVERVIEW_CACHE_KEY).limit(1).execute()
    overview = r2.data[0]['payload'] if r2.data else []
    overview_by_sgg = {o['sgg_cd']: o for o in overview}

    # 거래량 회복 — trade_vs_long_ratio 큰 순 (1.0 초과만)
    trade_recovery = []
    for sgg, rec in latest_per_sgg.items():
        fb = rec.get('feature_breakdown') or {}
        ratio = fb.get('trade_vs_long_ratio')
        if ratio is None:
            continue
        trade_recovery.append({
            'sgg_cd': sgg,
            'sgg_nm': _SGG_KO_NAMES.get(sgg, sgg),
            'trade_vs_long_ratio': ratio,
            'trade_count': overview_by_sgg.get(sgg, {}).get('trade_count'),
            'stats_ym': rec.get('stats_ym'),
        })
    trade_recovery.sort(key=lambda x: x['trade_vs_long_ratio'], reverse=True)

    # 가격 상승 — change_pct_3m 큰 순
    price_up = []
    for sgg, ov in overview_by_sgg.items():
        chg = ov.get('change_pct_3m')
        if chg is None:
            continue
        price_up.append({
            'sgg_cd': sgg,
            'sgg_nm': _SGG_KO_NAMES.get(sgg, sgg),
            'change_pct_3m': chg,
            'median_price_per_py': ov.get('median_price_per_py'),
            'stats_ym': ov.get('stats_ym'),
        })
    price_up.sort(key=lambda x: x['change_pct_3m'], reverse=True)

    return {
        'trade_recovery_top5': trade_recovery[:5],
        'price_top5': price_up[:5],
        'updated_at': date.today().isoformat(),
    }


@router.get('/ranking')
def get_ranking():
    """app_cache 에서 사전 계산된 랭킹 select. miss 시 직접 계산 + 적재."""
    from database.supabase_client import get_client
    client = get_client()
    try:
        r = (
            client.table('app_cache')
            .select('payload')
            .eq('cache_key', RANKING_CACHE_KEY)
            .limit(1)
            .execute()
        )
        if r.data:
            return r.data[0]['payload']
    except Exception as e:
        print(f'[ranking] cache read 실패: {e}')

    payload = compute_ranking()
    try:
        client.table('app_cache').upsert(
            {'cache_key': RANKING_CACHE_KEY, 'payload': payload},
            on_conflict='cache_key',
        ).execute()
    except Exception as e:
        print(f'[ranking] cache write 실패: {e}')
    return payload



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


# ─────────────────────────────────────────────────────────────────────
# GET /market-summary — 오늘의 부동산 시장 LLM 요약 (24h 캐시)
# ─────────────────────────────────────────────────────────────────────
# 25구 buy_signal + region_summary + macro_rate 종합 → Groq LLM → 한 단락 요약.
# 캐시 24h (compute 최소화 메모리 룰: LLM 호출 30/월).
import time as _time
_market_summary_cache = {'data': None, 'ts': 0}
_MARKET_SUMMARY_TTL = 24 * 3600  # 24시간


def _build_market_summary_data():
    """LLM 입력용 부동산 시장 종합 데이터 dict + 표시용 분포."""
    target_ym = _default_ym()

    # 시그널 분포
    signal_dist = {'매수': 0, '관망': 0, '주의': 0}
    sgg_signals = []
    for sgg_cd in [
        '11110','11140','11170','11200','11215','11230','11260','11290','11305','11320',
        '11350','11380','11410','11440','11470','11500','11530','11545','11560','11590',
        '11620','11650','11680','11710','11740',
    ]:
        s = fetch_buy_signal(sgg_cd, target_ym)
        if not s:
            continue
        sig = s.get('signal')
        if sig in signal_dist:
            signal_dist[sig] += 1
        sgg_signals.append({
            'sgg_cd': sgg_cd,
            'signal': sig,
            'score': s.get('score'),
            'trade_chg_pct': (s.get('feature_breakdown') or {}).get('trade_chg_pct'),
            'price_mom_pct': (s.get('feature_breakdown') or {}).get('price_mom_pct'),
        })

    # 가격 변화 top 3 / bottom 3 (sgg-overview 활용)
    overview = get_sgg_overview('')
    overview_sorted = sorted(
        [r for r in overview if r.get('change_pct_3m') is not None],
        key=lambda r: r['change_pct_3m'], reverse=True,
    )
    top_up = overview_sorted[:3]
    top_down = overview_sorted[-3:][::-1]

    # 매크로
    macro = fetch_macro_rate_kr(months=12) or []
    latest_macro = macro[-1] if macro else None
    earliest_macro = macro[0] if macro else None
    base_drop = None
    if latest_macro and earliest_macro:
        b1 = latest_macro.get('base_rate')
        b0 = earliest_macro.get('base_rate')
        if b1 is not None and b0 is not None:
            base_drop = round(b1 - b0, 2)

    return {
        'target_ym': target_ym,
        'signal_distribution': signal_dist,
        'sgg_signals': sgg_signals,
        'top_up': [{'sgg_cd': r['sgg_cd'], 'change_pct_3m': r['change_pct_3m'], 'top_stdg_nm': r.get('top_stdg_nm')} for r in top_up],
        'top_down': [{'sgg_cd': r['sgg_cd'], 'change_pct_3m': r['change_pct_3m'], 'top_stdg_nm': r.get('top_stdg_nm')} for r in top_down],
        'base_rate_latest': latest_macro.get('base_rate') if latest_macro else None,
        'base_rate_drop_12m': base_drop,
        'mortgage_rate_latest': latest_macro.get('mortgage_rate') if latest_macro else None,
    }


_MARKET_SUMMARY_PROMPT = """/no_think
너는 한국어 부동산 시장 분석가다. 주어진 서울 25구 부동산 시장 데이터를 일반 투자자가 이해하도록 한 단락(3~4문장)으로 요약하라.

배경 지식:
- "매수/관망/주의" 는 25구별 매수 시그널 분포
- "가격 상승/하락 top" 은 3개월 평단가 변화율 기준
- 기준금리는 한국은행 기준금리

설명할 내용:
1. 25구 시그널 분포 (매수 N개, 관망 M개, 주의 K개) 의 의미
2. 가격이 가장 많이 상승/하락한 구 1~2개와 변화율
3. 금리 환경 (기준금리 + 12개월 변화)
4. 이 모든 신호가 의미하는 오늘의 매수 환경 한 마디

규칙:
- 3~4문장, 총 250자 이내
- 부드러운 어투
- 마크다운/불릿 금지
- 줄바꿈 가능"""


@router.get('/market-summary')
def get_market_summary():
    """오늘의 서울 부동산 시장 LLM 요약 (24h 캐시).

    응답:
      {
        "summary": "...한 단락 LLM 요약...",
        "signal_distribution": {"매수": N, "관망": M, "주의": K},
        "top_up": [...],
        "top_down": [...],
        "base_rate_latest": ...,
        "as_of": "YYYY-MM-DD HH:MM",
        "cached": true|false
      }
    """
    now = _time.time()
    cached = _market_summary_cache['data']
    if cached and (now - _market_summary_cache['ts']) < _MARKET_SUMMARY_TTL:
        return {**cached, 'cached': True}

    data = _build_market_summary_data()

    # LLM 호출 — 부동산 sites 측 helper 부재 → market_summary._groq_call 재사용
    try:
        from api.routers.market_summary import _groq_call
        import json as _json
        user_text = _json.dumps(data, ensure_ascii=False, indent=2)
        summary_text = _groq_call(_MARKET_SUMMARY_PROMPT, user_text, max_tokens=350)
    except Exception as e:
        print(f'[real_estate.market_summary] LLM 실패: {e}')
        summary_text = None

    if not summary_text:
        # Fallback — 룰베이스 한 줄
        sd = data['signal_distribution']
        summary_text = (
            f"오늘의 서울 부동산 시그널 분포: 매수 {sd['매수']}구, "
            f"관망 {sd['관망']}구, 주의 {sd['주의']}구. "
            f"기준금리 {data.get('base_rate_latest', '-')}% (12개월 변화 "
            f"{data.get('base_rate_drop_12m', '-')}%p)."
        )

    from datetime import datetime, timezone, timedelta
    as_of = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')

    response = {
        'summary': summary_text,
        'signal_distribution': data['signal_distribution'],
        'top_up': data['top_up'],
        'top_down': data['top_down'],
        'base_rate_latest': data['base_rate_latest'],
        'base_rate_drop_12m': data['base_rate_drop_12m'],
        'as_of': as_of,
        'cached': False,
    }
    _market_summary_cache['data'] = response
    _market_summary_cache['ts'] = now
    return response
