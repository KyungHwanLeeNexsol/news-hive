"""AI 키워드 생성 서비스 (SPEC-FOLLOW-001).

Gemini/Z.AI를 사용하여 팔로잉 종목의 투자 모니터링 키워드를 자동 생성한다.
사업보고서(공시) + 애널리스트 리포트 본문을 교차 참조하여 투자포인트 중심의 키워드를 도출한다.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.services.ai_client import ask_ai_standard as ask_ai

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 지원하는 키워드 카테고리
_CATEGORIES = ("product", "competitor", "upstream", "market")

# 애널리스트 리포트 수집 기간 (최근 1년)
_REPORT_LOOKBACK_DAYS = 365


def _build_reference_context(stock_code: str, db: Session) -> str:
    """DB에서 최신 공시 보고서 및 애널리스트 리포트를 조회하여 컨텍스트 문자열을 반환한다.

    공시 보고서와 애널리스트 리포트 본문을 함께 제공하여 투자포인트 중심의 키워드를
    생성할 수 있도록 한다. 리포트 본문(content)이 있는 경우 내용을 포함하고,
    없는 경우 제목+의견만 포함한다.

    Args:
        stock_code: 종목 코드 (6자리)
        db: SQLAlchemy 세션

    Returns:
        프롬프트에 삽입할 참고 자료 문자열. 데이터가 없으면 빈 문자열.
    """
    from app.models.stock import Stock
    from app.models.disclosure import Disclosure
    from app.models.securities_report import SecuritiesReport

    try:
        # 종목 ID 조회
        stock = db.query(Stock).filter(Stock.stock_code == stock_code).first()
        if not stock:
            return ""

        lines: list[str] = []

        # 기업 기본 정보 (항상 포함 — 공시/리포트 없을 때도 섹터 앵커링 역할)
        basic_parts: list[str] = []
        if stock.sector:
            basic_parts.append(f"섹터/업종: {stock.sector.name}")
        if stock.market:
            basic_parts.append(f"상장 시장: {stock.market}")
        if basic_parts:
            lines.append("## 기업 기본 정보")
            for part in basic_parts:
                lines.append(f"- {part}")

        # 최신 정기공시 보고서 (사업/분기/반기보고서) 최대 3건
        disclosures = (
            db.query(Disclosure)
            .filter(
                Disclosure.stock_id == stock.id,
                Disclosure.report_type == "정기공시",
            )
            .order_by(Disclosure.rcept_dt.desc())
            .limit(3)
            .all()
        )
        if disclosures:
            # 가장 최신 공시를 '현재 사업 내용'으로 강조 — 사업 전환 기업에서 stale한 섹터보다 우선
            latest = disclosures[0]
            latest_summary = (latest.ai_summary or "")[:600]
            lines.append("## 현재 사업 내용 (최신 공시 기준)")
            lines.append(
                f"- [{latest.rcept_dt}] {latest.report_name}"
                + (f"\n  {latest_summary}" if latest_summary else "")
            )
            if len(disclosures) > 1:
                lines.append("## 이전 공시 보고서")
                for d in disclosures[1:]:
                    summary = (d.ai_summary or "")[:300]
                    lines.append(f"- [{d.rcept_dt}] {d.report_name}" + (f": {summary}" if summary else ""))

        # 최근 1년간 발행된 애널리스트 리포트 최대 5건
        # 본문(content)이 있는 리포트를 우선 조회
        cutoff = datetime.now(timezone.utc) - timedelta(days=_REPORT_LOOKBACK_DAYS)
        reports_with_content = (
            db.query(SecuritiesReport)
            .filter(
                SecuritiesReport.stock_id == stock.id,
                SecuritiesReport.content.isnot(None),
                SecuritiesReport.published_at >= cutoff,
            )
            .order_by(SecuritiesReport.published_at.desc())
            .limit(5)
            .all()
        )
        reports_meta_only = (
            db.query(SecuritiesReport)
            .filter(
                SecuritiesReport.stock_id == stock.id,
                SecuritiesReport.content.is_(None),
                SecuritiesReport.published_at >= cutoff,
            )
            .order_by(SecuritiesReport.published_at.desc())
            .limit(5)
            .all()
        )

        # 본문 있는 리포트를 앞에, 없는 것을 뒤에 배치 (최대 5건 유지)
        all_reports = reports_with_content + reports_meta_only
        all_reports = all_reports[:5]

        # 본문 없는 경우 — 날짜 제한 없이 최근 5건 폴백
        if not all_reports:
            all_reports = (
                db.query(SecuritiesReport)
                .filter(SecuritiesReport.stock_id == stock.id)
                .order_by(SecuritiesReport.collected_at.desc())
                .limit(5)
                .all()
            )

        if all_reports:
            has_content = any(r.content for r in all_reports)
            if has_content:
                lines.append("## 애널리스트 리포트 (최근 1년, 투자포인트 핵심 요약)")
            else:
                lines.append("## 최신 애널리스트 리포트 (제목/의견 기준)")

            for r in all_reports:
                date_str = (
                    r.published_at.strftime("%Y.%m.%d")
                    if r.published_at
                    else "날짜미상"
                )
                price_str = f", 목표주가 {r.target_price:,}원" if r.target_price else ""
                opinion_str = f" ({r.opinion}{price_str})" if r.opinion else ""
                header = f"- [{date_str}] [{r.securities_firm}] {r.title}{opinion_str}"

                if r.content:
                    # 본문 중 핵심 부분만 포함 (최대 600자)
                    content_excerpt = r.content[:600].strip()
                    lines.append(f"{header}\n  [리포트 본문 요약] {content_excerpt}")
                else:
                    lines.append(header)

        return "\n".join(lines) if lines else ""

    except Exception as e:
        logger.warning(f"참고 자료 조회 실패 ({stock_code}): {e}")
        return ""


# @MX:ANCHOR: [AUTO] generate_keywords — 라우터와 스케줄러에서 호출되는 AI 키워드 생성 진입점
# @MX:REASON: 라우터(수동 트리거)와 스케줄러(자동 갱신) 2곳 이상에서 호출됨
async def generate_keywords(
    stock_code: str,
    company_name: str,
    existing_keywords: list[str],
    db: Session,
) -> dict[str, list[str]] | None:
    """AI를 사용하여 4개 카테고리별 투자 모니터링 키워드를 생성한다.

    사업보고서(공시)와 애널리스트 리포트 본문을 교차 참조하여 원론적 키워드가 아닌
    실제 투자포인트에 밀착한 키워드를 도출한다.

    Args:
        stock_code: 종목 코드 (6자리)
        company_name: 기업명
        existing_keywords: 이미 등록된 키워드 목록 (중복 제거용)
        db: SQLAlchemy 세션

    Returns:
        카테고리별 키워드 딕셔너리.
        AI 서비스 자체가 불가한 경우 None 반환.
        JSON 파싱 실패 등 부분 실패는 빈 카테고리를 포함한 dict 반환.
        예: {"product": [...], "competitor": [...], "upstream": [...], "market": [...]}
    """
    # 빈 응답 기본값
    empty_result: dict[str, list[str]] = {cat: [] for cat in _CATEGORIES}

    # DB에서 공시/리포트 컨텍스트 조회
    reference_context = _build_reference_context(stock_code, db)
    reference_section = (
        f"\n\n참고 자료 (기업 정보, 공시 보고서, 애널리스트 리포트 본문):\n{reference_context}\n"
        if reference_context
        else ""
    )

    prompt = f"""당신은 한국 주식 투자 전문가입니다.
종목 코드 {stock_code}, 기업명 '{company_name}'에 대한 투자 모니터링 키워드를 생성해주세요.{reference_section}

[키워드 생성 원칙]

1. 사업보고서 + 애널리스트 리포트 교차 참조
   - '현재 사업 내용 (최신 공시 기준)' 항목을 최우선 기준으로 삼으세요.
   - '애널리스트 리포트 본문 요약'이 있다면, 해당 리포트의 투자포인트·핵심 테마를 반드시 키워드에 반영하세요.
   - 공시에서 확인된 사실 + 애널리스트가 강조한 모멘텀을 결합하여 키워드를 도출하세요.
   - 애널리스트 리포트가 없을 경우, 사업보고서의 사업 내용과 전자공시에서 파악 가능한 핵심 팩트만 사용하세요.

2. 투자포인트 중심
   - "이 기업의 주가를 움직일 수 있는 요인은 무엇인가?"를 기준으로 키워드를 선정하세요.
   - 원론적·범용 키워드("데이터 보호", "AI 기반 솔루션", "디지털 전환", "클라우드 서비스" 등)는 절대 생성하지 마세요.
   - 해당 기업 고유의 제품명, 기술명, 고객사명, 공급망 업체명, 시장 동향을 구체적으로 사용하세요.

3. 현재 사업 기준
   - 과거에 영위했으나 현재 중단된 사업의 키워드는 생성하지 마세요.
   - 기업명만으로 업종을 추측하지 말고, 반드시 위 참고 자료를 기준으로 하세요.

4. 필수 포함 키워드 (반드시 아래 3가지 유형의 키워드를 각 카테고리에 포함하세요)
   - 기업 주력 제품명: 기업이 실제 영위하는 주력 제품/서비스의 구체적인 명칭 (예: "스판덱스", "LNG선", "OLED 패널")
   - 이익 핵심 키팩터: 이 기업의 매출·이익을 직접 결정하는 핵심 요소 (예: "수주잔고", "스프레드", "ASP", "가동률", "환율", "원자재 가격")
   - 기업명: '{company_name}'을 product 카테고리에 반드시 1개 포함

⚠️ 중요 제약 사항:
- 섹터/업종은 보조 참고용이며, 기업이 사업을 전환한 경우 공시 내용이 우선입니다.
- 해당 기업의 실제 사업과 무관한 범용 키워드는 절대 생성하지 마세요.

다음 4개 카테고리별로 각 3~5개의 한국어 키워드를 제안하세요:
- product: 이 기업의 주요 제품/서비스·기술 관련 키워드 (기업명 + 주력 제품명 필수 포함)
- competitor: 직접 경쟁사 및 경쟁 관계 키워드 (기업명 또는 경쟁 구도)
- upstream: 후방산업 관련 키워드 (이 기업에 원자재·부품·소재를 공급하는 업체 및 공급망 체인)
- market: 산업 동향, 규제, 시장 환경 키워드 + 이익 핵심 키팩터 (투자포인트와 직결된 것만)

이미 등록된 키워드(제외 필요): {existing_keywords if existing_keywords else '없음'}

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "product": ["키워드1", "키워드2", "키워드3"],
  "competitor": ["키워드1", "키워드2", "키워드3"],
  "upstream": ["키워드1", "키워드2", "키워드3"],
  "market": ["키워드1", "키워드2", "키워드3"]
}}"""

    try:
        response = await ask_ai(prompt)
        if not response:
            logger.warning(f"AI 키워드 생성 응답 없음: {company_name}({stock_code})")
            return empty_result

        # JSON 파싱 (마크다운 코드 블록 제거)
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # 첫 줄(```json 또는 ```) 및 마지막 줄(```) 제거
            cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

        data = json.loads(cleaned)

        result: dict[str, list[str]] = {}
        existing_set = set(existing_keywords)

        for cat in _CATEGORIES:
            raw_list = data.get(cat, [])
            if not isinstance(raw_list, list):
                result[cat] = []
                continue
            # 기존 키워드 중복 제거, 빈 문자열 제거, 100자 초과 제거
            filtered = [
                kw for kw in raw_list
                if isinstance(kw, str) and kw.strip() and kw.strip() not in existing_set and len(kw.strip()) <= 100
            ]
            result[cat] = [kw.strip() for kw in filtered]

        return result

    except json.JSONDecodeError as e:
        logger.error(f"AI 키워드 생성 JSON 파싱 실패: {e} | 응답: {response[:200] if response else 'None'}")
        return empty_result
    except Exception as e:
        logger.error(f"AI 키워드 생성 예외: {e}")
        return empty_result
