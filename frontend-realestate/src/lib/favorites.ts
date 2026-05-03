import { useEffect, useState } from "react";

// localStorage 기반 관심·최근 검색 — 계정 시스템 없음. 사용자 1대 디바이스 한정.
// keys:
//   passive:re:fav      → FavoriteItem[] (사용자가 ♥ 토글)
//   passive:re:recent   → FavoriteItem[] (검색에서 클릭한 결과 자동 적재, 최근 20건)

export interface FavoriteItem {
  type: "sgg" | "stdg" | "apt";
  code: string;          // sgg_cd / stdg_cd / apt_seq
  name: string;          // 표시명 (예: "강남구" / "옥길동" / "래미안")
  sgg_cd?: string;       // stdg/apt 일 때 부모 시군구 코드
  sgg_nm?: string;
  addedAt: number;       // unix epoch (ms)
}

const FAV_KEY = "passive:re:fav";
const RECENT_KEY = "passive:re:recent";
const RECENT_MAX = 20;

function load(key: string): FavoriteItem[] {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function save(key: string, items: FavoriteItem[]) {
  try { localStorage.setItem(key, JSON.stringify(items)); } catch { /* quota */ }
}

// 모든 useFavorites 호출자 간 동기화 — storage event + 모듈 in-memory 캐시
const listeners = new Set<() => void>();
function notify() { listeners.forEach((fn) => fn()); }
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === FAV_KEY || e.key === RECENT_KEY) notify();
  });
}

export function useFavorites() {
  const [favorites, setFavorites] = useState<FavoriteItem[]>(() => load(FAV_KEY));
  const [recents, setRecents] = useState<FavoriteItem[]>(() => load(RECENT_KEY));

  useEffect(() => {
    function refresh() {
      setFavorites(load(FAV_KEY));
      setRecents(load(RECENT_KEY));
    }
    listeners.add(refresh);
    return () => { listeners.delete(refresh); };
  }, []);

  function isFavorite(type: FavoriteItem["type"], code: string): boolean {
    return favorites.some((f) => f.type === type && f.code === code);
  }

  function toggleFavorite(item: Omit<FavoriteItem, "addedAt">) {
    const cur = load(FAV_KEY);
    const idx = cur.findIndex((f) => f.type === item.type && f.code === item.code);
    let next: FavoriteItem[];
    if (idx >= 0) next = cur.filter((_, i) => i !== idx);
    else next = [{ ...item, addedAt: Date.now() }, ...cur];
    save(FAV_KEY, next);
    setFavorites(next);
    notify();
  }

  function pushRecent(item: Omit<FavoriteItem, "addedAt">) {
    const cur = load(RECENT_KEY).filter((r) => !(r.type === item.type && r.code === item.code));
    const next = [{ ...item, addedAt: Date.now() }, ...cur].slice(0, RECENT_MAX);
    save(RECENT_KEY, next);
    setRecents(next);
    notify();
  }

  function clearRecents() {
    save(RECENT_KEY, []);
    setRecents([]);
    notify();
  }

  return { favorites, recents, isFavorite, toggleFavorite, pushRecent, clearRecents };
}
