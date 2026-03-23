"""
24명의 더미 사용자를 Supabase user_visit 테이블에 추가하는 스크립트.

사용법:
  1. .env 파일에 SUPABASE_URL, SUPABASE_KEY 설정
  2. python scripts/seed_users.py

또는 배포된 사이트 API를 통해 추가:
  python scripts/seed_users.py --api https://your-site.up.railway.app
"""
import sys
import uuid
import datetime


def seed_via_supabase():
    """Supabase 직접 접속으로 24명 추가"""
    sys.path.insert(0, ".")
    from database.supabase_client import get_client

    client = get_client()
    today = datetime.date.today().isoformat()

    records = []
    for i in range(24):
        records.append({
            "user_hash": str(uuid.uuid4()),
            "visit_date": today,
            "is_new": True,
        })

    # 한 번에 bulk insert
    result = client.table("user_visit").insert(records).execute()
    print(f"{len(result.data)}명 추가 완료 (날짜: {today})")


def seed_via_api(base_url: str):
    """배포된 API를 통해 24명 추가"""
    import urllib.request
    import json

    base_url = base_url.rstrip("/")
    success = 0
    for i in range(24):
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
                print(f"[{i+1}/24] OK")
        except Exception as e:
            print(f"[{i+1}/24] 실패: {e}")

    print(f"\n총 {success}/24명 추가 완료")


if __name__ == "__main__":
    if "--api" in sys.argv:
        idx = sys.argv.index("--api")
        if idx + 1 < len(sys.argv):
            seed_via_api(sys.argv[idx + 1])
        else:
            print("사용법: python scripts/seed_users.py --api https://your-site.com")
    else:
        seed_via_supabase()
