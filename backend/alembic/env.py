from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
# @MX:WARN: [AUTO] disable_existing_loggers=False 명시 필수 — 기본값(True)은 alembic.ini의
# [loggers](root/sqlalchemy/alembic만 나열)에 없는 기존 로거(app.services.* 전체)를
# `.disabled = True`로 영구 비활성화시킨다. Logger.isEnabledFor()는 disabled를 최우선 검사하므로
# 레벨과 무관하게 ERROR/CRITICAL 포함 모든 로그가 완전한 no-op이 된다.
# @MX:REASON: SPEC-AI-073 REQ-AI073-003 — _run_migrations()가 앱 시작 시 1회 실행되며, 이
# 인자가 없으면 app.services.scheduler/dart_crawler 로거가 프로세스 수명 내내 침묵해 실제
# 프로덕션에서 8일간 DART 크롤 실패(ForeignKeyViolation)가 무증상으로 방치됐다.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402, F401
    Sector, Stock, NewsArticle, NewsStockRelation,
    FundSignal, DailyBriefing, PortfolioReport,
)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    from app.config import settings

    url = settings.DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    from app.config import settings

    db_url = settings.DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = db_url
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
