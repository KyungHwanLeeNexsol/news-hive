"""NewsHive Prometheus 커스텀 메트릭 모듈.

prometheus_client 카운터, 히스토그램, 게이지 정의.
prometheus-fastapi-instrumentator가 기본 HTTP 메트릭을 자동 수집하고,
여기서는 비즈니스 로직 메트릭만 정의한다.
"""

from prometheus_client import Counter, Histogram, Gauge

# ---------------------------------------------------------------------------
# 크롤링 메트릭
# ---------------------------------------------------------------------------
CRAWL_ARTICLES = Counter(
    "newshive_crawl_articles_total",
    "수집된 뉴스 기사 수",
    ["source"],
)
CRAWL_ERRORS = Counter(
    "newshive_crawl_errors_total",
    "크롤링 오류 횟수",
    ["source"],
)

# ---------------------------------------------------------------------------
# 캐시 메트릭
# ---------------------------------------------------------------------------
CACHE_HITS = Counter(
    "newshive_cache_hits_total",
    "캐시 적중 횟수",
    ["namespace"],
)
CACHE_MISSES = Counter(
    "newshive_cache_misses_total",
    "캐시 미스 횟수",
    ["namespace"],
)

# ---------------------------------------------------------------------------
# 스케줄러 메트릭
# ---------------------------------------------------------------------------
JOB_DURATION = Histogram(
    "newshive_job_duration_seconds",
    "작업 실행 시간",
    ["job_id"],
)
JOB_FAILURES = Counter(
    "newshive_job_failures_total",
    "작업 최종 실패 횟수",
    ["job_id"],
)
JOB_RETRIES = Counter(
    "newshive_job_retries_total",
    "작업 재시도 횟수",
    ["job_id"],
)

# ---------------------------------------------------------------------------
# WebSocket 메트릭
# ---------------------------------------------------------------------------
WS_CONNECTIONS = Gauge(
    "newshive_websocket_connections",
    "활성 WebSocket 연결 수",
)

# ---------------------------------------------------------------------------
# AI 분류 메트릭
# ---------------------------------------------------------------------------
AI_CLASSIFICATIONS = Counter(
    "newshive_ai_classifications_total",
    "AI 분류 실행 횟수",
    ["model"],
)
AI_ERRORS = Counter(
    "newshive_ai_errors_total",
    "AI API 오류 횟수",
    ["model"],
)
