"""홈 화면 '오늘의 종합 판단' 카드용 뉴스 AI 브리핑.

RSS 피드 → 헤드라인 수집 → Groq llama-3.3-70b 한 줄 요약 → in-memory TTL 캐시.
region 별 캐시 분리. TTL 10분.

투자자문 회피 — 프롬프트에서 매수/매도 추천 금지, 사실 묘사만, 한 줄 강제.
"""
import os
import re
import time
import json
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

# RSS 소스 — 무료 공개 피드
_RSS_SOURCES = {
    'kr': [
        ('한경 증권', 'https://rss.hankyung.com/feed/marketstock.xml'),
        ('이데일리 증권', 'https://rss.edaily.co.kr/stock_news.xml'),
        ('매경 증권', 'https://www.mk.co.kr/rss/50200011/'),
    ],
    'us': [
        ('Yahoo Finance', 'https://finance.yahoo.com/news/rssindex'),
        ('MarketWatch', 'https://feeds.content.dowjones.io/public/rss/RSSMarketsMain'),
        ('CNBC Markets', 'https://www.cnbc.com/id/15839069/device/rss/rss.html'),
    ],
}

_CACHE_TTL = 600  # 10분
_GROQ_MODEL = 'llama-3.3-70b-versatile'
_MAX_HEADLINES = 12  # LLM 입력 헤드라인 상한

# region 별 캐시 — {region: {'data': {...}, 'ts': float}}
_cache: Dict[str, dict] = {}
_lock = threading.Lock()


def _kst_now_str() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')


def _fetch_headlines(region: str) -> List[dict]:
    """RSS 피드 fetch + dedup. 각 항목 {title, url, source}."""
    import feedparser
    items: List[dict] = []
    seen_titles = set()
    for source_name, url in _RSS_SOURCES.get(region, []):
        try:
            feed = feedparser.parse(url)
            entries = feed.entries[:8] if feed.entries else []
            for entry in entries:
                title = (entry.get('title') or '').strip()
                link = (entry.get('link') or '').strip()
                if not title or not link:
                    continue
                # 단순 중복 제거 — 제목 앞 30자 기준
                key = title[:30]
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                items.append({'title': title, 'url': link, 'source': source_name})
        except Exception as e:
            print(f'[market_brief] RSS fetch 실패 {source_name}: {e}')
    return items[:_MAX_HEADLINES]


def _build_prompt(region: str, headlines: List[dict], indicators: dict) -> str:
    """Groq 에 전달할 user 메시지."""
    idx_name = '코스피' if region == 'kr' else 'S&P500'
    lines = [f'지역: {"한국" if region == "kr" else "미국"} 시장 ({idx_name} 기준)']
    if indicators.get('return_pct') is not None:
        lines.append(f'{idx_name} 일일 수익률: {indicators["return_pct"]:+.2f}%')
    if indicators.get('vix') is not None:
        lines.append(f'VIX: {indicators["vix"]:.1f}')
    if indicators.get('rsi') is not None:
        lines.append(f'RSI(14): {indicators["rsi"]:.1f}')
    lines.append('')
    lines.append('오늘 헤드라인:')
    for i, h in enumerate(headlines, 1):
        lines.append(f'{i}. {h["title"]}')
    return '\n'.join(lines)


_SYSTEM_PROMPT = """너는 한국어 금융 시황 요약가다. 주어진 지표와 헤드라인에서 오늘 시장 흐름을 한 줄로 요약한다.

규칙:
- 출력은 JSON 한 개. 다른 텍스트 절대 금지.
- 형식: {"text": "한 줄 시황 (40~70자)", "keywords": ["키워드1", "키워드2", "키워드3"]}
- text: 사실 묘사만. "상승/하락/혼조/관망/우려" 같은 표현 OK. 매수/매도/추천/사라/팔아라/목표가/투자 판단 절대 금지.
- text: 명사형 또는 ~이다 종결. 격식 존대 X. 이모지 X.
- keywords: 헤드라인에서 추출한 핵심 키워드 2~3개. 짧게 (3~8자).
- 출처 인용/번호 표기 X (text 안에 [1] 같은 거 넣지 마라).
- 정치/사회 이슈만 있는 헤드라인은 무시. 금융·기업·경제 관련만 사용.
"""


def _call_groq(prompt: str) -> Optional[dict]:
    """Groq llama-3.3-70b 호출. JSON 파싱 결과 반환. 실패 시 None."""
    if os.getenv('DISABLE_GROQ', '').lower() in ('true', '1', 'yes'):
        return None
    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        print('[market_brief] GROQ_API_KEY 없음')
        return None
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[
                {'role': 'system', 'content': _SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.3,
            max_tokens=400,
            response_format={'type': 'json_object'},
        )
        raw = completion.choices[0].message.content or ''
        raw = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()
        data = json.loads(raw)
        if not isinstance(data, dict) or 'text' not in data:
            return None
        text = str(data.get('text') or '').strip()
        kws = data.get('keywords') or []
        if not isinstance(kws, list):
            kws = []
        kws = [str(k).strip() for k in kws if str(k).strip()][:3]
        return {'text': text, 'keywords': kws}
    except Exception as e:
        print(f'[market_brief] Groq 호출 실패: {e}')
        return None


def _fetch_indicators(region: str) -> dict:
    """간단한 지표 (수익률·VIX·RSI) — 기존 DB/Yahoo 활용. 실패 시 빈 dict."""
    out: dict = {}
    try:
        from database.repositories import fetch_macro_latest2
        rows = fetch_macro_latest2(region=region) or []
        if rows:
            row = rows[0]
            ret = row.get('sp500_return')
            if ret is not None:
                rv = float(ret)
                if region == 'us':
                    rv *= 100
                out['return_pct'] = rv
            rsi = row.get('sp500_rsi')
            if rsi is not None:
                out['rsi'] = float(rsi)
            vix = row.get('vix')
            if vix is not None:
                out['vix'] = float(vix)
    except Exception as e:
        print(f'[market_brief] indicator fetch 실패: {e}')
    return out


def get_market_brief(region: str) -> dict:
    """region 별 시황 브리핑 반환. 캐시 hit 시 즉시, miss 시 RSS+LLM 생성.

    반환 구조:
      {
        'text': str,
        'keywords': [str, ...],
        'sources': [{'title', 'url', 'source'}, ...],
        'updated_at': 'YYYY-MM-DD HH:MM',
        'region': 'us'|'kr',
        'cached': bool,
      }
    """
    region = region if region in ('us', 'kr') else 'us'
    now = time.time()
    with _lock:
        entry = _cache.get(region)
        if entry and (now - entry['ts']) < _CACHE_TTL:
            return {**entry['data'], 'cached': True}

    headlines = _fetch_headlines(region)
    indicators = _fetch_indicators(region)
    summary: Optional[dict] = None
    if headlines:
        prompt = _build_prompt(region, headlines, indicators)
        summary = _call_groq(prompt)

    if not summary:
        # 폴백 — 첫 헤드라인 + 지표 한 줄
        if headlines:
            fallback_text = headlines[0]['title']
        elif indicators.get('return_pct') is not None:
            idx = '코스피' if region == 'kr' else 'S&P500'
            fallback_text = f'{idx} 일일 수익률 {indicators["return_pct"]:+.2f}%'
        else:
            fallback_text = '시황 데이터 수집 중'
        summary = {'text': fallback_text, 'keywords': []}

    data = {
        'text': summary['text'],
        'keywords': summary['keywords'],
        'sources': headlines,
        'updated_at': _kst_now_str(),
        'region': region,
    }
    with _lock:
        _cache[region] = {'data': data, 'ts': now}
    return {**data, 'cached': False}
