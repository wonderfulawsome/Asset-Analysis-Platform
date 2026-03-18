# -------------------------------------------------------------------
# DB 에서 최신 ETF 가격 데이터를 조회해 반환하는 FastAPI 라우터 엔드포인트
# 특정 URL 경로(예: /latest)로 HTTP 요청이 들어왔을 때 어떤 함수를 실행할지 연결해주는 규칙 정의
# -------------------------------------------------------------------
from fastapi import APIRouter
from database.repositories import fetch_index_prices_latest
from database.supabase_client import get_client

router = APIRouter()


@router.get('/latest')
def get_index_latest():
    # DB에서 가장 최근 날짜의 ETF 가격/등락률 조회
    return fetch_index_prices_latest()


@router.get('/debug')
def get_index_debug():
    """DB 데이터 상태 확인용 디버그 엔드포인트"""
    client = get_client()
    # 최근 5개 날짜의 SPY 데이터 확인
    recent = (
        client.table("index_price_raw")
        .select("date,ticker,close,change_pct")
        .eq("ticker", "SPY")
        .order("date", desc=True)
        .limit(5)
        .execute()
    )
    # change_pct != 0 인 행 확인
    nz = (
        client.table("index_price_raw")
        .select("date,ticker,change_pct")
        .or_("change_pct.gt.0,change_pct.lt.0")
        .order("date", desc=True)
        .limit(5)
        .execute()
    )
    return {
        "recent_spy": recent.data,
        "non_zero_rows": nz.data,
        "total_recent": len(recent.data),
        "total_non_zero": len(nz.data),
    }
