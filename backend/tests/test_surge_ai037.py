"""SPEC-AI-037: 급등 탐지 테마 커버리지 확장 및 비테마 팩터 강화 — 인수 조건 테스트.

AC-037-001: 신규 7개 테마 키워드가 config에 포함
AC-037-002a: 완화된 floor(0.55)로 비테마 종목이 통과
AC-037-002b: 과열(volume_z_score >= 3.0) 시 원래 floor(0.7) 적용
AC-037-003: min_market_cap_krw == 50_000_000_000 (500억)
AC-037-004: 모든 sector_theme_map 섹터명이 _SNAPSHOT에 존재
AC-037-005 strong: disclosure_pattern_score >= 0.70 이면 fast path 통과
AC-037-005 weak: disclosure_pattern_score < 0.70 이고 volume_news_combo_score < 0.80 이면 통과 안 함
AC-037-006 regression: 앙상블 가중치 합산 == 1.0
AC-037-006 exception isolation: None / 잘못된 dict 입력 시 예외 없음
"""

import pytest

from app.seed.sectors import _SNAPSHOT
from app.surge_config.surge_settings import SurgeDetectionConfig, get_surge_config
from app.services.surge_threshold_service import is_combo_theme_gate_passed


# ---------------------------------------------------------------------------
# 설정 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg() -> SurgeDetectionConfig:
    """실제 YAML에서 로드한 SurgeDetectionConfig."""
    return get_surge_config()


def _make_cfg_with_floor(floor: float) -> SurgeDetectionConfig:
    """지정한 combo_zero_theme_floor를 사용하는 독립 config를 생성한다."""
    base = get_surge_config()
    # model_copy(deep=True)로 싱글턴에 영향 없이 수정
    copy = base.model_copy(deep=True)
    copy.adaptive_threshold.combo_zero_theme_floor = floor  # type: ignore[assignment]
    return copy


# ---------------------------------------------------------------------------
# AC-037-001: 신규 7개 테마 키워드
# ---------------------------------------------------------------------------

NEW_THEMES = ["게임", "엔터", "조선", "해운물류", "건설부동산", "음식료", "화학소재"]


class TestAC037001ThemeKeywords:
    def test_new_themes_in_keywords(self, cfg: SurgeDetectionConfig) -> None:
        """신규 7개 테마가 theme_cluster.keywords에 모두 포함된다."""
        keywords = cfg.theme_cluster.keywords
        assert len(keywords) >= 20, f"전체 테마 키워드 수 부족: {len(keywords)}"
        for theme in NEW_THEMES:
            assert theme in keywords, f"누락된 테마: {theme}"

    def test_new_themes_in_sector_map(self, cfg: SurgeDetectionConfig) -> None:
        """신규 7개 테마가 theme_cluster.sector_theme_map에 모두 포함된다."""
        sector_map = cfg.theme_cluster.sector_theme_map
        for theme in NEW_THEMES:
            assert theme in sector_map, f"sector_theme_map에 누락된 테마: {theme}"
            assert len(sector_map[theme]) > 0, f"테마 {theme}의 섹터 목록이 비어 있음"


# ---------------------------------------------------------------------------
# AC-037-004: 모든 섹터명이 _SNAPSHOT에 존재
# ---------------------------------------------------------------------------

class TestAC037004SectorNameValidity:
    def test_all_sector_names_in_snapshot(self, cfg: SurgeDetectionConfig) -> None:
        """sector_theme_map의 모든 섹터명이 KRX _SNAPSHOT에 존재한다."""
        snapshot_names = set(_SNAPSHOT.keys())
        invalid = []
        for theme, sectors in cfg.theme_cluster.sector_theme_map.items():
            for sector in sectors:
                if sector not in snapshot_names:
                    invalid.append(f"{theme}: '{sector}'")
        assert not invalid, "_SNAPSHOT에 없는 섹터명 발견:\n" + "\n".join(invalid)


# ---------------------------------------------------------------------------
# AC-037-002a: 완화된 floor(0.55)로 비테마 종목 통과
# ---------------------------------------------------------------------------

class TestAC037002aRelaxedFloor:
    def test_theme_score_at_relaxed_floor_passes(self, cfg: SurgeDetectionConfig) -> None:
        """combo=0.0, theme=0.58 → True (floor=0.55 이상)."""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.58}
        assert is_combo_theme_gate_passed(meta, cfg) is True

    def test_theme_score_exactly_at_floor_passes(self, cfg: SurgeDetectionConfig) -> None:
        """combo=0.0, theme=0.55 → True (floor 경계값 정확히)."""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.55}
        assert is_combo_theme_gate_passed(meta, cfg) is True

    def test_theme_score_below_floor_excluded(self, cfg: SurgeDetectionConfig) -> None:
        """combo=0.0, theme=0.50 → False (floor=0.55 미만)."""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.50}
        assert is_combo_theme_gate_passed(meta, cfg) is False


# ---------------------------------------------------------------------------
# AC-037-002b: 과열(volume_z_score >= 3.0) 시 원래 floor(0.7) 적용
# ---------------------------------------------------------------------------

class TestAC037002bOverheatFloor:
    def test_overheat_applies_original_floor(self, cfg: SurgeDetectionConfig) -> None:
        """volume_z_score=3.5(과열) + combo=0.0 + theme=0.58 → False (원래 0.7 floor 적용)."""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.58, "volume_z_score": 3.5}
        assert is_combo_theme_gate_passed(meta, cfg) is False

    def test_overheat_exact_threshold_applies_original_floor(self, cfg: SurgeDetectionConfig) -> None:
        """volume_z_score=3.0(과열 경계) + combo=0.0 + theme=0.58 → False."""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.58, "volume_z_score": 3.0}
        assert is_combo_theme_gate_passed(meta, cfg) is False

    def test_below_overheat_uses_relaxed_floor(self, cfg: SurgeDetectionConfig) -> None:
        """volume_z_score=2.9(과열 미만) + combo=0.0 + theme=0.58 → True (완화 floor 적용)."""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.58, "volume_z_score": 2.9}
        assert is_combo_theme_gate_passed(meta, cfg) is True

    def test_overheat_high_theme_passes(self, cfg: SurgeDetectionConfig) -> None:
        """volume_z_score=3.5(과열) + combo=0.0 + theme=0.75 → True (원래 0.7 이상)."""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.75, "volume_z_score": 3.5}
        assert is_combo_theme_gate_passed(meta, cfg) is True


# ---------------------------------------------------------------------------
# AC-037-003: min_market_cap_krw == 50_000_000_000 (500억)
# ---------------------------------------------------------------------------

class TestAC037003MinMarketCap:
    def test_min_market_cap_krw(self, cfg: SurgeDetectionConfig) -> None:
        """min_market_cap_krw가 50_000_000_000원(500억)이어야 한다."""
        assert cfg.theme_cluster.min_market_cap_krw == 50_000_000_000


# ---------------------------------------------------------------------------
# AC-037-005: 비테마 fast path
# ---------------------------------------------------------------------------

class TestAC037005NonThemeFastPath:
    def test_strong_disclosure_score_fast_path(self, cfg: SurgeDetectionConfig) -> None:
        """combo=0.0, theme=0.0, disclosure_pattern_score=0.72 → True (strong fast path)."""
        meta = {
            "combo_score": 0.0,
            "theme_cluster_score": 0.0,
            "disclosure_pattern_score": 0.72,
        }
        assert is_combo_theme_gate_passed(meta, cfg) is True

    def test_disclosure_score_at_threshold_fast_path(self, cfg: SurgeDetectionConfig) -> None:
        """combo=0.0, theme=0.0, disclosure_pattern_score=0.70 → True (fast path 경계값)."""
        meta = {
            "combo_score": 0.0,
            "theme_cluster_score": 0.0,
            "disclosure_pattern_score": 0.70,
        }
        assert is_combo_theme_gate_passed(meta, cfg) is True

    def test_weak_disclosure_score_no_fast_path(self, cfg: SurgeDetectionConfig) -> None:
        """combo=0.0, theme=0.0, disclosure=0.30 → False (fast path 미충족)."""
        meta = {
            "combo_score": 0.0,
            "theme_cluster_score": 0.0,
            "disclosure_pattern_score": 0.30,
            "volume_news_combo_score": 0.50,
        }
        assert is_combo_theme_gate_passed(meta, cfg) is False

    def test_strong_volume_news_combo_fast_path(self, cfg: SurgeDetectionConfig) -> None:
        """combo=0.0, theme=0.0, volume_news_combo_score=0.82, 비과열 → True (volume fast path)."""
        meta = {
            "combo_score": 0.0,
            "theme_cluster_score": 0.0,
            "volume_news_combo_score": 0.82,
            "volume_z_score": 2.0,  # 비과열
            "disclosure_pattern_score": 0.30,
        }
        assert is_combo_theme_gate_passed(meta, cfg) is True

    def test_strong_volume_news_overheat_no_fast_path(self, cfg: SurgeDetectionConfig) -> None:
        """volume_news_combo_score=0.82이어도 과열(z=3.2) 시 fast path 적용 안 함."""
        meta = {
            "combo_score": 0.0,
            "theme_cluster_score": 0.0,
            "volume_news_combo_score": 0.82,
            "volume_z_score": 3.2,  # 과열
            "disclosure_pattern_score": 0.30,
        }
        # 과열 + theme=0.0 < original floor 0.7 → False
        assert is_combo_theme_gate_passed(meta, cfg) is False


# ---------------------------------------------------------------------------
# AC-037-006: 앙상블 가중치 합산 회귀 + 예외 격리
# ---------------------------------------------------------------------------

class TestAC037006Regression:
    def test_ensemble_weights_sum_to_one(self, cfg: SurgeDetectionConfig) -> None:
        """앙상블 가중치 합산이 1.0 (±0.001) 이어야 한다."""
        w = cfg.ensemble.weights
        total = w.theme_cluster + w.volume_news_combo + w.disclosure_pattern + w.legacy_detectors
        assert abs(total - 1.0) < 0.001, f"가중치 합산 오류: {total:.4f}"

    def test_none_metadata_no_exception(self, cfg: SurgeDetectionConfig) -> None:
        """surge_metadata=None 입력 시 예외 없이 True 반환."""
        result = is_combo_theme_gate_passed(None, cfg)
        assert result is True

    def test_empty_dict_metadata_no_exception(self, cfg: SurgeDetectionConfig) -> None:
        """combo_score 키 없는 빈 dict 입력 시 예외 없이 True 반환 (레거시 시그널)."""
        result = is_combo_theme_gate_passed({}, cfg)
        assert result is True

    def test_garbage_values_no_exception(self, cfg: SurgeDetectionConfig) -> None:
        """잘못된 타입 값 포함 dict 입력 시 예외 없이 처리된다."""
        meta = {"combo_score": "invalid", "theme_cluster_score": None, "volume_z_score": "bad"}
        try:
            is_combo_theme_gate_passed(meta, cfg)
        except Exception as exc:
            pytest.fail(f"예외 발생하면 안 됨: {exc}")

    def test_missing_volume_z_no_exception(self, cfg: SurgeDetectionConfig) -> None:
        """volume_z_score 키 없는 경우 예외 없이 처리된다 (비과열로 간주)."""
        meta = {"combo_score": 0.0, "theme_cluster_score": 0.58}
        result = is_combo_theme_gate_passed(meta, cfg)
        # volume_z_score 없으면 0.0으로 간주 → 비과열 → 완화 floor 0.55 적용 → 0.58 >= 0.55 → True
        assert result is True
