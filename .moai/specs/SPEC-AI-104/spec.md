---
id: SPEC-AI-104
title: "급등예측 Pool D 활성화 검증 — 관측 canary 전환 + 정밀도 측정 게이트"
version: "0.1.0"
status: completed
created: 2026-08-06
updated: 2026-08-06
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scan-universe, pool-d, activation-gate, precision-measurement, backend"
tier: M
related_specs: [SPEC-AI-086, SPEC-AI-089, SPEC-AI-096, SPEC-AI-102]
---

# SPEC-AI-104: 급등예측 Pool D 활성화 검증 — 관측 canary 전환 + 정밀도 측정 게이트

## HISTORY

- 2026-08-06 v0.1.0 (draft): 위임 프롬프트("Pool D를 활성화해야 하는가, 활성화한다면 어떻게
  검증할 것인가")에 대한 응답으로 작성. 원 지시가 요구한 "SurgeActualOutcome 과거 데이터
  대상 backtest"는 코드 직접 확인 결과 기술적으로 불가능함을 확인했다(§Context 핵심 정정
  참고) — 대신 이 프로젝트의 기존 전진 적용 관례와 일치하는 forward 섀도우 관측 창으로
  대체했다. git 히스토리 조사로 `pool_d_min_slots`가 도입 시점(SPEC-AI-086, 2026-07-27)부터
  단 한 번도 0이 아니었던 적이 없음을 확인했고(단순 누락이 아니라 SPEC-AI-066/079/091이
  확립한 "배선 → 관측 → 활성화는 별도 결정" 단계적 롤아웃 관례의 의도된 결과), SPEC-AI-096이
  이미 관측 인프라(pool_d_count 영속화)와 활성화 기준 초안(canary=10, 최소 5거래일)을
  문서화했으나 그 기준을 **명시적으로 "임의 제안값 — Open Questions에 최종 확정 필요"로
  남겨두었음**을 확인했다. 본 SPEC은 그 열린 질문을 해소하는 후속 SPEC이며, SPEC-AI-096을
  개정하지 않는다 — SPEC-AI-096 자신이 세부 수치 확정을 후속 작업에 명시적으로 위임했기
  때문이다(§Decisions D0 참고). 조사 중 리포트 스크립트에서 신규 결함(pool_d 열이 표 렌더링에서
  누락됨)을 직접 코드 확인으로 발견해 REQ로 반영했다.

## 선행 SPEC

- **SPEC-AI-086** (완료): Pool D(뉴스 언급 기반 신규 소스 풀) 도입. `pool_d_min_slots`
  기본값 0 — 도입 시점부터 의도적으로 비활성(§Context 검증된 사실 1 참고). Pool D는
  측정 전용 그림자 유니버스 소속일 뿐 탐지 후보(`merged`)에 재투입되지 않는다.
- **SPEC-AI-089** (완료): `measure_universe_detection_gap()`(실시간 인메모리 gap 집계,
  `universe_gap_measurement_enabled` 기본 False) + `analyze_no_signal_pool_attribution()`
  (오프라인 무시그널 실제급등 종목의 풀 귀속 분석, `SurgeActualOutcome`×`SurgeUniverseMember`
  조인) 도입. 두 함수 모두 pool_d를 이미 1급 시민으로 취급한다(`_POOL_NAMES` 튜플에 포함).
  본 SPEC은 이 인프라를 재사용하며 두 함수의 로직 자체는 변경하지 않는다.
- **SPEC-AI-096** (완료): Pool D 관측 영속화(`SurgeUniversePoolHistory.pool_d_count`
  컬럼) + canary 활성화 기준 **초안**(§Decisions D3: canary 값 10, 최소 5거래일
  `pool_d_count > 0` 관측) 문서화. D3 원문이 명시적으로 "거래일 수(5일)는 이 프로젝트가
  다른 관측 기간을 명시한 선례가 없어 임의 제안값이다 — Open Questions에 최종 확정 필요
  항목으로 남긴다"고 밝혔다 — 본 SPEC이 그 최종 확정을 데이터 기반으로 수행한다.
- **SPEC-AI-102** (in-progress): `build_scan_universe()`를 Pool 소싱/existing 병합으로
  내부 분리(`_source_scan_universe_pools`/`_assemble_scan_universe`). Pool D 활성화 및
  bridge 마스터 스위치 기본값 전환은 명시적으로 이 SPEC의 범위 밖으로 위임했다("이미
  SPEC-AI-096 §Decisions D3/D4가 문서화한 별도의 관측-기반 운영 활성화 절차"). 본 SPEC이
  그 절차를 이행한다.

## Context / Problem

### 검증된 사실 1 — `pool_d_min_slots`는 도입 시점부터 의도적으로 0이었다 (단순 누락이 아님)

`git log --all -p -S"pool_d_min_slots"`로 전체 히스토리를 대조한 결과, 이 필드는
`surge_settings.py`/`surge_detection.yaml`에 최초로 등장한 커밋(`d30863b`, 2026-07-27,
SPEC-AI-086)부터 지금까지 값 `0`을 벗어난 적이 단 한 번도 없다. 이는 이 프로젝트가
반복적으로 사용해 온 **단계적 롤아웃 관례**(SPEC-AI-066/079/091 — "배선을 먼저 완성하고
기본값 OFF로 배포, 이후 관측 데이터로 활성화 여부를 별도 판단")를 그대로 따른 결과다.
SPEC-AI-096이 이미 이 사실을 확인했고, 본 SPEC의 git 히스토리 재조사도 동일한 결론에
도달했다 — Pool D가 "꺼진 채 방치"된 것이 아니라 "관측 인프라가 갖춰지기 전까지 의도적으로
비활성 상태를 유지"한 것이다.

### 검증된 사실 2 — Pool D는 현재 news-mention 기반이며, 이미 `relevance == "direct"`로 필터링되어 있다

`_source_scan_universe_pools()`(`surge_detector.py:5544`-`5579`)의 실제 쿼리:

```python
if config.pool_d_min_slots > 0:
    pool_d_rows = (
        db.query(Stock.stock_code)
        .join(NewsStockRelation, NewsStockRelation.stock_id == Stock.id)
        .join(NewsArticle, NewsArticle.id == NewsStockRelation.news_id)
        .filter(
            NewsArticle.published_at.isnot(None),
            NewsArticle.published_at >= datetime.now(timezone.utc) - timedelta(hours=24),
            NewsStockRelation.relevance == "direct",
        )
        .distinct()
        .limit(max(config.pool_d_min_slots * 5, config.pool_d_min_slots))
        .all()
    )
```

즉 "아무 기사에나 언급된 아무 종목"이 아니라, 이미 (a) `relevance == "direct"`(SPEC-AI-085가
확장한 직접 관계 매칭)로 필터링되고, (b) 최근 24시간 이내 기사로 제한되며, (c) 예약 슬롯의
5배까지만 유계 오버페치된다. 매칭 정확도(뉴스-종목 관계 자체의 품질) 개선은 SPEC-AI-085/096이
이미 별도 SPEC("C")으로 위임한 영역이며, 본 SPEC은 그 필터링 로직 자체를 재론하지 않는다.

### 핵심 정정 — 과거 데이터 대상 backtest는 기술적으로 불가능하다 (전진 관측으로 대체)

위임 프롬프트는 "SurgeActualOutcome 과거 이력을 대상으로 backtest/shadow 모드에서 측정한
뒤 활성화하라"고 요청했으나, 코드 직접 확인 결과 이는 **기술적으로 실행 불가능**하다:

1. Pool D 소싱 쿼리의 `NewsArticle.published_at >= datetime.now(timezone.utc) - timedelta(hours=24)`
   조건은 **실행 시점 상대적**(`now()` 기준 최근 24시간)이며, 과거 특정 거래일을 매개변수로
   받아 그 날짜 기준으로 재실행할 방법이 코드에 없다 — Pool A(`Disclosure.rcept_dt ==
   today_str`)와 달리 파라미터화되어 있지 않다.
2. 이 프로젝트는 SPEC-AI-071/076/086/089를 포함해 반복적으로 "과거 데이터 백필/소급
   재계산 금지, 전진 적용만"을 명시적 정책으로 채택해 왔다(예: SPEC-AI-089 Out of Scope
   "과거 스캔 유니버스/탐지 결과의 소급 재계산·백필은 수행하지 않는다").

따라서 본 SPEC은 backtest 대신 **forward 섀도우 관측 창**(canary 값으로 실제 운영 중
매일 신규로 데이터를 축적하는 방식)을 채택한다 — 이는 SPEC-AI-096 D3/D4가 이미 채택한
접근과 동일한 방법론이며, 프로젝트 관례와도 일치한다.

### 검증된 사실 3 — `pool_d_min_slots=0`인 한 어떤 관측도 원천적으로 불가능하다

`if config.pool_d_min_slots > 0:` 게이트(`surge_detector.py:5551`) 때문에, 값이 0인 동안
Pool D 소싱 쿼리 자체가 **한 번도 실행되지 않는다** — `pool_d_codes`는 항상 빈 리스트이고,
`entry_pool_map`에 `"pool_d"` 값이 기록된 적이 없으며, 따라서 `SurgeUniverseMember.entry_pool`
에도 `"pool_d"` 행이 지금까지 단 하나도 영속화되지 않았다. 이는 SPEC-AI-089의
`analyze_no_signal_pool_attribution()`을 지금 실행해도 pool_d 귀속 건수가 항상 0으로
나옴을 의미한다 — 코드 버그가 아니라 canary 전환 자체가 관측의 **선행 조건**이라는 뜻이다.

### 신규 발견 — 기존 측정 리포트 스크립트에 pool_d 열 누락 결함이 있다

`scripts/measure_universe_detection_gap_report.py`의 `_render_report()`(:45-97)를 직접
읽은 결과, 거래일별 표 헤더와 행 렌더링(:55-73)이 `pool_a`/`pool_b`/`pool_c`/`absent`
4개 컬럼만 명시적으로 추출하며 **`pool_d`를 누락**한다 — `analyze_no_signal_pool_attribution()`
이 반환하는 `attribution_summary`에는 `pool_d` 키가 이미 존재하는데도(하단 "표본 합산"
집계 루프(:90)는 `pool_d`를 올바르게 포함한다), 사람이 가장 먼저 보는 거래일별 표에서는
빠져 있다. Pool D를 canary 전환한 뒤 이 리포트를 그대로 사용하면 recall측 관측 결과가
표에서 보이지 않는다 — 본 SPEC의 REQ-AI104-001이 수정한다.

## Goals

1. `pool_d_min_slots`를 관측 목적의 최소 침습 canary 값으로 전환해, 현재 원천적으로 불가능한
   Pool D 관측을 가능하게 한다 — 탐지·매매 경로에는 영향을 주지 않는다(§Context 검증된 사실 1,
   Pool D는 `merged`에 재투입되지 않음).
2. `universe_gap_measurement_enabled`를 활성화해 SPEC-AI-089의 기존 gap 계측이 canary 관측
   기간 동안 실행되도록 한다.
3. Pool D의 recall측(무시그널 실제급등 종목 중 pool_d 귀속분) 관측을 위해 기존 리포트의
   pool_d 열 누락 결함을 수정한다.
4. Pool D의 precision측(pool_d 소속 전체 종목 중 실제 급등 비율 — "노이즈가 많은가"라는
   원 우려에 직접 답하는 지표)을 측정하는 신규 함수를 추가한다 — 기존 인프라는 recall측만
   다루고 precision측은 다루지 않는다.
5. recall측과 precision측을 함께 검토할 수 있는 단일 리포트를 산출하고, SPEC-AI-096 D3가
   "임의 제안값"으로 남긴 활성화 기준을 정량적으로 재정의해 plan.md에 문서화한다 — 실제
   판단(canary를 넘어선 추가 상향, bridge 마스터 스위치 전환)은 이 SPEC의 산출물을 근거로
   한 별도의 향후 운영 결정으로 남긴다.

## Non-Goals

### Out of Scope — Pool D/bridge 실제 프로덕션 활성화(canary를 넘어선 추가 플래그 전환)

- canary 값(10)을 넘어서는 `pool_d_min_slots` 추가 상향은 본 SPEC의 관측 리포트를 근거로 한
  별도의 향후 운영 판단이다.
- `scan_universe_bridge_candidates_enabled`(기존 False 유지) 전환은 SPEC-AI-096 §Decisions
  D4가 이미 별도로 정의한 관측-기반 활성화 절차(최소 10거래일)의 대상이며 본 SPEC은 건드리지
  않는다.

### Out of Scope — 과거 데이터 백필/소급 backtest

- Pool D 소싱 쿼리(`NewsArticle.published_at >= now()-24h`)는 실행 시점 상대적이라 과거
  특정 거래일에 대해 재실행할 수 없다.
- 이 프로젝트의 전진 적용 전용 관례(SPEC-AI-071/076/086/089)를 따라 과거 데이터 소급
  재계산·백필을 수행하지 않는다. 원 위임 프롬프트가 요청한 backtest는 이 기술적/관례적
  제약으로 인해 전진(forward) 섀도우 관측 창으로 대체한다(§Context 핵심 정정 참고).

### Out of Scope — Pool D 소싱 쿼리 로직 자체

- `NewsStockRelation.relevance == "direct"` 필터, 24시간 윈도, 유계 오버페치 배수(5x) 등
  Pool D 소싱 쿼리의 필터링 로직은 SPEC-AI-086 소유이며 무변경.
- 뉴스-종목 관계 매칭 정확도 개선은 SPEC-AI-085/096이 이미 별도 SPEC("C")으로 위임한 영역이다.

### Out of Scope — pool_a/b/c 소싱 로직 및 quota 재조정

- 신규 precision 측정 함수는 pool_d를 우선 대상으로 하며, pool_a/b/c에 대한 동일 측정은
  비교 baseline 목적으로만 리포트에 병기한다.
- pool_a/b/c의 기존 소싱 로직(SPEC-AI-065/074/076/078)이나 quota(`pool_b/c_min_slots`,
  SPEC-AI-076)를 정밀도 측정 결과에 따라 조정하는 것은 범위 밖이다.
- **SPEC-AI-065 위치 참고**: 이 SPEC은 완료 상태이나 루트 `.moai/specs/`가 아닌 레거시 경로
  `backend/.moai/specs/SPEC-AI-065/`에 위치한다(`ls backend/.moai/specs/` 확인 완료) — AI SPEC
  디렉토리가 한동안 두 경로(`root .moai/specs/`, `backend/.moai/specs/`)로 분산되어 있던 시기의
  배치이며 오탈자가 아니다. 본 문서에서 인용하는 SPEC-AI-065(본 항목 및 REQ-AI104-008)는 모두 이
  위치를 가리킨다.

## Decisions

### D0 — SPEC-AI-096을 개정하지 않고 신규 SPEC으로 후속한다

SPEC-AI-096 §Decisions D3는 canary 값과 관측 기간을 "임의 제안값 — Open Questions에 최종
확정 필요"로 명시적으로 남겼다. 이는 완료된 SPEC의 확정된 결정을 뒤집는 것이 아니라, 그
SPEC 스스로 후속 작업에 위임한 미해결 항목을 해소하는 것이다 — `completed → in-progress
(amendment)` 절차(제자리 개정)를 적용할 근거가 없다. SPEC-AI-102가 동일한 패턴(Pool D
활성화를 명시적으로 범위 밖으로 위임)을 이미 보였다.

### D1 — `pool_d_min_slots`는 Pydantic 모델 기본값이 아닌 YAML 배포값만 canary로 전환한다

SPEC-AI-079가 확립한 선례(`relative_threshold_enabled` 활성화 시 "YAML 런타임 값만 flip,
Pydantic 기본값 유지" — 근거: `test_new_fields_on_existing_configs`류 테스트가 모델 기본값을
단언하는 패턴)를 계승한다. `surge_settings.py`의 `pool_d_min_slots: int = 0` 기본값은
무변경 유지하고, `surge_detection.yaml`의 배포값만 canary 값(10, SPEC-AI-096 D3 제안값
계승)으로 전환한다. **필수 검증**(plan.md M3): 기존 테스트 스위트에 `pool_d_min_slots`
모델 기본값을 단언하는 테스트가 있는지 확인하고, 있다면 그 값(0)과 일치시킨다.

기각한 대안: Pydantic 기본값 자체를 10으로 변경 — SPEC-AI-079 선례와 어긋나고, 향후
`SurgeDetectionConfig()`를 인자 없이 생성하는 모든 테스트/스크립트가 암묵적으로 Pool D를
활성화한 채 실행되는 부작용을 낳는다(명시적 오버라이드 없이는 항상 안전한 기본값이어야 한다는
설계 원칙 위반).

### D2 — canary 전환은 탐지·매매 경로에 구조적으로 영향을 줄 수 없다

`_assemble_scan_universe()`(`surge_detector.py:5593`-)를 직접 읽은 결과, `pool_d_codes`는
`_universe_codes`(측정 유니버스)와 `entry_pool_map`(태깅) 조립에만 사용되며, 8개 1차
탐지기의 후보 딕셔너리(`merged`)에는 어떤 경로로도 재투입되지 않는다. `merged`로의 유일한
승격 경로는 `generate_scan_universe_bridge_candidates()`(SPEC-AI-092/102)이고, 그 함수의
마스터 스위치(`scan_universe_bridge_candidates_enabled`)는 본 SPEC에서 무변경(False
유지)이다. 따라서 canary 전환은 **구조적으로** 탐지 후보 집합·앙상블 점수·발행 시그널·매매
실행에 영향을 줄 수 없다 — 이는 추정이 아니라 코드 읽기로 확인된 사실이며, REQ-AI104-003의
[HARD] 불변식으로 명문화한다.

### D3 — precision측 측정은 SPEC-AI-089 인프라의 자매 함수로 추가한다 (기존 함수 무수정)

기존 `analyze_no_signal_pool_attribution()`은 "무시그널 실제급등 종목이 어느 풀에
있었는가"(recall측)만 답한다. "그 풀에 있는 종목 중 실제로 몇 %가 진짜 급등이었는가"
(precision측, 노이즈 여부)는 답하지 않는다 — 두 지표는 서로 다른 질문이며 하나가 다른
하나를 함의하지 않는다. 신규 함수 `analyze_pool_precision_by_date()`를
`surge_universe_gap_service.py`에 자매 함수로 추가하고, `SurgeUniverseMember.entry_pool`
× `SurgeActualOutcome.was_surge` 조인만 사용한다(신규 마이그레이션 없음, REQ-AI104-005).

기각한 대안: 기존 `analyze_no_signal_pool_attribution()`을 확장해 precision을 함께
반환 — 그 함수는 "무시그널 종목"이라는 이미 좁혀진 부분집합만 순회하므로 pool_d 소속
**전체** 종목(무시그널이 아닌, 즉 이미 다른 채널로 시그널을 받은 종목 포함)을 대상으로 하는
precision 계산과 입력 집합이 다르다 — 함수를 억지로 겸용하면 두 관심사가 뒤섞여
가독성·테스트 격리 모두 나빠진다(YAGNI, Enforce Simplicity 사다리).

### D4 — 활성화 기준은 recall측 unique-catch + precision측 baseline 비교의 복합 게이트로 재정의한다

SPEC-AI-096 D3의 "5거래일 동안 pool_d_count > 0"은 **존재 여부만** 확인하는 약한 기준이다
— 소싱 쿼리가 비어 있지 않다는 사실은 그 결과가 유용하다는 증거가 아니다. 본 SPEC은 D3를
다음 복합 기준으로 대체한다(REQ-AI104-007, 문서화만 — 실제 판단은 범위 밖):
(a) recall측: 관측 창 내 최소 N거래일에서 pool_d 귀속 unique-catch(pool_d에만 있고
pool_a/b/c에는 없는 무시그널 실제급등 종목)가 1건 이상 관측됨, AND (b) precision측:
pool_d의 정밀도가 같은 기간 pool_a/b/c 정밀도 대비 뚜렷이 낮지 않음(구체적 정량 임계값은
관측 데이터 축적 후 확정 — Open Questions).

## Requirements

### REQ-AI104-001: 측정 리포트 pool_d 열 누락 결함 수정

**When** `scripts/measure_universe_detection_gap_report.py`가 거래일별 귀속 요약 표를
렌더링하면, the report script **shall** `pool_d` 카운트를 `pool_a`/`pool_b`/`pool_c`/
`absent`와 동일하게 매 거래일 행에 표시해야 한다.

필수 조건:

- 표 헤더에 `pool_d` 열이 추가되어야 한다.
- 기존 "표본 합산" 집계 섹션(이미 `pool_d`를 올바르게 포함)의 산출값과 신규 거래일별
  `pool_d` 열의 합이 일치해야 한다(회귀 검증).
- `analyze_no_signal_pool_attribution()` 자체(SPEC-AI-089 소유)는 무수정이다.

### REQ-AI104-002: `pool_d_min_slots` canary 전환

`pool_d_min_slots`가 0(기존 배포값)이면 Pool D 소싱 쿼리 자체가 실행되지 않아 어떤 관측도
원천적으로 불가능하다(§Context 검증된 사실 3). **Where** `pool_d_min_slots`가 0(기존
배포값)이면, the system's deployed config **shall** `surge_detection.yaml`의
`pool_d_min_slots` 값을 관측 목적의 최소 침습 canary 값(10)으로 전환해야 한다.

필수 조건:

- `surge_settings.py`의 Pydantic 모델 기본값(`int = 0`)은 무변경 유지한다(§Decisions D1).
- 기존 테스트 스위트에 모델 기본값을 단언하는 테스트가 있으면 그 결과와 일치해야 한다(plan.md
  M3 사전조사).
- Pool D 소싱 쿼리의 필터·유계 오버페치 배수(5x) 로직 자체는 무변경이다(§Non-Goals).

### REQ-AI104-003: 탐지·매매 경로 무영향 불변식 [HARD]

**While** canary 전환(REQ-AI104-002)이 적용되는 동안, the system **shall not** Pool D
소싱 결과를 8개 1차 탐지기의 병합 후보(`merged`), 앙상블 점수(`compute_ensemble_score`),
발행 시그널, 또는 매매 실행 경로(`surge_trading_service.py`)에 어떤 방식으로도 유입시켜서는
안 된다.

필수 조건:

- Pool D 코드는 `_universe_codes`/`entry_pool_map`/`pool_counts`/`SurgeUniverseMember`
  영속화(측정 전용 경로)에만 사용되어야 한다.
- `scan_universe_bridge_candidates_enabled`는 False로 무변경 유지되어야 한다 — 이 플래그가
  Pool D를 `merged`로 승격시키는 유일한 경로다.
- `git diff --name-only`에 `surge_trading_service.py`, `compute_ensemble_score`가 포함된
  파일이 등장하면 안 된다.

### REQ-AI104-004: gap 계측 활성화

관측 창 동안 Pool D의 recall측 관측이 가능하려면 SPEC-AI-089의 실시간 gap 집계
(`measure_universe_detection_gap()`)가 매 스캔 사이클마다 실행되어야 한다. **Where**
canary 관측 창(REQ-AI104-002)이 활성화되어 있으면, the system's deployed config **shall**
`universe_gap_measurement_enabled`를 True로 전환해야 한다.

필수 조건:

- `measure_universe_detection_gap()` 자체(SPEC-AI-089 소유)는 무수정이다.
- REQ-AI089-003/004의 기존 [HARD] 불변식(탐지 무영향, 비용 예산 5%/120초 여유)이 계속
  성립함을 재확인해야 한다(회귀 검증만 — 새 코드 아님).

### REQ-AI104-005: Pool D precision 측정 신규 함수

**When** 관측 창 내 특정 거래일에 `SurgeUniverseMember.entry_pool == "pool_d"`로 영속화된
종목이 1개 이상 존재하면, the system **shall** 그날 pool_d 소속 전체 종목 중
`SurgeActualOutcome.was_surge == True`에 해당하는 비율(precision)을 계산하는 신규 함수
`analyze_pool_precision_by_date()`를 제공해야 한다.

필수 조건:

- 신규 함수는 `surge_universe_gap_service.py`에 `analyze_no_signal_pool_attribution()`의
  자매 함수로 추가하며, 신규 DB 쓰기·마이그레이션 없이 `SurgeUniverseMember` ×
  `SurgeActualOutcome` 조인만 사용해야 한다.
- pool_a/b/c에 대해서도 동일한 계산을 수행해 baseline 비교값을 함께 반환해야 한다
  (§Non-Goals — pool_a/b/c 로직 변경은 아니며, 순수 비교 목적의 동일 계산 재사용).
- 해당 거래일 pool_d 소속 종목이 0건이면 precision을 `None`으로 반환해야 한다
  (division-by-zero guard, 기존 `measure_universe_detection_gap()`의 `*_gap_ratio` 패턴
  계승).

### REQ-AI104-006: 통합 관측 리포트 확장

**When** `scripts/measure_universe_detection_gap_report.py`가 실행되면, the report
script **shall** REQ-AI104-001로 수정된 recall측 pool_d 열과 REQ-AI104-005의 precision측
지표(pool_d 및 pool_a/b/c baseline)를 동일 리포트에 병기해야 한다.

필수 조건:

- 신규 정량 임계값을 코드에 하드코딩하지 않는다 — 리포트는 관측값만 제시하고, 활성화
  여부 판단은 사람이 수행한다(REQ-AI089-005 M2 결정 게이트 관례 계승).
- 표본 거래일 수(`--days`)는 기존 스크립트의 CLI 인자를 그대로 재사용한다.

### REQ-AI104-007: 데이터 기반 활성화 게이트 문서화 (코드 아님)

**While** 관측 창(최소 5거래일, SPEC-AI-096 §Decisions D3 제안값 계승)이 누적되는 동안,
plan.md **shall** `pool_d_min_slots`를 canary 값(10)을 넘어 추가로 상향하거나
`scan_universe_bridge_candidates_enabled`를 켜는 후속 결정에 필요한 정량 기준(§Decisions
D4의 복합 게이트: recall측 unique-catch + precision측 baseline 비교)을 문서화해야 한다.

필수 조건:

- 그 기준의 실제 충족 여부 판단과 플래그 전환 자체는 본 SPEC의 범위 밖이다(§Non-Goals).
- SPEC-AI-096 D3/D4의 원 제안값(canary=10, bridge 관측 10거래일)과의 관계를 명시적으로
  기술해야 한다(대체가 아니라 정량화 — D4는 무변경).

### REQ-AI104-008: 기존 파이프라인 회귀 없음 보장 [HARD]

**While** 본 SPEC이 적용되는 동안, the system **shall not** 8개 탐지기의 스코어링·앙상블
가중치, quota 배분(SPEC-AI-076/096), bridge 후보화(SPEC-AI-092/102), existing 병합
필터(SPEC-AI-094), Pool A/B/C 소싱 로직(SPEC-AI-065/074/076/078)을 변경한다.

필수 조건:

- `git diff --name-only`에 위 로직을 소유한 파일이 포함되면, 그 변경이 순수
  characterization 테스트 추가(REQ-AI104-001/005의 회귀 검증 목적)뿐임을 diff 리뷰로
  증명해야 한다.

## Open Questions

1. **precision측 baseline 비교의 구체적 정량 임계값**(예: "pool_d 정밀도가 pool_a/b/c
   평균 대비 N%p 이상 낮지 않음"의 N값): 관측 데이터가 없는 현재로서는 임의 설정이
   근거 없는 숫자가 된다 — 최소 5거래일 관측 데이터 축적 후, 실측 분포를 근거로
   Implementation Kickoff 이후 별도 확정한다.
2. **관측 창 5거래일이 실제로 충분한 표본을 제공하는가**: 이 프로젝트의 실제 급등 발생
   빈도(거래일당 실제 급등 종목 수)에 따라 5거래일 내 pool_d 소속 종목이 전혀 없을 수도
   있다 — REQ-AI104-006 리포트가 표본 부족 자체를 명시적으로 드러내야 하며(division-by-zero
   guard), 표본이 부족하면 관측 창을 연장하는 것도 유효한 결론이다.
3. **`pool_d_min_slots` Pydantic 모델 기본값을 단언하는 기존 테스트의 존재 여부**:
   `test_spec_ai_096.py`/`test_spec_ai_086.py` 등을 plan.md M3에서 직접 확인해야
   한다(§Decisions D1 필수 검증) — 존재하지 않으면 이 REQ는 신규 테스트로 그 계약을
   최초로 명문화한다.
