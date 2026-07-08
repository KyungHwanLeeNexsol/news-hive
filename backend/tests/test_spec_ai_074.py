"""SPEC-AI-074: Pool B 거래량 순위 후보 레버리지/인버스 ETF·ETN 오염 제거 검증.

Reproduction-First(CLAUDE.md Rule 4): 아래 characterization 테스트는 수정 전 코드에서
실패(크라우딩아웃으로 genuine 종목이 Pool B에 못 듦)함을 먼저 확인한 뒤, 수정 후 통과해야
한다. 픽스처는 2026-07-07 실제 미탐지 사례(109610 에스와이, 비율 6.86x)를 본뜬다.

대상: `build_scan_universe`(surge_detector.py) Pool B 블록, 공유 헬퍼
`stock_registry_service.fetch_tracked_stock_codes`, `naver_finance.fetch_volume_leaders_sync`
페이지네이션.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.services.surge_detector import build_scan_universe, detect_volume_breakout
from app.surge_config.surge_settings import get_surge_config

# ---------------------------------------------------------------------------
# 픽스처 헬퍼 — 레버리지/인버스 ETF·ETN이 절대 거래량 순위 상위를 지배하는 시나리오
# ---------------------------------------------------------------------------

# 2026-07-08 라이브 조사에서 확인된 실제 레버리지/인버스 ETF·ETN 코드(research.md §1)
_ETF_CODES = ["252670", "114800", "252710", "233740", "069500"]

# 각 ETF·ETN의 20일 평균 대비 당일 비율(관측치 0.27x~0.53x, research.md 재현) — (당일, 기준)
_ETF_RATIOS: dict[str, tuple[float, float]] = {
    "252670": (270.0, 1000.0),  # 0.27x
    "114800": (350.0, 1000.0),  # 0.35x
    "252710": (400.0, 1000.0),  # 0.40x
    "233740": (450.0, 1000.0),  # 0.45x
    "069500": (530.0, 1000.0),  # 0.53x
}

# 미추적 필러 종목 수 — 구 limit=100을 채우고도 genuine 종목을 top-N 밖으로 밀어낼 만큼 충분히 크다
_FILLER_COUNT = 130


def _raw_ranking() -> list[str]:
    """ETF·ETN + 미추적 필러가 절대 거래량 상위를 지배하는 픽스처 랭킹(총 136개).

    `109610`(에스와이, 2026-07-07 비율 6.86x 실제 미탐지 사례)은 랭킹 136번째에 위치해
    구 limit=100으로는 결코 후보에 들지 못한다(크라우딩아웃 재현).
    """
    filler = [f"9{i:05d}" for i in range(_FILLER_COUNT)]
    return _ETF_CODES + filler + ["109610"]


class _Bar:
    """fetch_stock_price_history_sync가 반환하는 PriceRecord를 흉내내는 최소 스텁."""

    def __init__(self, volume: float):
        self.volume = volume


def _hist(today_vol: float, baseline_vol: float, n_baseline: int = 20) -> list[_Bar]:
    """history[0]=당일, 이후 n_baseline개는 동일 기준 거래량."""
    return [_Bar(today_vol)] + [_Bar(baseline_vol) for _ in range(n_baseline)]


def _fake_history(code: str, pages: int = 3) -> list[_Bar]:
    """종목별 20일 평균 대비 당일 거래량 비율을 흉내내는 fake history 제공자."""
    if code == "109610":
        return _hist(686.0, 100.0)  # ratio 6.86x
    if code in _ETF_RATIOS:
        today, baseline = _ETF_RATIOS[code]
        return _hist(today, baseline)
    return []  # 필러 종목: history 짧음 → baseline_days+1 미달로 스킵(단순화)


def _volume_leaders_side_effect(ranking: list[str]):
    """실제 fetch_volume_leaders_sync처럼 limit으로 절단하는 fake."""

    def _fake(limit: int = 50, max_pages: int = 1) -> list[str]:
        return ranking[:limit]

    return _fake


# ---------------------------------------------------------------------------
# AC-074-001 — 크라우딩아웃 재현 → 수정 후 genuine 종목 표면화
# ---------------------------------------------------------------------------


class TestPoolBEtfEtnCrowdingOut:
    """SPEC-AI-074 AC-074-001: ETF·ETN 크라우딩아웃 재현 → 수정 후 genuine 종목 표면화."""

    def test_genuine_midcap_surfaces_after_etf_etn_exclusion(self, db: Session, make_stock):
        """109610(에스와이, 비율 6.86x)이 수정 후 Pool B에 포함되고, ETF·ETN은 결코 포함되지 않는다."""
        make_stock(stock_code="109610", name="에스와이")
        # ETF·ETN·필러 코드는 stocks에 미등록(의도적 — 앱이 추적하지 않는 상품/미추적 기업)

        cfg = get_surge_config()
        ranking = _raw_ranking()

        with (
            patch("app.services.naver_finance._is_market_open", return_value=False),
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                side_effect=_volume_leaders_side_effect(ranking),
            ),
            patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                side_effect=_fake_history,
            ),
        ):
            _universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert entry_pool_map.get("109610") == "pool_b", (
            "비율 6.86x genuine 종목(109610)이 ETF·ETN 크라우딩아웃 배제 후 Pool B에 "
            "표면화되어야 한다"
        )
        for etf_code in _ETF_CODES:
            assert entry_pool_map.get(etf_code) != "pool_b", (
                f"레버리지/인버스 ETF·ETN({etf_code})은 stocks 부재 + 비율 미달 이중 배제로 "
                "Pool B에 결코 포함되지 않아야 한다"
            )
        assert pool_counts["pool_b"] >= 1


# ---------------------------------------------------------------------------
# AC-074-002 — 분류가 stocks 교집합(단일 공유 헬퍼)으로 이뤄짐
# ---------------------------------------------------------------------------


class TestPoolBUsesSharedTrackedStockHelper:
    """SPEC-AI-074 AC-074-002: 분류가 SPEC-AI-071과 단일 공유 헬퍼로 이뤄진다."""

    def test_pool_b_calls_shared_fetch_tracked_stock_codes(self, db: Session):
        cfg = get_surge_config()
        with (
            patch("app.services.naver_finance._is_market_open", return_value=False),
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=["109610"],
            ),
            patch(
                "app.services.stock_registry_service.fetch_tracked_stock_codes",
                return_value=set(),
            ) as mock_tracked,
        ):
            build_scan_universe(db, cfg, existing_codes=set())

        assert mock_tracked.called, (
            "Pool B는 SPEC-AI-071과 공유하는 stock_registry_service.fetch_tracked_stock_codes를 "
            "호출해 분류해야 한다(단일 출처, 코드대역 휴리스틱 금지)"
        )


# ---------------------------------------------------------------------------
# AC-074-003 — 배제가 순 genuine 후보를 감소시키지 않음 (오버페치로 크라우딩아웃 보상)
# ---------------------------------------------------------------------------


class TestPoolBOverfetchCompensatesCrowdingOut:
    """SPEC-AI-074 AC-074-003: 배제 후 genuine-stock 후보 수가 배제 전보다 줄지 않는다."""

    def test_multiple_genuine_midcaps_beyond_old_limit_all_surface(
        self, db: Session, make_stock
    ):
        """구 limit=100 밖(135번째 이후)에 위치한 genuine 종목 3개가 모두 표면화되어야 한다."""
        genuine_codes = ["201010", "202020", "203030"]
        for code in genuine_codes:
            make_stock(stock_code=code, name=f"중소형주_{code}")

        etf_filler = _ETF_CODES + [f"9{i:05d}" for i in range(_FILLER_COUNT)]  # 135개
        ranking = etf_filler + genuine_codes  # genuine 3종 모두 135번째 이후(구 limit 밖)

        def _fake_history_multi(code: str, pages: int = 3) -> list[_Bar]:
            if code in genuine_codes:
                return _hist(500.0, 100.0)  # ratio 5.0x
            if code in _ETF_RATIOS:
                today, baseline = _ETF_RATIOS[code]
                return _hist(today, baseline)
            return []

        cfg = get_surge_config()
        with (
            patch("app.services.naver_finance._is_market_open", return_value=False),
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                side_effect=_volume_leaders_side_effect(ranking),
            ),
            patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                side_effect=_fake_history_multi,
            ),
        ):
            _universe, entry_pool_map, pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        for code in genuine_codes:
            assert entry_pool_map.get(code) == "pool_b", (
                f"오버페치로 확보된 슬롯을 genuine 종목({code})이 채워야 한다(크라우딩아웃 완화)"
            )
        assert pool_counts["pool_b"] == len(genuine_codes), (
            "ETF·ETN·필러는 모두 배제되어 genuine 종목만 Pool B에 남아야 한다"
        )


# ---------------------------------------------------------------------------
# AC-074-004 — stocks 조회 실패 시 fail-open
# ---------------------------------------------------------------------------


class TestPoolBStocksLookupFailOpen:
    """SPEC-AI-074 AC-074-004/REQ-004: stocks 조회 실패 시 Pool B가 미필터로 진행한다."""

    def test_intersection_failure_keeps_pool_b_unfiltered(self, db: Session):
        cfg = get_surge_config()
        with (
            patch("app.services.naver_finance._is_market_open", return_value=False),
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=["300001"],
            ),
            patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                return_value=_hist(500.0, 100.0),  # ratio 5.0x
            ),
            patch(
                "app.services.stock_registry_service.fetch_tracked_stock_codes",
                return_value=None,  # stocks 조회 실패 시뮬레이션 (fail-open)
            ),
        ):
            _universe, entry_pool_map, _pool_counts = build_scan_universe(
                db, cfg, existing_codes=set()
            )

        assert entry_pool_map.get("300001") == "pool_b", (
            "stocks 교집합 조회 실패 시 미필터로 진행해 stocks에 없는 코드도 배제되지 "
            "않아야 한다(fail-open)"
        )


# ---------------------------------------------------------------------------
# AC-074-005 — 배제 관측 로깅
# ---------------------------------------------------------------------------


class TestPoolBExclusionLogging:
    """SPEC-AI-074 AC-074-005/REQ-005: 배제 종목 수를 로그로 남긴다(0건이면 무로그)."""

    def test_logs_excluded_count_when_exclusion_occurs(self, db: Session, make_stock, caplog):
        make_stock(stock_code="109610", name="에스와이")
        ranking = _raw_ranking()
        cfg = get_surge_config()

        with (
            patch("app.services.naver_finance._is_market_open", return_value=False),
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                side_effect=_volume_leaders_side_effect(ranking),
            ),
            patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                side_effect=_fake_history,
            ),
            caplog.at_level(logging.INFO, logger="app.services.surge_detector"),
        ):
            build_scan_universe(db, cfg, existing_codes=set())

        assert any(
            "제외" in record.message and "Pool B" in record.message
            for record in caplog.records
        ), "배제 종목 수가 [스캔유니버스] Pool B 로그에 남아야 한다"

    def test_no_exclusion_log_when_nothing_excluded(self, db: Session, make_stock, caplog):
        """AC-074-005: 배제가 0건이면 불필요한 로그를 남기지 않는다."""
        make_stock(stock_code="109610", name="에스와이")
        cfg = get_surge_config()

        with (
            patch("app.services.naver_finance._is_market_open", return_value=False),
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=["109610"],  # 전부 stocks 존재 → 배제 없음
            ),
            patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                side_effect=_fake_history,
            ),
            caplog.at_level(logging.INFO, logger="app.services.surge_detector"),
        ):
            build_scan_universe(db, cfg, existing_codes=set())

        assert not any(
            "미존재 종목 제외" in record.message for record in caplog.records
        ), "배제가 0건이면 제외 로그를 남기지 않아야 한다"


# ---------------------------------------------------------------------------
# AC-074-006 — 공유 fetch 수정 시 detect_volume_breakout 거동 diff 0
# ---------------------------------------------------------------------------


class _FakeHtmlResponse:
    def __init__(self, html: str):
        self.text = html

    def raise_for_status(self) -> None:
        pass


class _FakeHttpxClient:
    """httpx.Client(...)의 생성자 호출 + 컨텍스트 매니저 프로토콜을 흉내내는 테스트 더블.

    (sosok, page) 쿼리 파라미터별 고정 HTML을 반환해 fetch_volume_leaders_sync의
    실제 페이지네이션 루프(naver_finance.py)를 네트워크 없이 검증한다.
    """

    def __init__(
        self,
        html_by_query: dict[tuple[int, int], str],
        raise_at: set[tuple[int, int]] | None = None,
    ):
        self._html_by_query = html_by_query
        self._raise_at = raise_at or set()

    def __call__(self, *args, **kwargs) -> "_FakeHttpxClient":
        return self

    def __enter__(self) -> "_FakeHttpxClient":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def get(self, url: str, headers: dict | None = None) -> _FakeHtmlResponse:
        import re

        sosok = int(re.search(r"sosok=(\d)", url).group(1))
        page_match = re.search(r"page=(\d+)", url)
        page = int(page_match.group(1)) if page_match else 1
        if (sosok, page) in self._raise_at:
            raise ConnectionError(f"모의 네트워크 실패 (sosok={sosok}, page={page})")
        html = self._html_by_query.get((sosok, page), "<html></html>")
        return _FakeHtmlResponse(html)


def _make_html(codes: list[str]) -> str:
    anchors = "".join(
        f'<a class="tltle" href="/item/main.naver?code={c}">종목{c}</a>' for c in codes
    )
    return f"<html><body>{anchors}</body></html>"


class TestFetchVolumeLeadersSyncPagination:
    """SPEC-AI-074 REQ-002: naver_finance.fetch_volume_leaders_sync 페이지네이션(유계 오버페치)."""

    def test_default_max_pages_one_is_single_page_per_market_backward_compat(self):
        """max_pages 기본값 1이면 기존 호출부(detect_volume_breakout)처럼 market당 1페이지만 조회한다."""
        from app.services.naver_finance import fetch_volume_leaders_sync

        page1_codes = [f"1{i:05d}" for i in range(50)]
        fake_client = _FakeHttpxClient({
            (0, 1): _make_html(page1_codes),
            (1, 1): _make_html([]),
        })
        with patch("app.services.naver_finance.httpx.Client", fake_client):
            codes = fetch_volume_leaders_sync(limit=50)

        assert len(codes) == 50, "기본 max_pages=1이면 market당 1페이지만 조회해야 한다(하위 호환)"

    def test_max_pages_fetches_additional_pages_to_fill_limit(self):
        """max_pages > 1이면 limit을 채우기 위해 market별 추가 페이지를 조회한다(오버페치)."""
        from app.services.naver_finance import fetch_volume_leaders_sync

        page1 = [f"1{i:05d}" for i in range(50)]
        page2 = [f"2{i:05d}" for i in range(50)]
        page3 = [f"3{i:05d}" for i in range(40)]
        fake_client = _FakeHttpxClient({
            (0, 1): _make_html(page1),
            (0, 2): _make_html(page2),
            (0, 3): _make_html(page3),
            (1, 1): _make_html([]),  # KOSDAQ은 빈 페이지 — 즉시 종료
        })
        with patch("app.services.naver_finance.httpx.Client", fake_client):
            codes = fetch_volume_leaders_sync(limit=140, max_pages=3)

        assert len(codes) == 140, "market별 최대 3페이지까지 조회해 limit(140)을 채워야 한다"
        assert page1[0] in codes
        assert page3[-1] in codes

    def test_empty_page_stops_pagination_early(self):
        """빈 페이지를 만나면 limit 미달이어도 추가 페이지 조회를 중단한다(목록 끝 감지)."""
        from app.services.naver_finance import fetch_volume_leaders_sync

        page1 = [f"5{i:05d}" for i in range(30)]
        fake_client = _FakeHttpxClient({
            (0, 1): _make_html(page1),
            (0, 2): _make_html([]),  # 목록 끝
            (1, 1): _make_html([]),
        })
        with patch("app.services.naver_finance.httpx.Client", fake_client):
            codes = fetch_volume_leaders_sync(limit=140, max_pages=5)

        assert len(codes) == 30, "빈 페이지 도달 시 limit 미달이어도 페이지네이션을 중단해야 한다"

    def test_limit_reached_on_first_page_skips_remaining_pages(self):
        """limit을 첫 페이지에서 이미 채웠다면 max_pages가 남아 있어도 추가 페이지를 조회하지 않는다."""
        from app.services.naver_finance import fetch_volume_leaders_sync

        page1 = [f"6{i:05d}" for i in range(50)]  # limit(50)과 정확히 일치
        fake_client = _FakeHttpxClient({
            (0, 1): _make_html(page1),
            (1, 1): _make_html([]),
        })
        with patch("app.services.naver_finance.httpx.Client", fake_client):
            codes = fetch_volume_leaders_sync(limit=50, max_pages=3)

        assert len(codes) == 50, "1페이지에서 limit 도달 시 2·3페이지 조회 없이 종료해야 한다"

    def test_page_fetch_exception_stops_that_market_pagination(self):
        """특정 페이지 조회 중 예외가 발생하면 해당 market의 페이지네이션을 중단한다(fail-open)."""
        from app.services.naver_finance import fetch_volume_leaders_sync

        page1 = [f"7{i:05d}" for i in range(30)]  # limit(140) 미달
        fake_client = _FakeHttpxClient(
            {(0, 1): _make_html(page1), (1, 1): _make_html([])},
            raise_at={(0, 2)},  # KOSPI 2페이지 조회 시 네트워크 실패 시뮬레이션
        )
        with patch("app.services.naver_finance.httpx.Client", fake_client):
            codes = fetch_volume_leaders_sync(limit=140, max_pages=3)

        assert len(codes) == 30, (
            "2페이지 조회 실패 시 1페이지 결과는 보존하고 해당 market 페이지네이션만 "
            "중단해야 한다(예외가 전체 함수를 중단시키지 않음)"
        )

    def test_all_duplicate_page_stops_pagination_early(self):
        """신규 코드 없이 중복 코드만 반환하는 페이지를 만나면 추가 페이지 조회를 중단한다."""
        from app.services.naver_finance import fetch_volume_leaders_sync

        page1 = [f"8{i:05d}" for i in range(30)]  # limit(140) 미달
        fake_client = _FakeHttpxClient({
            (0, 1): _make_html(page1),
            (0, 2): _make_html(page1),  # 2페이지가 1페이지와 완전히 동일(중복만) — 목록 끝과 동등
            (1, 1): _make_html([]),
        })
        with patch("app.services.naver_finance.httpx.Client", fake_client):
            codes = fetch_volume_leaders_sync(limit=140, max_pages=3)

        assert len(codes) == 30, "신규 코드 없는 페이지(중복만)를 만나면 페이지네이션을 중단해야 한다"


class TestDetectVolumeBreakoutUnaffectedBySharedFetchChange:
    """SPEC-AI-074 AC-074-006: 공유 fetch 수정 시 detect_volume_breakout 거동 diff 0."""

    def test_detect_volume_breakout_still_calls_with_original_limit_only(
        self, db: Session, make_stock
    ):
        """detect_volume_breakout은 Pool B 전용 오버페치 인자(max_pages) 없이 호출해야 한다."""
        make_stock(stock_code="400001", name="거래량폭발테스트")
        cfg = get_surge_config()

        with (
            patch("app.services.naver_finance._is_market_open", return_value=False),
            patch(
                "app.services.naver_finance.fetch_volume_leaders_sync",
                return_value=["400001"],
            ) as mock_leaders,
            patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                return_value=_hist(4000.0, 1000.0),  # 4x flat 통과
            ),
        ):
            results = detect_volume_breakout(db, cfg)

        mock_leaders.assert_called_once_with(limit=cfg.volume_breakout.max_candidates // 2)
        assert any(r.stock_code == "400001" for r in results), (
            "detect_volume_breakout 거동(임계·후보 탐지)이 공유 fetch 변경과 무관하게 유지되어야 한다"
        )
