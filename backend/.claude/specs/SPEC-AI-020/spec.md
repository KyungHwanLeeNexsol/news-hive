---
id: SPEC-AI-020
version: 0.1.0
status: draft
created: 2026-05-28
updated: 2026-05-28
author: Nexsol
priority: high
issue_number: null
---

# SPEC-AI-020: 급등 시그널 PER/PBR 밸류에이션 필터 제거 (모멘텀-가치 시간축 불일치 교정)

## HISTORY

- 2026-05-28 (v0.1.0): 최초 작성. SPEC-AI-018 Phase 3 에서 도입되고 SPEC-AI-019
  로 적용 범위가 확장된 PER/PBR 밸류에이션 부적격 필터를 급등 시그널 파이프라인
  에서 전면 제거한다. 모멘텀 시그널에 가치 팩터를 결합한 것은 시간축 불일치
  (24~72시간 모멘텀 vs 12개월 회계 기반 가치) 이며, 운영 시뮬레이션 결과 산업
  편향(바이오/제약/적자 테마주 부당 제외)만 초래하고 본래 의도한 "극단 과대평가
  outlier 차단"은 달성하지 못한 것으로 확인되었다.

---

## 선행 SPEC

- **SPEC-AI-018**: 급등예측 신호 품질 개선 Phase 3 — 밸류에이션 부적격 필터
  도입 (REQ-AI018-006 ~ REQ-AI018-008). 본 SPEC 이 무효화한다.
- **SPEC-AI-019**: 급등 시그널 밸류에이션 필터 적용 범위 확장 — Path A/B
  공통 단일 지점(`surge_detector.detect_surge_candidates()`)으로 필터 이전.
  본 SPEC 이 무효화한다.

> 본 SPEC 은 두 선행 SPEC 의 **필터 적용 로직만** 무효화한다. SPEC-AI-019 가
> 도입한 데이터 수집 인프라(SurgeCandidate per/pbr 필드, 3개 탐지기 piggy-back
> 수집, `_extract_valuation` 헬퍼)는 향후 관찰성(observability) 및 사후 알파
> 분석 용도로 **유지**한다.

---

## Overview

본 SPEC 은 SPEC-AI-018 Phase 3 가 도입한 가치 기반 부적격 필터(PER > 500 또는
PBR > 30 종목 제외)를 급등 시그널 생성 파이프라인에서 완전히 제거한다.
필터 제거는 단일 지점인 `surge_detector.detect_surge_candidates()` 에서
수행되며, 관련 테스트는 인버트되어 해당 후보들이 시그널 풀에 포함되는 것을
검증한다.

이 SPEC 은 **무엇을(WHAT)** 과 **왜(WHY)** 를 정의한다. 구체적인 구현 세부는
Run 단계로 이연한다.

---

## Background — 왜 필터를 제거하는가

### 1. 시간축 불일치 (Time-scale mismatch)

급등 시그널은 뉴스, 거래량 급증, 공시 이벤트를 트리거로 하는 **24~72시간 단기
모멘텀** 신호이다. 반면 PER/PBR 은 12개월 회계 데이터에 기반한 **장기 가치**
지표이다. 두 팩터는 시간 지평이 다르며, 학계 실증 연구(Asness, Moskowitz &
Pedersen, "Value and Momentum Everywhere", *Journal of Finance* 2013)에서
가치 팩터와 모멘텀 팩터는 종종 음의 상관관계를 보이는 것으로 보고되었다.
모멘텀 전략에 가치 필터를 결합하면 알파가 희석되며, 두 팩터를 동시에
운용할 의도라면 별도의 가치 전략으로 분리하는 것이 표준 관행이다.

### 2. 한국 급등주 산업 특성

한국 시장의 급등 후보는 코스닥 중소형 테마주(바이오·제약, 2차전지, AI, 로봇)
가 다수를 차지한다. 이들 산업은 다음 특성을 가진다.

- 적자 기업 비율이 높아 EPS < 0 인 경우가 빈번하다. EPS 가 음수이거나 0 에
  근접하면 PER 은 정의되지 않거나 의미가 사라진다(매우 큰 양수로 발산).
- 성장 단계 기업은 미래 현금흐름을 시장이 가격에 반영하므로 PBR 이 자연스럽게
  높다. 이는 과대평가의 신호가 아니라 산업 구조적 특징이다.

대표적 반례로 Tesla 2020년은 PER > 1000 인 상태에서 최대 상승률을 기록하였다.
PER 필터를 적용했다면 2020년의 모든 매수 시그널이 차단되었을 것이다.

### 3. SPEC-AI-018 의 의도와 실제 효과의 괴리

SPEC-AI-018 Phase 3 의 명시적 의도는 "극단 과대평가 outlier 차단"이었다.
그러나 SPEC-AI-019 적용 후 운영 데이터 시뮬레이션 결과, 실제 효과는
"성장주·바이오/제약 부당 제외" 였다(아래 Evidence 참조). 의도와 효과의
괴리가 분명하므로 필터 자체를 폐기한다.

---

## Evidence (운영 데이터)

SPEC-AI-019 의 필터 로직을 현재 운영 `fund_signals` 테이블의 96 개
`signal_type='surge_candidate'` 시그널에 시뮬레이션 적용한 결과:

### 제외 종목 분포 (총 11 종목, 11.5%)

| 분류 | 종목 수 | 대표 사례 |
|---|---|---|
| 바이오/제약 성장주 | 7 | 알테오젠 (pbr=46.8), 펩트론 (pbr=47.1), 보로노이 (pbr=49.4), 에이비엘바이오 (pbr=36.7), 디앤디파마텍 (pbr=54.1), 네이처셀 (pbr=32.7) |
| 적자 테마주 (per>500: EPS 0 근접) | 4 | 레인보우로보틱스 (per=10027) 외 3종 |
| 진짜 pump-and-dump 의심 종목 | 0 | 해당 없음 |

### 신뢰도(confidence) 영향 분석

- **Top 5 신뢰도 종목 (conf ≥ 0.484)**: 0 종목 제외 (필터가 high-confidence
  시그널은 건드리지 못함)
- **제외된 11 종목의 신뢰도 범위**: 0.238 ~ 0.452 (mid-tier 만 제거)

### 결론

필터의 본래 의도(위험 종목 차단)는 달성되지 못했고, 부수 효과(산업 편향)만
남았다. 11.5% 의 시그널이 정당한 사유 없이 매일 제거되고 있으며, 그중 64%
가 바이오/제약 성장주이다.

---

## Goal

- 모멘텀 시그널 본래의 시간 지평(24~72시간)을 유지하고, 시간축이 다른 가치
  지표로 인한 산업 편향을 제거한다.
- 단일 지점(`surge_detector.detect_surge_candidates()`)에서 필터 블록만
  제거하여, Path A 와 Path B 의 행위 동등성은 자동으로 보존된다(양 경로 모두
  필터 없음).
- 향후 가치 지표는 시그널 차단이 아니라 **observability / 사후 알파 분석**
  용도로만 활용한다.

---

## Approach Summary

1. `surge_detector.detect_surge_candidates()` 에서 SPEC-AI-019 REQ-AI019-003
   ~005 가 추가한 valuation 필터 블록을 **제거**한다.
2. `SurgeCandidate.per`, `SurgeCandidate.pbr` 필드는 **데이터 관찰용으로
   유지**한다. 필드 정의 주석에 "data-only; filter removed by SPEC-AI-020"
   을 명시한다.
3. `_extract_valuation` 헬퍼와 3개 탐지기의 piggy-back 수집 로직은 **유지**
   한다(향후 분석용).
4. `ValuationDisqualifiersConfig` Pydantic 모델과 `surge_detection.yaml` 의
   `valuation_disqualifiers` 섹션은 **스키마 유지, 미사용 표시**한다.
   YAML 항목에 `# DEPRECATED by SPEC-AI-020` 주석을 추가한다.
5. SPEC-AI-018 REQ-AI018-006 ~ 008 은 본 SPEC 으로 **deprecated** 처리한다.
   SPEC-AI-018 문서 자체는 FROZEN 이므로 수정하지 않는다.
6. 관련 테스트(`test_surge_ai019_path_b.py`, `test_surge_ai018.py` Phase 3
   케이스)를 인버트하거나 retire 한다.

---

## EARS Requirements

### REQ-AI020-001: 밸류에이션 필터 블록 제거

The system **shall** remove the `valuation_disqualifiers` filter block from
`backend/app/services/surge_detector.py` `detect_surge_candidates()`.
The qualification loop **shall not** evaluate any candidate against
`max_per` or `max_pbr` thresholds. No `SurgeCandidate` **shall** be excluded
from the emitted signal set on valuation grounds.

### REQ-AI020-002: SurgeCandidate per/pbr 필드 유지 (data-only)

The `per: float | None` and `pbr: float | None` fields on the
`SurgeCandidate` dataclass **shall** remain in place. The field-level
docstring or inline comment **shall** state explicitly that these fields are
"data-only observability; filtering removed by SPEC-AI-020". The fields
**shall not** be referenced by any conditional control flow in the signal
emission path after this SPEC is implemented.

### REQ-AI020-003: _extract_valuation 헬퍼 유지

The `_extract_valuation` helper introduced by SPEC-AI-019 **shall** remain
callable and **shall** continue to be invoked during `SurgeCandidate`
construction so that per/pbr values are populated. **Where** the helper is
called, it **shall** populate the candidate fields but **shall not** trigger
any disqualification decision.

### REQ-AI020-004: 3개 탐지기 piggy-back 수집 유지

The piggy-back per/pbr collection performed by
`detect_theme_cluster_candidates`, `detect_volume_news_combo_candidates`,
and `detect_disclosure_pattern_candidates` **shall** be preserved. Detectors
**shall** continue to populate `SurgeCandidate.per` and `SurgeCandidate.pbr`
from their existing market data retrieval paths for future observability
analysis.

### REQ-AI020-005: ValuationDisqualifiersConfig schema 유지, 미사용 표시

The `ValuationDisqualifiersConfig` Pydantic model in
`backend/app/surge_config/surge_settings.py` and the
`valuation_disqualifiers` section in
`backend/app/surge_config/surge_detection.yaml` **shall** remain present
to preserve schema stability. The YAML entry **shall** carry a comment
`# DEPRECATED by SPEC-AI-020: schema preserved for future use, filter
removed`. The configuration loader call **shall** be removed from
`detect_surge_candidates()`.

### REQ-AI020-006: SPEC-AI-018 Phase 3 deprecation 명시

The system **shall** treat SPEC-AI-018 REQ-AI018-006, REQ-AI018-007, and
REQ-AI018-008 as **deprecated** and superseded by SPEC-AI-020. The
SPEC-AI-018 document itself **shall not** be modified (it is FROZEN
historical reference). The supersession relationship **shall** be documented
in this SPEC's HISTORY and 선행 SPEC sections.

### REQ-AI020-007: Path B 테스트 인버트

The tests in `backend/tests/test_surge_ai019_path_b.py` that previously
asserted exclusion of `per > 500` or `pbr > 30` candidates **shall** be
inverted so that the same candidates now assert **inclusion** in the
qualified signal set. Tests asserting `None`/normal-value pass-through
**shall** remain unchanged in expected behavior (they still pass, now
trivially because no filter exists). Path A/B parity tests **shall** be
retained because parity is preserved by both paths having no filter.

### REQ-AI020-008: SPEC-AI-018 Phase 3 테스트 retire/invert

The tests in `backend/tests/test_surge_ai018.py` that exercise Phase 3
(PER/PBR exclusion) behavior **shall** be either retired with a comment
referencing SPEC-AI-020, or inverted to assert inclusion. Tests covering
SPEC-AI-018 Phase 1, 2, and 4 (ensemble weights, recent surge penalty,
group consensus multiplier) **shall** remain unchanged and **shall**
continue to pass.

### REQ-AI020-009: 전체 회귀 통과

The full pre-existing test suite **shall** continue to pass under the
acceptance criteria amended by REQ-AI020-007 and REQ-AI020-008. No public
behavior other than the removal of valuation-based exclusion **shall**
change.

### REQ-AI020-010: MX 태그 정리

The `@MX:ANCHOR` annotation referencing `SPEC-AI-019 REQ-AI019-003` on
the removed filter block **shall** be removed together with the block.
The `@MX:NOTE` annotations on the `SurgeCandidate.per` and
`SurgeCandidate.pbr` fields **shall** be updated to read
"SPEC-AI-020: data-only observability, filtering removed". The
`valuation_disqualifiers` configuration definition site **shall** receive
a new `@MX:NOTE` indicating its deprecated status.

---

## Exclusions (What NOT to Build)

본 SPEC 의 범위에서 **명시적으로 제외**되는 항목 (별도 후속 SPEC 로 분리):

- **대체 안전판 도입은 포함하지 않는다**. 관리종목 차단, 거래정지 차단,
  일일 변동성 캡, 유동성 필터 등은 분명히 올바른 방향이지만 별도 설계 SPEC
  (SPEC-AI-021 후보) 으로 분리한다.
- **임계값 완화는 포함하지 않는다**. PER>2000, PBR>100 등으로 임계값을
  높이는 방식이 아니라 필터 자체의 전면 제거이다.
- **백테스팅 인프라 또는 A/B 테스트 하네스 구축은 포함하지 않는다**.
  필터 효과 측정을 위한 별도 인프라는 SPEC-AI-022 이후 후보이다.
- **산업·섹터별 적응형 필터링은 포함하지 않는다**. 복잡도 대비 효과 불확실
  하며, 별도 backtesting 없이 도입 시 또 다른 편향을 야기할 수 있다.
- **PER/PBR 데이터의 영구 저장(`stocks` 테이블 스키마 변경)은 포함하지
  않는다**. SPEC-AI-019 와 동일하게 외부 API 동적 조회를 유지한다.
- **다른 가치 지표(EV/EBITDA, ROE, PSR 등)의 도입은 포함하지 않는다**.
- **`run_surge_signal_generation` 스케줄 또는 실행 빈도 변경은 포함하지
  않는다**.

---

## Rejected Alternatives

### Option A: 임계값 완화 (per > 2000, pbr > 100)

극단값만 차단하도록 임계값을 상향 조정하는 방식. **거부**.

- 시간축 불일치라는 근본 문제는 해결되지 않는다. 모멘텀 전략에 가치 필터를
  결합하는 설계 자체가 잘못이다.
- 임계값을 어떤 값으로 설정해도 동일한 카테고리 오류(category error)가
  잔존한다.

### Option B: 산업/섹터별 차등 임계값

바이오/제약은 PER 임계값을 상향, 일반 제조업은 그대로 유지하는 방식.
**거부**.

- 복잡도 대비 효과 불확실. 산업 분류 데이터의 신뢰성과 적용 시점 문제
  (산업 재분류 빈도) 가 추가된다.
- 별도 backtesting 없이 도입 시 또 다른 편향(예: 산업 분류 기준에 따른
  bias) 을 야기할 가능성.

### Option C: 부분 유지 (PER 만 유지, PBR 만 제거)

두 지표 중 하나만 살리는 방식. **거부**.

- PER 과 PBR 은 같은 카테고리(가치 팩터)에 속한다. 부분 유지는 근거 없는
  자의적 선택이다.
- 시간축 불일치 문제는 두 지표 모두에 동일하게 적용된다.

### Option D: 필터를 경고(warning) 로 강등하여 시그널 메타데이터에 기록

차단은 하지 않되 메타데이터에 high_valuation=True 플래그를 부착하는 방식.
**부분 채택 — Future Work 로 이연**.

- 본 SPEC 의 REQ-AI020-002 (per/pbr 필드 데이터 유지) 가 이미 기본
  observability 인프라를 보존한다.
- 별도 메타데이터 플래그 추가는 본 SPEC 의 범위(필터 제거)를 벗어나므로
  Future Work 로 이연한다.

---

## Impact

### 운영 영향

- 매 영업일 시그널 풀에서 시뮬레이션 기준 **11 개 내외 종목이 다시 포함**
  된다(96 시그널 중 11.5%).
- 다음 영업일 09:00 KST 의 `surge_execute_buys` 가 검토하는 후보 종목이
  다양해진다. 특히 바이오/제약 성장주가 정상적으로 평가 대상에 포함된다.

### 시그널 품질

- 모멘텀 시그널의 산업 다양성 회복 (특히 바이오/제약 부문).
- 시간축 정합성 회복: 24~72시간 모멘텀 신호가 12개월 가치 지표에 의해
  필터링되지 않음.

### 관찰성

- `SurgeCandidate.per`, `SurgeCandidate.pbr` 필드는 유지되어 향후 사후
  분석이 가능하다. 시그널 메타데이터 또는 별도 로깅을 통해 가치 지표 분포
  를 추적할 수 있다(별도 SPEC 으로 이연).

### SPEC 정합성

- SPEC-AI-018 Phase 3 (REQ-006 ~ 008) 와 SPEC-AI-019 의 필터 적용 로직이
  무효화된다. 두 선행 SPEC 의 데이터 수집 인프라(SPEC-AI-019 REQ-001 ~ 002,
  004)는 유지된다.

---

## Future Work

본 SPEC 이 명시적으로 제외한 항목들은 별도 후속 SPEC 후보이다.

- **SPEC-AI-021 (후보)**: 대체 안전판 도입 — 관리종목·거래정지 차단,
  일일 변동성 캡, 유동성 필터. 모멘텀 전략에 적합한 시간 지평의 안전판
  설계.
- **SPEC-AI-022 (후보)**: PER/PBR 데이터를 활용한 사후 알파 분석 —
  필터링이 아닌 observability 용도. 매수 후 수익률을 가치 지표 분위별로
  분해하여 실제 산업·가치 효과를 측정.
- **SPEC-AI-023 (후보)**: 산업/섹터 분류를 활용한 시그널 다양화 또는
  포지션 사이징.

---

## Rollout Plan

### Step 0: SPEC-AI-019 PR 처리 결정 (사용자)

사용자는 본 SPEC 의 구현 PR 을 만들기 전에 다음 중 하나를 결정한다.

- (a) SPEC-AI-019 PR 을 머지하지 않고 close 한 뒤, SPEC-AI-020 을 main
  브랜치에 직접 기반하여 구현. 이 경우 SPEC-AI-019 의 데이터 수집 인프라
  (REQ-001 ~ 002, 004) 부분만 SPEC-AI-020 구현 PR 에 포함시킨다.
- (b) SPEC-AI-019 PR 을 먼저 머지하고, SPEC-AI-020 PR 이 필터 부분만
  revert. 이 경우 SPEC-AI-020 구현 PR 의 변경 범위는 좁다.

두 옵션 모두 본 SPEC 의 acceptance 기준에는 영향을 주지 않는다.

### Step 1: 구현 PR 생성

단일 PR 로 다음을 포함한다.

- `surge_detector.detect_surge_candidates()` 필터 블록 제거
- `SurgeCandidate.per/pbr` 필드 주석 업데이트
- `surge_detection.yaml` 의 `valuation_disqualifiers` 항목에 deprecation
  주석 추가
- `test_surge_ai019_path_b.py` 인버트
- `test_surge_ai018.py` Phase 3 케이스 retire/invert
- MX 태그 정리
- 회귀 테스트 전체 통과 확인

### Step 2: 머지 및 배포

main 머지 후 자동 배포.

### Step 3: 사후 모니터링

다음 영업일 15:20 KST 잡 결과 모니터링: 직전 시뮬레이션에서 제외되었던
11 종목 중 적절한 confidence 종목이 다시 시그널로 등장하는지 확인.

### Step 4: 롤백 안전성

회귀 발견 시 즉시 롤백 가능하도록 단일 PR 단위로 구성. 데이터 수집 인프라
는 유지되므로 필터 재도입 결정 시 코드 차이는 작다.

---

## Success Metrics

- **필터 부재 검증**: 다음 영업일 15:20 KST 잡 실행 후
  `fund_signals.signal_type='surge_candidate'` 시그널 중 PER>500 또는
  PBR>30 종목이 정상 포함된다 (이전 시뮬레이션에서 제외되었던 11 종목과
  유사 분포 예상).
- **테스트 메트릭**: REQ-AI020-007, REQ-AI020-008 에 따라 인버트된
  테스트 케이스 100% 통과. 기존 SPEC-AI-018 Phase 1/2/4 테스트 영향 없음.
- **데이터 보존 검증**: `SurgeCandidate.per`, `SurgeCandidate.pbr` 필드가
  3개 탐지기 모두에서 정상 populate 됨을 단위 테스트로 확인.
- **회귀 메트릭**: 변경된 acceptance 기준 하에 전체 회귀 슈트 100% 통과.

---

## MX Tag Targets

- **제거 대상**: `surge_detector.detect_surge_candidates()` 의 필터 블록
  과 함께 `@MX:ANCHOR SPEC-AI-019 REQ-AI019-003,004,005` 태그 삭제.
- **업데이트 대상**: `SurgeCandidate.per` 및 `SurgeCandidate.pbr` 필드의
  `@MX:NOTE` 를 "SPEC-AI-020: data-only observability, filtering removed"
  으로 변경.
- **신규 추가**: `ValuationDisqualifiersConfig` 정의부 (Pydantic 모델)
  와 `valuation_disqualifiers` YAML 섹션에 `@MX:NOTE` 추가하여
  "DEPRECATED by SPEC-AI-020: schema preserved, no longer applied" 명시.
- **삭제 커밋 메시지**: 본 SPEC 의 구현 커밋 메시지에 "supersedes
  SPEC-AI-018 REQ-006~008 and SPEC-AI-019 REQ-003~005" 명시.

---

## References

### 학술 근거

- Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013).
  "Value and Momentum Everywhere". *Journal of Finance*, 68(3), 929–985.
  가치 팩터와 모멘텀 팩터의 음의 상관관계 실증 보고.

### 선행 SPEC

- SPEC-AI-018 (`backend/.claude/specs/SPEC-AI-018/spec.md`):
  Phase 3 밸류에이션 필터 도입 — 본 SPEC 이 무효화.
- SPEC-AI-019 (`backend/.claude/specs/SPEC-AI-019/spec.md`):
  필터 적용 범위 확장 — 본 SPEC 이 무효화.

### 코드 위치 (제거/수정 대상)

- `backend/app/services/surge_detector.py`
  `detect_surge_candidates()` 의 valuation 필터 블록 (REQ-AI020-001)
- `backend/app/services/surge_detector.py`
  `SurgeCandidate` per/pbr 필드 주석 (REQ-AI020-002)
- `backend/app/services/surge_detector.py`
  `_extract_valuation` 헬퍼 (REQ-AI020-003: 유지)
- `backend/app/services/surge_detector.py`
  3개 탐지기 piggy-back 수집 (REQ-AI020-004: 유지)
- `backend/app/surge_config/surge_settings.py`
  `ValuationDisqualifiersConfig` (REQ-AI020-005: schema 유지)
- `backend/app/surge_config/surge_detection.yaml`
  `valuation_disqualifiers` 섹션 (REQ-AI020-005: deprecation 주석 추가)
- `backend/tests/test_surge_ai019_path_b.py` (REQ-AI020-007: 인버트)
- `backend/tests/test_surge_ai018.py`
  Phase 3 관련 케이스 (REQ-AI020-008: retire/invert)
