# ============================================================
# BE_11_FastAPI — FastAPI 앱 설정 빈칸 연습
# 원본: api/app.py
# 총 빈칸: 35개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

# Q1~Q6: 필요한 모듈 임포트
from contextlib import ___                               # Q1: 비동기 컨텍스트 매니저 데코레이터
from fastapi import ___                                  # Q2: FastAPI 앱 클래스
from fastapi import ___                                  # Q3: HTTP 요청 객체 클래스
from fastapi.middleware.cors import ___                   # Q4: CORS 미들웨어 클래스
from fastapi.staticfiles import ___                      # Q5: 정적 파일 서빙 클래스
from fastapi.templating import ___                       # Q6: Jinja2 템플릿 엔진 클래스
from apscheduler.schedulers.background import ___        # Q7: 백그라운드 스케줄러 클래스
from api.routers import regime, macro, index_feed, sector_cycle, crash_surge, market_summary
from scheduler.job import ___                            # Q8: 파이프라인 실행 함수


@___                                                     # Q9: 비동기 컨텍스트 매니저 데코레이터
async def lifespan(_app: FastAPI):
    """서버 시작/종료 시 스케줄러를 관리하는 lifespan 컨텍스트."""
    # Q10: 백그라운드 스케줄러 생성
    scheduler = ___()                                    # Q10: 백그라운드 스케줄러 인스턴스 생성

    # Q11: 경량 파이프라인 — 10분마다 실행
    scheduler.___(run_pipeline, '___', minutes=___, id='light_pipeline',  # Q11~Q13: 작업 등록 메서드, 주기적 트리거 유형, 실행 간격(분)
                       kwargs={'___': True})              # Q14: 경량 모드를 활성화하는 파라미터 키

    # Q15: 전체 파이프라인 — 3시간마다 실행
    scheduler.add_job(run_pipeline, 'interval', hours=___, id='full_pipeline')  # Q15: 전체 파이프라인 실행 간격(시간)

    # Q16: 서버 시작 30초 후 전체 파이프라인 1회 실행
    from datetime import datetime, timedelta
    scheduler.add_job(run_pipeline, '___', run_date=datetime.now() + timedelta(seconds=___),  # Q16~Q17: 특정 시각에 1회 실행하는 트리거 유형, 지연 시간(초)
                      id='init_pipeline')

    scheduler.___()                                      # Q18: 스케줄러를 시작하는 메서드
    ___                                                  # Q19: 제너레이터 제어권을 양보하는 키워드 (lifespan 중간 지점)
    scheduler.___()                                      # Q20: 스케줄러를 종료하는 메서드


# Q21: FastAPI 앱 생성
app = ___(title='Passive 투자 비서 API', version='___', lifespan=___)  # Q21~Q23: 웹 프레임워크 앱 클래스, API 버전 문자열, lifespan 함수명

# Q24: CORS 미들웨어 추가 (모든 출처 허용)
app.___(                                                 # Q24: 미들웨어를 추가하는 메서드
    CORSMiddleware,
    allow_origins=["___"],                                # Q25: 모든 출처를 허용하는 와일드카드 문자
    allow_methods=["*"],
    allow_headers=["*"],
)

# Q26: 정적 파일 마운트
app.___(  '/static', StaticFiles(directory='___'), name='static')  # Q26~Q27: 정적 파일 경로를 마운트하는 메서드, 정적 파일 폴더명

# Q28: 템플릿 엔진 설정
templates = Jinja2Templates(directory='___')              # Q28: 템플릿 파일이 저장된 폴더명

# Q29~Q34: 라우터 등록
app.___(regime.router,     prefix='/api/___', tags=['시장 국면'])   # Q29~Q30: 라우터를 등록하는 메서드, 국면 관련 API 경로명
app.include_router(macro.router,      prefix='/api/___',  tags=['거시 지표'])  # Q31: 거시 지표 API 경로명
app.include_router(index_feed.router, prefix='/api/___',  tags=['인덱스 피드'])  # Q32: 인덱스 피드 API 경로명
app.include_router(sector_cycle.router,  prefix='/api/___', tags=['섹터 경기국면'])  # Q33: 섹터 경기국면 API 경로명 (하이픈 포함)
app.include_router(crash_surge.router,  prefix='/api/___',  tags=['폭락/급등 전조'])  # Q34
app.include_router(market_summary.router, prefix='/api/market-summary', tags=['마켓 오버뷰'])


# Q35: 루트 경로 핸들러
@app.get('___')                                          # Q35
def root(request: Request):
    return templates.TemplateResponse('___', {'request': request})  # Q36


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | from contextlib import ___    | asynccontextmanager    |
# | Q2 | from fastapi import ___       | FastAPI                |
# | Q3 | from fastapi import ___       | Request                |
# | Q4 | import ___                    | CORSMiddleware         |
# | Q5 | import ___                    | StaticFiles            |
# | Q6 | import ___                    | Jinja2Templates        |
# | Q7 | import ___                    | BackgroundScheduler    |
# | Q8 | import ___                    | run_pipeline           |
# | Q9 | @___                          | asynccontextmanager    |
# | Q10| ___()                         | BackgroundScheduler    |
# | Q11| scheduler.___                 | add_job                |
# | Q12| '___'                         | interval               |
# | Q13| minutes=___                   | 10                     |
# | Q14| '___': True                   | light                  |
# | Q15| hours=___                     | 3                      |
# | Q16| '___'                         | date                   |
# | Q17| seconds=___                   | 30                     |
# | Q18| scheduler.___()               | start                  |
# | Q19| ___                           | yield                  |
# | Q20| scheduler.___()               | shutdown               |
# | Q21| ___(...)                       | FastAPI                |
# | Q22| version='___'                 | 0.1.0                  |
# | Q23| lifespan=___                  | lifespan               |
# | Q24| app.___                       | add_middleware          |
# | Q25| allow_origins=["___"]         | *                      |
# | Q26| app.___                       | mount                  |
# | Q27| directory='___'               | static                 |
# | Q28| directory='___'               | templates              |
# | Q29| app.___                       | include_router         |
# | Q30| prefix='/api/___'             | regime                 |
# | Q31| prefix='/api/___'             | macro                  |
# | Q32| prefix='/api/___'             | index                  |
# | Q33| prefix='/api/___'             | sector-cycle           |
# | Q34| prefix='/api/___'             | crash-surge            |
# | Q35| @app.get('___')               | /                      |
# | Q36| '___'                         | index.html             |
# ============================================================
