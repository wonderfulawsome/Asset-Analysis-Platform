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
        ('매경 증권', 'https://www.mk.co.kr/rss/50200011/'),
        ('한경 증권', 'https://rss.hankyung.com/feed/marketstock.xml'),
        ('이데일리 증권', 'https://rss.edaily.co.kr/stock_news.xml'),
        ('연합뉴스 경제', 'https://www.yna.co.kr/rss/economy.xml'),
        ('서울경제 증권', 'https://www.sedaily.com/RSS/S11.xml'),
        ('파이낸셜뉴스 증권', 'https://www.fnnews.com/rss/r20/fn_realnews_stock.xml'),
        ('머니투데이 증권', 'https://rss.mt.co.kr/mt_stock.xml'),
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


_TAG_RE = re.compile(r'<[^>]+>')


def _clean_summary(raw: str, limit: int = 120) -> str:
    """RSS description/summary 에서 HTML 태그 제거 + 길이 컷."""
    if not raw:
        return ''
    txt = _TAG_RE.sub('', raw)
    txt = re.sub(r'&[a-z]+;', ' ', txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    if len(txt) > limit:
        txt = txt[:limit].rstrip() + '…'
    return txt


def _fmt_time(published) -> str:
    """RSS pubDate → 'HH:MM' (KST). 파싱 실패 시 ''."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(published)
        if dt is None:
            return ''
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        kst = dt.astimezone(timezone(timedelta(hours=9)))
        return kst.strftime('%H:%M')
    except Exception:
        return ''


_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::url)?["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE)
_OG_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::url)?["\']',
    re.IGNORECASE)


def _fetch_og_image(url: str) -> str:
    """기사 URL 의 og:image / twitter:image 추출. 실패 시 ''."""
    try:
        import httpx
        r = httpx.get(url, timeout=5.0, follow_redirects=True,
                      headers={'User-Agent': 'Mozilla/5.0 (compatible; PassiveBot/1.0)'})
        html = r.text[:200000]  # head 영역이면 충분
        m = _OG_RE.search(html) or _OG_RE2.search(html)
        if m:
            img = m.group(1).strip()
            if img.startswith('//'):
                img = 'https:' + img
            if img.startswith('http'):
                return img
    except Exception:
        pass
    return ''


def _enrich_images(sources: List[dict]) -> List[dict]:
    """이미지 없는 기사들에 og:image 병렬 보강. 모든 카드에 썸네일 노출 목적."""
    todo = [i for i, s in enumerate(sources) if not s.get('image') and s.get('url')]
    if not todo:
        return sources
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(lambda i: (i, _fetch_og_image(sources[i]['url'])), todo))
        for i, img in results:
            if img:
                sources[i]['image'] = img
    except Exception as e:
        print(f'[market_brief] og:image 보강 실패: {e}')
    return sources


def _parse_feed(url: str) -> List[dict]:
    """RSS/Atom 피드 → [{'title','link','summary','image','time'}].

    httpx(브라우저 UA)로 바이트를 받아 feedparser 에 넘긴다 (UA 차단·malformed XML 대응).
    실패 시 feedparser URL 직접 / stdlib 순으로 폴백.
    """
    content = None
    try:
        import httpx
        r = httpx.get(url, timeout=8.0, follow_redirects=True,
                      headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                             'AppleWebKit/537.36 (KHTML, like Gecko) '
                                             'Chrome/124.0 Safari/537.36'})
        if r.status_code == 200:
            content = r.content
    except Exception:
        content = None

    # 1) feedparser — 받은 바이트 우선, 없으면 URL 직접
    try:
        import feedparser
        feed = feedparser.parse(content if content is not None else url)
        out = []
        for e in (feed.entries or []):
            img = ''
            # media:thumbnail / media:content / enclosure 순으로 이미지 탐색
            if e.get('media_thumbnail'):
                img = (e['media_thumbnail'][0] or {}).get('url', '')
            if not img and e.get('media_content'):
                for mc in e['media_content']:
                    if str(mc.get('medium') or '').startswith('image') or 'image' in str(mc.get('type') or ''):
                        img = mc.get('url', ''); break
                if not img:
                    img = (e['media_content'][0] or {}).get('url', '')
            if not img:
                for lk in (e.get('links') or []):
                    if lk.get('rel') == 'enclosure' and 'image' in str(lk.get('type') or ''):
                        img = lk.get('href', ''); break
            out.append({
                'title': (e.get('title') or '').strip(),
                'link': (e.get('link') or '').strip(),
                'summary': _clean_summary(e.get('summary') or e.get('description') or ''),
                'image': img or '',
                'time': _fmt_time(e.get('published') or e.get('updated') or ''),
            })
        if out:
            return out
    except Exception as e:
        print(f'[market_brief] feedparser 미사용/실패 → stdlib 폴백: {e}')

    # 2) stdlib 폴백 — 이미 받은 content (없으면 재요청) + xml.etree
    try:
        import xml.etree.ElementTree as ET
        raw = content
        if raw is None:
            import httpx
            resp = httpx.get(url, timeout=8.0, follow_redirects=True,
                             headers={'User-Agent': 'Mozilla/5.0 (compatible; PassiveBot/1.0)'})
            raw = resp.content
        root = ET.fromstring(raw)
        out = []
        for node in root.iter():
            tag = node.tag.split('}')[-1]
            if tag not in ('item', 'entry'):
                continue
            title, link, summary, image, pub = '', '', '', '', ''
            for ch in node:
                ctag = ch.tag.split('}')[-1]
                if ctag == 'title':
                    title = (ch.text or '').strip()
                elif ctag == 'link':
                    link = (ch.text or '').strip() or ch.get('href', '')
                elif ctag in ('description', 'summary', 'encoded'):
                    if not summary:
                        summary = _clean_summary(ch.text or '')
                elif ctag in ('thumbnail', 'content') and ch.get('url'):
                    if not image and 'image' in (ch.get('type', '') + ch.get('medium', '') + 'image'):
                        image = ch.get('url', '')
                elif ctag == 'enclosure' and 'image' in str(ch.get('type', '')):
                    image = ch.get('url', '')
                elif ctag in ('pubDate', 'published', 'date'):
                    pub = (ch.text or '').strip()
            out.append({'title': title, 'link': link, 'summary': summary,
                        'image': image, 'time': _fmt_time(pub)})
        return out
    except Exception as e:
        print(f'[market_brief] stdlib RSS 파싱 실패 {url}: {e}')
        return []


def _fetch_headlines(region: str) -> dict:
    """뉴스 2갈래 반환.

    - 'brief': 브리핑(LLM) 입력 풀 = Google News(화제성) + 언론사 RSS 병합 [:_MAX_HEADLINES].
    - 'display': 화면 카드용 = 언론사 RSS 만 (실제 기사 URL·이미지 보유, og 보강 가능).
    각 항목 {title, url, source, summary, image, time}.
    """
    def _mk(title, link, source, entry):
        title = (title or '').strip()
        link = (link or '').strip()
        if not title or not link:
            return None
        return {'title': title, 'url': link, 'source': source,
                'summary': entry.get('summary') or '', 'image': entry.get('image') or '',
                'time': entry.get('time') or ''}

    gnews_items: List[dict] = []
    gurl = _GNEWS_SOURCES.get(region)
    if gurl:
        for entry in _parse_feed(gurl)[:_GNEWS_TAKE]:
            clean_title, src = _clean_gnews_title(entry['title'])
            it = _mk(clean_title, entry['link'], src or 'Google뉴스', entry)
            if it:
                gnews_items.append(it)

    pub_items: List[dict] = []
    for source_name, url in _RSS_SOURCES.get(region, []):
        for entry in _parse_feed(url)[:6]:
            it = _mk(entry['title'], entry['link'], source_name, entry)
            if it:
                pub_items.append(it)

    # 제목 앞 30자 기준 dedup (병합 풀)
    seen = set()
    brief_pool = []
    for it in gnews_items + pub_items:
        k = it['title'][:30]
        if k in seen:
            continue
        seen.add(k)
        brief_pool.append(it)

    # display = 언론사 RSS 만 dedup
    seen_d = set()
    display = []
    for it in pub_items:
        k = it['title'][:30]
        if k in seen_d:
            continue
        seen_d.add(k)
        display.append(it)

    return {'brief': brief_pool[:_MAX_HEADLINES], 'display': display[:20]}


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
        phase = indicators.get('live_phase', 'regular')
        phase_kr = {'pre': '프리장(개장 전)', 'regular': '정규장 장중',
                    'after': '시간외(장 마감 후)', 'closed': '장 마감 상태'}.get(phase, '장중')
        lines.append(f'★ 현재 시장 단계: {phase_kr}. 실시간 등락(SPY vs 직전 정규장 종가): {lv:+.2f}% ({direction}) — 지금 시장 방향. 방향 서술 시 이 단계 용어를 정확히 써라(프리장이 아니면 "프리장"이라 쓰지 마라).')
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


_EN_RE = re.compile(r'[A-Za-z]')


def _translate_sources_ko(sources: List[dict]) -> List[dict]:
    """US 영어 뉴스 제목·요약을 한국어로 일괄 번역 (Groq). 실패/차단 시 원문 유지.

    title/summary 만 교체, url·source·image·time 보존. 1회 호출(배치).
    """
    if os.getenv('DISABLE_GROQ', '').lower() in ('true', '1', 'yes'):
        return sources
    # 영어가 섞인 항목만 번역 대상
    targets = [i for i, s in enumerate(sources)
               if _EN_RE.search(s.get('title', '') or '') or _EN_RE.search(s.get('summary', '') or '')]
    if not targets:
        return sources
    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        return sources
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        payload = [{'i': i, 't': sources[i].get('title', ''), 's': sources[i].get('summary', '')}
                   for i in targets]
        sys_prompt = (
            '너는 금융 뉴스 번역가다. 주어진 영어 제목(t)과 요약(s)을 자연스러운 한국어로 번역한다. '
            '출력은 JSON 한 개: {"items":[{"i":인덱스,"t":"한국어 제목","s":"한국어 요약"}]}. '
            '순서·인덱스 유지. 종목/기업명은 한국 통용 표기(Nvidia=엔비디아, Tesla=테슬라, Fed=연준 등). '
            '한자 절대 금지, 한글만. 의역 OK, 과장·추측 금지. 다른 텍스트 절대 출력 금지.'
        )
        user_msg = json.dumps({'items': payload}, ensure_ascii=False)
        completion = client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[{'role': 'system', 'content': sys_prompt},
                      {'role': 'user', 'content': user_msg}],
            temperature=0.2, max_tokens=2000,
            response_format={'type': 'json_object'},
        )
        raw = completion.choices[0].message.content or ''
        raw = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()
        data = json.loads(raw)
        for it in (data.get('items') or []):
            idx = it.get('i')
            if not isinstance(idx, int) or idx < 0 or idx >= len(sources):
                continue
            t = _clean(str(it.get('t') or '').strip())
            s = _clean(str(it.get('s') or '').strip())
            if t:
                sources[idx]['title'] = t
            if s:
                sources[idx]['summary'] = s
        return sources
    except Exception as e:
        print(f'[market_brief] 소스 번역 실패: {e}')
        return sources


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
            fx = row.get('usdkrw')
            if fx is not None:
                out['usdkrw'] = float(fx)
            fxc = row.get('usdkrw_change_pct')
            if fxc is not None:
                out['usdkrw_change_pct'] = float(fxc)
    except Exception as e:
        print(f'[market_brief] indicator fetch 실패: {e}')
    # US 실시간 등락 (프리장·장중·시간외 현재가 vs 직전 정규장 종가) — 방향 판단 1순위
    if region == 'us':
        live = _fetch_live_us()
        if live is not None:
            out['live_pct'] = live
            phase = _us_market_phase()
            out['live_phase'] = phase  # pre / regular / after / closed
            # 프론트 '프리장' 태그는 실제 프리장 시간대에만 노출
            if phase == 'pre':
                out['premarket_pct'] = live
    return out


def _fetch_volume_ratio(region: str) -> Optional[float]:
    """지수 거래량 / 최근 20일 평균 비율. SPY(US) / ^KS11(KR). 실패 시 None."""
    try:
        import yfinance as yf
        ticker = 'SPY' if region == 'us' else '^KS11'
        df = yf.download(ticker, period='2mo', progress=False)
        if df is None or df.empty or 'Volume' not in df:
            return None
        vol = df['Volume'].dropna().values.ravel()
        if len(vol) < 6:
            return None
        latest = float(vol[-1])
        base = vol[-21:-1] if len(vol) > 21 else vol[:-1]
        avg = float(base.mean())
        if avg <= 0:
            return None
        return round(latest / avg, 2)
    except Exception as e:
        print(f'[market_brief] 거래량 비율 fetch 실패: {e}')
        return None


def _build_meta(region: str, indicators: dict) -> dict:
    """홈 카드 메타라인 — US: 공포탐욕·RSI·거래량 / KR: 원달러·RSI·거래량."""
    meta: dict = {}
    if indicators.get('rsi') is not None:
        meta['rsi'] = round(indicators['rsi'], 1)
    vr = _fetch_volume_ratio(region)
    if vr is not None:
        meta['volume_ratio'] = vr
    if region == 'us':
        try:
            from database.repositories import fetch_fear_greed_latest
            fg = fetch_fear_greed_latest() or {}
            if fg.get('score') is not None:
                meta['fear_greed'] = {'score': round(float(fg['score'])),
                                      'rating': fg.get('rating') or ''}
        except Exception as e:
            print(f'[market_brief] fear_greed fetch 실패: {e}')
    else:  # kr
        if indicators.get('usdkrw') is not None:
            meta['usdkrw'] = round(indicators['usdkrw'], 1)
            if indicators.get('usdkrw_change_pct') is not None:
                meta['usdkrw_change_pct'] = round(indicators['usdkrw_change_pct'], 2)
    return meta


def _us_market_phase() -> str:
    """현재 미국 동부시각 기준 시장 단계. pre / regular / after / closed.

    pre: 04:00~09:30, regular: 09:30~16:00, after: 16:00~20:00 (ET, 평일).
    공휴일은 미반영 (근사).
    """
    try:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo('America/New_York'))
        except Exception:
            # 폴백 — UTC 에서 EDT(-4) 근사
            now = datetime.now(timezone.utc) - timedelta(hours=4)
        if now.weekday() >= 5:  # 토(5)/일(6)
            return 'closed'
        mins = now.hour * 60 + now.minute
        if 4 * 60 <= mins < 9 * 60 + 30:
            return 'pre'
        if 9 * 60 + 30 <= mins < 16 * 60:
            return 'regular'
        if 16 * 60 <= mins < 20 * 60:
            return 'after'
        return 'closed'
    except Exception:
        return 'closed'


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


_STOP = {'있어요', '했어요', '됐어요', '오늘', '시장', '주식', '관련', '대비', '이번',
         '기록', '전망', '발표', '대한', '있는', '이날', '대해', '통해', '위해', '가운데'}
_TOKEN_RE = re.compile(r'[가-힣A-Za-z0-9]{2,}')


def _keywords_from_brief(brief: dict) -> set:
    """브리핑 headline+summary+섹션 제목에서 핵심 토큰 집합 추출."""
    text = ' '.join([
        brief.get('headline', ''),
        ' '.join(brief.get('summary') or []),
        ' '.join(s.get('title', '') for s in (brief.get('sections') or [])),
    ])
    toks = set()
    for t in _TOKEN_RE.findall(text):
        if t in _STOP or len(t) < 2:
            continue
        toks.add(t.lower())
    return toks


def _rank_display_by_brief(display: List[dict], brief: dict) -> List[dict]:
    """브리핑 키워드와 겹치는 기사를 앞으로. 동점은 기존(최신) 순서 유지."""
    kws = _keywords_from_brief(brief)
    if not kws or not display:
        return display

    def score(item):
        text = (item.get('title', '') + ' ' + item.get('summary', '')).lower()
        toks = set(_TOKEN_RE.findall(text))
        return len(toks & kws)

    scored = [(score(it), idx, it) for idx, it in enumerate(display)]
    # 점수 내림차순, 동점은 원래 인덱스 오름차순(안정)
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [it for _, _, it in scored]


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

    news = _fetch_headlines(region)
    brief_pool = news['brief']       # 브리핑(LLM) 입력 — Google News 포함
    display = news['display']        # 화면 카드 — 언론사 RSS 만 (이미지·실URL)
    indicators = _fetch_indicators(region)
    brief: Optional[dict] = None
    if brief_pool:
        prompt = _build_prompt(region, brief_pool, indicators)
        brief = _call_groq(prompt)

    if not brief:
        # 폴백 — 지표/첫 헤드라인 기반 최소 구조
        idx = '코스피' if region == 'kr' else 'S&P500'
        if indicators.get('live_pct') is not None:
            lv = indicators['live_pct']
            d = '상승' if lv > 0.05 else ('하락' if lv < -0.05 else '보합')
            ph = {'pre': '프리장', 'regular': '장중', 'after': '시간외',
                  'closed': '최근'}.get(indicators.get('live_phase'), '현재')
            fb_head = f'{idx} {ph} {lv:+.2f}% {d}'
        elif indicators.get('return_pct') is not None:
            fb_head = f'{idx} 일일 수익률 {indicators["return_pct"]:+.2f}%'
        elif brief_pool:
            fb_head = brief_pool[0]['title']
        else:
            fb_head = '시황 데이터 수집 중'
        brief = {
            'headline': fb_head,
            'summary': [h['title'] for h in brief_pool[:3]],
            'sections': [],
        }

    # 화면 카드(display): US 영어면 한국어 번역 + 이미지 og 보강
    if region == 'us':
        display = _translate_sources_ko(display)
    display = _enrich_images(display)
    # 브리핑 핵심 키워드와 일치하는 '주요 뉴스'를 상단으로 정렬
    display = _rank_display_by_brief(display, brief)

    data = {
        'headline': brief['headline'],
        'summary': brief.get('summary') or [],
        'sections': brief.get('sections') or [],
        'sources': display,
        'premarket_pct': indicators.get('premarket_pct'),  # US 프리장 등락% (없으면 None)
        'meta': _build_meta(region, indicators),            # US: 공포탐욕·RSI·거래량 / KR: 원달러·RSI·거래량
        'updated_at': _kst_now_str(),
        'region': region,
    }
    with _lock:
        _cache[region] = {'data': data, 'ts': now}
    return {**data, 'cached': False}
