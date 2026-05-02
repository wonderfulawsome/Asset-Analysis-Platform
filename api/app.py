import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from api.routers import regime, macro, index_feed, sector_cycle, crash_surge, market_summary, chart, real_estate
try:
    from api.routers import tracking
except Exception:
    tracking = None
from scheduler.job import run_pipeline

# 환경변수로 스케줄러 ON/OFF 제어 (기본값: true — 단일 서비스 운영 시 스케줄러 활성)
# 별도 스케줄러 서비스 분리 후 웹 서비스에서 RUN_SCHEDULER=false 로 전환
_scheduler_enabled = os.getenv('RUN_SCHEDULER', 'true').lower() == 'true'


def _need_init_once(models_dir: str) -> bool:
    """첫 deploy 또는 어떤 모델 .pkl 이라도 빠져있으면 True.

    - HMM, crash_surge .pkl
    - chart_models/{ticker}.pkl × 16 (Stage 4 가드)
    """
    from processor.feature4_chart_predict import CHART_TICKERS
    required = [
        os.path.join(models_dir, 'noise_hmm.pkl'),
        os.path.join(models_dir, 'crash_surge_xgb.pkl'),
    ]
    chart_dir = os.path.join(models_dir, 'chart_models')
    chart_pkls = [os.path.join(chart_dir, f'{t}.pkl') for t in CHART_TICKERS]
    return any(not os.path.exists(p) for p in required + chart_pkls)


def _train_chart_models_monthly():
    """월 1회 16 ETF × 5-모델 앙상블 재학습 + .pkl 저장 + DB upsert.

    Stage 3 — full_pipeline (3시간) 은 추론만, 이 함수가 학습 전담.
    """
    print('[App][train_monthly] 16 ETF chart 모델 재학습 시작')
    try:
        from processor.feature4_chart_predict import run_chart_predict_single, CHART_TICKERS
        from database.repositories import upsert_chart_predict
        ok, fail = 0, 0
        for ticker in CHART_TICKERS:
            try:
                res = run_chart_predict_single(ticker, train=True)
                if res:
                    upsert_chart_predict(res)
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                print(f'[App][train_monthly] {ticker} 실패: {e}')
                fail += 1
        print(f'[App][train_monthly] 완료 — 성공 {ok}, 실패 {fail}')
    except Exception as e:
        print(f'[App][train_monthly] 전체 실패: {e}')


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler = None
    if _scheduler_enabled:
        scheduler = BackgroundScheduler()
        # 경량 파이프라인: 10분마다 최근 데이터만 갱신 (거시지표 + ETF 가격 + 실시간 예측)
        scheduler.add_job(run_pipeline, 'interval', minutes=10, id='light_pipeline', kwargs={'light': True})
        # supabase TLS keepalive: 4분마다 1회 ping → idle 닫힘 방지 (cold = 5~6s 대신 0.3s 유지)
        def _supabase_keepalive():
            try:
                from database.supabase_client import get_client
                get_client().table('app_cache').select('cache_key').limit(1).execute()
            except Exception as e:
                print(f'[App][keepalive] {e}')
        scheduler.add_job(_supabase_keepalive, 'interval', minutes=4, id='supabase_keepalive')
        # 전체 파이프라인: 3시간마다 실행 (수집 + HMM/XGBoost/chart 모두 추론, chart 학습 X)
        scheduler.add_job(run_pipeline, 'interval', hours=3, id='full_pipeline')
        # Stage 3: 매월 1일 03:00 KST (= UTC 18:00) chart 5-모델 재학습 1회
        scheduler.add_job(
            _train_chart_models_monthly,
            CronTrigger(day=1, hour=18, minute=0),
            id='train_chart_pipeline',
        )
        # KR Stage 2C: 매일 16:00 KST (= UTC 07:00) 한국 시장 데이터 1회 적재
        # KR 장 마감(15:30) 후 30분 뒤 — 일별 단위 분석이라 분당 갱신 불필요
        try:
            from scheduler.job_kr import run_kr_pipeline
            scheduler.add_job(
                run_kr_pipeline,
                CronTrigger(hour=7, minute=0),  # UTC 07:00 = KST 16:00
                id='kr_daily_pipeline',
            )
            print('[App] KR 일일 파이프라인 등록 (KST 16:00, UTC 07:00)')
        except Exception as e:
            print(f'[App] KR 파이프라인 등록 실패 (collector 미설치 가능성): {e}')
        # Stage 4: 모델 .pkl 하나라도 빠져있으면 60초 후 init_once 1회 실행
        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
        if _need_init_once(models_dir):
            from datetime import datetime, timedelta
            scheduler.add_job(run_pipeline, 'date', run_date=datetime.now() + timedelta(seconds=60), id='init_once')
            print('[App] 모델 .pkl 미완비 — 60초 후 초기 full pipeline 1회 실행 (chart 모델은 fallback 학습)')
        else:
            print('[App] 모든 모델 .pkl 존재 — init_once 건너뜀')
        scheduler.start()
        print('[App] 스케줄러 활성화 (light=10m, full=3h 추론, train=매월 1일 03:00 KST)')
    else:
        print('[App] 스케줄러 비활성화 — 웹 서버 전용 모드 (RUN_SCHEDULER=false)')
    # Supabase TLS warmup — 첫 요청의 핸드셰이크 5~6초를 startup 으로 옮김
    try:
        from database.supabase_client import get_client
        get_client().table('app_cache').select('cache_key').limit(1).execute()
        print('[App] supabase warmup OK')
    except Exception as e:
        print(f'[App] supabase warmup 실패 (무시): {e}')
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

# GZip 압축 — 마지막 add 가 outermost (Starlette 규약). JSON/HTML/JS/CSS 1KB+ 자동 압축.
app.add_middleware(GZipMiddleware, minimum_size=500)

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
app.include_router(real_estate.router, prefix='/api/realestate', tags=['부동산'])
if tracking:
    app.include_router(tracking.router, prefix='/api/tracking', tags=['사용자 추적'])

@app.get('/')
def root():
    # 부동산 SPA 가 아직 미완성 → landing 우회하고 바로 주식 앱 (/stocks) 으로 직행.
    # 부동산 완성되면 templates.TemplateResponse(name='landing.html') 로 복귀.
    return RedirectResponse(url='/stocks', status_code=307)

@app.get('/stocks')
def stocks_page(request: Request):
    return templates.TemplateResponse(request=request, name='stocks.html')

@app.get('/stats')
def stats_page(request: Request):
    return templates.TemplateResponse(request=request, name='stats.html')

# /realestate/* 는 모두 Vite 빌드 index.html로 — React Router가 클라이언트 라우팅 처리.
# /static/realestate/assets/* 는 StaticFiles 마운트가 먼저 잡으므로 충돌 없음.
@app.get('/realestate')
@app.get('/realestate/{path:path}')
def realestate_spa(request: Request, path: str = ''):
    return FileResponse('static/realestate/index.html')

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
SITE_URL = 'https://dinsightlab.com'

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