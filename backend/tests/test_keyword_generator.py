"""SPEC-FOLLOW-001 AI 키워드 생성 서비스 단위 테스트.

ask_ai()를 Mock으로 대체하여 외부 AI 호출 없이 생성 로직을 검증한다.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.keyword_generator import generate_keywords


# ---------------------------------------------------------------------------
# 테스트 헬퍼
# ---------------------------------------------------------------------------


def _make_ai_response(data: dict) -> str:
    """AI 응답 형식의 JSON 문자열을 생성한다."""
    return json.dumps(data, ensure_ascii=False)


def _make_db_mock() -> MagicMock:
    """SQLAlchemy 세션 Mock 생성."""
    return MagicMock()


# ---------------------------------------------------------------------------
# generate_keywords 테스트
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_keywords_success() -> None:
    """정상 AI 응답 시 4개 카테고리 키워드 딕셔너리를 반환한다."""
    ai_response = _make_ai_response({
        "product": ["갤럭시", "반도체", "DRAM"],
        "competitor": ["SK하이닉스", "TSMC"],
        "upstream": ["실리콘", "포토레지스트"],
        "market": ["반도체 규제", "메모리 수요"],
    })

    with patch("app.services.keyword_generator.ask_ai", new=AsyncMock(return_value=ai_response)):
        result = await generate_keywords(
            stock_code="005930",
            company_name="삼성전자",
            existing_keywords=[],
            db=_make_db_mock(),
        )

    assert set(result.keys()) == {"product", "competitor", "upstream", "market"}
    assert "갤럭시" in result["product"]
    assert "SK하이닉스" in result["competitor"]
    assert len(result["market"]) == 2


@pytest.mark.asyncio
async def test_generate_keywords_ai_failure() -> None:
    """AI가 빈 응답을 반환하면 각 카테고리에 빈 리스트를 반환한다."""
    with patch("app.services.keyword_generator.ask_ai", new=AsyncMock(return_value=None)):
        result = await generate_keywords(
            stock_code="005930",
            company_name="삼성전자",
            existing_keywords=[],
            db=_make_db_mock(),
        )

    # 모든 카테고리가 빈 리스트여야 한다
    assert result == {"product": [], "competitor": [], "upstream": [], "market": []}


@pytest.mark.asyncio
async def test_generate_keywords_deduplication() -> None:
    """existing_keywords에 이미 있는 키워드는 결과에서 제외한다."""
    ai_response = _make_ai_response({
        "product": ["갤럭시", "반도체", "DRAM"],  # "반도체"는 기존에 있음
        "competitor": ["SK하이닉스"],
        "upstream": [],
        "market": [],
    })

    with patch("app.services.keyword_generator.ask_ai", new=AsyncMock(return_value=ai_response)):
        result = await generate_keywords(
            stock_code="005930",
            company_name="삼성전자",
            existing_keywords=["반도체"],  # 중복 키워드
            db=_make_db_mock(),
        )

    # "반도체"는 기존 키워드이므로 제외되어야 한다
    assert "반도체" not in result["product"]
    assert "갤럭시" in result["product"]
    assert "DRAM" in result["product"]


@pytest.mark.asyncio
async def test_generate_keywords_invalid_json() -> None:
    """AI가 JSON 파싱 불가 응답을 반환하면 빈 딕셔너리를 반환한다."""
    with patch(
        "app.services.keyword_generator.ask_ai",
        new=AsyncMock(return_value="이것은 유효하지 않은 JSON 응답입니다."),
    ):
        result = await generate_keywords(
            stock_code="005930",
            company_name="삼성전자",
            existing_keywords=[],
            db=_make_db_mock(),
        )

    # JSON 파싱 실패 시 모든 카테고리 빈 리스트
    assert result == {"product": [], "competitor": [], "upstream": [], "market": []}


@pytest.mark.asyncio
async def test_generate_keywords_markdown_code_block() -> None:
    """AI가 마크다운 코드 블록으로 응답을 감쌌을 때 올바르게 파싱한다."""
    data = {
        "product": ["갤럭시"],
        "competitor": ["애플"],
        "upstream": ["실리콘"],
        "market": ["스마트폰 시장"],
    }
    # 마크다운 코드 블록으로 감싼 응답
    markdown_response = f"```json\n{json.dumps(data, ensure_ascii=False)}\n```"

    with patch(
        "app.services.keyword_generator.ask_ai",
        new=AsyncMock(return_value=markdown_response),
    ):
        result = await generate_keywords(
            stock_code="005930",
            company_name="삼성전자",
            existing_keywords=[],
            db=_make_db_mock(),
        )

    assert "갤럭시" in result["product"]
    assert "애플" in result["competitor"]


@pytest.mark.asyncio
async def test_generate_keywords_exception_handling() -> None:
    """AI 호출 중 예외 발생 시 빈 딕셔너리를 반환하고 예외를 전파하지 않는다."""
    with patch(
        "app.services.keyword_generator.ask_ai",
        new=AsyncMock(side_effect=RuntimeError("AI 서비스 오류")),
    ):
        result = await generate_keywords(
            stock_code="005930",
            company_name="삼성전자",
            existing_keywords=[],
            db=_make_db_mock(),
        )

    # 예외가 발생해도 빈 결과를 반환하고 호출자에게 전파하지 않아야 한다
    assert result == {"product": [], "competitor": [], "upstream": [], "market": []}
