"""뉴스 토픽 클러스터링 -- 동일 섹터 내 유사 뉴스를 그룹핑하여 핫 토픽을 감지한다.

SPEC-NEWS-002 Phase 3, TASK-009 (REQ-NEWS-006)
간단한 응집 클러스터링(agglomerative clustering)으로 구현한다.
외부 ML 라이브러리 의존 없이 character bigram Jaccard 유사도를 사용한다.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _title_bigrams(title: str) -> set[str]:
    """제목에서 character bigram 집합을 추출한다."""
    title = title.strip().lower()
    if len(title) < 2:
        return set()
    return {title[i : i + 2] for i in range(len(title) - 1)}


def _bigram_similarity(bg_a: set[str], bg_b: set[str]) -> float:
    """두 bigram 집합의 Jaccard 유사도를 계산한다."""
    if not bg_a or not bg_b:
        return 0.0
    return len(bg_a & bg_b) / len(bg_a | bg_b)


@dataclass
class NewsCluster:
    """뉴스 클러스터 -- 유사 주제의 뉴스 그룹."""

    sector_id: int
    sector_name: str
    articles: list[dict] = field(default_factory=list)
    is_hot_topic: bool = False  # True if 5+ articles

    @property
    def size(self) -> int:
        return len(self.articles)

    def summary_for_prompt(self) -> str:
        """AI 프롬프트에 포함할 클러스터 요약."""
        if self.is_hot_topic:
            return f"[핫 토픽] {self.sector_name}: {self.size}건의 관련 뉴스"
        return f"{self.sector_name}: {self.size}건"


def cluster_news(
    articles: list[dict],
    similarity_threshold: float = 0.3,
    hot_topic_min_size: int = 5,
    time_window_hours: int = 24,
) -> list[NewsCluster]:
    """섹터별 뉴스를 클러스터링하고 핫 토픽을 감지한다.

    Args:
        articles: 뉴스 기사 리스트 (sector_id, sector_name, title, published_at 포함)
        similarity_threshold: bigram 유사도 임계값 (기본 0.3)
        hot_topic_min_size: 핫 토픽으로 간주할 최소 클러스터 크기 (기본 5)
        time_window_hours: 클러스터링 대상 시간 범위 (기본 24시간)

    Returns:
        list[NewsCluster]: 섹터별 뉴스 클러스터 리스트
    """
    if not articles:
        return []

    # 시간 범위 필터링
    cutoff = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
    filtered: list[dict] = []
    for a in articles:
        pub = a.get("published_at")
        if pub is None:
            # published_at이 없으면 포함 (최근 기사로 간주)
            filtered.append(a)
            continue
        # timezone-naive datetime 처리
        if hasattr(pub, "tzinfo") and pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub >= cutoff:
            filtered.append(a)

    if not filtered:
        return []

    # 섹터별 그룹핑
    sector_groups: dict[int, list[dict]] = {}
    sector_names: dict[int, str] = {}
    for a in filtered:
        sid = a.get("sector_id")
        if sid is None:
            continue
        if sid not in sector_groups:
            sector_groups[sid] = []
            sector_names[sid] = a.get("sector_name", f"섹터_{sid}")
        sector_groups[sid].append(a)

    all_clusters: list[NewsCluster] = []

    for sid, group in sector_groups.items():
        # 3건 미만인 섹터는 단일 클러스터로 처리
        if len(group) < 3:
            cluster = NewsCluster(
                sector_id=sid,
                sector_name=sector_names[sid],
                articles=group,
                is_hot_topic=False,
            )
            all_clusters.append(cluster)
            continue

        # 각 기사의 bigram 사전 계산
        bigrams_list: list[set[str]] = [
            _title_bigrams(a.get("title", "")) for a in group
        ]

        # 응집 클러스터링: 각 기사를 기존 클러스터에 추가하거나 새 클러스터 생성
        # clusters: list of (대표 bigram, 기사 인덱스 리스트)
        clusters: list[tuple[set[str], list[int]]] = []

        for i, bg in enumerate(bigrams_list):
            if not bg:
                # bigram이 없는 기사는 독립 클러스터
                clusters.append((bg, [i]))
                continue

            best_cluster_idx = -1
            best_similarity = 0.0

            for ci, (rep_bg, _members) in enumerate(clusters):
                if not rep_bg:
                    continue
                sim = _bigram_similarity(bg, rep_bg)
                if sim >= similarity_threshold and sim > best_similarity:
                    best_similarity = sim
                    best_cluster_idx = ci

            if best_cluster_idx >= 0:
                # 기존 클러스터에 추가
                clusters[best_cluster_idx][1].append(i)
                # 대표 bigram 업데이트 (합집합 접근 -- 클러스터 확장)
                clusters[best_cluster_idx] = (
                    clusters[best_cluster_idx][0] | bg,
                    clusters[best_cluster_idx][1],
                )
            else:
                # 새 클러스터 생성
                clusters.append((bg, [i]))

        # NewsCluster 객체로 변환
        for _rep_bg, member_indices in clusters:
            cluster_articles = [group[idx] for idx in member_indices]
            is_hot = len(cluster_articles) >= hot_topic_min_size
            cluster = NewsCluster(
                sector_id=sid,
                sector_name=sector_names[sid],
                articles=cluster_articles,
                is_hot_topic=is_hot,
            )
            all_clusters.append(cluster)

    hot_count = sum(1 for c in all_clusters if c.is_hot_topic)
    if hot_count:
        logger.info(f"토픽 클러스터링: {len(all_clusters)}개 클러스터, {hot_count}개 핫 토픽")

    return all_clusters
