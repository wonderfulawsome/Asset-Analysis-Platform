"""
seed_users.py로 추가된 24명의 더미 사용자를 Supabase user_visit 테이블에서 삭제합니다.
is_new=True인 더미 유저들을 날짜 기준으로 삭제합니다.

사용법:
  python scripts/delete_seed_users.py
"""
import sys

# seed_users.py와 동일한 날짜 분배
SEED_DATES = [
    "2026-03-01",
    "2026-03-05",
    "2026-03-10",
    "2026-03-13",
    "2026-03-14",
    "2026-03-15",
    "2026-03-16",
    "2026-03-17",
    "2026-03-18",
    "2026-03-19",
    "2026-03-20",
    "2026-03-21",
    "2026-03-23",
]


def delete_seed_users():
    sys.path.insert(0, ".")
    from database.supabase_client import get_client

    client = get_client()
    total_deleted = 0

    for visit_date in SEED_DATES:
        # 해당 날짜의 is_new=True 레코드를 삭제
        result = (
            client.table("user_visit")
            .delete()
            .eq("visit_date", visit_date)
            .eq("is_new", True)
            .execute()
        )
        count = len(result.data) if result.data else 0
        if count > 0:
            print(f"  {visit_date}: {count}건 삭제")
            total_deleted += count

    print(f"\n총 {total_deleted}건 삭제 완료")


if __name__ == "__main__":
    delete_seed_users()
