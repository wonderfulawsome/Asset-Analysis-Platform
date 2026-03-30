import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse            # 텍스트 응답 (robots.txt 등)
from fastapi.middleware.cors import CORSMiddleware        # CORS 미들웨어 (앱에서 API 호출용)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.background import BackgroundScheduler
from api.routers import regime, macro, index_feed, sector_cycle, crash_surge, market_summary, chart
try:
    from api.routers import tracking
except Exception:
    tracking = None
from scheduler.job import run_pipeline

# 환경변수로 스케줄러 ON/OFF 제어 (기본값: true — 단일 서비스 운영 시 스케줄러 활성)
# 별도 스케줄러 서비스 분리 후 웹 서비스에서 RUN_SCHEDULER=false 로 전환
_scheduler_enabled = os.getenv('RUN_SCHEDULER', 'true').lower() == 'true'


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler = None
    if _scheduler_enabled:
        scheduler = BackgroundScheduler()
        # 경량 파이프라인: 10분마다 최근 데이터만 갱신 (거시지표 + ETF 가격 + 실시간 예측)
        scheduler.add_job(run_pipeline, 'interval', minutes=10, id='light_pipeline', kwargs={'light': True})
        # 전체 파이프라인: 3시간마다 실행 (100년치 수집 + HMM/XGBoost 모델 학습)
        scheduler.add_job(run_pipeline, 'interval', hours=3, id='full_pipeline')
        # 모델 파일이 없을 때만 시작 60초 후 1회 full pipeline 실행
        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
        hmm_exists = os.path.exists(os.path.join(models_dir, 'noise_hmm.pkl'))
        cs_exists = os.path.exists(os.path.join(models_dir, 'crash_surge_xgb.pkl'))
        if not hmm_exists or not cs_exists:
            from datetime import datetime, timedelta
            scheduler.add_job(run_pipeline, 'date', run_date=datetime.now() + timedelta(seconds=60), id='init_once')
            print('[App] 모델 없음 — 60초 후 초기 full pipeline 1회 실행')
        scheduler.start()
        print('[App] 스케줄러 활성화 (RUN_SCHEDULER=true)')
    else:
        print('[App] 스케줄러 비활성화 — 웹 서버 전용 모드 (RUN_SCHEDULER=false)')
    # FastAPI 앱 실행 구간 (요청 처리)
    yield
    # 서버 종료 시 스케줄러 정리
    if scheduler:
        scheduler.shutdown()

# FastAPI로 서버 생성
app = FastAPI(title='Passive 투자 비서 API', version='0.1.0', lifespan=lifespan)

# CORS 허용 (React Native WebView 등 외부 앱에서 API 호출 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],                                  # 모든 출처 허용
    allow_methods=["*"],                                  # 모든 HTTP 메서드 허용
    allow_headers=["*"],                                  # 모든 헤더 허용
)

# 정적 파일을 /static url로 요청을 보냄
app.mount('/static', StaticFiles(directory='static'), name='static')
templates = Jinja2Templates(directory='templates')

# regime.router의 요청을 /api/regime 경로로 등록
app.include_router(regime.router,     prefix='/api/regime', tags=['시장 국면'])
# macro.router의 요청을 /api/macro 경로로 등록
app.include_router(macro.router,      prefix='/api/macro',  tags=['거시 지표'])
# index_feed.router의 요청을 /api/index 경로로 등록
app.include_router(index_feed.router,    prefix='/api/index',        tags=['인덱스 피드'])
app.include_router(sector_cycle.router,  prefix='/api/sector-cycle', tags=['섹터 경기국면'])
app.include_router(crash_surge.router,  prefix='/api/crash-surge',  tags=['폭락/급등 전조'])
app.include_router(market_summary.router, prefix='/api/market-summary', tags=['마켓 오버뷰'])
app.include_router(chart.router, prefix='/api/chart', tags=['차트'])
if tracking:
    app.include_router(tracking.router, prefix='/api/tracking', tags=['사용자 추적'])

# GET / 요청이 오면 index.html을 렌더링해서 반환
@app.get('/')
def root(request: Request):
    return templates.TemplateResponse(request=request, name='index.html')

# 사용자 통계 대시보드 페이지
@app.get('/stats')
def stats_page(request: Request):
    return templates.TemplateResponse(request=request, name='stats.html')

# 파이프라인 헬스체크: 스케줄러 상태 + 모델 파일 존재 여부
@app.get('/api/health')
def health_check():
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
    result = {
        'scheduler_enabled': _scheduler_enabled,
        'noise_model': os.path.exists(os.path.join(models_dir, 'noise_hmm.pkl')),
        'cs_model': os.path.exists(os.path.join(models_dir, 'crash_surge_xgb.pkl')),
        'fred_cache': os.path.exists(os.path.join(models_dir, 'fred_cache.pkl')),
    }
    try:
        result['model_files'] = os.listdir(models_dir)
    except Exception:
        result['model_files'] = []
    return result

@app.get('/api/health/diagnose')
def diagnose():
    """Step 3 각 단계를 개별 실행하여 어디서 실패하는지 진단."""
    import traceback, datetime
    diag = {}

    # 1) Shiller
    try:
        from collector.noise_regime_data import fetch_shiller
        shiller = fetch_shiller()
        diag['shiller'] = f'OK ({len(shiller)}rows)'
    except Exception as e:
        diag['shiller'] = f'FAIL: {e}'

    # 2) FRED
    try:
        from collector.noise_regime_data import fetch_fred_regime
        fred = fetch_fred_regime()
        diag['fred'] = f'OK ({list(fred.keys())})'
    except Exception as e:
        diag['fred'] = f'FAIL: {e}'

    # 3) Sector stocks
    try:
        from collector.noise_regime_data import fetch_sector_stocks
        start_date = str(datetime.date.today() - datetime.timedelta(days=365 * 18 + 30))
        stocks = fetch_sector_stocks(start_date)
        diag['sector_stocks'] = f'OK ({stocks.shape})'
    except Exception as e:
        diag['sector_stocks'] = f'FAIL: {e}'

    # 4) Amihud
    try:
        from collector.noise_regime_data import fetch_amihud_stocks
        start_date = str(datetime.date.today() - datetime.timedelta(days=365 * 18 + 30))
        amihud = fetch_amihud_stocks(start_date)
        diag['amihud'] = f'OK ({len(amihud)} tickers)'
    except Exception as e:
        diag['amihud'] = f'FAIL: {e}'

    # 5) Monthly features
    try:
        from collector.noise_regime_data import compute_monthly_features
        bundle = compute_monthly_features(shiller, fred, stocks, amihud)
        diag['monthly_features'] = f'OK ({len(bundle["features"])}rows)'
    except Exception as e:
        diag['monthly_features'] = f'FAIL: {e}'

    # 6) HMM train
    try:
        from processor.feature1_regime import train_hmm
        model_bundle = train_hmm(bundle['features'], monthly_bundle=bundle)
        diag['hmm_train'] = f'OK (month: {model_bundle.get("train_month")})'
    except Exception as e:
        diag['hmm_train'] = f'FAIL: {e}'

    return diag

# 사이트 도메인 (sitemap, robots.txt에서 사용)
SITE_URL = 'https://passive-financial-data-analysis-production.up.railway.app'

# robots.txt: 검색엔진 크롤러 허용 규칙 + sitemap 위치
@app.get('/robots.txt', response_class=PlainTextResponse)
def robots_txt():
    return (                                               # 모든 크롤러 허용, API 경로는 차단
        'User-agent: *\n'
        'Allow: /\n'
        'Disallow: /api/\n'
        f'Sitemap: {SITE_URL}/sitemap.xml\n'
    )

# TikTok 도메인 인증 파일
@app.get('/tiktokPFHpLA0MzDof0SYGfC4gfqJEhsk65ZrR.txt')
def tiktok_verify():
    file_path = os.path.join('static', 'tiktokPFHpLA0MzDof0SYGfC4gfqJEhsk65ZrR.txt')
    with open(file_path, 'r') as f:
        return PlainTextResponse(f.read())

# sitemap.xml: 검색엔진에 크롤링 대상 URL 제공
@app.get('/sitemap.xml', response_class=PlainTextResponse)
def sitemap_xml():
    return (                                               # XML 형식 사이트맵
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'  <url><loc>{SITE_URL}/</loc><priority>1.0</priority></url>\n'
        '</urlset>\n'
    )

# -------------------------------------------------------------------
### 3시간 스케줄링
### 어떤 URL로 요청받고, 어디서 데이터 가져오고, 언제 자동 실행할지를 한 곳에서 정의

# -------------------------------------------------------------------
# FAST API: 브라우저에서 html이 요청을 보내면 index.html 화면을 보여줌 