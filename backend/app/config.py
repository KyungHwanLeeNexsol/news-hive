from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/stock_news_tracker"

    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""

    NEWSAPI_KEY: str = ""

    GEMINI_API_KEY: str = ""

    KIS_APP_KEY: str = ""
    KIS_APP_SECRET: str = ""

    NEWS_CRAWL_INTERVAL_MINUTES: int = 10

    FRONTEND_URL: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
