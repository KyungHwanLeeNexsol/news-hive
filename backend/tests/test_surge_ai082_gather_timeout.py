"""SPEC-AI-082: gather_surge_candidates 글로벌 타임아웃 오폐기 특성화 및 회귀 테스트.

DDD ANALYZE-PRESERVE-IMPROVE (재현-우선, CLAUDE.md Rule 4):

- RED (수정 전, ANALYZE 단계 특성화): `_GATHER_TIMEOUT_S`가 `_gather_surge_candidates()`
  함수 본문 내부의 리터럴로 선언되어 있어(spec.md §2 [E-1]) 모듈 속성으로 존재하지 않는다.
  이 전제 자체가 재현 테스트 작성을 가로막는 오폐기 버그의 근본 원인이므로,
  `TestTimeoutConstantPromotion`의 첫 assertion은 IMPROVE(모듈 상수 승격) 이전에는
  실패해야 한다 — 이 실패가 RED 증거다.
- GREEN (수정 후): `_GATHER_TIMEOUT_S`를 모듈 상수로 승격 + 300→1200 상향한 이후에는 동일
  assertion이 통과하고, 승격으로 가능해진 monkeypatch 주입을 이용해 오폐기 재현
  (AC-082-002 RED), 오폐기 없음(AC-082-002 GREEN), 안전망 보존(AC-082-003), 값 회귀 가드
  (AC-082-001), 로그 포맷 보존(AC-082-007)을 검증한다.

주의: 실제 12~15분 HTTP 지연은 재현하지 않는다. 소형 주입 타임아웃 + 블로킹 mock(sync
time.sleep, executor 스레드에서 실행)으로 래퍼의 타임아웃 경계 거동을 결정적으로 구동한다
(plan.md §3, acceptance.md AC-082-002/004). 범위: `_gather_surge_candidates` 래퍼의
타임아웃 값만 검증 — 탐지 본체·앙상블·유니버스·매매 로직은 변경/검증 대상이 아니다
(REQ-AI082-006).
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.sector import Sector
from app.models.stock import Stock
from app.services import fund_manager
from app.services.fund_manager import _gather_surge_candidates
from app.services.surge_detector import SurgeCandidate


# ---------------------------------------------------------------------------
# 공통 픽스처 / 헬퍼
# ---------------------------------------------------------------------------

@pytest.fixture
def sector_ai082(db: Session) -> Sector:
    """SPEC-AI-082 테스트 전용 섹터."""
    s = Sector(name="SPEC-AI-082테스트섹터")
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def stock_ai082(db: Session, sector_ai082: Sector) -> Stock:
    """SPEC-AI-082 테스트 전용 종목."""
    stock = Stock(
        name="AI082테스트종목",
        stock_code="900082",
        sector_id=sector_ai082.id,
        market_cap=500,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_bypass_candidate(stock: Stock) -> SurgeCandidate:
    """품질 floor를 우회(strong_single_bypass)하는 mock 후보.

    theme_cluster_score>=0.85 + combo_score>0.1 조합은 fund_manager.py의
    품질 floor 게이트를 우회한다(test_surge_ai080_fund_manager.py와 동일 패턴 재사용) —
    본 테스트의 관심사는 품질 게이트 로직이 아니라 타임아웃 래퍼 거동이므로, 이미 검증된
    bypass 조합을 그대로 차용해 candidate가 결과에 반드시 반영되도록 한다.
    """
    return SurgeCandidate(
        stock_code=stock.stock_code,
        stock_name=stock.name,
        theme_cluster_score=0.9,
        combo_score=0.9,
        active_detectors=["theme_cluster", "volume_news_combo"],
    )


def _blocking_gather(delay_s: float, candidates: list[SurgeCandidate]):
    """gather_surge_candidates를 대체하는 블로킹 mock.

    _gather_surge_candidates()는 이 함수를 loop.run_in_executor(None, ...)로 스레드풀에서
    동기 실행하므로, time.sleep으로 실제 소요 시간을 결정적으로 모사할 수 있다(실 HTTP
    지연 없이 타임아웃 경계를 구동, plan.md §3).
    """

    def _fn(*args, **kwargs):
        time.sleep(delay_s)
        return candidates

    return _fn


# ---------------------------------------------------------------------------
# RED -> GREEN: 타임아웃 값의 모듈 상수 승격 (REQ-AI082-004, AC-082-004, AC-082-001)
# ---------------------------------------------------------------------------

class TestTimeoutConstantPromotion:
    """ANALYZE 단계 특성화: 타임아웃 값이 외부에서 관찰/주입 가능한 형태인지 확인.

    RED(수정 전): `_GATHER_TIMEOUT_S`는 `_gather_surge_candidates()` 함수 본문 내부의
    리터럴이라 모듈 속성으로 존재하지 않는다 — 아래 assertion은 승격 전에는 실패한다.
    GREEN(수정 후): 모듈 상수로 승격되면 hasattr이 True가 되고 monkeypatch로 실제 타임아웃
    분기를 결정적으로 구동할 수 있다.
    """

    def test_gather_timeout_constant_is_module_level_and_injectable(self) -> None:
        assert hasattr(fund_manager, "_GATHER_TIMEOUT_S"), (
            "SPEC-AI-082 [E-1]: _GATHER_TIMEOUT_S가 모듈 상수로 승격되어야 monkeypatch "
            "가능하다 (현재는 _gather_surge_candidates() 함수 본문 내부 리터럴이라 "
            "외부에서 관찰/주입이 불가능하다)"
        )

    def test_gather_timeout_constant_value_at_least_1200s(self) -> None:
        """AC-082-001: 프로덕션 상수 값이 문서화된 정상 실행 시간(12~15분)을 여유 있게
        상회하는 >= 1200s(20분)임을 값 회귀 가드로 고정한다."""
        assert fund_manager._GATHER_TIMEOUT_S >= 1200, (
            "현행 300s(5분)는 문서화된 정상 실행 시간 상단(15분/900s)의 1/3에 불과하다 "
            "(spec.md §1). 1200s(20분) 미만으로 회귀해서는 안 된다."
        )


# ---------------------------------------------------------------------------
# AC-082-002: 오폐기 재현(RED) → 교정(GREEN)
# ---------------------------------------------------------------------------

class TestGatherTimeoutDiscardReproduction:
    """핵심 재현 시나리오 — 2026-07-20 프로덕션 10:00 KST 잡의 "타임아웃 초과 → 0개 후보"
    오폐기를, 소형 주입 타임아웃 + 블로킹 mock으로 대리 재현한다(spec.md §1 라이브 증거)."""

    @pytest.mark.asyncio
    async def test_reproduce_spurious_empty_discard_when_timeout_too_small(
        self, db: Session, stock_ai082: Stock
    ) -> None:
        """RED: 적용 타임아웃(0.05s)보다 오래 블로킹(0.3s)하는 mock — 실제 후보가 있음에도
        빈 리스트가 반환된다(오폐기 재현, REQ-AI082-005)."""
        candidate = _make_bypass_candidate(stock_ai082)
        with (
            patch.object(fund_manager, "_GATHER_TIMEOUT_S", 0.05),
            patch(
                "app.services.fund_manager.gather_surge_candidates",
                side_effect=_blocking_gather(0.3, [candidate]),
            ),
        ):
            result = await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        assert result == [], (
            "적용 타임아웃(0.05s)보다 mock 소요(0.3s)가 크면 asyncio.TimeoutError로 실제 "
            "후보가 있음에도 빈 리스트가 반환되어야 한다(오폐기 거동 재현, spec.md §2 [E-2])"
        )

    @pytest.mark.asyncio
    async def test_no_discard_when_call_completes_within_applied_timeout(
        self, db: Session, stock_ai082: Stock
    ) -> None:
        """GREEN(REQ-AI082-002): 적용 타임아웃(5s)이 mock 소요(0.05s)보다 크면 실제 후보
        리스트가 그대로 반환된다(오폐기 없음)."""
        candidate = _make_bypass_candidate(stock_ai082)
        with (
            patch.object(fund_manager, "_GATHER_TIMEOUT_S", 5.0),
            patch(
                "app.services.fund_manager.gather_surge_candidates",
                side_effect=_blocking_gather(0.05, [candidate]),
            ),
        ):
            result = await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        assert result != [], (
            "적용 타임아웃 이내에 완료된 실제 탐지 결과는 빈 리스트로 폐기되어서는 안 된다"
            "(REQ-AI082-002)"
        )
        assert any(r["stock_code"] == stock_ai082.stock_code for r in result), (
            "반환된 후보 리스트에 mock 후보의 stock_code가 그대로 보존되어야 한다"
        )


# ---------------------------------------------------------------------------
# AC-082-003: 병리적 초과 시 안전망 거동 보존 (REQ-AI082-003/007) [HARD]
# ---------------------------------------------------------------------------

class TestSafetyNetPreserved:
    """상향된 타임아웃마저 초과하는 병리적인 날에도 경고 로그 + 빈 리스트 반환 안전망은
    그대로 유지되어야 한다(무한 대기/가드 제거 금지, REQ-AI082-003)."""

    @pytest.mark.asyncio
    async def test_warns_and_returns_empty_when_even_raised_timeout_exceeded(
        self, db: Session, stock_ai082: Stock, caplog
    ) -> None:
        candidate = _make_bypass_candidate(stock_ai082)
        timeout_value = 0.05
        expected_log_fragment = "%ds" % timeout_value  # fund_manager.py 경고 로그와 동일 포맷
        with (
            patch.object(fund_manager, "_GATHER_TIMEOUT_S", timeout_value),
            patch(
                "app.services.fund_manager.gather_surge_candidates",
                side_effect=_blocking_gather(0.3, [candidate]),
            ),
            caplog.at_level("WARNING", logger="app.services.fund_manager"),
        ):
            result = await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        assert result == [], "상향된 타임아웃마저 초과하면 여전히 빈 리스트를 반환해야 한다"
        assert any(expected_log_fragment in rec.message for rec in caplog.records), (
            "경고 로그가 남아야 한다(안전망 관찰 가능성 보존, REQ-AI082-003/007)"
        )

    def test_gather_timeout_constant_remains_bounded_not_removed(self) -> None:
        """REQ-AI082-003 [HARD]: 타임아웃 가드 자체가 제거되거나 사실상 무한대가 되어서는
        안 된다 — 하루(다음 스케줄 잡 간격) 대비 충분히 작은 유계 값이어야 한다."""
        assert fund_manager._GATHER_TIMEOUT_S < 86400, (
            "타임아웃은 유계(bounded)여야 한다 — 하루(86400s) 이상의 사실상 무한 대기는 "
            "REQ-AI082-003 위반이다"
        )


# ---------------------------------------------------------------------------
# AC-082-007 (REQ-AI082-008, P2 선택): 관측성 연속성 — 로그 포맷 유지
# ---------------------------------------------------------------------------

class TestTimeoutLogFormatPreserved:
    """타임아웃 경고 로그가 숫자 %ds 포맷을 유지하는지 확인 — journalctl ASCII 부분 문자열
    검색(예: "1200s") 가능성을 보장한다(REQ-AI082-008)."""

    @pytest.mark.asyncio
    async def test_warning_log_includes_numeric_timeout_value(
        self, db: Session, stock_ai082: Stock, caplog
    ) -> None:
        candidate = _make_bypass_candidate(stock_ai082)
        timeout_value = 0.09
        expected_log_fragment = "%ds" % timeout_value
        with (
            patch.object(fund_manager, "_GATHER_TIMEOUT_S", timeout_value),
            patch(
                "app.services.fund_manager.gather_surge_candidates",
                side_effect=_blocking_gather(0.3, [candidate]),
            ),
            caplog.at_level("WARNING", logger="app.services.fund_manager"),
        ):
            await _gather_surge_candidates(db, recent_news=[], leading_candidates=[])

        assert any(expected_log_fragment in rec.message for rec in caplog.records), (
            "경고 로그에 적용된 타임아웃 초 값이 숫자로 포함되어야 한다(%ds 포맷 유지)"
        )
