# Python 3.11 경량 이미지 사용
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 의존성 먼저 설치 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스코드 복사
COPY . .

# models 디렉토리 생성 (모델 파일 저장용)
RUN mkdir -p models

# Railway가 주입하는 PORT 환경변수 사용 (기본값 8000)
CMD uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000}
