"""VIP투자자문 대량보유 공시 수집기.

DART Open API에서 VIP투자자문의 주식등의대량보유 공시를 수집하여
vip_disclosures 테이블에 저장한다.

SPEC-VIP-001 REQ-VIP-001
"""
import io
import logging
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.stock import Stock
from app.models.vip_trading import VIPDisclosure

logger = logging.getLogger(__name__)

# DART API 엔드포인트
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.json"

# VIP투자자문 공시자명 키워드 — DART flr_nm 필드에서 부분 매칭
VIP_FILER_KEYWORD = "VIP투자자문"

# 대량보유 공시 보고서명 키워드
STAKE_REPORT_KEYWORD = "주식등의대량보유"


async def fetch_vip_disclosures(db: Session, days: int = 3) -> int:
    """DART OpenAPI에서 VIP투자자문의 대량보유 공시를 수집한다.

    전략:
    1. DART list API에서 지분공시(pblntf_ty=B) 목록 조회
    2. report_nm에 "주식등의대량보유" 포함 항목 필터링
    3. flr_nm에 "VIP투자자문" 포함 여부 확인
    4. VIP 공시 발견 시 상세 보고서 파싱 (stake_pct, avg_price 추출)
    5. vip_disclosures 테이블에 저장

    Args:
        db: DB 세션
        days: 조회 기간 (기본 3일)

    Returns:
        신규 저장된 공시 수
    """
    dart_key = settings.DART_API_KEY
    if not dart_key:
        logger.warning("DART_API_KEY 미설정, VIP 공시 수집 스킵")
        return 0

    # 기존 수집 rcept_no 중복 방지
    existing_rcepts: set[str] = {
        row[0] for row in db.query(VIPDisclosure.rcept_no).all()
    }

    # 종목 코드 → stock_id 매핑 테이블 구성
    stocks = db.query(Stock).filter(Stock.stock_code.isnot(None)).all()
    code_to_id: dict[str, int] = {s.stock_code.strip(): s.id for s in stocks}

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    bgn_de = start_dt.strftime("%Y%m%d")
    end_de = end_dt.strftime("%Y%m%d")
    logger.info("VIP 공시 수집 시작: %s ~ %s", bgn_de, end_de)

    saved = 0
    page_no = 1
    page_count = 100

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = {
                "crtfc_key": dart_key,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "pblntf_ty": "B",  # 지분공시 분류
                "sort": "date",
                "sort_mth": "desc",
                "page_no": str(page_no),
                "page_count": str(page_count),
            }

            try:
                resp = await client.get(DART_LIST_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                logger.error("DART list API HTTP 오류 (page %d): %s", page_no, e)
                break
            except httpx.RequestError as e:
                logger.error("DART list API 요청 실패 (page %d): %s", page_no, e)
                break

            status = data.get("status", "")
            if status == "013":
                # 데이터 없음 — 정상 종료
                logger.debug("DART list API: 조회 결과 없음 (page %d)", page_no)
                break
            if status != "000":
                logger.warning("DART list API 비정상 응답: status=%s, msg=%s", status, data.get("message"))
                break

            items = data.get("list", [])
            if not items:
                break

            for item in items:
                report_nm = item.get("report_nm", "")
                flr_nm = item.get("flr_nm", "")
                rcept_no = item.get("rcept_no", "")

                # 대량보유 공시 여부 필터
                if STAKE_REPORT_KEYWORD not in report_nm:
                    continue

                # VIP투자자문 공시자 필터
                if VIP_FILER_KEYWORD not in flr_nm:
                    continue

                # 중복 스킵
                if rcept_no in existing_rcepts:
                    logger.debug("VIP 공시 이미 존재: %s", rcept_no)
                    continue

                corp_name = item.get("corp_name", "")
                stock_code = item.get("stock_code", "").strip() or None
                rcept_dt = item.get("rcept_dt", "")

                logger.info(
                    "VIP 공시 발견: %s (%s) rcept_no=%s",
                    corp_name, stock_code, rcept_no,
                )

                # 보고서 상세 파싱 시도 (stake_pct, avg_price 추출)
                detail = await _parse_vip_disclosure_detail(client, rcept_no, dart_key)
                stake_pct: float = 0.0
                avg_price: float | None = None
                raw_xml: str | None = None

                if detail:
                    stake_pct = detail.get("stake_pct", 0.0)
                    avg_price = detail.get("avg_price")
                    raw_xml = detail.get("raw_xml")

                # parse_success: 파싱 성공 여부 — 실패 시 "below5" 대신 "unknown" 분류
                # (파싱 실패를 below5로 처리하면 VIP 매수 공시를 잘못 청산할 위험 있음)
                parse_success = detail is not None and stake_pct > 0.0
                disclosure_type = _determine_disclosure_type(stake_pct, report_nm, parse_success)

                if disclosure_type == "unknown":
                    logger.warning(
                        "VIP 공시 파싱 실패 — 수동 확인 필요: rcept_no=%s, corp=%s, report=%s",
                        rcept_no, corp_name, report_nm,
                    )

                # stock_code로 stock_id 매핑
                stock_id: int | None = None
                if stock_code and stock_code in code_to_id:
                    stock_id = code_to_id[stock_code]

                vip_disc = VIPDisclosure(
                    rcept_no=rcept_no,
                    corp_name=corp_name,
                    stock_code=stock_code,
                    stock_id=stock_id,
                    stake_pct=stake_pct,
                    avg_price=avg_price,
                    disclosure_type=disclosure_type,
                    rcept_dt=rcept_dt,
                    flr_nm=flr_nm,
                    report_nm=report_nm,
                    raw_xml=raw_xml,
                    processed=False,
                )
                db.add(vip_disc)
                existing_rcepts.add(rcept_no)
                saved += 1

            if len(items) < page_count:
                # 마지막 페이지
                break
            page_no += 1

    if saved:
        db.commit()
        logger.info("VIP 공시 %d건 신규 저장 완료", saved)

    return saved


async def _parse_vip_disclosure_detail(
    client: httpx.AsyncClient,
    rcept_no: str,
    dart_key: str,
) -> dict | None:
    """DART 공시 상세 내용에서 지분율/평균단가/종목코드를 파싱한다.

    DART document API가 반환하는 ZIP 파일 내 XML을 파싱하여
    보유비율(stake_pct), 평균단가(avg_price)를 추출한다.

    파싱 실패 시 None 반환 — 호출자가 기본값(0.0, None)을 사용.

    Args:
        client: 재사용 httpx 클라이언트
        rcept_no: DART 접수번호
        dart_key: DART API 키

    Returns:
        {"stake_pct": float, "avg_price": float|None, "raw_xml": str|None} or None
    """
    try:
        resp = await client.get(
            DART_DOCUMENT_URL,
            params={"crtfc_key": dart_key, "rcept_no": rcept_no},
            timeout=20.0,
        )
        resp.raise_for_status()

        # ZIP 파일 압축 해제
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith((".xml", ".htm", ".html"))]
            if not xml_names:
                logger.debug("VIP 공시 문서에 XML 파일 없음: %s", rcept_no)
                return None

            xml_content = zf.read(xml_names[0]).decode("utf-8", errors="replace")

        return _extract_stake_info_from_xml(xml_content, rcept_no)

    except zipfile.BadZipFile:
        logger.debug("VIP 공시 문서 ZIP 파싱 실패 (BadZipFile): %s", rcept_no)
        return None
    except httpx.HTTPStatusError as e:
        logger.debug("VIP 공시 문서 API HTTP 오류 (%s): %s", rcept_no, e)
        return None
    except httpx.RequestError as e:
        logger.debug("VIP 공시 문서 요청 실패 (%s): %s", rcept_no, e)
        return None
    except Exception as e:
        logger.debug("VIP 공시 문서 파싱 예외 (%s): %s", rcept_no, e)
        return None


def _extract_stake_info_from_xml(xml_content: str, rcept_no: str) -> dict | None:
    """XML/HTML 문자열에서 보유비율과 평균단가를 추출한다.

    DART 보고서는 XML과 HTML 두 형식으로 제공된다.
    정규식 → ElementTree → HTML 텍스트 스캔 순서로 3단계 파싱을 시도한다.

    Args:
        xml_content: XML 또는 HTML 문자열
        rcept_no: 로깅용 접수번호

    Returns:
        {"stake_pct": float, "avg_price": float|None, "raw_xml": str} or None
    """
    import re

    stake_pct: float = 0.0
    avg_price: float | None = None

    # -------------------------------------------------------------------
    # 1단계: 정규식 패턴 매칭 (XML 태그 + HTML 텍스트 패턴 통합)
    # DART XML: <보유비율>5.12</보유비율>
    # DART HTML 테이블: >5.12%< 또는 >5.12 <  (보유비율 셀 다음 셀)
    # -------------------------------------------------------------------
    stake_patterns = [
        # XML 태그 방식
        r"<보유비율[^>]*>\s*([\d.]+)\s*</보유비율>",
        r"<주식등의비율[^>]*>\s*([\d.]+)\s*</주식등의비율>",
        # HTML 셀: "보유비율" 키워드 이후 숫자+% (최대 200자 이내)
        r"보유비율.{0,200}?([\d]+\.[\d]+)\s*%",
        r"보유\s*비율.{0,200}?([\d]+\.[\d]+)",
        # 주식등의수 / 발행주식 비율 패턴
        r"주식등의\s*비율.{0,200}?([\d]+\.[\d]+)\s*%",
        r"소유\s*비율.{0,200}?([\d]+\.[\d]+)\s*%",
    ]
    for pattern in stake_patterns:
        match = re.search(pattern, xml_content, re.DOTALL)
        if match:
            try:
                val = float(match.group(1))
                if 0.0 < val <= 100.0:
                    stake_pct = val
                    logger.debug("VIP 공시 보유비율 정규식 추출 (%s): %.2f%%", rcept_no, stake_pct)
                    break
            except ValueError:
                continue

    # 평균단가 추출
    avg_patterns = [
        r"<평균단가[^>]*>\s*([\d,]+)\s*</평균단가>",
        r"평균\s*단가.{0,200}?([\d,]+)원",
        r"평균\s*단가.{0,200}?([\d,]{4,})",   # 4자리 이상 숫자 (1,000원 이상)
        r"취득\s*단가.{0,200}?([\d,]{4,})",
    ]
    for pattern in avg_patterns:
        match = re.search(pattern, xml_content, re.DOTALL)
        if match:
            try:
                raw_num = match.group(1).replace(",", "")
                val = float(raw_num)
                if val >= 100:   # 100원 이상만 유효한 주가로 간주
                    avg_price = val
                    break
            except ValueError:
                continue

    # -------------------------------------------------------------------
    # 2단계: ElementTree XML 파싱 (정규식 보완)
    # -------------------------------------------------------------------
    if stake_pct == 0.0:
        try:
            root = ET.fromstring(xml_content)
            for elem in root.iter():
                tag = (elem.tag or "").lower()
                text = (elem.text or "").strip().replace(",", "").replace("%", "")
                if ("보유비율" in tag or "주식등의비율" in tag) and text:
                    try:
                        val = float(text)
                        if 0.0 < val <= 100.0:
                            stake_pct = val
                            logger.debug(
                                "VIP 공시 보유비율 ElementTree 추출 (%s): %.2f%%",
                                rcept_no, stake_pct,
                            )
                            break
                    except ValueError:
                        continue
        except ET.ParseError:
            logger.debug("XML ElementTree 파싱 실패 (%s) — HTML 문서 가능성", rcept_no)

    # -------------------------------------------------------------------
    # 3단계: HTML 테이블 텍스트 스캔 (DART HTML 보고서 대응)
    # "보유비율" 키워드 다음에 오는 td/th 셀의 첫 번째 숫자 추출
    # -------------------------------------------------------------------
    if stake_pct == 0.0:
        # 셀 경계 분리 후 "보유비율" 셀 다음 셀에서 숫자 추출
        cells = re.split(r"<(?:td|th)[^>]*>", xml_content, flags=re.IGNORECASE)
        for idx, cell in enumerate(cells):
            clean = re.sub(r"<[^>]+>", "", cell).strip()
            if "보유비율" in clean or "주식등의비율" in clean:
                # 다음 셀들에서 숫자 탐색
                for next_cell in cells[idx + 1 : idx + 4]:
                    next_clean = re.sub(r"<[^>]+>", "", next_cell).strip().replace(",", "")
                    num_match = re.search(r"([\d]+\.[\d]+)", next_clean)
                    if num_match:
                        try:
                            val = float(num_match.group(1))
                            if 0.0 < val <= 100.0:
                                stake_pct = val
                                logger.debug(
                                    "VIP 공시 보유비율 HTML 테이블 추출 (%s): %.2f%%",
                                    rcept_no, stake_pct,
                                )
                                break
                        except ValueError:
                            continue
                if stake_pct > 0.0:
                    break

    if stake_pct == 0.0:
        logger.debug("VIP 공시 보유비율 추출 실패 (%s) — 3단계 모두 시도", rcept_no)

    # 원본은 최대 50KB만 보존 (DB 부담 최소화)
    raw_xml = xml_content[:51200] if xml_content else None

    return {
        "stake_pct": stake_pct,
        "avg_price": avg_price,
        "raw_xml": raw_xml,
    }


def _determine_disclosure_type(
    stake_pct: float, report_nm: str, parse_success: bool = True
) -> str:
    """공시 유형을 결정한다.

    parse_success=False(파싱 실패)이고 보고서명에 명시적 매도/감소 키워드가 없으면
    "below5" 대신 "unknown"을 반환한다.
    → "unknown"은 매매 없이 로그만 남기고 수동 확인을 유도한다.
    → 파싱 실패를 "below5"로 처리하면 VIP 매수 공시를 잘못 청산할 위험이 있다.

    Args:
        stake_pct: 보유비율 (%)
        report_nm: DART 보고서명
        parse_success: 상세 파싱 성공 여부 (stake_pct > 0.0이면 True)

    Returns:
        "accumulate" | "reduce" | "below5" | "unknown"
    """
    if stake_pct >= 5.0:
        return "accumulate"
    if 0.0 < stake_pct < 5.0:
        return "below5"
    # stake_pct == 0.0 — 파싱 실패이거나 실제 0%
    _REDUCE_KEYWORDS = ("처분", "감소", "감량", "매도", "일부처분")
    if any(kw in report_nm for kw in _REDUCE_KEYWORDS):
        return "below5"   # 명시적 매도/감소 보고서
    if not parse_success:
        return "unknown"  # 파싱 실패 — 수동 확인 필요
    return "below5"


async def process_unhandled_vip_disclosures(db: Session) -> int:
    """미처리 VIP 공시를 조회하여 매매 서비스로 라우팅한다.

    공시 수집 후 별도 호출하거나, 스케줄러에서 직접 호출할 수 있다.

    Args:
        db: DB 세션

    Returns:
        처리된 공시 수
    """
    from app.services.vip_follow_trading import process_new_vip_disclosure

    unprocessed = (
        db.query(VIPDisclosure)
        .filter(VIPDisclosure.processed.is_(False))
        .order_by(VIPDisclosure.rcept_dt.asc(), VIPDisclosure.created_at.asc())
        .all()
    )

    if not unprocessed:
        return 0

    count = 0
    for disc in unprocessed:
        try:
            await process_new_vip_disclosure(db, disc)
            count += 1
        except Exception as e:
            logger.error("VIP 공시 처리 실패 (rcept_no=%s): %s", disc.rcept_no, e)

    return count
