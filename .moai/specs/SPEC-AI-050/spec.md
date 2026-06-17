---
id: SPEC-AI-050
version: 0.1.0
status: draft
created: 2026-06-17
updated: 2026-06-17
author: manager-spec
priority: P0
issue_number: null
---

# SPEC-AI-050: 급등예측 탐지기 커버리지 개선 — 주말 공백 및 BEAR 레짐 과도 억제 해결

## HISTORY

- 2026-06-17 (v0.1.0): 초안 작성. 2026-06-17 라이브 데이터 분석 결과 기반.
  월요일 news_window_hours=12 신호 고사, BEAR 레짐 과도 억제(12h), 자가개선
  루프의 min_score 단일 조정 한계, group_cascade 오탐, 주말 갭업 미포착의
  5개 진단 문제를 다룬다. recall=0 지속 상태에서 P0로 분류.

---

## 배경 (Why)

NewsHive 급등예측 시스템은 매일 T-1 시그널을 생성하고 T일 실제 ≥10% 급등과
대조 평가(precision/recall/F1)한 뒤 자가개선 루프(SPEC-AI-041)로 설정을
조정한다. 그러나 2026-06-17 라이브 데이터 분석에서 **구조적 커버리지 공백**으로
인한 recall=0 지속이 확인되었다.

### 진단 1: 월요일 news_window_hours=12 가 신호 생성을 고사시킴

- 현행 BEAR 레짐 설정: `regime_detector_params.BEAR.news_window_hours: 12`
  (surge_detection.yaml line 98).
- 2026-06-15(월) 신호 생성은 ~10:00 KST 실행. 12h 윈도우는 일요일 22:00
  이후 뉴스만 포착 — 주말 공백으로 뉴스가 거의 없음.
- 결과: group_cascade 탐지기만 발동, 6건 예측, recall=0.
- **2026-06-16 실제 급등 47종목(+18~30%)이 미포착됨:**
  - 해상풍력 테마: 씨에스윈드, SK오션플랜트, 씨에스베어링, 태웅 (+22~30%)
  - 건설 테마: 대우건설, 일성건설, 광진실업 (+20~30%)
  - 방위산업: LIG넥스원 (+18.6%)
  - 이 테마들의 트리거 뉴스는 금요일(6/13) — 12h 윈도우 밖이라 미탐.

### 진단 2: 자가개선이 min_score_for_signal 만 조정함

- SPEC-AI-041 자가개선기(`surge_auto_improver.py`)는 recall 기반으로
  `ensemble.weights.*` 와 `ensemble.min_score_for_signal` (±0.02/일)만 조정한다
  (analyze_and_improve Step 4, lines 318-344).
- 그러나 근본 원인은 임계값이 아니라 **탐지기 커버리지(detector COVERAGE)**.
  탐지기가 score=0 을 내는 상황에서는 min_score 를 낮춰도 신호가 생기지 않는다.

### 진단 3: 월요일은 구조적 엣지 케이스

- 주말 직후에는 news_window_hours 가 금요일 뉴스를 포함하도록 연장되어야 한다.
- 현재 요일 인식형 동적 윈도우가 없다 (`detect_volume_surge_news_combo`는
  market_regime 만 인지, 요일 미인지 — surge_detector.py:455-464).

### 진단 4: group_cascade 탐지기 오탐

- 2026-06-15 예측 6건 전부 group_cascade (삼성그룹, 대한그룹 계열).
- 그중 어느 종목도 10%+ 급등하지 않음.
- group_cascade(SPEC-AI-027)는 상관관계 있는 계열사를 선택하지만 실제 급등
  후보를 선별하지 못한다. flagship 확률이 낮을 때 단독 cascade 신호는 노이즈.

## 목표 (What)

탐지기 커버리지 공백을 해소하여 주말 직후 및 BEAR 레짐에서도 실제 급등 후보를
포착하고, 자가개선 루프가 임계값뿐 아니라 윈도우 파라미터까지 조정하며,
저확률 group_cascade 단독 신호를 억제한다. 신규 weekend_gap_up 경량 탐지기로
주말 갭업 후보를 선제 포착한다.

본 SPEC은 신규 대규모 탐지기를 만들기보다 **기존 탐지기/설정의 윈도우·게이트
파라미터를 개선**하는 것을 우선한다. 데이터 가용성 제약(아래 가정 참조)을
존중하여 구현 가능한 요구사항만 정의한다.

---

## 가정 및 데이터 제약 (Assumptions)

이 가정들은 SPEC-AI-027/030/041 구현 시 검증된 코드 사실이며, 요구사항의
구현 가능성을 결정한다.

1. **news_window_hours 흐름**: `detect_volume_surge_news_combo`는
   `config.regime_detector_params.get(market_regime)` 로 레짐 파라미터를 읽고
   `VolumeNewsComboConfig(news_window_hours=regime_params.news_window_hours)` 를
   재구성한다 (surge_detector.py:455-464). 동적 윈도우는 이 지점에서 주입 가능.
2. **YAML 자동 패치 기반 존재**: `_patch_yaml_values()`/`_replace_yaml_value()` 는
   임의 dot-path(`ensemble.min_score_for_signal`,
   `regime_detector_params.BEAR.news_window_hours`)에 대해 주석 보존 라인 패치를
   지원한다 (surge_auto_improver.py:75-144). `reload_surge_config()` 는 캐시
   무효화를 위해 존재한다 (surge_settings.py, auto_improver lines 394/416 사용).
3. **자가개선 조정 대상**: 현행 `_DETECTORS` 가중치와
   `ensemble.min_score_for_signal` 만 패치한다 (auto_improver:37, 401-417).
   `regime_detector_params.*.news_window_hours` 는 현재 미조정 대상.
4. **group_cascade 필드명**: `GroupCascadeConfig` 는 `flagship_prob_threshold`
   (대장주 확률 임계값 0.70), `decay_factor`(0.7)를 가지며 cascade 신호 강도는
   `flagship_prob * decay_factor` 로 계산된다 (surge_settings.py:374-386). 별도
   `cascade_probability` 필드는 존재하지 않으므로, 본 SPEC의 "cascade_probability"
   는 **유효 cascade 신뢰도(= flagship_prob × decay_factor)** 로 해석한다.
5. **companion 탐지 기반**: `detect_group_cascade_signals` 는 당일 기존 시그널을
   `existing_today: dict[stock_id, set[signal_type]]` 로 이미 수집한다
   (surge_detector.py:2333-2343). 동반 탐지기 존재 여부 판정에 재사용 가능.
6. **시가(open_price) 미가용**: `_fetch_price_change_sync` / `fetch_current_price_with_change_sync`
   는 `{current_price, change_rate}` 만 반환하며 시가는 없다. change_rate 는 전일
   종가 대비 %. weekend_gap_up 의 "갭업 기대"는 시가 비교가 아니라 과거 급등
   이력 + 테마 매칭으로 정의한다.
7. **detector_groups 구조**: ensemble 은 detector 를
   news(theme_cluster+volume_news_combo)/disclosure/technical 로 묶고
   `validate_ensemble_weights` 는 weight 합산 1.0 을 강제한다. 가중치 5개 필드
   (theme_cluster/volume_news_combo/disclosure_pattern/legacy_detectors/news_delayed)
   가 합 1.0 (surge_detection.yaml:58-62).
8. **요일 가드 재사용**: `is_market_hours()`/`KRX_EXTRA_HOLIDAYS`
   (surge_trading_service.py)로 직전 거래일 판정 로직을 재사용할 수 있다.

> 위 가정 중 하나라도 틀리면 알려주세요. 그렇지 않으면 이 전제로 진행합니다.

---

## 요구사항 (EARS Requirements)

### REQ-1: 요일 기반 동적 news_window_hours

**When** 급등 신호 생성이 실행될 때, **the** 시스템 **shall** 현재 요일과
직전 거래일 간격을 판정하여 동적 news_window_hours 를 적용한다.

- **When** 신호 생성 실행일이 월요일이거나 직전 거래일이 2 역일(calendar day)
  이상 이전인 경우, **the** 시스템 **shall** news_window_hours 를
  `min(72, configured_hours * 4)` 로 확장한다.
- **While** 일반 거래일(직전 거래일이 1 역일 이전)인 경우, **the** 시스템
  **shall** 설정된 레짐 news_window_hours 를 그대로 사용한다.
- **the** 시스템 **shall** 요일 판정을 탐지기 실행 직전
  (`detect_volume_surge_news_combo` 의 cfg 재구성 지점,
  surge_detector.py:455-464)에서 수행하며, 확장된 윈도우를 해당 탐지기에 주입한다.
- **the** 시스템 **shall** 확장 적용 여부와 최종 윈도우 값을 로그로 남긴다.

근거: 진단 1·3. 금요일(6/13) 뉴스가 월요일(6/15) 12h 윈도우 밖이라 47종목 미포착.

### REQ-2: BEAR 레짐 news_window_hours 완화

**the** 시스템 **shall** `regime_detector_params.BEAR.news_window_hours` 의
설정 최소값을 **24h** 로 한다.

- **the** 시스템 **shall** surge_detection.yaml 의 BEAR.news_window_hours 를
  현행 12 에서 24 로 변경한다.
- **If** 자가개선 또는 운영자가 BEAR.news_window_hours 를 24 미만으로 설정하려
  시도하면, **then the** 시스템 **shall** 24 로 클램프하고 경고 로그를 남긴다.

근거: 진단 1. 12h 는 너무 공격적이어서 당일 뉴스 및 전일 저녁 뉴스를 놓친다.
24h 가 안전 최소값.

### REQ-3: 자가개선 루프를 레짐 윈도우 파라미터로 확장

**While** 롤링 5일 recall=0 이고 모든 탐지기 기여도(detector contribution)=0
상태가 지속되는 경우, **the** 시스템 **shall** min_score_for_signal 조정에
더해 regime_detector_params 윈도우 조정을 트리거한다.

- **When** recall=0 이 3일 이상 연속 지속되면, **the** 시스템 **shall**
  활성 레짐의 `regime_detector_params.{regime}.news_window_hours` 를
  +12h 증가시킨다 (상한 48h).
- **the** 시스템 **shall** news_window_hours 증가를 dot-path
  `regime_detector_params.{regime}.news_window_hours` 로 `_patch_yaml_values`
  를 통해 적용하고 `reload_surge_config()` 로 캐시를 무효화한다.
- **the** 시스템 **shall** 윈도우 조정을 `SurgeAutoImprovementLog`
  (parameter_path = 해당 dot-path)에 기록하여 R12 자동 롤백 대상에 포함시킨다.
- **If** news_window_hours 가 이미 48h 인 경우, **then the** 시스템 **shall**
  추가 증가를 하지 않고 "윈도우 상한 도달" 로그만 남긴다.

근거: 진단 2. min_score 조정은 탐지기 score=0 일 때 무력. 윈도우 확장이
커버리지 회복의 직접 수단.

### REQ-4: group_cascade 탐지기 정밀도 가드

**If** group_cascade 신호의 유효 cascade 신뢰도(= flagship_prob × decay_factor)가
0.4 미만이면, **then the** 시스템 **shall** 해당 cascade 종목에 대해 동반 탐지기
(companion detector)의 보강을 요구한다.

- **the** 시스템 **shall** `GroupCascadeConfig` 에
  `require_companion_detector: true` 와 `companion_required_below_prob: 0.4`
  (기본값)를 추가한다.
- **When** cascade 종목의 유효 신뢰도가 `companion_required_below_prob` 미만이고
  해당 종목에 당일 다른 탐지기 시그널(`existing_today[stock_id]` 에
  group_cascade 외 signal_type)이 없는 경우, **the** 시스템 **shall** 해당
  cascade surge_candidate 신호를 생성하지 않는다.
- **While** cascade 종목의 유효 신뢰도가 `companion_required_below_prob` 이상인
  경우, **the** 시스템 **shall** 기존 동작대로 단독 cascade 신호를 허용한다.
- **the** 시스템 **shall** companion 가드로 차단된 cascade 후보 수를 로그로 남긴다.

근거: 진단 4. 2026-06-15 group_cascade 단독 6건 전부 급등 실패. 저확률 단독
cascade 는 노이즈.

### REQ-5: weekend_gap_up 신규 경량 탐지기

**Where** 주말 갭업 후보 탐지 기능이 활성화된 경우, **the** 시스템 **shall**
최근 급등 이력과 활성 테마 매칭에 기반해 주말 직후 갭업 후보를 탐지한다.

- **the** 시스템 **shall** 신규 `detect_weekend_gap_up_signals()` 탐지기를
  추가한다. 신호 조건은:
  (a) 종목이 최근 10 거래일 내 `surge_actual_outcome` 에서
      `was_surge=True` 로 기록되었고,
  (b) 종목 섹터가 최근 뉴스의 활성 테마(active themes)와 매칭됨.
- **While** 신호 생성 실행일이 월요일이거나 직전 거래일이 2 역일 이상 이전인
  경우에만, **the** 시스템 **shall** 이 탐지기를 활성화한다 (REQ-1 동일 가드).
- **the** 시스템 **shall** weekend_gap_up 에 앙상블 가중치 0.10 을 부여하되,
  이를 legacy_detectors 할당분에서 가져온다 (legacy_detectors 0.10 → 0.00,
  weekend_gap_up 0.10 신설; 합 1.0 유지). `EnsembleWeightsConfig` 와
  `validate_ensemble_weights` 합산 라인을 함께 수정한다.
- **If** legacy_detectors 가중치를 0 으로 만드는 것이 운영상 부적합하면,
  **then the** 시스템 **shall** 대안으로 legacy_detectors 0.10 → 0.05,
  weekend_gap_up 0.05 의 분할 배분을 제안하고 운영자 승인을 받는다 (구현
  시점에 설계 결정 — plan.md 참조).
- **the** 시스템 **shall** weekend_gap_up 신호를 signal_type="surge_candidate"
  로 저장하되 surge_metadata.surge_basis 에 "weekend_gap_up" 을 포함시킨다.

근거: 진단 1·3. 47종목 미포착분 다수가 최근 급등 이력 + 테마 종목. 시가
미가용(가정 6) 때문에 "갭업"은 이력+테마 매칭으로 근사한다.

---

## Exclusions (What NOT to Build)

- **시가(open_price) 기반 실제 갭 계산 미구현**: `fetch_current_price_with_change_sync`
  가 시가를 반환하지 않으므로(가정 6), weekend_gap_up 은 실제 시가-종가 갭이
  아니라 급등 이력+테마 근사로만 동작한다. 진짜 갭 계산이 필요하면 별도 SPEC.
- **장중(intraday) 실시간 재탐지 미포함**: 본 SPEC은 신호 생성 시점의 윈도우/
  게이트 개선에 한정한다. 장중 실시간 재스캔은 SPEC-AI-035/038 범위.
- **새 탐지기 다수 추가 금지**: weekend_gap_up 1개만 신규. 그 외 진단된 미포착
  테마(해상풍력 등)를 위한 개별 테마 탐지기는 추가하지 않는다. theme_cluster
  키워드/섹터맵 확장은 SPEC-AI-037 영역으로 위임.
- **앙상블 컨센서스 배율/적응형 임계값 공식 변경 금지**: REQ-4/5 는 가중치
  재배분만 건드리며 consensus_multiplier, adaptive_threshold 공식은 무변경.
- **min_score 조정 로직 자체 변경 금지**: REQ-3 은 윈도우 조정을 추가할 뿐,
  기존 min_score ±0.02 조정 규칙(SPEC-AI-041)은 그대로 유지한다.
- **group_cascade 의 flagship 판정 로직 변경 금지**: REQ-4 는 cascade 종목
  발행 단계에만 companion 가드를 추가하며 flagship_prob_threshold/
  flagship_change_pct 등 대장주 판정은 무변경.
- **백엔드 numpy/scipy/sklearn 도입 금지**: 모든 계산은 순수 Python.

---

## 영향 범위 (Affected Components)

| 구분 | 파일 | 변경 성격 |
|------|------|-----------|
| 설정 | `backend/app/surge_config/surge_detection.yaml` | BEAR.news_window_hours 12→24, ensemble.weights 재배분, group_cascade.require_companion_detector 추가 |
| 설정 모델 | `backend/app/surge_config/surge_settings.py` | EnsembleWeightsConfig(weekend_gap_up 필드), GroupCascadeConfig(companion 필드), validate_ensemble_weights 수정 |
| 탐지기 | `backend/app/services/surge_detector.py` | 요일 동적 윈도우(REQ-1), group_cascade companion 가드(REQ-4), detect_weekend_gap_up_signals 신규(REQ-5) |
| 자가개선 | `backend/app/services/surge_auto_improver.py` | 레짐 윈도우 조정(REQ-3), _DETECTORS 목록 확장 |
| 오케스트레이션 | `backend/app/services/fund_manager.py` | weekend_gap_up 호출 배선, group_cascade companion 가드 호출부 |

## 관련 SPEC (Dependencies)

- **SPEC-AI-027** (group_cascade): REQ-4 가 이 탐지기에 companion 가드를 추가.
- **SPEC-AI-041** (자가개선 루프): REQ-3 가 이 루프를 윈도우 파라미터로 확장.
  본 SPEC은 AI-041 의 `_patch_yaml_values`/`reload_surge_config`/R12 롤백 인프라에
  의존.
- **SPEC-AI-022** (커버리지 확장/volume_anomaly): weekend_gap_up 는 동일한
  `_gather_surge_candidates` 후처리 파이프라인(fund_manager.py:3804+)에 배선.
- **SPEC-AI-018/038** (레짐 임계값): REQ-2 가 BEAR 윈도우를 조정하나 레짐 임계값
  (regime_thresholds)은 무변경 — 도메인 분리.

> 참고: 기존 AI SPEC들은 모두 저장소 루트 `.moai/specs/SPEC-AI-0XX/` 에 존재한다.
> 본 SPEC은 요청에 따라 `backend/.moai/specs/SPEC-AI-050/` 에 작성되었다. 향후
> 일관성을 위해 위치 통일 여부를 검토할 것.
