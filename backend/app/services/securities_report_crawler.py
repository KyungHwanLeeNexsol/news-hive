"""증권사 리포트 크롤러 (SPEC-FOLLOW-002).

네이버 리서치 센터 종목분석 리포트를 수집하여 DB에 저장한다.
PDF 파일은 수집하지 않으며 URL과 메타데이터만 저장한다 (REQ-FOLLOW-002-N3).
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

    async with httpx.AsyncClient(timeout=30.0, headers=_HEADERS) as client:
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
                try:
                    url = row_data.get("url", "")
                    if not url or url in existing_urls:
                        continue

                    # 종목명으로 stock_id 매핑
                    company_name = row_data.get("company_name", "")
                    stock_id = name_to_id.get(company_name)

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
                    )
                    db.add(report)
                    existing_urls.add(url)
                    new_count += 1
                except Exception as e:
                    logger.warning(f"리포트 행 처리 실패 (url={row_data.get('url', '')}): {e}")
                    continue

            api_circuit_breaker.record_success("naver_research")
            db.commit()
            logger.debug(f"네이버 리서치 page={page} 완료: 누적 {new_count}건 저장")

    logger.info(f"증권사 리포트 크롤링 완료: 신규 {new_count}건 저장")
    return new_count


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

            # PDF 링크 제외 (REQ-FOLLOW-002-N3)
            if href.endswith(".pdf") or "pdf" in href.lower():
                continue

            # URL을 절대경로로 변환
            if href.startswith("http"):
                url = href
            elif href.startswith("/"):
                url = f"https://finance.naver.com{href}"
            else:
                url = f"https://finance.naver.com/{href}"

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
