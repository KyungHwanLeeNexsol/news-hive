"""SPEC-AI-096: 급등예측 스캔 유니버스 파이프라인 — 캡·절단·단계적 활성화 정책.

AC-096-001/002: Pool D 관측 영속화(pool_d_count 신규 컬럼 + 하위 호환)
AC-096-003/004: max_scan_universe 기본값 150→250 + clamp 무수정(no-op)
AC-096-005/006/007: price-fetch 사전절단 pool 소속 후보 면제 + 경고 로그
AC-096-008: Pool D 활성화 기준 — canary 값(10)이 코드 변경 없이 동작
AC-096-009: bridge 활성화 기준 — flag True 전환이 코드 변경 없이 동작
AC-096-010: 기본 설정 조합(cap=150 고정)에서 무회귀 — 전체 회귀 스위트로 커버
"""

from __future__ import annotations

import logging
import os
from datetime import date as _date

from sqlalchemy.orm import Session

from app.models.surge_universe_pool_history import SurgeUniversePoolHistory
from app.services.surge_detector import (
    SurgeCandidate,
    _apply_price_fetch_truncation,
    _resolve_scan_universe_cap,
    generate_scan_universe_bridge_candidates,
)
from app.services.surge_universe_pool_service import (
    get_pool_counts_for_date,
    persist_pool_counts,
)
from app.surge_config.surge_settings import SurgeDetectionConfig, get_surge_config

from tests.test_spec_ai_086 import _seed_pool_d_news_mentions


# ---------------------------------------------------------------------------
# AC-096-001/002 — pool_d_count 신규 컬럼 영속화 + 하위 호환
# ---------------------------------------------------------------------------

class TestPoolDCountPersistence:
    """AC-096-001: pool_d_count 신규 컬럼이 마이그레이션으로 존재하고 영속화된다."""

    def test_persist_pool_counts_stores_pool_d_count(self, db: Session):
        payload = {
            "pool_a": 3,
            "pool_b": 2,
            "pool_c": 1,
            "pool_d": 4,
            "scan_universe_size": 10,
        }
        persist_pool_counts(db, _date.today(), payload)
        db.commit()

        loaded = get_pool_counts_for_date(db, _date.today())
        assert loaded is not None
        assert loaded["pool_d"] == 4

    def test_new_row_pool_d_count_defaults_to_zero(self, db: Session):
        """신규 행 직접 INSERT 시 pool_d_count 기본값이 0이어야 한다."""
        row = SurgeUniversePoolHistory(date=_date(2020, 1, 1))
        db.add(row)
        db.flush()

        assert row.pool_d_count == 0

    def test_alembic_revision_chain_070_to_071(self):
        """alembic heads/history -r 070:071 정적 리비전 체인 검증."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
        cfg = Config(ini_path)
        script = ScriptDirectory.from_config(cfg)

        rev = script.get_revision("071_surge_universe_pool_history_pool_d")
        assert rev is not None
        assert rev.down_revision == "070_surge_pred_eval_high_based"
        assert "071_surge_universe_pool_history_pool_d" in script.get_heads()


class TestPoolDKeyBackwardCompat:
    """AC-096-002: pool_d 키 누락 시 하위 호환(0으로 처리), 예외 없음."""

    def test_persist_pool_counts_without_pool_d_key_defaults_to_zero(self, db: Session):
        # SPEC-AI-065 시절 호출부 형태(pool_d 키 없음)를 그대로 재현
        legacy_payload = {"pool_a": 3, "pool_b": 2, "pool_c": 1, "scan_universe_size": 6}

        persist_pool_counts(db, _date.today(), legacy_payload)
        db.commit()

        loaded = get_pool_counts_for_date(db, _date.today())
        assert loaded is not None
        assert loaded["pool_d"] == 0
        assert "pool_d" in loaded

    def test_get_pool_counts_for_date_includes_pool_d_key(self, db: Session):
        persist_pool_counts(
            db,
            _date.today(),
            {"pool_a": 1, "pool_b": 0, "pool_c": 0, "pool_d": 7, "scan_universe_size": 1},
        )
        db.commit()

        loaded = get_pool_counts_for_date(db, _date.today())
        assert loaded is not None
        assert loaded["pool_d"] == 7


# ---------------------------------------------------------------------------
# AC-096-003/004 — max_scan_universe 기본값 250 + clamp 무수정
# ---------------------------------------------------------------------------

class TestMaxScanUniverseDefaultAndClamp:
    def test_pydantic_field_default_max_scan_universe_is_250(self):
        """SurgeDetectionConfig는 필수 중첩 필드가 있어 인자 없이 인스턴스화할 수 없으므로
        (theme_cluster 등), 필드 레벨 기본값을 직접 검사한다(get_surge_config()가 실제
        인스턴스화 경로는 아래 test_yaml_loaded_config_max_scan_universe_is_250이 커버)."""
        field = SurgeDetectionConfig.model_fields["max_scan_universe"]
        assert field.default == 250

    def test_yaml_loaded_config_max_scan_universe_is_250(self):
        cfg = get_surge_config()
        assert cfg.max_scan_universe == 250

    def test_resolve_scan_universe_cap_no_op_at_default_250(self):
        """clamp [50,600] 범위 내이므로 250은 그대로 반환된다(no-op)."""
        cfg = get_surge_config()
        assert _resolve_scan_universe_cap(cfg) == 250

    def test_clamp_still_applies_when_out_of_range(self, caplog):
        """clamp 로직 자체는 무수정 — 범위를 벗어나는 별도 설정에는 여전히 clamp가 적용된다."""
        cfg = get_surge_config().model_copy(update={"max_scan_universe": 5000})
        with caplog.at_level(logging.WARNING, logger="app.services.surge_detector"):
            resolved = _resolve_scan_universe_cap(cfg)
        assert resolved == 600
        assert any("clamp" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# AC-096-005/006/007 — price-fetch 사전절단 pool 소속 후보 면제
# ---------------------------------------------------------------------------

def _make_candidate(code: str, entry_pool: str = "existing", score: float = 0.0) -> SurgeCandidate:
    """theme_cluster_score(가중치 0.19)만 채워 _pre_score가 score*0.19로 결정론적이 되게 한다."""
    return SurgeCandidate(
        stock_code=code,
        stock_name=f"종목_{code}",
        entry_pool=entry_pool,
        theme_cluster_score=score,
    )


class TestPriceFetchTruncationPoolExemption:
    """AC-096-005: pool 소속 후보는 사전절단에서 면제된다(절단 자체가 발생하지 않는 케이스)."""

    def test_no_truncation_when_existing_subset_below_cap(self):
        merged = {}
        for i in range(40):
            code = f"p{i:05d}"
            merged[code] = _make_candidate(code, entry_pool="pool_a", score=1.0)
        for i in range(20):
            code = f"e{i:05d}"
            merged[code] = _make_candidate(code, entry_pool="existing", score=float(i))

        assert len(merged) == 60  # > 50, 절단 로직 진입

        result = _apply_price_fetch_truncation(merged)

        # existing 20개는 50 미만이라 절단 없음 — 전체 60개 그대로 생존
        assert len(result) == 60
        assert set(result.keys()) == set(merged.keys())


class TestPriceFetchTruncationActualCut:
    """AC-096-006: existing 후보만 실제로 절단된다(절단 발생 케이스)."""

    def test_pool_members_survive_existing_truncated_to_top_50(self):
        merged = {}
        pool_codes = []
        for i in range(40):
            code = f"p{i:05d}"
            pool_codes.append(code)
            # pool 소속은 사전점수와 무관하게 전원 생존해야 하므로 낮은 점수로 설정
            merged[code] = _make_candidate(code, entry_pool="pool_b", score=0.01)

        existing_codes_by_score = []
        for i in range(80):
            code = f"e{i:05d}"
            score = float(i)  # 0..79, 유니크 오름차순
            existing_codes_by_score.append((code, score))
            merged[code] = _make_candidate(code, entry_pool="existing", score=score)

        assert len(merged) == 120  # > 50, 절단 로직 진입

        result = _apply_price_fetch_truncation(merged)

        assert len(result) == 90  # 40(pool 전원) + 50(existing 상위)

        # pool 소속 40개 전원 생존(사전점수와 무관)
        for code in pool_codes:
            assert code in result, f"pool 소속 {code}는 절단되면 안 된다"

        # existing은 사전점수 내림차순 상위 50개만 생존 (score 30..79가 상위 50개)
        expected_survivors = {code for code, score in existing_codes_by_score if score >= 30.0}
        expected_discarded = {code for code, score in existing_codes_by_score if score < 30.0}
        assert len(expected_survivors) == 50
        assert len(expected_discarded) == 30

        for code in expected_survivors:
            assert code in result, f"existing 상위 후보 {code}는 생존해야 한다"
        for code in expected_discarded:
            assert code not in result, f"existing 하위 후보 {code}는 폐기되어야 한다"


class TestPriceFetchTruncationWarningLog:
    """AC-096-007: pool 소속 후보 과다 시 경고 로그가 남는다."""

    def test_warning_logged_when_pool_member_count_exceeds_threshold(self, caplog):
        merged = {}
        for i in range(201):  # 경고 임계값(200) 초과
            code = f"p{i:05d}"
            merged[code] = _make_candidate(code, entry_pool="pool_c", score=0.0)
        for i in range(10):
            code = f"e{i:05d}"
            merged[code] = _make_candidate(code, entry_pool="existing", score=float(i))

        with caplog.at_level(logging.WARNING, logger="app.services.surge_detector"):
            _apply_price_fetch_truncation(merged)

        assert any(
            "pool" in r.message.lower() and "200" in r.message
            for r in caplog.records
        ), "pool 소속 후보 과다 시 경고 로그가 남아야 한다"

    def test_no_warning_when_pool_member_count_below_threshold(self, caplog):
        merged = {}
        for i in range(40):
            code = f"p{i:05d}"
            merged[code] = _make_candidate(code, entry_pool="pool_a", score=0.0)
        for i in range(20):
            code = f"e{i:05d}"
            merged[code] = _make_candidate(code, entry_pool="existing", score=float(i))

        with caplog.at_level(logging.WARNING, logger="app.services.surge_detector"):
            _apply_price_fetch_truncation(merged)

        assert not any(
            "급증" in r.message or "200" in r.message for r in caplog.records
        )


# ---------------------------------------------------------------------------
# AC-096-008 — Pool D 활성화 기준이 코드 변경 없이 canary 값을 받아들인다
# ---------------------------------------------------------------------------

class TestPoolDCanaryActivationNoCodeChange:
    def test_pool_d_min_slots_canary_value_10_sources_without_code_change(self, db: Session):
        """pool_d_min_slots를 0→10(제안 canary 값)으로만 변경 — 기존
        `if config.pool_d_min_slots > 0:` 게이트가 코드 변경 없이 소싱 쿼리를 실행한다."""
        from unittest.mock import patch

        from app.services.surge_detector import build_scan_universe

        pool_d_codes = [f"d{i:05d}" for i in range(15)]
        _seed_pool_d_news_mentions(db, pool_d_codes)

        cfg = get_surge_config().model_copy(update={"pool_d_min_slots": 10})

        with patch(
            "app.services.naver_finance.fetch_volume_leaders_sync",
            return_value=[],
        ):
            final_universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert pool_counts["pool_d"] == 15
        pool_d_represented = sum(
            1 for c in final_universe if entry_pool_map.get(c) == "pool_d"
        )
        assert pool_d_represented >= 10


# ---------------------------------------------------------------------------
# AC-096-009 — bridge 활성화 기준이 코드 변경 없이 canary 값을 받아들인다
# ---------------------------------------------------------------------------

class TestBridgeCanaryActivationNoCodeChange:
    def test_bridge_flag_false_to_true_only_sources_without_code_change(
        self, db: Session, make_stock
    ):
        """scan_universe_bridge_candidates_enabled를 False→True로만 변경 — 그 외 어떤
        코드도 수정하지 않고 generate_scan_universe_bridge_candidates가 정상 실행되어
        attribution(active_detectors)을 유지하는 후보를 반환한다."""
        from datetime import date, timedelta

        from app.models.surge_actual_outcome import SurgeActualOutcome

        make_stock(name="AC096브리지종목", stock_code="931009")
        prev_day = date.today() - timedelta(days=1)
        db.add(
            SurgeActualOutcome(
                trading_date=prev_day,
                stock_code="931009",
                stock_name="AC096브리지종목",
                change_rate=10.0,
                was_surge=False,
                market="KOSPI",
            )
        )
        db.commit()

        cfg = get_surge_config().model_copy(
            update={"scan_universe_bridge_candidates_enabled": True}
        )

        result = generate_scan_universe_bridge_candidates(
            db,
            cfg,
            universe_codes=["931009"],
            entry_pool_map={"931009": "pool_c"},
            merged={},
        )

        assert len(result) == 1
        candidate = result[0]
        assert "scan_universe_bridge" in candidate.active_detectors
        assert "pool_c" in candidate.active_detectors


# ---------------------------------------------------------------------------
# AC-096-010 — 기본 설정 조합(cap=150 고정)에서 최종 후보 집합 무회귀
# ---------------------------------------------------------------------------

class TestNoRegressionAtFixedCap150:
    """pool_d_min_slots=0, scan_universe_bridge_candidates_enabled=False 상태에서
    max_scan_universe를 150으로 고정하면 REQ-AI096-001 적용 이전과 동일해야 한다.

    핵심 회귀 검증은 test_spec_ai_065/086/089/092/094.py 전체 스위트(캡 파라미터를
    150으로 명시 오버라이드)가 이미 담당한다(§C 검증 계획). 여기서는 SPEC-AI-096이
    Pool D/bridge 기본값 및 clamp 로직에 손대지 않았음을 직접 재확인한다.
    """

    def test_default_pool_d_and_bridge_flags_remain_off(self):
        cfg = get_surge_config()
        assert cfg.pool_d_min_slots == 0
        assert cfg.scan_universe_bridge_candidates_enabled is False

    def test_price_fetch_truncation_is_no_op_below_cap(self):
        """merged가 _MAX_PRICE_FETCH_CANDIDATES(50) 이하이면 무수정으로 반환한다."""
        merged = {
            f"e{i:05d}": _make_candidate(f"e{i:05d}", entry_pool="existing", score=float(i))
            for i in range(50)
        }
        result = _apply_price_fetch_truncation(merged)
        assert result is merged  # 동일 객체 반환(no-op) — 원본 merged를 새로 만들지 않음
