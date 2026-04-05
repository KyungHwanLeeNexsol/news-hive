"""설정 외부화(Configuration Externalization) 검증 테스트.

config.py에 추가된 새 설정 필드들이 기본값을 가지며,
각 서비스에서 올바르게 참조되는지 검증한다.
"""


from app.config import Settings


class TestConfigDefaults:
    """새 설정 필드의 기본값 검증."""

    def test_news_crawler_defaults(self):
        """뉴스 크롤러 쿼리 제한 기본값."""
        s = Settings(
            _env_file=None,
            DATABASE_URL="sqlite://",
        )
        assert s.MAX_TOTAL_QUERIES == 60
        assert s.MAX_STOCK_QUERIES == 20

    def test_macro_risk_defaults(self):
        """매크로 리스크 감지 기본값."""
        s = Settings(
            _env_file=None,
            DATABASE_URL="sqlite://",
        )
        assert s.MACRO_RISK_WINDOW_HOURS == 1
        assert s.MACRO_RISK_WARNING_THRESHOLD == 3
        assert s.MACRO_RISK_CRITICAL_THRESHOLD == 7
        assert s.MACRO_RISK_COOLDOWN_HOURS == 6

    def test_naver_cache_ttl_defaults(self):
        """네이버 금융 캐시 TTL 기본값."""
        s = Settings(
            _env_file=None,
            DATABASE_URL="sqlite://",
        )
        assert s.PRICE_CACHE_TTL_MARKET_OPEN == 10
        assert s.PRICE_CACHE_TTL_MARKET_CLOSED == 300

    def test_kis_token_defaults(self):
        """KIS API 토큰 기본값."""
        s = Settings(
            _env_file=None,
            DATABASE_URL="sqlite://",
        )
        assert s.KIS_TOKEN_REFRESH_MARGIN_SECONDS == 60
        assert s.KIS_TOKEN_DEFAULT_EXPIRES == 86400

    def test_scheduler_defaults(self):
        """스케줄러 주기 기본값."""
        s = Settings(
            _env_file=None,
            DATABASE_URL="sqlite://",
        )
        assert s.DART_CRAWL_INTERVAL_MINUTES == 30
        assert s.MARKET_CAP_UPDATE_HOURS == 6


class TestConfigOverride:
    """환경변수로 설정 오버라이드 가능한지 검증."""

    def test_can_override_via_env(self, monkeypatch):
        """환경변수를 통해 설정값을 변경할 수 있다."""
        monkeypatch.setenv("MAX_TOTAL_QUERIES", "100")
        monkeypatch.setenv("MACRO_RISK_CRITICAL_THRESHOLD", "10")
        monkeypatch.setenv("DATABASE_URL", "sqlite://")
        s = Settings(_env_file=None)
        assert s.MAX_TOTAL_QUERIES == 100
        assert s.MACRO_RISK_CRITICAL_THRESHOLD == 10
