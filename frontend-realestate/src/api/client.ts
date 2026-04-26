const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

// fetch 래퍼 — baseURL·에러 처리를 한 곳에서 관리.
// 4xx/5xx는 Error를 throw해 호출부에서 catch하도록 통일.
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, init);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}
