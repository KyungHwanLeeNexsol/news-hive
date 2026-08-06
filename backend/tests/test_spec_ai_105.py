"""SPEC-AI-105: 급등예측 스캔 유니버스 bridge 후보 활성화 검증 — Shadow 정밀도 측정 게이트 —
인수조건 테스트.

- AC-105-001/002: persist_bridge_shadow_candidates() 일자당 replace semantics + composite PK 스키마.
- AC-105-003/004: shadow 계측이 기존 함수를 config override로 재호출하며 qualified/merged/마스터
  스위치에 무영향.
- AC-105-005/006: analyze_bridge_shadow_precision_by_date() pool 분리 반환 + division-by-zero guard.
- AC-105-007: 리포트에 pool_a/pool_c 분리 병기(blended 표시 금지).
- AC-105-008: pool_b 하드코딩 배제(반환값에 pool_b 부재 + fetch_stock_price_history_batch_sync 미호출).
- AC-105-009는 별도 회귀 스위트(test_spec_ai_092/096/102/104.py) 재실행으로 검증한다(본 파일 범위 밖).
"""

from __future__ import annotations

import contextlib
from datetime import date as _date
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_bridge_shadow_candidate import SurgeBridgeShadowCandidate

# SPEC-AI-100/101 소유 모델 — 이 모듈이 SurgeHorizonShadowObservation을 Base.metadata에
# 등록해야 test_engine(session-scoped)의 create_all()이 해당 테이블도 생성한다. 이
# import 없이 test_spec_ai_105.py를 단독 실행하면 gather_surge_candidates() 내부
# run_horizon_shadow_comparison()(무관 기존 기능, SPEC-AI-100/101 소유)의 실패 후
# db.rollback()이 같은 트랜잭션 내 앞서 flush된 데이터를 함께 되돌려 본 SPEC 테스트를
# 오염시킨다(회귀 코드 자체는 무수정, 테스트 격리 목적의 import만 추가).
from app.models.surge_horizon_shadow_observation import (  # noqa: F401
    SurgeHorizonShadowObservation,
)
from app.services.surge_bridge_shadow_service import persist_bridge_shadow_candidates
from app.services.surge_detector import (
    SurgeCandidate,
    gather_surge_candidates,
    generate_scan_universe_bridge_candidates,
)
from app.services.surge_universe_gap_service import analyze_bridge_shadow_precision_by_date
from app.surge_config.surge_settings import get_surge_config
from scripts.measure_universe_detection_gap_report import _render_report

# 전체 gather_surge_candidates() 파이프라인 무회귀 테스트에서 매 사이클 반복 사용하는
# 1차 탐지기 목록. test_spec_ai_104.py test_merged_key_set_byte_identical_...와 동일 패턴
# (naver_finance.fetch_volume_leaders_sync만 [] 고정하면 fetch_stock_price_history_batch_sync는
# 빈 코드 리스트로 안전 no-op 호출됨 — 별도 패치 불필요, 기존 회귀 테스트가 이미 증명).
_DETECTOR_NAMES: tuple[str, ...] = (
    "detect_theme_news_cluster",
    "detect_volume_surge_news_combo",
    "detect_disclosure_surge_pattern",
    "detect_immediate_disclosure_signal",
    "detect_news_delayed_response",
    "detect_volume_breakout",
    "detect_momentum_continuation",
)


def _add_disclosure(db: Session, stock_code: str, impact_score: float, *, suffix: str = "1") -> None:
    today_str = _date.today().strftime("%Y%m%d")
    db.add(
        Disclosure(
            corp_code=f"AI105{suffix}",
            corp_name=f"테스트기업105_{suffix}",
            stock_code=stock_code,
            report_name="테스트공시(SPEC-AI-105)",
            rcept_no=f"AI105{suffix.zfill(14)}",
            rcept_dt=today_str,
            url=f"https://dart.fss.or.kr/test105/{suffix}",
            impact_score=impact_score,
        )
    )
    db.flush()


def _add_actual_outcome(
    db: Session, trading_date: _date, stock_code: str, was_surge: bool
) -> None:
    db.add(
        SurgeActualOutcome(
            trading_date=trading_date,
            stock_code=stock_code,
            stock_name=f"종목_{stock_code}",
            change_rate=12.0 if was_surge else 1.0,
            was_surge=was_surge,
            market="KOSPI",
        )
    )


def _add_shadow_candidate(
    db: Session, trading_date: _date, stock_code: str, entry_pool: str, bridge_score: float = 0.5
) -> None:
    db.add(
        SurgeBridgeShadowCandidate(
            trading_date=trading_date,
            stock_code=stock_code,
            entry_pool=entry_pool,
            bridge_score=bridge_score,
        )
    )


# ---------------------------------------------------------------------------
# AC-105-001/002 — persist_bridge_shadow_candidates() 일자당 replace + composite PK 스키마
# ---------------------------------------------------------------------------


class TestSurgeBridgeShadowCandidateSchema:
    def test_composite_pk_and_column_types(self):
        """AC-105-002: composite PK (trading_date, stock_code) + entry_pool(String) +
        bridge_score(Float, not null)."""
        table = SurgeBridgeShadowCandidate.__table__
        pk_cols = set(table.primary_key.columns.keys())

        assert pk_cols == {"trading_date", "stock_code"}
        assert table.columns["entry_pool"].nullable is False
        assert table.columns["bridge_score"].nullable is False
        assert table.columns["bridge_score"].type.__class__.__name__ == "Float"


class TestPersistBridgeShadowCandidates:
    def test_replace_semantics_second_call_replaces_first(self, db: Session):
        """AC-105-001: 동일 trading_date에 두 번 연속 호출(예: 10:00 스캔 후 15:20 스캔) —
        첫 호출 레코드를 전량 삭제한 뒤 두 번째 호출 결과만 남는다."""
        today = _date.today()
        first = [
            SurgeCandidate(
                stock_code="911001", stock_name="A", entry_pool="pool_a", bridge_score=0.5
            )
        ]
        second = [
            SurgeCandidate(
                stock_code="911002", stock_name="B", entry_pool="pool_c", bridge_score=0.6
            )
        ]

        persist_bridge_shadow_candidates(db, today, first)
        persist_bridge_shadow_candidates(db, today, second)
        db.flush()

        rows = (
            db.query(SurgeBridgeShadowCandidate)
            .filter(SurgeBridgeShadowCandidate.trading_date == today)
            .all()
        )
        codes = {r.stock_code for r in rows}
        assert codes == {"911002"}

    def test_empty_candidates_persists_zero_rows_no_exception(self, db: Session):
        today = _date.today()
        count = persist_bridge_shadow_candidates(db, today, [])
        assert count == 0

    def test_duplicate_stock_code_in_input_deduped(self, db: Session):
        """SurgeUniverseMember.persist_universe_members() 관례 계승 — 동일 종목코드 중복
        입력 시 순서 보존 dedup(첫 항목만 유지)."""
        today = _date.today()
        candidates = [
            SurgeCandidate(
                stock_code="911003", stock_name="C1", entry_pool="pool_a", bridge_score=0.4
            ),
            SurgeCandidate(
                stock_code="911003", stock_name="C2", entry_pool="pool_a", bridge_score=0.9
            ),
        ]

        count = persist_bridge_shadow_candidates(db, today, candidates)
        db.flush()

        assert count == 1
        row = (
            db.query(SurgeBridgeShadowCandidate)
            .filter(SurgeBridgeShadowCandidate.stock_code == "911003")
            .one()
        )
        assert row.bridge_score == 0.4  # 첫 항목 유지


# ---------------------------------------------------------------------------
# AC-105-003/004 — shadow 계측이 동일 함수를 config override로 재호출하며 무영향
# ---------------------------------------------------------------------------


class TestShadowConfigOverride:
    def test_model_copy_override_does_not_mutate_original_config(self):
        """§Decisions D1: config.model_copy(update=...)는 원본 config를 변경하지 않는다."""
        base = get_surge_config()
        assert base.scan_universe_bridge_candidates_enabled is False

        shadow = base.model_copy(update={"scan_universe_bridge_candidates_enabled": True})

        assert shadow.scan_universe_bridge_candidates_enabled is True
        assert base.scan_universe_bridge_candidates_enabled is False


class TestShadowWiringNoRegression:
    def test_shadow_enabled_reuses_same_function_and_leaves_qualified_merged_byte_identical(
        self, db: Session
    ):
        """AC-105-003/004: shadow 계측이 generate_scan_universe_bridge_candidates()를
        (spy로 확인된) 동일 함수 참조로 재호출하며, qualified/merged 코드 집합이
        shadow_enabled=False일 때와 바이트 동등하고, 실행 후에도 원본
        config.scan_universe_bridge_candidates_enabled == False로 남는다."""

        def _run(shadow_enabled: bool) -> tuple[set[str], int]:
            cfg = get_surge_config().model_copy(
                update={"scan_universe_bridge_shadow_enabled": shadow_enabled}
            )
            with contextlib.ExitStack() as stack:
                stack.enter_context(
                    patch(
                        "app.services.naver_finance.fetch_volume_leaders_sync",
                        return_value=[],
                    )
                )
                for name in _DETECTOR_NAMES:
                    stack.enter_context(
                        patch(f"app.services.surge_detector.{name}", return_value=[])
                    )
                mock_gen = stack.enter_context(
                    patch(
                        "app.services.surge_detector.generate_scan_universe_bridge_candidates",
                        wraps=generate_scan_universe_bridge_candidates,
                    )
                )
                candidates = gather_surge_candidates(db, [], cfg, [])
            assert cfg.scan_universe_bridge_candidates_enabled is False  # AC-105-004
            return {c.stock_code for c in candidates}, mock_gen.call_count

        before_keys, before_call_count = _run(shadow_enabled=False)
        after_keys, after_call_count = _run(shadow_enabled=True)

        assert before_keys == after_keys  # AC-105-004: qualified 바이트 동등
        assert before_call_count == 1  # shadow OFF: 실제 bridge 호출 1회만
        # shadow ON: 실제 bridge 호출 + shadow 호출 = 동일 함수 참조 2회(AC-105-003 — 별도
        # 복제 함수 부재 확인).
        assert after_call_count == 2

    def test_shadow_enabled_with_real_pool_a_candidate_persists_shadow_row_but_leaves_qualified_untouched(
        self, db: Session
    ):
        """실제 pool_a 후보(오늘 공시 impact_score=80, min_score 0.3 통과)가 존재해도, shadow
        계측은 그 후보를 surge_bridge_shadow_candidates에 저장할 뿐 qualified에는 절대
        유입시키지 않는다(AC-105-004 — 실제 마스터 스위치가 여전히 False이므로)."""
        _add_disclosure(db, "911040", impact_score=80.0, suffix="1")

        cfg = get_surge_config().model_copy(
            update={"scan_universe_bridge_shadow_enabled": True}
        )
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.naver_finance.fetch_volume_leaders_sync",
                    return_value=[],
                )
            )
            for name in _DETECTOR_NAMES:
                stack.enter_context(
                    patch(f"app.services.surge_detector.{name}", return_value=[])
                )
            candidates = gather_surge_candidates(db, [], cfg, [])

        assert "911040" not in {c.stock_code for c in candidates}  # qualified 무영향
        assert cfg.scan_universe_bridge_candidates_enabled is False  # 마스터 스위치 무변경

        shadow_row = (
            db.query(SurgeBridgeShadowCandidate)
            .filter(SurgeBridgeShadowCandidate.stock_code == "911040")
            .first()
        )
        assert shadow_row is not None
        assert shadow_row.entry_pool == "pool_a"
        assert shadow_row.bridge_score >= 0.3


# ---------------------------------------------------------------------------
# AC-105-008 — pool_b는 shadow 계측 대상에서 하드코딩으로 배제된다
# ---------------------------------------------------------------------------


class TestPoolBHardcodedExclusion:
    def test_shadow_filtered_entry_pool_map_excludes_pool_b_and_skips_batch_fetch(
        self, db: Session
    ):
        """AC-105-008: scan_universe_bridge_pool_b_enabled=True(하위 플래그 켜짐)여도, shadow
        wiring이 수행하는 entry_pool_map 필터링(§Decisions D4) 이후에는 pool_b 후보가
        절대 생성되지 않고, fetch_stock_price_history_batch_sync가 호출되지 않는다."""
        base_config = get_surge_config().model_copy(
            update={"scan_universe_bridge_pool_b_enabled": True}
        )
        shadow_config = base_config.model_copy(
            update={"scan_universe_bridge_candidates_enabled": True}
        )
        entry_pool_map = {"911030": "pool_b", "911031": "pool_a"}
        # 실제 shadow wiring(surge_detector.py)이 수행하는 필터링을 그대로 재현한다.
        shadow_entry_pool_map = {
            code: pool for code, pool in entry_pool_map.items() if pool != "pool_b"
        }

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync"
        ) as mock_batch:
            result = generate_scan_universe_bridge_candidates(
                db,
                shadow_config,
                universe_codes=["911030", "911031"],
                entry_pool_map=shadow_entry_pool_map,
                merged={},
            )

        assert all(c.entry_pool != "pool_b" for c in result)
        mock_batch.assert_not_called()

    def test_pool_b_code_absent_from_filtered_map_never_reaches_candidate_codes(
        self, db: Session
    ):
        """entry_pool_map에서 제거된 pool_b 코드는 universe_codes에 남아있어도 후보 생성
        경로에 아예 진입하지 못한다(entry_pool_map.get(code) not in _target_pools)."""
        shadow_config = get_surge_config().model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": True,
                "scan_universe_bridge_pool_b_enabled": True,
            }
        )
        # pool_b 코드가 universe_codes에는 존재하지만 entry_pool_map에는 없다(필터링됨).
        result = generate_scan_universe_bridge_candidates(
            db,
            shadow_config,
            universe_codes=["911032"],
            entry_pool_map={},
            merged={},
        )

        assert result == []


# ---------------------------------------------------------------------------
# AC-105-005/006 — analyze_bridge_shadow_precision_by_date() pool 분리 반환 +
# division-by-zero guard
# ---------------------------------------------------------------------------


class TestAnalyzeBridgeShadowPrecisionByDate:
    def test_pool_a_pool_c_separated_matches_manual_calc(self, db: Session):
        """시나리오 1(acceptance.md): pool_a 1건(급등), pool_c 1건(미급등) → 분리 반환."""
        today = _date.today()
        _add_shadow_candidate(db, today, "005930", "pool_a", bridge_score=0.8)
        _add_shadow_candidate(db, today, "035420", "pool_c", bridge_score=0.4)
        _add_actual_outcome(db, today, "005930", was_surge=True)
        _add_actual_outcome(db, today, "035420", was_surge=False)
        db.flush()

        result = analyze_bridge_shadow_precision_by_date(db, today)

        assert result == {
            "pool_a": {"total": 1, "surge_count": 1, "precision": 1.0},
            "pool_c": {"total": 1, "surge_count": 0, "precision": 0.0},
        }

    def test_key_set_is_exactly_pool_a_pool_c_no_blended(self, db: Session):
        """AC-105-005: 반환 딕셔너리 키 집합이 정확히 {"pool_a", "pool_c"}임을 확인
        (blended 합산 키 없음)."""
        today = _date.today()
        result = analyze_bridge_shadow_precision_by_date(db, today)
        assert set(result.keys()) == {"pool_a", "pool_c"}

    def test_total_zero_returns_none_precision_no_exception(self, db: Session):
        """시나리오 2(acceptance.md): pool_a/pool_c 모두 shadow 후보 0건 → precision=None,
        0으로 나누기 예외 없음(AC-105-006)."""
        today = _date.today()

        result = analyze_bridge_shadow_precision_by_date(db, today)

        assert result == {
            "pool_a": {"total": 0, "surge_count": 0, "precision": None},
            "pool_c": {"total": 0, "surge_count": 0, "precision": None},
        }

    def test_pool_b_rows_if_present_are_excluded_from_totals(self, db: Session):
        """방어적 테스트: surge_bridge_shadow_candidates에 pool_b 행이 존재하더라도(정상
        경로에서는 발생하지 않음, AC-105-008) analyze_bridge_shadow_precision_by_date()는
        이를 집계하지 않는다."""
        today = _date.today()
        _add_shadow_candidate(db, today, "000001", "pool_b", bridge_score=0.5)
        db.flush()

        result = analyze_bridge_shadow_precision_by_date(db, today)

        assert set(result.keys()) == {"pool_a", "pool_c"}
        assert result["pool_a"]["total"] == 0
        assert result["pool_c"]["total"] == 0


# ---------------------------------------------------------------------------
# AC-105-007 — 리포트에 pool_a/pool_c 분리 병기(blended 표시 금지)
# ---------------------------------------------------------------------------


class TestReportBridgeShadowSection:
    def test_render_report_includes_bridge_shadow_section_with_separate_pool_rows(self):
        today = _date.today()
        bridge_shadow_results = [
            (
                today,
                {
                    "pool_a": {"total": 4, "surge_count": 2, "precision": 0.5},
                    "pool_c": {"total": 0, "surge_count": 0, "precision": None},
                },
            )
        ]

        report = _render_report([], [], bridge_shadow_results)

        assert "## Bridge Shadow 정밀도" in report
        assert "| T | pool_a | pool_c |" in report
        assert f"| {today} | 4/2/50.0% | 0/0/N/A |" in report

    def test_render_report_backward_compatible_when_bridge_shadow_arg_omitted(self):
        """AC-105-009 인접 회귀: 3번째 인자 없이(test_spec_ai_104.py의 기존 호출 시그니처)
        호출해도 예외 없이 렌더링되고 '표본 데이터 없음' placeholder가 표시된다."""
        report = _render_report([], [])

        assert "## Bridge Shadow 정밀도" in report
        assert "(표본 데이터 없음)" in report
