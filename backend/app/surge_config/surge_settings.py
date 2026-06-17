"""SPEC-AI-012: 급등 징후 탐지 설정 모델.

surge_detection.yaml 파일을 읽어 SurgeDetectionConfig Pydantic 모델로 파싱한다.
앙상블 가중치 합산 검증 포함.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# 설정 파일 경로 (이 파일과 동일 디렉토리)
_CONFIG_PATH = Path(__file__).parent / "surge_detection.yaml"


class RegimeDetectorParams(BaseModel):
    """REQ-018-004: 레짐별 탐지기 파라미터 오버라이드."""

    volume_zscore_threshold: float = 2.5
    news_window_hours: int = 24
    min_news_sentiment: float = 0.3


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

    # P1a: 탐지기 비활성화 플래그 — False이면 detect_volume_news_combo가 빈 목록 반환
    enabled: bool = True
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


class CarryoverConfig(BaseModel):
    """SPEC-AI-039 REQ-039-001: carry-over 최대 거래일 제한 설정."""

    # @MX:NOTE: [AUTO] SPEC-AI-039 — 3 거래일 ≈ 5 역일 (주말 1회 포함). cutoff = today - timedelta(days=int(max_trading_days*1.67))
    # @MX:SPEC: SPEC-AI-039 REQ-039-001
    max_trading_days: int = 3


class HighImpactNewsConfig(BaseModel):
    """SPEC-AI-039 REQ-039-003: 고임팩트 뉴스 키워드 multiplier 설정.

    기술이전/임상/수주 등 급등 트리거 이벤트를 일반 뉴스보다 차별화 탐지.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-039 REQ-039-003 — 키워드 카테고리별 multiplier. get_multiplier()로 접근
    # @MX:SPEC: SPEC-AI-039 REQ-039-003
    tech_transfer: list[str] = Field(default_factory=lambda: ["기술이전", "로열티", "기술수출"])
    tech_transfer_multiplier: float = 2.0
    clinical: list[str] = Field(default_factory=lambda: ["임상", "FDA", "허가", "승인"])
    clinical_multiplier: float = 1.8
    contract: list[str] = Field(default_factory=lambda: ["수주", "계약체결", "파트너십"])
    contract_multiplier: float = 1.5

    def get_multiplier(self, title: str) -> float:
        """뉴스 제목에서 고임팩트 키워드를 탐지하여 multiplier를 반환한다.

        우선순위: tech_transfer(2.0) > clinical(1.8) > contract(1.5) > default(1.0)

        Args:
            title: 뉴스 기사 제목 (또는 title+summary 조합)

        Returns:
            해당 카테고리 multiplier (기본값 1.0)
        """
        for kw in self.tech_transfer:
            if kw in title:
                return self.tech_transfer_multiplier
        for kw in self.clinical:
            if kw in title:
                return self.clinical_multiplier
        for kw in self.contract:
            if kw in title:
                return self.contract_multiplier
        return 1.0


class EnsembleWeightsConfig(BaseModel):
    """앙상블 스코어 가중치."""

    theme_cluster: float
    volume_news_combo: float
    disclosure_pattern: float
    legacy_detectors: float
    # SPEC-AI-039 REQ-039-002: 뉴스 지연 반응 탐지기 가중치
    news_delayed: float = 0.0
    # SPEC-AI-050 REQ-5: 주말 갭업 탐지기 가중치 (커버리지 확장용, 앙상블 합산에는 포함)
    # @MX:NOTE: [AUTO] SPEC-AI-050 REQ-5 — weekend_gap_up은 coverage-expansion 탐지기. 가중치 필드는 합산 검증용
    # @MX:SPEC: SPEC-AI-050 REQ-5
    weekend_gap_up: float = 0.10


class EnsembleConfig(BaseModel):
    """앙상블 스코어링 설정."""

    weights: EnsembleWeightsConfig
    # @MX:NOTE: [AUTO] min_score_for_signal — SPEC-AI-016에서 0.20→0.45로 상향 (정밀도 강화)
    # @MX:SPEC: SPEC-AI-016 REQ-001
    min_score_for_signal: float
    # @MX:NOTE: [AUTO] SPEC-AI-017 REQ-001: 레짐별 임계값 — 없으면 min_score_for_signal 사용
    regime_thresholds: dict[str, float] = {}
    # @MX:NOTE: [AUTO] SPEC-AI-017 REQ-002: 컨센서스 배율 — 복수 탐지기 발동 시 점수 증폭
    consensus_multiplier_two: float = 1.30
    consensus_multiplier_three_plus: float = 1.55
    # @MX:NOTE: [AUTO] SPEC-AI-017 REQ-003: 강한 단일 신호 우회 임계값 (즉각 공시 bypass와 대칭)
    # @MX:NOTE: [AUTO] SPEC-AI-018 REQ-002: 0.72→0.85로 상향 (단일 신호 남용 방지)
    strong_single_bypass_threshold: float = 0.85
    # @MX:NOTE: [AUTO] SPEC-AI-018 REQ-001: 즉각 공시 우회 임계값 — 하드코딩(0.70)에서 설정값으로 이전
    # @MX:SPEC: SPEC-AI-018
    immediate_disclosure_bypass_threshold: float = 0.85


class PriceQueryConfig(BaseModel):
    """가격 배치 조회 설정 (SPEC-AI-016 REQ-004).

    # @MX:NOTE: [AUTO] 배치 가격 조회 파라미터 — Naver Finance 레이트 리미트 회피용
    # @MX:SPEC: SPEC-AI-016
    """

    batch_size: int = 10
    batch_delay_sec: float = 0.5
    retry_count: int = 1


class BacktestConfig(BaseModel):
    """백테스트 설정."""

    enabled: bool
    evaluation_horizon_days: int


class ValuationDisqualifiersConfig(BaseModel):
    """DEPRECATED by SPEC-AI-020. 스키마는 향후 observability/A-B-testing 용도로 보존.
    필터링 로직은 적용되지 않음 (REQ-AI020-005).

    Schema preserved for future use; filter removed by SPEC-AI-020
    (모멘텀-가치 시간축 불일치 교정 — SPEC-AI-018 REQ-006~008 superseded).
    """

    # @MX:NOTE: SPEC-AI-020: deprecated by SPEC-AI-020 — schema preserved, no longer applied
    # @MX:SPEC: SPEC-AI-020
    max_per: float = 500.0
    max_pbr: float = 30.0
    # 스키마 보존: 값이 설정되어 있어도 필터링에 사용하지 않음
    skip_if_missing: bool = True


class DisclosureTypeFilterConfig(BaseModel):
    """SPEC-AI-028: 공시 유형별 역신호 필터링 설정.

    exclusion_patterns: 해당 키워드가 report_name/ai_summary에 포함된 공시는 즉시 시그널 생성 차단.
    penalty_patterns: 해당 키워드가 포함된 경우 immediate_disclosure_score에 penalty_factor 배율 적용.
    skip_bearish_in_today_signals: True이면 get_today_signals()에서 bearish 시그널 제외.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-028 — 역신호 키워드 필터. 코드 변경 없이 운영 조정 가능
    # @MX:SPEC: SPEC-AI-028 REQ-AI028-004
    exclusion_patterns: list[str] = ["유상증자", "전환사채발행", "신주인수권", "주식매수선택권"]
    penalty_patterns: list[str] = ["최대주주변경", "손실", "영업손실"]
    penalty_factor: float = 0.3
    skip_bearish_in_today_signals: bool = True


class ComboChaseGuardConfig(BaseModel):
    """SPEC-AI-030: volume_news_combo 추격매수 방지 게이트 설정.

    4개 게이트로 z-score 임계 돌파 시점에 이미 급등이 끝난 종목을 필터링한다.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-030 — 추격매수 방지 마스터 스위치. False이면 모든 게이트 비활성
    # @MX:SPEC: SPEC-AI-030
    enabled: bool = True
    # Gate 1 (REQ-AI030-001): 당일 과열 필터 — change_rate >= 이 값이면 제외
    overheat_change_pct: float = 5.0
    # Gate 2 (REQ-AI030-002): 거래량 신선도 — volumes[-1]/volumes[-2] < 이 값이면 제외
    min_freshness_ratio: float = 1.5
    # Gate 3 (REQ-AI030-003): 분산 패턴 거부 — change_rate < 이 값이면 제외 (0.0=음수만 제외)
    distribution_change_pct: float = 0.0
    # Gate 1/3 가격 조회 실패 시 제외 여부
    exclude_on_price_unavailable: bool = True
    # Gate 4 (REQ-AI030-004): gather_surge_candidates에서 combo 단독 신호 제외
    require_companion_detector: bool = True


class AdaptiveThresholdConfig(BaseModel):
    """SPEC-AI-029: 적응형 surge_probability 임계값 설정.

    직전 5거래 승률, 시장 레짐 배율, 콤보/테마 게이트를 조합하여
    동적으로 임계값을 산출한다.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-029 — 적응형 임계값 시스템. enabled=False이면 정적 min_score_for_signal 사용
    # @MX:SPEC: SPEC-AI-029 REQ-AI029-001
    enabled: bool = True
    # 직전 N회 종료 거래 승률 계산 창
    win_rate_window: int = 5
    # 승률이 이 값 미만이면 임계값 상향 조정
    win_rate_floor: float = 0.40
    # 승률 미달 시 기본 임계값에 더할 값
    win_rate_addition: float = 0.05
    # 승률 조정 후 상한선
    win_rate_cap: float = 0.70
    # 레짐별 배율: BEAR(신중), SIDEWAYS(중립), BULL(완화)
    regime_multipliers: dict[str, float] = Field(
        default_factory=lambda: {"BEAR": 1.2, "SIDEWAYS": 1.0, "BULL": 0.9}
    )
    # 최종 임계값 하한/상한 클램프
    final_clamp_min: float = 0.45
    final_clamp_max: float = 0.85
    # combo_score=0.0 일 때 테마 점수 최소 기준 (미달 시 종목 제외)
    combo_zero_theme_floor: float = 0.7


class SurgeDetectionConfig(BaseModel):
    """급등 징후 탐지 전체 설정.

    앙상블 가중치 합산이 1.0 (±0.001) 이어야 한다.
    """

    theme_cluster: ThemeClusterConfig
    volume_news_combo: VolumeNewsComboConfig
    disclosure_pattern: DisclosurePatternConfig
    ensemble: EnsembleConfig
    price_query: PriceQueryConfig = PriceQueryConfig()
    backtest: BacktestConfig
    # REQ-018-004: 레짐별 탐지기 파라미터 (BULL/BEAR별 오버라이드)
    regime_detector_params: dict[str, RegimeDetectorParams] = {}
    # SPEC-AI-018 REQ-006: 밸류에이션 부적격 필터 설정
    valuation_disqualifiers: ValuationDisqualifiersConfig = ValuationDisqualifiersConfig()
    # SPEC-AI-028: 공시 유형별 역신호 필터링 설정
    disclosure_type_filter: DisclosureTypeFilterConfig = Field(default_factory=DisclosureTypeFilterConfig)
    # SPEC-AI-029: 적응형 surge_probability 임계값 설정
    adaptive_threshold: AdaptiveThresholdConfig = Field(default_factory=AdaptiveThresholdConfig)
    # SPEC-AI-030: volume_news_combo 추격매수 방지 게이트 설정
    combo_chase_guard: ComboChaseGuardConfig = Field(default_factory=ComboChaseGuardConfig)

    # SPEC-AI-036: 품질 floor 게이트 — 보정 confidence / composite_score 최소값
    # # @MX:NOTE: [AUTO] SPEC-AI-036 — 두 조건 중 하나만 충족해도 시그널 통과 (OR 게이트)
    # # @MX:SPEC: SPEC-AI-036 REQ-036-003
    min_calibrated_confidence: float = 0.35
    min_composite_score: float = 0.60
    # 캘리브레이터 학습 최소 샘플 수
    min_calibration_samples: int = 50

    # SPEC-AI-039 REQ-039-001: carry-over 최대 거래일 제한
    carryover: CarryoverConfig = Field(default_factory=CarryoverConfig)
    # SPEC-AI-039 REQ-039-003: 고임팩트 뉴스 키워드 multiplier
    high_impact_news: HighImpactNewsConfig = Field(default_factory=HighImpactNewsConfig)

    # SPEC-AI-042 REQ-042-008: 장전 갭업 조기 진입 임계값 (하드코딩 금지)
    # 0 <= change_rate < gap_entry_threshold → 조기 진입
    # change_rate >= gap_entry_threshold → skip (갭풀백 위임)
    # @MX:NOTE: [AUTO] SPEC-AI-042 — 갭 필터 임계값. 변경 시 surge_detection.yaml에서만 조정
    gap_entry_threshold: float = 0.05

    # @MX:ANCHOR: [AUTO] 앙상블 가중치 합산 검증 — 6개 탐지기 가중치 합산 반드시 1.0
    # @MX:REASON: 가중치 합산 != 1.0 이면 앙상블 스코어 범위가 0~1을 벗어나 시그널 임계값 판정이 왜곡됨
    @model_validator(mode="after")
    def validate_ensemble_weights(self) -> "SurgeDetectionConfig":
        """앙상블 가중치 합산이 1.0이어야 한다 (SPEC-AI-050: weekend_gap_up 포함 6개)."""
        w = self.ensemble.weights
        total = (
            w.theme_cluster
            + w.volume_news_combo
            + w.disclosure_pattern
            + w.legacy_detectors
            + w.news_delayed
            + w.weekend_gap_up
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"ensemble weights must sum to 1.0 (got {total:.4f})"
            )
        return self


class ThemePropagationConfig(BaseModel):
    """SPEC-AI-022 REQ-001: 테마 전파 시그널 설정."""

    # 앵커 종목의 theme_cluster_score 최소값 (이 이상이면 전파 트리거)
    anchor_score_threshold: float = 0.80
    # 피어 종목의 최근 5일 수익률 임계값 (이 이상이면 이미 급등, 전파 제외)
    peer_price_trend_threshold: float = 20.0
    # 전파 시그널 confidence 고정값
    propagation_confidence: float = 0.25


class VolumeAnomalyConfig(BaseModel):
    """SPEC-AI-022 REQ-002: 비활성 종목 거래량 이상 탐지 설정."""

    # 비활성 기준: 최근 lookback_days 내 surge_candidate 시그널 수
    dormant_signal_count_threshold: int = 3
    dormant_lookback_days: int = 90
    # 최소 시가총액 (억원) — 이 이하 종목은 제외
    min_market_cap: int = 300
    # volume_ratio 임계값 (오늘 거래량 / 최근 60일 평균)
    volume_ratio_threshold: float = 5.0
    # 최소 히스토리 일수
    min_history_days: int = 40
    # confidence = min(ratio / confidence_denominator, max_confidence)
    confidence_denominator: float = 10.0
    max_confidence: float = 0.40
    # 가격 히스토리 조회 페이지 수 (1 page ≈ 10거래일)
    history_pages: int = 6


class NearLimitUpConfig(BaseModel):
    """SPEC-AI-023: 상한가 근접 종목 익일 carry-forward 설정."""

    enabled: bool = True
    # 상한가 근접 기준 최소 등락률 (%)
    near_limit_up_min_pct: float = 25.0
    # 상한가 기준 최대 등락률 (%) — 상한가 도달 시 제외
    near_limit_up_max_pct: float = 29.99
    # 시총 상위 N 종목만 평가
    max_stocks_to_check: int = 500
    # 하루 최대 발행 시그널 수
    max_signals_per_day: int = 10


class InsiderPurchaseConfig(BaseModel):
    """SPEC-AI-024: 임원 자사주 직접 매수 공시 기반 시그널 설정."""

    enabled: bool = True
    base_confidence: float = 0.45
    lookback_days: int = 1


class ThemeGroupCarryConfig(BaseModel):
    """SPEC-AI-025: 테마 그룹 강세 carry-forward 설정."""

    enabled: bool = True
    anchor_surge_min_pct: float = 5.0
    max_signals_per_group: int = 5


class ForumMentionConfig(BaseModel):
    """SPEC-AI-026: 포럼 언급 급증 탐지 설정."""

    enabled: bool = True
    mention_multiplier: float = 5.0
    min_absolute_mentions: int = 10
    baseline_days: int = 7
    mention_window_hours: int = 24
    max_confidence: float = 0.35


class GroupCascadeConfig(BaseModel):
    """SPEC-AI-027: 대기업 그룹 계열사 테마캐리 탐지기 설정."""

    # @MX:NOTE: [AUTO] SPEC-AI-027 — 종목명 접두사 매칭으로 대기업 그룹 계열사 동반 cascade 탐지
    # @MX:SPEC: SPEC-AI-027
    enabled: bool = True
    flagship_prob_threshold: float = 0.70       # 대장주 확률 임계값
    flagship_change_pct: float = 12.0           # 대장주 intraday 등락률 임계값 (%)
    flagship_min_market_cap: int = 50000        # 대장주 최소 시총 (억원, 5조원)
    cascade_min_market_cap: int = 1000          # 계열사 최소 시총 (억원, 1,000억원)
    min_prefix_len: int = 2                     # 그룹 식별 접두사 최소 길이
    max_cascade_per_flagship: int = 3           # 대장주당 최대 계열사 수
    decay_factor: float = 0.7                   # confidence decay 계수
    # SPEC-AI-050 REQ-4: companion guard — effective_confidence < companion_required_below_prob 시
    # 다른 탐지기 시그널(companion)이 없으면 cascade 시그널 차단
    # @MX:NOTE: [AUTO] SPEC-AI-050 REQ-4 — 저확률 단독 cascade 시그널 필터링 (기본값 인스턴스에서만 사용)
    # @MX:SPEC: SPEC-AI-050 REQ-4
    require_companion_detector: bool = True
    companion_required_below_prob: float = 0.4


class BollingerSqueezeConfig(BaseModel):
    """SPEC-AI-051: 볼린저 밴드 스퀴즈 탐지 설정."""

    enabled: bool = True
    # 시총 상위 N 종목만 평가
    max_stocks_to_check: int = 200
    # 일봉 조회 페이지 수 (pages=6 ≈ 60 거래일)
    price_pages: int = 6
    # 스퀴즈 판정 룩백 기간 (영업일)
    lookback_days: int = 60
    # 스퀴즈 점수 최소 임계값 (미만 종목 제외)
    min_squeeze_score: float = 0.5


class GapUpRunnersConfig(BaseModel):
    """SPEC-AI-051: 14:30 갭상승 런너 파이프라인 설정."""

    enabled: bool = True
    # 리더 시그널 최소 confidence 임계값
    min_leader_confidence: float = 0.75
    # 런너 confidence 감쇠율 (leader.confidence * decay)
    confidence_decay: float = 0.7


class CoverageDashboardConfig(BaseModel):
    """SPEC-AI-022 REQ-004: 커버리지 대시보드 API 설정."""

    # 응답 캐시 TTL (초)
    cache_ttl_seconds: int = 60
    # top_missed 조회 시총 최소값 (억원)
    top_missed_min_market_cap: int = 1000
    # top_missed 등락률 최소값 (%)
    top_missed_min_change_pct: float = 15.0
    # top_missed 최대 항목 수
    top_missed_limit: int = 20
    # top_missed 조회 타임아웃 (초)
    top_missed_timeout_seconds: float = 15.0


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


def reload_surge_config() -> SurgeDetectionConfig:
    """싱글턴 캐시를 비우고 surge_detection.yaml을 재로드한다."""
    global _config_singleton
    _config_singleton = _load_config_from_yaml(_CONFIG_PATH)
    logger.info("SurgeDetectionConfig 재로드 완료: %s", _CONFIG_PATH)
    return _config_singleton
