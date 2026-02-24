"""On-demand article content scraper.

Fetches the full text of a news article from its URL.
Uses BeautifulSoup to extract the main content from common
Korean news site HTML structures.
"""

import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# Common content selectors for Korean news sites (ordered by priority)
CONTENT_SELECTORS = [
    "article",
    "#articleBodyContents",       # Naver News
    "#newsEndContents",           # Naver News (new)
    ".article_body",              # 한국경제, 매일경제
    "#article_body",
    ".article-body",
    ".article_txt",               # 이데일리
    ".news_cnt_detail_wrap",      # 파이낸셜뉴스
    "#news_body_area",
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
]


async def scrape_article_content(url: str) -> str | None:
    """Scrape the main text content from a news article URL.

    Returns cleaned plain text, or None if scraping fails.
    """
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=HEADERS)
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Article fetch failed for {url}: {e}")
        return None

    # Detect encoding
    content_type = resp.headers.get("content-type", "")
    if "euc-kr" in content_type.lower():
        html = resp.content.decode("euc-kr", errors="replace")
    else:
        html = resp.text

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
        # Fallback: find the largest text block
        content_el = _find_largest_text_block(soup)

    if not content_el:
        return None

    # Extract and clean text
    text = _clean_text(content_el)

    # Minimum content threshold
    if len(text) < 50:
        return None

    return text


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
