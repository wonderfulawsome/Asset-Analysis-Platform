데이터는 단방향으로 흐른다: 외부 소스 → 수집기 → (Supabase + 처리기) → API → 프론트엔드. FRED 캐시(fred_cache)를 통해 Step 3에서 수집한 데이터를 Step 7에서 재사용하여 중복 API 호출을 방지한다.
