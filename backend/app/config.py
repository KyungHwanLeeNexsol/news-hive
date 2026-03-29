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

    NEWS_CRAWL_INTERVAL_MINUTES: int = 10  # minutes between news crawl cycles

    FRONTEND_URL: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
