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

# 언론사 공식 RSS — 최신순 (안정 소스)
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

# Google News RSS — 화제성(관련도·최신성 자동 랭킹) 소스. 최근 1일 검색.
# 쿼리에 지수 + 대형 종목/섹터 키워드 → 개별 종목 화제도 끌어옴
_GNEWS_SOURCES = {
    'kr': 'https://news.google.com/rss/search?q=(%EC%BD%94%EC%8A%A4%ED%94%BC%20OR%20%EC%A6%9D%EC%8B%9C%20OR%20%EC%BD%94%EC%8A%A4%EB%8B%A5%20OR%20%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90%20OR%20%EB%B0%98%EB%8F%84%EC%B2%B4)%20when:1d&hl=ko&gl=KR&ceid=KR:ko',
    'us': 'https://news.google.com/rss/search?q=(stock%20market%20OR%20S%26P%20500%20OR%20nasdaq%20OR%20nvidia%20OR%20fed)%20when:1d&hl=en-US&gl=US&ceid=US:en',
}

_CACHE_TTL = 3600  # 1시간
_GROQ_MODEL = 'llama-3.3-70b-versatile'
_MAX_HEADLINES = 14  # LLM 입력 헤드라인 상한 (화제성 + 최신 병합)
_GNEWS_TAKE = 8      # Google News 에서 가져올 상위 건수 (화제성 우선)

# region 별 캐시 — {region: {'data': {...}, 'ts': float}}
_cache: Dict[str, dict] = {}
_lock = threading.Lock()


def _kst_now_str() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')


def _clean_gnews_title(title: str) -> tuple:
    """Google News 제목 'A - 매체명' → (제목, 매체명) 분리."""
    if ' - ' in title:
        head, _, src = title.rpartition(' - ')
        if head and src and len(src) <= 30:
            return head.strip(), src.strip()
    return title, None


def _parse_feed(url: str) -> List[dict]:
    """RSS/Atom 피드 → [{'title','link'}]. feedparser 있으면 사용, 없으면 stdlib 폴백.

    Railway 등에서 feedparser 미설치여도 동작하도록 httpx+xml.etree 폴백 보유.
    """
    # 1) feedparser 우선 (설치돼 있으면)
    try:
        import feedparser
        feed = feedparser.parse(url)
        out = [{'title': (e.get('title') or '').strip(),
                'link': (e.get('link') or '').strip()}
               for e in (feed.entries or [])]
        if out:
            return out
    except Exception as e:
        print(f'[market_brief] feedparser 미사용/실패 → stdlib 폴백: {e}')

    # 2) stdlib 폴백 — httpx + xml.etree
    try:
        import httpx
        import xml.etree.ElementTree as ET
        resp = httpx.get(url, timeout=8.0, follow_redirects=True,
                         headers={'User-Agent': 'Mozilla/5.0 (compatible; PassiveBot/1.0)'})
        root = ET.fromstring(resp.content)
        out = []
        for node in root.iter():
            tag = node.tag.split('}')[-1]
            if tag not in ('item', 'entry'):
                continue
            title, link = '', ''
            for ch in node:
                ctag = ch.tag.split('}')[-1]
                if ctag == 'title':
                    title = (ch.text or '').strip()
                elif ctag == 'link':
                    link = (ch.text or '').strip() or ch.get('href', '')
            out.append({'title': title, 'link': link})
        return out
    except Exception as e:
        print(f'[market_brief] stdlib RSS 파싱 실패 {url}: {e}')
        return []


def _fetch_headlines(region: str) -> List[dict]:
    """화제성(Google News) + 최신(언론사 RSS) 병합. dedup. 각 항목 {title, url, source}.

    Google News 를 앞에 둬서 화제성 높은 헤드라인이 LLM 입력 상위에 오게 한다.
    """
    items: List[dict] = []
    seen_titles = set()

    def _add(title, link, source):
        title = (title or '').strip()
        link = (link or '').strip()
        if not title or not link:
            return
        key = title[:30]
        if key in seen_titles:
            return
        seen_titles.add(key)
        items.append({'title': title, 'url': link, 'source': source})

    # 1) Google News — 화제성 우선
    gurl = _GNEWS_SOURCES.get(region)
    if gurl:
        for entry in _parse_feed(gurl)[:_GNEWS_TAKE]:
            clean_title, src = _clean_gnews_title(entry['title'])
            _add(clean_title, entry['link'], src or 'Google뉴스')

    # 2) 언론사 공식 RSS — 최신순 보강
    for source_name, url in _RSS_SOURCES.get(region, []):
        for entry in _parse_feed(url)[:6]:
            _add(entry['title'], entry['link'], source_name)

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
    if indicators.get('live_pct') is not None:
        lv = indicators['live_pct']
        direction = '상승' if lv > 0.05 else ('하락' if lv < -0.05 else '보합')
        lines.append(f'★ 현재 실시간 등락(SPY, 프리장·장중·시간외 현재가 vs 직전 정규장 종가): {lv:+.2f}% ({direction}) — 지금 시장 방향')
    lines.append('')
    lines.append('오늘 헤드라인:')
    for i, h in enumerate(headlines, 1):
        lines.append(f'{i}. {h["title"]}')
    return '\n'.join(lines)


_SYSTEM_PROMPT = """너는 한국어 금융 시황 브리핑 작성가다. 네이버 금융 'AI 브리핑' 스타일로 오늘 시장을 요약한다.

규칙:
- 출력은 JSON 한 개만. 다른 텍스트 절대 금지.
- 형식:
  {
    "headline": "한 줄 헤드라인 (25~45자, 핵심 한 문장)",
    "summary": ["요약 문장1", "요약 문장2", "요약 문장3"],
    "sections": [
      {"emoji": "📉", "title": "소제목 한 줄", "body": "2~3문장 설명"},
      {"emoji": "💸", "title": "소제목 한 줄", "body": "2~3문장 설명"}
    ]
  }
- summary: 정확히 3개. 각 1문장. 오늘 시장의 핵심 흐름.
- sections: 2~3개. 각 emoji(시황 맞는 이모지 1개) + title(소제목) + body(2~3문장 본문). **서로 다른 촉발 이슈를 다뤄라** — 같은 내용 반복 금지. 메인 흐름(예: 외국인 매도) 외에 헤드라인에 나온 개별 종목·기업 이슈(예: 삼성전자 노사 갈등, 특정 섹터 이슈)가 있으면 별도 섹션으로 반드시 다뤄라.
- 프리장/시간외 등락 정보가 주어지면 그 흐름도 반영해라 (예: "정규장은 하락했지만 프리장에서는 상승하고 있어요"). 단 프리장은 변동이 크다는 점을 감안해 단정적 전망은 피해라.
- 어투: 친근한 존대체 "~했어요 / ~됐어요 / ~보였어요" 로 통일. (네이버 AI 브리핑 톤)
- 사실·데이터 묘사만. 매수/매도/추천/사라/팔아라/목표가/투자 판단·전망 절대 금지.
- headline 은 이모지 없이. body 안에 출처 번호([1] 등) 넣지 마라.
- 정치/연예/사회 가십 헤드라인은 무시. 금융·기업·경제·매크로만 사용.
- 헤드라인이 영어면 한국어로 번역해 반영. 종목명은 한국어 통용명 우선.
- 한자(漢字) 절대 사용 금지. 전부 한글로만 작성. (예: "테크株" X → "테크주" O, "美" X → "미국" O, "中" X → "중국" O)
- 인과 처리: 헤드라인에 등락의 원인·악재·호재가 *명시돼 있으면* 그대로 반영해라 (예: 헤드라인에 "삼성전자 노사 갈등 부담", "외국인 매도" 가 있으면 헤드라인/본문에 그 요인을 구체적으로 담아라). 단, 헤드라인 어디에도 없는 인과는 지어내지 마라. (없는데 "엔비디아 실적 때문에 상승" 처럼 창작 금지.)
- headline 은 *가장 구체적인 시장 촉발 이슈* 를 담아라. "코스피 매도에 하락" 같은 막연한 표현 금지. 헤드라인들에서 반복·강조되는 실제 사건(예: "외국인 3조 매도")을 핵심으로 하되, **그와 함께 두드러진 개별 종목·이벤트(예: 삼성전자 노사 갈등)가 있으면 헤드라인에 같이 엮어라**. (예: "외국인 매도·삼성 노사 갈등에 코스피 하락") 거시 요인 하나만 단독으로 쓰지 말고 구체적 사건을 곁들여 정보량을 높여라.
- 지수 방향(상승/하락/혼조): **'현재 실시간 등락'(★ 표시)이 있으면 그 부호를 1순위로** 따른다. 즉 지금 시장이 오르고 있으면 헤드라인도 상승으로 써라. 실시간 등락이 없을 때만 '일일 수익률'(직전 마감) 부호를 쓴다.
- 실시간 등락과 직전 마감 방향이 다르면 둘 다 표기: "간밤 정규장은 하락 마감했지만 현재 프리장에서는 상승하고 있어요" 처럼 시점을 구분해 서술. 직전 마감 하락만 보고 "하락"이라 단정하지 마라.
- 종목·기업·인물 명칭은 한국에서 통용되는 정확한 표기 사용. 음역 오류 금지. 예: Nvidia=엔비디아, Tesla=테슬라, Apple=애플, Microsoft=마이크로소프트, Alphabet/Google=알파벳/구글, Amazon=아마존, Meta=메타, Broadcom=브로드컴, TSMC=TSMC, Fed=연준.
"""


# 흔한 금융 한자 약어 → 한글 치환 (LLM 이 가끔 흘리는 것 후처리 보정)
_HANJA_MAP = {
    '美': '미국', '中': '중국', '日': '일본', '韓': '한국', '英': '영국',
    '獨': '독일', '佛': '프랑스', '株': '주', '增': '증가', '減': '감소',
    '前': '전', '後': '후', '上': '상', '下': '하', '高': '고', '低': '저',
    '大': '대', '小': '소', '新': '신', '舊': '구', '亞': '아시아',
    '銀': '은행', '證': '증권', '財': '재정', '油': '석유', '金': '금',
}
_HANJA_RE = re.compile(r'[一-鿿]')


def _strip_hanja(s: str) -> str:
    """문자열 내 한자를 한글로 치환. 매핑에 없는 한자는 제거."""
    if not s or not _HANJA_RE.search(s):
        return s
    out = []
    for ch in s:
        if '一' <= ch <= '鿿':
            out.append(_HANJA_MAP.get(ch, ''))  # 매핑 없으면 삭제
        else:
            out.append(ch)
    return re.sub(r'\s{2,}', ' ', ''.join(out)).strip()


# LLM 이 가끔 틀리는 종목·기업 음역 보정
_NAME_FIX = {
    '나이드비아': '엔비디아', '엔비디': '엔비디아', '느비디아': '엔비디아',
    '엔비디아아': '엔비디아', '테슬라사': '테슬라', '애플사': '애플',
}


def _fix_names(s: str) -> str:
    if not s:
        return s
    for wrong, right in _NAME_FIX.items():
        if wrong in s:
            s = s.replace(wrong, right)
    return s


def _clean(s: str) -> str:
    """한자 제거 + 음역 보정 일괄 적용."""
    return _fix_names(_strip_hanja(s))


def _call_groq(prompt: str) -> Optional[dict]:
    """Groq llama-3.3-70b 호출. 구조화 JSON 파싱 결과 반환. 실패 시 None."""
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
            temperature=0.4,
            max_tokens=1200,
            response_format={'type': 'json_object'},
        )
        raw = completion.choices[0].message.content or ''
        raw = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()
        data = json.loads(raw)
        if not isinstance(data, dict) or 'headline' not in data:
            return None
        headline = _clean(str(data.get('headline') or '').strip())
        if not headline:
            return None
        summary = data.get('summary') or []
        if not isinstance(summary, list):
            summary = []
        summary = [_clean(str(s).strip()) for s in summary if str(s).strip()][:3]
        sections_raw = data.get('sections') or []
        sections = []
        if isinstance(sections_raw, list):
            for sec in sections_raw[:3]:
                if not isinstance(sec, dict):
                    continue
                t = _clean(str(sec.get('title') or '').strip())
                b = _clean(str(sec.get('body') or '').strip())
                if not t or not b:
                    continue
                sections.append({
                    'emoji': str(sec.get('emoji') or '•').strip()[:4],
                    'title': t,
                    'body': b,
                })
        return {'headline': headline, 'summary': summary, 'sections': sections}
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
    # US 실시간 등락 (프리장·장중·시간외 현재가 vs 직전 정규장 종가) — 방향 판단 1순위
    if region == 'us':
        live = _fetch_live_us()
        if live is not None:
            out['live_pct'] = live
            out['premarket_pct'] = live  # 프론트 태그 호환 (기존 키 유지)
    return out


def _last_close_value(series) -> Optional[float]:
    """yfinance Series/DataFrame 컬럼에서 마지막 유효값을 안전하게 float 추출."""
    try:
        vals = series.dropna().values.ravel()
        if len(vals) == 0:
            return None
        return float(vals[-1])
    except Exception:
        return None


def _fetch_live_us() -> Optional[float]:
    """SPY 현재가(프리장·장중·시간외 포함) vs 직전 정규장 종가 등락%. 실패 시 None.

    fast_info.previous_close 를 기준선으로, prepost 1분봉 최신 체결가를 현재가로 사용.
    """
    try:
        import yfinance as yf
        t = yf.Ticker('SPY')
        prev_close = None
        last = None
        # 1) 기준선 = 직전 정규장 종가 (fast_info)
        try:
            fi = t.fast_info
            prev_close = float(fi.previous_close)
            last = float(fi.last_price)
        except Exception:
            pass
        # 2) 현재가 = 시간외 포함 1분봉 최신 체결가 (프리장/애프터장 반영)
        try:
            intra = yf.download('SPY', period='1d', interval='1m',
                                prepost=True, progress=False)
            if intra is not None and not intra.empty:
                v = _last_close_value(intra['Close'])
                if v is not None:
                    last = v
        except Exception:
            pass
        # 3) 기준선 폴백 — fast_info 실패 시 일봉에서
        if prev_close is None:
            try:
                daily = yf.download('SPY', period='7d', prepost=False, progress=False)
                closes = daily['Close'].dropna().values.ravel()
                # intraday 최신이 오늘 종가와 사실상 같으면(장 마감) 그 전 종가를 기준
                if len(closes) >= 2 and last is not None and abs(last / float(closes[-1]) - 1) < 0.0005:
                    prev_close = float(closes[-2])
                elif len(closes) >= 1:
                    prev_close = float(closes[-1])
            except Exception:
                pass
        if last is None or prev_close is None or prev_close <= 0:
            return None
        return round((last / prev_close - 1.0) * 100.0, 2)
    except Exception as e:
        print(f'[market_brief] 실시간 등락 fetch 실패: {e}')
        return None


def get_market_brief(region: str) -> dict:
    """region 별 시황 브리핑 반환. 캐시 hit 시 즉시, miss 시 RSS+LLM 생성.

    반환 구조 (네이버 AI 브리핑 스타일):
      {
        'headline': str,                       # 진입 바 + 모달 상단 한 줄
        'summary': [str, str, str],            # 요약 박스 3-bullet
        'sections': [{'emoji','title','body'}],# 상세 섹션 2~3개
        'sources': [{'title','url','source'}], # 출처 헤드라인
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
    brief: Optional[dict] = None
    if headlines:
        prompt = _build_prompt(region, headlines, indicators)
        brief = _call_groq(prompt)

    if not brief:
        # 폴백 — 지표/첫 헤드라인 기반 최소 구조
        idx = '코스피' if region == 'kr' else 'S&P500'
        if indicators.get('live_pct') is not None:
            lv = indicators['live_pct']
            d = '상승' if lv > 0.05 else ('하락' if lv < -0.05 else '보합')
            fb_head = f'{idx} 현재 {lv:+.2f}% {d} (프리장·장중 기준)'
        elif indicators.get('return_pct') is not None:
            fb_head = f'{idx} 일일 수익률 {indicators["return_pct"]:+.2f}%'
        elif headlines:
            fb_head = headlines[0]['title']
        else:
            fb_head = '시황 데이터 수집 중'
        brief = {
            'headline': fb_head,
            'summary': [h['title'] for h in headlines[:3]],
            'sections': [],
        }

    data = {
        'headline': brief['headline'],
        'summary': brief.get('summary') or [],
        'sections': brief.get('sections') or [],
        'sources': headlines,
        'premarket_pct': indicators.get('premarket_pct'),  # US 프리장 등락% (없으면 None)
        'updated_at': _kst_now_str(),
        'region': region,
    }
    with _lock:
        _cache[region] = {'data': data, 'ts': now}
    return {**data, 'cached': False}
