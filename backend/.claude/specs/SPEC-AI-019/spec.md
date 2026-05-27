---
id: SPEC-AI-019
version: 0.1.0
status: draft
created: 2026-05-27
updated: 2026-05-27
author: Nexsol
priority: high
issue_number: null
---

# SPEC-AI-019: 급등 시그널 밸류에이션 필터 적용 범위 확장 (모든 생성 경로 커버)

## HISTORY

- 2026-05-27 (v0.1.0): 최초 작성. SPEC-AI-018 Phase 3 (밸류에이션 부적격 필터)이
  `_gather_leading_candidates()`에만 적용되어 15:20 KST 독립 잡 경로
  (`run_surge_signal_generation` → `_gather_surge_candidates`)에서는 우회되는 결함을
  교정한다. SPEC-AI-013 (15:20 독립 잡 분리)과 SPEC-AI-018 (Phase 3 도입)의 상호 작용
  공백을 메꾸는 후속 SPEC이다.

---

## 선행 SPEC

- **SPEC-AI-018**: 급등예측 신호 품질 개선 (Phase 3 밸류에이션 필터 도입). 본 SPEC은
  REQ-AI018-006 ~ REQ-AI018-008의 적용 범위를 확장한다.
- **SPEC-AI-013**: 급등 시그널 생성을 전일 15:20 KST 독립 잡으로 분리. 본 SPEC은
  해당 독립 잡 경로(Path B)에서 누락된 필터링을 복구한다.

---

## Overview

본 SPEC은 SPEC-AI-018에서 도입한 밸류에이션 부적격 필터(PER > 500 또는 PBR > 30
종목 제외)가 모든 급등 시그널 생성 경로에 일관되게 적용되도록 단일 지점으로
이전한다. 현재 필터는 `fund_manager.py` 의 `_gather_leading_candidates()` 함수에만
존재하므로, 같은 파일의 `run_surge_signal_generation` 잡이 호출하는
`_gather_surge_candidates(..., leading_candidates=[])` 경로에서는 우회된다.

이 SPEC은 **무엇을(WHAT)** 과 **왜(WHY)** 를 정의한다. 구체적인 구현 세부는
Run 단계로 이연한다.

---

## Problem Statement

급등 시그널 생성은 현재 두 개의 실행 경로로 운영된다.

- **Path A (08:30 KST 데일리 브리핑 잡)**: `generate_daily_briefing()` →
  `_gather_leading_candidates()` 호출 + `_gather_surge_candidates(...,
  leading_candidates=<populated>)` 호출. Phase 3 필터 적용됨 (정상).
- **Path B (15:20 KST 독립 잡)**: `run_surge_signal_generation()`
  (`fund_manager.py:2859`) → `_gather_surge_candidates(db, recent_news,
  leading_candidates=[])` 만 호출. `_gather_leading_candidates()` 미호출. Phase 3
  필터 미적용 (결함).

SPEC-AI-018 REQ-AI018-007 은 필터 코드를 `_gather_leading_candidates()`
(`fund_manager.py:1711`) 함수 내부에 배치했다. 그러나 Path B 는 해당 함수를
실행하지 않으므로 필터가 우회된다. 결과적으로 매 영업일 15:20 잡이 생성하는
시그널에는 PER>500 또는 PBR>30 종목이 포함될 수 있고, 다음 날 09:00 KST 의
`surge_execute_buys` 가 이 시그널을 소비하여 모의 매수를 실행한다.

또한 PER/PBR 데이터는 `stocks` 테이블에 저장되어 있지 않다. `market_cap` 컬럼만
존재하며, 두 지표는 `_gather_leading_candidates()` 내부에서 외부 API 로부터 동적
조회되어 후보 dict 의 `"per"` / `"pbr"` 키에 주입된다. 따라서 필터 코드를 단순히
`_gather_surge_candidates()` 로 복사 이동하면 모든 후보의 per/pbr 이 None 이 되어,
REQ-AI018-008 ("None 은 통과") 규칙에 의해 필터가 사실상 비활성화된다.

본 SPEC 은 데이터 수집 책임 자체를 탐지기 단계로 옮겨, 모든 생성 경로가 동일한
밸류에이션 데이터를 가지고 동일한 필터를 통과하도록 설계한다.

---

## Evidence (운영 데이터)

오늘(2026-05-27 KST, 수요일) 운영 데이터베이스의 `fund_signals` 테이블에서
`signal_type='surge_candidate'` 시그널 96 건이 생성되었으며, `surge_metadata` 의
`legacy_score` 가 모두 0.0 으로 확인되었다. `legacy_score` 는
`_gather_leading_candidates()` 가 산출한 `leading_signals` 카운트에서 파생되며
(`surge_detector.py:931-941`), 모든 시그널의 `legacy_score=0` 은 해당 함수가 호출
되지 않은 Path B(`leading_candidates=[]`) 경로가 모든 시그널을 생성했음을 입증한다.

신뢰도 상위 5 종목 (모두 오늘 KST 18:08 / 18:31 생성, 15:20 잡의 약 3시간 처리
지연 추정):

| code | name | theme | combo | imm_disc | legacy | conf |
|---|---|---|---|---|---|---|
| 045100 | 한양이엔지 | 0.500 | 0.6919 | 0.82 | 0 | 0.710 |
| 027580 | 상보 | 0.9636 | 0.700 | 0 | 0 | 0.515 |
| 018260 | 삼성SDS | 0.960 | 0.6942 | 0 | 0 | 0.512 |
| 011070 | LG이노텍 | 0.880 | 0.6835 | 0 | 0 | 0.486 |
| 005690 | 파미셀 | 0.7448 | 0 | 0.82 | 0 | 0.484 |

Phase 1 가중치(0.28 / 0.35 / 0.20 / 0.17) 및 Phase 4 그룹 컨센서스 배율
(1.0 / 1.30 / 1.55) 은 정상 적용 확인 (모든 conf 가 `weighted_sum × multiplier` 와
소수점 4자리까지 일치). Phase 2 (`_recent_surge_penalty`) 도 코드 별 적용 확인
(`surge_detector.py:941-960` 에 명시적 패치 존재). 오직 Phase 3 만 누락 상태이다.

---

## Goal

모든 급등 시그널 생성 경로 (Path A, Path B, 향후 추가될 수동 트리거 및 테스트)
에서 SPEC-AI-018 REQ-AI018-006 ~ REQ-AI018-008 의 행위 보장이 성립하도록 한다.
이를 위해 PER/PBR 수집 책임을 탐지기 단계로 이전하고, 부적격 필터를
`surge_detector` 의 단일 지점에 배치하여 중복을 제거한다.

---

## Approach Summary

선택된 접근(Option A — 탐지기 단계에서 per/pbr 수집 + `surge_detector` 에서 필터):

1. `SurgeCandidate` 모델에 `per`, `pbr` 필드를 추가한다.
2. 3개 탐지기가 기존 시장 데이터 조회 경로에 piggy-back 하여 per/pbr 를 함께
   수집한다 (추가 API 호출 없음).
3. `surge_detector.detect_surge_candidates()` 의 앙상블 스코어 계산 전 단계에
   부적격 필터를 단일 지점으로 배치한다.
4. `fund_manager.py:1700-1718` 의 중복 필터 코드는 제거하고 단일 source of truth
   를 `surge_detector` 에 둔다.

---

## EARS Requirements

### REQ-AI019-001: SurgeCandidate 모델 확장

The system **shall** add `per: float | None = None` and `pbr: float | None = None`
fields to the `SurgeCandidate` dataclass in `backend/app/services/surge_detector.py`,
adjacent to the existing `price_5d_trend` field introduced by SPEC-AI-018
REQ-AI018-005.

### REQ-AI019-002: 탐지기 단계에서 밸류에이션 데이터 수집

**When** any of the three surge detectors (`detect_theme_cluster_candidates`,
`detect_volume_news_combo_candidates`, `detect_disclosure_pattern_candidates`)
fetches stock market data for candidate construction, the detector **shall**
populate the `per` and `pbr` fields on the resulting `SurgeCandidate`.
The detector **shall not** issue additional standalone API calls solely for
per/pbr; it **shall** piggy-back on the existing market data retrieval path
(equivalent to the SPEC-AI-018 REQ-005 cached price-history pattern).

### REQ-AI019-003: 단일 지점 밸류에이션 필터 배치

The function `surge_detector.detect_surge_candidates()` **shall** apply the
`valuation_disqualifiers` filter at a single location, before the ensemble
score computation and qualification loop. The filter configuration **shall** be
loaded from `app.surge_config.surge_settings.ValuationDisqualifiersConfig`
using the same accessor pattern already used for ensemble weights.

### REQ-AI019-004: 부적격 기준

**If** a `SurgeCandidate` has `per > config.valuation_disqualifiers.max_per`
(default 500.0) **or** `pbr > config.valuation_disqualifiers.max_pbr`
(default 30.0), **then** the system **shall** exclude that candidate from the
qualification loop and **shall not** emit a `surge_candidate` signal for it.

### REQ-AI019-005: 결측치 통과 규칙 (호환성)

**If** a candidate's `per` is `None` **or** `0` **or** the `pbr` is `None`
**or** `0`, **then** the system **shall not** treat the candidate as
disqualified on valuation grounds. This preserves SPEC-AI-018 REQ-AI018-008
("None 은 통과") behavior and respects
`ValuationDisqualifiersConfig.skip_if_missing=true`.

### REQ-AI019-006: 중복 필터 제거 (Single Source of Truth)

The duplicated valuation filter logic currently located at
`backend/app/services/fund_manager.py:1700-1718` (inside
`_gather_leading_candidates()`) **shall** be removed. After REQ-AI019-003 takes
effect, the only authoritative valuation filter **shall** reside in
`surge_detector.detect_surge_candidates()`.

### REQ-AI019-007: Path A / Path B 행위 동등성

The system **shall** guarantee that for an identical set of inputs, the
`surge_candidate` signal set produced by Path A
(`generate_daily_briefing` → `_gather_leading_candidates` + `_gather_surge_candidates`)
and Path B (`run_surge_signal_generation` → `_gather_surge_candidates` with
`leading_candidates=[]`) **shall** apply the same per/pbr exclusion criteria.

### REQ-AI019-008: 회귀 방지

All existing SPEC-AI-018 acceptance tests (`backend/tests/test_surge_ai018.py`)
and the full pre-existing test suite (currently 1147 tests) **shall** continue
to pass after this SPEC is implemented. No existing public behavior other than
the bug fix described in this SPEC **shall** change.

### REQ-AI019-009: 신규 단위 테스트 추가

The system **shall** include new unit tests at
`backend/tests/test_surge_ai019_path_b.py` (or equivalent path) that verify:
(a) **When** a candidate has `per > 500` and Path B is invoked
(`detect_surge_candidates` is called directly with no leading candidates),
**then** the candidate **shall** be excluded;
(b) **When** a candidate has `pbr > 30` under the same conditions,
**then** the candidate **shall** be excluded;
(c) **When** a candidate has `per is None`, **then** the candidate **shall**
pass the valuation filter;
(d) **When** a candidate has both `per <= 500` and `pbr <= 30`, **then** the
candidate **shall** pass the valuation filter.

### REQ-AI019-010: MX 태그 적용

**Where** the modified `detect_surge_candidates()` function contains the new
valuation filter block, the system **shall** annotate the block with an
`@MX:ANCHOR` tag referencing this SPEC ID. The `SurgeCandidate` per/pbr fields
**shall** be annotated with `@MX:NOTE`. The removed `fund_manager.py:1700-1718`
filter block **shall** be marked with `@MX:LEGACY` in the commit history or
preserved deletion note.

---

## Exclusions (What NOT to Build)

- 본 SPEC 은 PER/PBR 데이터를 `stocks` 테이블에 영구 저장하는 스키마 변경을
  포함하지 않는다. 데이터는 기존과 동일하게 외부 API 에서 동적 조회한다.
- 본 SPEC 은 `valuation_disqualifiers` 임계값(`max_per=500`, `max_pbr=30`)을
  변경하지 않는다. SPEC-AI-018 의 기본값을 그대로 유지한다.
- 본 SPEC 은 `_recent_surge_penalty`(Phase 2) 또는 Phase 4 그룹 컨센서스 배율
  로직을 수정하지 않는다.
- 본 SPEC 은 `run_surge_signal_generation` 의 스케줄 시각(15:20 KST) 또는
  실행 빈도를 변경하지 않는다.
- 본 SPEC 은 새로운 외부 API 통합이나 다른 valuation 지표(EV/EBITDA, ROE 등)
  도입을 포함하지 않는다.

---

## Rejected Alternatives

### Option B: `run_surge_signal_generation` 내부에서 별도 PER/PBR 일괄 조회 후 후처리 필터

후보 셋이 확정된 다음, Path B 진입점에서 외부 API 로 일괄 조회하여 후처리 필터를
적용하는 방식. 거부 이유:
- 두 경로에 동일 책임의 코드가 분기되어 유지 보수 부담 증가
- 운영 데이터 기준 96 종목에 대해 추가 API 호출 발생 (rate-limit / 비용 이슈)
- 향후 새 경로가 생길 때마다 동일 패턴 반복 필요

### Option C: `run_surge_signal_generation` 에서 `_gather_leading_candidates` 도 호출

Path B 가 Path A 와 동일한 사전 단계를 수행하도록 만드는 방식. 거부 이유:
- SPEC-AI-013 가 명시적으로 분리한 "경량 독립 잡" 의도 위배 (전 시장 풀스캔이
  하루 두 번 실행됨)
- API 호출량 및 처리 시간이 2배로 증가
- 두 잡의 책임 경계가 흐려져 향후 변경 영향도 분석이 어려워짐

---

## Impact

- **운영**: 매 영업일 15:20 KST 잡이 생성하는 시그널 (현재 96/day 기준) 에서
  PER>500 또는 PBR>30 종목이 자동 제외된다.
- **모의 매매 안전성**: 다음 영업일 09:00 KST 의 `surge_execute_buys`
  (`scheduler.py:1378-1383` 등록 잡) 가 소비할 시그널의 품질이 향상된다.
  현재 극단 밸류에이션 종목의 자동 매수 가능성을 제거한다.
- **SPEC 정합성**: SPEC-AI-018 REQ-AI018-007 의 본래 의도가 모든 경로에서
  성립하도록 보장한다.
- **확장성**: 향후 다른 시그널 생성 경로가 추가되어도 동일한 필터가 자동 적용
  된다.

---

## Rollout Plan

1. 단일 PR 로 코드 변경 + 신규 테스트 + 기존 회귀 테스트 통과 + 문서 sync 를
   포함한다.
2. 운영 배포 후 첫 영업일(다음 평일) 15:20 KST 잡 실행 결과를 모니터링한다.
3. 생성된 `fund_signals` 의 `signal_type='surge_candidate'` 레코드에 대해
   각 종목 코드의 운영 PER/PBR 을 별도 쿼리로 확인하여 부적격 종목이
   제외되었는지 사후 검증한다.
4. 회귀 발견 시 즉시 롤백 가능하도록 PR 은 단일 커밋 단위로 구성한다.

---

## Success Metrics

- **품질 메트릭**: `fund_signals.signal_type='surge_candidate'` 시그널 중
  `per > 500` 또는 `pbr > 30` 인 종목 비율 = 0% (배포 이후 영구 유지).
  현재는 측정 불가(데이터 미저장). 배포 후 사후 쿼리로 검증.
- **데이터 메트릭**: `surge_metadata.legacy_score=0` 인 시그널에 대해서도
  valuation_filter_applied = True 가 보장됨 (Path B 도 필터 통과 확인).
- **테스트 메트릭**: 신규 `test_surge_ai019_path_b.py` 의 4개 케이스
  (per>500 제외, pbr>30 제외, per=None 통과, 정상값 통과) 100% 통과.
- **회귀 메트릭**: 기존 1147개 테스트 전부 통과 (SPEC-AI-018 acceptance 포함).

---

## MX Tag Targets

- `SurgeCandidate` (per/pbr 필드 신규 추가): `@MX:NOTE`
- `surge_detector.detect_surge_candidates()` valuation 필터 블록 (REQ-AI019-003,
  REQ-AI019-004): `@MX:ANCHOR` — fan_in 3+ (3개 탐지기 후 단일 진입점), SPEC
  invariant 보장 지점.
- `fund_manager.py:1700-1718` (제거 대상): `@MX:LEGACY` 또는 삭제 커밋 메시지
  에 SPEC-AI-019 명시.
- 3개 탐지기의 per/pbr piggy-back 수집 지점 (REQ-AI019-002): `@MX:NOTE`.

---

## References

- SPEC-AI-018 (`backend/.claude/specs/SPEC-AI-018/spec.md`): Phase 3
  밸류에이션 필터 도입 (REQ-AI018-006 ~ REQ-AI018-008)
- SPEC-AI-013: 15:20 KST 독립 잡 분리 (commit `2bfe435`)
- 코드 위치
  - `backend/app/services/fund_manager.py:2859` (`run_surge_signal_generation`)
  - `backend/app/services/fund_manager.py:1224` (`_gather_surge_candidates`)
  - `backend/app/services/fund_manager.py:1498` (`_gather_leading_candidates`)
  - `backend/app/services/fund_manager.py:1700-1718` (제거 대상 필터)
  - `backend/app/services/surge_detector.py:72` (SurgeCandidate 정의 영역)
  - `backend/app/services/surge_detector.py:779` (`compute_ensemble_score`)
  - `backend/app/services/surge_detector.py:900-1050` (qualification + bypass)
  - `backend/app/surge_config/surge_settings.py:112-115`
    (`ValuationDisqualifiersConfig`)
  - `backend/app/surge_config/surge_detection.yaml`
    (`valuation_disqualifiers` 항목)
  - `backend/app/services/scheduler.py:1378-1383` (`surge_execute_buys` 등록)
