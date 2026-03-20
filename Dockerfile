# ── Stage 1: 빌드 (의존성 설치) ──
FROM python:3.11-slim AS builder

WORKDIR /app

# 시스템 빌드 도구 (일부 패키지 컴파일에 필요)
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# PyTorch CPU-only 경량 버전 먼저 설치 (CUDA 제거로 ~4GB 절약)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# 나머지 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: 런타임 (경량 이미지) ──
FROM python:3.11-slim

WORKDIR /app

# 빌드 스테이지에서 설치된 패키지만 복사
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 소스코드 복사
COPY . .

# models 디렉토리 생성 (모델 파일 저장용)
RUN mkdir -p models

# Railway가 주입하는 PORT 환경변수 사용 (기본값 8000)
CMD uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000}
