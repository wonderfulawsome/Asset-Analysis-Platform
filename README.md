### 시스템 아키텍처

```mermaid
graph LR
    frontend["프론트엔드\ntemplates/ + static/"]
    frontend -->|"fetch /api/*"| api-layer["API 레이어\napi/"]
    api-layer -->|"조회/저장"| database-layer["데이터베이스 레이어\ndatabase/"]
    database-layer -->|"Supabase REST"| supabase-db["Supabase\n외부 PostgreSQL"]
    scheduler-engine["스케줄러 엔진\nscheduler/job.py"]
    scheduler-engine -->|"데이터 수집"| collector-layer["수집 레이어\ncollector/"]
    scheduler-engine -->|"ML 학습/예측"| processor-layer["처리 레이어\nprocessor/"]
    scheduler-engine -->|"결과 저장"| database-layer
    collector-layer -->|"Yahoo/FRED/CNN/CBOE"| external-apis["외부 데이터 소스\nYahoo·FRED·CNN·CBOE"]
    processor-layer -->|"모델 파일 저장"| model-store["모델 저장소\nmodels/"]
    api-layer -->|"실시간 데이터"| external-apis

    classDef external fill:#585b70,stroke:#585b70,color:#cdd6f4
    classDef entry fill:#89b4fa,stroke:#89b4fa,color:#1e1e2e
    classDef store fill:#a6e3a1,stroke:#a6e3a1,color:#1e1e2e

    class supabase-db,external-apis external
    class frontend,scheduler-engine entry
    class model-store,database-layer store
