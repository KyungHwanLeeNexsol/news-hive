"""SPEC-AI-023/SPEC-AI-072: 상한가 근접 종목 익일 carry-forward 테스트.

AC-001 ~ AC-015(SPEC-AI-023) + AC-072-001~005(SPEC-AI-072) 전체 검증.

SPEC-AI-072 (DDD ANALYZE-PRESERVE-IMPROVE):
- PRESERVE: 라이브 change_rate(``_fetch_price_change_sync``)가 더 이상 사용되지 않음을
  고정하는 characterization/regression 테스트(구 버그 재현 방지) 포함.
- IMPROVE: change_rate 소스가 ``fetch_stock_price_history_sync`` 일봉의 T-1 종가-대-종가로
  교체됨에 따라, 모든 mock을 ``_fetch_price_change_sync`` → ``fetch_stock_price_history_sync``
  (OHLCV 픽스처)로 갱신.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Generator
from unittest.mock import patch

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

def _make_stock(
    db: Session,
    stock_code: str,
    name: str = "테스트주식",
    market_cap: int = 1_000_000_000_000,  # 1조 원
) -> "Stock":  # noqa: F821
    """테스트용 Stock 레코드 생성 헬퍼."""
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
        market_cap=market_cap,
    )
    db.add(stock)
    db.flush()
    return stock


def _make_signal(
    db: Session,
    stock_id: int,
    signal_type: str = "surge_candidate",
    created_at: datetime | None = None,
    paper_executed: bool = True,
) -> "FundSignal":  # noqa: F821
    """테스트용 FundSignal 레코드 생성 헬퍼."""
    from app.models.fund_signal import FundSignal

    if created_at is None:
        created_at = datetime.now(timezone.utc)

    signal = FundSignal(
        stock_id=stock_id,
        signal="buy",
        confidence=0.45,
        reasoning="테스트 시그널",
        signal_type=signal_type,
        paper_executed=paper_executed,
        created_at=created_at,
    )
    db.add(signal)
    db.flush()
    return signal


def _make_config(**kwargs):
    """NearLimitUpConfig 헬퍼."""
    from app.surge_config.surge_settings import NearLimitUpConfig
    return NearLimitUpConfig(**kwargs)


def _t1_t2_dates() -> tuple[date, date]:
    """실행 시점 기준 예상 T-1/T-2 KST 거래일을 산출한다.

    ``detect_near_limit_up_carries``가 실제로 사용하는 ``_get_prev_business_day``를
    그대로 재사용해, 테스트 실행일이 언제든(주말 직후 포함) 정합성이 깨지지 않도록 한다.
    """
    from zoneinfo import ZoneInfo
    from app.services.surge_trading_service import _get_prev_business_day

    KST = ZoneInfo("Asia/Seoul")
    today = datetime.now(KST).date()
    t1 = _get_prev_business_day(today)
    t2 = _get_prev_business_day(t1)
    return t1, t2


def _older_business_day(ref: date) -> date:
    """ref보다 하루 이전의 평일(토/일 제외, 임시공휴일 미고려) 날짜를 반환한다."""
    prev = ref - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


def _make_history(
    t1_close: int,
    t2_close: int,
    *,
    t1: date | None = None,
    t2: date | None = None,
    include_today_partial: bool = False,
    today_close: int | None = None,
    extra_days: int = 5,
) -> list:
    """T-1/T-2 종가를 지정한 최신순(newest-first) PriceRecord 픽스처를 생성한다.

    include_today_partial=True면 records[0]에 당일 partial 행을 추가해, 인덱스가 아니라
    date 매칭으로 T-1을 선정하는지 검증하는 AC-072-002에 사용한다.
    """
    from app.services.naver_finance import PriceRecord

    if t1 is None or t2 is None:
        t1, t2 = _t1_t2_dates()

    records: list[PriceRecord] = []
    if include_today_partial:
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        records.append(
            PriceRecord(
                date=today.strftime("%Y.%m.%d"),
                close=today_close if today_close is not None else t1_close,
            )
        )
    records.append(PriceRecord(date=t1.strftime("%Y.%m.%d"), close=t1_close))
    records.append(PriceRecord(date=t2.strftime("%Y.%m.%d"), close=t2_close))

    cursor = t2
    for _ in range(extra_days):
        cursor = _older_business_day(cursor)
        records.append(PriceRecord(date=cursor.strftime("%Y.%m.%d"), close=t2_close))

    return records


def _patch_history(return_value=None, side_effect=None):
    """fetch_stock_price_history_sync 패치 컨텍스트 매니저 헬퍼.

    detect_near_limit_up_carries 내부에서 매 호출마다
    ``from app.services.naver_finance import fetch_stock_price_history_sync``로
    지역 임포트하므로, 패치 대상은 정의 모듈(app.services.naver_finance)이어야 한다.
    """
    if side_effect is not None:
        return patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            side_effect=side_effect,
        )
    return patch(
        "app.services.naver_finance.fetch_stock_price_history_sync",
        return_value=return_value,
    )


def _history_for_change(change_rate: float, base_close: int = 10000) -> list:
    """지정된 T-1-대-T-2 change_rate(%)를 만족하는 히스토리 픽스처를 생성한다."""
    t1_close = round(base_close * (1 + change_rate / 100))
    return _make_history(t1_close, base_close)


# ---------------------------------------------------------------------------
# AC-001: +27% 종목 → surge_candidate 생성, confidence ≈ 0.45
# ---------------------------------------------------------------------------

def test_ac001_27pct_creates_surge_candidate(db):
    """AC-001: T-1 종가-대-종가 +27% 종목에서 surge_candidate 시그널 생성, confidence ≈ 0.45."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _stock = _make_stock(db, "000010", "상한가근접주")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(12700, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_type == "surge_candidate"
    assert abs(sig.confidence - 0.45) < 0.01  # 27/30*0.5 = 0.45
    metadata = json.loads(sig.surge_metadata)
    assert "near_limit_up_carry" in metadata["surge_basis"]


# ---------------------------------------------------------------------------
# AC-002: +30% 정확히 → 생성 안 함 (상한가 도달)
# ---------------------------------------------------------------------------

def test_ac002_exact_30pct_no_signal(db):
    """AC-002: T-1 종가-대-종가 +30.0% 종목은 시그널 생성 안 함."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000020", "상한가정확히")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(13000, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-003: +10% 종목 → 생성 안 함 (min_pct 미달, 15.0→10.0 완화 후에도 미달)
# ---------------------------------------------------------------------------

def test_ac003_10pct_below_threshold_no_signal(db):
    """AC-003: T-1 종가-대-종가 +10% 종목은 min_pct=15.0 미달로 생성 안 함."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000030", "약상승주")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(11000, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-004: 오늘 이미 surge_candidate 있는 종목 → 중복 생성 안 함
# ---------------------------------------------------------------------------

def test_ac004_existing_surge_candidate_today_no_duplicate(db):
    """AC-004: 오늘 surge_candidate 이미 있으면 중복 생성 안 함."""
    from app.services.surge_detector import detect_near_limit_up_carries

    stock = _make_stock(db, "000040", "기존시그널주")
    _make_signal(db, stock.id, signal_type="surge_candidate")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(12700, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-005: 오늘 이미 theme_propagation 있는 종목 → 중복 생성 안 함
# ---------------------------------------------------------------------------

def test_ac005_existing_theme_propagation_today_no_duplicate(db):
    """AC-005: 오늘 theme_propagation 이미 있으면 중복 생성 안 함."""
    from app.services.surge_detector import detect_near_limit_up_carries

    stock = _make_stock(db, "000050", "테마전파주")
    _make_signal(db, stock.id, signal_type="theme_propagation")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(12700, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# AC-006: 이력 조회 실패(빈 리스트) → 스킵하고 계속 진행
# ---------------------------------------------------------------------------

def test_ac006_price_fetch_failure_skips_and_continues(db):
    """AC-006: 첫 종목 이력 조회 실패(빈 리스트) → 스킵하고 두 번째 종목 처리 계속."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _stock1 = _make_stock(db, "000060", "조회실패주")
    stock2 = _make_stock(db, "000070", "조회성공주")

    history = _make_history(12700, 10000)

    def _mock_provider(stock_code: str, *args, **kwargs):
        if stock_code == "000060":
            return []  # 조회 실패 → 빈 리스트
        return history

    cfg = _make_config()

    with _patch_history(side_effect=_mock_provider):
        signals = detect_near_limit_up_carries(db, cfg)

    # stock2만 생성
    assert len(signals) == 1
    assert signals[0].stock_id == stock2.id


# ---------------------------------------------------------------------------
# AC-007: detect_near_limit_up_carries 내부 예외 → 빈 리스트 반환
# ---------------------------------------------------------------------------

def test_ac007_internal_exception_returns_empty_list(db):
    """AC-007: 내부 예외 발생 시 빈 리스트 반환, 파이프라인 미영향."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000080", "예외발생주")
    cfg = _make_config()

    with _patch_history(side_effect=RuntimeError("네트워크 오류")):
        signals = detect_near_limit_up_carries(db, cfg)

    # 예외가 발생해도 빈 리스트 반환 (파이프라인 보호)
    assert isinstance(signals, list)
    assert signals == []


# ---------------------------------------------------------------------------
# AC-008: max_signals_per_day=2 설정 시 최대 2건만 생성
# ---------------------------------------------------------------------------

def test_ac008_max_signals_per_day_limits_output(db):
    """AC-008: max_signals_per_day=2 설정 시 최대 2건만 생성."""
    from app.services.surge_detector import detect_near_limit_up_carries

    for i in range(5):
        _make_stock(db, f"00010{i}", f"종목{i}")

    cfg = _make_config(max_signals_per_day=2)

    with _patch_history(return_value=_make_history(12700, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 2


# ---------------------------------------------------------------------------
# AC-015: max_signals_per_day 기본값(None) → 상한 없이 전부 생성
# ---------------------------------------------------------------------------

def test_ac015_default_max_signals_per_day_is_unlimited(db):
    """AC-015: max_signals_per_day 미지정(기본값 None) 시 10건 초과도 전부 생성."""
    from app.services.surge_detector import detect_near_limit_up_carries

    for i in range(15):
        _make_stock(db, f"0002{i:02d}", f"종목{i}")

    cfg = _make_config()  # max_signals_per_day 미지정 → 기본값 None

    with _patch_history(return_value=_make_history(12700, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 15


# ---------------------------------------------------------------------------
# AC-009: enabled=False → 빈 리스트 반환
# ---------------------------------------------------------------------------

def test_ac009_disabled_returns_empty_list(db):
    """AC-009: enabled=False 설정 시 즉시 빈 리스트 반환, 이력 조회 자체가 일어나지 않음."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000090", "비활성화주")
    cfg = _make_config(enabled=False)

    with _patch_history(return_value=_make_history(12700, 10000)) as mock_fetch:
        signals = detect_near_limit_up_carries(db, cfg)

    assert signals == []
    mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# AC-010: +29.99% 종목 → 생성됨 (상한가 미달 경계값)
# ---------------------------------------------------------------------------

def test_ac010_boundary_29_99_creates_signal(db):
    """AC-010: T-1 종가-대-종가 +29.99% 종목은 상한가 미달 경계값으로 시그널 생성됨."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000100", "경계값주")
    cfg = _make_config()

    # 10000 * 1.2999 = 12999.0 (정수로 정확히 떨어짐)
    with _patch_history(return_value=_make_history(12999, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1


# ---------------------------------------------------------------------------
# AC-011: +15.0% 종목 → 생성됨 (최소 경계값, 15~24% 모멘텀 이월 대응으로 완화)
# ---------------------------------------------------------------------------

def test_ac011_boundary_15_0_creates_signal(db):
    """AC-011: T-1 종가-대-종가 +15.0% 종목은 완화된 최소 경계값으로 시그널 생성됨."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000110", "최소경계주")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(11500, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1


# ---------------------------------------------------------------------------
# AC-013: +18% 종목 → 생성됨 (기존 25% 하한에서는 제외됐던 구간)
# ---------------------------------------------------------------------------

def test_ac013_18pct_now_qualifies_after_band_widening(db):
    """AC-013: T-1 종가-대-종가 +18% 종목은 완화 전 min_pct=25.0 기준으로는 제외됐으나 완화 후 생성됨."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000130", "밴드확대주")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(11800, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1


# ---------------------------------------------------------------------------
# AC-014: market_cap=NULL 종목도 후보 풀에 포함됨
# ---------------------------------------------------------------------------

def test_ac014_null_market_cap_stock_included_as_candidate(db):
    """AC-014: market_cap이 NULL인 종목도 시총 필터에서 제외되지 않고 후보로 포함됨."""
    from app.services.surge_detector import detect_near_limit_up_carries

    stock = _make_stock(db, "000140", "시총누락주", market_cap=None)

    cfg = _make_config()

    with _patch_history(return_value=_make_history(12700, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    assert signals[0].stock_id == stock.id


# ---------------------------------------------------------------------------
# AC-012: paper_executed=True 확인
# ---------------------------------------------------------------------------

def test_ac012_paper_executed_is_true(db):
    """AC-012: 생성된 시그널의 paper_executed=True 확인."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000120", "페이퍼주")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(12700, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    assert signals[0].paper_executed is True


# ---------------------------------------------------------------------------
# BUGFIX 재현 테스트 (SPEC-AI-023 spec.md 대비 구현 불일치)
# ---------------------------------------------------------------------------

def test_bugfix_ai023_min_market_cap_eok_field_exists_with_default_300(db):
    """BUG: NearLimitUpConfig에 시총 하한 필터 필드(min_market_cap_eok)가 없음."""
    cfg = _make_config()
    assert hasattr(cfg, "min_market_cap_eok")
    assert cfg.min_market_cap_eok == 300


def test_bugfix_ai023_min_market_cap_eok_filters_small_cap_stock(db):
    """BUG: 쿼리에 시총 하한 조건이 없어 min_market_cap_eok 미만 종목도 후보로 평가됨.

    market_cap=100(억원) < min_market_cap_eok=300 인 종목은 후보에서 제외되어야 한다.
    """
    from app.services.surge_detector import detect_near_limit_up_carries

    small_cap = _make_stock(db, "000150", "소형주", market_cap=100)
    cfg = _make_config(min_market_cap_eok=300)

    with _patch_history(return_value=_make_history(12700, 10000)) as mock_fetch:
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 0
    assert all(call.args[0] != small_cap.stock_code for call in mock_fetch.call_args_list)


def test_bugfix_ai023_surge_metadata_has_near_limit_up_carry_true_key(db):
    """BUG: surge_metadata에 SPEC이 요구하는 "near_limit_up_carry": true 키가 없음."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000160", "메타데이터주")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(12700, 10000)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    metadata = json.loads(signals[0].surge_metadata)
    assert metadata.get("near_limit_up_carry") is True
    # 기존 키(yesterday_change_pct 등)는 유지되어야 함
    assert "yesterday_change_pct" in metadata


# ===========================================================================
# SPEC-AI-072: near_limit_up carry-forward 데이터 소스 교정 (T-1 종가 기준)
# ===========================================================================

# ---------------------------------------------------------------------------
# PRESERVE: 구(버그) 동작 characterization — 라이브 change_rate 미사용 회귀 고정
# ---------------------------------------------------------------------------

def test_characterize_near_limit_up_carry_live_price_change_not_used(db):
    """PRESERVE/회귀 고정: SPEC-AI-023 구현은 라이브 ``_fetch_price_change_sync`` 값을

    change_rate/confidence/yesterday_change_pct에 그대로 흘려보내는 버그가 있었다
    (research.md §4 실증: 034940 조아제약, 09:58 KST +29.9% 라이브 → 10:05 KST 잡이
    "전일 29.90% 상승"으로 오라벨).

    SPEC-AI-072 IMPROVE 이후에는 ``_fetch_price_change_sync``가 change_rate 산출에
    전혀 관여하지 않아야 한다 — 라이브 mock을 실제(historical) change_rate와 다른 값으로
    설정해도 생성된 시그널이 라이브 값이 아니라 T-1 종가-대-종가 값을 사용함을 확인한다.
    """
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000170", "라이브오라벨검증주")
    cfg = _make_config()

    # 라이브 mock: 장중 순간 등락률 +29.9% (구 버그라면 이 값이 그대로 사용됨)
    live_mock = {"current_price": 12345, "change_rate": 29.9}
    # 실제 T-1 종가-대-종가는 +18.0% — 라이브 값과 명확히 다르게 설정해 구분 가능하게 함
    history = _make_history(11800, 10000)

    with patch(
        "app.services.surge_detector._fetch_price_change_sync",
        return_value=live_mock,
    ) as mock_live, _patch_history(return_value=history):
        signals = detect_near_limit_up_carries(db, cfg)

    # 라이브 헬퍼는 이 탐지기 경로에서 더 이상 호출되지 않아야 한다(버그 제거 확인).
    mock_live.assert_not_called()

    assert len(signals) == 1
    sig = signals[0]
    metadata = json.loads(sig.surge_metadata)
    # yesterday_change_pct/reasoning/confidence 모두 라이브(29.9)가 아니라 T-1(18.0) 기반이어야 함.
    assert metadata["yesterday_change_pct"] == 18.0
    assert "18.00" in sig.reasoning
    assert "29.9" not in sig.reasoning
    assert abs(sig.confidence - round(18.0 / 30.0 * 0.5, 4)) < 1e-6
    # price_at_signal도 라이브 current_price(12345)가 아니라 T-1 종가(11800)여야 함(REQ-005).
    assert sig.price_at_signal == 11800


# ---------------------------------------------------------------------------
# AC-072-001: T-1 종가-대-종가로 change_rate 계산, 라이브 아님
# ---------------------------------------------------------------------------

def test_ac072_001_change_rate_from_t1_close_to_close(db):
    """AC-072-001: change_rate/confidence/yesterday_change_pct/reasoning이 모두

    T-1 종가-대-종가((close[T-1]-close[T-2])/close[T-2]*100)에서 산출된다.
    """
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000171", "T1종가검증주")
    cfg = _make_config()

    # (127-100)/100*100 = 27.0%
    with _patch_history(return_value=_make_history(127, 100)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    sig = signals[0]
    metadata = json.loads(sig.surge_metadata)
    assert metadata["yesterday_change_pct"] == 27.0
    assert "전일 27.00% 상승" in sig.reasoning
    assert abs(sig.confidence - 0.45) < 0.01


# ---------------------------------------------------------------------------
# AC-072-002: 날짜 매칭으로 T-1 선택, 인덱스 가정 아님
# ---------------------------------------------------------------------------

def test_ac072_002_date_matching_selects_t1_regardless_of_today_partial_row(db):
    """AC-072-002: 당일 partial 행 존재 유무와 무관하게 date 매칭으로 동일한 T-1

    change_rate가 산출된다(인덱스 위치 가정이 아님).
    """
    from app.services.surge_detector import detect_near_limit_up_carries

    stock_with_partial = _make_stock(db, "000172", "당일행있음주")
    stock_without_partial = _make_stock(db, "000173", "당일행없음주")
    cfg = _make_config()

    t1, t2 = _t1_t2_dates()

    history_with_partial = _make_history(
        127, 100, t1=t1, t2=t2, include_today_partial=True, today_close=999,
    )
    history_without_partial = _make_history(127, 100, t1=t1, t2=t2)

    def _mock_provider(stock_code: str, *args, **kwargs):
        if stock_code == stock_with_partial.stock_code:
            return history_with_partial
        if stock_code == stock_without_partial.stock_code:
            return history_without_partial
        return []

    with _patch_history(side_effect=_mock_provider):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 2
    by_stock = {sig.stock_id: sig for sig in signals}
    metadata_a = json.loads(by_stock[stock_with_partial.id].surge_metadata)
    metadata_b = json.loads(by_stock[stock_without_partial.id].surge_metadata)
    # 두 경우 모두 동일한 T-1 change_rate(27.0) — 당일 partial 행(close=999)이 T-1로
    # 오선택되지 않음을 증명.
    assert metadata_a["yesterday_change_pct"] == metadata_b["yesterday_change_pct"] == 27.0


# ---------------------------------------------------------------------------
# AC-072-003: T-1 날짜 부재 종목은 스킵, 배치 미중단
# ---------------------------------------------------------------------------

def test_ac072_003_missing_t1_date_skips_stock_without_aborting_batch(db):
    """AC-072-003: 예상 T-1 날짜가 이력에 없는 종목은 조용히 스킵되고, 후속 종목은

    정상적으로 시그널이 생성된다(배치 중단 없음).
    """
    from app.services.surge_detector import detect_near_limit_up_carries

    stock_c = _make_stock(db, "000174", "T1날짜없는주")
    stock_d = _make_stock(db, "000175", "T1날짜있는주")
    cfg = _make_config()

    t1, t2 = _t1_t2_dates()
    # C: T-1 날짜가 없는 이력 (전부 T-2보다 더 오래된 날짜들로만 구성)
    history_missing_t1 = [
        r for r in _make_history(127, 100, t1=t1, t2=t2)
        if r.date != t1.strftime("%Y.%m.%d")
    ]
    history_ok = _make_history(127, 100, t1=t1, t2=t2)

    def _mock_provider(stock_code: str, *args, **kwargs):
        if stock_code == stock_c.stock_code:
            return history_missing_t1
        return history_ok

    with _patch_history(side_effect=_mock_provider):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    assert signals[0].stock_id == stock_d.id


# ---------------------------------------------------------------------------
# AC-072-004: 임계·공식·시그널 생성 회귀 없음 (경계값 4종 일괄 검증)
# ---------------------------------------------------------------------------

def test_ac072_004_threshold_and_confidence_formula_regression(db):
    """AC-072-004: change_rate 30.0/29.99/15.0/10.0 각각에 대해 임계·confidence 공식·

    signal_type/paper_executed/surge_basis가 change_rate 소스 교체 외 무변경임을 확인.
    """
    from app.services.surge_detector import detect_near_limit_up_carries

    stock_over = _make_stock(db, "000176", "30pct주")
    stock_upper = _make_stock(db, "000177", "29_99pct주")
    stock_lower = _make_stock(db, "000178", "15pct주")
    stock_under = _make_stock(db, "000179", "10pct주")
    cfg = _make_config()

    def _mock_provider(stock_code: str, *args, **kwargs):
        mapping = {
            stock_over.stock_code: _history_for_change(30.0),
            stock_upper.stock_code: _history_for_change(29.99),
            stock_lower.stock_code: _history_for_change(15.0),
            stock_under.stock_code: _history_for_change(10.0),
        }
        return mapping.get(stock_code, [])

    with _patch_history(side_effect=_mock_provider):
        signals = detect_near_limit_up_carries(db, cfg)

    signaled_ids = {sig.stock_id for sig in signals}
    assert stock_over.id not in signaled_ids  # 30.0 → 생성 안 함
    assert stock_upper.id in signaled_ids  # 29.99 → 생성
    assert stock_lower.id in signaled_ids  # 15.0 → 생성
    assert stock_under.id not in signaled_ids  # 10.0 → 생성 안 함

    for sig in signals:
        metadata = json.loads(sig.surge_metadata)
        change_rate = metadata["yesterday_change_pct"]
        assert sig.confidence == round(change_rate / 30.0 * 0.5, 4)
        assert sig.signal_type == "surge_candidate"
        assert sig.paper_executed is True
        assert metadata["surge_basis"] == ["near_limit_up_carry"]


# ---------------------------------------------------------------------------
# AC-072-005: price_at_signal 채워짐, 오라벨 없음
# ---------------------------------------------------------------------------

def test_ac072_005_price_at_signal_filled_from_t1_close_no_mislabel(db):
    """AC-072-005: price_at_signal이 NULL이 아니며 T-1 종가로 채워지고, 라이브 값이

    "전일" 의미로 오라벨되지 않는다.
    """
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000180", "가격기록검증주")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(127, 100)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.price_at_signal is not None
    assert sig.price_at_signal == 127  # T-1 종가


# ---------------------------------------------------------------------------
# EC-1: close[T-2] <= 0 이면 0 나눗셈 방지, 해당 종목 스킵
# ---------------------------------------------------------------------------

def test_ec1_zero_t2_close_skips_stock(db):
    """EC-1: T-2 종가가 0이면 0 나눗셈을 피해 해당 종목을 스킵한다."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000181", "T2제로주")
    cfg = _make_config()

    with _patch_history(return_value=_make_history(127, 0)):
        signals = detect_near_limit_up_carries(db, cfg)

    assert signals == []


# ---------------------------------------------------------------------------
# EC-2: 이력 조회가 빈 리스트를 반환하면 스킵, 배치는 계속됨
# ---------------------------------------------------------------------------

def test_ec2_empty_history_skips_stock_and_continues(db):
    """EC-2: fetch_stock_price_history_sync가 빈 리스트를 반환하면 스킵, 배치는 계속된다."""
    from app.services.surge_detector import detect_near_limit_up_carries

    stock_empty = _make_stock(db, "000182", "이력없음주")
    stock_ok = _make_stock(db, "000183", "이력있음주")
    cfg = _make_config()

    def _mock_provider(stock_code: str, *args, **kwargs):
        if stock_code == stock_empty.stock_code:
            return []
        return _make_history(127, 100)

    with _patch_history(side_effect=_mock_provider):
        signals = detect_near_limit_up_carries(db, cfg)

    assert len(signals) == 1
    assert signals[0].stock_id == stock_ok.id


# ---------------------------------------------------------------------------
# EC-3: T-1은 있으나 T-2가 없으면(pages 부족 등) 스킵
# ---------------------------------------------------------------------------

def test_ec3_t1_present_without_t2_skips_stock(db):
    """EC-3: T-1 레코드는 있으나 그 이전(T-2) 레코드가 없으면 change_rate 계산 불가 →

    해당 종목 스킵.
    """
    from app.services.surge_detector import detect_near_limit_up_carries
    from app.services.naver_finance import PriceRecord

    _make_stock(db, "000184", "T2없음주")
    cfg = _make_config()

    t1, _t2 = _t1_t2_dates()
    history_only_t1 = [PriceRecord(date=t1.strftime("%Y.%m.%d"), close=127)]

    with _patch_history(return_value=history_only_t1):
        signals = detect_near_limit_up_carries(db, cfg)

    assert signals == []


# ---------------------------------------------------------------------------
# EC-4: 함수 최상위 예외 시 기존 try/except가 빈 리스트 반환 (무변경)
# ---------------------------------------------------------------------------

def test_ec4_top_level_exception_returns_empty_list(db):
    """EC-4: 억제되지 않은 예외가 발생하면 기존 try/except가 빈 리스트를 반환해

    상위 파이프라인을 보호한다(무변경).
    """
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000185", "최상위예외주")
    cfg = _make_config()

    with _patch_history(side_effect=RuntimeError("예상치 못한 오류")):
        signals = detect_near_limit_up_carries(db, cfg)

    assert signals == []


# ---------------------------------------------------------------------------
# EC-5: enabled=False → 이력 조회 자체가 일어나지 않음 (AC-009와 중복 검증, 명시적 재확인)
# ---------------------------------------------------------------------------

def test_ec5_disabled_config_never_fetches_history(db):
    """EC-5: config.enabled=False면 즉시 빈 리스트 반환, 이력 조회 자체가 일어나지 않는다."""
    from app.services.surge_detector import detect_near_limit_up_carries

    _make_stock(db, "000186", "비활성화검증주")
    cfg = _make_config(enabled=False)

    with _patch_history(return_value=_make_history(127, 100)) as mock_fetch:
        signals = detect_near_limit_up_carries(db, cfg)

    assert signals == []
    mock_fetch.assert_not_called()
