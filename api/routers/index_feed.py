# -------------------------------------------------------------------
# DB 에서 최신 ETF 가격 데이터를 조회해 반환하는 FastAPI 라우터 엔드포인트
# 특정 URL 경로(예: /latest)로 HTTP 요청이 들어왔을 때 어떤 함수를 실행할지 연결해주는 규칙 정의
# -------------------------------------------------------------------
from fastapi import APIRouter
from database.repositories import fetch_index_prices_latest

router = APIRouter()


@router.get('/latest')
def get_index_latest():
    # DB에서 가장 최근 날짜의 ETF 가격/등락률 조회
    return fetch_index_prices_latest()

# http 요청이 오면 DB에서 가장 최근 ETF 가격 데이터를 조회해 반환
