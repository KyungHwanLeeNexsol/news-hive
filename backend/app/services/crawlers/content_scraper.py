"""뉴스 기사 본문 스크래핑 모듈.

기사 URL에서 본문 텍스트를 추출한다.
네이버 뉴스, 한국 경제지, 일반 뉴스 사이트를 지원한다.
"""

import asyncio
import logging
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 본문 추출 시 최대 글자 수 (토큰 절약)
MAX_CONTENT_LENGTH = 3000

# 동시 요청 제한
_SCRAPE_SEMAPHORE = asyncio.Semaphore(5)

# 공통 HTTP 헤더
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _clean_text(text: str) -> str:
    """공백/줄바꿈 정리 및 길이 제한."""
    # 연속 공백/줄바꿈 정리
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.strip()
    if len(text) > MAX_CONTENT_LENGTH:
        text = text[:MAX_CONTENT_LENGTH] + "..."
    return text


def _extract_naver_news(soup: BeautifulSoup) -> str | None:
    """네이버 뉴스 본문 추출."""
    # 네이버 뉴스 본문 영역 (newsct_article, dic_area)
    selectors = [
        "#dic_area",
        "#newsct_article",
        "#articeBody",
        "#articleBodyContents",
        ".news_end._article_body",
        "#news_body_area",
    ]
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            # 스크립트/스타일/광고 제거
            for tag in el.find_all(["script", "style", "iframe", "ins"]):
                tag.decompose()
            text = el.get_text(separator="\n")
            if len(text) > 50:
                return _clean_text(text)
    return None


def _extract_naver_entertain_sports(soup: BeautifulSoup) -> str | None:
    """네이버 연예/스포츠 뉴스 본문 추출."""
    selectors = [
        ".news_end._article_body",
        "#articeBody",
        ".article_body",
        "#newsEndContents",
    ]
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            for tag in el.find_all(["script", "style", "iframe", "ins"]):
                tag.decompose()
            text = el.get_text(separator="\n")
            if len(text) > 50:
                return _clean_text(text)
    return None


def _extract_korean_portal(soup: BeautifulSoup) -> str | None:
    """한국 경제지/일반 뉴스 사이트 본문 추출.

    etoday, fnnews, sedaily, hankyung, mk, edaily 등
    """
    selectors = [
        # 경제지 공통
        ".article_body",
        ".article-body",
        ".article_txt",
        ".articleView",
        "#article-view-content-div",
        "#articleBody",
        ".view_con",
        ".view_txt",
        ".news_body",
        ".newsView",
        ".article-view-body",
        # 매경/한경
        "#article_body",
        ".art_body",
        ".article_content",
        # 조선/중앙/동아
        ".par",
        "#article_content",
        ".article_cont",
    ]
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            for tag in el.find_all(["script", "style", "iframe", "ins", "figure", "figcaption"]):
                tag.decompose()
            text = el.get_text(separator="\n")
            if len(text) > 50:
                return _clean_text(text)
    return None


def _extract_generic(soup: BeautifulSoup) -> str | None:
    """일반 뉴스 사이트 본문 추출 (fallback).

    <article> 태그 또는 가장 긴 텍스트 블록을 찾는다.
    """
    # 1) <article> 태그
    article = soup.find("article")
    if article:
        for tag in article.find_all(["script", "style", "iframe", "ins", "nav", "header", "footer"]):
            tag.decompose()
        text = article.get_text(separator="\n")
        if len(text) > 100:
            return _clean_text(text)

    # 2) 가장 긴 <p> 집합이 있는 컨테이너
    containers = soup.find_all(["div", "section"], recursive=True)
    best_text = ""
    for container in containers:
        paragraphs = container.find_all("p", recursive=False)
        if len(paragraphs) >= 2:
            text = "\n".join(p.get_text() for p in paragraphs)
            if len(text) > len(best_text):
                best_text = text

    if len(best_text) > 100:
        return _clean_text(best_text)

    return None


def _is_naver_news(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return "n.news.naver.com" in host or "news.naver.com" in host


def _is_naver_entertain_sports(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return "n.news.naver.com" not in host and (
        "entertain.naver.com" in host or "sports.naver.com" in host
    )


async def scrape_article_content(url: str, client: httpx.AsyncClient) -> str | None:
    """단일 기사 URL에서 본문 텍스트를 추출한다.

    Returns:
        본문 텍스트 (성공 시) 또는 None (실패/스킵 시)
    """
    try:
        async with _SCRAPE_SEMAPHORE:
            resp = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=10.0)
            if resp.status_code != 200:
                return None
            # 텍스트가 아닌 응답 스킵
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # URL 패턴에 따라 적절한 추출기 선택
            if _is_naver_news(url):
                text = _extract_naver_news(soup)
            elif _is_naver_entertain_sports(url):
                text = _extract_naver_entertain_sports(soup)
            else:
                text = _extract_korean_portal(soup) or _extract_generic(soup)

            return text

    except (httpx.TimeoutException, httpx.ConnectError, httpx.TooManyRedirects):
        return None
    except Exception as e:
        logger.debug(f"Content scrape failed for {url}: {e}")
        return None


async def scrape_articles_batch(
    articles: list[dict],
    max_articles: int = 50,
) -> dict[str, str]:
    """여러 기사의 본문을 병렬로 스크래핑한다.

    Args:
        articles: url 키를 가진 기사 dict 리스트
        max_articles: 최대 스크래핑할 기사 수 (API 비용/시간 제한)

    Returns:
        {url: content} 매핑 딕셔너리
    """
    # 스크래핑 대상 선정 (최대 max_articles개)
    targets = articles[:max_articles]

    async with httpx.AsyncClient() as client:
        tasks = [scrape_article_content(a["url"], client) for a in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    url_to_content: dict[str, str] = {}
    success_count = 0
    for article, result in zip(targets, results):
        if isinstance(result, str) and result:
            url_to_content[article["url"]] = result
            success_count += 1

    if targets:
        logger.info(
            f"Content scraping: {success_count}/{len(targets)} articles "
            f"({success_count / len(targets) * 100:.0f}% success)"
        )

    return url_to_content
