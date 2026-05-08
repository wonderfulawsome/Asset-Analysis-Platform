from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel
from database.repositories import (
    track_user_visit, fetch_user_stats,
    track_page_view, fetch_page_stats,
)
from database.supabase_client import get_client

router = APIRouter()

KST = timezone(timedelta(hours=9))


def _kst_today():
    """KST 기준 오늘 날짜를 반환합니다."""
    return datetime.now(KST).date()


class VisitRequest(BaseModel):
    user_hash: str


@router.post("/visit")
def record_visit(body: VisitRequest):
    """사용자 방문을 기록하고 신규/재방문 여부를 반환합니다."""
    try:
        today = _kst_today().isoformat()
        result = track_user_visit(body.user_hash, today)
        return result
    except Exception as e:
        print(f"[Tracking] visit 기록 실패: {e}")
        return {"error": "tracking unavailable", "is_new": False}


@router.get("/stats")
def get_stats(
    d: str = Query(default=None, description="조회 날짜 (YYYY-MM-DD). 기본값: 오늘 KST"),
    m: str = Query(default=None, description="조회 월 (YYYY-MM). 기본값: 이번 달 KST"),
):
    """DAU, MAU, 신규/재방문 사용자 통계를 조회합니다."""
    try:
        today = _kst_today()
        target_date = d or today.isoformat()
        target_month = m or today.strftime("%Y-%m")
        return fetch_user_stats(target_date, target_month)
    except Exception as e:
        print(f"[Tracking] stats 조회 실패: {e}")
        return {"error": "tracking unavailable", "dau": 0, "mau": 0, "new_users": 0, "returning_users": 0}


class PageViewRequest(BaseModel):
    user_hash: str
    path: str
    tab: Optional[str] = None
    dwell_ms: Optional[int] = None


@router.post("/page")
def record_page_view(body: PageViewRequest):
    """페이지·탭 조회 1건 기록 (sendBeacon 친화 — fire and forget).

    - path: '/stocks' / '/about' / '/landing' / '/stats' 등
    - tab: '/stocks' 안의 SPA 탭 식별자 (ai-chart/market/fundamental/signal/sector/sector-val/sector-mom/market-valuation). 다른 페이지는 null.
    - dwell_ms: 머문 시간 ms. 페이지 이탈 / 탭 전환 시 보냄. 진입 직후엔 null.
    """
    try:
        today = _kst_today().isoformat()
        track_page_view(body.user_hash, today, body.path, body.tab, body.dwell_ms)
        return {"ok": True}
    except Exception as e:
        print(f"[Tracking] page_view 기록 실패: {e}")
        return {"error": "tracking unavailable", "ok": False}


@router.get("/pages")
def get_page_stats(
    d: str = Query(default=None, description="조회 날짜 (YYYY-MM-DD). 기본값: 오늘 KST"),
):
    """특정 날짜의 페이지·탭별 조회수·고유 사용자수·평균 dwell 집계."""
    try:
        target_date = d or _kst_today().isoformat()
        return fetch_page_stats(target_date)
    except Exception as e:
        print(f"[Tracking] page stats 조회 실패: {e}")
        return {"error": "tracking unavailable", "by_path": [], "by_tab": [],
                "total_views": 0, "total_unique_users": 0}


@router.delete("/purge-dummy")
def purge_dummy_users(
    count: int = Query(default=21, description="삭제할 더미 유저 수"),
):
    """is_new=True인 더미 유저를 최대 count명까지 삭제합니다."""
    try:
        client = get_client()
        # is_new=True인 레코드를 조회
        rows = (
            client.table("user_visit")
            .select("id")
            .eq("is_new", True)
            .limit(count)
            .execute()
        )
        if not rows.data:
            return {"deleted": 0, "message": "삭제할 더미 유저가 없습니다"}

        ids = [r["id"] for r in rows.data]
        for row_id in ids:
            client.table("user_visit").delete().eq("id", row_id).execute()

        return {"deleted": len(ids), "message": f"{len(ids)}명 삭제 완료"}
    except Exception as e:
        print(f"[Tracking] purge 실패: {e}")
        return {"error": str(e), "deleted": 0}
