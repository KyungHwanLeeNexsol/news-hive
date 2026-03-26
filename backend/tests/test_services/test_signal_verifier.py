"""signal_verifier 서비스 테스트.

get_accuracy_stats() 함수의 통계 산출 로직을 검증한다.
외부 API 호출이 필요한 verify_signals()는 이 단계에서 제외.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.services.signal_verifier import get_accuracy_stats


class TestGetAccuracyStats:
    """get_accuracy_stats 통계 산출 로직 검증."""

    def test_empty_db_returns_zero_stats(self, db: Session) -> None:
        """검증된 시그널이 없으면 모든 통계가 0이다."""
        result = get_accuracy_stats(db, days=30)

        assert result["total"] == 0
        assert result["correct"] == 0
        assert result["accuracy"] == 0.0
        assert result["avg_return"] == 0.0
        assert result["buy_accuracy"] == 0.0
        assert result["sell_accuracy"] == 0.0
        assert result["by_confidence"] == {}

    def test_single_correct_buy_signal(
        self, db: Session, make_fund_signal,
    ) -> None:
        """적중한 매수 시그널 1건 -> 100% 적중률."""
        now = datetime.now(timezone.utc)
        signal = make_fund_signal(
            signal="buy",
            confidence=0.8,
            price_at_signal=10000,
            price_after_5d=11000,
            is_correct=True,
            return_pct=10.0,
            verified_at=now,
            created_at=now - timedelta(days=5),
        )

        result = get_accuracy_stats(db, days=30)

        assert result["total"] == 1
        assert result["correct"] == 1
        assert result["accuracy"] == 100.0
        assert result["avg_return"] == 10.0
        assert result["buy_accuracy"] == 100.0
        assert result["sell_accuracy"] == 0.0  # 매도 시그널 없음

    def test_single_incorrect_sell_signal(
        self, db: Session, make_fund_signal,
    ) -> None:
        """빗나간 매도 시그널 1건 -> 0% 적중률."""
        now = datetime.now(timezone.utc)
        make_fund_signal(
            signal="sell",
            confidence=0.6,
            price_at_signal=10000,
            price_after_5d=11000,
            is_correct=False,
            return_pct=10.0,
            verified_at=now,
            created_at=now - timedelta(days=5),
        )

        result = get_accuracy_stats(db, days=30)

        assert result["total"] == 1
        assert result["correct"] == 0
        assert result["accuracy"] == 0.0
        assert result["sell_accuracy"] == 0.0

    def test_mixed_signals_accuracy(
        self, db: Session, make_fund_signal,
    ) -> None:
        """매수 2건(1적중, 1실패) + 매도 1건(1적중) -> 66.7%."""
        now = datetime.now(timezone.utc)
        base_time = now - timedelta(days=7)

        # 매수 적중
        make_fund_signal(
            signal="buy", confidence=0.9,
            price_at_signal=10000, price_after_5d=12000,
            is_correct=True, return_pct=20.0,
            verified_at=now, created_at=base_time,
        )
        # 매수 실패
        make_fund_signal(
            signal="buy", confidence=0.5,
            price_at_signal=10000, price_after_5d=9000,
            is_correct=False, return_pct=-10.0,
            verified_at=now, created_at=base_time,
        )
        # 매도 적중
        make_fund_signal(
            signal="sell", confidence=0.7,
            price_at_signal=10000, price_after_5d=8000,
            is_correct=True, return_pct=-20.0,
            verified_at=now, created_at=base_time,
        )

        result = get_accuracy_stats(db, days=30)

        assert result["total"] == 3
        assert result["correct"] == 2
        assert result["accuracy"] == 66.7
        assert result["buy_accuracy"] == 50.0
        assert result["sell_accuracy"] == 100.0
        # 평균 수익률: (20 + (-10) + (-20)) / 3 = -3.33
        assert result["avg_return"] == pytest.approx(-3.33, abs=0.01)

    def test_confidence_buckets(
        self, db: Session, make_fund_signal,
    ) -> None:
        """신뢰도 구간별(high/medium/low) 적중률 분류 검증."""
        now = datetime.now(timezone.utc)
        base_time = now - timedelta(days=7)

        # high confidence (>= 0.7): 2건 중 2건 적중
        make_fund_signal(
            signal="buy", confidence=0.9,
            price_at_signal=10000, price_after_5d=11000,
            is_correct=True, return_pct=10.0,
            verified_at=now, created_at=base_time,
        )
        make_fund_signal(
            signal="sell", confidence=0.8,
            price_at_signal=10000, price_after_5d=9000,
            is_correct=True, return_pct=-10.0,
            verified_at=now, created_at=base_time,
        )
        # medium confidence (0.4 ~ 0.7): 1건 중 0건 적중
        make_fund_signal(
            signal="buy", confidence=0.5,
            price_at_signal=10000, price_after_5d=9000,
            is_correct=False, return_pct=-10.0,
            verified_at=now, created_at=base_time,
        )
        # low confidence (< 0.4): 1건 중 1건 적중
        make_fund_signal(
            signal="buy", confidence=0.3,
            price_at_signal=10000, price_after_5d=11000,
            is_correct=True, return_pct=10.0,
            verified_at=now, created_at=base_time,
        )

        result = get_accuracy_stats(db, days=30)

        assert result["by_confidence"]["high"]["total"] == 2
        assert result["by_confidence"]["high"]["accuracy"] == 100.0
        assert result["by_confidence"]["medium"]["total"] == 1
        assert result["by_confidence"]["medium"]["accuracy"] == 0.0
        assert result["by_confidence"]["low"]["total"] == 1
        assert result["by_confidence"]["low"]["accuracy"] == 100.0

    def test_days_filter_excludes_old_signals(
        self, db: Session, make_fund_signal,
    ) -> None:
        """days 파라미터로 조회 기간 필터링이 동작하는지 검증."""
        now = datetime.now(timezone.utc)

        # 최근 시그널 (7일 전)
        make_fund_signal(
            signal="buy", confidence=0.8,
            price_at_signal=10000, price_after_5d=11000,
            is_correct=True, return_pct=10.0,
            verified_at=now, created_at=now - timedelta(days=7),
        )
        # 오래된 시그널 (60일 전)
        make_fund_signal(
            signal="buy", confidence=0.8,
            price_at_signal=10000, price_after_5d=9000,
            is_correct=False, return_pct=-10.0,
            verified_at=now - timedelta(days=55),
            created_at=now - timedelta(days=60),
        )

        # 30일 범위: 최근 시그널만 포함
        result_30d = get_accuracy_stats(db, days=30)
        assert result_30d["total"] == 1
        assert result_30d["accuracy"] == 100.0

        # 90일 범위: 둘 다 포함
        result_90d = get_accuracy_stats(db, days=90)
        assert result_90d["total"] == 2
        assert result_90d["accuracy"] == 50.0

    def test_unverified_signals_excluded(
        self, db: Session, make_fund_signal,
    ) -> None:
        """verified_at이 None인 시그널은 통계에 포함되지 않는다."""
        now = datetime.now(timezone.utc)

        # 검증된 시그널
        make_fund_signal(
            signal="buy", confidence=0.8,
            price_at_signal=10000, price_after_5d=11000,
            is_correct=True, return_pct=10.0,
            verified_at=now, created_at=now - timedelta(days=7),
        )
        # 미검증 시그널
        make_fund_signal(
            signal="buy", confidence=0.9,
            price_at_signal=10000,
            # verified_at, price_after_5d, is_correct 모두 None
            created_at=now - timedelta(days=3),
        )

        result = get_accuracy_stats(db, days=30)
        assert result["total"] == 1  # 검증된 것만 카운트

    def test_hold_signals_not_in_stats(
        self, db: Session, make_fund_signal,
    ) -> None:
        """hold 시그널은 적중 판단 대상이 아니므로 verified_at이 설정되지 않는다.

        get_accuracy_stats는 verified_at이 있는 시그널만 조회하므로
        hold 시그널은 자연스럽게 제외된다.
        """
        now = datetime.now(timezone.utc)

        # hold 시그널 (verified_at None)
        make_fund_signal(
            signal="hold", confidence=0.6,
            price_at_signal=10000,
            created_at=now - timedelta(days=7),
        )

        result = get_accuracy_stats(db, days=30)
        assert result["total"] == 0
