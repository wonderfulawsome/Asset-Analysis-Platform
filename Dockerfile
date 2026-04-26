# Stage 1: React 빌드
# vite.config.ts 의 outDir="../static/realestate" → /project/static/realestate 로 산출.
FROM node:20-slim AS frontend-builder
WORKDIR /project

# package.json 만 먼저 복사 → 소스 변경 시에도 npm install 레이어 재활용.
COPY frontend-realestate/package.json frontend-realestate/
RUN cd frontend-realestate && npm install

# 나머지 소스 복사 후 빌드 (해시된 자산 파일명으로 번들링됨).
COPY frontend-realestate/ frontend-realestate/
RUN cd frontend-realestate && npm run build


# Stage 2: Python 서버
FROM python:3.11-slim
WORKDIR /app

# uvicorn 로그가 버퍼링되면 Railway 대시보드에서 실시간 확인 불가.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# xgboost/catboost 등이 런타임에 libgomp 필요 — slim 이미지엔 미포함.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# requirements 먼저 복사 → 코드 변경만 있을 때 pip install 캐시 재활용.
COPY requirements.txt .
RUN pip install -r requirements.txt

# 애플리케이션 코드 복사 (.dockerignore 로 node_modules, data, notebooks 등 제외).
COPY . .

# Stage 1 의 Vite 산출물을 static/realestate 로 덮어쓰기
# (.dockerignore 로 로컬 산출물이 복사되지 않아 덮어쓸 대상이 비어있음).
COPY --from=frontend-builder /project/static/realestate static/realestate

# runtime 에 HMM/XGBoost 모델 파일이 생성될 디렉토리.
RUN mkdir -p models

# Railway 등 PaaS 는 PORT 환경변수로 포트 주입 — shell 치환으로 받음.
CMD uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000}
