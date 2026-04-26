"""sector_valuation 분기별 historical backfill — siblis research 스크래핑.

siblis 가 무료 페이지에 11개 GICS sector 분기별 CAPE + P/B 노출 (2.5년치).
운용사·yfinance·FMP 모두 ETF 직접 historical valuation 안 주는 상황에서 가장
honest 한 무료 소스. CAPE 는 trailing PE 가 아니라 Shiller 10년 평균 PE 라서
모달 라벨을 "PER" → "CAPE" 로 변경 필요 (별도 작업).

매핑:
  Information Technology → XLK + IGV (IGV = Software, IT 의 sub-sector)
  나머지 10 sector → 1 ETF 씩

URL:
  https://siblisresearch.com/data/cape-ratios-by-sector/        (CAPE)
  https://siblisresearch.com/data/price-to-book-sector/         (P/B)
"""
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from collector.sector_valuation import SECTOR_VALUATION_ETFS
from database.repositories import upsert_sector_valuation


CAPE_URL = "https://siblisresearch.com/data/cape-ratios-by-sector/"
PB_URL = "https://siblisresearch.com/data/price-to-book-sector/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)

# siblis sector_name → 우리 ETF ticker 들
SECTOR_TO_ETFS: dict[str, list[str]] = {
    "Communications":         ["XLC"],
    "Consumer Discretionary": ["XLY"],
    "Consumer Staples":       ["XLP"],
    "Energy":                 ["XLE"],
    "Financials":             ["XLF"],
    "Health Care":            ["XLV"],
    "Industrials":            ["XLI"],
    "Information Technology": ["XLK", "IGV"],   # IGV 도 IT 시계열 공유
    "Materials":              ["XLB"],
    "Real Estate":            ["XLRE"],
    "Utilities":              ["XLU"],
}


def parse_siblis_table(html: str) -> dict[str, dict[str, float]]:
    """siblis 페이지의 첫 번째 데이터 테이블 파싱.

    반환: {sector_name: {date_str(M/D/YYYY): value}}
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        raise RuntimeError("siblis 페이지에서 <table> 못 찾음")
    rows = table.find_all("tr")
    headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    date_cols = headers[1:]   # 첫 컬럼은 'GICS Sector'

    out: dict[str, dict[str, float]] = {}
    for tr in rows[1:]:
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) != len(headers):
            continue
        sector = cells[0]
        out[sector] = {}
        for i, val in enumerate(cells[1:]):
            v = (val or "").replace(",", "").replace("\xa0", "").strip()
            if not v or v == "-":
                continue
            try:
                out[sector][date_cols[i]] = float(v)
            except ValueError:
                pass
    return out


def normalize_date(s: str) -> str:
    """'12/31/2025' or '12/30/2024' → '2025-12-31'."""
    return datetime.strptime(s, "%m/%d/%Y").date().isoformat()


def fetch_siblis(url: str) -> dict[str, dict[str, float]]:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return parse_siblis_table(r.text)


def backfill_siblis() -> int:
    cape = fetch_siblis(CAPE_URL)  # {sector: {date: cape}}
    pb = fetch_siblis(PB_URL)      # {sector: {date: pb}}

    rows: list[dict] = []
    for sector, etfs in SECTOR_TO_ETFS.items():
        cape_series = cape.get(sector, {})
        pb_series = pb.get(sector, {})
        all_dates = set(cape_series.keys()) | set(pb_series.keys())
        for d_str in all_dates:
            iso_date = normalize_date(d_str)
            for etf in etfs:
                rows.append({
                    "date": iso_date,
                    "ticker": etf,
                    "sector_name": SECTOR_VALUATION_ETFS.get(etf, sector),
                    "per": cape_series.get(d_str),     # CAPE 를 per 컬럼에 저장
                    "pbr": pb_series.get(d_str),       # trailing P/B
                })

    if not rows:
        print("[siblis] 0 행 — 파싱 실패")
        return 0
    for i in range(0, len(rows), 100):
        upsert_sector_valuation(rows[i:i + 100])
    print(f"[siblis] 총 {len(rows)} 행 upsert (CAPE + P/B)")
    return len(rows)


if __name__ == "__main__":
    backfill_siblis()
