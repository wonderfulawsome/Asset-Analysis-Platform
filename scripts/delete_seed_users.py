"""
seed_users.py로 추가된 더미 사용자 21명을 Supabase user_visit 테이블에서 삭제합니다.
is_new=True인 더미 유저들을 날짜 기준으로 삭제합니다.

사용법:
  python scripts/delete_seed_users.py
"""
import sys

# 삭제 대상 날짜 및 각 날짜별 삭제 수량 (총 21명)
DELETE_DISTRIBUTION = {
    "2026-03-01": 1,
    "2026-03-05": 1,
    "2026-03-10": 1,
    "2026-03-13": 3,
    "2026-03-14": 4,
    "2026-03-15": 3,
    "2026-03-16": 2,
    "2026-03-17": 2,
    "2026-03-18": 2,
    "2026-03-19": 1,
    "2026-03-20": 1,
}
# 합계: 21명


def delete_seed_users():
    sys.path.insert(0, ".")
    from database.supabase_client import get_client

    client = get_client()
    total_deleted = 0

    for visit_date, target_count in DELETE_DISTRIBUTION.items():
        # 해당 날짜의 is_new=True 레코드 조회
        rows = (
            client.table("user_visit")
            .select("id")
            .eq("visit_date", visit_date)
            .eq("is_new", True)
            .limit(target_count)
            .execute()
        )
        if not rows.data:
            continue

        ids_to_delete = [r["id"] for r in rows.data[:target_count]]
        for row_id in ids_to_delete:
            client.table("user_visit").delete().eq("id", row_id).execute()

        print(f"  {visit_date}: {len(ids_to_delete)}건 삭제")
        total_deleted += len(ids_to_delete)

    print(f"\n총 {total_deleted}/21건 삭제 완료")


if __name__ == "__main__":
    delete_seed_users()
