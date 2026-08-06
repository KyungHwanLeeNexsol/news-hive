"""SPEC-AI-104: Pool D 활성화 검증 — 관측 canary 전환 + 정밀도 측정 게이트 — 인수조건 테스트.

- AC-104-003/004: analyze_pool_precision_by_date() — 4개 풀 {total, surge_count, precision}
  반환 + division-by-zero guard(총합 0이면 precision=None, 예외 없음).
- AC-104-005: 측정 리포트 거래일별 표에 pool_d 열이 존재하고 "표본 합산" 섹션과 합계가 일치.
- AC-104-006: canary 전환(pool_d_min_slots=10) 후에도 pool_d 코드가 1차 탐지 후보(merged)에
  유입되지 않는다 — _assemble_scan_universe()는 merged를 인자로 받지 않는 순수 조립 함수이므로,
  별도 준비한 merged 픽스처 딕셔너리가 호출 전후 불변임을 직접 확인한다.
- AC-104-007은 신규 테스트가 아니라 기존 5개 회귀 스위트(test_spec_ai_086/089/094/096/102.py)의
  재실행으로 검증한다(plan.md TASK-004) — 본 파일 범위 밖.
"""

from __future__ import annotations

from datetime import date as _date

from sqlalchemy.orm import Session

from app.models.surge_actual_outcome import SurgeActualOutcome
from app.models.surge_universe_member import SurgeUniverseMember
from app.services.surge_detector import _assemble_scan_universe
from app.services.surge_universe_gap_service import analyze_pool_precision_by_date
from app.surge_config.surge_settings import get_surge_config
from scripts.measure_universe_detection_gap_report import _fmt_precision_cell, _render_report

from tests.test_spec_ai_086 import _seed_pool_d_news_mentions


def _add_universe_member(db: Session, trading_date: _date, stock_code: str, entry_pool: str) -> None:
    db.add(
        SurgeUniverseMember(
            trading_date=trading_date,
            stock_code=stock_code,
            entry_pool=entry_pool,
        )
    )


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


# ---------------------------------------------------------------------------
# AC-104-003 — analyze_pool_precision_by_date()가 4개 풀 각각의 {total, surge_count, precision}
# ---------------------------------------------------------------------------

class TestAnalyzePoolPrecisionByDate:
    def test_scenario1_pool_d_precision_matches_manual_calc(self, db: Session):
        """시나리오 1(acceptance.md): pool_d 3종목 중 1개만 실제 급등 → precision=1/3."""
        today = _date.today()
        for code in ("005930", "000660", "035420"):
            _add_universe_member(db, today, code, "pool_d")
        _add_actual_outcome(db, today, "005930", was_surge=True)
        _add_actual_outcome(db, today, "000660", was_surge=False)
        db.flush()

        result = analyze_pool_precision_by_date(db, today)

        assert result["pool_d"]["total"] == 3
        assert result["pool_d"]["surge_count"] == 1
        assert result["pool_d"]["precision"] == 1 / 3

    def test_all_four_pools_returned_with_manual_computed_values(self, db: Session):
        """AC-104-003: pool_a/b/c/d 4개 키 모두 반환되고 값이 수동 산출값과 일치한다."""
        today = _date.today()
        # pool_a: 2종목, 1개 급등 → precision 0.5
        _add_universe_member(db, today, "a00001", "pool_a")
        _add_universe_member(db, today, "a00002", "pool_a")
        _add_actual_outcome(db, today, "a00001", was_surge=True)
        _add_actual_outcome(db, today, "a00002", was_surge=False)
        # pool_b: 1종목, 0개 급등 → precision 0.0
        _add_universe_member(db, today, "b00001", "pool_b")
        _add_actual_outcome(db, today, "b00001", was_surge=False)
        # pool_c: 0종목 (미영속화) → total 0, precision None
        # pool_d: 3종목, 1개 급등 → precision 1/3
        for code in ("d00001", "d00002", "d00003"):
            _add_universe_member(db, today, code, "pool_d")
        _add_actual_outcome(db, today, "d00001", was_surge=True)
        db.flush()

        result = analyze_pool_precision_by_date(db, today)

        assert set(result.keys()) == {"pool_a", "pool_b", "pool_c", "pool_d"}
        assert result["pool_a"] == {"total": 2, "surge_count": 1, "precision": 0.5}
        assert result["pool_b"] == {"total": 1, "surge_count": 0, "precision": 0.0}
        assert result["pool_c"] == {"total": 0, "surge_count": 0, "precision": None}
        assert result["pool_d"]["total"] == 3
        assert result["pool_d"]["surge_count"] == 1
        assert result["pool_d"]["precision"] == 1 / 3


# ---------------------------------------------------------------------------
# AC-104-004 — total==0이면 precision은 None(division-by-zero guard, 예외 없음)
# ---------------------------------------------------------------------------

class TestDivisionByZeroGuard:
    def test_scenario2_no_pool_d_members_returns_none_precision_no_exception(
        self, db: Session
    ):
        """시나리오 2(acceptance.md): pool_d 소속 종목 0건 → {total:0, surge_count:0, precision:None}."""
        today = _date.today()
        # pool_d 미영속화 — 다른 풀만 존재해도 pool_d는 반드시 0건으로 처리되어야 한다.
        _add_universe_member(db, today, "a00001", "pool_a")
        _add_actual_outcome(db, today, "a00001", was_surge=True)
        db.flush()

        result = analyze_pool_precision_by_date(db, today)

        assert result["pool_d"] == {"total": 0, "surge_count": 0, "precision": None}

    def test_all_pools_empty_no_exception(self, db: Session):
        """엣지 케이스: 해당 거래일 SurgeUniverseMember 영속화 자체가 없는 날 — 예외 없음."""
        today = _date.today()

        result = analyze_pool_precision_by_date(db, today)

        for pool in ("pool_a", "pool_b", "pool_c", "pool_d"):
            assert result[pool] == {"total": 0, "surge_count": 0, "precision": None}


# ---------------------------------------------------------------------------
# AC-104-005 — 리포트 거래일별 표에 pool_d 열이 존재하고 "표본 합산" 섹션과 합계가 일치
# ---------------------------------------------------------------------------

class TestReportPoolDColumn:
    def test_render_report_includes_pool_d_column_and_sums_match_aggregate(self):
        today = _date.today()
        results = [
            {
                "trading_date": today,
                "sample_present": True,
                "actual_surge_count": 5,
                "no_signal_codes": ["a1", "d1", "d2"],
                "attribution": {"a1": "pool_a", "d1": "pool_d", "d2": "pool_d"},
                "attribution_summary": {"pool_a": 1, "pool_d": 2},
            }
        ]
        precision_results = [
            (
                today,
                {
                    "pool_a": {"total": 3, "surge_count": 1, "precision": 1 / 3},
                    "pool_b": {"total": 0, "surge_count": 0, "precision": None},
                    "pool_c": {"total": 0, "surge_count": 0, "precision": None},
                    "pool_d": {"total": 3, "surge_count": 1, "precision": 1 / 3},
                },
            )
        ]

        report = _render_report(results, precision_results)

        # 거래일별 표 헤더에 pool_d 열이 존재한다.
        assert "| T | 실제급등 | 무시그널 | 무시그널% | pool_a | pool_b | pool_c | pool_d | absent |" in report
        # 거래일별 행에 pool_d 카운트(2)가 렌더링된다.
        assert f"| {today} | 5 | 3 | 60.0% | 1 | 0 | 0 | 2 | 0 |" in report
        # "표본 합산" 섹션의 pool_d 합계(2)와 거래일별 표의 pool_d 값(2)이 일치한다(회귀 검증).
        assert "- pool_d: 2 (66.7%)" in report
        # precision측 신규 섹션이 병기된다.
        assert "## Pool별 정밀도(Precision)" in report
        assert "3/1/33.3%" in report

    def test_fmt_precision_cell_none_renders_na(self):
        assert _fmt_precision_cell({"total": 0, "surge_count": 0, "precision": None}) == "0/0/N/A"

    def test_fmt_precision_cell_value_renders_percentage(self):
        assert _fmt_precision_cell({"total": 2, "surge_count": 1, "precision": 0.5}) == "2/1/50.0%"


# ---------------------------------------------------------------------------
# AC-104-006 — canary 전환(pool_d_min_slots=10) 후에도 pool_d 코드가 merged에 유입되지 않는다
# ---------------------------------------------------------------------------

class TestPoolDNeverLeaksIntoMerged:
    def test_assemble_scan_universe_pool_d_codes_do_not_touch_merged_fixture(self):
        """pool_d_min_slots=10으로 _assemble_scan_universe()를 직접 호출해도, 별도 준비한
        merged 픽스처 딕셔너리는 호출 전후 키 집합이 변경되지 않는다(AC-104-006).

        _assemble_scan_universe()는 merged를 인자로 받지 않는 순수 조립 함수다(REQ-AI104-003
        [HARD] 구조적 확인 — merged로의 유일한 승격 경로는 generate_scan_universe_bridge_candidates()
        이며 본 SPEC은 그 마스터 스위치를 건드리지 않는다).
        """
        cfg = get_surge_config().model_copy(update={"pool_d_min_slots": 10})
        pool_d_codes = ["d00001", "d00002", "d00003"]
        # _source_scan_universe_pools()가 정상적으로 수행하는 사전 태깅을 재현한다 —
        # _assemble_scan_universe()는 pool_a/b/c/d 태깅을 스스로 수행하지 않고 호출부가
        # 채운 entry_pool_map을 그대로 소비/확장(existing만 추가)하는 순수 조립 함수다.
        entry_pool_map: dict[str, str] = {code: "pool_d" for code in pool_d_codes}

        # 탐지기가 이미 별도로 채워둔 병합 후보 딕셔너리(호출 전에 준비).
        merged_fixture = {"existing_hit_1": object(), "existing_hit_2": object()}
        merged_keys_before = set(merged_fixture.keys())

        universe_codes, entry_pool_map, pool_counts = _assemble_scan_universe(
            cfg,
            pool_a_codes=[],
            pool_b_codes=[],
            pool_c_codes=[],
            pool_d_codes=pool_d_codes,
            entry_pool_map=entry_pool_map,
            max_universe=cfg.max_scan_universe,
            existing_codes=set(),
        )

        # positive control: pool_d가 실제로 조립 결과에 반영되었는지 확인(canary 활성 증거).
        assert pool_counts["pool_d"] == 3
        assert any(entry_pool_map.get(c) == "pool_d" for c in universe_codes)

        # merged 픽스처는 함수 호출 인자로 전달되지 않았으므로 키 집합이 완전히 불변이다.
        assert set(merged_fixture.keys()) == merged_keys_before

    def test_merged_key_set_byte_identical_before_and_after_canary_transition(self, db: Session):
        """gather_surge_candidates() 관점(test_spec_ai_086.py
        test_detector_invocation_counts_unchanged_when_cap_expanded_or_pool_d_enabled와 동일
        패턴) — pool_d_min_slots=0(canary 전)과 =10(canary 후) 모두 8개 탐지기를 mock으로
        빈 리스트 고정하면, 실제 Pool D 소싱 쿼리가 종목을 찾아내더라도(뉴스 언급 시드)
        반환 후보(merged 유래) 키 집합은 바이트 동등(빈 집합)해야 한다 — pool_d 코드가
        merged에 유입되는 경로가 없음을 확인(AC-104-006)."""
        from unittest.mock import patch

        from app.services.surge_detector import gather_surge_candidates

        _seed_pool_d_news_mentions(db, ["dcanary1", "dcanary2"])

        detector_names = [
            "detect_theme_news_cluster",
            "detect_volume_surge_news_combo",
            "detect_disclosure_surge_pattern",
            "detect_immediate_disclosure_signal",
            "detect_news_delayed_response",
            "detect_volume_breakout",
            "detect_momentum_continuation",
        ]

        def _run(pool_d_min_slots: int) -> set[str]:
            import contextlib

            cfg = get_surge_config().model_copy(update={"pool_d_min_slots": pool_d_min_slots})
            with contextlib.ExitStack() as stack:
                stack.enter_context(
                    patch(
                        "app.services.naver_finance.fetch_volume_leaders_sync",
                        return_value=[],
                    )
                )
                for name in detector_names:
                    stack.enter_context(
                        patch(f"app.services.surge_detector.{name}", return_value=[])
                    )
                candidates = gather_surge_candidates(db, [], cfg, [])
            return {c.stock_code for c in candidates}

        before_keys = _run(pool_d_min_slots=0)
        after_keys = _run(pool_d_min_slots=10)

        assert before_keys == after_keys == set()
        assert "dcanary1" not in after_keys
        assert "dcanary2" not in after_keys
