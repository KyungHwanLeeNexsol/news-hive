"""SPEC-AI-086: 스캔 유니버스 커버리지 확장(측정 계층) — 캐릭터라이제이션 및 인수조건 테스트.

DDD ANALYZE-PRESERVE-IMPROVE — PRESERVE 선행(Reproduction-First).

C1: 현재 build_scan_universe 골든 유니버스(150-cap, quota 배분) 바이트 고정
C2: non_scannable 원인 진단(truncated/absent) 결손 RED 재현 (구현 전 실패 확인용)
C3: scannable_recall/coverage 산식 동결(회귀 감지 기준선)
C4: 측정 전용 비용 경계 — _universe_codes가 merged(탐지 입력)에 재투입되지 않음(Exclusion 1)
"""

from __future__ import annotations

import inspect
import logging
from datetime import date as _date
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.surge_config.surge_settings import get_surge_config
from app.services.surge_detector import build_scan_universe, gather_surge_candidates

from tests.test_spec_ai_065 import (
    _make_pool_a_disclosures,
    _make_pool_c_outcomes,
    _pool_b_patches,
)
from tests.test_surge_evaluation_service import _seed_predicted_and_actual


# ---------------------------------------------------------------------------
# C1 — 골든 유니버스 베이스라인 (결정론적 소규모 시나리오, 순서까지 바이트 고정)
# ---------------------------------------------------------------------------

def _make_pool_a_disclosures_named(db: Session, codes: list[str]) -> None:
    today_str = _date.today().strftime("%Y%m%d")
    for idx, code in enumerate(codes):
        db.add(
            Disclosure(
                corp_code=f"g{idx:07d}",
                corp_name=f"골든기업A_{idx}",
                stock_code=code,
                report_name="테스트공시(SPEC-AI-086 골든)",
                rcept_no=f"G086{idx:012d}",
                rcept_dt=today_str,
                url=f"https://dart.fss.or.kr/test086/{idx}",
            )
        )
    db.flush()


def _make_pool_c_outcomes_named(db: Session, codes: list[str]) -> None:
    today = _date.today()
    for idx, code in enumerate(codes):
        db.add(
            SurgeActualOutcome(
                trading_date=today,
                stock_code=code,
                stock_name=f"골든종목C_{idx}",
                change_rate=10.0,
                was_surge=True,
                market="KOSPI",
            )
        )
    db.flush()


class TestGoldenUniverseBaseline:
    """C1: 절단 압력 없는 소규모 결정론적 시나리오 — 최종 유니버스 순서·pool_counts 바이트 고정.

    Pool A=[a0..a4](5), Pool C=[c0..c2](3), Pool B=[b0,b1](2). 합계 10 << max_universe(150)
    이므로 절단 없음. 기본 quota(pool_b_min_slots=20, pool_c_min_slots=30)가 B/C 전량을
    예약분으로 흡수하므로 기대 순서 = [b0,b1, c0,c1,c2, a0..a4] (reserved_b + reserved_c +
    pool_a + b_remaining(공집합) + c_remaining(공집합)).
    """

    def test_golden_order_and_pool_counts_default_config(self, db: Session):
        pool_a_codes = ["a00000", "a00001", "a00002", "a00003", "a00004"]
        pool_c_codes = ["c00000", "c00001", "c00002"]
        pool_b_codes = ["b00000", "b00001"]

        _make_pool_a_disclosures_named(db, pool_a_codes)
        _make_pool_c_outcomes_named(db, pool_c_codes)

        cfg = get_surge_config()  # 신규 설정 전부 기본값 확인용(REQ-007 동시 검증)
        # SPEC-AI-096 REQ-AI096-001: 기본값 150→250. 이 테스트의 후보 수(10)는 두 값
        # 모두보다 훨씬 작아 절단이 발생하지 않으므로 골든 순서/pool_counts 자체는 무영향.
        assert cfg.max_scan_universe == 250
        assert cfg.pool_d_min_slots == 0
        assert cfg.dynamic_scan_universe_caps == {}

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with p1, p2, p3:
            final_universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        expected_order = pool_b_codes + pool_c_codes + pool_a_codes
        assert final_universe == expected_order, (
            f"골든 순서 불일치: {final_universe} != {expected_order}"
        )

        assert pool_counts["pool_a"] == 5
        assert pool_counts["pool_b"] == 2
        assert pool_counts["pool_c"] == 3
        assert pool_counts["pool_a_scanned"] == 5
        assert pool_counts["pool_b_scanned"] == 2
        assert pool_counts["pool_c_scanned"] == 3

        # SPEC-AI-086: Pool D 기본 비활성 — raw/scanned 0(또는 부재), entry_pool에 'pool_d' 없음
        assert pool_counts.get("pool_d", 0) == 0
        assert pool_counts.get("pool_d_scanned", 0) == 0
        assert "pool_d" not in entry_pool_map.values()

        for code in pool_a_codes:
            assert entry_pool_map[code] == "pool_a"
        for code in pool_b_codes:
            assert entry_pool_map[code] == "pool_b"
        for code in pool_c_codes:
            assert entry_pool_map[code] == "pool_c"

    def test_golden_0708_replay_scenario_unchanged_at_fixed_cap_150(self, db: Session):
        """SPEC-AI-076 07-08형 재현 시나리오(A=232,B=0,C=52)가 SPEC-AI-086 이후에도
        cap=150 고정 시 정확히 동일해야 한다(REQ-007 백워드 호환, 대규모 절단 압력 케이스).

        SPEC-AI-096 REQ-AI096-001이 max_scan_universe 기본값을 150→250으로 상향했으므로,
        이 테스트는 원래의 "기본 설정" 대신 cap=150을 명시 오버라이드하여 캡 파라미터
        자체(clamp 로직 무수정)의 회귀 감지 가치를 그대로 유지한다(AC-096-010 검증 방법).
        """
        _make_pool_a_disclosures(db, 232)
        _make_pool_c_outcomes(db, 52)
        cfg = get_surge_config().model_copy(update={"max_scan_universe": 150})

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) == 150
        assert pool_counts["pool_a"] == 232
        assert pool_counts["pool_c"] == 52
        assert pool_counts["pool_a_scanned"] == 120
        assert pool_counts["pool_c_scanned"] == 30
        assert pool_counts.get("pool_d", 0) == 0


# ---------------------------------------------------------------------------
# C2 — non_scannable 원인 진단(truncated/absent) 결손 RED 재현
# 구현 전: ImportError/AttributeError로 실패해야 한다(REQ-002 결손 확인).
# 구현 후: 아래 두 종목이 각각 truncated/absent로 정확히 분류되어야 한다.
# ---------------------------------------------------------------------------

class TestNonScannableDiagnosisGap:
    """C2: REQ-AI086-002 진단 함수 결손(RED) → 구현 후 truncated/absent 분류(GREEN)."""

    def test_truncated_vs_absent_classification(self, db: Session):
        """AC-086-004: 종목 A(T-1 Pool A/C raw 자격 있음, absent 아님) truncated,
        종목 B(T-1 공시·등락 기준 전부 미충족) absent로 분류된다."""
        from app.services.surge_evaluation_service import diagnose_non_scannable_causes
        from app.services.surge_trading_service import _get_prev_business_day

        trading_date = _date(2026, 7, 1)  # 수요일
        t_minus_1 = _get_prev_business_day(trading_date)

        # T-1에 종목 A는 DART 공시 raw 자격 보유(→ truncated 판정 대상), B는 아무 자격 없음(→ absent)
        db.add(
            Disclosure(
                corp_code="00000086",
                corp_name="테스트기업086A",
                stock_code="A00086",
                report_name="테스트공시(SPEC-AI-086)",
                rcept_no="A086000000000001",
                rcept_dt=t_minus_1.strftime("%Y%m%d"),
                url="https://dart.fss.or.kr/test086/a",
            )
        )
        db.flush()

        # T(당일) 실제급등 결과 — 둘 다 non_scannable로 이미 라벨링된 상태를 재현
        db.add(
            SurgeActualOutcome(
                trading_date=trading_date,
                stock_code="A00086",
                stock_name="테스트기업086A",
                change_rate=12.0,
                was_surge=True,
                market="KOSPI",
                surge_type="non_scannable",
            )
        )
        db.add(
            SurgeActualOutcome(
                trading_date=trading_date,
                stock_code="B00086",
                stock_name="테스트기업086B",
                change_rate=11.0,
                was_surge=True,
                market="KOSPI",
                surge_type="non_scannable",
            )
        )
        db.commit()

        result = diagnose_non_scannable_causes(db, trading_date)

        assert result.get("A00086") == "truncated"
        assert result.get("B00086") == "absent"

    def test_empty_when_no_non_scannable_rows(self, db: Session):
        from app.services.surge_evaluation_service import diagnose_non_scannable_causes

        trading_date = _date(2026, 7, 1)
        result = diagnose_non_scannable_causes(db, trading_date)
        assert result == {}


# ---------------------------------------------------------------------------
# C3 — scannable_recall/coverage 산식 동결 (회귀 감지 기준선)
# ---------------------------------------------------------------------------

class TestMetricFormulaFreeze:
    """C3: SPEC-AI-068 산식(scannable_recall = |universe∩actual∩predicted| / |universe∩actual|,
    coverage = |universe∩actual| / |actual|)이 SPEC-AI-086 이후에도 불변임을 동결한다."""

    def test_scannable_recall_and_coverage_formula_unchanged(self, db: Session):
        trading_date = _date(2026, 7, 1)
        predicted = ["A"]
        actual = ["A", "B", "X", "Y", "Z"]

        t_minus_1 = _seed_predicted_and_actual(db, predicted, actual, trading_date)

        from app.services.surge_universe_pool_service import persist_universe_members

        persist_universe_members(
            db,
            t_minus_1,
            ["A", "B", "C", "D"],
            {"A": "pool_a", "B": "pool_b", "C": "pool_b", "D": "pool_c"},
        )
        db.commit()

        from app.services.surge_evaluation_service import evaluate_surge_predictions

        result = evaluate_surge_predictions(db, trading_date)

        assert result.scannable_actual_count == 2
        assert result.total_actual_count == 5
        assert abs((result.scannable_recall or 0.0) - 0.5) < 1e-9
        assert abs((result.coverage or 0.0) - 0.4) < 1e-9

    def test_evaluate_surge_predictions_backward_compatible_without_new_kwarg(
        self, db: Session
    ):
        """REQ-007 계승: prior_scannable_metrics 미전달 시 기존 호출부와 완전히 동일하게 동작한다."""
        trading_date = _date(2026, 7, 1)
        _seed_predicted_and_actual(db, ["R1"], ["R1"], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions

        result = evaluate_surge_predictions(db, trading_date)
        assert result.true_positive == 1


# ---------------------------------------------------------------------------
# C4 — 측정 전용 비용 경계 (Exclusion 1): _universe_codes가 merged에 재투입되지 않는다
# ---------------------------------------------------------------------------

class TestCostBoundaryBaseline:
    """C4: gather_surge_candidates 소스 상에서 build_scan_universe 반환값(_universe_codes)이
    entry_pool 태깅/영속화 이외 용도(탐지 입력 merged 재투입)로 쓰이지 않음을 정적으로 고정한다."""

    def test_universe_codes_never_feeds_detector_merge_dict(self):
        source = inspect.getsource(gather_surge_candidates)

        assert "build_scan_universe(" in source, "build_scan_universe 호출부가 존재해야 한다"

        lines_with_universe_codes = [
            line for line in source.splitlines() if "_universe_codes" in line
        ]
        assert lines_with_universe_codes, "_universe_codes 참조가 최소 1곳 이상 있어야 한다"

        forbidden_patterns = ("merged[", "merged.update", "merged =")
        for line in lines_with_universe_codes:
            for pattern in forbidden_patterns:
                assert pattern not in line, (
                    f"Exclusion 1 위반: _universe_codes가 탐지 입력(merged)에 재투입되는 "
                    f"코드가 발견됨 — {line.strip()!r}"
                )

    def test_build_scan_universe_only_tags_preexisting_merged_keys(self, db: Session):
        """entry_pool 태깅 루프가 merged.keys()를 순회하고 새 키를 추가하지 않는지 확인."""
        source = inspect.getsource(gather_surge_candidates)
        assert "for code, candidate in merged.items():" in source

    def test_detector_invocation_counts_unchanged_when_cap_expanded_or_pool_d_enabled(
        self, db: Session
    ):
        """AC-086-005(HARD): 상한 확장/Pool D 활성화가 유효해도 7개 탐지기 각각의 호출
        수는 확장 전과 동일(1회씩)해야 하며, 측정 유니버스 코드가 탐지 결과(merged)에
        재투입되지 않는다(회귀 assert, 호출그래프 기반)."""
        detector_names = [
            "detect_theme_news_cluster",
            "detect_volume_surge_news_combo",
            "detect_disclosure_surge_pattern",
            "detect_immediate_disclosure_signal",
            "detect_news_delayed_response",
            "detect_volume_breakout",
            "detect_momentum_continuation",
        ]

        def _run_with_config(cfg) -> dict[str, int]:
            import contextlib

            with contextlib.ExitStack() as stack:
                stack.enter_context(
                    patch(
                        "app.services.naver_finance.fetch_volume_leaders_sync",
                        return_value=[],
                    )
                )
                mocks = {
                    name: stack.enter_context(
                        patch(f"app.services.surge_detector.{name}", return_value=[])
                    )
                    for name in detector_names
                }
                candidates = gather_surge_candidates(db, [], cfg, [])
            assert candidates == []  # 탐지기 전부 mock되어 반환 후보 0건
            return {name: m.call_count for name, m in mocks.items()}

        baseline_cfg = get_surge_config()
        expanded_cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 500, "pool_d_min_slots": 20}
        )

        baseline_counts = _run_with_config(baseline_cfg)
        expanded_counts = _run_with_config(expanded_cfg)

        assert baseline_counts == expanded_counts == {name: 1 for name in detector_names}, (
            f"탐지기 호출 수 변화 감지 — baseline={baseline_counts}, expanded={expanded_counts}"
        )


# ---------------------------------------------------------------------------
# AC-086-001/002 — max_scan_universe 경계 [50,600] clamp
# ---------------------------------------------------------------------------

class TestMaxScanUniverseClamp:
    def test_within_bounds_applied_as_is(self, db: Session):
        """AC-086-001: 상한=300(경계 이내) → 그대로 적용, 유니버스 길이 <= 300."""
        _make_pool_a_disclosures(db, 320)
        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 300, "pool_b_min_slots": 0, "pool_c_min_slots": 0}
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) == 300

    def test_exceeds_ceiling_clamped_to_600_with_warning_no_exception(
        self, db: Session, caplog
    ):
        """AC-086-002: 상한=5000(경계 초과) → 600으로 clamp + 경고 로그 + 예외 없음."""
        _make_pool_a_disclosures(db, 620)
        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 5000, "pool_b_min_slots": 0, "pool_c_min_slots": 0}
        )

        with (
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=[],
            ),
            caplog.at_level(logging.WARNING, logger="app.services.surge_detector"),
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) == 600
        assert any("clamp" in r.message.lower() for r in caplog.records)

    def test_below_floor_clamped_to_50_with_warning(self, db: Session, caplog):
        """상한 하한(50) 미만 설정 → 50으로 clamp + 경고 로그."""
        _make_pool_a_disclosures(db, 60)
        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 10, "pool_b_min_slots": 0, "pool_c_min_slots": 0}
        )

        with (
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=[],
            ),
            caplog.at_level(logging.WARNING, logger="app.services.surge_detector"),
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) == 50
        assert any("clamp" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# AC-086-006 — Pool D quota 통합 (기본 OFF 확인 포함)
# ---------------------------------------------------------------------------

def _seed_pool_d_news_mentions(db: Session, codes: list[str]) -> None:
    """Pool D(뉴스 언급 기반) raw 후보 `codes`개를 DB에 직접 삽입한다(모듈 레벨 재사용 헬퍼)."""
    from datetime import datetime, timezone as _tz

    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation
    from app.models.sector import Sector
    from app.models.stock import Stock

    sector = Sector(name=f"SPEC-AI-086 Pool D 섹터_{len(codes)}", is_custom=False)
    db.add(sector)
    db.flush()

    for idx, code in enumerate(codes):
        stock = Stock(stock_code=code, name=f"뉴스언급종목_{idx}", sector_id=sector.id, market="KOSPI")
        db.add(stock)
        db.flush()

        article = NewsArticle(
            title=f"뉴스언급 테스트기사_{idx}",
            url=f"https://news.test/pool_d/{code}/{idx}",
            source="test",
            published_at=datetime.now(_tz.utc),
        )
        db.add(article)
        db.flush()

        db.add(
            NewsStockRelation(
                news_id=article.id,
                stock_id=stock.id,
                match_type="ai_classified",
                relevance="direct",
            )
        )
    db.flush()


class TestPoolDQuotaIntegration:
    def test_pool_d_disabled_by_default_no_query_no_tagging(self, db: Session):
        """기본 설정(pool_d_min_slots=0)이면 Pool D 소싱 쿼리 자체가 스킵된다."""
        _seed_pool_d_news_mentions(db, ["d00000", "d00001"])
        cfg = get_surge_config()
        assert cfg.pool_d_min_slots == 0

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert pool_counts.get("pool_d", 0) == 0
        assert "d00000" not in final_universe
        assert "pool_d" not in entry_pool_map.values()

    def test_pool_d_reserved_slots_survive_truncation_pressure(self, db: Session):
        """AC-086-006: 신규 풀 예약=20 + 절단 압력 → Pool D >= 20 잔존 + entry_pool='pool_d' 태깅."""
        _make_pool_a_disclosures(db, 200)  # 큰 절단 압력
        pool_d_codes = [f"d{i:05d}" for i in range(25)]
        _seed_pool_d_news_mentions(db, pool_d_codes)

        cfg = get_surge_config().model_copy(
            update={
                "max_scan_universe": 150,
                "pool_b_min_slots": 0,
                "pool_c_min_slots": 0,
                "pool_d_min_slots": 20,
            }
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        pool_d_represented = sum(
            1 for c in final_universe if entry_pool_map.get(c) == "pool_d"
        )
        assert pool_d_represented >= 20, (
            f"Pool D 대표 수={pool_d_represented} (기대: >=20)"
        )
        assert len(final_universe) == 150
        assert pool_counts["pool_d"] == 25

    def test_pool_d_fail_open_exception_does_not_propagate(self, db: Session, caplog):
        """엣지 케이스(acceptance.md): 신규 풀 소싱 조회 실패 → fail-open(해당 풀 스킵),
        예외가 build_scan_universe 밖으로 전파되지 않고 유니버스가 정상 반환된다."""
        _make_pool_a_disclosures(db, 5)
        _seed_pool_d_news_mentions(db, ["dfail0", "dfail1"])

        cfg = get_surge_config().model_copy(
            update={"pool_b_min_slots": 0, "pool_c_min_slots": 0, "pool_d_min_slots": 20}
        )

        # NewsStockRelation을 속성 없는 plain object로 치환해 Pool D 쿼리 구성(.stock_id
        # 접근) 시점에 AttributeError가 발생하도록 강제한다(로컬 import라 함수 호출 시점의
        # 모듈 속성을 그대로 가져온다).
        with (
            patch("app.models.news_relation.NewsStockRelation", new=object()),
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=[],
            ),
            caplog.at_level(logging.WARNING, logger="app.services.surge_detector"),
        ):
            final_universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        # 예외 없이 정상 반환 — Pool D만 스킵되고 Pool A는 정상 반영됨
        assert len(final_universe) == 5
        assert pool_counts["pool_a"] == 5
        assert pool_counts.get("pool_d", 0) == 0
        assert "dfail0" not in final_universe
        assert any(
            "Pool D 조회 실패" in r.message for r in caplog.records
        ), "Pool D 실패 시 fail-open 경고 로그가 남아야 한다"


# ---------------------------------------------------------------------------
# AC-086-008 — 장중 시간대별 동적 상한(선택)
# ---------------------------------------------------------------------------
# 엣지 케이스(acceptance.md): 신규 풀 예약 슬롯 합계가 상한 초과 → SPEC-AI-076 clamp
# 로직으로 비율 축소 — pool_d_min_slots>0 상태에서 3풀 합이 상한을 초과하는 조합.
# ---------------------------------------------------------------------------

class TestThreePoolProportionalClampWithPoolD:
    def test_reserved_b_c_d_sum_shrinks_to_exactly_max_universe(self, db: Session, caplog):
        """reserved_b+reserved_c+reserved_d(180) > max_universe(100) → 비율 축소되어
        3풀 합이 정확히 max_universe(100)로 수렴한다(레거시 2풀 clamp의 3풀 확장 분기)."""
        _make_pool_a_disclosures(db, 5)
        _make_pool_c_outcomes(db, 60)
        pool_b_codes = [f"b{i:05d}" for i in range(60)]
        pool_d_codes = [f"d{i:05d}" for i in range(60)]
        _seed_pool_d_news_mentions(db, pool_d_codes)

        cfg = get_surge_config().model_copy(
            update={
                "max_scan_universe": 100,
                "pool_b_min_slots": 60,
                "pool_c_min_slots": 60,
                "pool_d_min_slots": 60,
            }
        )

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with (
            p1, p2, p3,
            caplog.at_level(logging.WARNING, logger="app.services.surge_detector"),
        ):
            final_universe, entry_pool_map, _pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) == 100

        b_represented = sum(1 for c in final_universe if entry_pool_map.get(c) == "pool_b")
        c_represented = sum(1 for c in final_universe if entry_pool_map.get(c) == "pool_c")
        d_represented = sum(1 for c in final_universe if entry_pool_map.get(c) == "pool_d")

        assert b_represented + c_represented + d_represented == 100, (
            f"3풀 합 불일치: B={b_represented} C={c_represented} D={d_represented} "
            f"(기대 합=100)"
        )
        # 비례 축소 산술 확인: reserved_b=(60*100)//180=33, reserved_c=33, reserved_d=100-33-33=34
        assert b_represented == 33
        assert c_represented == 33
        assert d_represented == 34

        assert any(
            "축소" in r.message or "clamp" in r.message.lower() for r in caplog.records
        ), "풀 예약 슬롯 합계 초과 시 경고 로그가 남아야 한다"

        # pool_a 후보(5개)는 예약분(100)이 이미 상한을 소진해 전량 절단됨을 확인
        assert not any(entry_pool_map.get(c) == "pool_a" for c in final_universe)


class TestDynamicScanUniverseCap:
    def test_dynamic_cap_applied_when_time_bin_matches(self, db: Session):
        from datetime import datetime as _dt

        _make_pool_a_disclosures(db, 250)
        cfg = get_surge_config().model_copy(
            update={
                "dynamic_scan_universe_caps": {"premarket_early": 200, "close_final": 100},
            }
        )
        premarket_time = _dt(2026, 7, 1, 9, 10)  # 09:00-09:30 bin

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set(), now=premarket_time
            )

        assert len(final_universe) == 200

    def test_dynamic_cap_unset_falls_back_to_flat_cap(self, db: Session):
        """미설정(기본 빈 dict)이면 REQ-001의 단일 평탄 상한(max_scan_universe)이 적용된다.

        SPEC-AI-096 REQ-AI096-001로 기본 상한이 150→250으로 상향되어, 절단 압력을
        여전히 재현하려면 후보 수를 250 초과로 늘려야 한다(원본은 200/150 조합).
        """
        _make_pool_a_disclosures(db, 300)
        cfg = get_surge_config()  # dynamic_scan_universe_caps={} (기본)

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert len(final_universe) == 250  # cfg.max_scan_universe 기본값(SPEC-AI-096)

    def test_dynamic_cap_current_bin_key_absent_falls_back_to_flat_cap(self, db: Session):
        """동적 상한 맵에 현재 시간대 키가 없으면 단일 평탄 상한으로 폴백한다.

        SPEC-AI-096 REQ-AI096-001로 기본 상한이 150→250으로 상향되어, 절단 압력을
        여전히 재현하려면 후보 수를 250 초과로 늘려야 한다(원본은 200/150 조합).
        """
        from datetime import datetime as _dt

        _make_pool_a_disclosures(db, 300)
        cfg = get_surge_config().model_copy(
            update={"dynamic_scan_universe_caps": {"close_final": 100}},
        )
        # 09:00-09:30(premarket_early) 시각이지만 맵에는 close_final만 존재
        premarket_time = _dt(2026, 7, 1, 9, 10)

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=set(), now=premarket_time
            )

        assert len(final_universe) == 250  # flat max_scan_universe 폴백(SPEC-AI-096)


# ---------------------------------------------------------------------------
# AC-086-009 — 관측성 단일 로그 라인
# ---------------------------------------------------------------------------

class TestObservabilityLogLine:
    def test_single_summary_log_line_contains_required_fields(self, db: Session, caplog):
        _make_pool_a_disclosures(db, 5)
        cfg = get_surge_config()

        with (
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=[],
            ),
            caplog.at_level(logging.INFO, logger="app.services.surge_detector"),
        ):
            build_scan_universe(db, cfg, existing_codes=set())

        summary_records = [
            r for r in caplog.records
            if "최종 유니버스" in r.message and "상한=" in r.message
        ]
        assert len(summary_records) == 1, "요약 로그 라인이 정확히 1줄이어야 한다"
        msg = summary_records[0].message
        assert "raw:" in msg and "scanned:" in msg
        assert "D=" in msg  # Pool D 카운트 포함(신규 풀)


# ---------------------------------------------------------------------------
# REQ-006 — scannable_denominator_expanded 명명 토큰
# ---------------------------------------------------------------------------

class TestScannableDenominatorExpandedToken:
    def test_pure_function_true_when_denominator_and_intersection_both_grow(self):
        from app.services.surge_evaluation_service import (
            classify_scannable_denominator_expansion,
        )

        assert classify_scannable_denominator_expansion(
            prev_scannable_actual_count=3,
            prev_scan_universe_size=19,
            curr_scannable_actual_count=3,
            curr_scan_universe_size=40,
        ) is True

    def test_pure_function_false_when_denominator_shrinks(self):
        from app.services.surge_evaluation_service import (
            classify_scannable_denominator_expansion,
        )

        assert classify_scannable_denominator_expansion(
            prev_scannable_actual_count=3,
            prev_scan_universe_size=40,
            curr_scannable_actual_count=3,
            curr_scan_universe_size=19,
        ) is False

    def test_evaluate_surge_predictions_sets_token_when_prior_metrics_given(
        self, db: Session
    ):
        """AC-086-007(D6): 평가 결과 객체에 명명 필드가 존재해 기계적으로 assert 가능하다."""
        trading_date = _date(2026, 7, 1)
        predicted = ["A"]
        actual = ["A", "B", "X", "Y", "Z"]
        t_minus_1 = _seed_predicted_and_actual(db, predicted, actual, trading_date)

        from app.services.surge_universe_pool_service import persist_universe_members

        persist_universe_members(
            db, t_minus_1, ["A", "B", "C", "D"],
            {"A": "pool_a", "B": "pool_b", "C": "pool_b", "D": "pool_c"},
        )
        db.commit()

        from app.services.surge_evaluation_service import evaluate_surge_predictions

        result = evaluate_surge_predictions(
            db, trading_date,
            prior_scannable_metrics={"scannable_actual_count": 1, "scan_universe_size": 2},
        )

        assert hasattr(result, "scannable_denominator_expanded")
        assert result.scannable_denominator_expanded is True  # 2→4 분모 확장, 1→2 교집합 불감소

    def test_token_is_none_when_prior_metrics_not_provided(self, db: Session):
        """미제공 시 속성은 None — 기존 호출부와 완전히 동일(REQ-007)."""
        trading_date = _date(2026, 7, 1)
        _seed_predicted_and_actual(db, ["R1"], ["R1"], trading_date)

        from app.services.surge_evaluation_service import evaluate_surge_predictions

        result = evaluate_surge_predictions(db, trading_date)
        assert result.scannable_denominator_expanded is None
