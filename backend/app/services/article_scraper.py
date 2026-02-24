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
    # General patterns
    "article",
    ".view_con",
    ".article-view-body",
    ".news_view",
    ".articleView",
    "#articeBody",
    "#textBody",
    ".post-content",
    ".entry-content",
    "main",
]

# Tags to remove from extracted content
REMOVE_TAGS = [
    "script", "style", "iframe", "nav", "header", "footer",
    "aside", "form", "button", "input", "select", "textarea",
    "figure", "figcaption", "img", "video", "audio", "source",
    "ad", ".ad", ".advertisement", ".social-share", ".related-article",
    ".reporter_area", ".byline", ".copyright", ".article_footer",
    ".article_relation", ".article_issue",
]


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
    text = await _extract_with_ai(html)
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

    # Remove unwanted elements
    for tag in REMOVE_TAGS:
        if tag.startswith("."):
            for el in soup.select(tag):
                el.decompose()
        else:
            for el in soup.find_all(tag):
                el.decompose()

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


async def _extract_with_ai(html: str) -> str | None:
    """Use Gemini AI to extract article content from HTML."""
    from app.config import settings

    if not settings.GEMINI_API_KEY:
        return None

    # Truncate HTML to avoid token limits (keep first ~30K chars)
    truncated = html[:30000]

    # Strip script/style tags to reduce noise
    truncated = re.sub(r"<script[^>]*>.*?</script>", "", truncated, flags=re.DOTALL | re.IGNORECASE)
    truncated = re.sub(r"<style[^>]*>.*?</style>", "", truncated, flags=re.DOTALL | re.IGNORECASE)

    prompt = f"""다음 HTML에서 뉴스 기사 본문만 추출해주세요.
광고, 메뉴, 사이드바, 관련기사 등은 제외하고 기사 본문 텍스트만 반환해주세요.
마크다운이나 HTML 태그 없이 순수 텍스트로 반환해주세요.
기사 본문을 찾을 수 없으면 "EMPTY"라고만 반환해주세요.

HTML:
{truncated}"""

    try:
        from google import genai

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        if not text or text == "EMPTY" or len(text) < 50:
            return None
        return text
    except Exception as e:
        logger.warning(f"AI content extraction failed: {e}")
        return None


def _find_largest_text_block(soup: BeautifulSoup):
    """Find the DOM element with the most text content."""
    best = None
    best_len = 0
    for el in soup.find_all(["div", "section", "article", "main"]):
        text = el.get_text(strip=True)
        if len(text) > best_len:
            best_len = len(text)
            best = el
    return best if best_len > 200 else None


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

    return text
