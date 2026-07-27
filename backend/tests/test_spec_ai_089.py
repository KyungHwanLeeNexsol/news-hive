"""SPEC-AI-089 M1: 스캔 유니버스→탐지 배선 측정 스파이크 — 인수조건 테스트.

M1(측정 스파이크)만 검증한다. 배선 구현(M2/M3+)은 본 SPEC의 범위 밖이다.

- AC-089-001 (시나리오 1): measure_universe_detection_gap() 풀별 raw/covered 산출
- AC-089-002 (시나리오 2): 계측 비활성(기본값) 시 바이트 동등성
- AC-089-003 (REQ-002, 시나리오 3): 무시그널 실제급등 종목 풀 귀속 4분류
- AC-089-004: 비용 예산 불변식(수동/스테이징 측정 — 본 파일 범위 밖, §F 자가검증 별도 기록)
- AC-089-006 (REQ-006): 앙상블 가중치 합=1.0 불변식이 신규 플래그 추가 후에도 유지
- AC-089-007 (REQ-007, 시나리오 4): 단일 로그 라인, 종목별 상세 로그 없음
- AC-089-008 (REQ-003, 시나리오 5): 계측 ACTIVE 상태에서도 탐지 결과 완전 동일
"""

from __future__ import annotations

import contextlib
import logging
from datetime import date as _date
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_universe_member import SurgeUniverseMember
from app.services.surge_detector import SurgeCandidate, gather_surge_candidates
from app.services.surge_trading_service import _get_prev_business_day
from app.services.surge_universe_gap_service import (
    analyze_no_signal_pool_attribution,
    measure_universe_detection_gap,
)
from app.surge_config.surge_settings import get_surge_config


# ---------------------------------------------------------------------------
# AC-089-001 — 시나리오 1: 계측 활성화 시 간극 측정 정확성 (순수 함수)
# ---------------------------------------------------------------------------

class TestMeasureUniverseDetectionGap:
    def test_scenario1_pool_totals_and_covered(self):
        """시나리오 1: Pool A=3(1개 탐지망 포함), Pool B=2(0개 탐지망 포함)."""
        universe_codes = ["a1", "a2", "a3", "b1", "b2"]
        entry_pool_map = {
            "a1": "pool_a", "a2": "pool_a", "a3": "pool_a",
            "b1": "pool_b", "b2": "pool_b",
        }
        merged = {"a1": object()}  # Pool A의 1개 종목만 탐지망(merged)에 포함

        result = measure_universe_detection_gap(universe_codes, entry_pool_map, merged)

        assert result["pool_a_total"] == 3
        assert result["pool_a_covered"] == 1
        assert result["pool_b_total"] == 2
        assert result["pool_b_covered"] == 0

    def test_edge_all_pools_empty_no_division_error(self):
        """엣지 케이스: 모든 풀이 비어있는 날 — 0으로 나누기 없이 안전하게 완료."""
        result = measure_universe_detection_gap([], {}, {})

        for pool in ("pool_a", "pool_b", "pool_c", "pool_d"):
            assert result[f"{pool}_total"] == 0
            assert result[f"{pool}_covered"] == 0
            assert result[f"{pool}_gap_ratio"] is None

    def test_edge_merged_empty_all_covered_zero(self):
        """엣지 케이스: merged가 비어있는 날 — 모든 풀의 covered가 0, 예외 없음."""
        universe_codes = ["a1", "b1", "c1"]
        entry_pool_map = {"a1": "pool_a", "b1": "pool_b", "c1": "pool_c"}

        result = measure_universe_detection_gap(universe_codes, entry_pool_map, {})

        assert result["pool_a_covered"] == 0
        assert result["pool_b_covered"] == 0
        assert result["pool_c_covered"] == 0
        assert result["pool_a_gap_ratio"] == 1.0

    def test_edge_unmapped_code_defaults_to_existing_excluded_from_pool_counts(self):
        """엣지 케이스: entry_pool_map에 없는 코드는 'existing'으로 분류되며 A/B/C/D
        카운트에 영향을 주지 않는다(기존 build_scan_universe 시맨틱과 일치)."""
        universe_codes = ["x1"]
        result = measure_universe_detection_gap(universe_codes, {}, {"x1": object()})

        assert result["pool_a_total"] == 0
        assert result["pool_b_total"] == 0
        assert result["pool_c_total"] == 0
        assert result["pool_d_total"] == 0

    def test_pool_d_included_when_present(self):
        """Pool D(SPEC-AI-086 뉴스 언급 기반, opt-in)도 동일하게 계측된다."""
        universe_codes = ["d1", "d2"]
        entry_pool_map = {"d1": "pool_d", "d2": "pool_d"}
        merged = {"d1": object()}

        result = measure_universe_detection_gap(universe_codes, entry_pool_map, merged)

        assert result["pool_d_total"] == 2
        assert result["pool_d_covered"] == 1
        assert result["pool_d_gap"] == 1
        assert result["pool_d_gap_ratio"] == 0.5

    def test_no_new_db_writes(self, db: Session):
        """반환값 산출 중 신규 DB 쓰기가 발생하지 않는다(mock 세션으로 검증 불필요 —
        함수 시그니처 자체에 Session 파라미터가 없음을 확인)."""
        import inspect

        sig = inspect.signature(measure_universe_detection_gap)
        assert "db" not in sig.parameters, "measure_universe_detection_gap은 순수 함수여야 한다(Session 인자 없음)"


# ---------------------------------------------------------------------------
# AC-089-003 — 시나리오 3: REQ-002 무시그널 실제급등 종목 풀 귀속 4분류
# ---------------------------------------------------------------------------

def _seed_stock(db: Session, code: str) -> int:
    sector = Sector(name=f"AI089섹터_{code}", is_custom=False)
    db.add(sector)
    db.flush()
    stock = Stock(stock_code=code, name=f"주식{code}", sector_id=sector.id, market="KOSPI")
    db.add(stock)
    db.flush()
    return stock.id


class TestNoSignalPoolAttribution:
    def test_scenario3_four_way_pool_classification(self, db: Session):
        """시나리오 3: 무시그널 실제급등 종목 4개가 각각 Pool A/B/C/부재로 분류된다."""
        trading_date = _date(2026, 7, 20)
        prev_bday = _get_prev_business_day(trading_date)

        codes = {"a_only": "pool_a", "b_only": "pool_b", "c_only": "pool_c"}
        for code in list(codes.keys()) + ["absent_code"]:
            _seed_stock(db, code)
            db.add(
                SurgeActualOutcome(
                    trading_date=trading_date,
                    stock_code=code,
                    stock_name=f"주식{code}",
                    change_rate=12.0,
                    was_surge=True,
                    market="KOSPI",
                )
            )

        for code, pool in codes.items():
            db.add(
                SurgeUniverseMember(
                    trading_date=prev_bday, stock_code=code, entry_pool=pool
                )
            )
        # "absent_code"는 SurgeUniverseMember 레코드 자체가 없음 (소스 부재형)
        db.commit()

        result = analyze_no_signal_pool_attribution(db, trading_date)

        assert result["sample_present"] is True
        assert result["actual_surge_count"] == 4
        assert set(result["no_signal_codes"]) == {"a_only", "b_only", "c_only", "absent_code"}
        assert result["attribution"]["a_only"] == "pool_a"
        assert result["attribution"]["b_only"] == "pool_b"
        assert result["attribution"]["c_only"] == "pool_c"
        assert result["attribution"]["absent_code"] == "absent"
        assert result["attribution_summary"] == {
            "pool_a": 1, "pool_b": 1, "pool_c": 1, "absent": 1,
        }

    def test_signaled_stock_excluded_from_no_signal_set(self, db: Session):
        """당일(T) surge_candidate 시그널을 받은 종목은 무시그널 집합에서 제외된다."""
        trading_date = _date(2026, 7, 20)
        stock_id = _seed_stock(db, "signaled")
        db.add(
            SurgeActualOutcome(
                trading_date=trading_date,
                stock_code="signaled",
                stock_name="주식signaled",
                change_rate=15.0,
                was_surge=True,
                market="KOSPI",
            )
        )
        db.add(
            FundSignal(
                stock_id=stock_id,
                signal="buy",
                signal_type="surge_candidate",
                confidence=0.7,
                reasoning="테스트",
                created_at=datetime(
                    trading_date.year, trading_date.month, trading_date.day,
                    10, 0, tzinfo=timezone.utc,
                ),
            )
        )
        db.commit()

        result = analyze_no_signal_pool_attribution(db, trading_date)

        assert result["actual_surge_count"] == 1
        assert result["no_signal_codes"] == []
        assert "signaled" not in result["attribution"]

    def test_no_actual_surge_data_returns_sample_absent_explicit(self, db: Session):
        """엣지 케이스: 표본일에 실제 급등 종목 데이터가 없으면 sample_present=False로
        명시적으로 기록된다(조용히 스킵하지 않음)."""
        result = analyze_no_signal_pool_attribution(db, _date(1999, 1, 1))

        assert result["sample_present"] is False
        assert result["actual_surge_count"] == 0
        assert result["no_signal_codes"] == []
        assert result["attribution"] == {}


# ---------------------------------------------------------------------------
# AC-089-006 — REQ-006: 앙상블 가중치 합=1.0 불변식이 M1 범위에서 유지된다
# ---------------------------------------------------------------------------

class TestEnsembleWeightInvariantUnchanged:
    def test_flag_defaults_to_false(self):
        cfg = get_surge_config()
        assert cfg.universe_gap_measurement_enabled is False

    def test_flag_true_still_validates_ensemble_weights(self):
        """신규 플래그를 True로 바꿔도 validate_ensemble_weights 불변식이 여전히 통과한다."""
        cfg = get_surge_config().model_copy(update={"universe_gap_measurement_enabled": True})
        w = cfg.ensemble.weights
        total = (
            w.theme_cluster
            + w.volume_news_combo
            + w.disclosure_pattern
            + w.legacy_detectors
            + w.news_delayed
            + w.weekend_gap_up
            + w.volume_breakout
            + w.momentum_continuation
        )
        assert abs(total - 1.0) <= 0.001
        assert cfg.universe_gap_measurement_enabled is True


# ---------------------------------------------------------------------------
# AC-089-002 / AC-089-008 — 시나리오 2/5: 바이트 동등성 + ACTIVE 상태 불변식
# ---------------------------------------------------------------------------

_DETECTOR_NAMES = (
    "detect_theme_news_cluster",
    "detect_volume_surge_news_combo",
    "detect_disclosure_surge_pattern",
    "detect_immediate_disclosure_signal",
    "detect_news_delayed_response",
    "detect_volume_breakout",
    "detect_momentum_continuation",
)


def _make_theme_candidate() -> SurgeCandidate:
    return SurgeCandidate(
        stock_code="005930",
        stock_name="삼성전자테스트",
        theme_cluster_score=1.0,
        active_detectors=["theme_cluster"],
    )


def _make_combo_candidate() -> SurgeCandidate:
    return SurgeCandidate(
        stock_code="005930",
        stock_name="삼성전자테스트",
        combo_score=1.0,
        active_detectors=["volume_news_combo"],
    )


@contextlib.contextmanager
def _patch_pipeline_dependencies(with_candidate: bool):
    """7개 탐지기 + Naver 조회를 모킹한다. with_candidate=True면 theme+combo가 동일
    종목에 대해 항상 새 SurgeCandidate 인스턴스를 반환(재사용 mutation 오염 방지)."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch("app.services.naver_finance.fetch_volume_leaders_sync", return_value=[])
        )
        stack.enter_context(
            patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                return_value=[],
            )
        )
        for name in _DETECTOR_NAMES:
            if with_candidate and name == "detect_theme_news_cluster":
                stack.enter_context(
                    patch(
                        f"app.services.surge_detector.{name}",
                        side_effect=lambda *a, **kw: [_make_theme_candidate()],
                    )
                )
            elif with_candidate and name == "detect_volume_surge_news_combo":
                stack.enter_context(
                    patch(
                        f"app.services.surge_detector.{name}",
                        side_effect=lambda *a, **kw: [_make_combo_candidate()],
                    )
                )
            else:
                stack.enter_context(
                    patch(f"app.services.surge_detector.{name}", return_value=[])
                )
        yield


class TestByteEquivalenceAndActiveInvariant:
    def test_flag_off_matches_empty_detector_baseline(self, db: Session):
        """AC-089-002 / 시나리오 2: 계측 비활성(기본값) 시 출력이 M1 이전과 동일(빈 후보)."""
        cfg = get_surge_config().model_copy(update={"universe_gap_measurement_enabled": False})

        with _patch_pipeline_dependencies(with_candidate=False):
            candidates = gather_surge_candidates(db, [], cfg, [])

        assert candidates == []

    def test_flag_on_vs_off_produces_identical_qualified_candidates(self, db: Session):
        """AC-089-008 / 시나리오 5(REQ-AI089-003 HARD): 동일 fixture에 대해 계측
        OFF/ON 두 실행의 반환 SurgeCandidate 목록·앙상블 관련 필드가 완전히 동일하다."""
        cfg_off = get_surge_config().model_copy(
            update={"universe_gap_measurement_enabled": False}
        )
        cfg_on = get_surge_config().model_copy(
            update={"universe_gap_measurement_enabled": True}
        )

        with _patch_pipeline_dependencies(with_candidate=True):
            result_off = gather_surge_candidates(db, [], cfg_off, [])

        with _patch_pipeline_dependencies(with_candidate=True):
            result_on = gather_surge_candidates(db, [], cfg_on, [])

        assert len(result_off) == 1
        assert len(result_on) == 1
        assert result_off == result_on, (
            "REQ-AI089-003 위반: 계측 ON/OFF 사이에 탐지 후보 결과가 달라졌다"
        )

    def test_measurement_hook_never_mutates_merged(self):
        """정적 검증: 측정 훅 코드가 merged 딕셔너리를 재할당/갱신하지 않는다
        (REQ-AI089-003 [HARD] — test_spec_ai_086 C4 패턴과 동일한 방어)."""
        import inspect

        source = inspect.getsource(gather_surge_candidates)
        assert "measure_universe_detection_gap(" in source

        lines_with_gap_hook = [
            line for line in source.splitlines()
            if "measure_universe_detection_gap" in line or "_gap = " in line
        ]
        forbidden_patterns = ("merged[", "merged.update", "merged =")
        for line in lines_with_gap_hook:
            for pattern in forbidden_patterns:
                assert pattern not in line, (
                    f"REQ-AI089-003 위반: 측정 훅이 merged를 변경하는 코드 발견 — {line.strip()!r}"
                )


# ---------------------------------------------------------------------------
# AC-089-007 — 시나리오 4: 관측성 로그 라인 (REQ-007)
# ---------------------------------------------------------------------------

class TestObservabilityLogLine:
    def test_single_log_line_with_pool_summary_no_per_stock_detail(self, db: Session, caplog):
        """계측 활성화 시 측정 실행/소요시간/풀별 raw·커버 요약이 정확히 1줄 기록되고,
        종목코드(005930)는 로그에 나타나지 않는다(종목별 상세 로그 금지)."""
        cfg = get_surge_config().model_copy(update={"universe_gap_measurement_enabled": True})

        with (
            _patch_pipeline_dependencies(with_candidate=True),
            caplog.at_level(logging.INFO, logger="app.services.surge_detector"),
        ):
            gather_surge_candidates(db, [], cfg, [])

        gap_log_lines = [
            r.getMessage() for r in caplog.records if "[유니버스간극측정]" in r.getMessage()
        ]
        assert len(gap_log_lines) == 1, f"정확히 1줄이어야 하나 {len(gap_log_lines)}줄 기록됨"
        line = gap_log_lines[0]
        assert "실행됨" in line
        assert "005930" not in line, "종목별 상세 로그(개별 종목 코드)는 남기지 않아야 한다"
