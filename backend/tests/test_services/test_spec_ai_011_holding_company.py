"""SPEC-AI-011 지배구조 인식 기반 종목선택 개선 테스트.

AC-HIER: StockRelation holding_company / subsidiary 타입
AC-CAND: 자회사 후보 풀 확장 로직
AC-BRIEF: 브리핑 프롬프트 지주사 컨텍스트 주입
AC-FACTOR: factor_scoring 지주사 할인 팩터
"""

from sqlalchemy.orm import Session

from app.models.stock_relation import StockRelation
from app.services.factor_scoring import build_factor_scores_json
from app.services.fund_manager import (
    _is_holding_company,
    _get_subsidiaries,
    _expand_candidates_with_subsidiaries,
)


# ---------------------------------------------------------------------------
# AC-HIER: _is_holding_company / _get_subsidiaries
# ---------------------------------------------------------------------------

class TestIsHoldingCompany:
    """_is_holding_company 함수 테스트."""

    def test_holding_company_detected(self, db: Session, make_stock) -> None:
        """holding_company 관계 target으로 등록된 종목은 지주사로 판별된다."""
        parent = make_stock(name="지주사", stock_code="000001")
        child = make_stock(name="자회사", stock_code="000002")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        assert _is_holding_company(db, parent.id) is True

    def test_non_holding_company_not_detected(self, db: Session, make_stock) -> None:
        """holding_company 관계가 없는 종목은 지주사가 아니다."""
        stock = make_stock(name="일반종목", stock_code="000003")
        assert _is_holding_company(db, stock.id) is False

    def test_subsidiary_not_holding_company(self, db: Session, make_stock) -> None:
        """source_stock_id에 등록된 자회사는 지주사가 아니다."""
        parent = make_stock(name="지주사B", stock_code="000004")
        child = make_stock(name="자회사B", stock_code="000005")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        assert _is_holding_company(db, child.id) is False

    def test_cache_is_populated(self, db: Session, make_stock) -> None:
        """캐시를 전달하면 결과가 저장된다."""
        parent = make_stock(name="지주사C", stock_code="000006")
        child = make_stock(name="자회사C", stock_code="000007")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        cache: dict[int, bool] = {}
        _is_holding_company(db, parent.id, cache)
        assert parent.id in cache
        assert cache[parent.id] is True

    def test_cache_hit_skips_db(self, db: Session, make_stock) -> None:
        """캐시에 결과가 있으면 DB 쿼리를 하지 않는다 (캐시 값 그대로 반환)."""
        stock = make_stock(name="캐시종목", stock_code="000008")
        cache = {stock.id: True}  # DB에 관계가 없어도 캐시가 True면 True 반환
        assert _is_holding_company(db, stock.id, cache) is True


class TestGetSubsidiaries:
    """_get_subsidiaries 함수 테스트."""

    def test_returns_subsidiary_ids(self, db: Session, make_stock) -> None:
        """지주사 ID 전달 시 자회사 ID 목록을 반환한다."""
        parent = make_stock(name="지주사D", stock_code="000010")
        child1 = make_stock(name="자회사D1", stock_code="000011")
        child2 = make_stock(name="자회사D2", stock_code="000012")
        for child in (child1, child2):
            db.add(StockRelation(
                source_stock_id=child.id,
                target_stock_id=parent.id,
                relation_type="holding_company",
                confidence=1.0,
            ))
        db.flush()

        result = _get_subsidiaries(db, [parent.id])
        assert sorted(result[parent.id]) == sorted([child1.id, child2.id])

    def test_empty_input_returns_empty(self, db: Session) -> None:
        """빈 목록 전달 시 빈 dict를 반환한다."""
        assert _get_subsidiaries(db, []) == {}

    def test_non_holding_company_returns_empty_list(self, db: Session, make_stock) -> None:
        """지주사 관계가 없는 종목은 빈 목록을 반환한다."""
        stock = make_stock(name="관계없음", stock_code="000013")
        result = _get_subsidiaries(db, [stock.id])
        assert result[stock.id] == []

    def test_competitor_relation_not_included(self, db: Session, make_stock) -> None:
        """competitor 타입 관계는 자회사로 포함되지 않는다."""
        parent = make_stock(name="지주사E", stock_code="000014")
        competitor = make_stock(name="경쟁사", stock_code="000015")
        db.add(StockRelation(
            source_stock_id=competitor.id,
            target_stock_id=parent.id,
            relation_type="competitor",
            confidence=1.0,
        ))
        db.flush()

        result = _get_subsidiaries(db, [parent.id])
        assert result[parent.id] == []


# ---------------------------------------------------------------------------
# AC-CAND: _expand_candidates_with_subsidiaries
# ---------------------------------------------------------------------------

class TestExpandCandidatesWithSubsidiaries:
    """_expand_candidates_with_subsidiaries 함수 테스트."""

    def test_holding_company_candidate_expands_to_subsidiaries(
        self, db: Session, make_stock
    ) -> None:
        """후보 목록에 지주사가 있으면 자회사가 추가된다."""
        parent = make_stock(name="HD지주", stock_code="267250")
        child = make_stock(name="HD조선", stock_code="009540")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        candidates = [{"name": "HD지주", "code": "267250", "news_count": 3}]
        expanded, subsidiary_map = _expand_candidates_with_subsidiaries(db, candidates)

        codes = [c["code"] for c in expanded]
        assert "267250" in codes  # 지주사 유지
        assert "009540" in codes  # 자회사 추가

    def test_subsidiary_marked_with_flag(self, db: Session, make_stock) -> None:
        """추가된 자회사 항목에는 holding_company_subsidiary 플래그가 있다."""
        parent = make_stock(name="HD지주2", stock_code="267251")
        child = make_stock(name="HD조선2", stock_code="009541")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        candidates = [{"name": "HD지주2", "code": "267251", "news_count": 1}]
        expanded, _ = _expand_candidates_with_subsidiaries(db, candidates)

        sub_entry = next(c for c in expanded if c["code"] == "009541")
        assert sub_entry.get("holding_company_subsidiary") is True

    def test_already_present_subsidiary_not_duplicated(
        self, db: Session, make_stock
    ) -> None:
        """이미 후보에 있는 자회사는 중복 추가되지 않는다."""
        parent = make_stock(name="HD지주3", stock_code="267252")
        child = make_stock(name="HD조선3", stock_code="009542")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        # 자회사가 이미 후보에 있는 경우
        candidates = [
            {"name": "HD지주3", "code": "267252", "news_count": 2},
            {"name": "HD조선3", "code": "009542", "news_count": 1},
        ]
        expanded, _ = _expand_candidates_with_subsidiaries(db, candidates)

        # 009542 중복 없이 1번만 등장해야 함
        child_entries = [c for c in expanded if c["code"] == "009542"]
        assert len(child_entries) == 1

    def test_no_holding_company_returns_original(
        self, db: Session, make_stock
    ) -> None:
        """지주사가 없으면 원본 후보와 빈 map을 그대로 반환한다."""
        make_stock(name="일반주A", stock_code="111111")
        candidates = [{"name": "일반주A", "code": "111111", "news_count": 1}]
        expanded, sub_map = _expand_candidates_with_subsidiaries(db, candidates)
        assert expanded == candidates
        assert sub_map == {}

    def test_empty_candidates_returns_empty(self, db: Session) -> None:
        """빈 후보 목록 입력 시 빈 목록과 빈 map을 반환한다."""
        expanded, sub_map = _expand_candidates_with_subsidiaries(db, [])
        assert expanded == []
        assert sub_map == {}


# ---------------------------------------------------------------------------
# AC-FACTOR: build_factor_scores_json 지주사 할인
# ---------------------------------------------------------------------------

class TestBuildFactorScoresJsonHoldingDiscount:
    """build_factor_scores_json 지주사 할인 (-5) 테스트."""

    def test_holding_company_discount_applied(
        self, db: Session, make_stock
    ) -> None:
        """지주사 종목은 composite_score에서 -5 할인이 적용된다."""
        parent = make_stock(name="지주사팩터", stock_code="555001")
        child = make_stock(name="자회사팩터", stock_code="555002")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        # stock_id 없이 호출 (기준점 확인)
        _, score_no_id = build_factor_scores_json([], {}, {})

        # 지주사 stock_id + db 전달
        _, score_holding = build_factor_scores_json(
            [], {}, {}, stock_id=parent.id, db=db
        )

        assert score_holding == max(0.0, round(score_no_id - 5.0, 1))

    def test_non_holding_no_discount(self, db: Session, make_stock) -> None:
        """지주사가 아닌 종목은 할인이 없다."""
        normal = make_stock(name="일반주B", stock_code="555003")

        _, score_no_id = build_factor_scores_json([], {}, {})
        _, score_normal = build_factor_scores_json(
            [], {}, {}, stock_id=normal.id, db=db
        )

        assert score_normal == score_no_id

    def test_discount_not_below_zero(self, db: Session, make_stock) -> None:
        """composite_score가 5 미만이어도 0 이하로 내려가지 않는다."""
        parent = make_stock(name="지주사최소", stock_code="555004")
        child = make_stock(name="자회사최소", stock_code="555005")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        # score 0에서 -5 → 0 이하 방지
        _, score = build_factor_scores_json(
            [], {}, {}, stock_id=parent.id, db=db
        )
        assert score >= 0.0

    def test_holding_discount_field_in_json(
        self, db: Session, make_stock
    ) -> None:
        """지주사 할인 시 factor_scores JSON에 holding_company_discount 필드가 포함된다."""
        import json as _json

        parent = make_stock(name="지주사JSON", stock_code="555006")
        child = make_stock(name="자회사JSON", stock_code="555007")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        factor_json, _ = build_factor_scores_json(
            [], {}, {}, stock_id=parent.id, db=db
        )
        scores = _json.loads(factor_json)
        assert scores.get("holding_company_discount") == -5

    def test_no_db_no_discount(self, db: Session, make_stock) -> None:
        """db=None이면 지주사 체크를 하지 않는다 (backward compatibility)."""
        parent = make_stock(name="지주사호환", stock_code="555008")
        child = make_stock(name="자회사호환", stock_code="555009")
        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        _, score_without_db = build_factor_scores_json(
            [], {}, {}, stock_id=parent.id, db=None
        )
        _, score_baseline = build_factor_scores_json([], {}, {})

        assert score_without_db == score_baseline


# ---------------------------------------------------------------------------
# AC-HIER: relation_propagator 지배구조 관계 전파 방지
# ---------------------------------------------------------------------------

class TestRelationPropagatorGuard:
    """holding_company/subsidiary 관계는 뉴스 전파에서 제외된다."""

    def test_holding_company_relation_skipped_in_propagation(
        self, db: Session, make_stock
    ) -> None:
        """holding_company 타입은 propagate_news에서 무시된다."""
        from app.services.relation_propagator import propagate_news

        parent = make_stock(name="지주사전파", stock_code="999001")
        child = make_stock(name="자회사전파", stock_code="999002")

        db.add(StockRelation(
            source_stock_id=child.id,
            target_stock_id=parent.id,
            relation_type="holding_company",
            confidence=1.0,
        ))
        db.flush()

        # 지주사를 direct_relations로 전달 → 자회사에 전파되지 않아야 함
        results = propagate_news(
            db=db,
            news_id=1,
            article_sentiment="positive",
            direct_relations=[
                {"stock_id": parent.id, "sector_id": None, "stock_name": "지주사전파", "sector_name": None}
            ],
        )

        # holding_company 타입 relation은 스킵되어야 하므로 결과에 자회사 없음
        propagated_stock_ids = {r.get("stock_id") for r in results}
        assert child.id not in propagated_stock_ids
