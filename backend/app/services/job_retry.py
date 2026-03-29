"""스케줄러 작업용 재시도 데코레이터.

3회 시도, exponential backoff (1s, 2s, 4s).
최종 실패 시 로깅 + Prometheus 메트릭 기록.
"""

import functools
import time
import logging

logger = logging.getLogger(__name__)


def retry_with_backoff(max_attempts: int = 3, base_delay: float = 1.0):
    """스케줄러 작업용 재시도 데코레이터.

    Args:
        max_attempts: 최대 시도 횟수 (기본 3)
        base_delay: 기본 대기 시간(초), 시도마다 2배 증가
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        logger.critical(
                            "%s 최종 실패 (%d/%d회 시도): %s",
                            func.__name__, attempt, max_attempts, e,
                        )
                        # Prometheus 메트릭: 최종 실패 기록
                        try:
                            from app.metrics import JOB_FAILURES
                            JOB_FAILURES.labels(job_id=func.__name__).inc()
                        except Exception:
                            pass
                        # 스케줄러 작업은 예외를 전파하지 않음 (로깅 + 메트릭만 기록)
                        return None
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "%s 실패 (%d/%d회), %.1f초 후 재시도: %s",
                        func.__name__, attempt, max_attempts, delay, e,
                    )
                    # Prometheus 메트릭: 재시도 기록
                    try:
                        from app.metrics import JOB_RETRIES
                        JOB_RETRIES.labels(job_id=func.__name__).inc()
                    except Exception:
                        pass
                    time.sleep(delay)
        return wrapper
    return decorator
