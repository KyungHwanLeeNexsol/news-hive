---
id: SPEC-AI-028
version: 1.0.0
status: implemented
created: 2026-06-01
updated: 2026-06-01
author: MoAI
priority: High
issue_number: null
---

# SPEC-AI-028: 공시 유형별 역신호 필터링 및 실패 자동 분류

## HISTORY

- 2026-06-01 (v0.1.0): 최초 작성. 2026-06-01 운영 분석에서 `immediate_disclosure`
  탐지기 시그널 종목들이 일제히 하락한 사례(한양이엔지 -3.32%, 나노팀 -10.24%,
  삼화전자 -13.80% 등)가 확인되었다. 근본 원인은 (1) 모든 공시를 호재로 간주하는
  탐지 로직과 (2) 공시 기반 시그널 실패 시 `error_category`가 자동 분류되지 않아
  실패에서 학습하지 못하는 구조이다. 본 SPEC은 공시 유형별 역신호 사전 필터링
  (Sub-system A)과 실패 패턴 자동 분류(Sub-system B)를 정의한다.

---

## 선행 SPEC (전제 조건 / Assumptions)

본 SPEC은 다음 기존 SPEC이 구축한 인프라 위에 동작한다. 새로운 인프라를 만들지
않고 기존 자산을 재사용하는 것을 전제한다.

- **SPEC-AI-004 (공시 기반 선제적 시그널 시스템)**: `Disclosure` 모델의 공시 데이터
  (`report_name`, `report_type`, `ai_summary`), `disclosure_impact_scorer.py`의
  충격 스코어링, `FundSignal.error_category`(String 30) 필드를 도입했다. 본 SPEC은
  이 필드와 모델을 그대로 사용한다.
  - **전제**: `Disclosure` 모델에는 공시 본문 전문(`dart_document_text`)이 **존재하지
    않는다**. 공시 텍스트 분석은 `report_name`(공시 제목, String 500)과
    `ai_summary`(AI 요약, Text, nullable)만을 대상으로 한다.
  - **전제**: `_BASE_IMPACT_BY_TYPE`에 이미 `"발행공시": -10`(희석 효과)이 정의되어
    있다. 본 SPEC의 키워드 필터는 이 충격 스코어링과 **독립적인 별도 게이트**이며,
    `immediate_disclosure` 탐지기 경로(`surge_detector.detect_immediate_disclosure_signal`)에
    적용된다.
- **SPEC-AI-012 (급등 징후 탐지 시스템)**: `surge_detector.py`의 4개 탐지기, 앙상블
  스코어링, `FundSignal.surge_metadata`(Text, JSON 문자열) 필드,
  `surge_candidate_to_signal_metadata()` 변환 함수, `surge_detection.yaml` /
  `surge_settings.py` 설정 인프라를 도입했다.
  - **전제**: `immediate_disclosure` 탐지기는 `_IMMEDIATE_EVENT_PATTERNS`(키워드→점수)
    로 `Disclosure.report_name`을 매칭하여 `immediate_disclosure_score`를 부여한다.
    본 SPEC의 역신호 필터는 동일한 `report_name` 기반으로 동작한다.
  - **전제**: `surge_metadata` JSON은 `surge_candidate_to_signal_metadata()`가
    생성하며, 현재 `surge_probability_score`, `surge_basis`(탐지기 list), 탐지기별
    점수를 포함한다. 본 SPEC은 여기에 `disclosure_sentiment` 키를 추가한다.

---

## Overview

본 SPEC은 두 개의 독립적 하위 시스템을 정의한다.

- **Sub-system A — 공시 유형 사전 필터(Disclosure Type Pre-Filter)**: 공시 텍스트에
  하락 유발 키워드(유상증자, 전환사채, 손실 등)가 포함된 경우 `immediate_disclosure`
  시그널 생성을 차단하거나 confidence에 강한 페널티를 부여한다. 공시 감성
  (`disclosure_sentiment`)을 `surge_metadata`에 기록한다.
- **Sub-system B — 실패 패턴 자동 분류(Failure Auto-Classification)**: 공시 기반
  시그널이 검증 단계에서 실패(`is_correct=False`)했을 때, 공시 제목/요약 키워드로
  `error_category`를 자동 분류한다. AI 호출 없이 수급 반전(`supply_reversal`)을
  우선 판정하고, 그렇지 않으면 섹터 전이(`sector_contagion`)로 분류한다.

이 SPEC은 **무엇을(WHAT)**과 **왜(WHY)**를 정의하며, 구체적 구현 세부는 Run 단계로
이연한다.

### 문제 맥락 — 공시 감성 3분류 시나리오

| 시나리오 | 공시 유형 예시 | 키워드 매칭 | 기대 동작 | 현재 동작(버그) |
|---|---|---|---|---|
| Bullish (호재) | 자기주식소각, 단일판매·공급계약, 합병 | 호재 키워드만 | `immediate_disclosure` 시그널 정상 생성 | 정상 |
| Bearish (악재) | 유상증자, 전환사채 발행, 영업손실 | 하락 키워드 매칭 | 시그널 차단 또는 confidence × 0.3 페널티 | **무조건 호재로 간주, 매수 시그널 생성 → 하락** |
| Ambiguous (혼재) | 최대주주 변경, 기타 발행공시 | 페널티 키워드 매칭 | confidence × 0.3 페널티 적용, `neutral`로 기록 | 페널티 없이 정상 생성 |

### 2026-06-01 운영 증거 (Evidence)

`immediate_disclosure` 또는 `theme_cluster` 탐지기가 발동한 시그널 종목의 익일 등락률:

| 종목 | 코드 | 탐지기 조합 | 익일 등락 | 비고 |
|---|---|---|---|---|
| 한양이엔지 | 045100 | immediate_disclosure + theme_cluster + volume_news_combo | -3.32% | 최고 확률 0.710 |
| 나노팀 | 417010 | theme_cluster + volume_news_combo | -10.24% | |
| 삼화전자 | 011230 | theme_cluster + volume_news_combo | -13.80% | |
| 선익시스템 | 171090 | theme_cluster + immediate_disclosure | -5.57% | |
| 비에이치아이 | 083650 | theme_cluster + immediate_disclosure | -1.35% | |
| 쎄노텍 | 222420 | theme_cluster + immediate_disclosure | +10.24% | 예외(상승) |

6건 중 5건이 하락했으며, 그중 3건은 `immediate_disclosure` 탐지기를 포함했다.

---

## Root Cause (두 가지 근본 원인)

### Root Cause 1 — 모든 공시를 호재로 간주

`surge_detector.detect_immediate_disclosure_signal()`은 `_IMMEDIATE_EVENT_PATTERNS`에
정의된 **호재성 키워드**(자기주식소각, 단일판매·공급계약, 합병 등)만 인식하고,
하락을 유발하는 공시 유형은 전혀 거르지 않는다. 결과적으로 동일 종목에 호재
키워드와 악재 키워드(예: 합병 공시 + 유상증자 공시)가 동시에 존재해도 호재 점수만
부여된다.

역사적으로 주가 하락을 선행하는 공시 유형:

- 유상증자 (rights offering — 지분 희석)
- 전환사채(CB) / 신주인수권부사채(BW) 발행 (잠재적 희석)
- 최대주주 변경 (불확실성, 경영권 분쟁 신호일 수 있음)
- 손실 / 영업손실 관련 공시

### Root Cause 2 — 공시 기반 시그널 실패의 비분류

`signal_verifier.verify_signals()`는 시그널 실패 시 `_classify_error()`로 AI를 호출해
`error_category`를 채우지만, 이 경로는 (1) AI 레이트리밋에 취약하고 (2)
`surge_candidate` 시그널의 `surge_basis`에 `immediate_disclosure`가 포함된 경우에도
공시 텍스트를 보지 않고 일반 프롬프트로 분류한다. 공시 실패의 가장 흔한 원인인
**수급 반전(공시 후 희석)**이 결정론적으로 분류되지 않아, 실패 패턴 통계
(`error_distribution`)가 신뢰성을 잃는다.

---

## 설계 원칙 (Design Principles)

1. **Filter-first (사전 필터 우선)**: 악재 공시는 시그널 생성 단계에서 차단/감점하여,
   매수 후보 풀(`get_today_signals`)에 진입하기 전에 제거한다. 사후 검증이 아니라
   사전 게이트로 동작한다.
2. **No new DB table / No schema migration (신규 테이블·스키마 변경 없음)**:
   `disclosure_sentiment`는 기존 `FundSignal.surge_metadata`(Text, JSON) 안에 키로
   추가한다. 실패 분류는 기존 `FundSignal.error_category`(String 30) 필드를 재사용한다.
   Alembic 마이그레이션을 발생시키지 않는다.
3. **Backward compatible (하위 호환)**: `surge_metadata`에 `disclosure_sentiment` 키가
   없는 기존 시그널은 `neutral`로 간주한다. 기존 `error_category` 허용값
   (macro_shock, supply_reversal, earnings_miss, sector_contagion, technical_breakdown)
   집합은 변경하지 않는다. 본 SPEC은 기존 5개 값 중 2개(`supply_reversal`,
   `sector_contagion`)만 결정론적으로 채운다.
4. **Config-driven (설정 주도)**: 차단/페널티 키워드 목록은 `surge_detection.yaml`에
   정의하여 코드 변경 없이 운영 중 조정 가능하게 한다.
5. **Keyword-only analysis (키워드 분석 한정)**: 공시 본문 전문이 DB에 없으므로
   `report_name`(제목) + `ai_summary`(요약)만 키워드 매칭 대상으로 한다.

---

## EARS Requirements

### REQ-AI028-001: immediate_disclosure 시그널의 악재 키워드 사전 필터

**When** the system generates `immediate_disclosure` surge candidates in
`backend/app/services/surge_detector.py` `detect_immediate_disclosure_signal()`,
the system **shall** scan each candidate disclosure's `report_name` and
`ai_summary` for bearish disclosure keywords (e.g. "유상증자", "전환사채",
"신주인수권부사채", "배정", "희석", "손실", "적자").

**If** an exclusion-pattern keyword is detected, **then** the system **shall not**
emit an `immediate_disclosure` candidate for that disclosure (signal generation
is skipped). **If** a penalty-pattern keyword is detected (and no exclusion
pattern matches), **then** the system **shall** multiply the candidate's
`immediate_disclosure_score` by a penalty factor of `0.3` before it enters the
ensemble. The keyword lists **shall** be sourced from configuration (see
REQ-AI028-004), not hardcoded.

### REQ-AI028-002: surge_metadata에 disclosure_sentiment 필드 추가

The system **shall** add a `disclosure_sentiment` key to the JSON produced by
`surge_detector.surge_candidate_to_signal_metadata()`. Its value **shall** be one
of `"bullish"`, `"bearish"`, or `"neutral"`, determined by keyword analysis of
the originating disclosure(s):

- `"bearish"` when a penalty-pattern keyword matched (the candidate survived only
  with the 0.3 penalty),
- `"bullish"` when only positive `_IMMEDIATE_EVENT_PATTERNS` keywords matched and
  no bearish keyword was present,
- `"neutral"` when the candidate has no `immediate_disclosure` basis or no
  disclosure keyword analysis applies.

**Where** `get_today_signals()` in
`backend/app/services/surge_trading_service.py` parses `surge_metadata`, the
system **shall** optionally skip signals whose `disclosure_sentiment == "bearish"`,
controlled by a configuration flag (default: skip enabled). Signals lacking the
`disclosure_sentiment` key **shall** be treated as `"neutral"` (backward compatible,
not skipped).

### REQ-AI028-003: 공시 기반 시그널 실패의 결정론적 자동 분류

**When** `signal_verifier.verify_signals()` finalizes a signal as
`is_correct = False` **and** that signal's `surge_metadata` `surge_basis` list
contains `"immediate_disclosure"` (or the signal is otherwise linked to a
disclosure via `disclosure_id`), the system **shall** classify the failure by
reading the linked disclosure's `report_name` and `ai_summary`:

- **If** a supply-related keyword is present (e.g. "유상증자", "전환사채",
  "신주인수권부사채", "배정", "희석"), **then** the system **shall** set
  `error_category = "supply_reversal"`.
- Otherwise, the system **shall** set `error_category = "sector_contagion"` as the
  default category for disclosure-based failures.

This deterministic classification **shall** run **before** the existing AI-based
`_classify_error()` call and **shall** short-circuit it (no AI request is made for
disclosure-linked failures). For all other failed signals, the existing
`_classify_error()` AI path **shall** remain unchanged.

### REQ-AI028-004: surge_detection.yaml에 disclosure_type_filter 설정 추가

The system **shall** add a `disclosure_type_filter` section under
`surge_detection:` in `backend/app/surge_config/surge_detection.yaml`, parsed by a
new Pydantic model in `backend/app/surge_config/surge_settings.py`. The section
**shall** define at minimum:

- `exclusion_patterns`: list of `report_name`/`ai_summary` keyword substrings that
  **skip** signal generation. Default: `["유상증자", "전환사채발행", "신주인수권", "주식매수선택권"]`.
- `penalty_patterns`: list of keyword substrings that apply the confidence penalty.
  Default: `["최대주주변경", "손실", "영업손실"]`.
- `penalty_factor`: float multiplier applied to `immediate_disclosure_score` when a
  penalty pattern matches. Default: `0.3`.
- `skip_bearish_in_today_signals`: bool flag controlling REQ-AI028-002's
  `get_today_signals()` skip behavior. Default: `true`.

The configuration **shall** be adjustable without code changes. When the section
is absent from the YAML, the loader **shall** apply the documented defaults
(backward compatible).

### REQ-AI028-005: 과거 검증 시그널 error_category 백필 스크립트

The system **shall** provide a one-time backfill script at
`backend/scripts/backfill_disclosure_error_category.py`. The script **shall**
update `error_category` for historical `FundSignal` rows where **all** of the
following hold:

- `is_correct = False`, **and**
- `signal_type = 'surge_candidate'`, **and**
- `surge_metadata` `surge_basis` includes `"immediate_disclosure"`, **and**
- `error_category` is currently `NULL`.

For each matching row the script **shall** apply the same deterministic keyword
classification defined in REQ-AI028-003 (supply keywords → `supply_reversal`,
otherwise `sector_contagion`), reading the linked disclosure via `disclosure_id`
when available. The script **shall** be idempotent (re-running **shall not**
overwrite an already-populated `error_category`) and **shall** report a count of
rows updated.

---

## Implementation Scope

| 파일 | 변경 내용 | 관련 REQ |
|---|---|---|
| `backend/app/surge_config/surge_detection.yaml` | `disclosure_type_filter` 섹션 신규 추가 (exclusion_patterns, penalty_patterns, penalty_factor, skip_bearish_in_today_signals) | REQ-AI028-004 |
| `backend/app/surge_config/surge_settings.py` | `DisclosureTypeFilterConfig` Pydantic 모델 추가, `SurgeDetectionConfig`에 필드 연결 (기본값 제공) | REQ-AI028-004 |
| `backend/app/services/surge_detector.py` | `detect_immediate_disclosure_signal()`에 악재 키워드 사전 필터(차단/페널티) 추가, `SurgeCandidate`에 공시 감성 추적 정보 보강 | REQ-AI028-001 |
| `backend/app/services/surge_detector.py` | `surge_candidate_to_signal_metadata()`에 `disclosure_sentiment` 키 추가 | REQ-AI028-002 |
| `backend/app/services/surge_trading_service.py` | `get_today_signals()`에서 `disclosure_sentiment == "bearish"` 시그널 옵션 스킵 (config flag 제어, 키 부재 시 neutral) | REQ-AI028-002 |
| `backend/app/services/signal_verifier.py` | `verify_signals()` 실패 처리부에서 공시 연계 시그널 결정론적 분류 추가, AI `_classify_error()` 호출 전 short-circuit | REQ-AI028-003 |
| `backend/scripts/backfill_disclosure_error_category.py` | 신규 백필 스크립트 (멱등, 업데이트 건수 보고) | REQ-AI028-005 |
| `backend/tests/test_surge_ai028.py` | 신규 테스트 — 키워드 필터, 감성 분류, 실패 자동 분류, 백필 멱등성 | 전체 |

---

## Acceptance Criteria

| ID | 기준 | 검증 방법 |
|---|---|---|
| AC-028-01 | `report_name`에 exclusion 키워드(예: "유상증자")가 포함된 공시는 `immediate_disclosure` 후보로 생성되지 않는다 | 단위 테스트: 유상증자 공시 fixture → `detect_immediate_disclosure_signal()` 결과에 해당 종목 없음 |
| AC-028-02 | `report_name`에 penalty 키워드(예: "최대주주변경")가 포함되면 `immediate_disclosure_score`가 0.3배로 감점된다 | 단위 테스트: 원점수 0.90 → 결과 0.27 (±0.001) |
| AC-028-03 | bearish 키워드 매칭 후보의 `surge_metadata`에 `"disclosure_sentiment": "bearish"`가 기록된다 | `surge_candidate_to_signal_metadata()` 반환 JSON 검증 |
| AC-028-04 | `skip_bearish_in_today_signals=true`일 때 `get_today_signals()`가 bearish 시그널을 제외한다; `disclosure_sentiment` 키가 없는 기존 시그널은 제외되지 않는다 | 단위 테스트: bearish/neutral/키없음 3종 fixture |
| AC-028-05 | `is_correct=False` + `surge_basis`에 `immediate_disclosure` 포함 + 공시에 수급 키워드 → `error_category="supply_reversal"`, 수급 키워드 없으면 `sector_contagion` | 단위 테스트: 두 케이스 모두; AI `_classify_error()`가 호출되지 않음(mock assert_not_called) |
| AC-028-06 | 비-공시 시그널 실패는 기존 AI `_classify_error()` 경로를 그대로 사용한다 | 단위 테스트: 일반 surge 시그널 실패 시 AI 호출 발생 확인 |
| AC-028-07 | 백필 스크립트가 대상 행만 업데이트하고, 이미 `error_category`가 있는 행은 건드리지 않으며, 2회 실행 시 동일 결과(멱등) | 통합 테스트: 시드 데이터 → 1회 실행 후 카운트, 2회 실행 후 변경 0 |
| AC-028-08 | `disclosure_type_filter` 섹션이 YAML에 없어도 문서화된 기본값으로 로드되며 앙상블 가중치 검증을 깨지 않는다 | 단위 테스트: 섹션 제거된 config 로드 → 기본값 적용, `get_surge_config()` 정상 |
| AC-028-09 | 신규 컬럼/테이블/Alembic 마이그레이션이 생성되지 않는다 | `alembic check` 또는 마이그레이션 디렉토리 diff 없음 확인 |
| AC-028-10 | 전체 기존 회귀 테스트가 통과한다 (`uv run pytest tests/ -m "not slow"`) | 회귀 슈트 100% 통과 |

---

## Non-Goals (What NOT to Build)

본 SPEC의 범위에서 **명시적으로 제외**되는 항목:

- **공시 본문 전문(`dart_document_text`) 수집·저장은 포함하지 않는다.** 키워드 분석은
  기존 `report_name` + `ai_summary`만 대상으로 한다. DART 원문 다운로드/파싱 인프라는
  별도 SPEC 후보이다.
- **AI 기반 공시 감성 분석은 포함하지 않는다.** 본 SPEC은 결정론적 키워드 매칭만
  사용한다. LLM을 통한 공시 호재/악재 판단은 레이트리밋·비용·재현성 문제로 제외한다.
- **`error_category` 허용값 집합 변경은 포함하지 않는다.** 기존 5개 값을 유지하며,
  새 카테고리(예: `dilution`)를 추가하지 않는다. 공시 실패는 기존
  `supply_reversal` / `sector_contagion`에 매핑한다.
- **`theme_cluster` / `volume_news_combo` 탐지기에 대한 공시 필터 적용은 포함하지
  않는다.** 역신호 필터는 `immediate_disclosure` 경로에만 적용한다. (운영 증거의
  하락 종목 다수가 theme/combo 조합이지만, 이들은 공시 텍스트와 직접 연계되지
  않으므로 별도 분석 SPEC 후보이다.)
- **확률 임계값·앙상블 가중치 조정은 포함하지 않는다.** 본 SPEC은 키워드 게이트와
  감점만 도입하며 기존 임계값 체계를 변경하지 않는다.
- **백테스팅 또는 A/B 테스트 하네스 구축은 포함하지 않는다.** 필터 효과 측정 인프라는
  별도 후속 SPEC 후보이다.
- **`disclosure_impact_scorer.py`의 `_BASE_IMPACT_BY_TYPE` 충격 스코어링 로직 변경은
  포함하지 않는다.** 기존 공시 충격 점수 체계와 본 SPEC의 키워드 필터는 독립적으로
  동작한다.
- **스케줄러 실행 빈도·시각 변경은 포함하지 않는다.**

---

## References

### 코드 위치 (수정/신규 대상)

- `backend/app/services/surge_detector.py`
  - `detect_immediate_disclosure_signal()` (`_IMMEDIATE_EVENT_PATTERNS` 인접) — REQ-AI028-001
  - `surge_candidate_to_signal_metadata()` — REQ-AI028-002
  - `SurgeCandidate` dataclass (`immediate_disclosure_score` 필드 인접) — 감성 추적 보강
- `backend/app/services/surge_trading_service.py`
  - `get_today_signals()` / `_parse_surge_metadata()` — REQ-AI028-002
- `backend/app/services/signal_verifier.py`
  - `verify_signals()` 실패 처리부 + `_classify_error()` short-circuit — REQ-AI028-003
- `backend/app/surge_config/surge_detection.yaml` — REQ-AI028-004
- `backend/app/surge_config/surge_settings.py`
  - `DisclosureTypeFilterConfig` 신규 모델, `SurgeDetectionConfig` 연결 — REQ-AI028-004
- `backend/scripts/backfill_disclosure_error_category.py` (신규) — REQ-AI028-005

### 데이터 모델 사실 확인

- `Disclosure` (`backend/app/models/disclosure.py`): `report_name`(String 500, 공시
  제목), `report_type`(String 50, nullable), `ai_summary`(Text, nullable),
  `stock_id`(FK). **공시 본문 전문 컬럼 없음.**
- `FundSignal` (`backend/app/models/fund_signal.py`): `error_category`(String 30,
  허용값 5종), `surge_metadata`(Text, JSON 문자열), `signal_type`(String 30),
  `disclosure_id`(FK → disclosures.id), `is_correct`(Boolean nullable).

### 선행 SPEC

- SPEC-AI-004: 공시 기반 선제적 시그널 시스템 (`error_category`, `Disclosure` 충격
  스코어링 인프라)
- SPEC-AI-012: 급등 징후 탐지 시스템 (`surge_metadata`, `immediate_disclosure`
  탐지기, `surge_detection.yaml` 설정 인프라)
