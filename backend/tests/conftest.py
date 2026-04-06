"""NewsHive 테스트 인프라 설정.

SQLite 인메모리 DB를 기본으로 사용한다.
- PostgreSQL이 필요한 경우 TEST_DATABASE_URL 환경변수로 오버라이드 가능
- Stock.keywords의 ARRAY(Text) 타입은 SQLite에서 TEXT로 자동 매핑 (JSON 직렬화)
- 각 테스트는 트랜잭션 롤백으로 격리
"""

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.models.sector import Sector
from app.models.stock import Stock
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.fund_signal import FundSignal
from app.models.daily_briefing import DailyBriefing
from app.models.disclosure import Disclosure
from app.models.macro_alert import MacroAlert
from app.models.sector_insight import SectorInsight
from app.models.economic_event import EconomicEvent
from app.models.news_price_impact import NewsPriceImpact
from app.models.portfolio_report import PortfolioReport
from app.models.commodity import Commodity
from app.models.news_commodity_relation import NewsCommodityRelation
from app.models.sector_momentum import SectorMomentum
from app.models.prompt_version import PromptVersion
from app.models.stock_relation import StockRelation
from app.models.virtual_portfolio import VirtualPortfolio
from app.models.factor_weight import FactorWeightHistory  # noqa: F401
from app.models.improvement_log import ImprovementLog  # noqa: F401
from app.models.securities_report import SecuritiesReport  # noqa: F401 — SPEC-FOLLOW-002


# 테스트 DB URL: 기본 SQLite 인메모리, 환경변수로 PostgreSQL 오버라이드 가능
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite://")

_is_sqlite = TEST_DATABASE_URL.startswith("sqlite")


def _patch_array_for_sqlite():
    """SQLite에서 ARRAY 타입을 TEXT로 매핑하는 컴파일 확장.

    Stock.keywords (ARRAY(Text))가 SQLite에서도 동작하도록 한다.
    DDL은 TEXT로 컴파일하고, DML은 JSON 직렬화/역직렬화한다.
    """
    from sqlalchemy import ARRAY
    from sqlalchemy.ext.compiler import compiles

    @compiles(ARRAY, "sqlite")
    def _compile_array_sqlite(type_, compiler, **kw):
        return "TEXT"

    # DML: Python list <-> JSON string 변환
    _orig_bind = ARRAY.bind_processor
    _orig_result = ARRAY.result_processor

    def _sqlite_bind(self, dialect):
        if dialect.name == "sqlite":
            def process(value):
                return json.dumps(value) if value is not None else None
            return process
        return _orig_bind(self, dialect)

    def _sqlite_result(self, dialect, coltype):
        if dialect.name == "sqlite":
            def process(value):
                return json.loads(value) if value is not None else None
            return process
        return _orig_result(self, dialect, coltype)

    ARRAY.bind_processor = _sqlite_bind
    ARRAY.result_processor = _sqlite_result


def _add_sqlite_timezone_hook(engine):
    """SQLite에서 timezone-naive datetime을 UTC로 자동 변환하는 훅.

    PostgreSQL은 timestamp with time zone을 지원하지만 SQLite는 지원하지 않는다.
    이 훅은 SQLite에서 읽어온 datetime 값에 UTC tzinfo를 부여하여
    프로덕션 코드의 timezone-aware 비교가 정상 동작하도록 한다.
    """
    from sqlalchemy import event as sa_event

    @sa_event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        # SQLite가 ISO 8601 timestamp을 반환하도록 설정
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


@pytest.fixture(scope="session")
def test_engine():
    """테스트용 DB 엔진."""
    if _is_sqlite:
        _patch_array_for_sqlite()
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        # PostgreSQL 사용 시
        from sqlalchemy import text as sa_text

        admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            result = conn.execute(
                sa_text("SELECT 1 FROM pg_database WHERE datname = 'news_hive_test'")
            )
            if not result.fetchone():
                conn.execute(sa_text("CREATE DATABASE news_hive_test"))
        admin_engine.dispose()
        engine = create_engine(TEST_DATABASE_URL)

    # 모든 모델의 테이블을 import하여 Base.metadata에 등록되도록 보장
    from app.models.sector_insight import SectorInsight  # noqa: F401
    from app.models.economic_event import EconomicEvent  # noqa: F401
    from app.models.news_price_impact import NewsPriceImpact  # noqa: F401
    from app.models.portfolio_report import PortfolioReport  # noqa: F401
    from app.models.commodity import Commodity, CommodityPrice, SectorCommodityRelation  # noqa: F401
    from app.models.news_commodity_relation import NewsCommodityRelation  # noqa: F401
    from app.models.sector_momentum import SectorMomentum  # noqa: F401
    from app.models.prompt_version import PromptVersion, PromptABResult  # noqa: F401
    from app.models.stock_relation import StockRelation  # noqa: F401
    from app.models.virtual_portfolio import VirtualPortfolio, VirtualTrade, PortfolioSnapshot  # noqa: F401
    from app.models.factor_weight import FactorWeightHistory  # noqa: F401, F811
    from app.models.improvement_log import ImprovementLog  # noqa: F401, F811

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db(test_engine) -> Session:
    """각 테스트 함수마다 트랜잭션 롤백으로 DB 격리."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(db: Session) -> TestClient:
    """FastAPI TestClient with DB override.

    lifespan에서 실행되는 마이그레이션/시딩/스케줄러를 모두 비활성화한다.
    """
    from app.main import app

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch("app.main._run_migrations"),
        patch("app.main.start_scheduler"),
        patch("app.main.stop_scheduler"),
        patch("threading.Thread"),
    ):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 팩토리 픽스처 -- 테스트 데이터 생성 헬퍼
# ---------------------------------------------------------------------------

@pytest.fixture
def make_sector(db: Session):
    """Sector 팩토리. 호출할 때마다 새 Sector를 생성한다."""
    _counter = 0

    def _factory(name: str | None = None, **kwargs) -> Sector:
        nonlocal _counter
        _counter += 1
        defaults = {
            "name": name or f"테스트섹터_{_counter}",
            "is_custom": False,
        }
        defaults.update(kwargs)
        sector = Sector(**defaults)
        db.add(sector)
        db.flush()
        return sector

    return _factory


@pytest.fixture
def make_stock(db: Session, make_sector):
    """Stock 팩토리. sector_id가 없으면 자동으로 섹터를 생성한다.

    SQLite에서는 keywords를 사용하지 않는다 (ARRAY 비호환).
    PostgreSQL에서는 keywords를 정상적으로 사용 가능.
    """
    _counter = 0

    def _factory(
        name: str | None = None,
        stock_code: str | None = None,
        sector_id: int | None = None,
        **kwargs,
    ) -> Stock:
        nonlocal _counter
        _counter += 1
        if sector_id is None:
            sector = make_sector()
            sector_id = sector.id
        defaults = {
            "name": name or f"테스트종목_{_counter}",
            "stock_code": stock_code or f"{100000 + _counter}",
            "sector_id": sector_id,
        }
        defaults.update(kwargs)
        stock = Stock(**defaults)
        db.add(stock)
        db.flush()
        return stock

    return _factory


@pytest.fixture
def make_news(db: Session):
    """NewsArticle 팩토리."""
    _counter = 0

    def _factory(
        title: str | None = None,
        sentiment: str = "neutral",
        **kwargs,
    ) -> NewsArticle:
        nonlocal _counter
        _counter += 1
        now = datetime.utcnow() if _is_sqlite else datetime.now(timezone.utc)
        defaults = {
            "title": title or f"테스트 뉴스 {_counter}",
            "url": f"https://test.example.com/news/{_counter}_{now.timestamp()}",
            "source": "test",
            "sentiment": sentiment,
            "published_at": now,
            "collected_at": now,
        }
        defaults.update(kwargs)
        # kwargs에서 제공된 datetime이 aware이면 SQLite용으로 naive 변환
        if _is_sqlite:
            for dt_field in ("published_at", "collected_at"):
                val = defaults.get(dt_field)
                if val and hasattr(val, "tzinfo") and val.tzinfo is not None:
                    defaults[dt_field] = val.replace(tzinfo=None)
        article = NewsArticle(**defaults)
        db.add(article)
        db.flush()
        return article

    return _factory


@pytest.fixture
def make_news_relation(db: Session):
    """NewsStockRelation 팩토리."""

    def _factory(
        news_id: int,
        stock_id: int | None = None,
        sector_id: int | None = None,
        match_type: str = "keyword",
        relevance: str = "direct",
    ) -> NewsStockRelation:
        rel = NewsStockRelation(
            news_id=news_id,
            stock_id=stock_id,
            sector_id=sector_id,
            match_type=match_type,
            relevance=relevance,
        )
        db.add(rel)
        db.flush()
        return rel

    return _factory


@pytest.fixture
def make_fund_signal(db: Session, make_stock):
    """FundSignal 팩토리."""
    _counter = 0

    def _factory(
        stock_id: int | None = None,
        signal: str = "buy",
        confidence: float = 0.8,
        **kwargs,
    ) -> FundSignal:
        nonlocal _counter
        _counter += 1
        if stock_id is None:
            stock = make_stock()
            stock_id = stock.id
        defaults = {
            "stock_id": stock_id,
            "signal": signal,
            "confidence": confidence,
            "reasoning": f"테스트 시그널 근거 {_counter}",
        }
        defaults.update(kwargs)
        fs = FundSignal(**defaults)
        db.add(fs)
        db.flush()
        return fs

    return _factory


@pytest.fixture
def make_macro_alert(db: Session):
    """MacroAlert 팩토리."""
    _counter = 0

    def _factory(
        level: str = "warning",
        keyword: str | None = None,
        **kwargs,
    ) -> MacroAlert:
        nonlocal _counter
        _counter += 1
        defaults = {
            "level": level,
            "keyword": keyword or f"리스크키워드_{_counter}",
            "title": f"매크로 리스크 알림 {_counter}",
            "article_count": 5,
            "is_active": True,
        }
        defaults.update(kwargs)
        alert = MacroAlert(**defaults)
        db.add(alert)
        db.flush()
        return alert

    return _factory


@pytest.fixture
def make_disclosure(db: Session):
    """Disclosure 팩토리."""
    _counter = 0

    def _factory(
        stock_id: int | None = None,
        **kwargs,
    ) -> Disclosure:
        nonlocal _counter
        _counter += 1
        defaults = {
            "corp_code": f"0000{_counter:04d}",
            "corp_name": f"테스트기업_{_counter}",
            "report_name": f"사업보고서 ({2024}년)",
            "rcept_no": f"2024{_counter:012d}",
            "rcept_dt": "20240101",
            "url": f"https://dart.fss.or.kr/test/{_counter}",
            "stock_id": stock_id,
        }
        defaults.update(kwargs)
        disclosure = Disclosure(**defaults)
        db.add(disclosure)
        db.flush()
        return disclosure

    return _factory


@pytest.fixture
def make_daily_briefing(db: Session):
    """DailyBriefing 팩토리 — AI 펀드매니저 일일 브리핑."""
    from datetime import date as date_type
    _counter = 0

    def _factory(**kwargs) -> DailyBriefing:
        nonlocal _counter
        _counter += 1
        defaults = {
            "briefing_date": date_type(2026, 1, _counter % 28 + 1),
            "market_overview": f"오늘의 시장 요약 {_counter}",
            "sector_highlights": f"섹터 동향 {_counter}",
            "stock_picks": f"주목 종목 {_counter}",
            "risk_assessment": f"리스크 평가 {_counter}",
            "strategy": f"전략 제안 {_counter}",
        }
        defaults.update(kwargs)
        briefing = DailyBriefing(**defaults)
        db.add(briefing)
        db.flush()
        return briefing

    return _factory


@pytest.fixture
def make_sector_insight(db: Session, make_sector):
    """SectorInsight 팩토리 — 섹터 분석 인사이트."""
    _counter = 0

    def _factory(sector_id: int | None = None, **kwargs) -> SectorInsight:
        nonlocal _counter
        _counter += 1
        if sector_id is None:
            sector = make_sector()
            sector_id = sector.id
        defaults = {
            "sector_id": sector_id,
            "content": f"섹터 인사이트 분석 내용 {_counter}",
        }
        defaults.update(kwargs)
        insight = SectorInsight(**defaults)
        db.add(insight)
        db.flush()
        return insight

    return _factory


@pytest.fixture
def make_economic_event(db: Session):
    """EconomicEvent 팩토리 — 글로벌 경제/지정학 이벤트."""
    _counter = 0

    def _factory(**kwargs) -> EconomicEvent:
        nonlocal _counter
        _counter += 1
        now = datetime.utcnow() if _is_sqlite else datetime.now(timezone.utc)
        defaults = {
            "title": f"경제 이벤트 {_counter}",
            "description": f"이벤트 설명 {_counter}",
            "event_date": now,
            "category": "fomc",
            "importance": "medium",
            "country": "US",
        }
        defaults.update(kwargs)
        if _is_sqlite:
            val = defaults.get("event_date")
            if val and hasattr(val, "tzinfo") and val.tzinfo is not None:
                defaults["event_date"] = val.replace(tzinfo=None)
        event = EconomicEvent(**defaults)
        db.add(event)
        db.flush()
        return event

    return _factory


@pytest.fixture
def make_news_price_impact(db: Session, make_stock, make_news):
    """NewsPriceImpact 팩토리 — 뉴스-가격 반응 추적."""
    _counter = 0

    def _factory(
        stock_id: int | None = None,
        news_id: int | None = None,
        **kwargs,
    ) -> NewsPriceImpact:
        nonlocal _counter
        _counter += 1
        if stock_id is None:
            stock = make_stock()
            stock_id = stock.id
        if news_id is None:
            news = make_news()
            news_id = news.id
        defaults = {
            "stock_id": stock_id,
            "news_id": news_id,
            "price_at_news": 50000.0 + _counter * 100,
        }
        defaults.update(kwargs)
        impact = NewsPriceImpact(**defaults)
        db.add(impact)
        db.flush()
        return impact

    return _factory


@pytest.fixture
def make_portfolio_report(db: Session):
    """PortfolioReport 팩토리 — AI 포트폴리오 분석 리포트."""
    _counter = 0

    def _factory(**kwargs) -> PortfolioReport:
        nonlocal _counter
        _counter += 1
        defaults = {
            "stock_ids": "1,2,3",
            "overall_assessment": f"종합 평가 {_counter}",
            "risk_analysis": f"리스크 분석 {_counter}",
            "sector_balance": f"섹터 분산 분석 {_counter}",
            "rebalancing": f"리밸런싱 제안 {_counter}",
        }
        defaults.update(kwargs)
        report = PortfolioReport(**defaults)
        db.add(report)
        db.flush()
        return report

    return _factory


@pytest.fixture
def make_commodity(db: Session):
    """Commodity 팩토리 — 원자재 마스터."""
    _counter = 0

    def _factory(**kwargs) -> Commodity:
        nonlocal _counter
        _counter += 1
        defaults = {
            "symbol": f"TEST{_counter}=F",
            "name_ko": f"테스트원자재_{_counter}",
            "name_en": f"Test Commodity {_counter}",
            "category": "energy",
            "unit": "barrel",
            "currency": "USD",
        }
        defaults.update(kwargs)
        commodity = Commodity(**defaults)
        db.add(commodity)
        db.flush()
        return commodity

    return _factory


@pytest.fixture
def make_news_commodity_relation(db: Session, make_news, make_commodity):
    """NewsCommodityRelation 팩토리 — 뉴스-원자재 매핑."""

    def _factory(
        news_id: int | None = None,
        commodity_id: int | None = None,
        **kwargs,
    ) -> NewsCommodityRelation:
        if news_id is None:
            news = make_news()
            news_id = news.id
        if commodity_id is None:
            commodity = make_commodity()
            commodity_id = commodity.id
        defaults = {
            "news_id": news_id,
            "commodity_id": commodity_id,
            "relevance": "direct",
            "match_type": "keyword",
        }
        defaults.update(kwargs)
        rel = NewsCommodityRelation(**defaults)
        db.add(rel)
        db.flush()
        return rel

    return _factory


@pytest.fixture
def make_sector_momentum(db: Session, make_sector):
    """SectorMomentum 팩토리 — 섹터 모멘텀 일간 데이터."""
    from datetime import date as date_type
    _counter = 0

    def _factory(sector_id: int | None = None, **kwargs) -> SectorMomentum:
        nonlocal _counter
        _counter += 1
        if sector_id is None:
            sector = make_sector()
            sector_id = sector.id
        defaults = {
            "sector_id": sector_id,
            "date": date_type(2026, 1, _counter % 28 + 1),
            "daily_return": 1.5,
        }
        defaults.update(kwargs)
        momentum = SectorMomentum(**defaults)
        db.add(momentum)
        db.flush()
        return momentum

    return _factory


@pytest.fixture
def make_prompt_version(db: Session):
    """PromptVersion 팩토리 — AI 프롬프트 버전 관리."""
    _counter = 0

    def _factory(**kwargs) -> PromptVersion:
        nonlocal _counter
        _counter += 1
        defaults = {
            "version_name": f"v{_counter}.0",
            "description": f"프롬프트 변경사항 {_counter}",
            "template_key": "briefing",
            "is_active": True,
            "is_control": False,
        }
        defaults.update(kwargs)
        version = PromptVersion(**defaults)
        db.add(version)
        db.flush()
        return version

    return _factory


@pytest.fixture
def make_stock_relation(db: Session, make_stock):
    """StockRelation 팩토리 — 종목/섹터 간 관계."""

    def _factory(
        source_stock_id: int | None = None,
        target_stock_id: int | None = None,
        **kwargs,
    ) -> StockRelation:
        if source_stock_id is None:
            stock = make_stock()
            source_stock_id = stock.id
        if target_stock_id is None:
            stock = make_stock()
            target_stock_id = stock.id
        defaults = {
            "source_stock_id": source_stock_id,
            "target_stock_id": target_stock_id,
            "relation_type": "competitor",
            "confidence": 0.9,
            "reason": "동일 업종 경쟁사",
        }
        defaults.update(kwargs)
        rel = StockRelation(**defaults)
        db.add(rel)
        db.flush()
        return rel

    return _factory


@pytest.fixture
def make_virtual_portfolio(db: Session):
    """VirtualPortfolio 팩토리 — 가상 포트폴리오."""
    _counter = 0

    def _factory(**kwargs) -> VirtualPortfolio:
        nonlocal _counter
        _counter += 1
        defaults = {
            "name": f"테스트 포트폴리오 {_counter}",
            "initial_capital": 100_000_000,
            "current_cash": 100_000_000,
            "is_active": True,
            "is_defensive_mode": False,
        }
        defaults.update(kwargs)
        portfolio = VirtualPortfolio(**defaults)
        db.add(portfolio)
        db.flush()
        return portfolio

    return _factory
