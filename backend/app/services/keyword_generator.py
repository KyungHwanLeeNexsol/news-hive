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
            latest_summary = (latest.ai_summary or "")[:500]
            lines.append("## 현재 사업 내용 (최신 공시 기준)")
            lines.append(
                f"- [{latest.rcept_dt}] {latest.report_name}"
                + (f"\n  {latest_summary}" if latest_summary else "")
            )
            if len(disclosures) > 1:
                lines.append("## 이전 공시 보고서")
                for d in disclosures[1:]:
                    summary = (d.ai_summary or "")[:200]
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
        f"\n\n참고 자료 (기업 정보, 공시 보고서, 애널리스트 리포트):\n{reference_context}\n"
        if reference_context
        else ""
    )

    prompt = f"""당신은 한국 주식 투자 전문가입니다.
종목 코드 {stock_code}, 기업명 '{company_name}'에 대한 투자 모니터링 키워드를 생성해주세요.{reference_section}
위 참고 자료를 바탕으로, 해당 기업의 **현재** 사업 영역에 해당하는 키워드만 도출하세요.
전자공시에 공시된 최근 결산 사업보고서, 분기보고서, 반기보고서와 애널리스트 분석 보고서를 대조해 핵심 키워드를 생성하세요.

⚠️ 중요 제약 사항:
- '현재 사업 내용 (최신 공시 기준)' 항목이 있으면 해당 내용을 최우선으로 참조하세요. 섹터/업종은 보조 참고용이며, 기업이 사업을 전환한 경우 공시 내용이 우선입니다.
- 반드시 현재 수행 중인 사업에 직접 관련된 구체적인 키워드만 생성하세요. 과거에 영위했으나 현재 중단된 사업의 키워드는 생성하지 마세요.
- 해당 기업의 실제 사업과 무관한 범용 IT·AI·금융·데이터 키워드(예: "데이터 보호", "AI 기반 솔루션", "디지털 전환", "클라우드 서비스")는 절대 생성하지 마세요.
- 기업명만으로 업종을 추측하지 말고, 반드시 위 참고 자료를 기준으로 하세요.

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
