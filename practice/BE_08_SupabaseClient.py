# ============================================================
# BE_08_SupabaseClient — Supabase 연결 싱글턴 빈칸 연습
# 원본: database/supabase_client.py
# 총 빈칸: 25개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

# Q1: 환경변수 접근을 위한 표준 라이브러리 모듈
import ___                                       # Q1: 환경변수 접근용 표준 라이브러리
# Q2: 스레드 안전한 로컬 저장소를 제공하는 모듈
import ___                                       # Q2: 스레드 로컬 저장소 제공 모듈
# Q3~Q4: Supabase 클라이언트 생성 함수와 타입 힌트
from supabase import ___, ___                    # Q3~Q4: 클라이언트 생성 함수 / 클라이언트 타입 클래스
# Q5: .env 파일에서 환경변수를 로드하는 함수
from ___ import load_dotenv                      # Q5: .env 파일 로딩 패키지명

# .env 파일의 환경변수를 프로세스에 로드
___()                                            # Q6: .env 파일 로딩 함수 호출

# Q7: 스레드별 독립 저장소 생성 (각 스레드마다 별도의 client 보관)
_local = threading.___()                         # Q7: 스레드별 독립 저장소 클래스명


# Q8: 반환 타입 힌트
def get_client() -> ___:                         # Q8: Supabase 클라이언트 타입 힌트
    """Supabase 클라이언트를 thread-local 싱글턴으로 반환합니다."""

    # Q9: 스레드 로컬에 'client' 속성이 있는지 확인
    if not ___(___,  '___'):                     # Q9~Q11: 속성 존재 확인 함수 / 검사 대상 객체 / 속성명 문자열

        # Q12~Q13: 환경변수에서 Supabase 접속 정보 읽기
        url = os.___(  "___")                    # Q12~Q13: 환경변수 읽기 메서드 / URL 환경변수 키명
        key = os.___("___")                      # Q14~Q15: 환경변수 읽기 메서드 / API키 환경변수 키명

        # Q16: URL과 KEY가 모두 있는지 검증
        if not url ___  not key:                 # Q16: 논리 연산자 (둘 중 하나라도 없으면)
            # Q17: 설정 누락 시 발생시킬 예외 타입
            raise ___(".env에 SUPABASE_URL과 SUPABASE_KEY를 설정하세요.")  # Q17: 잘못된 값에 대한 예외 클래스

        # Q18: Supabase 클라이언트 객체 생성 후 thread-local에 저장
        _local.___ = ___(url, key)               # Q18~Q19: 저장할 속성명 / 클라이언트 생성 함수

    # Q20: thread-local에서 클라이언트 반환
    return _local.___                            # Q20: 반환할 클라이언트 속성명


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                        | 정답              |
# |----|---------------------------- |-------------------|
# | Q1 | import ___                  | os                |
# | Q2 | import ___                  | threading         |
# | Q3 | from supabase import ___    | create_client     |
# | Q4 | from supabase import ___    | Client            |
# | Q5 | from ___ import load_dotenv | dotenv            |
# | Q6 | ___()                       | load_dotenv       |
# | Q7 | threading.___()             | local             |
# | Q8 | -> ___                      | Client            |
# | Q9 | ___(_local, ...)            | hasattr           |
# | Q10| hasattr(___, ...)           | _local            |
# | Q11| hasattr(..., '___')         | client            |
# | Q12| os.___("...")               | getenv            |
# | Q13| os.getenv("___")            | SUPABASE_URL      |
# | Q14| os.___("...")               | getenv            |
# | Q15| os.getenv("___")            | SUPABASE_KEY      |
# | Q16| not url ___ not key         | or                |
# | Q17| raise ___("...")            | ValueError        |
# | Q18| _local.___ = ...            | client            |
# | Q19| ___(url, key)               | create_client     |
# | Q20| _local.___                  | client            |
# ============================================================
