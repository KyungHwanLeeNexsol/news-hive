"""증권사 리포트 크롤러 (SPEC-FOLLOW-002).

네이버 리서치 센터 종목분석 리포트를 수집하여 DB에 저장한다.
URL과 메타데이터를 수집하고, HTML 페이지에서 보고서 본문도 추출하여 저장한다.
본문은 AI 키워드 생성 시 투자포인트 추출에 활용된다.
"""

import logging
import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models.securities_report import SecuritiesReport
from app.models.stock import Stock
from app.services.circuit_breaker import api_circuit_breaker

logger = logging.getLogger(__name__)

# 네이버 리서치 종목분석 리스트 URL
NAVER_RESEARCH_URL = "https://finance.naver.com/research/company_list.naver"

# HTTP 요청 헤더 (네이버 차단 방지)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/research/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 보고서 본문 최대 저장 길이
_CONTENT_MAX_LEN = 3000


def _parse_target_price(text: str | None) -> int | None:
    """목표주가 문자열을 정수로 변환한다.

    Args:
        text: "1,234,000원" 또는 "N/A" 또는 "-" 형태의 문자열

    Returns:
        정수형 목표주가, 파싱 실패 시 None
    """
    if not text:
        return None
    cleaned = re.sub(r"[^0-9]", "", text)
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except (ValueError, OverflowError):
        return None


def _parse_published_at(date_str: str | None) -> datetime | None:
    """날짜 문자열을 datetime 객체로 변환한다.

    Args:
        date_str: "2026.04.06" 형태의 날짜 문자열

    Returns:
        UTC datetime, 파싱 실패 시 None
    """
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _extract_report_content(html: str) -> str | None:
    """네이버 리서치 보고서 HTML에서 본문 텍스트를 추출한다.

    Args:
        html: 보고서 페이지 HTML 문자열

    Returns:
        추출된 본문 텍스트 (최대 _CONTENT_MAX_LEN자), 추출 실패 시 None
    """
    soup = BeautifulSoup(html, "html.parser")

    # 불필요 태그 제거 (스크립트, 스타일, 네비게이션)
    for tag in soup.find_all(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    text_parts: list[str] = []

    # 1차: 네이버 리서치 본문 컨테이너 탐색 (알려진 선택자 순서대로)
    content_selectors = [
        ("div", {"class": "view_txt"}),
        ("div", {"class": "view_text"}),
        ("div", {"class": "report_text"}),
        ("div", {"id": "content"}),
        ("div", {"class": "content"}),
    ]
    for tag, attrs in content_selectors:
        el = soup.find(tag, attrs)
        if el:
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 100:
                text_parts.append(text)
                break

    # 2차: 폴백 — td.view 또는 본문 td 탐색
    if not text_parts:
        td = soup.find("td", {"class": "view"})
        if td:
            text = td.get_text(separator=" ", strip=True)
            if len(text) > 100:
                text_parts.append(text)

    # 3차: 폴백 — 모든 <p> 태그에서 본문 수집
    if not text_parts:
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 30]
        if paras:
            text_parts.append(" ".join(paras))

    if not text_parts:
        return None

    # 공백 정규화 및 길이 제한
    combined = re.sub(r"\s{2,}", " ", " ".join(text_parts)).strip()
    return combined[:_CONTENT_MAX_LEN] if combined else None


async def _fetch_report_content(client: httpx.AsyncClient, url: str) -> str | None:
    """보고서 URL에서 HTML을 가져와 본문 텍스트를 추출한다.

    Args:
        client: 재사용 httpx 클라이언트
        url: 보고서 페이지 URL

    Returns:
        추출된 본문 텍스트, 실패 시 None
    """
    try:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return _extract_report_content(resp.text)
    except Exception as e:
        logger.debug(f"보고서 본문 조회 실패 ({url}): {e}")
        return None


async def fetch_securities_reports(db: Session, pages: int = 3) -> int:
    """네이버 리서치 종목분석 리포트를 수집하여 저장한다.

    Args:
        db: SQLAlchemy 세션
        pages: 수집할 페이지 수 (기본값 3)

    Returns:
        신규 저장된 리포트 건수
    """
    # 서킷 브레이커 확인
    if not api_circuit_breaker.is_available("naver_research"):
        logger.warning("네이버 리서치 서킷 브레이커 오픈 — 크롤링 스킵")
        return 0

    # 기존 URL 사전 로드 (중복 방지)
    existing_urls: set[str] = {
        row[0] for row in db.query(SecuritiesReport.url).all()
    }

    # 종목명 → stock_id 매핑 (stock_code가 있는 종목만)
    name_to_id: dict[str, int] = {
        stock.name: stock.id
        for stock in db.query(Stock).filter(Stock.stock_code.isnot(None)).all()
    }

    new_count = 0
    # 새로 발견된 보고서 목록 (URL + 메타데이터)
    new_reports: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0, headers=_HEADERS) as client:
        # 1단계: 리스트 페이지에서 메타데이터 수집
        for page in range(1, pages + 1):
            try:
                resp = await client.get(
                    NAVER_RESEARCH_URL,
                    params={"page": page},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.warning(f"네이버 리서치 HTTP 오류 (page={page}): {e.response.status_code}")
                api_circuit_breaker.record_failure("naver_research")
                break
            except httpx.RequestError as e:
                logger.warning(f"네이버 리서치 요청 실패 (page={page}): {e}")
                api_circuit_breaker.record_failure("naver_research")
                break

            rows = _parse_report_rows(resp.text)
            if not rows:
                logger.debug(f"네이버 리서치 page={page}: 파싱된 행 없음, 종료")
                break

            for row_data in rows:
                url = row_data.get("url", "")
                if url and url not in existing_urls:
                    new_reports.append(row_data)
                    existing_urls.add(url)

            api_circuit_breaker.record_success("naver_research")

        # 2단계: 새 보고서 본문 개별 조회 후 저장
        for row_data in new_reports:
            url = row_data.get("url", "")
            if not url:
                continue

            # 보고서 본문 조회 (실패해도 메타데이터만으로 저장)
            content = await _fetch_report_content(client, url)

            company_name = row_data.get("company_name", "")
            stock_id = name_to_id.get(company_name)

            try:
                report = SecuritiesReport(
                    title=row_data.get("title", "")[:500],
                    company_name=company_name[:200],
                    stock_code=row_data.get("stock_code"),
                    stock_id=stock_id,
                    securities_firm=row_data.get("securities_firm", "")[:100],
                    opinion=row_data.get("opinion"),
                    target_price=row_data.get("target_price"),
                    url=url[:1000],
                    published_at=row_data.get("published_at"),
                    content=content,
                )
                db.add(report)
                new_count += 1
            except Exception as e:
                logger.warning(f"리포트 행 처리 실패 (url={url}): {e}")
                continue

        db.commit()

    logger.info(f"증권사 리포트 크롤링 완료: 신규 {new_count}건 저장")
    return new_count


async def backfill_report_content(db: Session, batch_size: int = 50) -> int:
    """기존 보고서 중 content가 없는 항목을 백필한다.

    Args:
        db: SQLAlchemy 세션
        batch_size: 한 번에 처리할 최대 건수

    Returns:
        백필 완료된 건수
    """
    reports = (
        db.query(SecuritiesReport)
        .filter(SecuritiesReport.content.is_(None))
        .order_by(SecuritiesReport.published_at.desc())
        .limit(batch_size)
        .all()
    )

    if not reports:
        return 0

    updated = 0
    async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as client:
        for report in reports:
            content = await _fetch_report_content(client, report.url)
            if content:
                report.content = content
                updated += 1

    db.commit()
    logger.info(f"증권사 리포트 본문 백필 완료: {updated}/{len(reports)}건")
    return updated


def _parse_report_rows(html: str) -> list[dict]:
    """HTML에서 리포트 행 데이터를 파싱한다.

    Args:
        html: 네이버 리서치 페이지 HTML 문자열

    Returns:
        리포트 데이터 딕셔너리 목록
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # 종목분석 테이블 탐색 (table.type_1 또는 id/class 기반 폴백)
    table = soup.find("table", class_="type_1")
    if not table:
        table = soup.find("table")

    if not table:
        return results

    rows = table.find_all("tr")
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            # 헤더 행이나 구분 행은 스킵
            continue

        try:
            # 컬럼 순서: 종목명, 리포트제목, 증권사, 목표주가, 의견, 날짜
            # 실제 네이버 리서치 구조에 맞게 파싱
            company_td = cols[0]
            title_td = cols[1]
            firm_td = cols[2]
            # 목표주가와 의견은 위치가 다를 수 있음
            target_td = cols[3] if len(cols) > 3 else None
            opinion_td = cols[4] if len(cols) > 4 else None
            date_td = cols[-1]  # 날짜는 마지막 컬럼

            company_name = company_td.get_text(strip=True)

            # 리포트 제목 및 URL
            title_tag = title_td.find("a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")

            # PDF 링크 제외
            if href.endswith(".pdf") or "pdf" in href.lower():
                continue

            # JavaScript 링크 및 빈 링크 제외
            if not href or href.startswith("javascript:"):
                continue

            # URL을 절대경로로 변환
            if href.startswith("http"):
                url = href.strip()
            elif href.startswith("/"):
                url = f"https://finance.naver.com{href.strip()}"
            else:
                url = f"https://finance.naver.com/{href.strip()}"

            # 네이버 HTML 구조 변경 대응:
            # /company_read.naver?nid=N&page=M → /research/company_read.naver?nid=N
            if "/company_read.naver" in url and "/research/" not in url:
                nid_m = re.search(r"nid=(\d+)", url)
                if nid_m:
                    url = f"https://finance.naver.com/research/company_read.naver?nid={nid_m.group(1)}"

            securities_firm = firm_td.get_text(strip=True)
            target_price_text = target_td.get_text(strip=True) if target_td else None
            opinion = opinion_td.get_text(strip=True) if opinion_td else None
            date_str = date_td.get_text(strip=True)

            results.append({
                "company_name": company_name,
                "title": title,
                "url": url,
                "securities_firm": securities_firm,
                "opinion": opinion if opinion and opinion not in ("-", "N/A", "") else None,
                "target_price": _parse_target_price(target_price_text),
                "published_at": _parse_published_at(date_str),
                "stock_code": None,  # 네이버 리서치 목록에는 코드 미노출
            })
        except Exception as e:
            logger.debug(f"리포트 행 파싱 실패: {e}")
            continue

    return results
