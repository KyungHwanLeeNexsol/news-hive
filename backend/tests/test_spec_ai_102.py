"""SPEC-AI-102: 급등예측 후보군 손실 구조 개선 — TASK-002/003/005/006 테스트.

AC-102-002: Pool 소싱 함수 단독 호출 동등성 (existing_codes 없이)
AC-102-003: build_scan_universe() 공개 시그니처·반환값 무회귀
AC-102-004: pool_b bridge 하위 플래그 OFF(기본) 시 완전 무회귀
AC-102-005: pool_b bridge ON 시 배치 조회 + 거래량 비율 점수화
AC-102-006: pool_b bridge 후보 수 상한 준수 (레거시 config 키 부재 폴백 포함)
AC-102-007: Pool B 루프 배치 전환 결과가 순차 판정 규칙과 동일
AC-102-008: Pool B 배치 조회 개별 실패가 나머지 판정을 막지 않음

AC-102-001(측정 근거 기록) / AC-102-009(미전환 지점 판단 근거)는 문서 기록 기준이라
plan.md / 커밋 메시지 / 소스 @MX 주석으로 검증한다(pytest 대상 아님).
"""

from __future__ import annotations

import inspect
from datetime import date as _date
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.surge_actual_outcome import SurgeActualOutcome
from app.services.surge_detector import (
    _BRIDGE_POOL_B_DEFAULT_LIMIT,
    SurgeCandidate,
    _assemble_scan_universe,
    _source_scan_universe_pools,
    build_scan_universe,
    generate_scan_universe_bridge_candidates,
)
from app.surge_config.surge_settings import SurgeDetectionConfig, get_surge_config


# ---------------------------------------------------------------------------
# 공용 fixture / 스텁
# ---------------------------------------------------------------------------


class _Bar:
    """fetch_stock_price_history_sync가 반환하는 PriceRecord 최소 스텁(volume만 사용)."""

    def __init__(self, volume: float):
        self.volume = volume


def _history(today_volume: float, baseline_volume: float = 100.0) -> list[_Bar]:
    """history[0]=당일, history[1:21]=baseline 20일치를 만든다."""
    return [_Bar(today_volume)] + [_Bar(baseline_volume) for _ in range(20)]


def _pool_b_codes(count: int, prefix: str = "3") -> list[str]:
    return [f"{prefix}{i:05d}" for i in range(count)]


def _make_pool_a_disclosures(db: Session, count: int, prefix: str = "1") -> list[str]:
    today_str = _date.today().strftime("%Y%m%d")
    codes = [f"{prefix}{i:05d}" for i in range(count)]
    for idx, code in enumerate(codes):
        db.add(
            Disclosure(
                corp_code=f"{idx:08d}",
                corp_name=f"테스트기업A_{idx}",
                stock_code=code,
                report_name="테스트공시(SPEC-AI-102)",
                rcept_no=f"A102{idx:012d}",
                rcept_dt=today_str,
                url=f"https://dart.fss.or.kr/test102/{idx}",
                impact_score=80.0,
            )
        )
    db.flush()
    return codes


def _make_pool_c_outcomes(db: Session, count: int, prefix: str = "2") -> list[str]:
    today = _date.today()
    codes = [f"{prefix}{i:05d}" for i in range(count)]
    for idx, code in enumerate(codes):
        db.add(
            SurgeActualOutcome(
                trading_date=today,
                stock_code=code,
                stock_name=f"테스트종목C_{idx}",
                change_rate=10.0,
                was_surge=True,
                market="KOSPI",
            )
        )
    db.flush()
    return codes


def _patch_pool_b_sourcing(codes: list[str], history_fn):
    """build_scan_universe Pool B 소싱을 통제하는 patch 3종.

    fetch_stock_price_history_batch_sync는 패치하지 않는다 — 내부적으로 워커 스레드에서
    fetch_stock_price_history_sync를 그대로 호출하므로(SPEC-AI-097 AC-097-005) 종목 단위
    패치만으로 배치 경로 전체가 통제된다. 이 성질이 곧 TASK-005 전환의 무회귀 근거다.
    """
    return (
        patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=codes,
        ),
        patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            side_effect=history_fn,
        ),
        patch(
            "app.services.stock_registry_service.fetch_tracked_stock_codes",
            return_value=None,
        ),
    )


@pytest.fixture
def base_config() -> SurgeDetectionConfig:
    return get_surge_config()


# ---------------------------------------------------------------------------
# AC-102-002 / AC-102-003 — TASK-002 함수 분리
# ---------------------------------------------------------------------------


class TestPoolSourcingSplit:
    """REQ-AI102-001: Pool 소싱 / existing 병합 분리."""

    def test_standalone_sourcing_matches_full_call(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """AC-102-002: existing_codes 없이 Pool 소싱만 단독 호출해도 동일 산출."""
        _make_pool_a_disclosures(db, 4)
        _make_pool_c_outcomes(db, 3)
        b_codes = _pool_b_codes(2)

        p1, p2, p3 = _patch_pool_b_sourcing(b_codes, lambda _c, pages=3: _history(500.0))
        with p1, p2, p3:
            (
                pool_a,
                pool_b,
                pool_c,
                pool_d,
                sourcing_map,
                max_universe,
            ) = _source_scan_universe_pools(db, base_config)

        p1, p2, p3 = _patch_pool_b_sourcing(b_codes, lambda _c, pages=3: _history(500.0))
        with p1, p2, p3:
            full_universe, full_map, full_counts = build_scan_universe(
                db, base_config, existing_codes=set()
            )

        # Pool A/B/C/D 리스트가 raw 집계와 정확히 일치해야 한다.
        assert full_counts["pool_a"] == len(pool_a)
        assert full_counts["pool_b"] == len(pool_b)
        assert full_counts["pool_c"] == len(pool_c)
        assert set(pool_b) == set(b_codes)
        assert pool_d == []

        # existing 태깅을 제외한 entry_pool_map이 동일해야 한다.
        assert sourcing_map == {
            k: v for k, v in full_map.items() if v != "existing"
        }
        # existing_codes=set()이면 "existing" 태깅이 하나도 없다(§D Edge Case).
        assert "existing" not in full_map.values()
        assert set(full_universe) <= set(pool_a) | set(pool_b) | set(pool_c)
        assert max_universe > 0

    def test_assemble_alone_produces_public_contract(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """AC-102-002 보강: 소싱 결과를 조립 함수에 넘기면 wrapper와 동일 계약."""
        _make_pool_a_disclosures(db, 3)
        b_codes = _pool_b_codes(2)

        p1, p2, p3 = _patch_pool_b_sourcing(b_codes, lambda _c, pages=3: _history(500.0))
        with p1, p2, p3:
            pool_a, pool_b, pool_c, pool_d, smap, cap = _source_scan_universe_pools(
                db, base_config
            )
        universe, emap, counts = _assemble_scan_universe(
            base_config, pool_a, pool_b, pool_c, pool_d, smap, cap, set()
        )
        assert isinstance(universe, list)
        assert isinstance(emap, dict)
        assert isinstance(counts, dict)
        assert set(universe) <= set(pool_a) | set(pool_b) | set(pool_c)

    def test_public_signature_unchanged(self):
        """AC-102-003: build_scan_universe() 공개 시그니처가 분리 이전과 동일."""
        sig = inspect.signature(build_scan_universe)
        assert list(sig.parameters) == ["db", "config", "existing_codes", "now"]
        assert sig.parameters["existing_codes"].default is None
        assert sig.parameters["now"].default is None

    def test_wrapper_is_thin(self):
        """AC-102-003 보강: wrapper가 두 내부 함수를 순서대로 호출하는 껍데기여야 한다."""
        src = inspect.getsource(build_scan_universe)
        assert src.index("_source_scan_universe_pools(") < src.index(
            "_assemble_scan_universe("
        )


# ---------------------------------------------------------------------------
# AC-102-007 / AC-102-008 — TASK-005 Pool B 루프 배치 전환
# ---------------------------------------------------------------------------


class TestPoolBBatchConversion:
    """REQ-AI102-004: Pool B 루프 배치 전환 무회귀."""

    def test_batch_result_matches_sequential_decision_rule(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """AC-102-007: 배치 전환 후에도 ratio>=2.0 판정 결과가 순차 방식과 동일.

        짝수 인덱스 종목만 ratio=5.0(통과), 홀수 인덱스는 ratio=1.0(탈락)이 되도록
        fixture를 구성해 "전량 통과/전량 탈락"으로는 드러나지 않는 필터링 동등성을
        검증한다.
        """
        codes = _pool_b_codes(20)
        expected_pass = {c for i, c in enumerate(codes) if i % 2 == 0}

        def _hist(code: str, pages: int = 3) -> list[_Bar]:
            idx = codes.index(code)
            return _history(500.0 if idx % 2 == 0 else 100.0)

        p1, p2, p3 = _patch_pool_b_sourcing(codes, _hist)
        with p1, p2, p3:
            _universe, entry_pool_map, counts = build_scan_universe(
                db, base_config, existing_codes=set()
            )

        actual_pass = {c for c, p in entry_pool_map.items() if p == "pool_b"}
        assert actual_pass == expected_pass
        assert counts["pool_b"] == len(expected_pass)

    def test_partial_fetch_failure_is_isolated(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """AC-102-008: 일부 종목 조회 실패가 나머지 판정/전체 완료를 막지 않는다."""
        codes = _pool_b_codes(20)
        failing = {codes[3], codes[11]}

        def _hist(code: str, pages: int = 3) -> list[_Bar]:
            if code in failing:
                raise RuntimeError("naver 404 (mock)")
            return _history(500.0)

        p1, p2, p3 = _patch_pool_b_sourcing(codes, _hist)
        with p1, p2, p3:
            _universe, entry_pool_map, counts = build_scan_universe(
                db, base_config, existing_codes=set()
            )

        passed = {c for c, p in entry_pool_map.items() if p == "pool_b"}
        assert passed == set(codes) - failing
        assert counts["pool_b"] == 18


# ---------------------------------------------------------------------------
# AC-102-004 / 005 / 006 — TASK-003 pool_b bridge 하위 플래그
# ---------------------------------------------------------------------------


def _bridge_inputs(
    pool_b_count: int = 5,
) -> tuple[list[str], dict[str, str], dict[str, SurgeCandidate]]:
    """pool_a 1개 + pool_b N개로 구성된 bridge 입력(모두 merged 미포함)."""
    b_codes = _pool_b_codes(pool_b_count)
    universe = ["100000"] + b_codes
    entry_pool_map = {"100000": "pool_a"}
    entry_pool_map.update({c: "pool_b" for c in b_codes})
    return universe, entry_pool_map, {}


class TestPoolBBridgeSubFlag:
    """REQ-AI102-002: bridge 후보화 pool_b 하위 플래그."""

    @pytest.mark.parametrize("master_enabled", [True, False])
    def test_sub_flag_off_is_byte_equivalent(
        self, db: Session, base_config: SurgeDetectionConfig, master_enabled: bool
    ):
        """AC-102-004: 하위 플래그 OFF면 마스터 스위치 값과 무관하게 pool_b 제외."""
        cfg = base_config.model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": master_enabled,
                "scan_universe_bridge_pool_b_enabled": False,
            }
        )
        universe, emap, merged = _bridge_inputs()

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync"
        ) as batch_mock:
            result = generate_scan_universe_bridge_candidates(
                db, cfg, universe, emap, merged
            )

        # pool_b 경로가 완전히 닫혀 있어야 한다 — 신규 HTTP 호출 자체가 없어야 함.
        batch_mock.assert_not_called()
        assert all(c.entry_pool != "pool_b" for c in result)

    def test_sub_flag_on_scores_pool_b_via_batch(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """AC-102-005: 두 플래그가 모두 ON이면 배치 조회 후 pool_b가 후보에 포함된다."""
        cfg = base_config.model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": True,
                "scan_universe_bridge_pool_b_enabled": True,
                "scan_universe_bridge_pool_limits": {"pool_a": 10, "pool_b": 5, "pool_c": 10},
            }
        )
        universe, emap, merged = _bridge_inputs(pool_b_count=3)
        b_codes = [c for c in universe if emap[c] == "pool_b"]

        def _batch(codes, pages=3):
            assert pages == 3
            return {c: _history(500.0) for c in codes}

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync",
            side_effect=_batch,
        ) as batch_mock:
            result = generate_scan_universe_bridge_candidates(
                db, cfg, universe, emap, merged
            )

        batch_mock.assert_called_once()
        assert set(batch_mock.call_args[0][0]) == set(b_codes)
        got = {c.stock_code for c in result if c.entry_pool == "pool_b"}
        assert got == set(b_codes)
        # ratio=5.0 → 5.0/6.0 정규화, _BRIDGE_MIN_SCORE(0.3) 초과
        for cand in result:
            if cand.entry_pool == "pool_b":
                assert 0.3 <= cand.bridge_score <= 1.0

    def test_below_min_ratio_is_not_promoted(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """AC-102-005 보강: ratio < 2.0이면 bridge 후보로 승격되지 않는다."""
        cfg = base_config.model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": True,
                "scan_universe_bridge_pool_b_enabled": True,
            }
        )
        universe, emap, merged = _bridge_inputs(pool_b_count=3)

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync",
            side_effect=lambda codes, pages=3: {c: _history(150.0) for c in codes},
        ):
            result = generate_scan_universe_bridge_candidates(
                db, cfg, universe, emap, merged
            )
        assert all(c.entry_pool != "pool_b" for c in result)

    def test_pool_b_limit_is_respected(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """AC-102-006: 상한(2)보다 후보(10)가 많아도 조회·승격 모두 상한을 넘지 않는다."""
        cfg = base_config.model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": True,
                "scan_universe_bridge_pool_b_enabled": True,
                "scan_universe_bridge_pool_limits": {"pool_a": 10, "pool_b": 2, "pool_c": 10},
            }
        )
        universe, emap, merged = _bridge_inputs(pool_b_count=10)

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync",
            side_effect=lambda codes, pages=3: {c: _history(500.0) for c in codes},
        ) as batch_mock:
            result = generate_scan_universe_bridge_candidates(
                db, cfg, universe, emap, merged
            )

        assert len(batch_mock.call_args[0][0]) <= 2
        assert sum(1 for c in result if c.entry_pool == "pool_b") <= 2

    def test_legacy_config_without_pool_b_key_falls_back_to_safe_default(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """§D Edge Case: "pool_b" 키 부재는 '무제한'이 아니라 보수적 기본값이다."""
        cfg = base_config.model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": True,
                "scan_universe_bridge_pool_b_enabled": True,
                # 레거시 config: pool_b 키 없음
                "scan_universe_bridge_pool_limits": {"pool_a": 10, "pool_c": 10},
            }
        )
        universe, emap, merged = _bridge_inputs(pool_b_count=12)

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync",
            side_effect=lambda codes, pages=3: {c: _history(500.0) for c in codes},
        ) as batch_mock:
            result = generate_scan_universe_bridge_candidates(
                db, cfg, universe, emap, merged
            )

        assert len(batch_mock.call_args[0][0]) <= _BRIDGE_POOL_B_DEFAULT_LIMIT
        assert (
            sum(1 for c in result if c.entry_pool == "pool_b")
            <= _BRIDGE_POOL_B_DEFAULT_LIMIT
        )

    def test_zero_pool_b_codes_does_not_call_batch(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """§D Edge Case: pool_b 종목이 0개면 빈 리스트 배치 호출을 시도하지 않는다."""
        cfg = base_config.model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": True,
                "scan_universe_bridge_pool_b_enabled": True,
            }
        )
        universe = ["100000"]
        emap = {"100000": "pool_a"}

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync"
        ) as batch_mock:
            result = generate_scan_universe_bridge_candidates(db, cfg, universe, emap, {})

        batch_mock.assert_not_called()
        assert all(c.entry_pool != "pool_b" for c in result)

    def test_batch_failure_does_not_propagate(
        self, db: Session, base_config: SurgeDetectionConfig
    ):
        """pool_b 배치 조회 실패가 bridge 생성 전체를 깨뜨리지 않는다(fail-open)."""
        cfg = base_config.model_copy(
            update={
                "scan_universe_bridge_candidates_enabled": True,
                "scan_universe_bridge_pool_b_enabled": True,
            }
        )
        universe, emap, merged = _bridge_inputs(pool_b_count=3)

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_batch_sync",
            side_effect=RuntimeError("network down (mock)"),
        ):
            result = generate_scan_universe_bridge_candidates(
                db, cfg, universe, emap, merged
            )
        assert all(c.entry_pool != "pool_b" for c in result)


class TestBridgeConfigDefaults:
    """REQ-AI102-002 기본값 계약."""

    def test_defaults_keep_pool_b_disabled(self):
        cfg = get_surge_config()
        assert cfg.scan_universe_bridge_pool_b_enabled is False
        assert cfg.scan_universe_bridge_pool_limits.get("pool_b") == 5
