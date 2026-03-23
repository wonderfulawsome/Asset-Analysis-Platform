from datetime import date
from fastapi import APIRouter, Query
from pydantic import BaseModel
from database.repositories import track_user_visit, fetch_user_stats

router = APIRouter()


class VisitRequest(BaseModel):
    user_hash: str


@router.post("/visit")
def record_visit(body: VisitRequest):
    """사용자 방문을 기록하고 신규/재방문 여부를 반환합니다."""
    try:
        today = date.today().isoformat()
        result = track_user_visit(body.user_hash, today)
        return result
    except Exception as e:
        print(f"[Tracking] visit 기록 실패: {e}")
        return {"error": "tracking unavailable", "is_new": False}


@router.get("/stats")
def get_stats(
    d: str = Query(default=None, description="조회 날짜 (YYYY-MM-DD). 기본값: 오늘"),
    m: str = Query(default=None, description="조회 월 (YYYY-MM). 기본값: 이번 달"),
):
    """DAU, MAU, 신규/재방문 사용자 통계를 조회합니다."""
    try:
        today = date.today()
        target_date = d or today.isoformat()
        target_month = m or today.strftime("%Y-%m")
        return fetch_user_stats(target_date, target_month)
    except Exception as e:
        print(f"[Tracking] stats 조회 실패: {e}")
        return {"error": "tracking unavailable", "dau": 0, "mau": 0, "new_users": 0, "returning_users": 0}
