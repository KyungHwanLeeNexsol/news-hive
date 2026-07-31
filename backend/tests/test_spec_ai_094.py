"""SPEC-AI-094: 스캔 유니버스 existing_codes 병합 필터 무효화 교정 — 인수조건 테스트.

AC-094-001: 플래그 활성 시 순수 existing이 유니버스에 포함된다 (절단 압력 없음)
AC-094-004: 절단 압력 하에서 existing은 우선순위 최하로 탈락한다
AC-094-005: 지표 이동 폭이 로깅된다 (existing_only / existing_included)

플래그 OFF 무회귀(AC-094-002/003/006)는 test_spec_ai_065.py / test_spec_ai_086.py /
test_spec_ai_074.py / test_spec_ai_089.py / test_spec_ai_092.py / test_spec_ai_070.py를
무수정으로 통과시키는 것으로 커버한다(plan.md TASK-005) — 이 파일은 플래그 ON 신규 동작만
다룬다.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.surge_config.surge_settings import get_surge_config
from app.services.surge_detector import build_scan_universe

# SPEC-AI-076 픽스처 헬퍼 재사용(TASK-004) — Pool A/B/C raw 후보 생성 + Pool B patch 3종
from tests.test_spec_ai_065 import (
    _make_pool_a_disclosures,
    _make_pool_b_codes,
    _make_pool_c_outcomes,
    _pool_b_patches,
)


class TestFlagOnNoTruncationPressure:
    """AC-094-001: 절단 압력 없음 + 플래그 ON → existing 5개 전부 포함, len == 35."""

    def test_pure_existing_included_when_flag_enabled(self, db: Session):
        pool_a_codes = _make_pool_a_disclosures(db, 10)
        pool_c_codes = _make_pool_c_outcomes(db, 12)
        pool_b_codes = _make_pool_b_codes(8)
        existing_codes = {f"9{i:05d}" for i in range(5)}

        cfg = get_surge_config().model_copy(
            update={
                "max_scan_universe": 150,
                "pool_b_min_slots": 20,
                "pool_c_min_slots": 30,
                "scan_universe_include_existing": True,
            }
        )

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with p1, p2, p3:
            final_universe, entry_pool_map, _counts = build_scan_universe(
                db, cfg, existing_codes=existing_codes
            )

        assert len(final_universe) == 35, (
            f"A(10)+B(8)+C(12)+existing(5)=35이어야 한다: got {len(final_universe)}"
        )
        assert existing_codes.issubset(set(final_universe)), (
            "existing 5개 전부가 final_universe에 포함되어야 한다(플래그 ON)"
        )
        for code in existing_codes:
            assert entry_pool_map.get(code) == "existing"
        # A/B/C 대표성은 SPEC-AI-076 계약대로 무영향이어야 한다
        for code in pool_a_codes:
            assert entry_pool_map.get(code) == "pool_a"
        for code in pool_b_codes:
            assert entry_pool_map.get(code) == "pool_b"
        for code in pool_c_codes:
            assert entry_pool_map.get(code) == "pool_c"

    def test_pure_existing_excluded_when_flag_disabled_same_input(self, db: Session):
        """동일 입력에서 플래그 OFF(기본값)면 existing은 여전히 배제된다(AC-076-004 보존 재확인)."""
        _make_pool_a_disclosures(db, 10)
        _make_pool_c_outcomes(db, 12)
        pool_b_codes = _make_pool_b_codes(8)
        existing_codes = {f"9{i:05d}" for i in range(5)}

        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 20, "pool_c_min_slots": 30}
        )
        assert cfg.scan_universe_include_existing is False

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with p1, p2, p3:
            final_universe, _map, _counts = build_scan_universe(
                db, cfg, existing_codes=existing_codes
            )

        assert len(final_universe) == 30
        assert not (set(final_universe) & existing_codes)


class TestFlagOnTruncationPressure:
    """AC-094-004: 절단 압력 있음(A=232/B=0/C=52/cap=150) + 플래그 ON →
    existing 태그 0개, len==150, Pool C 대표성(quota) 유지."""

    def test_existing_dropped_as_lowest_priority_under_truncation(self, db: Session):
        _make_pool_a_disclosures(db, 232)
        _make_pool_c_outcomes(db, 52)
        existing_codes = {f"9{i:05d}" for i in range(5)}

        cfg = get_surge_config().model_copy(
            update={
                "max_scan_universe": 150,
                "pool_b_min_slots": 20,
                "pool_c_min_slots": 30,
                "scan_universe_include_existing": True,
            }
        )

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=existing_codes
            )

        assert len(final_universe) == 150
        existing_represented = sum(
            1 for c in final_universe if entry_pool_map.get(c) == "existing"
        )
        assert existing_represented == 0, (
            "절단 압력 하에서 existing은 우선순위 최하로 전량 탈락해야 한다"
        )
        # Pool C의 quota 대표성(SPEC-AI-076 AC-076-001)은 existing 도입과 무관하게 유지된다.
        c_represented = sum(1 for c in final_universe if entry_pool_map.get(c) == "pool_c")
        assert c_represented >= min(52, cfg.pool_c_min_slots)


class TestExistingMetricShiftLogging:
    """AC-094-005: existing_only / existing_included 로그 필드가 기록된다(플래그 ON/OFF 2케이스)."""

    def test_logs_existing_only_and_included_flag_on(self, db: Session, caplog):
        _make_pool_a_disclosures(db, 10)
        _make_pool_c_outcomes(db, 12)
        pool_b_codes = _make_pool_b_codes(8)
        existing_codes = {f"9{i:05d}" for i in range(5)}

        cfg = get_surge_config().model_copy(
            update={
                "max_scan_universe": 150,
                "pool_b_min_slots": 20,
                "pool_c_min_slots": 30,
                "scan_universe_include_existing": True,
            }
        )

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with caplog.at_level(logging.INFO, logger="app.services.surge_detector"):
            with p1, p2, p3:
                build_scan_universe(db, cfg, existing_codes=existing_codes)

        universe_logs = [r.message for r in caplog.records if "최종 유니버스" in r.message]
        assert universe_logs, "최종 유니버스 로그 라인이 기록되어야 한다"
        log_line = universe_logs[-1]
        assert "existing_only=5" in log_line
        assert "existing_included=5" in log_line

    def test_logs_existing_only_nonzero_but_included_zero_flag_off(self, db: Session, caplog):
        """플래그 OFF(기본값)이면 existing_only는 관측 가능하되 existing_included는 항상 0."""
        _make_pool_a_disclosures(db, 10)
        _make_pool_c_outcomes(db, 12)
        pool_b_codes = _make_pool_b_codes(8)
        existing_codes = {f"9{i:05d}" for i in range(5)}

        cfg = get_surge_config().model_copy(
            update={"max_scan_universe": 150, "pool_b_min_slots": 20, "pool_c_min_slots": 30}
        )
        assert cfg.scan_universe_include_existing is False

        p1, p2, p3 = _pool_b_patches(pool_b_codes)
        with caplog.at_level(logging.INFO, logger="app.services.surge_detector"):
            with p1, p2, p3:
                build_scan_universe(db, cfg, existing_codes=existing_codes)

        universe_logs = [r.message for r in caplog.records if "최종 유니버스" in r.message]
        assert universe_logs, "최종 유니버스 로그 라인이 기록되어야 한다"
        log_line = universe_logs[-1]
        assert "existing_only=5" in log_line
        assert "existing_included=0" in log_line
