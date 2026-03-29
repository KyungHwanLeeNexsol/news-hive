"""topic_clustering.py 단위 테스트.

SPEC-NEWS-002 Phase 3, TASK-009 (REQ-NEWS-006)
토픽 클러스터링의 순수 함수와 클러스터링 로직을 검증한다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.topic_clustering import (
    NewsCluster,
    _bigram_similarity,
    _title_bigrams,
    cluster_news,
)


# ---------------------------------------------------------------------------
# _title_bigrams 테스트
# ---------------------------------------------------------------------------

class TestTitleBigrams:
    """제목 bigram 추출 테스트."""

    def test_normal_string(self) -> None:
        bigrams = _title_bigrams("abcd")
        assert bigrams == {"ab", "bc", "cd"}

    def test_korean_string(self) -> None:
        bigrams = _title_bigrams("삼성전자")
        assert "삼성" in bigrams
        assert "전자" in bigrams

    def test_single_char(self) -> None:
        assert _title_bigrams("a") == set()

    def test_empty_string(self) -> None:
        assert _title_bigrams("") == set()

    def test_whitespace_stripped(self) -> None:
        bigrams = _title_bigrams("  ab  ")
        assert bigrams == {"ab"}

    def test_lowercased(self) -> None:
        bigrams = _title_bigrams("AB")
        assert "ab" in bigrams


# ---------------------------------------------------------------------------
# _bigram_similarity 테스트
# ---------------------------------------------------------------------------

class TestBigramSimilarity:
    """Jaccard 유사도 계산 테스트."""

    def test_identical_sets(self) -> None:
        bg = {"ab", "bc", "cd"}
        assert _bigram_similarity(bg, bg) == 1.0

    def test_disjoint_sets(self) -> None:
        assert _bigram_similarity({"ab", "bc"}, {"xy", "yz"}) == 0.0

    def test_partial_overlap(self) -> None:
        sim = _bigram_similarity({"ab", "bc", "cd"}, {"ab", "bc", "xy"})
        # intersection=2, union=4 -> 0.5
        assert sim == pytest.approx(0.5)

    def test_empty_set_a(self) -> None:
        assert _bigram_similarity(set(), {"ab"}) == 0.0

    def test_empty_set_b(self) -> None:
        assert _bigram_similarity({"ab"}, set()) == 0.0

    def test_both_empty(self) -> None:
        assert _bigram_similarity(set(), set()) == 0.0


# ---------------------------------------------------------------------------
# NewsCluster 테스트
# ---------------------------------------------------------------------------

class TestNewsCluster:
    """NewsCluster 데이터 클래스 테스트."""

    def test_size_property(self) -> None:
        cluster = NewsCluster(
            sector_id=1,
            sector_name="반도체",
            articles=[{"title": "a"}, {"title": "b"}],
        )
        assert cluster.size == 2

    def test_summary_normal(self) -> None:
        cluster = NewsCluster(sector_id=1, sector_name="반도체", articles=[{}] * 3)
        assert "반도체: 3건" in cluster.summary_for_prompt()

    def test_summary_hot_topic(self) -> None:
        cluster = NewsCluster(
            sector_id=1, sector_name="반도체",
            articles=[{}] * 5, is_hot_topic=True,
        )
        summary = cluster.summary_for_prompt()
        assert "[핫 토픽]" in summary
        assert "5건" in summary


# ---------------------------------------------------------------------------
# cluster_news 테스트
# ---------------------------------------------------------------------------

class TestClusterNews:
    """클러스터링 메인 함수 테스트."""

    def _make_article(
        self, title: str, sector_id: int = 1,
        sector_name: str = "반도체",
        hours_ago: float = 0,
    ) -> dict:
        pub = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        return {
            "title": title,
            "sector_id": sector_id,
            "sector_name": sector_name,
            "published_at": pub,
        }

    def test_empty_input(self) -> None:
        assert cluster_news([]) == []

    def test_single_article(self) -> None:
        articles = [self._make_article("삼성전자 실적 발표")]
        clusters = cluster_news(articles)
        assert len(clusters) == 1
        assert clusters[0].size == 1

    def test_similar_titles_grouped(self) -> None:
        """유사한 제목의 기사가 같은 클러스터로 그룹핑."""
        articles = [
            self._make_article("삼성전자 3분기 실적 발표 호실적"),
            self._make_article("삼성전자 3분기 실적 발표 예상 상회"),
            self._make_article("삼성전자 3분기 실적 발표 영업이익 증가"),
        ]
        clusters = cluster_news(articles, similarity_threshold=0.3)
        # 유사한 제목이므로 1개 클러스터로 그룹핑되어야 함
        assert len(clusters) == 1
        assert clusters[0].size == 3

    def test_different_titles_separate_clusters(self) -> None:
        """다른 주제의 기사는 별도 클러스터로 분리."""
        articles = [
            self._make_article("삼성전자 반도체 공장 증설 계획"),
            self._make_article("삼성전자 반도체 공장 증설 발표"),
            self._make_article("삼성전자 반도체 공장 증설 확정"),
            self._make_article("현대차 수소차 전략 발표 수출"),
            self._make_article("현대차 수소차 전략 수출 목표"),
            self._make_article("현대차 수소차 전략 확대 계획"),
        ]
        clusters = cluster_news(articles, similarity_threshold=0.3)
        # 2개 그룹으로 나뉘어야 함 (삼성전자 vs 현대차)
        assert len(clusters) >= 2

    def test_hot_topic_detection(self) -> None:
        """5건 이상 유사 기사가 있으면 핫 토픽으로 마킹."""
        articles = [
            self._make_article(f"삼성전자 HBM 생산량 증가 뉴스 {i}")
            for i in range(6)
        ]
        clusters = cluster_news(articles, hot_topic_min_size=5)
        hot_clusters = [c for c in clusters if c.is_hot_topic]
        # 유사한 제목이 6개이므로 핫 토픽이 감지되어야 함
        assert len(hot_clusters) >= 1

    def test_time_window_filter(self) -> None:
        """시간 범위 밖의 기사는 제외."""
        articles = [
            self._make_article("삼성전자 실적", hours_ago=0),
            self._make_article("삼성전자 실적 발표", hours_ago=48),  # 48시간 전 -> 24h 범위 밖
        ]
        clusters = cluster_news(articles, time_window_hours=24)
        total_articles = sum(c.size for c in clusters)
        assert total_articles == 1

    def test_multiple_sectors(self) -> None:
        """다른 섹터의 기사는 별도로 클러스터링."""
        articles = [
            self._make_article("반도체 호황", sector_id=1, sector_name="반도체"),
            self._make_article("반도체 호황 지속", sector_id=1, sector_name="반도체"),
            self._make_article("반도체 호황 전망", sector_id=1, sector_name="반도체"),
            self._make_article("철강 수요 증가", sector_id=2, sector_name="철강"),
            self._make_article("철강 수요 증가 전망", sector_id=2, sector_name="철강"),
            self._make_article("철강 수요 증가 확대", sector_id=2, sector_name="철강"),
        ]
        clusters = cluster_news(articles)
        sector_ids = {c.sector_id for c in clusters}
        assert 1 in sector_ids
        assert 2 in sector_ids

    def test_no_sector_id_skipped(self) -> None:
        """sector_id가 없는 기사는 클러스터링에서 제외."""
        articles = [
            {"title": "기사 제목", "published_at": datetime.now(timezone.utc)},
        ]
        clusters = cluster_news(articles)
        assert len(clusters) == 0

    def test_naive_datetime_handled(self) -> None:
        """timezone-naive datetime도 정상 처리."""
        articles = [
            {
                "title": "삼성전자 실적",
                "sector_id": 1,
                "sector_name": "반도체",
                "published_at": datetime.utcnow(),  # naive datetime
            },
        ]
        clusters = cluster_news(articles)
        assert len(clusters) == 1

    def test_custom_threshold(self) -> None:
        """similarity_threshold를 높이면 더 엄격하게 분리."""
        articles = [
            self._make_article("삼성전자 실적 발표"),
            self._make_article("삼성전자 매출 공개"),
            self._make_article("삼성전자 영업이익 분석"),
        ]
        # 높은 임계값: 더 많은 클러스터
        strict = cluster_news(articles, similarity_threshold=0.8)
        # 낮은 임계값: 더 적은 클러스터
        loose = cluster_news(articles, similarity_threshold=0.1)
        assert len(strict) >= len(loose)
