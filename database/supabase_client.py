import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# 프로세스 단일 client — 이전엔 threading.local() 이라 worker thread 마다 새 client
# (= 새 httpx pool = 새 TLS handshake) 가 만들어져 첫 요청 cold-start 5~6s. supabase-py
# 의 httpx.Client 는 read-only 작업에 thread-safe → 단일 client 공유로 모든 worker
# 가 같은 connection pool 사용. lifespan warmup + scheduler keepalive 가 풀에 hot conn
# 유지하면 어떤 worker thread 로 라우팅돼도 즉시 응답.
_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError(".env에 SUPABASE_URL과 SUPABASE_KEY를 설정하세요.")
        _client = create_client(url, key)
    return _client