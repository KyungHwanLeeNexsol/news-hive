"""뉴스 기사 본문 스크래핑 모듈.

기사 URL에서 본문 텍스트를 추출한다.
on-demand 스크래퍼(article_scraper.py)의 정교한 추출 로직을 재사용한다.
"""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

# 동시 요청 제한 (10개로 증가하여 처리량 향상)
_SCRAPE_SEMAPHORE = asyncio.Semaphore(10)

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


async def scrape_article_content(url: str, client: httpx.AsyncClient) -> str | None:
    """단일 기사 URL에서 본문 텍스트를 추출한다.

    article_scraper.py의 정교한 BS4 추출 로직을 재사용한다.
    (AI fallback은 배치에서는 비용이 크므로 생략)

    Returns:
        본문 텍스트 (성공 시) 또는 None (실패/스킵 시)
    """
    from app.services.article_scraper import (
        CONTENT_SELECTORS,
        REMOVE_SELECTORS,
        _find_largest_text_block,
        _clean_text,
    )
    from bs4 import BeautifulSoup

    try:
        async with _SCRAPE_SEMAPHORE:
            resp = await client.get(url, headers=_HEADERS, follow_redirects=True, timeout=15.0)
            if resp.status_code != 200:
                return None
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None

            # EUC-KR 인코딩 처리
            if "euc-kr" in content_type.lower():
                html = resp.content.decode("euc-kr", errors="replace")
            else:
                html = resp.text

            soup = BeautifulSoup(html, "html.parser")

            # 노이즈 요소 제거 (article_scraper의 50+ 셀렉터 사용)
            for selector in REMOVE_SELECTORS:
                try:
                    for el in soup.select(selector):
                        el.decompose()
                except Exception:
                    continue

            # 본문 추출 (article_scraper의 셀렉터 사용)
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

            # 배치 스크래핑에서는 5000자로 제한
            if len(text) > 5000:
                text = text[:5000] + "..."

            return text

    except (httpx.TimeoutException, httpx.ConnectError, httpx.TooManyRedirects):
        return None
    except Exception as e:
        logger.debug(f"Content scrape failed for {url}: {e}")
        return None


async def scrape_articles_batch(
    articles: list[dict],
    max_articles: int = 0,
) -> dict[str, str]:
    """여러 기사의 본문을 병렬로 스크래핑한다.

    Args:
        articles: url 키를 가진 기사 dict 리스트
        max_articles: 최대 스크래핑할 기사 수 (0=전체)

    Returns:
        {url: content} 매핑 딕셔너리
    """
    targets = articles[:max_articles] if max_articles > 0 else articles

    if not targets:
        return {}

    # 배치 단위로 스크래핑 (메모리/연결 관리)
    batch_size = 30
    url_to_content: dict[str, str] = {}
    success_count = 0
    failed_urls: list[dict] = []

    async with httpx.AsyncClient() as client:
        for i in range(0, len(targets), batch_size):
            batch = targets[i : i + batch_size]
            tasks = [scrape_article_content(a["url"], client) for a in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for article, result in zip(batch, results):
                if isinstance(result, str) and result:
                    url_to_content[article["url"]] = result
                    success_count += 1
                else:
                    failed_urls.append(article)

        # 실패한 기사 1회 재시도
        if failed_urls:
            retry_targets = failed_urls[:50]
            retry_tasks = [scrape_article_content(a["url"], client) for a in retry_targets]
            retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)
            retry_success = 0
            for article, result in zip(retry_targets, retry_results):
                if isinstance(result, str) and result:
                    url_to_content[article["url"]] = result
                    success_count += 1
                    retry_success += 1
            if retry_success:
                logger.info(f"Content scraping retry: {retry_success}/{len(retry_targets)} recovered")

    if targets:
        logger.info(
            f"Content scraping: {success_count}/{len(targets)} articles "
            f"({success_count / len(targets) * 100:.0f}% success)"
        )

    return url_to_content
