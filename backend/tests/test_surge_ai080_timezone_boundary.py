"""SPEC-AI-080 T8/OQ-1/R-5/EC-3: created_at UTC 저장 + KST 야간 경계 특성화.

핵심 검증: `FundSignal.created_at`은 UTC로 저장되고(`DateTime(timezone=True)`, 항상
`datetime.now(timezone.utc)`로 기록), `evaluate_surge_predictions`의
`sqlfunc.date(created_at) == prev_business_day` 비교는 타임존 변환 없이 UTC 날짜를
그대로 쓴다. 09:00 KST(=00:00 UTC)가 정확히 UTC 날짜 경계와 일치하므로, 즉시 발화의
"next_day" 지평 윈도우(15:20 KST T-1 ~ 09:00 KST T)는 별도 변환 없이도 항상 UTC 날짜 T-1
하나에 속한다 — 이 사실을 심야/장전(00:00~09:00 KST) 접수 경계 사례로 재현한다.

이 테스트가 통과한다는 것은 OQ-1이 "타임존 변환 로직 추가 불필요"로 확정됨을 의미한다
(코드 수정 없이 검증만 수행 — T0에서 사전 확인된 가정을 실제 DB 라운드트립으로 고정).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.sector import Sector
from app.models.stock import Stock

# 시장 변동성 조회는 app.services.market_context._volatility_cache라는 프로세스 전역(5분 TTL)
# 캐시를 갖는다(이 SPEC 범위 밖 기존 코드). 실제 네트워크 호출을 그대로 두면 이 캐시가
# 오염되어 tests/test_services/test_market_context.py의 격리되지 않은 어설션에 영향을 줄 수
# 있으므로, 이 파일의 모든 테스트에서 고정값으로 스텁 처리한다.
_STUB_VOLATILITY = {"volatility_level": "normal"}


def _make_disclosure(db: Session, stock: Stock, rcept_dt: str, suffix: str) -> Disclosure:
    """실제 Disclosure 행을 생성한다 — FundSignal.disclosure_id FK 제약을 만족시키기 위함."""
    d = Disclosure(
        corp_code="00000000",
        corp_name="테스트기업",
        stock_code=stock.stock_code,
        stock_id=stock.id,
        report_name="단일판매ㆍ공급계약체결 500억원",
        report_type="주요사항보고",
        rcept_no=f"20260600{suffix}",
        rcept_dt=rcept_dt,
        url="https://dart.fss.or.kr/test/1",
        baseline_price=50000,
    )
    db.add(d)
    db.flush()
    return d


class TestOvernightPreOpenBoundary:
    """EC-3: 심야/장전(00:00~09:00 KST) 접수 공시의 UTC 날짜 경계 처리."""

    @pytest.mark.asyncio
    async def test_overnight_reception_lands_in_correct_t_minus_1_bucket(
        self, db: Session
    ) -> None:
        """KST 2026-06-09 00:30(장전, calendar day=T) 접수 즉시발화 시그널이
        UTC 저장 시 2026-06-08(T-1) 날짜로 기록되어 evaluate_surge_predictions의
        T-1→T predicted_set에 정상 편입되는지 확인한다.

        KST 00:30 T = UTC 15:30 (T-1) — 09:00 KST(=00:00 UTC) 경계 이전이므로 UTC 날짜가
        하루 당겨진다. 이는 버그가 아니라 next_day 지평 윈도우 전체가 UTC 기준 단일
        날짜(T-1)에 속한다는 사실의 자연스러운 결과다(OQ-1 검증).
        """
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal
        from app.services.surge_evaluation_service import evaluate_surge_predictions

        sector = Sector(name="AI080경계섹터", is_custom=False)
        db.add(sector)
        db.flush()
        stock = Stock(stock_code="BOUND01", name="경계종목", sector_id=sector.id, market="KOSPI")
        db.add(stock)
        db.flush()
        disclosure = _make_disclosure(db, stock, "20260608", "01")

        # KST 2026-06-09 00:30 == UTC 2026-06-08 15:30
        fixed_now = datetime(2026, 6, 8, 15, 30, tzinfo=timezone.utc)

        with (
            patch(
                "app.services.disclosure_impact_scorer.datetime",
                wraps=datetime,
                **{"now.return_value": fixed_now},
            ),
            patch(
                "app.services.naver_finance.fetch_current_price",
                new_callable=AsyncMock,
                return_value=50000,
            ),
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock,
                return_value=_STUB_VOLATILITY,
            ),
        ):
            signal = await _create_immediate_surge_signal(
                db, disclosure, impact_score=82.0, horizon="next_day"
            )

        assert signal is not None
        assert signal.created_at.date() == date(2026, 6, 8), (
            "즉시 발화 시각(KST 00:30, T calendar day)이 UTC 저장 시 T-1(2026-06-08)로 "
            "기록되어야 한다(09:00 KST=00:00 UTC 경계)"
        )

        # trading_date=T(2026-06-09) 평가 시 prev_business_day=2026-06-08과 매치되어야 한다
        result = evaluate_surge_predictions(db, date(2026, 6, 9))
        assert result.predicted_count == 1, (
            "심야/장전 접수 즉시발화 시그널이 T-1→T predicted_set에 정상 편입되어야 한다(OQ-1)"
        )

    @pytest.mark.asyncio
    async def test_just_before_market_open_still_t_minus_1(self, db: Session) -> None:
        """KST 08:59(장 시작 1분 전, calendar day=T) 접수도 동일하게 T-1 UTC 날짜로 기록된다
        (09:00 KST 경계 바로 아래 극단값)."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal
        from app.services.surge_evaluation_service import evaluate_surge_predictions

        sector = Sector(name="AI080경계섹터2", is_custom=False)
        db.add(sector)
        db.flush()
        stock = Stock(stock_code="BOUND02", name="경계종목2", sector_id=sector.id, market="KOSPI")
        db.add(stock)
        db.flush()
        disclosure = _make_disclosure(db, stock, "20260608", "02")

        # KST 2026-06-09 08:59 == UTC 2026-06-08 23:59
        fixed_now = datetime(2026, 6, 8, 23, 59, tzinfo=timezone.utc)

        with (
            patch(
                "app.services.disclosure_impact_scorer.datetime",
                wraps=datetime,
                **{"now.return_value": fixed_now},
            ),
            patch(
                "app.services.naver_finance.fetch_current_price",
                new_callable=AsyncMock,
                return_value=50000,
            ),
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock,
                return_value=_STUB_VOLATILITY,
            ),
        ):
            signal = await _create_immediate_surge_signal(
                db, disclosure, impact_score=82.0, horizon="next_day"
            )

        assert signal.created_at.date() == date(2026, 6, 8)
        result = evaluate_surge_predictions(db, date(2026, 6, 9))
        assert result.predicted_count == 1

    @pytest.mark.asyncio
    async def test_dominant_case_t_minus_1_evening_reception(self, db: Session) -> None:
        """지배적 미탐 표본 유형(spec.md [E-8]): T-1 종가 이후 저녁(예: 16:41 KST) 접수는
        타임존 경계와 무관하게 항상 T-1 UTC 날짜로 기록된다(실증 대응: 신테카바이오 07-09 16:41)."""
        from app.services.disclosure_impact_scorer import _create_immediate_surge_signal
        from app.services.surge_evaluation_service import evaluate_surge_predictions

        sector = Sector(name="AI080경계섹터3", is_custom=False)
        db.add(sector)
        db.flush()
        stock = Stock(stock_code="BOUND03", name="경계종목3", sector_id=sector.id, market="KOSPI")
        db.add(stock)
        db.flush()
        disclosure = _make_disclosure(db, stock, "20260608", "03")

        # KST 2026-06-08 16:41 == UTC 2026-06-08 07:41 (경계와 무관, 평이한 저녁 접수)
        fixed_now = datetime(2026, 6, 8, 7, 41, tzinfo=timezone.utc)

        with (
            patch(
                "app.services.disclosure_impact_scorer.datetime",
                wraps=datetime,
                **{"now.return_value": fixed_now},
            ),
            patch(
                "app.services.naver_finance.fetch_current_price",
                new_callable=AsyncMock,
                return_value=50000,
            ),
            patch(
                "app.services.market_context.get_market_volatility",
                new_callable=AsyncMock,
                return_value=_STUB_VOLATILITY,
            ),
        ):
            signal = await _create_immediate_surge_signal(
                db, disclosure, impact_score=82.0, horizon="next_day"
            )

        assert signal.created_at.date() == date(2026, 6, 8)
        result = evaluate_surge_predictions(db, date(2026, 6, 9))
        assert result.predicted_count == 1
