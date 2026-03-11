import os
import threading
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_local = threading.local()


def get_client() -> Client:
    if not hasattr(_local, 'client'):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError(".env에 SUPABASE_URL과 SUPABASE_KEY를 설정하세요.")
        _local.client = create_client(url, key)
    return _local.client

########## .env에서 Supabase 접속 정보를 읽어 DB 연결 객체를 한 번만 생성하고 재사용하는 파일