from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/news_hive"

    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""

    GEMINI_API_KEY: str = ""
    GEMINI_API_KEY_2: str = ""
    GEMINI_API_KEY_3: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    KIS_APP_KEY: str = ""
    KIS_APP_SECRET: str = ""

    DART_API_KEY: str = ""
    DART_PUSH_SECRET: str = ""  # Shared secret for GitHub Actions → server DART push
    DEPLOY_SECRET: str = ""  # Shared secret for GitHub webhook auto-deploy
    ADMIN_PASSWORD: str = ""  # Admin login password for AI Fund Manager access

    NEWS_CRAWL_INTERVAL_MINUTES: int = 10  # 뉴스 크롤링 주기 (분)

    FRONTEND_URL: str = "http://localhost:3000"

    # --- 뉴스 크롤러 쿼리 제한 (news_crawler.py) ---
    MAX_TOTAL_QUERIES: int = 60   # 크롤링 1회당 최대 총 검색 쿼리 수
    MAX_STOCK_QUERIES: int = 20   # 크롤링 1회당 최대 종목별 검색 쿼리 수

    # --- 매크로 리스크 감지 (macro_risk.py) ---
    MACRO_RISK_WINDOW_HOURS: int = 1      # 리스크 뉴스 집계 윈도우 (시간)
    MACRO_RISK_WARNING_THRESHOLD: int = 3  # warning 알림 임계치 (기사 수)
    MACRO_RISK_CRITICAL_THRESHOLD: int = 7 # critical 알림 임계치 (기사 수)
    MACRO_RISK_COOLDOWN_HOURS: int = 6     # 동일 키워드 알림 중복 방지 간격 (시간)

    # --- 네이버 금융 캐시 TTL (naver_finance.py) ---
    PRICE_CACHE_TTL_MARKET_OPEN: int = 10   # 장중 캐시 TTL (초)
    PRICE_CACHE_TTL_MARKET_CLOSED: int = 300 # 장외 캐시 TTL (초)

    # --- KIS API 토큰 (kis_api.py) ---
    KIS_TOKEN_REFRESH_MARGIN_SECONDS: int = 60    # 토큰 만료 전 갱신 여유 (초)
    KIS_TOKEN_DEFAULT_EXPIRES: int = 86400         # 토큰 기본 만료 시간 (초)

    # --- 스케줄러 주기 (scheduler.py) ---
    DART_CRAWL_INTERVAL_MINUTES: int = 30  # DART 공시 크롤링 주기 (분)
    MARKET_CAP_UPDATE_HOURS: int = 6       # 시가총액 업데이트 주기 (시간)

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
