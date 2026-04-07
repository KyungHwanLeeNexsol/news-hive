"""AI 키워드 생성 서비스 (SPEC-FOLLOW-001).

Gemini/Z.AI를 사용하여 팔로잉 종목의 투자 모니터링 키워드를 자동 생성한다.
"""

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.services.ai_client import ask_ai

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 지원하는 키워드 카테고리
_CATEGORIES = ("product", "competitor", "upstream", "market")


def _build_reference_context(stock_code: str, db: Session) -> str:
    """DB에서 최신 공시 보고서 및 애널리스트 리포트를 조회하여 컨텍스트 문자열을 반환한다.

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
            lines.append("## 최신 공시 보고서")
            for d in disclosures:
                summary = (d.ai_summary or "")[:300]
                lines.append(f"- [{d.rcept_dt}] {d.report_name}" + (f": {summary}" if summary else ""))

        # 최신 애널리스트 리포트 최대 5건
        reports = (
            db.query(SecuritiesReport)
            .filter(SecuritiesReport.stock_id == stock.id)
            .order_by(SecuritiesReport.collected_at.desc())
            .limit(5)
            .all()
        )
        if reports:
            lines.append("## 최신 애널리스트 리포트")
            for r in reports:
                price_str = f", 목표주가 {r.target_price:,}원" if r.target_price else ""
                opinion_str = f" ({r.opinion}{price_str})" if r.opinion else ""
                lines.append(f"- [{r.securities_firm}] {r.title}{opinion_str}")

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
        f"\n\n참고 자료 (최신 공시 보고서 및 애널리스트 리포트):\n{reference_context}\n"
        if reference_context
        else ""
    )

    prompt = f"""당신은 한국 주식 투자 전문가입니다.
종목 코드 {stock_code}, 기업명 '{company_name}'에 대한 투자 모니터링 키워드를 생성해주세요.{reference_section}
위 참고 자료(공시 보고서, 애널리스트 리포트)를 대조·분석하여, 해당 기업의 현재 핵심 이슈와 투자 포인트를 반영한 키워드를 도출하세요.
자료가 없는 경우 기업과 산업에 대한 전문 지식을 활용하세요.

다음 4개 카테고리별로 각 3~5개의 한국어 키워드를 제안하세요:
- product: 이 기업의 주요 제품/서비스 관련 키워드
- competitor: 경쟁사 및 경쟁 관계 키워드
- upstream: 후방산업 관련 키워드 (이 기업에 원자재·부품·소재를 공급하는 업체 및 공급망 체인)
- market: 산업 동향, 규제, 시장 환경 키워드

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
