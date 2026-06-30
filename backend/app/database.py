from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# Neon 등 클라우드 DB에서 postgres:// 스킴을 주는 경우 대응
database_url = settings.DATABASE_URL
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=600,
    connect_args={
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
        # idle_in_transaction_session_timeout=0: 비활성화
        # 30000(30s) 설정 시 크롤링 등 장기 실행 프로세스에서 SSL 연결이 끊김.
        # 스케줄러/시그널 생성이 10분+ 소요되므로 제한 없음으로 설정.
        "options": "-c idle_in_transaction_session_timeout=0",
    },
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
