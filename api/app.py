from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware        # CORS 미들웨어 (앱에서 API 호출용)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.background import BackgroundScheduler
from api.routers import regime, macro, index_feed, sector_cycle, crash_surge, market_summary
from scheduler.job import run_pipeline


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 백그라운드 스레드에서 동작하는 스케줄러 인스턴스 생성
    scheduler = BackgroundScheduler()
    # 경량 파이프라인: 30분마다 최근 데이터만 갱신 (거시지표 60일 + Fear&Greed + ETF 가격)
    scheduler.add_job(run_pipeline, 'interval', minutes=30, id='light_pipeline', kwargs={'light': True})
    # 전체 파이프라인: 3시간마다 실행 (100년치 수집 + HMM/XGBoost 모델 학습)
    scheduler.add_job(run_pipeline, 'interval', hours=3, id='full_pipeline')
    # 서버 시작 30초 후 경량 파이프라인 1회 실행 (Windows 소켓 충돌 방지)
    from datetime import datetime, timedelta
    scheduler.add_job(run_pipeline, 'date', run_date=datetime.now() + timedelta(seconds=30),
                      id='init_pipeline', kwargs={'light': True})
    scheduler.start()
    # FastAPI 앱 실행 구간 (요청 처리)
    yield
    # 서버 종료 시 스케줄러 정리
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

# GET / 요청이 오면 index.html을 렌더링해서 반환
@app.get('/')
def root(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})

# -------------------------------------------------------------------
### 3시간 스케줄링
### 어떤 URL로 요청받고, 어디서 데이터 가져오고, 언제 자동 실행할지를 한 곳에서 정의

# -------------------------------------------------------------------
# FAST API: 브라우저에서 html이 요청을 보내면 index.html 화면을 보여줌 