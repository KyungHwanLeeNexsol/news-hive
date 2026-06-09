"""SPEC-AI-042: preday_signal_service 인수 검증 테스트.

커버하는 요구사항:
  REQ-042-001: 장 마감 후 공시 스캔 → preday_disclosure 시그널 저장
  REQ-042-002: 동일 disclosure_id 중복 저장 방지
  REQ-042-003: 장전 워치리스트 갱신 — 재스캔 중복 없음
  REQ-042-004: get_today_signals이 preday_disclosure 포함
  REQ-042-005: 09:05 조기 진입 체크 — 갭 조회 및 필터 적용
  REQ-042-006: 갭 필터 경계값 (0%, 5%, 경계 초과/미만)
  REQ-042-007: execute_buy_orders 재사용
  REQ-042-009: get_today_signals preday 당일 08:00 cutoff
  REQ-042-012: 종목 갭 조회 실패 시 나머지 정상 처리
"""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import ARRAY, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.disclosure import Disclosure
from app.models.fund_signal import FundSignal
from app.models.sector import Sector
from app.models.stock import Stock
import app.models.surge_portfolio  # noqa: F401 — surge_trades 테이블을 Base.metadata에 등록

# KST 상수
KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# 인메모리 SQLite DB 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    @compiles(ARRAY, "sqlite")
    def _array_sqlite(type_, compiler, **kw):
        return "TEXT"

    _engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(_engine)
    yield _engine
    _engine.dispose()


@pytest.fixture()
def db(engine):
    """각 테스트에 독립적인 세션 (롤백 격리)."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

_sector_cache: dict = {}


def _make_stock(db: Session, code: str, name: str = "테스트종목") -> Stock:
    sector = Sector(name=f"섹터_{code}")
    db.add(sector)
    db.flush()
    stock = Stock(stock_code=code, name=name, sector_id=sector.id)
    db.add(stock)
    db.flush()
    return stock


def _make_disclosure(
    db: Session,
    stock_id: int,
    report_name: str = "자기주식소각",
    rcept_dt: str = "20260609",
) -> Disclosure:
    disc = Disclosure(
        corp_code="00000001",
        corp_name="테스트기업",
        stock_id=stock_id,
        report_name=report_name,
        rcept_no=f"RCEPT-{stock_id}-{rcept_dt}-{report_name[:4]}",
        rcept_dt=rcept_dt,
        url="http://dart.fss.or.kr/test",
    )
    db.add(disc)
    db.flush()
    return disc


def _make_preday_signal(
    db: Session,
    stock_id: int,
    disclosure_id: int | None = None,
    created_at: datetime | None = None,
) -> FundSignal:
    """테스트용 preday_disclosure 시그널 생성."""
    if created_at is None:
        created_at = datetime.now(KST)
    metadata = {"detector": "immediate_disclosure", "source": "immediate_disclosure", "surge_probability_score": 0.8}
    if disclosure_id is not None:
        metadata["disclosure_id"] = disclosure_id
    sig = FundSignal(
        stock_id=stock_id,
        signal="buy",
        confidence=0.8,
        reasoning="테스트 preday 시그널",
        signal_type="preday_disclosure",
        disclosure_id=disclosure_id,
        surge_metadata=json.dumps(metadata),
        created_at=created_at,
    )
    db.add(sig)
    db.flush()
    return sig


# ---------------------------------------------------------------------------
# _save_preday_signal 직접 테스트
# ---------------------------------------------------------------------------

class TestSavePredaySignal:
    """REQ-042-002: 중복 저장 방지."""

    def test_save_preday_signal_first_time_returns_true(self, db: Session):
        """최초 저장 시 True 반환."""
        from app.services.preday_signal_service import _save_preday_signal

        stock = _make_stock(db, "000001")
        disc = _make_disclosure(db, stock.id, "자기주식소각")

        result = _save_preday_signal(
            db,
            stock_id=stock.id,
            stock_code=stock.stock_code,
            disclosure_id=disc.id,
            score=0.85,
            detector="immediate_disclosure",
        )
        assert result is True

    def test_save_preday_signal_dedup_by_disclosure_id(self, db: Session):
        """동일 disclosure_id 두 번 저장 시 두 번째는 False (REQ-042-002)."""
        from app.services.preday_signal_service import _save_preday_signal

        stock = _make_stock(db, "000002")
        disc = _make_disclosure(db, stock.id, "합병결정")

        # 첫 번째 저장
        r1 = _save_preday_signal(
            db,
            stock_id=stock.id,
            stock_code=stock.stock_code,
            disclosure_id=disc.id,
            score=0.80,
            detector="immediate_disclosure",
        )
        # 두 번째 저장 (중복)
        r2 = _save_preday_signal(
            db,
            stock_id=stock.id,
            stock_code=stock.stock_code,
            disclosure_id=disc.id,
            score=0.90,
            detector="immediate_disclosure",
        )
        assert r1 is True
        assert r2 is False

    def test_save_preday_signal_stores_signal_type(self, db: Session):
        """저장된 시그널의 signal_type이 preday_disclosure인지 확인."""
        from app.services.preday_signal_service import _save_preday_signal

        stock = _make_stock(db, "000003")
        disc = _make_disclosure(db, stock.id, "수주계약체결")

        _save_preday_signal(
            db,
            stock_id=stock.id,
            stock_code=stock.stock_code,
            disclosure_id=disc.id,
            score=0.75,
            detector="immediate_disclosure",
        )

        saved = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock.id,
                FundSignal.signal_type == "preday_disclosure",
            )
            .first()
        )
        assert saved is not None
        assert saved.disclosure_id == disc.id
        meta = json.loads(saved.surge_metadata)
        assert meta["detector"] == "immediate_disclosure"


# ---------------------------------------------------------------------------
# post_market_scan 테스트
# ---------------------------------------------------------------------------

class TestPostMarketScan:
    """REQ-042-001: 장 마감 후 공시 스캔."""

    def test_post_market_scan_saves_preday_disclosure(self, db: Session):
        """공시 존재 + 탐지기 반환 → preday_disclosure 시그널 저장 (happy path)."""
        from app.services.preday_signal_service import post_market_scan
        from app.services.surge_detector import SurgeCandidate

        stock = _make_stock(db, "010001", "공시기업A")
        _make_disclosure(db, stock.id, "자기주식소각")

        scan_from = datetime.now(KST) - timedelta(hours=2)

        fake_candidates = [
            SurgeCandidate(
                stock_code=stock.stock_code,
                stock_name=stock.name,
                immediate_disclosure_score=0.90,
                active_detectors=["immediate_disclosure"],
            )
        ]

        with (
            patch(
                "app.services.surge_detector.detect_immediate_disclosure_signal",
                return_value=fake_candidates,
            ),
            patch(
                "app.services.preday_signal_service.detect_immediate_disclosure_signal",
                return_value=fake_candidates,
            ),
            patch(
                "app.services.preday_signal_service.detect_disclosure_surge_pattern",
                return_value=[],
            ),
        ):
            count = post_market_scan(db, scan_from)

        assert count >= 1
        sig = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock.id,
                FundSignal.signal_type == "preday_disclosure",
            )
            .first()
        )
        assert sig is not None

    def test_post_market_scan_dedup_by_disclosure_id(self, db: Session):
        """동일 disclosure_id로 두 번 스캔 → DB에 정확히 1건 (REQ-042-002)."""
        from app.services.preday_signal_service import post_market_scan
        from app.services.surge_detector import SurgeCandidate

        stock = _make_stock(db, "010002", "공시기업B")
        _make_disclosure(db, stock.id, "흡수합병결정")

        scan_from = datetime.now(KST) - timedelta(hours=2)

        fake_candidates = [
            SurgeCandidate(
                stock_code=stock.stock_code,
                stock_name=stock.name,
                immediate_disclosure_score=0.82,
                active_detectors=["immediate_disclosure"],
            )
        ]

        with (
            patch(
                "app.services.preday_signal_service.detect_immediate_disclosure_signal",
                return_value=fake_candidates,
            ),
            patch(
                "app.services.preday_signal_service.detect_disclosure_surge_pattern",
                return_value=[],
            ),
        ):
            count1 = post_market_scan(db, scan_from)
            count2 = post_market_scan(db, scan_from)  # 재스캔 — 중복 방지

        assert count1 >= 1
        assert count2 == 0  # 모두 중복으로 스킵

        # DB에 정확히 1건
        signals = (
            db.query(FundSignal)
            .filter(
                FundSignal.stock_id == stock.id,
                FundSignal.signal_type == "preday_disclosure",
            )
            .all()
        )
        assert len(signals) == 1

    def test_post_market_scan_no_disclosures_returns_zero(self, db: Session):
        """스캔 시작 이후 공시가 없으면 0 반환."""
        from app.services.preday_signal_service import post_market_scan

        # 미래 시간 → 공시 없음
        scan_from = datetime.now(KST) + timedelta(hours=1)

        count = post_market_scan(db, scan_from)
        assert count == 0


# ---------------------------------------------------------------------------
# preopen_watchlist_refresh 테스트
# ---------------------------------------------------------------------------

class TestPreopenWatchlistRefresh:
    """REQ-042-003: 장전 워치리스트 갱신."""

    def test_preopen_watchlist_refresh_no_duplicates(self, db: Session):
        """재스캔 시 중복 저장되지 않음 (REQ-042-002 동일 적용)."""
        from app.services.preday_signal_service import preopen_watchlist_refresh
        from app.services.surge_detector import SurgeCandidate

        stock = _make_stock(db, "020001", "공시기업C")
        _make_disclosure(db, stock.id, "수주계약체결")

        fake_candidates = [
            SurgeCandidate(
                stock_code=stock.stock_code,
                stock_name=stock.name,
                immediate_disclosure_score=0.78,
                active_detectors=["immediate_disclosure"],
            )
        ]

        with (
            patch(
                "app.services.preday_signal_service.detect_immediate_disclosure_signal",
                return_value=fake_candidates,
            ),
            patch(
                "app.services.preday_signal_service.detect_disclosure_surge_pattern",
                return_value=[],
            ),
        ):
            c1 = preopen_watchlist_refresh(db)

        # 재호출 — 중복 방지: 두 번째 스캔도 동일 패치로 실행
        with (
            patch(
                "app.services.preday_signal_service.detect_immediate_disclosure_signal",
                return_value=fake_candidates,
            ),
            patch(
                "app.services.preday_signal_service.detect_disclosure_surge_pattern",
                return_value=[],
            ),
        ):
            c2 = preopen_watchlist_refresh(db)

        assert c1 >= 1
        assert c2 == 0


# ---------------------------------------------------------------------------
# early_entry_check 테스트
# ---------------------------------------------------------------------------

class TestEarlyEntryCheck:
    """REQ-042-005~007: 09:05 조기 진입 체크."""

    def _make_today_preday_signal(self, db: Session, stock_id: int) -> FundSignal:
        """당일 08:00 이후 시각의 preday 시그널 생성."""
        now_kst = datetime.now(KST)
        today_kst = now_kst.date()
        created_at = datetime.combine(today_kst, time(8, 30)).replace(tzinfo=KST)
        return _make_preday_signal(db, stock_id, created_at=created_at)

    def test_early_entry_check_gap_normal_enters(self, db: Session):
        """0 <= gap < 5% → entered >= 1 (REQ-042-006)."""
        from app.services.preday_signal_service import early_entry_check

        stock = _make_stock(db, "030001", "갭정상종목")
        self._make_today_preday_signal(db, stock.id)

        mock_execute_result = {"executed": 1, "skipped": 0, "failed": 0}

        with (
            patch(
                "app.services.preday_signal_service._compute_gap_rate",
                return_value=0.02,  # 2% — 정상 갭
            ),
            patch(
                "app.services.preday_signal_service.execute_buy_orders",
                return_value=mock_execute_result,
            ) as mock_exec,
        ):
            result = early_entry_check(db)

        assert result["entered"] >= 1
        assert result["skipped_gapup"] == 0
        assert result["skipped_gapdown"] == 0
        assert mock_exec.called  # execute_buy_orders 호출됨 (REQ-042-007)

    def test_early_entry_check_gap_above_threshold_skips(self, db: Session):
        """gap >= 5% → skipped_gapup += 1 (REQ-042-006)."""
        from app.services.preday_signal_service import early_entry_check

        stock = _make_stock(db, "030002", "갭업과열종목")
        self._make_today_preday_signal(db, stock.id)

        with patch(
            "app.services.preday_signal_service._compute_gap_rate",
            return_value=0.06,  # 6% — 임계값 초과
        ):
            result = early_entry_check(db)

        assert result["skipped_gapup"] >= 1
        assert result["entered"] == 0

    def test_early_entry_check_gap_negative_skips(self, db: Session):
        """gap < 0% → skipped_gapdown += 1 (REQ-042-006)."""
        from app.services.preday_signal_service import early_entry_check

        stock = _make_stock(db, "030003", "갭다운종목")
        self._make_today_preday_signal(db, stock.id)

        with patch(
            "app.services.preday_signal_service._compute_gap_rate",
            return_value=-0.02,  # -2% — 갭다운
        ):
            result = early_entry_check(db)

        assert result["skipped_gapdown"] >= 1
        assert result["entered"] == 0

    def test_early_entry_check_price_fetch_failure_continues(self, db: Session):
        """1개 종목 갭 조회 실패 → 해당 종목 건너뛰고 나머지 정상 처리 (REQ-042-012)."""
        from app.services.preday_signal_service import early_entry_check

        stock_fail = _make_stock(db, "030004", "갭조회실패종목")
        stock_ok = _make_stock(db, "030005", "갭정상종목2")
        self._make_today_preday_signal(db, stock_fail.id)
        self._make_today_preday_signal(db, stock_ok.id)

        mock_execute_result = {"executed": 1, "skipped": 0, "failed": 0}

        def mock_gap_rate(stock_code: str) -> float | None:
            if stock_code == stock_fail.stock_code:
                return None  # 실패
            return 0.02  # 성공

        with (
            patch(
                "app.services.preday_signal_service._compute_gap_rate",
                side_effect=mock_gap_rate,
            ),
            patch(
                "app.services.preday_signal_service.execute_buy_orders",
                return_value=mock_execute_result,
            ),
        ):
            # execute_buy_orders가 RuntimeError를 발생시키지 않는지 확인
            result = early_entry_check(db)

        # 전체 실패하지 않고 정상 종목 처리됨
        assert result["candidates"] == 2
        assert result["entered"] >= 1  # stock_ok는 정상 처리 (갭 실패 종목은 건너뜀)

    def test_early_entry_check_returns_structured_dict(self, db: Session):
        """반환값이 expected 키를 모두 포함하는지 확인."""
        from app.services.preday_signal_service import early_entry_check

        result = early_entry_check(db)  # 시그널 없음 — candidates=0

        expected_keys = {"candidates", "entered", "skipped_gapup", "skipped_gapdown", "execute_result"}
        assert expected_keys == set(result.keys())


# ---------------------------------------------------------------------------
# _compute_gap_rate 테스트
# ---------------------------------------------------------------------------

class TestComputeGapRate:
    """REQ-042-012: 갭 조회 실패 시 None 반환 (예외 미전파)."""

    def test_compute_gap_rate_returns_float_on_success(self):
        """정상 조회 시 float 반환."""
        from app.services.preday_signal_service import _compute_gap_rate

        with patch(
            "app.services.preday_signal_service.fetch_current_price_with_change_sync",
            return_value={"current_price": 50000, "change_rate": 0.03},
        ):
            result = _compute_gap_rate("005930")

        assert result == pytest.approx(0.03)

    def test_compute_gap_rate_returns_none_on_none_response(self):
        """None 응답 시 None 반환."""
        from app.services.preday_signal_service import _compute_gap_rate

        with patch(
            "app.services.preday_signal_service.fetch_current_price_with_change_sync",
            return_value=None,
        ):
            result = _compute_gap_rate("005930")

        assert result is None

    def test_compute_gap_rate_returns_none_on_exception(self):
        """예외 발생 시 None 반환 — 절대 예외 미전파 (REQ-042-012)."""
        from app.services.preday_signal_service import _compute_gap_rate

        with patch(
            "app.services.preday_signal_service.fetch_current_price_with_change_sync",
            side_effect=Exception("network error"),
        ):
            result = _compute_gap_rate("INVALID")

        assert result is None  # 예외 발생해도 None 반환, 예외 미전파


# ---------------------------------------------------------------------------
# get_today_signals preday_disclosure 포함 확인 (REQ-042-004, REQ-042-009)
# ---------------------------------------------------------------------------

class TestGetTodaySignalsPreday:
    """REQ-042-004/009: get_today_signals preday_disclosure 시그널 포함."""

    def test_get_today_signals_includes_preday_disclosure(self, db: Session):
        """당일 08:00 이후 생성된 preday_disclosure 시그널이 get_today_signals에 포함된다."""
        from app.services.surge_trading_service import get_today_signals
        from decimal import Decimal

        stock = _make_stock(db, "040001", "preday테스트종목")

        # 당일 08:30 KST (cutoff 08:00 이후)
        today_kst = datetime.now(KST).date()
        created_at = datetime.combine(today_kst, time(8, 30)).replace(tzinfo=KST)

        # preday_disclosure 시그널 생성 (확률 0.7)
        metadata = {
            "detector": "immediate_disclosure",
            "source": "immediate_disclosure",
            "surge_probability_score": 0.70,
            "surge_basis": ["immediate_disclosure"],
        }
        sig = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.70,
            reasoning="테스트 preday 시그널",
            signal_type="preday_disclosure",
            surge_metadata=json.dumps(metadata),
            created_at=created_at,
        )
        db.add(sig)
        db.flush()

        # _get_recent_stop_loss_codes는 surge_trades 테이블을 쿼리하므로 패치
        with patch(
            "app.services.surge_trading_service._get_recent_stop_loss_codes",
            return_value=set(),
        ):
            results = get_today_signals(db, min_probability=Decimal("0.30"))

        stock_codes = [r[1].stock_code for r in results]
        assert stock.stock_code in stock_codes, (
            f"preday_disclosure 시그널({stock.stock_code})이 get_today_signals 결과에 없음"
        )

    def test_get_today_signals_excludes_old_preday_disclosure(self, db: Session):
        """당일 08:00 이전 생성된 preday_disclosure 시그널은 제외된다 (REQ-042-009)."""
        from app.services.surge_trading_service import get_today_signals
        from decimal import Decimal

        stock = _make_stock(db, "040002", "구형preday종목")

        # 당일 06:00 KST (cutoff 08:00 이전)
        today_kst = datetime.now(KST).date()
        created_at = datetime.combine(today_kst, time(6, 0)).replace(tzinfo=KST)

        metadata = {
            "detector": "immediate_disclosure",
            "source": "immediate_disclosure",
            "surge_probability_score": 0.70,
            "surge_basis": ["immediate_disclosure"],
        }
        sig = FundSignal(
            stock_id=stock.id,
            signal="buy",
            confidence=0.70,
            reasoning="구형 preday 시그널",
            signal_type="preday_disclosure",
            surge_metadata=json.dumps(metadata),
            created_at=created_at,
        )
        db.add(sig)
        db.flush()

        # _get_recent_stop_loss_codes는 surge_trades 테이블을 쿼리하므로 패치
        with patch(
            "app.services.surge_trading_service._get_recent_stop_loss_codes",
            return_value=set(),
        ):
            results = get_today_signals(db, min_probability=Decimal("0.30"))

        stock_codes = [r[1].stock_code for r in results]
        assert stock.stock_code not in stock_codes, (
            f"08:00 이전 preday 시그널({stock.stock_code})이 결과에 포함되면 안 됨"
        )
