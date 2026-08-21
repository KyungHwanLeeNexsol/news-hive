"""SPEC-AI-117: 급등예측 파이프라인 신뢰성(Tier 0).

AC-AI117-003: `_apply_price_fetch_truncation()`의 가격조회 사전절단 면제
조건을 `entry_pool != "existing"`에서
`entry_pool != "existing" OR candidate.volume_breakout_score >=
volume_breakout_bypass_threshold`로 확장한다(REQ-AI117-003).

M1(gather-timeout 40분 완화)의 회귀 가드는
`tests/test_surge_ai083_intraday_rescan.py::TestCommonInvariants::test_gather_timeout_constant_unchanged`가
소유한다(SPEC-AI-117 소유권 이전 반영, 이 파일에서는 재검증하지 않는다).
"""

from __future__ import annotations

from app.services.surge_detector import SurgeCandidate, _apply_price_fetch_truncation


def _make_candidate(
    code: str,
    entry_pool: str = "existing",
    theme_cluster_score: float = 0.0,
    volume_breakout_score: float = 0.0,
) -> SurgeCandidate:
    """theme_cluster_score(가중치 0.19)/volume_breakout_score(가중치 0.11)만
    채워 _pre_score가 결정론적이 되게 한다(test_spec_ai_096.py와 동일 패턴)."""
    return SurgeCandidate(
        stock_code=code,
        stock_name=f"종목_{code}",
        entry_pool=entry_pool,
        theme_cluster_score=theme_cluster_score,
        volume_breakout_score=volume_breakout_score,
    )


class TestPriceFetchTruncationVolumeBreakoutBypassExemption:
    """AC-AI117-003: volume_breakout_score가 bypass 임계값 이상인
    entry_pool == "existing" 후보는 가격조회 사전절단에서 추가로 면제된다.

    SPEC-AI-117 M2 진단(462860, 더즌)의 실측치를 그대로 사용한다:
    volume_breakout_score=0.50(18~110배 거래량 급증 시 클램프 상한값),
    bypass_threshold=0.30(SPEC-AI-063 volume_breakout_bypass_threshold).
    """

    def _build_merged(self) -> tuple[dict[str, SurgeCandidate], str]:
        merged: dict[str, SurgeCandidate] = {}
        for i in range(50):
            code = f"e{i:05d}"
            # theme_cluster_score 상위 50개 — 사전점수가 target보다 항상 높다
            merged[code] = _make_candidate(code, entry_pool="existing", theme_cluster_score=10.0 + i)
        target_code = "462860"
        merged[target_code] = _make_candidate(
            target_code,
            entry_pool="existing",
            theme_cluster_score=0.0,
            volume_breakout_score=0.50,
        )
        return merged, target_code

    def test_truncated_without_bypass_threshold(self) -> None:
        """무회귀 기준선: volume_breakout_bypass_threshold를 지정하지 않으면
        (기존 SPEC-AI-096 호출 시그니처와 완전히 동일) target은 사전점수
        최하위로 여전히 절단된다."""
        merged, target_code = self._build_merged()
        assert len(merged) == 51  # > 50, 절단 로직 진입

        result = _apply_price_fetch_truncation(merged)

        assert target_code not in result, (
            "volume_breakout_bypass_threshold 미지정 시 target은 절단되어야 한다(무회귀)"
        )
        assert len(result) == 50

    def test_survives_with_bypass_threshold_met(self) -> None:
        """SPEC-AI-117 REQ-AI117-003: volume_breakout_score(0.50)가
        bypass_threshold(0.30) 이상이면 entry_pool == "existing"이어도
        절단에서 면제되어 생존한다."""
        merged, target_code = self._build_merged()
        assert len(merged) == 51

        result = _apply_price_fetch_truncation(
            merged, volume_breakout_bypass_threshold=0.30
        )

        assert target_code in result, (
            "volume_breakout_score가 bypass 임계값 이상이면 절단에서 면제되어야 한다"
        )
        # 면제된 target 1개 + existing 상위 50개 = 51개 전원 생존
        assert len(result) == 51

    def test_below_threshold_still_truncated(self) -> None:
        """volume_breakout_score가 bypass 임계값 미만이면 여전히 절단된다 —
        새 임계값을 도입하지 않고 SPEC-AI-063 기존 값을 그대로 재사용함을
        확인한다."""
        merged, target_code = self._build_merged()
        merged[target_code].volume_breakout_score = 0.10  # < 0.30

        result = _apply_price_fetch_truncation(
            merged, volume_breakout_bypass_threshold=0.30
        )

        assert target_code not in result
        assert len(result) == 50

    def test_pool_member_exemption_unaffected(self) -> None:
        """SPEC-AI-096의 pool 소속 면제 로직 자체는 무변경 — OR 조건 추가만
        확인한다(pool_a/b/c/d 소속 면제 로직 변경 없음, REQ-AI117-006)."""
        merged: dict[str, SurgeCandidate] = {}
        pool_codes = []
        for i in range(40):
            code = f"p{i:05d}"
            pool_codes.append(code)
            merged[code] = _make_candidate(code, entry_pool="pool_a", theme_cluster_score=0.0)
        for i in range(20):
            code = f"e{i:05d}"
            merged[code] = _make_candidate(code, entry_pool="existing", theme_cluster_score=float(i))

        result = _apply_price_fetch_truncation(
            merged, volume_breakout_bypass_threshold=0.30
        )

        for code in pool_codes:
            assert code in result, (
                "pool 소속 후보는 volume_breakout bypass 확장과 무관하게 여전히 전원 생존해야 한다"
            )
        # existing 20개는 캡(50) 미만이라 절단되지 않음 — pool 40개 + existing 20개 전원 생존
        assert len(result) == 60
