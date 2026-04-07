"""간단한 서킷 브레이커 유틸리티.

외부 API (Naver, KIS, DART, Gemini, Groq 등)가 연속 실패 시
해당 프로바이더를 일시적으로 스킵하여 불필요한 재시도를 방지한다.

의존성 없이 순수 Python으로 구현.
"""

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 연속 실패 시 서킷이 열리는 임계치 (rate limit 제외한 실제 서비스 오류 기준)
DEFAULT_FAILURE_THRESHOLD = 5
# 서킷 열림 후 재시도까지 대기 시간 (초)
DEFAULT_RECOVERY_TIMEOUT = 120  # 2분 (실제 서비스 장애는 보통 단기간 내 복구됨)


@dataclass
class _CircuitState:
    """개별 프로바이더의 서킷 상태."""
    failure_count: int = 0
    last_failure_time: float = 0.0
    is_open: bool = False


class CircuitBreaker:
    """프로바이더별 서킷 브레이커.

    사용법:
        breaker = CircuitBreaker()

        if breaker.is_available("naver"):
            try:
                result = await call_naver_api()
                breaker.record_success("naver")
            except Exception:
                breaker.record_failure("naver")
        else:
            logger.info("naver 서킷 열림, 스킵")
    """

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._states: dict[str, _CircuitState] = {}

    def _get_state(self, provider: str) -> _CircuitState:
        """프로바이더의 서킷 상태를 가져오거나 생성."""
        if provider not in self._states:
            self._states[provider] = _CircuitState()
        return self._states[provider]

    def is_available(self, provider: str) -> bool:
        """프로바이더가 사용 가능한지 확인.

        서킷이 열려있어도 recovery_timeout이 지나면 반개방(half-open) 상태로
        전환하여 재시도를 허용한다.
        """
        state = self._get_state(provider)
        if not state.is_open:
            return True

        # 반개방 상태 확인: recovery_timeout 경과 시 재시도 허용
        elapsed = time.time() - state.last_failure_time
        if elapsed >= self._recovery_timeout:
            logger.info(
                f"서킷 브레이커 반개방: {provider} "
                f"({elapsed:.0f}초 경과, 재시도 허용)"
            )
            return True

        return False

    def record_success(self, provider: str) -> None:
        """API 호출 성공 기록. 서킷을 닫는다."""
        state = self._get_state(provider)
        if state.is_open:
            logger.info(f"서킷 브레이커 닫힘: {provider} (성공 복구)")
        state.failure_count = 0
        state.is_open = False

    def record_failure(self, provider: str) -> None:
        """API 호출 실패 기록. 임계치 초과 시 서킷을 연다."""
        state = self._get_state(provider)
        state.failure_count += 1
        state.last_failure_time = time.time()

        if state.failure_count >= self._failure_threshold and not state.is_open:
            state.is_open = True
            logger.warning(
                f"서킷 브레이커 열림: {provider} "
                f"(연속 {state.failure_count}회 실패, "
                f"{self._recovery_timeout}초 후 재시도)"
            )

    def reset(self, provider: str | None = None) -> None:
        """서킷 상태 초기화. provider 미지정 시 전체 초기화."""
        if provider:
            self._states.pop(provider, None)
        else:
            self._states.clear()

    def get_status(self) -> dict[str, dict]:
        """전체 프로바이더의 서킷 상태를 반환."""
        return {
            name: {
                "failure_count": state.failure_count,
                "is_open": state.is_open,
                "available": self.is_available(name),
            }
            for name, state in self._states.items()
        }


# 전역 인스턴스 — 앱 전체에서 공유
api_circuit_breaker = CircuitBreaker()
