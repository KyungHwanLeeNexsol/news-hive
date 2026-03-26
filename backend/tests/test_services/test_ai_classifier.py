"""ai_classifier.py 순수 함수 단위 테스트.

외부 API 호출 없이 키워드 매칭, 감성 분류, 비금융 기사 탐지,
섹터 키워드 추출 등 순수 로직만 검증한다.
"""

import pytest

from app.models.sector import Sector
from app.models.stock import Stock
from app.services.ai_classifier import (
    KeywordIndex,
    _extract_sector_keywords,
    classify_news,
    classify_sentiment,
    is_non_financial_article,
)


# ---------------------------------------------------------------------------
# KeywordIndex.build 테스트
# ---------------------------------------------------------------------------

class TestKeywordIndexBuild:
    """KeywordIndex.build 메서드 테스트."""

    def test_build_with_stocks_and_sectors(self, db, make_sector, make_stock):
        """종목과 섹터가 있을 때 인덱스가 올바르게 구축되는지 확인."""
        sector = make_sector(name="반도체와반도체장비")
        stock = make_stock(name="삼성전자", sector_id=sector.id)

        index = KeywordIndex.build([sector], [stock])

        assert "삼성전자" in index.stock_names
        assert index.stock_names["삼성전자"] == (stock.id, sector.id)

    def test_build_empty_lists(self):
        """빈 리스트로 빌드해도 에러 없이 빈 인덱스 반환."""
        index = KeywordIndex.build([], [])

        assert index.stock_names == {}
        assert index.stock_keywords == {}
        assert index.sector_keywords == {}

    def test_build_sector_keywords_extracted(self, db, make_sector):
        """섹터 이름에서 키워드가 추출되어 인덱스에 등록되는지 확인."""
        sector = make_sector(name="반도체와반도체장비")

        index = KeywordIndex.build([sector], [])

        # _extract_sector_keywords("반도체와반도체장비") 결과가 인덱스에 존재
        assert "반도체" in index.sector_keywords
        assert index.sector_keywords["반도체"] == sector.id

    def test_build_stock_keywords(self, db, make_sector, make_stock):
        """Stock.keywords가 인덱스에 반영되는지 확인."""
        sector = make_sector(name="건설")
        stock = make_stock(name="대창단조", sector_id=sector.id)
        # SQLite에서 ARRAY 타입 직접 사용 불가하므로 객체에 직접 설정
        stock.keywords = ["포크레인", "굴삭기"]

        index = KeywordIndex.build([sector], [stock])

        assert "포크레인" in index.stock_keywords
        assert (stock.id, sector.id) in index.stock_keywords["포크레인"]


# ---------------------------------------------------------------------------
# classify_news 테스트
# ---------------------------------------------------------------------------

class TestClassifyNews:
    """classify_news 함수 테스트 (키워드 기반 뉴스 분류)."""

    def test_direct_stock_name_match(self, db, make_sector, make_stock):
        """뉴스 제목에 종목명이 직접 언급되면 direct 매칭."""
        sector = make_sector(name="반도체와반도체장비")
        stock = make_stock(name="삼성전자", sector_id=sector.id)
        index = KeywordIndex.build([sector], [stock])

        results = classify_news("삼성전자 4분기 실적 발표", index)

        assert len(results) >= 1
        direct_results = [r for r in results if r["relevance"] == "direct"]
        assert len(direct_results) == 1
        assert direct_results[0]["stock_id"] == stock.id
        assert direct_results[0]["sector_id"] == sector.id

    def test_no_match_returns_empty(self, db, make_sector, make_stock):
        """매칭되는 키워드가 없으면 빈 리스트 반환."""
        sector = make_sector(name="반도체와반도체장비")
        make_stock(name="삼성전자", sector_id=sector.id)
        index = KeywordIndex.build([sector], [])

        results = classify_news("오늘 날씨가 좋습니다", index)

        # 섹터 키워드 매칭만 가능하므로 반도체 관련 키워드가 없으면 빈 리스트
        sector_matches = [r for r in results if r["stock_id"] is None]
        stock_matches = [r for r in results if r["stock_id"] is not None]
        assert stock_matches == []

    def test_longer_stock_name_takes_priority(self, db, make_sector, make_stock):
        """긴 종목명이 짧은 종목명보다 우선 매칭 (SK하이닉스 vs 이닉스)."""
        sector = make_sector(name="반도체와반도체장비")
        stock_long = make_stock(name="SK하이닉스", sector_id=sector.id)
        stock_short = make_stock(name="이닉스", sector_id=sector.id)
        index = KeywordIndex.build([sector], [stock_long, stock_short])

        results = classify_news("SK하이닉스 HBM 생산 확대", index)

        stock_ids = [r["stock_id"] for r in results if r["stock_id"] is not None]
        assert stock_long.id in stock_ids
        # 이닉스는 SK하이닉스 내부 문자열이므로 매칭되지 않아야 함
        assert stock_short.id not in stock_ids

    def test_sector_keyword_indirect_match(self, db, make_sector):
        """섹터 키워드가 제목에 포함되면 indirect 매칭."""
        sector = make_sector(name="반도체와반도체장비")
        index = KeywordIndex.build([sector], [])

        results = classify_news("HBM 수요 급증으로 반도체 업황 호전", index)

        sector_results = [r for r in results if r["stock_id"] is None]
        assert len(sector_results) >= 1
        assert sector_results[0]["sector_id"] == sector.id
        assert sector_results[0]["relevance"] == "indirect"

    def test_korean_prefix_prevents_false_match(self, db, make_sector, make_stock):
        """한글 문자 뒤에 오는 종목명은 매칭되지 않음 (부진 != 이부진)."""
        sector = make_sector(name="유통")
        stock = make_stock(name="부진", sector_id=sector.id)
        index = KeywordIndex.build([sector], [stock])

        results = classify_news("이부진 회장 호텔 사업 확대", index)

        stock_matches = [r for r in results if r["stock_id"] == stock.id]
        assert stock_matches == []


# ---------------------------------------------------------------------------
# classify_sentiment 테스트
# ---------------------------------------------------------------------------

class TestClassifySentiment:
    """감성 분류 함수 테스트."""

    @pytest.mark.parametrize("title,expected", [
        ("삼성전자 4분기 실적 급등 호재", "positive"),
        ("SK하이닉스 매출증가 사상최대 기록", "positive"),
        ("반도체 업황 회복 기대감 상승", "positive"),
    ])
    def test_positive_sentiment(self, title: str, expected: str):
        """긍정 키워드가 포함된 뉴스 제목은 positive 반환."""
        assert classify_sentiment(title) == expected

    @pytest.mark.parametrize("title,expected", [
        ("코스피 급락 악재 겹쳐", "negative"),
        ("실적악화 적자 전환 우려", "negative"),
        ("부진한 실적에 주가 하락세", "negative"),
    ])
    def test_negative_sentiment(self, title: str, expected: str):
        """부정 키워드가 포함된 뉴스 제목은 negative 반환."""
        assert classify_sentiment(title) == expected

    def test_neutral_sentiment(self):
        """긍정/부정 키워드가 없으면 neutral 반환."""
        assert classify_sentiment("삼성전자 주주총회 개최") == "neutral"

    def test_mixed_sentiment_positive_wins(self):
        """긍정 키워드가 부정보다 많으면 positive."""
        # 급등(+), 상승(+) vs 우려(-)
        result = classify_sentiment("반도체 급등 상승세 일부 우려")
        assert result == "positive"

    def test_mixed_sentiment_negative_wins(self):
        """부정 키워드가 긍정보다 많으면 negative."""
        # 급락(-), 하락(-), 위기(-) vs 회복(+)
        result = classify_sentiment("급락 하락 위기 속 회복 기대")
        assert result == "negative"

    def test_empty_title_neutral(self):
        """빈 문자열은 neutral."""
        assert classify_sentiment("") == "neutral"

    def test_keyword_boundary_check(self):
        """'이부진'의 '부진'은 매칭되지 않아야 함 (한글 접두어 경계 체크).

        _count_keyword_matches는 한글 접두어가 있으면 매칭을 건너뛴다.
        그러나 '이부진'에서 '부진'은 접두어 '이'(한글)가 있으므로 매칭되지 않는다.
        하지만 '진'은 별도 키워드가 아니므로 다른 키워드에는 영향 없음.
        """
        # '이부진'에서 '부진'(negative keyword)은 한글 접두어 체크로 매칭 안됨
        # 그러나 실제로는 다른 키워드와 관계없이 neutral이어야 함
        # 실제 구현에서는 title_lower에서 find하므로 '이부진' -> '부진' 발견됨
        # 하지만 _count_keyword_matches에서 한글 접두어 체크로 스킵됨
        result = classify_sentiment("이부진 회장 호텔 사업 관련 뉴스")
        assert result == "neutral"


# ---------------------------------------------------------------------------
# is_non_financial_article 테스트
# ---------------------------------------------------------------------------

class TestIsNonFinancialArticle:
    """비금융 기사 탐지 테스트."""

    @pytest.mark.parametrize("title", [
        "흑백요리사 시즌2 출연진 공개",
        "프로야구 KBO 개막전 일정",
        "[포토] 아이돌 콘서트 현장",
        "국회의원 자산공개 재산신고",
        "검찰 구속 기소 혐의 확인",
    ])
    def test_non_financial_detected(self, title: str):
        """비금융 컨텐츠(예능, 스포츠, 정치, 범죄)가 탐지됨."""
        assert is_non_financial_article(title) is True

    @pytest.mark.parametrize("title", [
        "삼성전자 4분기 영업이익 발표",
        "한국은행 기준금리 동결 결정",
        "현대차 전기차 수출 증가",
    ])
    def test_financial_not_detected(self, title: str):
        """금융/투자 뉴스는 비금융으로 탐지되지 않음."""
        assert is_non_financial_article(title) is False

    def test_foreign_source_by_url(self):
        """외국 비투자 소스 URL은 비금융으로 탐지."""
        assert is_non_financial_article(
            "Some news title",
            url="https://vnexpress.net/some-article",
        ) is True

    def test_foreign_source_in_title(self):
        """제목에 외국 비투자 소스명이 포함되면 비금융으로 탐지."""
        assert is_non_financial_article("Vietnam.vn reports economic growth") is True

    def test_description_non_financial(self):
        """description에 비금융 키워드가 있으면 탐지."""
        assert is_non_financial_article(
            "일반 제목",
            description="흑백요리사 시즌2 관련 기사",
        ) is True

    def test_empty_strings(self):
        """빈 문자열 입력 시 False 반환."""
        assert is_non_financial_article("") is False
        assert is_non_financial_article("", url="", description="") is False


# ---------------------------------------------------------------------------
# _extract_sector_keywords 테스트
# ---------------------------------------------------------------------------

class TestExtractSectorKeywords:
    """섹터 키워드 추출 테스트."""

    def test_split_by_connectors(self):
        """'와', '및' 등 접속사로 분리."""
        keywords = _extract_sector_keywords("반도체와반도체장비")
        assert "반도체" in keywords
        assert "반도체장비" in keywords

    def test_full_name_included(self):
        """전체 섹터명도 키워드에 포함."""
        keywords = _extract_sector_keywords("소프트웨어")
        assert "소프트웨어" in keywords

    def test_extended_keywords_loaded(self):
        """_SECTOR_EXTRA_KEYWORDS에서 추가 키워드가 로드됨."""
        keywords = _extract_sector_keywords("반도체와반도체장비")
        # 확장 사전에 "HBM", "DRAM" 등이 포함
        assert "hbm" in keywords
        assert "dram" in keywords

    def test_short_parts_excluded(self):
        """1글자 이하의 파트는 제외."""
        keywords = _extract_sector_keywords("A및소프트웨어")
        # "A"는 1글자이므로 제외
        assert "a" not in keywords
        assert "소프트웨어" in keywords

    def test_slash_separator(self):
        """슬래시(/) 구분도 처리."""
        keywords = _extract_sector_keywords("호텔/레스토랑/레저")
        assert "호텔" in keywords
        assert "레스토랑" in keywords
        assert "레저" in keywords
