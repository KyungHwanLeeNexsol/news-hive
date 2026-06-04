---
id: SPEC-AI-037
version: 1.0.0
status: completed
created: 2026-06-04
updated: 2026-06-04
author: MoAI
priority: High
issue_number: null
title: 급등 탐지 테마 커버리지 확장 및 비테마 팩터 강화
---

# SPEC-AI-037 — 급등 탐지 테마 커버리지 확장 및 비테마 팩터 강화

## HISTORY

- 2026-06-04 (v0.1.0): 최초 초안 작성. 코드베이스 조사(research.md) 기반 EARS 요구사항 정의. SPEC-AI-029/030/036 의존 명시.

---

## 1. Environment (배경)

현재 급등 탐지 시스템은 13개 하드코딩 테마 안에 들어오는 종목만 효과적으로 잡고, 그 밖의 한국 시장 급등 패턴(게임/엔터/조선/해운/건설/음식료 등)을 놓치고 있다. research.md 조사로 확인된 근거:

1. **테마 커버리지 공백**: `surge_detection.yaml` `theme_cluster.keywords`에 13개만 존재(반도체/배터리/수소/전기차/AI/로봇/방위산업/바이오/원전/항공/5G/보안칩/K뷰티). 한국 시장의 주요 급등 섹터 다수가 미포함.

2. **비테마 차단 게이트**: `combo_zero_theme_floor: 0.7`(SPEC-AI-029)는 신호 생성이 아니라 **매수 실행 단계** 게이트(`is_combo_theme_gate_passed`, `surge_threshold_service.py:238~272`, 호출부 `surge_trading_service.py:692~707`)에서 동작한다. `combo_score == 0.0`이고 `theme_cluster_score < 0.7`인 종목은 disclosure/legacy 신호가 아무리 강해도 매수에서 제외된다. 순수 비테마 종목(theme=0)은 이 게이트를 통과할 수 없다.

3. **섹터-테마 매핑 정합성**: 테마-섹터 매핑은 detector가 `Sector.name.in_(...)`로 조회하므로 `seed/sectors.py` `_SNAPSHOT` 정본 이름과 정확히 일치해야 한다. 정본에 없는 이름(예: `음식료품`, `운송장비`, `미디어`)을 쓰면 0건 매칭되어 신규 테마가 무력화된다.

## 2. Assumptions (가정)

- `theme_cluster.keywords`(list[str])와 `sector_theme_map`(dict[str, list[str]])은 `surge_detector.py`에서 동적으로 순회되므로, 항목 추가는 **코드 변경 없이 YAML만으로** 가능하다(research.md §3, §10).
- `combo_zero_theme_floor`, `min_market_cap_krw`는 Pydantic 설정 필드이므로 단순 값 변경은 YAML-only로 가능하다(research.md §6, §7).
- KRX 섹터명 정본은 `backend/app/seed/sectors.py`의 `_SNAPSHOT`(67개)이며 DB `sectors.name`의 단일 출처다.
- 앙상블 4-detector 가중치 합은 `validate_ensemble_weights`가 1.0(±0.001)로 강제한다. 본 SPEC은 앙상블 가중치를 변경하지 않는다.
- SPEC-AI-029(적응형 임계값), SPEC-AI-030(combo chase guard), SPEC-AI-036(품질 floor)이 이미 적용/예정 상태이며 본 SPEC과 동일 파일을 공유한다.

## 3. Requirements (EARS format)

### REQ-037-001: 테마 키워드 및 섹터 매핑 확장 (Ubiquitous)

The system **shall** `theme_cluster.keywords`와 `sector_theme_map`에 다음 신규 테마를 포함한다: 게임, 엔터, 조선, 해운물류, 건설부동산, 음식료, 화학소재. 각 신규 테마의 매핑 섹터는 `seed/sectors.py` `_SNAPSHOT` 정본에 존재하는 이름만 사용한다.

권장 매핑(정본 검증 완료, research.md §2):
- 게임 → `게임엔터테인먼트`, `소프트웨어`, `IT서비스`
- 엔터 → `방송과엔터테인먼트`, `양방향미디어와서비스`, `광고`, `섬유,의류,신발,호화품`
- 조선 → `조선`, `기계`
- 해운물류 → `해운사`, `항공화물운송과물류`, `운송인프라`, `도로와철도운송`
- 건설부동산 → `건설`, `부동산`, `건축자재`, `건축제품`
- 음식료 → `식품`, `음료`, `식품과기본식료품소매`
- 화학소재 → `화학`, `철강`, `비철금속`, `포장재`

### REQ-037-002: combo_zero_theme_floor 완화 (Event-Driven + State-Driven)

**When** `combo_score == 0.0`이고 매수 게이트(`is_combo_theme_gate_passed`)가 평가될 때, the system **shall** `theme_cluster_score`를 완화된 floor 기준으로 비교한다. 기본 floor를 0.7에서 0.55~0.60 범위로 낮춘다.

**While** `volume_z_score >= 3.0`인 과열 종목인 동안, the system **shall** 완화된 floor를 적용하지 않고 기존 0.7 기준을 유지하여 과열 추격을 억제한다(조건부 적용).

본 요구사항은 SPEC-AI-029의 적응형 임계값 산출 로직(`compute_adaptive_threshold`)을 변경하지 않는다 — 변경 대상은 `is_combo_theme_gate_passed`의 floor 비교뿐이다.

### REQ-037-003: 소형주 시총 필터 조정 (Optional)

**Where** 소형주 급등을 포착할 필요가 있는 경우, the system **shall** 다음 중 하나를 적용한다:
- (a) `min_market_cap_krw`를 1000억(100000000000)에서 500억(50000000000)으로 낮추고, 위험 보정 confidence floor를 함께 적용한다, **또는**
- (b) 1000억 기준은 유지하되 `immediate_disclosure_score >= 0.80` 종목에 한해 시총 필터를 우회한다.

운영자는 (a)/(b) 중 하나를 선택한다. 본 SPEC은 두 옵션을 모두 명세하되, 구현은 한 가지를 채택한다.

### REQ-037-004: 테마-섹터 매핑 품질 검증 (Ubiquitous)

The system **shall** 모든 테마-섹터 매핑 값(`sector_theme_map`의 전체 섹터명)이 `seed/sectors.py` `_SNAPSHOT` 정본에 존재하는 이름과 정확히 일치하도록 보장한다. 정본에 없는 이름(`음식료품`, `운송장비`, `미디어` 등)은 사용하지 않는다.

### REQ-037-005: 비테마 신호 fast path (Event-Driven)

**When** 종목이 어떤 테마와도 매칭되지 않으나(`theme_cluster_score == 0.0`) 다음 조건 중 하나를 만족할 때, the system **shall** `combo_zero_theme_floor` 페널티 없이 매수 게이트를 통과시킨다:
- `disclosure_pattern_score >= 0.70` (강한 과거 급등 공시 패턴), **또는**
- `volume_news_combo_score >= 0.80` **그리고** 과열 상태가 아닐 때(combo chase guard 미발동).

비테마 fast path는 자체 bypass 임계값을 가지며, 게이트 함수에 명시적 분기로 추가된다.

### REQ-037-006: 회귀 안전성 (Unwanted Behavior)

**If** 본 SPEC의 변경이 기존 게이트 동작을 깨뜨릴 위험이 있으면, **then** the system **shall** 다음을 보장한다:
- 가능한 모든 변경은 YAML 전용으로 처리하고(REQ-037-001/002a/003a/004), 코드 변경은 최소화한다.
- 코드 변경이 필요한 부분(REQ-037-002b/003b/005)은 모든 신규 로직을 예외 격리(try/except, 실패 시 기존 동작 폴백)한다.
- SPEC-AI-029 적응형 임계값, SPEC-AI-030 combo chase guard, SPEC-AI-036 품질 floor 게이트는 변경 없이 계속 동작한다.

The system **shall not** 앙상블 4-detector 가중치 합(1.0)을 변경하거나, `compute_adaptive_threshold`의 산출 공식을 변경한다.

## 4. Specifications (측정 기준)

- **SP-001**: 확장 후 `theme_cluster.keywords` 개수 >= 20 (기존 13 + 신규 7 이상).
- **SP-002**: `sector_theme_map`의 모든 섹터명이 `_SNAPSHOT` 정본에 100% 존재(누락 0건).
- **SP-003**: `combo_zero_theme_floor` 값이 0.55~0.60 범위로 설정됨.
- **SP-004**: combo=0 & 0.55 <= theme < 0.7 종목이 비과열 상태에서 매수 게이트를 통과함(완화 전에는 차단되던 케이스).
- **SP-005**: theme=0 & disclosure_pattern_score >= 0.70 종목이 fast path로 매수 게이트를 통과함.
- **SP-006**: 기존 SPEC-AI-029/030/036 단위 테스트 전부 통과(회귀 0건).
- **SP-007**: 코드 변경분의 신규 분기는 예외 발생 시 기존 동작으로 폴백(예외 전파 0건).

## 5. Exclusions (What NOT to Build)

- **앙상블 가중치 재조정 금지**: theme_cluster/volume_news_combo/disclosure_pattern/legacy_detectors 가중치는 변경하지 않는다(가중치 합 1.0 유지). 별도 SPEC 영역.
- **신규 detector 추가 금지**: 새로운 탐지기를 추가하지 않는다. 기존 4개 detector + 보조 detector만 사용.
- **factor_scoring.py 변경 금지**: composite_score(LLM 경로 0~100 스케일)는 본 SPEC 범위 밖이다(SPEC-AI-036 소관).
- **`compute_adaptive_threshold` 공식 변경 금지**: 승률/레짐 배율 산출 로직은 SPEC-AI-029 소관으로 변경하지 않는다.
- **시가(open_price)/분봉 기반 신규 데이터 경로 추가 금지**: detector path는 `change_rate`(전일 종가 대비)만 사용 가능하므로 시가 기반 요구사항은 명세하지 않는다(research.md 데이터 제약).
- **테마 자동 생성/LLM 테마 추출 금지**: 테마 키워드는 수동 정의(YAML)로 유지한다. 동적 테마 발견은 향후 별도 SPEC.
- **프론트엔드/대시보드 변경 금지**: 본 SPEC은 백엔드 탐지/게이트 로직에 한정한다.

## 6. Dependencies

| SPEC | 관계 | 영향 |
|------|------|------|
| SPEC-AI-029 | Prerequisite | `combo_zero_theme_floor`, 적응형 임계값, `is_combo_theme_gate_passed` 도입. 본 SPEC이 floor를 완화하나 산출 공식은 무변경. |
| SPEC-AI-030 | Coexist | combo chase guard(과열/신선도/분산/단독차단 게이트). REQ-037-005 비테마 fast path는 chase guard 미발동을 전제로 함. |
| SPEC-AI-036 | Coexist | 동일 매수 게이트 영역에 품질 floor 추가(draft). 작업 시 충돌 확인 필요. floor는 더 엄격한 쪽이 적용되도록 유지. |
| SPEC-AI-012 | Base | 원본 4-detector 앙상블 시스템, `ThemeClusterConfig`. |

## 7. Traceability (REQ → AC → File)

| REQ | Acceptance Criteria | 대상 파일 | 구현 방식 |
|-----|---------------------|-----------|-----------|
| REQ-037-001 | AC-037-001 | `surge_detection.yaml` (keywords, sector_theme_map) | YAML-only |
| REQ-037-002 | AC-037-002 | `surge_detection.yaml` (combo_zero_theme_floor), `surge_threshold_service.py` (is_combo_theme_gate_passed) | YAML + 코드 |
| REQ-037-003 | AC-037-003 | `surge_detection.yaml` (min_market_cap_krw), `surge_detector.py` (시총 쿼리, 옵션 b) | YAML + 코드(선택) |
| REQ-037-004 | AC-037-004 | `surge_detection.yaml` (sector_theme_map), `seed/sectors.py` (정본 대조) | YAML-only |
| REQ-037-005 | AC-037-005 | `surge_threshold_service.py` (게이트 fast path 분기) | 코드 |
| REQ-037-006 | AC-037-006 | 위 전체 + 기존 테스트 스위트 | 검증/테스트 |
