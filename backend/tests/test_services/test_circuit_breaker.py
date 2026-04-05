"""서킷 브레이커 유닛 테스트.

CircuitBreaker의 핵심 동작을 검증한다:
- 정상 상태에서 사용 가능
- 연속 실패 시 서킷 열림
- 성공 시 서킷 닫힘
- recovery timeout 후 반개방 상태
"""

import time


from app.services.circuit_breaker import CircuitBreaker


class TestCircuitBreakerBasic:
    """기본 서킷 브레이커 동작 테스트."""

    def test_initially_available(self):
        """초기 상태에서 모든 프로바이더가 사용 가능하다."""
        cb = CircuitBreaker()
        assert cb.is_available("naver") is True
        assert cb.is_available("kis") is True

    def test_still_available_below_threshold(self):
        """실패 횟수가 임계치 미만이면 사용 가능하다."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("naver")
        cb.record_failure("naver")
        assert cb.is_available("naver") is True

    def test_circuit_opens_at_threshold(self):
        """연속 실패가 임계치에 도달하면 서킷이 열린다."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("naver")
        cb.record_failure("naver")
        cb.record_failure("naver")
        assert cb.is_available("naver") is False

    def test_success_resets_circuit(self):
        """성공 기록이 서킷을 닫는다."""
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("kis")
        cb.record_failure("kis")
        assert cb.is_available("kis") is False

        cb.record_success("kis")
        assert cb.is_available("kis") is True

    def test_success_resets_failure_count(self):
        """성공 후 실패 카운트가 리셋된다."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("naver")
        cb.record_failure("naver")
        cb.record_success("naver")
        cb.record_failure("naver")
        # 성공 후 1회 실패 → 아직 열리지 않음
        assert cb.is_available("naver") is True


class TestCircuitBreakerRecovery:
    """서킷 반개방(half-open) 상태 테스트."""

    def test_half_open_after_timeout(self):
        """recovery_timeout 후 반개방 상태가 된다."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10)
        cb.record_failure("dart")
        cb.record_failure("dart")
        assert cb.is_available("dart") is False

        # 시간을 앞으로 진행시킴
        state = cb._get_state("dart")
        state.last_failure_time = time.time() - 11
        assert cb.is_available("dart") is True

    def test_stays_closed_before_timeout(self):
        """recovery_timeout 전에는 서킷이 열린 상태를 유지한다."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=300)
        cb.record_failure("gemini")
        cb.record_failure("gemini")
        assert cb.is_available("gemini") is False


class TestCircuitBreakerIsolation:
    """프로바이더 간 격리 테스트."""

    def test_providers_are_independent(self):
        """서킷은 프로바이더별로 독립적이다."""
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("naver")
        cb.record_failure("naver")
        assert cb.is_available("naver") is False
        assert cb.is_available("google") is True

    def test_reset_single_provider(self):
        """특정 프로바이더만 리셋할 수 있다."""
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("naver")
        cb.record_failure("naver")
        cb.record_failure("kis")
        cb.record_failure("kis")
        cb.reset("naver")
        assert cb.is_available("naver") is True
        assert cb.is_available("kis") is False

    def test_reset_all(self):
        """전체 프로바이더를 리셋할 수 있다."""
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("naver")
        cb.record_failure("naver")
        cb.record_failure("kis")
        cb.record_failure("kis")
        cb.reset()
        assert cb.is_available("naver") is True
        assert cb.is_available("kis") is True


class TestCircuitBreakerStatus:
    """상태 조회 테스트."""

    def test_get_status(self):
        """서킷 상태를 딕셔너리로 조회할 수 있다."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("naver")
        cb.record_failure("naver")
        cb.record_failure("naver")
        cb.record_failure("kis")

        status = cb.get_status()
        assert status["naver"]["is_open"] is True
        assert status["naver"]["failure_count"] == 3
        assert status["kis"]["is_open"] is False
        assert status["kis"]["failure_count"] == 1
