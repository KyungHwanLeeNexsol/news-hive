"""SPEC-AI-097: 급등 후보 스코어링 가격이력 조회 배치·캐싱 성능개선 — 인수 검증 테스트.

AC 검증 목록:
  - AC-097-002 (REQ-003): pages 부족 시 캐시 미스로 재조회
  - AC-097-003 (REQ-003): pages 충분 시 캐시 히트(재조회 없음)
  - AC-097-004 (REQ-002): 배치 함수 동시조회 + 개별 실패 격리
  - AC-097-006 (REQ-005): 성능 측정 로그 존재
  - AC-097-007 (REQ-002, 스레드 안전성): 캐시 동시쓰기 경합 없음
  - AC-097-008 (REQ-004): 매수 주문 실행 경로 diff 0 (grep, 코드 리뷰 성격 — 별도 확인)
  - Edge Cases: pages_fetched 없는 레거시 캐시 상태
"""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.naver_finance import (
    PriceRecord,
    _price_cache,
    fetch_stock_price_history_batch_sync,
    fetch_stock_price_history_sync,
)


@pytest.fixture(autouse=True)
def _clear_price_cache():
    """각 테스트 전후로 _price_cache를 초기화한다(pages_fetched 포함)."""
    _price_cache.data.clear()
    _price_cache.last_updated.clear()
    _price_cache.pages_fetched.clear()
    yield
    _price_cache.data.clear()
    _price_cache.last_updated.clear()
    _price_cache.pages_fetched.clear()


def _fill_cache(code: str, pages: int, n_records: int = 1) -> None:
    """_price_cache에 pages 페이지 분량으로 채워진 상태를 시뮬레이션한다."""
    _price_cache.data[code] = [PriceRecord(date=f"2026.01.0{i+1}", close=1000) for i in range(n_records)]
    _price_cache.last_updated[code] = time.time()
    _price_cache.pages_fetched[code] = pages


# ---------------------------------------------------------------------------
# AC-097-002 / AC-097-003: pages 인지형 캐시 히트 판정
# ---------------------------------------------------------------------------


class TestPagesAwareCacheHit:
    def test_insufficient_pages_forces_refetch(self) -> None:
        """AC-097-002: pages=1로 캐시된 종목에 pages=3 요청 시 HTTP 재조회가 발생한다."""
        _fill_cache("005930", pages=1)

        html = (
            "<table class=\"type2\"><tr>"
            "<td>2026.03.28</td><td>50,000</td><td>1,000</td>"
            "<td>49,500</td><td>50,500</td><td>49,000</td><td>1,234,567</td>"
            "</tr></table>"
        ).encode("euc-kr")

        with patch("app.services.naver_finance.httpx.Client") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.content = html
            mock_resp.raise_for_status = MagicMock()
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.get.return_value = mock_resp

            result = fetch_stock_price_history_sync("005930", pages=3)

        assert mock_client.get.called, "pages 부족 → HTTP 재조회가 발생해야 한다"
        assert _price_cache.pages_fetched["005930"] >= 3
        assert len(result) == 3, "pages=3 요청 → 3페이지(mock 응답 3회) 분량 반환"

    def test_sufficient_pages_skips_refetch(self) -> None:
        """AC-097-003: pages=3으로 캐시된 종목은 pages=1/3 요청 모두 HTTP 재조회 없이 응답한다."""
        _fill_cache("005931", pages=3, n_records=3)

        with patch("app.services.naver_finance.httpx.Client") as mock_client_cls:
            result_1 = fetch_stock_price_history_sync("005931", pages=1)
            result_3 = fetch_stock_price_history_sync("005931", pages=3)

        mock_client_cls.assert_not_called()
        assert len(result_1) == 3
        assert len(result_3) == 3

    def test_legacy_cache_without_pages_fetched_is_treated_as_miss(self) -> None:
        """Edge Case: pages_fetched가 없는 레거시 상태는 0으로 취급되어 항상 미스 처리된다."""
        _price_cache.data["005932"] = [PriceRecord(date="2026.01.01", close=1000)]
        _price_cache.last_updated["005932"] = time.time()
        # pages_fetched는 의도적으로 채우지 않음 (레거시 배포 직후 상태 시뮬레이션)

        assert _price_cache.is_fresh_hit("005932", pages=1, ttl=3600) is False


# ---------------------------------------------------------------------------
# AC-097-004 / AC-097-007: 배치 함수 동시조회 + 실패 격리 + 스레드 안전성
# ---------------------------------------------------------------------------


class TestBatchFetchConcurrency:
    def test_batch_isolates_individual_failures(self) -> None:
        """AC-097-004: N=5 요청 중 2개 실패해도 나머지 3개는 정상 반환되고 예외가 전파되지 않는다."""
        codes = ["A001", "A002", "A003", "A004", "A005"]
        fail_codes = {"A002", "A004"}

        def _fake_sync(code: str, pages: int = 3) -> list[PriceRecord]:
            if code in fail_codes:
                raise RuntimeError(f"simulated failure for {code}")
            return [PriceRecord(date="2026.01.01", close=1000)]

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync", side_effect=_fake_sync
        ):
            results = fetch_stock_price_history_batch_sync(codes, pages=3, batch_size=10)

        assert set(results.keys()) == set(codes)
        for code in fail_codes:
            assert results[code] == [], f"{code}는 실패했으므로 빈 리스트여야 한다"
        for code in set(codes) - fail_codes:
            assert len(results[code]) == 1, f"{code}는 정상 반환되어야 한다"

    def test_batch_no_exception_propagation_on_full_failure(self) -> None:
        """Edge Case: 전체 배치가 실패해도 예외 없이 모든 종목이 빈 리스트로 반환된다."""
        codes = ["B001", "B002", "B003"]

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync",
            side_effect=RuntimeError("network down"),
        ):
            results = fetch_stock_price_history_batch_sync(codes, pages=3, batch_size=10)

        assert set(results.keys()) == set(codes)
        assert all(v == [] for v in results.values())

    def test_batch_stress_no_cache_corruption(self) -> None:
        """AC-097-007: 10개+ 종목을 20회 반복 동시 요청해도 예외/캐시 손상이 없다."""
        codes = [f"S{i:03d}" for i in range(15)]

        def _fake_sync(code: str, pages: int = 3) -> list[PriceRecord]:
            # 실제 함수와 동일하게 캐시에 기록 — 스레드 경합 시나리오 재현
            records = [PriceRecord(date="2026.01.01", close=1000)]
            _price_cache.data[code] = records
            _price_cache.last_updated[code] = time.time()
            _price_cache.pages_fetched[code] = 3
            return records

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync", side_effect=_fake_sync
        ):
            for _ in range(20):
                results = fetch_stock_price_history_batch_sync(codes, pages=3, batch_size=10)
                assert set(results.keys()) == set(codes)
                for code in codes:
                    assert len(results[code]) == 1

        # 캐시 무결성: 모든 종목이 마지막 성공 조회 결과(1개 레코드)와 일치
        for code in codes:
            assert len(_price_cache.data[code]) == 1
            assert _price_cache.pages_fetched[code] == 3

    def test_duplicate_codes_deduplicated(self) -> None:
        """중복된 종목 코드가 입력되어도 한 번만 조회되고 두 스레드가 같은 키를 동시 쓰지 않는다."""
        codes = ["C001", "C001", "C002"]
        call_counts: dict[str, int] = {}

        def _fake_sync(code: str, pages: int = 3) -> list[PriceRecord]:
            call_counts[code] = call_counts.get(code, 0) + 1
            return [PriceRecord(date="2026.01.01", close=1000)]

        with patch(
            "app.services.naver_finance.fetch_stock_price_history_sync", side_effect=_fake_sync
        ):
            results = fetch_stock_price_history_batch_sync(codes, pages=3, batch_size=10)

        assert set(results.keys()) == {"C001", "C002"}
        assert call_counts["C001"] == 1, "중복 코드는 1회만 조회되어야 한다"


# ---------------------------------------------------------------------------
# AC-097-006: 성능 측정 로그
# ---------------------------------------------------------------------------


class TestPerformanceLogging:
    def test_batch_logs_call_count_and_duration(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-097-006: 배치 조회 완료 시 HTTP 호출 수(캐시히트 제외)와 소요시간이 로그에 남는다."""
        codes = ["D001", "D002"]

        def _fake_sync(code: str, pages: int = 3) -> list[PriceRecord]:
            return [PriceRecord(date="2026.01.01", close=1000)]

        with caplog.at_level(logging.INFO, logger="app.services.naver_finance"):
            with patch(
                "app.services.naver_finance.fetch_stock_price_history_sync",
                side_effect=_fake_sync,
            ):
                fetch_stock_price_history_batch_sync(codes, pages=3, batch_size=10)

        matching = [r for r in caplog.records if "가격이력배치" in r.message]
        assert matching, "배치 완료 로그가 존재해야 한다"
        msg = matching[-1].message
        assert "HTTP조회" in msg
        assert "소요" in msg
