"""SPEC-AI-084 그룹 C: 키워드 태깅 인프라 테스트.

AC-084-001 ~ AC-084-005 검증. 규칙/사전 기반 추출(extract_theme_keywords),
1회성 배치 백필(backfill_stock_keywords), 지속 태깅(refresh_stock_keywords).
"""

from __future__ import annotations

import json
from typing import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


# ---------------------------------------------------------------------------
# 픽스처: 인메모리 SQLite DB
# ---------------------------------------------------------------------------

def _patch_array_for_sqlite() -> None:
    from sqlalchemy import ARRAY
    from sqlalchemy.ext.compiler import compiles

    @compiles(ARRAY, "sqlite")
    def _compile_array_sqlite(type_, compiler, **kw):
        return "TEXT"

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


_patch_array_for_sqlite()


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                naver_code VARCHAR(10),
                is_custom BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                stock_code VARCHAR(20) NOT NULL,
                market VARCHAR(10),
                market_cap BIGINT,
                keywords TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sector_id) REFERENCES sectors(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS news_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title VARCHAR(500) NOT NULL,
                summary TEXT,
                url VARCHAR(1000) UNIQUE NOT NULL,
                source VARCHAR(50) NOT NULL,
                published_at DATETIME,
                collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                sentiment VARCHAR(20),
                urgency VARCHAR(20),
                ai_summary TEXT,
                content TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS news_stock_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_id INTEGER NOT NULL,
                stock_id INTEGER,
                sector_id INTEGER,
                match_type VARCHAR(20) NOT NULL,
                relevance VARCHAR(20) NOT NULL,
                relevance_score INTEGER,
                relation_sentiment VARCHAR(20),
                propagation_type VARCHAR(10) DEFAULT 'direct',
                impact_reason TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS disclosures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                corp_code VARCHAR(8) NOT NULL,
                corp_name VARCHAR(100) NOT NULL,
                stock_code VARCHAR(6),
                stock_id INTEGER,
                report_name VARCHAR(500) NOT NULL,
                report_type VARCHAR(50),
                rcept_no VARCHAR(20) UNIQUE NOT NULL,
                rcept_dt VARCHAR(10) NOT NULL,
                url VARCHAR(500) NOT NULL,
                ai_summary TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                impact_score FLOAT,
                baseline_price INTEGER,
                reflected_pct FLOAT,
                unreflected_gap FLOAT,
                ripple_checked BOOLEAN DEFAULT 0,
                disclosed_at DATETIME
            )
        """))
        conn.commit()

    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_sector(db: Session):
    from app.models.sector import Sector
    sector = db.query(Sector).first()
    if sector is None:
        sector = Sector(name="테스트섹터", naver_code="001")
        db.add(sector)
        db.flush()
    return sector


def _make_stock(db: Session, stock_code: str, name: str, keywords=None):
    from app.models.stock import Stock
    sector = _make_sector(db)
    stock = Stock(stock_code=stock_code, name=name, sector_id=sector.id, keywords=keywords)
    db.add(stock)
    db.flush()
    return stock


def _make_news_with_relation(
    db: Session, stock_id: int, title: str, content: str = "", relevance: str = "direct"
):
    from app.models.news import NewsArticle
    from app.models.news_relation import NewsStockRelation

    article = NewsArticle(
        title=title,
        content=content,
        url=f"https://example.com/{title}",
        source="naver",
    )
    db.add(article)
    db.flush()

    rel = NewsStockRelation(
        news_id=article.id,
        stock_id=stock_id,
        match_type="keyword",
        relevance=relevance,
    )
    db.add(rel)
    db.flush()
    return article


_ROBOT_KEYWORDS = ["로봇", "AI", "반도체"]


# ---------------------------------------------------------------------------
# AC-084-001 / AC-AI091-002/003: 뉴스/공시 기반 키워드 추출
#
# SPEC-AI-091 REQ-AI091-002: 단일 blob 매칭에서 "테마 키워드가 최소 2개의 서로 다른
# 소스 텍스트에 출현할 때만 매칭" 방식으로 변경되었다 — 아래 픽스처는 이 계약을
# 반영해 각 매칭 대상 키워드가 최소 2개의 서로 다른 텍스트에 등장하도록 구성한다.
# ---------------------------------------------------------------------------

def test_extract_theme_keywords_matches_vocab():
    """REQ-AI091-002: 서로 다른 2개 이상의 텍스트에 등장하는 키워드만 매칭된다."""
    from app.services.keyword_tagging_service import extract_theme_keywords

    texts = [
        "삼성전자 로봇 전담조직 신설",
        "로봇 신사업 확대 발표",
        "AI 반도체 수요 급증",
        "AI 서버향 반도체 공급 확대",
    ]
    matched = extract_theme_keywords(texts, _ROBOT_KEYWORDS)

    assert matched == ["로봇", "AI", "반도체"]


def test_extract_theme_keywords_no_match_returns_empty():
    from app.services.keyword_tagging_service import extract_theme_keywords

    texts = ["주주총회 개최 안내"]
    matched = extract_theme_keywords(texts, _ROBOT_KEYWORDS)

    assert matched == []


def test_ac091_002_single_text_mention_is_excluded():
    """REQ-AI091-002: 정확히 1개 텍스트에만 등장하는 키워드는 결과에서 제외된다.

    §C 엣지 케이스 3의 대구 사례 — 단일 시황/묶음 기사가 우연히 언급한 무관 테마
    단어가 매칭되지 않아야 한다(버그 재현 방지의 핵심 회귀 가드).
    """
    from app.services.keyword_tagging_service import extract_theme_keywords

    texts = ["삼성전자 로봇 전담조직 신설", "AI 반도체 수요 급증"]
    matched = extract_theme_keywords(texts, _ROBOT_KEYWORDS)

    # 세 키워드 모두 정확히 1개 텍스트에만 등장 → 전부 제외
    assert matched == []


def test_ac091_002_exactly_two_texts_boundary_is_included():
    """§C 엣지 케이스 3: 정확히 2개 텍스트에 등장하는 경계값은 포함된다(>= 2, 초과 아님)."""
    from app.services.keyword_tagging_service import extract_theme_keywords

    texts = ["로봇 사업 확대", "로봇 신제품 출시"]
    matched = extract_theme_keywords(texts, _ROBOT_KEYWORDS)

    assert matched == ["로봇"]


def test_ac091_003_korean_preceding_char_boundary_guard():
    """AC-AI091-003: 매칭 위치 직전 문자가 한글 음절이면 해당 매칭을 거부한다."""
    from app.services.keyword_tagging_service import extract_theme_keywords

    # "이닉스"가 테마 어휘라고 가정 — "SK하이닉스" 안의 "이닉스"는 직전 문자가
    # 한글 음절("하")이므로 오탐으로 거부되어야 한다.
    texts = ["SK하이닉스 실적 발표", "SK하이닉스 신규 투자 확대"]
    matched = extract_theme_keywords(texts, ["이닉스"])

    assert matched == []


def test_ac001_backfill_fills_stock_keywords_from_linked_news(db):
    """AC-084-001 / REQ-AI091-002: direct 뉴스 2건 이상에서 테마 키워드를 추출해 채운다."""
    from app.services.keyword_tagging_service import backfill_stock_keywords

    stock = _make_stock(db, "277810", "레인보우로보틱스", keywords=None)
    _make_news_with_relation(db, stock.id, "레인보우로보틱스, 로봇 사업 확대")
    _make_news_with_relation(db, stock.id, "레인보우로보틱스 로봇 신제품 출시")

    result = backfill_stock_keywords(db, theme_keywords=_ROBOT_KEYWORDS)

    db.refresh(stock)
    assert stock.keywords == ["로봇"]
    assert result.stocks_tagged == 1


def test_ac091_001_indirect_relation_text_excluded_from_gathering(db):
    """AC-AI091-001: relevance="indirect" 관계에서 나온 뉴스 텍스트는 수집 대상에서
    제외된다 — indirect 뉴스만 2건 있어도 태깅되지 않아야 한다."""
    from app.services.keyword_tagging_service import backfill_stock_keywords

    stock = _make_stock(db, "105560", "KB금융", keywords=None)
    _make_news_with_relation(db, stock.id, "로봇 테마 관련주 급등", relevance="indirect")
    _make_news_with_relation(db, stock.id, "로봇 테마 후속 보도", relevance="indirect")

    result = backfill_stock_keywords(db, theme_keywords=_ROBOT_KEYWORDS)

    db.refresh(stock)
    assert stock.keywords is None
    assert result.stocks_tagged == 0


# ---------------------------------------------------------------------------
# AC-084-002: 배치 백필 유계·멱등
# ---------------------------------------------------------------------------

def test_ac002_backfill_idempotent_second_run_preserves(db):
    """1차 실행으로 채운 키워드를 2차 실행이 파괴하지 않는다(멱등)."""
    from app.services.keyword_tagging_service import backfill_stock_keywords

    stock = _make_stock(db, "277810", "레인보우로보틱스", keywords=None)
    _make_news_with_relation(db, stock.id, "레인보우로보틱스 로봇 신사업")
    _make_news_with_relation(db, stock.id, "레인보우로보틱스 로봇 사업 확대")

    result1 = backfill_stock_keywords(db, theme_keywords=_ROBOT_KEYWORDS)
    assert result1.stocks_tagged == 1

    result2 = backfill_stock_keywords(db, theme_keywords=_ROBOT_KEYWORDS)
    assert result2.stocks_tagged == 0
    assert result2.stocks_skipped_existing == 1

    db.refresh(stock)
    assert stock.keywords == ["로봇"]


def test_ac002_backfill_scanned_bounded_by_universe_size(db):
    """스캔 건수는 유니버스 크기와 정확히 일치한다(유계 비용 확인)."""
    from app.services.keyword_tagging_service import backfill_stock_keywords

    for i in range(5):
        _make_stock(db, f"00000{i}", f"종목{i}", keywords=None)

    result = backfill_stock_keywords(db, theme_keywords=_ROBOT_KEYWORDS)
    assert result.stocks_scanned == 5


# ---------------------------------------------------------------------------
# AC-084-003: 수동/사용자 키워드 오염 금지 [HARD]
# ---------------------------------------------------------------------------

def test_ac003_backfill_never_overwrites_existing_manual_keywords(db):
    """수동 설정된(비어있지 않은) keywords는 백필이 절대 덮어쓰지 않는다."""
    from app.services.keyword_tagging_service import backfill_stock_keywords

    stock = _make_stock(db, "000010", "수동설정종목", keywords=["수동테마"])
    _make_news_with_relation(db, stock.id, "로봇 관련 기사")

    result = backfill_stock_keywords(db, theme_keywords=_ROBOT_KEYWORDS)

    db.refresh(stock)
    assert stock.keywords == ["수동테마"]
    assert result.stocks_skipped_existing == 1
    assert result.stocks_tagged == 0


# ---------------------------------------------------------------------------
# AC-084-004: LLM 예산 가드 (규칙/사전 경로만 존재 — 무유계 호출 구조적 부재)
# ---------------------------------------------------------------------------

def test_ac004_no_network_or_llm_call_in_extraction():
    """extract_theme_keywords는 순수 문자열 매칭만 수행하며 외부 호출이 없다."""
    import inspect
    from app.services.keyword_tagging_service import extract_theme_keywords

    src = inspect.getsource(extract_theme_keywords)
    assert "requests" not in src
    assert "httpx" not in src
    assert "ai_client" not in src
    assert "await" not in src


# ---------------------------------------------------------------------------
# AC-084-005: 지속 태깅 신선도 + 캡
# ---------------------------------------------------------------------------

def test_ac005_refresh_merges_new_keywords_without_deleting_existing(db):
    """지속 태깅은 기존 키워드를 보존하며 신규 매칭 키워드를 병합한다."""
    from app.services.keyword_tagging_service import refresh_stock_keywords

    stock = _make_stock(db, "277810", "레인보우로보틱스", keywords=["로봇"])
    _make_news_with_relation(db, stock.id, "레인보우로보틱스 AI 반도체 신사업 발표")
    _make_news_with_relation(db, stock.id, "레인보우로보틱스 AI 반도체 협력 확대")

    updated = refresh_stock_keywords(db, [stock.id], theme_keywords=_ROBOT_KEYWORDS)

    db.refresh(stock)
    assert updated == 1
    assert stock.keywords[0] == "로봇"  # 기존 항목 보존(순서 유지)
    assert set(stock.keywords) == {"로봇", "AI", "반도체"}


def test_ac005_refresh_caps_keywords_per_stock(db):
    """종목당 키워드 수는 max_keywords_per_stock을 초과하지 않는다(무한 증식 방지)."""
    from app.services.keyword_tagging_service import refresh_stock_keywords

    stock = _make_stock(db, "277810", "레인보우로보틱스", keywords=["기존1", "기존2"])
    _make_news_with_relation(db, stock.id, "로봇 AI 반도체 관련 기사")
    _make_news_with_relation(db, stock.id, "로봇 AI 반도체 후속 기사")

    updated = refresh_stock_keywords(
        db, [stock.id], theme_keywords=_ROBOT_KEYWORDS, max_keywords_per_stock=3
    )

    db.refresh(stock)
    assert updated == 1
    assert len(stock.keywords) == 3


def test_ac005_refresh_noop_for_empty_stock_ids(db):
    """빈 stock_ids 목록이면 아무 것도 갱신하지 않는다(0건, 오류 없음)."""
    from app.services.keyword_tagging_service import refresh_stock_keywords

    updated = refresh_stock_keywords(db, [])
    assert updated == 0
