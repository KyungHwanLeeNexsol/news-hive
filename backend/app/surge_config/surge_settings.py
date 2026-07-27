"""SPEC-AI-012: 급등 징후 탐지 설정 모델.

surge_detection.yaml 파일을 읽어 SurgeDetectionConfig Pydantic 모델로 파싱한다.
앙상블 가중치 합산 검증 포함.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# 설정 파일 경로 (이 파일과 동일 디렉토리)
_CONFIG_PATH = Path(__file__).parent / "surge_detection.yaml"
# pytest-xdist 병렬 워커별 파일 분리 — 여러 워커 프로세스가 동일 auto.yaml을 동시에
# 읽고/쓰고/삭제하며 서로의 상태를 덮어쓰는 레이스를 방지한다. PYTEST_XDIST_WORKER는
# xdist가 각 워커 프로세스에 설정하는 환경변수(예: "gw0")로, 운영 환경에서는 절대
# 설정되지 않으므로 프로덕션 동작에는 영향이 없다.
_XDIST_SUFFIX = f".{os.environ['PYTEST_XDIST_WORKER']}" if "PYTEST_XDIST_WORKER" in os.environ else ""
# 자동 개선 오버라이드 파일 (git reset --hard에서 보호됨, .gitignore에 추가됨)
_AUTO_CONFIG_PATH = Path(__file__).parent / f"surge_detection.auto{_XDIST_SUFFIX}.yaml"


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


class VolumeBreakoutConfig(BaseModel):
    """뉴스/공시 없이 거래량 폭발만으로 소형주를 탐지하는 커버리지 확장 탐지기.

    Naver 거래량 순위 상위 종목 중 최근 20일 평균 대비 급증 종목을 후보로 반환.
    """

    enabled: bool = True
    # KOSPI + KOSDAQ 각 max_candidates/2개 조회
    max_candidates: int = 100
    # 평균 대비 최소 배율 (3배 = 비정상 거래 시작)
    volume_ratio_threshold: float = 3.0
    baseline_days: int = 20
    min_history_days: int = 10
    # volume_breakout_score = min(ratio / denominator, max_score)
    confidence_denominator: float = 8.0
    max_score: float = 0.50
    # SPEC-AI-063 REQ-063-002: volume_breakout 단독 bypass 임계값 (앙상블 임계 우회)
    # max_score=0.50 이므로 범위는 [0.20, 0.45] 내에서 자동 조정 (REQ-063-005)
    # @MX:NOTE: [AUTO] SPEC-AI-063 — detector-specific 설정. EnsembleConfig가 아닌 여기에 위치 (의도적)
    # @MX:SPEC: SPEC-AI-063 REQ-063-002
    volume_breakout_bypass_threshold: float = 0.30
    # SPEC-AI-066 REQ-AI066-005: 종목별 상대(z-score) 임계 + 촉매 종목 유니버스 확장 경로.
    # False이면 기존 고정 3.0x 배율/상위 50 유니버스만 사용 (레거시 동작 보존, staged rollout).
    # @MX:NOTE: [AUTO] SPEC-AI-066 REQ-005 — 기본값 False로 하위 호환 유지. surge_baseline_service 재사용
    # @MX:SPEC: SPEC-AI-066 REQ-AI066-005
    relative_threshold_enabled: bool = False


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
    # 거래량 폭발 탐지기 가중치 (소형주 커버리지 확장, 뉴스 없이 거래량만으로 탐지)
    volume_breakout: float = 0.0
    # SPEC-AI-065 REQ-3: 모멘텀 연속 탐지기 가중치
    # 전일 등락률 5~15% 종목의 익일 모멘텀 연속 패턴 탐지
    # @MX:NOTE: [AUTO] SPEC-AI-065 REQ-3 — 8번째 탐지기. volume_breakout(당일 거래량)과 구분됨
    # @MX:SPEC: SPEC-AI-065 REQ-3
    momentum_continuation: float = 0.0


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


class BacktestGateConfig(BaseModel):
    """SPEC-AI-069 REQ-AI069-001: backtest 운영 게이트 판정 floor 설정.

    초기값은 보수적으로 설정하고 Phase 2(REQ-001 배포 후) 데이터 축적을 통해 조정한다.
    """

    # 최소 신호 수 — 미달 시 verdict="insufficient" (EC-2, 데이터 부족)
    min_signals: int = 20
    # 최소 방향성 적중률 — 미달 시 verdict="fail"
    min_directional_accuracy: float = 0.50
    # compute_surge_backtest 조회 기간(일)
    lookback_days: int = 30


class BacktestConfig(BaseModel):
    """백테스트 설정."""

    enabled: bool
    evaluation_horizon_days: int
    # @MX:NOTE: [AUTO] SPEC-AI-069 REQ-001 — backtest 운영 게이트 floor. REQ-002/003 거버넌스가 참조
    # @MX:SPEC: SPEC-AI-069 REQ-AI069-001
    gate: BacktestGateConfig = Field(default_factory=BacktestGateConfig)


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
    # SPEC-AI-066 REQ-AI066-003: 전략적 인수/경영권 프리미엄 공시 페널티 예외.
    # 페널티 대상 공시("최대주주변경" 등)가 인수 호재 맥락이면 penalty_factor 대신
    # acquisition_penalty_factor(0.7)로 부분 완화한다 (완전 면제 아님 — 잔여 리스크 반영).
    # @MX:NOTE: [AUTO] SPEC-AI-066 REQ-003 — 부분 완화(0.3→0.7). exemption_enabled=False이면 레거시 전면 페널티
    # @MX:SPEC: SPEC-AI-066 REQ-AI066-003
    acquisition_exemption_enabled: bool = True
    acquisition_penalty_factor: float = 0.7


class ComboChaseGuardConfig(BaseModel):
    """SPEC-AI-030: volume_news_combo 추격매수 방지 게이트 설정.

    4개 게이트로 z-score 임계 돌파 시점에 이미 급등이 끝난 종목을 필터링한다.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-030 — 추격매수 방지 마스터 스위치. False이면 모든 게이트 비활성
    # @MX:SPEC: SPEC-AI-030
    enabled: bool = True
    # Gate 1 (REQ-AI030-001): 당일 과열 필터 — change_rate >= 이 값이면 제외
    overheat_change_pct: float = 5.0
    # SPEC-AI-066 REQ-AI066-002: 확신도 HIGH일 때만 적용되는 상향 과열 상한.
    # 확정 강한 촉매(M&A·지속 다출처 뉴스)에 개장 갭업하는 종목은 초기 진입이므로 추격매수가 아니다.
    # 신선도(Gate2)·분산(Gate3)·companion(Gate4) 게이트는 확신도와 무관하게 항상 유지된다.
    # @MX:NOTE: [AUTO] SPEC-AI-066 REQ-002 — HIGH 확신도 전용 상한. non-HIGH는 overheat_change_pct(5.0) 유지
    # @MX:SPEC: SPEC-AI-066 REQ-AI066-002
    overheat_change_pct_high_conviction: float = 15.0
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


class PerStockAnalysisConfig(BaseModel):
    """SPEC-AI-060: 종목별 개별 원인 분석 설정."""

    enabled: bool = True
    max_calls_per_run: int = 8
    call_delay_sec: float = 1.0
    fn_priority_over_tp: bool = True
    skip_if_no_context: bool = True


class MomentumContinuationConfig(BaseModel):
    """SPEC-AI-065 REQ-3: 모멘텀 연속 탐지기 설정.

    전일 등락률 5~15% 종목의 익일 모멘텀 연속 패턴을 탐지한다.
    15% 초과(추격매수 방지 REQ-3.4)와 BEAR 레짐에서는 점수를 감쇠한다.
    """

    enabled: bool = True
    # 탐지 기준: 전일 등락률 하한 (%)
    min_change_rate: float = 5.0
    # 탐지 기준: 전일 등락률 상한 (%) — 이 이상이면 탐지 제외 (추격매수 방지)
    max_change_rate: float = 15.0
    # 기본 confidence
    base_score: float = 0.40
    # 등락률에 따른 선형 스케일 상한
    max_score: float = 0.70
    # BEAR 레짐 점수 감쇠율
    bear_dampening: float = 0.7
    # 가격 히스토리 최소 일수 (이하면 탐지 제외)
    min_history_days: int = 5


class CatalystConvictionConfig(BaseModel):
    """SPEC-AI-066 REQ-AI066-001/006: 촉매 확신도(catalyst conviction) 설정.

    확정 강한 촉매(M&A·경영권 매각·지속 다출처 뉴스·공시 뒷받침)를 애매한 거래량 급증과
    구분하는 판별 신호. 확신도가 HIGH일 때만 명시된 완화 경로(과열 상한 상향/공시 페널티
    부분완화)를 조건부로 연다. enabled=False이면 모든 완화가 꺼지고 SPEC-AI-030/028 레거시
    동작이 그대로 복원된다.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-066 REQ-001 — 확신도 완화 마스터 스위치. False이면 REQ-002/003 완화 전면 비활성
    # @MX:SPEC: SPEC-AI-066 REQ-AI066-001
    enabled: bool = True
    # HIGH 확신도 승격 임계: 커버리지 기사 수 / 지속시간(시간) / 감성 강도
    min_article_count_high: int = 5
    min_coverage_hours_high: float = 6.0
    min_sentiment_high: float = 0.5
    # 고임팩트 인수/합병 촉매 키워드 (기존 high_impact_news 키워드에 더해 확신도·페널티 예외 판정에 사용)
    # "최대주주변경"은 페널티 패턴 자체이므로 제외 — 인수 호재 증거는 별도 키워드로 판별한다.
    acquisition_keywords: list[str] = Field(
        default_factory=lambda: ["인수", "합병", "경영권", "M&A", "지분인수", "지분취득"]
    )
    # REQ-004: 뉴스 공동언급 테마 자동 확장 (기본 False — staged rollout)
    comention_theme_enabled: bool = False
    comention_min_pairs: int = 3
    # REQ-007: 고임팩트 뉴스 이벤트 구동 재스캔 (기본 False — staged rollout)
    event_rescan_enabled: bool = False
    # 종목당 재트리거 쿨다운(분) — 동일 종목 반복 트리거 방지
    event_rescan_cooldown_minutes: int = 30
    # 일일 이벤트 트리거 상한 — LLM(Gemini 무료 tier) 예산 보호
    max_daily_event_triggers: int = 20


class IntradayLiveVolumeConfig(BaseModel):
    """SPEC-AI-067 REQ-AI067-007: 장중 실시간 당일 거래량 소스 설정.

    3개 호출부(combo z-score / volume_breakout / Pool B)가 "당일 거래량"으로 사용하는
    값을 장중에 한해 Naver 모바일 API accumulatedTradingVolume(실시간 정확)로 교정한다.
    sise_day "오늘" 행은 장중에 트래픽 의존적으로 지연(최대 4.0x 과소계상)되므로, 그 값을
    모바일 실시간 값으로 대체한다. enabled=false이면 전 호출부가 sise_day 당일값을 쓰는
    레거시 동작으로 복원된다.

    핵심 수정은 REQ-001~005(실시간 모바일 소스 전환)이며, 판별 로직(게이트/임계/가중치)은
    일절 변경하지 않는다 — 오직 게이트에 입력되는 "당일 거래량" 값의 신선도만 높인다.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-067 REQ-001 — 실시간 당일 거래량 마스터 스위치 (기본 활성, D1 확정)
    # @MX:SPEC: SPEC-AI-067 REQ-AI067-007
    enabled: bool = True
    # 장중(_is_market_open())에만 모바일 실시간 조회. 장외엔 완결된 sise_day 당일값 사용.
    market_hours_only: bool = True
    # 스캔당 모바일 실시간 조회 상한 — 레이트리밋 노출 유계. 초과 시 sise_day 폴백. (기본 80, D2 확정)
    max_live_fetches_per_scan: int = 80


class RelativeScoringConfig(BaseModel):
    """SPEC-AI-069 REQ-AI069-004: z-score 상대채점 회귀 격리 설정.

    zscore_enabled=false(기본값)이면 surge_detector.py의 z-score 정규화(sigmoid) 경로를
    우회하고 SPEC-AI-065 이전의 절대 점수(raw score) 채점으로 폴백한다. AI-065 소유 코드
    (surge_baseline_service.zscore_to_score 등)는 재작성하지 않고 게이팅만 추가한다.
    재활성(true)은 backtest(REQ-001)가 z-score 기준 임계값·가중치를 재도출·통과한 이후에만.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-069 REQ-004 — 기본값 false: AI-065 이전 절대채점으로 폴백
    # @MX:SPEC: SPEC-AI-069 REQ-AI069-004
    zscore_enabled: bool = False


class ImmediateSurgeConfig(BaseModel):
    """SPEC-AI-080: 동일-당일 고확신 공시 촉매 즉시 급등 시그널 발화 설정.

    enabled=False(기본값)이면 disclosure_impact_scorer.process_disclosure_impact()의 즉시
    발화 분기 전체가 비활성화되어 레거시 이벤트 구동 경로(반영 체크 예약/gap_pullback)만
    실행된다(Scenario 6, rollback 완전성). 이벤트 클래스 화이트리스트는 별도 목록을 두지
    않고 surge_detector._IMMEDIATE_EVENT_PATTERNS를 read-only로 재사용한다(REQ-AI080-003,
    [X-2] — 탐지기 본체 로직/상수는 변경하지 않음. 단일 출처 유지).
    """

    # @MX:NOTE: [AUTO] SPEC-AI-080 — 즉시 발화 마스터 스위치. 기본값 false(레거시 완전 보존)
    # @MX:SPEC: SPEC-AI-080 REQ-AI080-001
    enabled: bool = False
    # REQ-AI080-002: score_disclosure_impact()의 impact_score(계약금액/시총 스케일, 0~100)
    # 게이팅 임계값. surge_detector의 flat immediate_disclosure_score(0.82)는 재사용하지
    # 않는다([X-4] — 별개 스코어링 시스템, 이벤트 구동 경로 범위 밖).
    min_impact: float = 40.0
    # OQ-2: 배치 스캔 컷오프(KST, 기본 15:20) — 이 시각 이후(또는 장외/야간/장전, 주말)
    # 접수분은 horizon="next_day"(T-1→T recall 편입), 09:00~컷오프 접수분(배치가 이미 볼
    # 수 있었던 시간대)은 horizon="same_day"(REQ-AI080-004 둘째 규칙, 별도 서브지표).
    batch_cutoff_hour: int = 15
    batch_cutoff_minute: int = 20


class DisclosureContentAwareScoringConfig(BaseModel):
    """SPEC-AI-081: 공시 충격 스코어링 flat-base 카테고리 콘텐츠 인식 정밀화 설정.

    enabled=False(기본값)이면 score_disclosure_impact()의 flat-base 경로(주요사항보고/지분공시)가
    레거시 거동(Tier1/2/3 키워드 목록 + 기존 report_type 기준 base)을 완전히 유지한다.
    """

    # @MX:NOTE: [AUTO] SPEC-AI-081 — 기본값 false(레거시 완전 보존, 공유 고fan-in 함수 변경 원칙)
    # @MX:SPEC: SPEC-AI-081 REQ-AI081-004
    enabled: bool = False


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
    # SPEC-AI-066: 촉매 확신도 기반 조건부 완화 설정
    catalyst_conviction: CatalystConvictionConfig = Field(default_factory=CatalystConvictionConfig)
    # SPEC-AI-067: 장중 실시간 당일 거래량 소스 설정 (combo/breakout/PoolB 공유)
    intraday_live_volume: IntradayLiveVolumeConfig = Field(default_factory=IntradayLiveVolumeConfig)
    # SPEC-AI-069 REQ-AI069-004: z-score 상대채점 회귀 격리 설정
    relative_scoring: RelativeScoringConfig = Field(default_factory=RelativeScoringConfig)

    # @MX:NOTE: [AUTO] SPEC-AI-069 REQ-002 — 자동개선 전면 중단 스위치. 기본 false(REQ-002 확정 상태).
    # true로 재활성하려면 REQ-003(backtest 가드 + Scannable Recall)이 충족되어야 한다.
    # @MX:SPEC: SPEC-AI-069 REQ-AI069-002
    auto_improve_enabled: bool = False

    # SPEC-AI-080: 동일-당일 고확신 공시 촉매 즉시 급등 시그널 발화 설정 (기본 비활성)
    immediate_surge: ImmediateSurgeConfig = Field(default_factory=ImmediateSurgeConfig)

    # SPEC-AI-081: 공시 충격 스코어링 flat-base 카테고리 콘텐츠 인식 정밀화 설정 (기본 비활성)
    disclosure_content_aware_scoring: DisclosureContentAwareScoringConfig = Field(
        default_factory=DisclosureContentAwareScoringConfig
    )

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
    # SPEC-AI-060: 종목별 개별 원인 분석 설정
    per_stock_analysis: PerStockAnalysisConfig = Field(default_factory=PerStockAnalysisConfig)
    # 거래량 폭발 소형주 탐지기 설정
    volume_breakout: VolumeBreakoutConfig = Field(default_factory=VolumeBreakoutConfig)
    # SPEC-AI-065 REQ-3: 모멘텀 연속 탐지기 설정
    momentum_continuation: MomentumContinuationConfig = Field(
        default_factory=MomentumContinuationConfig
    )

    # SPEC-AI-042 REQ-042-008: 장전 갭업 조기 진입 임계값 (하드코딩 금지)
    # 0 <= change_rate < gap_entry_threshold → 조기 진입
    # change_rate >= gap_entry_threshold → skip (갭풀백 위임)
    # @MX:NOTE: [AUTO] SPEC-AI-042 — 갭 필터 임계값. 변경 시 surge_detection.yaml에서만 조정
    gap_entry_threshold: float = 0.05

    # SPEC-AI-065: z-score 기준선 최소 샘플 수 (cold-start 판단 기준)
    # @MX:NOTE: [AUTO] SPEC-AI-065 REQ-1 — 10일 미만이면 z-score 대신 절대값 사용
    # @MX:SPEC: SPEC-AI-065 REQ-1
    zscore_min_baseline_samples: int = 10
    # SPEC-AI-065: 스캔 유니버스 최대 크기 (Pool A+B+C+기존 합산 상한)
    # @MX:NOTE: [AUTO] SPEC-AI-065 REQ-2 — 150 초과 시 A > B > C > existing 우선순위로 잘라냄.
    # SPEC-AI-076: 이 상한 값 자체는 불변(스캔 비용 상한, SPEC-AI-065 소유 유지) — 배분
    # 메커니즘만 quota 방식(pool_b_min_slots/pool_c_min_slots)으로 슈퍼시드됨.
    # @MX:SPEC: SPEC-AI-065 REQ-2
    max_scan_universe: int = 150
    # SPEC-AI-076 REQ-AI076-007: 풀별 최소 슬롯 예약(quota floor). 절단 압력 하에서 상위
    # 우선순위 풀(특히 Pool A, 당일 DART 공시량에 의존해 통제 불가)이 하한 풀(B/C)을 0으로
    # 굶기는 것을 방지한다. sum(floors) > max_scan_universe면 비율 축소 + 경고 로그(clamp).
    # 기본값 0이면 레거시 엄격 concat-then-slice와 완전히 동일(REQ-AI076-004 백워드 호환).
    # @MX:NOTE: [AUTO] SPEC-AI-076 REQ-007 — Pool B 최소 슬롯 floor
    # @MX:SPEC: SPEC-AI-076 REQ-AI076-007
    pool_b_min_slots: int = 20
    # @MX:NOTE: [AUTO] SPEC-AI-076 REQ-007 — Pool C 최소 슬롯 floor(당일 실현급등 후행 풀,
    # 무거운 DART 공시일에 가장 굶주리기 쉬워 Pool B보다 큰 기본값)
    # @MX:SPEC: SPEC-AI-076 REQ-AI076-007
    pool_c_min_slots: int = 30
    # SPEC-AI-078 REQ-AI078-005: Pool A 후보 리스트를 종목별 MAX(impact_score) 내림차순
    # (NULL은 최후순위)으로 정렬할지 여부. False면 레거시 DB-순서(무순위) 거동으로 복귀
    # (백워드 호환 탈출구, SPEC-AI-076 pool_b_min_slots=0 패턴 계승). 기본값 True(신규 거동
    # ON) — SPEC-AI-076이 floors 기본값을 비-0으로 배포한 선례와 정합.
    # @MX:NOTE: [AUTO] SPEC-AI-078 REQ-AI078-005 — Pool A impact 정렬 토글
    # @MX:SPEC: SPEC-AI-078 REQ-AI078-005
    pool_a_rank_by_impact: bool = True

    # SPEC-AI-086 REQ-AI086-003: Pool D(뉴스 언급 기반) 최소 슬롯 예약(quota floor).
    # SPEC-AI-076 pool_b/c_min_slots quota 패턴을 확장한다. 기본값 0 = 완전 비활성
    # (build_scan_universe의 Pool D 소싱 쿼리 자체가 스킵됨 — REQ-AI086-007 백워드 호환).
    # @MX:NOTE: [AUTO] SPEC-AI-086 REQ-AI086-003 — Pool D 최소 슬롯 floor(기본 OFF)
    # @MX:SPEC: SPEC-AI-086 REQ-AI086-003
    pool_d_min_slots: int = 0
    # SPEC-AI-086 REQ-AI086-004: 장중 시간대별 동적 스캔 상한(선택, 기본 비활성).
    # 키는 시간대 라벨(surge_detector._DYNAMIC_CAP_TIME_BINS와 매칭), 값은 해당 시간대 적용
    # 상한. 빈 dict(기본값)이면 REQ-AI086-001의 단일 평탄 상한(max_scan_universe)으로 폴백한다.
    # @MX:NOTE: [AUTO] SPEC-AI-086 REQ-AI086-004 — 시간대별 동적 상한 맵(기본 비활성)
    # @MX:SPEC: SPEC-AI-086 REQ-AI086-004
    dynamic_scan_universe_caps: dict[str, int] = Field(default_factory=dict)

    # SPEC-AI-089 M1 REQ-AI089-001/003/004: 스캔 유니버스↔탐지망 간극 측정 계측 플래그.
    # 기본값 OFF — 활성화해도 순수 읽기·집계(신규 네트워크 조회/DB 쓰기 없음)이며 탐지
    # 파이프라인 출력에 영향을 주지 않는다(REQ-003 불변식, AC-089-008로 검증).
    # @MX:NOTE: [AUTO] SPEC-AI-089 REQ-AI089-001 — 측정 계측 토글(기본 비활성)
    # @MX:SPEC: SPEC-AI-089 REQ-AI089-001
    universe_gap_measurement_enabled: bool = False

    # @MX:ANCHOR: [AUTO] 앙상블 가중치 합산 검증 — 8개 탐지기 가중치 합산 반드시 1.0
    # @MX:REASON: 가중치 합산 != 1.0 이면 앙상블 스코어 범위가 0~1을 벗어나 시그널 임계값 판정이 왜곡됨
    @model_validator(mode="after")
    def validate_ensemble_weights(self) -> "SurgeDetectionConfig":
        """앙상블 가중치 합산이 1.0이어야 한다 (8개 탐지기 가중치 합산).

        SPEC-AI-065 REQ-3: momentum_continuation 추가로 8번째 탐지기 포함.
        """
        w = self.ensemble.weights
        total = (
            w.theme_cluster
            + w.volume_news_combo
            + w.disclosure_pattern
            + w.legacy_detectors
            + w.news_delayed
            + w.weekend_gap_up
            + w.volume_breakout
            + w.momentum_continuation
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
    # @MX:NOTE: [AUTO] SPEC-AI-087 REQ-003 — NULL 시총 종목 최소 보장 슬롯(floor quota).
    # 0(기본값)이면 NULL 전용 쿼리 자체를 스킵해 레거시 market_cap >= min_market_cap
    # 단일 조건 조회와 바이트 동등하다(REQ-008 백워드 호환 탈출구). >0이면 SPEC-AI-077 패턴을
    # 재사용해 날짜 로테이션 기반으로 NULL 시총 종목을 추가 편입한다. 이 경로만 후보당 신규
    # 네트워크 fetch(fetch_stock_price_history_sync)가 발생하므로 opt-in으로 비용을 상한한다.
    # @MX:SPEC: SPEC-AI-087 REQ-AI087-003
    null_cap_min_slots: int = 0


class NearLimitUpConfig(BaseModel):
    """SPEC-AI-023: 상한가 근접 종목 익일 carry-forward 설정."""

    enabled: bool = True
    # 상한가 근접 기준 최소 등락률 (%) — 15~24% 모멘텀 이월 종목 누락 방지로 25.0→15.0 완화
    near_limit_up_min_pct: float = 15.0
    # 상한가 기준 최대 등락률 (%) — 상한가 도달 시 제외
    near_limit_up_max_pct: float = 29.99
    # 시총 상위 N 종목만 평가 — NULL 시총 종목도 후보 풀에 포함되도록 500→1200 확대
    max_stocks_to_check: int = 1200
    # 하루 최대 발행 시그널 수 — None이면 무제한. 기존 10건 상한이 NULL 시총 종목을
    # 순위상 뒤로 밀어내 확인조차 못 하게 막는 병목이라 기본값을 무제한으로 완화
    max_signals_per_day: int | None = None
    # 시총 하한 필터 (억원) — REQ-AI023-001(a). NULL 시총 종목은 필터 대상에서 제외(허용)
    min_market_cap_eok: int = 300
    # @MX:NOTE: [AUTO] SPEC-AI-077 REQ-006 — NULL 시총 종목 최소 보장 슬롯(floor quota).
    # NearLimitUpConfig는 fund_manager.py에서 bare 생성되어 yaml 비구동이므로 이 필드는
    # Pydantic 기본값 전용이다 — surge_detection.yaml에 추가 금지(dead config 방지).
    # 0이면 로테이션/floor가 무효화되고 레거시 nullslast 거동으로 복귀한다(REQ-005 탈출구).
    # @MX:SPEC: SPEC-AI-077 REQ-AI077-006
    null_cap_min_slots: int = 300


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
    # @MX:NOTE: [AUTO] SPEC-AI-087 REQ-004 — NULL 시총 계열사 편입 boolean 토글. False(기본값)면
    # 기존 market_cap >= cascade_min_market_cap 단일 조건 필터와 바이트 동등하다(REQ-008).
    # True면 기존 max_cascade_per_flagship 상한 내에서 NULL 시총 계열사를 non-null 종목보다
    # 낮은 순위로 포함한다. 계열사 후보풀은 이미 접두사 매칭으로 소규모이고 상한이 걸려 있어
    # (근거: near_limit_up만큼의 굶주림 위험 없음) floor-quota가 아닌 단순 토글로 충분하다.
    # flagship(대장주) NULL 시총 배제 로직(REQ-006)은 이 필드의 영향을 받지 않는다.
    # @MX:SPEC: SPEC-AI-087 REQ-AI087-004
    cascade_include_null_market_cap: bool = False


class ThemeNewsCarryConfig(BaseModel):
    """SPEC-AI-084 그룹 A: 뉴스 기반 산업 테마 전파(키워드 바스켓 carry-forward) 설정.

    detect_theme_group_carry_forward(SPEC-AI-025, 계열/지분 그룹 전용)를 stocks.keywords
    (그룹 C가 채우는 테마 키워드 바스켓)로 재키잉한 additive 탐지기의 설정이다.
    enabled=False(기본값)이면 detect_theme_news_carry가 즉시 빈 리스트를 반환해 레거시
    파이프라인(기존 7종 탐지기 + theme_group_carry)이 완전히 보존된다(REQ-AI084-015,
    단계적 롤아웃 — SPEC-AI-079 관례 계승).
    """

    # @MX:NOTE: [AUTO] SPEC-AI-084 REQ-AI084-015 — 마스터 스위치. 기본값 false(레거시 완전 보존)
    # @MX:SPEC: SPEC-AI-084 REQ-AI084-015
    enabled: bool = False
    # 앵커 판정 최소 등락률(%) — ThemeGroupCarryConfig.anchor_surge_min_pct와 동일 기본값
    anchor_surge_min_pct: float = 5.0
    # REQ-AI084-011: 테마 활성 확인 게이트 — 복수 멤버 동반 이동 임계(최소 앵커 수)
    min_anchor_members_for_activation: int = 2
    # REQ-AI084-011: 고긴급 테마 뉴스 판정 윈도우(시간) — 앵커 1개 + 고긴급 뉴스 경로
    high_urgency_window_hours: int = 24
    # 바스켓당 최대 발행 시그널 수
    max_signals_per_basket: int = 5
    # EC-1: 이 미만 멤버 수의 바스켓은 전파 대상 없음(no-op)
    min_basket_size: int = 2


class NewsUrgencyRecalibrationConfig(BaseModel):
    """SPEC-AI-084 그룹 B: 뉴스 긴급도 재보정(co-mention 버스트 + 촉매 커버리지 확장) 설정.

    enabled=False(기본값)이면 news_crawler._classify_urgency 호출부가 recent_topic_counts를
    전혀 공급하지 않고 촉매 키워드 확장도 적용하지 않아 기존 긴급도 분류와 완전히 동일하다
    (REQ-AI084-008, 롤백=플래그 복귀로 완전 레거시).
    """

    # @MX:NOTE: [AUTO] SPEC-AI-084 REQ-AI084-008 — 마스터 스위치. 기본값 false(레거시 완전 보존)
    # @MX:SPEC: SPEC-AI-084 REQ-AI084-008
    enabled: bool = False


class DescriptionRelationMatchingConfig(BaseModel):
    """SPEC-AI-085: 기사 설명(description) 기반 종목 관계 생성 설정.

    enabled=False(기본값)이면 news_crawler의 관계 계산 루프가 기사 설명 텍스트를 전혀
    매칭하지 않아 기존 제목(classify_news)/쿼리(_resolve_query_relations) 기반 관계
    생성과 완전히 동일하다(REQ-AI085-006, 롤백=플래그 복귀로 완전 레거시).
    """

    # @MX:NOTE: [AUTO] SPEC-AI-085 REQ-AI085-006 — 마스터 스위치. 기본값 false(레거시 완전 보존)
    # @MX:SPEC: SPEC-AI-085 REQ-AI085-006
    enabled: bool = False
    # REQ-AI085-003: 기사당 설명 기반 신규 관계 생성 상한 — 시황/묶음 기사 남발 방지.
    # @MX:NOTE: [AUTO] SPEC-AI-085 REQ-AI085-003 — 값은 배포 전 보수적 기본치(실측 캘리브레이션
    # 아님, plan.md DP-1). 배포 후 관측(REQ-AI085-009) 결과에 따라 조정 대상.
    max_relations_per_article: int = 5


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
    # @MX:NOTE: [AUTO] SPEC-AI-087 REQ-005 — NULL 시총 섹터 피어 편입 boolean 토글. False(기본값)면
    # 기존 market_cap.isnot(None) 필터와 바이트 동등하다(REQ-008). True면 기존 섹터 피어 상한
    # (.limit(5)) 및 런너 선정([:2]) 내에서 NULL 시총 피어를 non-null 종목보다 낮은 순위로
    # 포함한다. 런너당 시세 조회는 [:2] 슬라이스로 이미 상한이 걸려 있어 이 토글 자체는 신규
    # 네트워크 비용을 늘리지 않는다.
    # @MX:SPEC: SPEC-AI-087 REQ-AI087-005
    runner_include_null_market_cap: bool = False


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


def _deep_merge(base: dict, override: dict) -> dict:
    """두 딕셔너리를 재귀적으로 병합한다. override 값이 우선한다."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_config_from_yaml(path: Path) -> SurgeDetectionConfig:
    """YAML 파일에서 SurgeDetectionConfig를 로드한다.

    surge_detection.auto.yaml이 존재하면 deep_merge로 오버라이드를 적용한다.
    auto.yaml은 배포 시 git reset --hard에서 보호되므로 자동개선 값이 유지된다.
    """
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    if _AUTO_CONFIG_PATH.exists():
        with open(_AUTO_CONFIG_PATH, encoding="utf-8") as f:
            auto_raw: dict[str, Any] = yaml.safe_load(f) or {}
        if auto_raw:
            raw = _deep_merge(raw, auto_raw)
            logger.debug("auto.yaml 오버라이드 적용: %s", _AUTO_CONFIG_PATH)

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
