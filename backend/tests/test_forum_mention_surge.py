"""SPEC-AI-026: 포럼 언급 급증 탐지 테스트.

AC-001 ~ AC-006 전체 검증.
RED 단계: detect_forum_mention_surge 미구현 상태에서 실패 확인.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


# ---------------------------------------------------------------------------
# 픽스처: 인메모리 SQLite DB
# ---------------------------------------------------------------------------

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
            CREATE TABLE IF NOT EXISTS stock_forum_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id INTEGER,
                stock_code VARCHAR(20) NOT NULL,
                content VARCHAR(200),
                nickname VARCHAR(100),
                post_date DATETIME,
                view_count INTEGER DEFAULT 0,
                agree_count INTEGER DEFAULT 0,
                disagree_count INTEGER DEFAULT 0,
                sentiment VARCHAR(20) DEFAULT 'neutral',
                collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (stock_id) REFERENCES stocks(id)
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

def _make_stock(db: Session, stock_code: str, name: str = "테스트주식") -> "Stock":  # noqa: F821
    from app.models.sector import Sector
    from app.models.stock import Stock

    sector = db.query(Sector).first()
    if sector is None:
        sector = Sector(name="테스트섹터", naver_code="001")
        db.add(sector)
        db.flush()

    stock = Stock(
        stock_code=stock_code,
        name=name,
        sector_id=sector.id,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_posts(
    db: Session,
    stock_id: int,
    stock_code: str,
    recent_count: int,
    old_count_per_day: int,
    baseline_days: int = 7,
) -> None:
    """포럼 게시글 생성 헬퍼.

    recent_count: 최근 24시간 게시글 수
    old_count_per_day: baseline 기간(days 2~8) 하루평균 게시글 수
    """
    from app.models.stock_forum import StockForumPost

    now = datetime.now(timezone.utc)

    # 최근 24시간 게시글
    for i in range(recent_count):
        post = StockForumPost(
            stock_id=stock_id,
            stock_code=stock_code,
            content=f"최근글 {i}",
            post_date=now - timedelta(hours=1, minutes=i),
        )
        db.add(post)

    # 베이스라인 기간 게시글 (2일전 ~ 8일전)
    for day in range(2, 2 + baseline_days):
        for j in range(old_count_per_day):
            post = StockForumPost(
                stock_id=stock_id,
                stock_code=stock_code,
                content=f"구글 day={day} j={j}",
                post_date=now - timedelta(days=day, minutes=j * 5),
            )
            db.add(post)

    db.flush()


def _make_signal_today(db: Session, stock_id: int) -> "FundSignal":  # noqa: F821
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


def _make_config(**kwargs):
    from app.surge_config.surge_settings import ForumMentionConfig
    return ForumMentionConfig(**kwargs)


# ---------------------------------------------------------------------------
# AC-001: ratio=10x, mentions=50 → confidence=0.35 (cap)
# ---------------------------------------------------------------------------

def test_characterize_forum_mention_surge_ac001_high_ratio_capped_confidence(db):
    """AC-001: ratio=10x, mentions=50 → confidence=0.35 (max_confidence 상한)."""
    from app.services.surge_detector import detect_forum_mention_surge

    stock = _make_stock(db, "000010", "포럼급증주")
    # baseline_avg = 5 posts/day → recent=50 → ratio=10x ≥ 5x, recent≥10
    _make_posts(db, stock.id, "000010", recent_count=50, old_count_per_day=5)

    cfg = _make_config()
    signals = detect_forum_mention_surge(db, cfg)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_type == "surge_candidate"
    assert abs(sig.confidence - 0.35) < 0.001  # max_confidence 캡

    import json
    metadata = json.loads(sig.surge_metadata or "{}")
    assert "forum_mention_surge" in metadata.get("surge_basis", [])


# ---------------------------------------------------------------------------
# AC-002: mentions=3 (< min_absolute=10) → 시그널 없음
# ---------------------------------------------------------------------------

def test_characterize_forum_mention_surge_ac002_below_min_absolute_no_signal(db):
    """AC-002: recent_count=3 (< min_absolute_mentions=10) → 시그널 없음."""
    from app.services.surge_detector import detect_forum_mention_surge

    stock = _make_stock(db, "000020", "소량언급주")
    # recent=3, old=1/day → ratio=3x, 하지만 min_absolute 미달
    _make_posts(db, stock.id, "000020", recent_count=3, old_count_per_day=1)

    cfg = _make_config()
    signals = detect_forum_mention_surge(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-003: ratio < 5x → 시그널 없음
# ---------------------------------------------------------------------------

def test_characterize_forum_mention_surge_ac003_low_ratio_no_signal(db):
    """AC-003: ratio < mention_multiplier(5x) → 시그널 없음."""
    from app.services.surge_detector import detect_forum_mention_surge

    stock = _make_stock(db, "000030", "저배율주")
    # recent=15, old=5/day → ratio=3x < 5x
    _make_posts(db, stock.id, "000030", recent_count=15, old_count_per_day=5)

    cfg = _make_config()
    signals = detect_forum_mention_surge(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-004: 이미 surge_candidate 있음 → 중복 없음
# ---------------------------------------------------------------------------

def test_characterize_forum_mention_surge_ac004_existing_signal_no_duplicate(db):
    """AC-004: 오늘 이미 surge_candidate → 중복 생성 안 함."""
    from app.services.surge_detector import detect_forum_mention_surge

    stock = _make_stock(db, "000040", "기존시그널주")
    _make_posts(db, stock.id, "000040", recent_count=50, old_count_per_day=5)
    _make_signal_today(db, stock.id)

    cfg = _make_config()
    signals = detect_forum_mention_surge(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-005: 내부 예외 → 파이프라인 보존 (빈 리스트 반환)
# ---------------------------------------------------------------------------

def test_characterize_forum_mention_surge_ac005_exception_pipeline_intact(db):
    """AC-005: 내부 예외 → 빈 리스트 반환, 파이프라인 보존."""
    from app.services.surge_detector import detect_forum_mention_surge
    from unittest.mock import patch

    cfg = _make_config()
    # StockForumPost는 함수 내부 로컬 import이므로, 로컬 import 경로를 mock
    with patch(
        "app.models.stock_forum.StockForumPost.id",
        side_effect=RuntimeError("DB 장애"),
    ):
        # DB 쿼리가 실패하도록 db.query 자체를 side_effect로 강제
        original_query = db.query

        def _bad_query(*args, **kwargs):
            if args and getattr(args[0], "__name__", "") == "StockForumPost":
                raise RuntimeError("DB 장애")
            return original_query(*args, **kwargs)

        with patch.object(db, "query", side_effect=_bad_query):
            signals = detect_forum_mention_surge(db, cfg)

    assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# AC-006: baseline=0 → 스킵 (ZeroDivisionError 없음)
# ---------------------------------------------------------------------------

def test_characterize_forum_mention_surge_ac006_zero_baseline_skip_no_error(db):
    """AC-006: baseline_avg=0 (신규 종목) → 스킵, ZeroDivisionError 없음."""
    from app.services.surge_detector import detect_forum_mention_surge

    stock = _make_stock(db, "000050", "신규상장주")
    # 최근 24시간에만 게시글 있고, baseline 기간에는 없음
    _make_posts(db, stock.id, "000050", recent_count=20, old_count_per_day=0)

    cfg = _make_config()
    # baseline=0이므로 스킵 — ZeroDivisionError가 발생하지 않아야 함
    signals = detect_forum_mention_surge(db, cfg)

    assert isinstance(signals, list)
    assert len(signals) == 0
