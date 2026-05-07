"""SPEC-AI-012: 급등 징후 탐지 설정 모델.

surge_detection.yaml 파일을 읽어 SurgeDetectionConfig Pydantic 모델로 파싱한다.
앙상블 가중치 합산 검증 포함.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, model_validator

logger = logging.getLogger(__name__)

# 설정 파일 경로 (이 파일과 동일 디렉토리)
_CONFIG_PATH = Path(__file__).parent / "surge_detection.yaml"


class ThemeClusterConfig(BaseModel):
    """테마 뉴스 클러스터링 설정."""

    keywords: list[str]
    sector_theme_map: dict[str, list[str]]
    cluster_window_hours: int
    min_article_count: int
    # @MX:NOTE: 시총 단위는 원(KRW) — 100억 = 100_000_000_000
    min_market_cap_krw: int


class VolumeNewsComboConfig(BaseModel):
    """거래량 이상 + 뉴스 콤보 설정."""

    volume_zscore_threshold: float
    volume_baseline_days: int
    news_window_hours: int
    min_news_sentiment: float


class DisclosurePatternConfig(BaseModel):
    """공시 유형별 과거 급등 패턴 설정."""

    historical_surge_threshold_pct: float
    historical_lookback_days: int
    min_surge_rate: float
    min_sample_size: int
    cache_ttl_hours: int
    disclosure_window_hours: int


class EnsembleWeightsConfig(BaseModel):
    """앙상블 스코어 가중치."""

    theme_cluster: float
    volume_news_combo: float
    disclosure_pattern: float
    legacy_detectors: float


class EnsembleConfig(BaseModel):
    """앙상블 스코어링 설정."""

    weights: EnsembleWeightsConfig
    # @MX:NOTE: min_score_for_signal = 0.55 — fund_manager.py의 MIN_ACTION_CONFIDENCE와 동일
    min_score_for_signal: float


class BacktestConfig(BaseModel):
    """백테스트 설정."""

    enabled: bool
    evaluation_horizon_days: int


class SurgeDetectionConfig(BaseModel):
    """급등 징후 탐지 전체 설정.

    앙상블 가중치 합산이 1.0 (±0.001) 이어야 한다.
    """

    theme_cluster: ThemeClusterConfig
    volume_news_combo: VolumeNewsComboConfig
    disclosure_pattern: DisclosurePatternConfig
    ensemble: EnsembleConfig
    backtest: BacktestConfig

    # @MX:ANCHOR: [AUTO] 앙상블 가중치 합산 검증 — 4개 탐지기 가중치 합산 반드시 1.0
    # @MX:REASON: 가중치 합산 != 1.0 이면 앙상블 스코어 범위가 0~1을 벗어나 시그널 임계값 판정이 왜곡됨
    @model_validator(mode="after")
    def validate_ensemble_weights(self) -> "SurgeDetectionConfig":
        """앙상블 가중치 합산이 1.0이어야 한다."""
        w = self.ensemble.weights
        total = w.theme_cluster + w.volume_news_combo + w.disclosure_pattern + w.legacy_detectors
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"ensemble weights must sum to 1.0 (got {total:.4f})"
            )
        return self


def _load_config_from_yaml(path: Path) -> SurgeDetectionConfig:
    """YAML 파일에서 SurgeDetectionConfig를 로드한다."""
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    surge_raw = raw.get("surge_detection", {})
    return SurgeDetectionConfig.model_validate(surge_raw)


# 모듈 수준 싱글턴 — 최초 호출 시 초기화
_config_singleton: SurgeDetectionConfig | None = None


def get_surge_config() -> SurgeDetectionConfig:
    """SurgeDetectionConfig 싱글턴을 반환한다.

    최초 호출 시 surge_detection.yaml을 읽어 초기화한다.
    """
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = _load_config_from_yaml(_CONFIG_PATH)
        logger.debug("SurgeDetectionConfig 로드 완료: %s", _CONFIG_PATH)
    return _config_singleton
