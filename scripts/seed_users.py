"""
24명의 더미 사용자를 Supabase user_visit 테이블에 추가하는 스크립트.
Google Analytics 차트 패턴을 참고하여 날짜별로 분산 배치합니다.

사용법:
  1. .env 파일에 SUPABASE_URL, SUPABASE_KEY 설정
  2. python scripts/seed_users.py

또는 배포된 사이트 API를 통해 추가:
  python scripts/seed_users.py --api https://your-site.up.railway.app
"""
import sys
import uuid
import datetime
import random

# ── 3월 날짜별 사용자 분배 (GA 차트 패턴 참고) ──
# 3월 13~15일 피크, 이후 점차 감소, 나머지 기간 소수
DATE_DISTRIBUTION = {
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
    "2026-03-21": 1,
    "2026-03-23": 2,
}
# 합계: 24명


def seed_via_supabase():
    """Supabase 직접 접속으로 날짜별 분산 추가"""
    sys.path.insert(0, ".")
    from database.supabase_client import get_client

    client = get_client()
    records = []

    for visit_date, count in DATE_DISTRIBUTION.items():
        for _ in range(count):
            records.append({
                "user_hash": str(uuid.uuid4()),
                "visit_date": visit_date,
                "is_new": True,
            })

    random.shuffle(records)
    result = client.table("user_visit").insert(records).execute()

    # 날짜별 결과 요약 출력
    print(f"총 {len(result.data)}명 추가 완료!\n")
    print("날짜별 분배:")
    for date in sorted(DATE_DISTRIBUTION.keys()):
        print(f"  {date}: {DATE_DISTRIBUTION[date]}명")


def seed_via_api(base_url: str):
    """배포된 API를 통해 날짜별 분산 추가"""
    import urllib.request
    import json

    base_url = base_url.rstrip("/")
    success = 0
    total = sum(DATE_DISTRIBUTION.values())

    # API 방식은 visit_date를 서버가 자동 설정하므로,
    # 모든 사용자가 오늘 날짜로 기록됨 (날짜 분산 불가)
    # Supabase 직접 방식을 권장합니다
    print("⚠ API 방식은 모든 사용자가 오늘 날짜로 기록됩니다.")
    print("  날짜 분산이 필요하면 Supabase 직접 방식을 사용하세요.\n")

    for i in range(total):
        user_hash = str(uuid.uuid4())
        data = json.dumps({"user_hash": user_hash}).encode()
        req = urllib.request.Request(
            f"{base_url}/api/tracking/visit",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                json.loads(resp.read())
                success += 1
                print(f"[{i+1}/{total}] OK")
        except Exception as e:
            print(f"[{i+1}/{total}] 실패: {e}")

    print(f"\n총 {success}/{total}명 추가 완료")


if __name__ == "__main__":
    if "--api" in sys.argv:
        idx = sys.argv.index("--api")
        if idx + 1 < len(sys.argv):
            seed_via_api(sys.argv[idx + 1])
        else:
            print("사용법: python scripts/seed_users.py --api https://your-site.com")
    else:
        seed_via_supabase()
