"""ai_classifier.py 순수 함수 단위 테스트.

��부 API 호출 없이 키워드 매칭, 감성 분류, 비금융 기사 탐지,
섹터 키워드 추출, 관련성 점수, 소스 신뢰도 등 순수 로직만 검증한다.
"""

import pytest

from app.services.ai_classifier import (
    GLOBAL_KEYWORD_SECTOR_MAP,
    KeywordIndex,
    _extract_sector_keywords,
    calculate_relevance_score,
    classify_news,
    classify_sentiment,
    detect_global_impact,
    get_source_credibility,
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
        [r for r in results if r["stock_id"] is None]
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

    def test_mixed_sentiment_both_present(self):
        """긍정+부정 키워드가 모두 있으면 mixed (6단계 확장)."""
        # 급등(+), 상승(+) vs 우려(-)
        result = classify_sentiment("반도체 급등 상승세 일부 우려")
        assert result == "mixed"

    def test_mixed_sentiment_negative_majority(self):
        """부정 키워드가 긍정보다 많아도 양쪽 모두 있으면 mixed."""
        # 급락(-), 하락(-), 위기(-) vs 회복(+)
        result = classify_sentiment("급락 하락 위기 속 회복 기대")
        assert result == "mixed"

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


# ---------------------------------------------------------------------------
# SPEC-NEWS-002 Phase 2: 감성 6단계 확장 테스트
# ---------------------------------------------------------------------------

class TestClassifySentiment6Level:
    """6단계 감성 분류 테스트 (strong_positive/positive/mixed/neutral/negative/strong_negative)."""

    def test_strong_positive(self):
        """강한 긍정 키워드 + pos_count >= 3이면 strong_positive."""
        title = "삼성전자 사상최대 실적 급등 호실적 매출증가 도약"
        result = classify_sentiment(title)
        assert result == "strong_positive"

    def test_strong_negative(self):
        """강한 부정 키워드 + neg_count >= 3이면 strong_negative."""
        title = "XX그룹 횡령 의혹 급락 하락 위기 침체"
        result = classify_sentiment(title)
        assert result == "strong_negative"

    def test_mixed_both_present(self):
        """긍정+부정 키워드 공존 시 mixed."""
        result = classify_sentiment("급등 기대감 반면 하락 우려도")
        assert result == "mixed"

    def test_positive_only(self):
        """긍정 키워드만 있으면 positive."""
        result = classify_sentiment("삼성전자 호실적 기대감")
        assert result == "positive"

    def test_negative_only(self):
        """부정 키워드만 있으면 negative."""
        result = classify_sentiment("코스피 급락 악재 겹쳐")
        assert result == "negative"

    def test_neutral_no_keywords(self):
        """키워드 없으면 neutral."""
        result = classify_sentiment("삼성전자 주주총회 개최")
        assert result == "neutral"

    def test_reversal_pattern_converts_to_mixed(self):
        """제목은 부정이지만 본문에 반전 패턴 + 긍정 키워드가 있으면 mixed."""
        title = "코스피 급락 악재"
        content = "코스피가 급락했다. 그러나 일부 종목은 호실적으로 상승 기대감이 있다."
        result = classify_sentiment(title, content=content)
        assert result == "mixed"

    def test_no_reversal_stays_negative(self):
        """본문에 반전 패턴이 없으면 부정 유지."""
        title = "급락 악재"
        content = "시장이 급락했다. 투자자들은 우려를 표하고 있다."
        result = classify_sentiment(title, content=content)
        # 급락(-) + 악재(-) + 우려(-) = neg만 있으므로 negative
        assert result == "negative"


# ---------------------------------------------------------------------------
# SPEC-NEWS-002 Phase 2: 소스 신뢰도 테스트 (TASK-006)
# ---------------------------------------------------------------------------

class TestSourceCredibility:
    """소스 신뢰도 가중치 테스트."""

    def test_tier1_exact_match(self):
        """Tier 1 경제지 정확 매칭."""
        assert get_source_credibility("한국경제") == 1.0
        assert get_source_credibility("매일경제") == 1.0

    def test_tier2_match(self):
        """Tier 2 종합 일간지."""
        assert get_source_credibility("\uc870\uc120\uc77c\ubcf4") == 0.85

    def test_tier3_match(self):
        """Tier 3 통신사/방송."""
        assert get_source_credibility("연합뉴스") == 0.7
        assert get_source_credibility("JTBC") == 0.7

    def test_tier4_match(self):
        """Tier 4 전문지/온라인."""
        assert get_source_credibility("더벨") == 0.5

    def test_unknown_source_default(self):
        """알 수 없는 소스는 기본값 0.5."""
        assert get_source_credibility("블로그뉴스") == 0.5

    def test_empty_source(self):
        """빈 소스는 기본값 0.5."""
        assert get_source_credibility("") == 0.5

    def test_partial_match(self):
        """부분 문자열 매칭 (소스명에 키가 포함)."""
        assert get_source_credibility("한국경제TV") == 1.0

    def test_alias_match(self):
        """별칭 매핑 (한경 -> 한국경제)."""
        assert get_source_credibility("한경") == 1.0


# ---------------------------------------------------------------------------
# SPEC-NEWS-002 Phase 2: 관련성 점수 테스트 (TASK-004)
# ---------------------------------------------------------------------------

class TestRelevanceScore:
    """관련성 점수 계산 테스트."""

    def test_title_stock_name_match(self):
        """제목에 종목명이 포함되면 +40 (소스 신뢰도 1.0 기준)."""
        score = calculate_relevance_score(
            title="삼성전자 4분기 실적 발표",
            description=None,
            stock_name="삼성전자",
            sector_name=None,
            source="한국경제",
        )
        # 종목명 매칭(+40) + 금융 키워드 '실적'(+15) = 55 * 1.0 = 55
        assert score >= 40

    def test_description_stock_name_match(self):
        """설명에도 종목명이 포함되면 추가 +20."""
        score = calculate_relevance_score(
            title="삼성전자 실적 발표",
            description="삼성전자가 4분기 실적을 발표했다",
            stock_name="삼성전자",
            sector_name=None,
            source="한국경제",
        )
        # 종목명 제목(+40) + 종목명 설명(+20) + 금융 '실적'(+15) = 75
        assert score >= 60

    def test_financial_keyword_bonus(self):
        """금융 키워드가 있으면 +15."""
        score = calculate_relevance_score(
            title="삼성전자 영업이익 발표",
            description=None,
            stock_name="삼성전자",
            sector_name=None,
            source="한국경제",
        )
        # 종목명 매칭(+40) + 금융 키워드(+15) = 55 * 1.0 = 55
        assert score >= 55

    def test_sector_keyword_bonus(self):
        """섹터 키워드 매칭 시 +15."""
        score = calculate_relevance_score(
            title="반도체 업황 호전 전망",
            description=None,
            stock_name=None,
            sector_name="반도체와반도체장비",
            source="한국경제",
        )
        # 섹터 키워드(+15) * 1.0 = 15
        assert score >= 15

    def test_non_financial_penalty(self):
        """비금융 기사 패턴 감지 시 -30."""
        score = calculate_relevance_score(
            title="삼성전자 흑백요리사 시즌2 출연",
            description=None,
            stock_name="삼성전자",
            sector_name=None,
            source="한국경제",
        )
        # 종목명 매칭(+40) - 비금융 패턴(-30) = 10 * 1.0 = 10
        assert score <= 15

    def test_ai_classified_base_score(self):
        """AI 분류 기사는 기본 +30점."""
        score = calculate_relevance_score(
            title="신재생에너지 정책 변화",
            description=None,
            stock_name=None,
            sector_name=None,
            is_ai_classified=True,
        )
        assert score >= 15  # 30 * 0.5(기본 신뢰도) = 15

    def test_credibility_weight_applied(self):
        """소스 신뢰도 가중치가 점수에 반영됨."""
        score_high = calculate_relevance_score(
            title="삼성전자 실적 발표",
            description=None,
            stock_name="삼성전자",
            sector_name=None,
            source="한국경제",
        )
        score_low = calculate_relevance_score(
            title="삼성전자 실적 발표",
            description=None,
            stock_name="삼성전자",
            sector_name=None,
            source="알수없는매체",
        )
        assert score_high > score_low

    def test_score_clamped_to_0_100(self):
        """점수는 0-100 범위로 클램핑."""
        score = calculate_relevance_score(
            title="",
            description=None,
            stock_name=None,
            sector_name=None,
        )
        assert 0 <= score <= 100


# ---------------------------------------------------------------------------
# SPEC-NEWS-002 Phase 3: 글로벌 뉴스 영향 분석 테스트 (TASK-011)
# ---------------------------------------------------------------------------

class TestGlobalKeywordSectorMap:
    """GLOBAL_KEYWORD_SECTOR_MAP 상수 테스트."""

    def test_map_not_empty(self):
        """매핑 테이블이 비어있지 않아야 함."""
        assert len(GLOBAL_KEYWORD_SECTOR_MAP) > 0

    def test_semiconductor_keywords_exist(self):
        """반도체 관련 키워드가 매핑에 포함."""
        assert "semiconductor" in GLOBAL_KEYWORD_SECTOR_MAP
        assert "Nvidia" in GLOBAL_KEYWORD_SECTOR_MAP
        assert "DRAM" in GLOBAL_KEYWORD_SECTOR_MAP

    def test_all_values_are_lists(self):
        """모든 값이 문자열 리스트여야 함."""
        for key, sectors in GLOBAL_KEYWORD_SECTOR_MAP.items():
            assert isinstance(sectors, list), f"{key}의 값이 리스트가 아님"
            assert all(isinstance(s, str) for s in sectors)


class TestDetectGlobalImpact:
    """글로벌 뉴스 영향 감지 테스트."""

    def test_semiconductor_keyword_detected(self):
        """반도체 키워드가 영문 소스에서 감지됨."""
        results = detect_global_impact(
            "Nvidia reports record revenue on AI chip demand",
            source="yahoo",
        )
        assert len(results) >= 1
        keywords = [r["keyword"] for r in results]
        assert "Nvidia" in keywords

    def test_multiple_keywords_detected(self):
        """여러 키워드가 동시에 감지됨."""
        results = detect_global_impact(
            "Samsung DRAM production boost helps semiconductor market",
            source="google",
        )
        keywords = [r["keyword"] for r in results]
        assert len(keywords) >= 2  # Samsung + DRAM + semiconductor 등

    def test_non_global_source_returns_empty(self):
        """글로벌 소스가 아닌 경우 빈 리스트 반환."""
        results = detect_global_impact(
            "Nvidia reports record revenue",
            source="naver",
        )
        assert results == []

    def test_no_matching_keywords_returns_empty(self):
        """매칭되는 키워드가 없으면 빈 리스트 반환."""
        results = detect_global_impact(
            "Local weather forecast for today",
            source="yahoo",
        )
        assert results == []

    def test_result_structure(self):
        """반환 구조가 올바른지 확인."""
        results = detect_global_impact("TSMC earnings beat", source="bloomberg")
        assert len(results) >= 1
        for r in results:
            assert "keyword" in r
            assert "sectors" in r
            assert "is_pre_market" in r
            assert isinstance(r["sectors"], list)
            assert isinstance(r["is_pre_market"], bool)

    def test_short_keyword_word_boundary(self):
        """짧은 키워드(EV, LG, SK)는 단어 경계에서만 매칭."""
        # "EV" 단독으로 있을 때
        results_match = detect_global_impact("New EV sales record", source="yahoo")
        ev_results = [r for r in results_match if r["keyword"] == "EV"]
        assert len(ev_results) == 1

        # "EVERY"에 포함된 "EV"는 매칭되지 않아야 함
        results_no_match = detect_global_impact("EVERY day is good", source="yahoo")
        ev_results = [r for r in results_no_match if r["keyword"] == "EV"]
        assert len(ev_results) == 0

    def test_case_insensitive_matching(self):
        """대소문자 구분 없이 매칭."""
        results = detect_global_impact("nvidia stock surges", source="yahoo")
        keywords = [r["keyword"] for r in results]
        assert "Nvidia" in keywords

    def test_empty_source(self):
        """빈 소스는 글로벌 소스로 판별되지 않음."""
        results = detect_global_impact("Nvidia stock up", source="")
        assert results == []

    def test_oil_keywords_detected(self):
        """정유/화학 관련 글로벌 키워드 감지."""
        results = detect_global_impact("OPEC cuts production targets", source="reuters")
        keywords = [r["keyword"] for r in results]
        assert "OPEC" in keywords
        sectors = results[0]["sectors"]
        assert "정유" in sectors

    def test_fed_rate_detected(self):
        """금융 관련 글로벌 키워드 감지."""
        results = detect_global_impact(
            "Federal Reserve holds interest rate steady",
            source="bloomberg",
        )
        keywords = [r["keyword"] for r in results]
        assert any(k in keywords for k in ["Federal Reserve", "interest rate"])
