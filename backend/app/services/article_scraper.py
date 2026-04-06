"""On-demand article content scraper.

Fetches the full text of a news article from its URL.
Uses BeautifulSoup to extract the main content from common
Korean news site HTML structures.  Falls back to Gemini AI
extraction when CSS selectors fail.
"""

import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
}

# Common content selectors for Korean news sites (ordered by priority)
CONTENT_SELECTORS = [
    # Naver News
    "#dic_area",                   # Naver News (current)
    "#articleBodyContents",        # Naver News (legacy)
    "#newsEndContents",            # Naver News (alternative)
    "#newsct_article",             # Naver News (sports/entertain)
    # Major Korean economic papers
    "#newsViewArea",               # 이투데이
    ".news_body_area",             # 이투데이 (alternative)
    "#article-view-content-div",   # 뉴스1
    ".article_body",               # 한국경제, 매일경제
    "#article_body",
    ".article-body",
    "#articleBody",
    ".article_txt",                # 이데일리
    ".news_cnt_detail_wrap",       # 파이낸셜뉴스
    "#news_body_area",
    "#article-body",               # 조선일보
    ".article__content",           # 중앙일보
    ".news_article",               # 동아일보
    "#article_content",
    "#snsAti498",                  # 서울경제
    ".view_con",                   # 아시아경제
    ".article-view-body",
    "#articeBody",
    "#textBody",
    ".post-content",
    ".entry-content",
]

# CSS selectors to remove before extraction
REMOVE_SELECTORS = [
    # Structural noise
    "script", "style", "iframe", "nav", "header", "footer",
    "aside", "form", "button", "input", "select", "textarea",
    # Media
    "figure", "figcaption", "img", "video", "audio", "source",
    # Ads & promotions
    ".ad", ".ads", ".advertisement", ".ad_wrap", ".adsbygoogle",
    "[class*='banner']", "[id*='banner']",
    "[class*='dable']", "[id*='dable']",
    "[class*='ad_']", "[id*='ad_']",
    "[class*='_ad']", "[id*='_ad']",
    "[class*='AdWrap']", "[class*='adwrap']",
    "[data-role='ad']", "[data-type='ad']",
    "[class*='sponsor']", "[id*='sponsor']",
    # Social / sharing
    ".social-share", ".sns_share", ".article_sns", ".share_btn",
    "[class*='social']",
    # Related articles & recommendations
    ".related-article", ".related_article", ".relation_news",
    ".article_relation", ".article_issue", ".news_relation",
    "[class*='related']", "[class*='recommend']",
    # Reporter / byline / copyright
    ".reporter_area", ".byline", ".copyright", ".article_footer",
    ".journalist", ".writer_info", ".report_area",
    "[class*='reporter']", "[class*='byline']",
    # Comments
    "[class*='comment']", "[id*='comment']",
    "[class*='reply']", "[id*='reply']",
    # Subscription / popup
    "[class*='subscribe']", "[class*='popup']", "[class*='layer']",
    "[class*='newsletter']",
    # Navigation / breadcrumb
    ".breadcrumb", "[class*='breadcrumb']",
    ".tab-nav", "[class*='tab_']", "[class*='tabnav']",
    # Photo captions (keep photos out)
    ".photo_area", ".img_area", ".image_area",
    "[class*='photo']", "[class*='caption']",
    # Stock info cards
    "[class*='stock_']", "[class*='namecard']",
    # Sidebar
    "[class*='sidebar']", "[class*='aside']", "[class*='right_']",
    # Most viewed / popular
    "[class*='popular']", "[class*='most_']", "[class*='ranking']",
    # Crypto / market widgets
    "[class*='crypto']", "[class*='coin']", "[class*='market_info']",
    # Newdaily / other site-specific noise
    "[class*='news_zone']", "[class*='quickguide']", "[class*='interworks']",
    "[class*='font_size']", "[class*='fontsize']", "[class*='font-size']",
    "[class*='voice']", "[class*='tts']",
    "[class*='article_tool']", "[class*='article-tool']",
    "[class*='article_util']", "[class*='article-util']",
]


_NOISE_PATTERNS = [
    # Reaction buttons
    r"좋아요\s*\d*",
    r"화나요\s*\d*",
    r"슬퍼요\s*\d*",
    r"후속기사\s*원해요\s*\d*",
    r"추가취재\s*원해요\s*\d*",
    # Reporter / subscription
    r".*기자의 주요 뉴스.*",
    r".*자세히보기.*",
    r".*구독.*완료.*",
    r".*뉴스레터.*신청.*",
    r".*마이페이지.*확인.*",
    r".*기자 구독.*",
    r".*기자 이름을 클릭.*",
    r".*북마크 되었습니다.*",
    r"북마크 되었습니다\.",
    # Ad slot markers
    r"본문내?상단\s*광고\s*시작",
    r"본문내?상단\s*광고\s*끝",
    r"본문내?중단\s*광고\s*시작",
    r"본문내?중단\s*광고\s*끝",
    r"본문내?하단\s*광고\s*시작",
    r"본문내?하단\s*광고\s*끝",
    r"페이지상단\s*광고",
    r"페이지하단\s*광고",
    r"광고\s*시작",
    r"광고\s*끝",
    r"웹배너\s*시작",
    r"웹배너\s*끝",
    # Ad unit IDs (e.g., /77034085/article/mid(1)_300×250)
    r"/\d+/article/\S+",
    r"\d+×\d+",
    # UI element markers
    r"요약\s*버튼\s*시작",
    r"요약\s*버튼\s*끝",
    r"말풍선\s*전체\s*감싼\s*요소",
    r"BOOK MARK POPUP",
    r"BANNER",
    r"BREADCRUMBS",
    # Font size / share buttons
    r"\d{2}:\d{2}\s*/\s*\d{2}:\d{2}",
    r"카카오톡|페이스북|엑스|URL공유",
    r"가장작게|작게|기본|크게|가장크게",
    r".*글씨 작게보기.*",
    # Naver in-article ad markers
    r"PC 기사뷰.*?//",
    r"AD Manager\s*\|\s*AD\d+\s*//",
    r"AD\d{10,}\s*//",
    r"_기사내\d*_\w+",
    # Misc ad noise
    r"AD\s*CLOSE",
    r"스폰서\s*링크",
    r"Sponsored",
    # Site-specific UI text
    r"news_zone[\w\s_]*",
    r"quickguide",
    r"article_body\s*for\s*interworks\s*tag",
    r"글자크기",
    r"음성으로\s*듣기",
    r"글씨\s*크기\s*조절",
    r"본문\s*듣기",
    r"본문\s*글씨\s*크기",
    r"기사\s*제보",
    r"무단\s*전재.*?금지",
    r"저작권자.*?무단.*?금지",
    r"ⓒ\s*\S+.*?무단.*?금지",
    # Raw HTML class/id attributes leaking through
    r"\b(?:class|id)\s*=\s*['\"][^'\"]+['\"]",
    r"</?(?:div|span|img|a|p|br|table|tr|td|ul|li|em|strong|b|i)\b[^>]*>",
]


def clean_cached_content(text: str) -> str:
    """Re-apply noise filtering to previously cached article content."""
    for pattern in _NOISE_PATTERNS:
        text = re.sub(pattern, "", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


async def scrape_article_content(url: str) -> str | None:
    """Scrape the main text content from a news article URL.

    Returns cleaned plain text, or None if scraping fails.
    Strategy: CSS selectors → largest text block → Gemini AI extraction.
    """
    html = await _fetch_html(url)
    if not html:
        return None

    # Try BeautifulSoup extraction first
    text = _extract_with_bs4(html)
    if text:
        return text

    # Fallback: use Gemini AI to extract article text from raw HTML
    text = await _extract_with_ai(html, source_url=url)
    if text:
        return text

    return None


async def _fetch_html(url: str) -> str | None:
    """Fetch HTML from URL with redirect following."""
    try:
        async with httpx.AsyncClient(
            timeout=20, follow_redirects=True, max_redirects=10
        ) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Article fetch failed for {url}: {e}")
        return None

    # Detect encoding
    content_type = resp.headers.get("content-type", "")
    if "euc-kr" in content_type.lower():
        return resp.content.decode("euc-kr", errors="replace")
    return resp.text


def _extract_with_bs4(html: str) -> str | None:
    """Extract article text using BeautifulSoup CSS selectors."""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None

    # Remove unwanted elements using CSS selectors
    for selector in REMOVE_SELECTORS:
        try:
            for el in soup.select(selector):
                el.decompose()
        except Exception:
            continue

    # Try each content selector
    content_el = None
    for selector in CONTENT_SELECTORS:
        content_el = soup.select_one(selector)
        if content_el and len(content_el.get_text(strip=True)) > 100:
            break
        content_el = None

    if not content_el:
        content_el = _find_largest_text_block(soup)

    if not content_el:
        return None

    text = _clean_text(content_el)
    if len(text) < 50:
        return None

    return text


# P4: 도메인별 AI 추출 실패 카운터 (5회 연속 실패 시 24h 블랙리스트)
_ai_extract_failures: dict[str, tuple[int, float]] = {}  # {host: (count, blacklist_until_ts)}
_AI_EXTRACT_FAIL_THRESHOLD = 5
_AI_EXTRACT_BLACKLIST_TTL = 24 * 3600  # 24h


def _ai_extract_blacklisted(url: str) -> bool:
    import time as _t
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    info = _ai_extract_failures.get(host)
    if not info:
        return False
    count, until = info
    if count < _AI_EXTRACT_FAIL_THRESHOLD:
        return False
    if _t.time() > until:
        # 만료 → 카운터 리셋
        _ai_extract_failures.pop(host, None)
        return False
    return True


def _ai_extract_record_failure(url: str) -> None:
    import time as _t
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return
    if not host:
        return
    count, _ = _ai_extract_failures.get(host, (0, 0.0))
    count += 1
    until = _t.time() + _AI_EXTRACT_BLACKLIST_TTL if count >= _AI_EXTRACT_FAIL_THRESHOLD else 0.0
    _ai_extract_failures[host] = (count, until)


def _ai_extract_record_success(url: str) -> None:
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return
    _ai_extract_failures.pop(host, None)


async def _extract_with_ai(html: str, source_url: str | None = None) -> str | None:
    """Use AI to extract article content from HTML.

    P4 최적화: 트렁케이션 12K, 노이즈 태그 추가 제거, 도메인 블랙리스트.
    """
    # 도메인 블랙리스트 체크
    if source_url and _ai_extract_blacklisted(source_url):
        logger.debug(f"AI 추출 블랙리스트 도메인 스킵: {source_url}")
        return None

    # 노이즈 태그 제거 (입력 토큰 절감)
    cleaned = html
    for tag in ("script", "style", "nav", "header", "footer", "aside", "form", "noscript", "iframe", "svg"):
        cleaned = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    # HTML 주석 제거
    cleaned = re.sub(r"<!--.*?-->", "", cleaned, flags=re.DOTALL)
    # 연속 공백 압축
    cleaned = re.sub(r"\s+", " ", cleaned)

    # 트렁케이션 12K (이전 30K → 60% 토큰 절감)
    truncated = cleaned[:12000]

    prompt = f"""다음 HTML에서 뉴스 기사 본문만 추출해주세요.
광고, 메뉴, 관련기사 등은 제외하고 기사 본문 텍스트만 반환해주세요.
마크다운이나 HTML 태그 없이 순수 텍스트로 반환해주세요.
기사 본문을 찾을 수 없으면 "EMPTY"라고만 반환해주세요.

HTML:
{truncated}"""

    try:
        from app.services.ai_client import ask_ai

        text = await ask_ai(prompt)
        if not text or text == "EMPTY" or len(text) < 50:
            if source_url:
                _ai_extract_record_failure(source_url)
            return None
        if source_url:
            _ai_extract_record_success(source_url)
        return text
    except Exception as e:
        logger.warning(f"AI content extraction failed: {e}")
        if source_url:
            _ai_extract_record_failure(source_url)
        return None


def _find_largest_text_block(soup: BeautifulSoup):
    """Find the DOM element most likely to be the article body.

    Uses a density heuristic: prefers elements where most children are <p> tags,
    and avoids top-level wrappers that contain the entire page.
    """
    candidates = []
    for el in soup.find_all(["div", "section", "article"]):
        text = el.get_text(strip=True)
        text_len = len(text)
        if text_len < 200:
            continue

        # Skip elements that contain the entire page (too high in the DOM tree)
        parent_text_len = len(el.parent.get_text(strip=True)) if el.parent else text_len
        if parent_text_len > 0 and text_len / parent_text_len > 0.9 and el.parent and el.parent.name != "[document]":
            # This element has almost the same text as its parent — skip if parent is not root
            if el.parent.parent and el.parent.parent.name != "[document]":
                continue

        # Count <p> children as a signal of article content
        p_count = len(el.find_all("p", recursive=False))
        # Score: text length + bonus for having many <p> children
        score = text_len + (p_count * 200)
        candidates.append((score, text_len, el))

    if not candidates:
        return None

    # Pick the best candidate
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][2]


def _clean_text(element) -> str:
    """Extract clean text from a BeautifulSoup element."""
    # Get text with newlines preserved at block boundaries
    lines = []
    for child in element.descendants:
        if child.name in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            lines.append("\n")
        if child.string:
            text = child.string.strip()
            if text:
                lines.append(text)

    text = " ".join(lines)
    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()

    # Remove duplicate consecutive lines (common in scraped HTML)
    seen = set()
    deduped_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            deduped_lines.append("")
            continue
        if stripped not in seen:
            seen.add(stripped)
            deduped_lines.append(line)
    text = "\n".join(deduped_lines)

    # Remove common noise patterns
    for pattern in _NOISE_PATTERNS:
        text = re.sub(pattern, "", text)

    # Final cleanup
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()

    return text
