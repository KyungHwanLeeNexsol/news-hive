"""SPEC-AI-084 그룹 A: 뉴스 기반 산업 테마 전파(키워드 바스켓 carry-forward) 테스트.

AC-084-010 ~ AC-084-017 검증(그룹 A 관련 부분). detect_theme_group_carry_forward
(SPEC-AI-025)의 앵커 self-exclusion 패턴을 stocks.keywords 바스켓으로 미러링한
detect_theme_news_carry를 대상으로 한다.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from typing import Generator
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


# ---------------------------------------------------------------------------
# 픽스처: 인메모리 SQLite DB (ARRAY(Text) 컬럼을 JSON 직렬화로 지원)
# ---------------------------------------------------------------------------

def _patch_array_for_sqlite() -> None:
    """Stock.keywords(ARRAY(Text))가 SQLite에서도 Python list로 동작하도록 패치.

    tests/conftest.py의 동명 패치와 동일한 접근(전역 ARRAY 타입 bind/result_processor
    오버라이드)이며, 이 테스트 파일은 다른 surge_detector 테스트들과 동일하게 독립된
    인메모리 엔진을 사용하므로 자체적으로 패치를 적용한다.
    """
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
    """인메모리 SQLite 세션 픽스처."""
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
            CREATE TABLE IF NOT EXISTS fund_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id INTEGER NOT NULL,
                signal VARCHAR(10) NOT NULL,
                confidence FLOAT NOT NULL,
                target_price INTEGER,
                stop_loss INTEGER,
                reasoning TEXT NOT NULL,
                news_summary TEXT,
                financial_summary TEXT,
                market_summary TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                originally_created_at DATETIME,
                price_at_signal INTEGER,
                price_after_1d INTEGER,
                price_after_3d INTEGER,
                price_after_5d INTEGER,
                is_correct BOOLEAN,
                return_pct FLOAT,
                verified_at DATETIME,
                benchmark_return_pct FLOAT,
                alpha_pct FLOAT,
                error_category VARCHAR(30),
                price_after_6h INTEGER,
                price_after_12h INTEGER,
                early_warning BOOLEAN,
                factor_scores TEXT,
                composite_score FLOAT,
                prompt_version VARCHAR(50),
                trend_alignment VARCHAR(20),
                volatility_level VARCHAR(10),
                ai_model VARCHAR(50),
                signal_type VARCHAR(30),
                disclosure_id INTEGER,
                tp_sl_method VARCHAR(20) DEFAULT 'legacy_fixed',
                paper_executed BOOLEAN NOT NULL DEFAULT 0,
                surge_metadata TEXT,
                FOREIGN KEY (stock_id) REFERENCES stocks(id)
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


def _make_stock(db: Session, stock_code: str, name: str, keywords: list[str] | None = None):
    from app.models.stock import Stock
    sector = _make_sector(db)
    stock = Stock(stock_code=stock_code, name=name, sector_id=sector.id, keywords=keywords)
    db.add(stock)
    db.flush()
    return stock


def _make_signal_today(db: Session, stock_id: int):
    from app.models.fund_signal import FundSignal
    signal = FundSignal(
        stock_id=stock_id,
        signal="buy",
        confidence=0.5,
        reasoning="기존 시그널",
        signal_type="surge_candidate",
        paper_executed=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(signal)
    db.flush()
    return signal


def _make_news_article(db: Session, title: str, urgency: str, hours_ago: float = 1.0):
    from app.models.news import NewsArticle
    article = NewsArticle(
        title=title,
        url=f"https://example.com/{title}-{hours_ago}",
        source="naver",
        urgency=urgency,
        published_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )
    db.add(article)
    db.flush()
    return article


def _make_config(**kwargs):
    from app.surge_config.surge_settings import ThemeNewsCarryConfig
    return ThemeNewsCarryConfig(enabled=True, **kwargs)


def _mock_price_by_code(prices: dict[str, float]):
    def _fn(stock_code: str):
        if stock_code not in prices:
            return None
        return {"current_price": 50000, "change_rate": prices[stock_code]}
    return _fn


# ---------------------------------------------------------------------------
# 마스터 스위치 (REQ-AI084-015)
# ---------------------------------------------------------------------------

def test_disabled_by_default_returns_empty(db):
    """기본 설정(enabled=False)이면 즉시 빈 리스트 반환 — 레거시 파이프라인 완전 보존."""
    from app.services.surge_detector import detect_theme_news_carry
    from app.surge_config.surge_settings import ThemeNewsCarryConfig

    _make_stock(db, "000010", "앵커", keywords=["로봇"])
    _make_stock(db, "000020", "멤버", keywords=["로봇"])

    cfg = ThemeNewsCarryConfig()  # enabled=False 기본값
    assert cfg.enabled is False

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value={"current_price": 50000, "change_rate": 20.0},
    ):
        signals = detect_theme_news_carry(db, cfg)

    assert signals == []


# ---------------------------------------------------------------------------
# AC-084-010: 키워드 바스켓 앵커 → 미이동 멤버 전파
# ---------------------------------------------------------------------------

def test_ac010_basket_anchor_propagates_to_unmoved_members(db):
    """복수 앵커 동반 이동(테마 확인) → 미이동 멤버에만 전파, 앵커 자신은 제외."""
    from app.services.surge_detector import detect_theme_news_carry

    a = _make_stock(db, "277810", "레인보우로보틱스", keywords=["로봇"])
    b = _make_stock(db, "090360", "로보스타", keywords=["로봇"])
    c = _make_stock(db, "108490", "로보티즈", keywords=["로봇"])  # 미이동 대상

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_price_by_code({"277810": 16.8, "090360": 13.1, "108490": 1.0}),
    ):
        signals = detect_theme_news_carry(db, cfg)

    target_signals = [s for s in signals if s.stock_id == c.id]
    assert len(target_signals) == 1
    assert target_signals[0].signal_type == "surge_candidate"

    # 앵커(a, b) 자신은 전파 대상이 아니다
    assert all(s.stock_id not in (a.id, b.id) for s in signals)

    metadata = json.loads(target_signals[0].surge_metadata)
    assert metadata["surge_basis"] == ["theme_news_carry"]
    assert metadata["theme_keyword"] == "로봇"


def test_ac010_existing_ids_excluded(db):
    """미이동 멤버가 이미 오늘 시그널을 보유 → 재전파하지 않는다."""
    from app.services.surge_detector import detect_theme_news_carry

    _make_stock(db, "277810", "레인보우로보틱스", keywords=["로봇"])
    _make_stock(db, "090360", "로보스타", keywords=["로봇"])
    c = _make_stock(db, "108490", "로보티즈", keywords=["로봇"])
    _make_signal_today(db, c.id)

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_price_by_code({"277810": 16.8, "090360": 13.1, "108490": 1.0}),
    ):
        signals = detect_theme_news_carry(db, cfg)

    assert all(s.stock_id != c.id for s in signals)


# ---------------------------------------------------------------------------
# AC-084-011: 테마 활성 확인 게이트 (오전파 통제)
# ---------------------------------------------------------------------------

def test_ac011_single_anchor_without_news_blocks_propagation(db):
    """단일 앵커만 이동 + 고긴급 뉴스 없음 → 테마 활성 미확인, 전파 없음."""
    from app.services.surge_detector import detect_theme_news_carry

    _make_stock(db, "277810", "레인보우로보틱스", keywords=["로봇"])
    c = _make_stock(db, "108490", "로보티즈", keywords=["로봇"])

    cfg = _make_config()  # min_anchor_members_for_activation=2 (기본값)

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_price_by_code({"277810": 16.8, "108490": 1.0}),
    ):
        signals = detect_theme_news_carry(db, cfg)

    assert signals == []
    assert not db.query(__import__("app.models.fund_signal", fromlist=["FundSignal"]).FundSignal).filter_by(stock_id=c.id).first()


def test_ac011_single_anchor_with_high_urgency_news_opens_gate(db):
    """단일 앵커 + 고긴급 테마 뉴스 존재 → 테마 활성 확인, 전파 발생."""
    from app.services.surge_detector import detect_theme_news_carry

    _make_stock(db, "277810", "레인보우로보틱스", keywords=["로봇"])
    c = _make_stock(db, "108490", "로보티즈", keywords=["로봇"])
    _make_news_article(db, "로봇주 '불기둥'…줄줄이 상한가", urgency="breaking", hours_ago=0.5)

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_price_by_code({"277810": 16.8, "108490": 1.0}),
    ):
        signals = detect_theme_news_carry(db, cfg)

    assert any(s.stock_id == c.id for s in signals)


# ---------------------------------------------------------------------------
# AC-084-012: 바스켓 데이터 부재 시 안전 no-op [HARD]
# ---------------------------------------------------------------------------

def test_ac012_no_keywords_returns_empty_no_error(db):
    """모든 종목이 keywords=NULL/빈 배열 → 오류 없이 조용히 빈 리스트."""
    from app.services.surge_detector import detect_theme_news_carry

    _make_stock(db, "000010", "종목A", keywords=None)
    _make_stock(db, "000020", "종목B", keywords=[])

    cfg = _make_config()

    signals = detect_theme_news_carry(db, cfg)
    assert signals == []


def test_ec4_price_fetch_failure_skips_member_quietly(db):
    """EC-4: 가격 조회 실패(None 반환) → 해당 멤버는 앵커 후보에서 조용히 제외, 예외 없음."""
    from app.services.surge_detector import detect_theme_news_carry

    _make_stock(db, "277810", "레인보우로보틱스", keywords=["로봇"])
    _make_stock(db, "090360", "로보스타", keywords=["로봇"])  # 가격 조회 실패(None) 대상
    c = _make_stock(db, "108490", "로보티즈", keywords=["로봇"])

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_price_by_code({"277810": 16.8, "108490": 1.0}),  # 090360 없음 → None
    ):
        signals = detect_theme_news_carry(db, cfg)

    # 단일 앵커(277810)만 인정되고 090360은 가격 조회 실패로 제외되므로,
    # 테마 활성 확인(복수 멤버 동반 이동 경로)이 실패해 전파 없음.
    assert not any(s.stock_id == c.id for s in signals)


def test_max_signals_per_basket_cap(db):
    """바스켓당 발행 시그널 수는 max_signals_per_basket을 초과하지 않는다."""
    from app.services.surge_detector import detect_theme_news_carry

    _make_stock(db, "277810", "앵커1", keywords=["로봇"])
    _make_stock(db, "090360", "앵커2", keywords=["로봇"])
    targets = [
        _make_stock(db, f"10{i}490", f"타겟{i}", keywords=["로봇"]) for i in range(5)
    ]

    cfg = _make_config(max_signals_per_basket=2)
    prices = {"277810": 16.8, "090360": 13.1}
    for t in targets:
        prices[t.stock_code] = 1.0

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_price_by_code(prices),
    ):
        signals = detect_theme_news_carry(db, cfg)

    assert len(signals) == 2


def test_ac001_basket_size_one_is_noop(db):
    """EC-1: 바스켓 멤버가 1명뿐이면 전파 대상 없음(no-op)."""
    from app.services.surge_detector import detect_theme_news_carry

    _make_stock(db, "000010", "단독종목", keywords=["희귀테마"])
    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value={"current_price": 50000, "change_rate": 20.0},
    ):
        signals = detect_theme_news_carry(db, cfg)

    assert signals == []


# ---------------------------------------------------------------------------
# AC-084-013: same-day 지평 귀속 → 평가 편입 [HARD, 최상위]
# ---------------------------------------------------------------------------

def test_ac013_same_day_horizon_db_assertion(db):
    """전파 신호의 surge_metadata['horizon']이 'same_day'로 영속화되는지 DB 어서션."""
    from app.services.surge_detector import detect_theme_news_carry
    from app.services.surge_evaluation_service import _is_same_day_event_horizon_signal

    _make_stock(db, "277810", "레인보우로보틱스", keywords=["로봇"])
    _make_stock(db, "090360", "로보스타", keywords=["로봇"])
    c = _make_stock(db, "108490", "로보티즈", keywords=["로봇"])

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_price_by_code({"277810": 16.8, "090360": 13.1, "108490": 1.0}),
    ):
        signals = detect_theme_news_carry(db, cfg)

    target_signals = [s for s in signals if s.stock_id == c.id]
    assert len(target_signals) == 1

    # DB에서 재조회하여 영속화 여부를 어서션 (기계적 검증)
    from app.models.fund_signal import FundSignal
    persisted = db.query(FundSignal).filter(FundSignal.stock_id == c.id).first()
    assert persisted is not None
    metadata = json.loads(persisted.surge_metadata)
    assert metadata["horizon"] == "same_day"

    # 기존 same-day 평가 경로가 이 신호를 인식하는지 확인 (SPEC-AI-080 경로 재사용)
    assert _is_same_day_event_horizon_signal(persisted.surge_metadata) is True


# ---------------------------------------------------------------------------
# AC-084-016: first-mover 비목표 [HARD] — 명명된 음성 테스트
# ---------------------------------------------------------------------------

def test_first_mover_excluded_from_theme_news_carry_scope(db):
    """AC-084-016: first-mover(이미 임계 초과 이동한 앵커) 종목 코드는 이 탐지기의 전파
    출력(predicted_set에 해당하는 theme_news_carry 신호 집합)에 나타나지 않아야 한다.

    07-22 로봇 랠리의 1차 파동 종목(예: 09:14 이미 상한가 도달 보도된 종목)은 그 자신이
    바스켓의 앵커이므로, 본 탐지기는 구조적으로 앵커 자신에게 신호를 발행하지 않는다
    (existing_ids/emitted 패턴과 동형의 self-exclusion). first-mover 예측은 본 SPEC의
    목표가 아니다(REQ-AI084-017, [X-1]).
    """
    from app.services.surge_detector import detect_theme_news_carry
    from app.models.fund_signal import FundSignal

    first_mover = _make_stock(db, "066430", "아이로보틱스", keywords=["로봇"])
    second_wave_anchor = _make_stock(db, "432470", "케이엔에스", keywords=["로봇"])
    unmoved_member = _make_stock(db, "391710", "코닉오토메이션", keywords=["로봇"])

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_price_by_code(
            {"066430": 29.9, "432470": 29.9, "391710": 0.5}
        ),
    ):
        signals = detect_theme_news_carry(db, cfg)

    # first-mover(앵커) 자신에게는 어떤 theme_news_carry 신호도 발행되지 않는다
    first_mover_signal = (
        db.query(FundSignal).filter(FundSignal.stock_id == first_mover.id).first()
    )
    assert first_mover_signal is None

    # 다른 앵커(second_wave_anchor)도 동일하게 자기 자신에게는 신호가 없다
    assert not any(s.stock_id == second_wave_anchor.id for s in signals)

    # 미이동 멤버만 전파 대상이 된다
    assert any(s.stock_id == unmoved_member.id for s in signals)


# ---------------------------------------------------------------------------
# AC-084-014: 실매매 미트리거 + 기존 경로 불변 [HARD] (정적 회귀 가드)
# ---------------------------------------------------------------------------

def test_ac014_no_execute_signal_trade_and_theme_group_untouched():
    """detect_theme_news_carry 소스에 execute_signal_trade/ThemeGroup 참조가 없어야 한다."""
    from app.services.surge_detector import detect_theme_news_carry

    src = inspect.getsource(detect_theme_news_carry)
    assert "execute_signal_trade" not in src
    assert "ThemeGroup" not in src
    assert "StockThemeGroup" not in src


# ---------------------------------------------------------------------------
# EC-3: 크로스바스켓 dedup
# ---------------------------------------------------------------------------

def test_ec3_cross_basket_dedup(db):
    """동일 종목이 복수 바스켓(로봇, AI)에 속해도 1회만 전파된다."""
    from app.services.surge_detector import detect_theme_news_carry
    from app.models.fund_signal import FundSignal

    _make_stock(db, "277810", "앵커A", keywords=["로봇", "AI"])
    _make_stock(db, "090360", "앵커B", keywords=["로봇", "AI"])
    target = _make_stock(db, "108490", "타겟", keywords=["로봇", "AI"])

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=_mock_price_by_code({"277810": 16.8, "090360": 13.1, "108490": 1.0}),
    ):
        detect_theme_news_carry(db, cfg)

    target_signals = db.query(FundSignal).filter(FundSignal.stock_id == target.id).all()
    assert len(target_signals) == 1


# ---------------------------------------------------------------------------
# 예외 격리
# ---------------------------------------------------------------------------

def test_exception_isolation_returns_empty_list(db):
    """내부 예외 발생 시 빈 리스트를 반환하고 파이프라인은 보존된다."""
    from app.services.surge_detector import detect_theme_news_carry

    _make_stock(db, "000010", "앵커", keywords=["로봇"])
    _make_stock(db, "000020", "멤버", keywords=["로봇"])

    cfg = _make_config()

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        side_effect=RuntimeError("네트워크 오류"),
    ):
        signals = detect_theme_news_carry(db, cfg)

    assert isinstance(signals, list)
    assert signals == []


# ---------------------------------------------------------------------------
# REQ-AI084-018: DDD 재현 우선 무회귀 — _run_coverage_expansion 배선 회귀 확인
# ---------------------------------------------------------------------------

def test_run_coverage_expansion_wiring_does_not_break_pipeline(db):
    """detect_theme_news_carry가 _run_coverage_expansion 9번째 단계로 배선되어도
    (기본 enabled=False) 기존 커버리지 확장 파이프라인은 예외 없이 완주한다.
    """
    from app.services.fund_manager import _run_coverage_expansion

    try:
        _run_coverage_expansion(db, [])
    except Exception as exc:
        pytest.fail(f"_run_coverage_expansion이 예외를 raise했습니다: {exc}")
