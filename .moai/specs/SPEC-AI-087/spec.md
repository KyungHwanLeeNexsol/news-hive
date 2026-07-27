---
id: SPEC-AI-087
title: "시가총액/키워드 데이터 완전성 개선"
version: "0.1.0"
status: completed
created: 2026-07-27
updated: 2026-07-27
author: Nexsol
priority: High
phase: "backend data-completeness v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, market-cap, null-handling, scheduler, keyword-backfill, data-completeness, backend"
issue_number: null
tier: M
---

# SPEC-AI-087: 시가총액/키워드 데이터 완전성 개선

## HISTORY

- 2026-07-27 v0.1.0 (draft): 초안 생성. 이번 세션의 read-only 조사(DB 쿼리 + 코드 검증)로 확인된 3가지
  근본원인(시총 업데이트 페이지 상한 500종목 고정 / NULL 시총 하드 필터로 인한 탐지기 후보풀 배제 /
  키워드 백필 함수 미스케줄링)을 사용자 승인(AskUserQuestion)에 따라 하나의 SPEC으로 번들.

## Context / Problem

2026-07-24 급등예측 recall 근사 0% 근본원인 조사에서, 추적 종목(`stocks` 테이블, 2,605건) 중 63%가
`market_cap = NULL`이며, 여러 탐지기가 `market_cap >= threshold` 형태의 하드 필터를 사용함이 확인됐다.
SQL에서 `NULL >= N`은 항상 미충족(unknown/false)이므로, 이 필터는 NULL 시총 종목 — 통계적으로 소형/유통
주식수 적은, 실제 급등이 상대적으로 잦은 종목군 — 을 후보풀에서 조용히 배제한다.

### 검증된 사실 (이번 세션 read-only 조사, 2026-07-27)

- **[F-1] 시총 업데이트 잡이 시장당 상위 500종목만 커버한다.** `_update_market_caps()`
  (`scheduler.py:423`)의 `for page in range(1, 11)`(시장당 10페이지×50=500종목) 고정 상한이 원인이다.
  Naver 모바일 API(`fetch_naver_stock_list`, `naver_finance.py:1143`)를 이번 세션에 직접 조회한 결과
  KOSPI `totalCount=2471`, KOSDAQ `totalCount=1822`로, API 자체에는 500종목 제한이 없다 — 제한은
  순수히 `_update_market_caps`의 하드코딩된 `range(1, 11)`이다. DB의 populated market_cap 건수(964)가
  이 500×2 상한의 이론적 상한(≤1000)에 근접함이 이를 뒷받침한다.
- **[F-2] NULL 시총 대응 패턴(floor-quota + 날짜 로테이션)이 이미 SPEC-AI-077에서 검증됐으나
  일부 경로에만 적용돼 있다.** `near_limit_up` 탐지기(`surge_detector.py:2704-2769`,
  `NearLimitUpConfig.null_cap_min_slots`)는 이 패턴을 사용하지만, `volume_anomaly` 탐지기
  (`_detect_volume_anomaly_internal`, `surge_detector.py:2489`)의 후보 쿼리(`:2504`,
  `Stock.market_cap >= config.min_market_cap`, 상한(LIMIT) 자체가 없는 무제한 조회)와,
  `detect_group_cascade_signals`의 계열사 후보 필터(`:3630-3639`,
  `Stock.market_cap >= config.cascade_min_market_cap`), `detect_gap_up_runners`의 섹터 피어 필터
  (`:4006-4014`, `Stock.market_cap.isnot(None)`)는 하드 배제 상태다. 실측: 진흥기업2우B(002787,
  2026-07-24 거래량비 5.53x)가 `market_cap IS NULL`이라는 이유만으로 volume_anomaly 시그널을 받지
  못했다(다른 조건은 임계값을 상회).
  > **사전 조사 메모 정정**: 초기 조사 메모는 "sector cascade/ripple leader selection"의 위치를
  > `surge_detector.py:3894-3898`로 기재했으나, 본 SPEC 작성 중 재검증한 결과 해당 라인은
  > `detect_bollinger_squeeze`(볼린저 밴드 스퀴즈 탐지기)의 시총 상위 N 선정 쿼리였다 —
  > `detect_group_cascade_signals`/`detect_gap_up_runners`와는 무관한 별개 함수다. `:4006-4014`
  > (gap_up_runners 섹터 피어)는 정확했다. 이 정정에 따라 본 SPEC은 REQ-006에서 두 경계를 모두
  > 명시적으로 확정한다(§Out of Scope 참고).
- **[F-3] 키워드 백필 함수는 존재하나 정기 실행 경로가 없다.** `backfill_stock_keywords()`
  (`keyword_tagging_service.py:110`, idempotent — `keywords`가 NULL/빈 값인 종목만 갱신)가
  `scheduler.py`의 `register_jobs()`에 등록돼 있지 않음을 grep으로 확인(0건 매치). 추적 종목의
  75.1%(1,957/2,605)가 `keywords = NULL`이며, 이는 뉴스기반 테마전파 탐지기(SPEC-AI-084, 현재 플래그
  OFF)의 입력을 무력화한다. `_gather_stock_theme_texts()`(`keyword_tagging_service.py:62`)는 외부
  API/LLM 호출 없이 이미 저장된 `NewsArticle`/`Disclosure` 레코드만 읽으며
  (`_MAX_ARTICLES_PER_STOCK=50`, `_MAX_DISCLOSURES_PER_STOCK=20` 상한 기존 존재) — 정기 스케줄링
  비용이 낮다.
- **[F-4] 테마클러스터 후보 생성기는 위 세 경로와 무관한, 이미 존재하는 다섯 번째 NULL 시총 처리
  패턴을 가진다.** `_get_theme_cluster_candidates`(`surge_detector.py:363-384`, SPEC-AI-038 소유)의
  섹터 피어 조회는 `or_(Stock.market_cap >= min_market_cap_eok, and_(Stock.market_cap.is_(None),
  Stock.stock_code.in_(_news_mentioned_codes)))` 형태로, NULL 시총 종목을 "해당 뉴스 창(window) 내
  언급된 종목"에 한해서만 조건부 포함한다(SPEC-AI-038 REQ-038-PF1, 불필요한 가격 API 호출 폭증
  방지가 목적). 이 패턴은 F-1/F-2가 다루는 세 탐지기(volume_anomaly/group_cascade/gap_up_runners)
  및 근접상한가 이월(near_limit_up) 어디에도 속하지 않는 별개 함수이며, 본 SPEC의 REQ-001~008 중
  어느 것도 이 함수를 대상으로 하지 않는다 — §Out of Scope 참고.

### Goal

세 근본원인에 대해 행동보존(behavior-preserving) 원칙 하에: (1) 시총 업데이트가 추적 종목 전체 범위까지
확장 가능하도록, (2) 3개 탐지기 경로가 NULL 시총 종목을 opt-in 방식으로 후보풀에 편입할 수 있도록,
(3) 키워드 백필이 정기적으로 실행되도록 한다. 목표는 데이터 완전성(coverage) 개선이며, 탐지기 본체 로직·
앙상블 가중치·매매 로직은 변경하지 않는다.

## Requirements (EARS)

### REQ-AI087-001 (While, P0) — 시가총액 업데이트 페이지 상한 확장
**While** 시가총액 업데이트 배치 잡이 실행되는 동안, the system **shall** 시장당 안전 상한
60페이지(페이지당 50종목, 시장당 최대 3,000종목 조회 범위)에 도달하거나 Naver API가 빈 페이지를
반환할 때까지 시장별 순위 페이지를 계속 조회하여, 추적 대상(`stocks` 테이블) 종목이 포함될 수 있는
범위까지 시가총액 조회 범위를 확장한다.
> 구현 참고: 대상 함수 `_update_market_caps`(`scheduler.py:423`). 현재 `for page in range(1, 11)`
> (시장당 10페이지=최대 500종목) 고정 상한을 안전 상한 상수 `_MARKET_CAP_UPDATE_MAX_PAGES = 60`
> (시장당)로 확장한다. 기존 `if not items: break` 조기 종료 로직(`:437-438`)은 그대로 유지 — 안전
> 상한은 API 이상 동작 시의 방어선이지 정상 경로의 종료 조건이 아니다(plan.md R-3 리스크 분석 참고,
> 60페이지×2시장=최대 120회 Naver 호출).

### REQ-AI087-002 (When undesired-detected, P0) — 기존 커버리지 종목 값 불변 [HARD]
**When** 페이지 상한이 확장된 상태에서 시가총액 업데이트가 실행되면, the system **shall NOT** 이미
상위 500위 이내 순위로 조회되던 종목의 market_cap 계산 방식·값 출처를 변경하며, 갱신 대상 범위를
`stocks` 테이블 교집합(추적 종목) 밖으로 확장하지 아니한다.
> 구현 참고: 갱신 대상은 이미 `Stock.stock_code.in_(cap_map.keys())`(`scheduler.py:449`)로 추적
> 종목에 한정돼 있다 — 이 경계는 변경하지 않는다.

### REQ-AI087-003 (Where, P1) — volume_anomaly NULL 시총 후보 편입(floor quota, 기본 OFF)
**Where** volume_anomaly 탐지기의 NULL 시총 최소 슬롯 설정이 0보다 크게 설정된 경우, the system
**shall** SPEC-AI-077의 floor-quota + 날짜 로테이션 패턴을 적용하여 NULL 시총 종목을 최대 그 슬롯
수만큼 기존 non-null 후보 조회와 별도로 추가 편입시킨다. **Where** 값이 0(기본값)인 경우, the system
**shall** 기존 `market_cap >= min_market_cap` 단일 조건 조회를 바이트 동등하게 유지한다.
> 구현 참고: 대상 `_detect_volume_anomaly_internal`(`surge_detector.py:2489`), 현재 필터
> `Stock.market_cap >= config.min_market_cap`(`:2504`, 상한 없는 전체 조회 — 종목당
> `fetch_stock_price_history_sync` 네트워크 fetch 발생). 신규 필드
> `VolumeAnomalyConfig.null_cap_min_slots: int = 0`(기본 OFF). 이 경로는 유일하게 NULL 편입이
> 신규 네트워크 fetch를 유발하므로(다른 두 경로와 달리) 명시적 opt-in floor-quota로 비용을 상한한다.

### REQ-AI087-004 (Where, P1) — group_cascade 계열사 후보 NULL 시총 편입(기존 상한 내)
**Where** group_cascade 탐지기의 NULL 시총 계열사 편입이 설정으로 활성화된 경우, the system **shall**
기존 `max_cascade_per_flagship` 상한 내에서 NULL 시총 계열사를 non-null 종목보다 낮은 정렬 순위로
후보에 포함시킨다. **Where** 미설정(기본값)인 경우, the system **shall** 기존
`market_cap >= cascade_min_market_cap` 단일 조건 필터를 유지한다. 대장주(flagship) 판정 로직은 본
요구사항의 대상이 아니다(REQ-006 참고).
> 구현 참고: 대상 `detect_group_cascade_signals`(`surge_detector.py:3529`), 계열사 후보 필터
> (`:3630-3639`). 신규 필드 `GroupCascadeConfig.cascade_include_null_market_cap: bool = False`
> (기본 OFF). 이 경로는 후보당 네트워크 fetch가 없음(검증됨 — `:3642-3658` 순수 DB/인메모리 처리)이므로
> floor-quota가 아닌 단순 boolean 토글로 충분하다(후보풀 자체가 접두사 매칭으로 이미 작고
> `max_cascade_per_flagship`로 상한이 걸려 있어 굶주림/경쟁 위험이 near_limit_up만큼 크지 않음).

### REQ-AI087-005 (Where, P1) — gap_up_runners 섹터 피어 후보 NULL 시총 편입(기존 상한 내)
**Where** gap_up_runners 탐지기의 NULL 시총 피어 편입이 설정으로 활성화된 경우, the system **shall**
기존 섹터 피어 조회 상한(`.limit(5)`) 및 런너 선정 로직(`[:2]`) 내에서 NULL 시총 피어를 non-null
종목보다 낮은 정렬 순위로 후보에 포함시킨다. **Where** 미설정(기본값)인 경우, the system **shall**
기존 `market_cap.isnot(None)` 필터를 유지한다.
> 구현 참고: 대상 `detect_gap_up_runners`(`surge_detector.py:3945`), 섹터 피어 쿼리(`:4006-4014`).
> 신규 필드 `GapUpRunnersConfig.runner_include_null_market_cap: bool = False`(기본 OFF). 런너당
> 시세 조회(`_fetch_price_change_sync`, `:4032`)는 `[:2]` 슬라이스로 이미 상한이 걸려 있어(검증됨)
> NULL 편입 자체는 네트워크 비용을 늘리지 않는다.

### REQ-AI087-006 (When undesired-detected, P0) — 편입 대상 경계 명시 [HARD]
**When** REQ-003~005의 NULL 시총 편입이 어떤 방식으로든 적용되면, the system **shall NOT** (a)
`detect_group_cascade_signals`의 대장주(flagship) NULL 시총 제외 로직(`:3598-3600`, `:3609`, `:3613`,
의도된 설계)을 수정하며, (b) `detect_bollinger_squeeze`의 시총 상위 N 선정 쿼리(`:3894-3900`,
`market_cap.isnot(None)` 유사 패턴이 존재하나 본 SPEC 승인 범위 밖)를 수정하지 아니한다.
> 구현 참고: (a)/(b) 모두 회귀 테스트로 무변경을 고정한다(§Out of Scope 참고).

### REQ-AI087-007 (Ubiquitous, P1) — 키워드 백필 정기 스케줄링
The system **shall** `backfill_stock_keywords()`를 APScheduler 정기 잡으로 등록하여, `keywords`가
NULL 또는 공백인 추적 종목에 한해 주기적으로 키워드 태깅을 시도하며, 이미 채워진 종목의 `keywords` 값은
변경하지 아니한다(함수 자체의 기존 idempotent 계약을 그대로 소비).
> 구현 참고: 등록 지점 `scheduler.py` `register_jobs()`(기존 `_update_market_caps` 등록 패턴,
> `:2094-2101` 참고 구조). 대상 함수 `backfill_stock_keywords`(`keyword_tagging_service.py:110`).
> `refresh_stock_keywords()`(이미 태깅된 종목 재계산)는 본 REQ의 대상이 아니다(§Out of Scope 참고).

### REQ-AI087-008 (While, P0) — 백워드 호환 탈출구 [HARD]
**While** REQ-003~005의 신규 설정 필드가 모두 기본값(`null_cap_min_slots=0`,
`cascade_include_null_market_cap=False`, `runner_include_null_market_cap=False`)일 때, the system
**shall** 본 SPEC 적용 이전과 바이트 동등한 탐지 후보 집합 및 시그널 생성 결과를 낸다. **While**
REQ-001의 페이지 상한 확장이 적용된 이후에도, the system **shall** 이미 커버되던 상위 500위 이내
종목의 market_cap 값을 변경하지 아니한다(REQ-002 재확인).

## Out of Scope

### Out of Scope — 유니버스→탐지 배선
- SPEC-AI-086이 이미 measurement-only로 범위를 확정한 `build_scan_universe` 그림자 유니버스를 실제
  탐지 입력으로 배선하는 작업은 본 SPEC과 무관하며 별도 SPEC 영역이다(SPEC-AI-086 Exclusion 1 계승).
  본 SPEC이 다루는 3개 탐지기 후보 쿼리(volume_anomaly/group_cascade/gap_up_runners)는 이미 실제
  탐지 입력 경로이며 `build_scan_universe`의 그림자 유니버스와는 다른 층위다.

### Out of Scope — 편입 대상에서 명시적으로 제외된 코드 경로
- `detect_group_cascade_signals`의 대장주(flagship) NULL 시총 제외 로직(`surge_detector.py:3598-3600`,
  `:3609`, `:3613`, AC-007 의도된 설계) — 수정 금지.
- `detect_bollinger_squeeze`의 시총 상위 N 선정 쿼리(`surge_detector.py:3894-3900`,
  `market_cap.isnot(None)` 유사 패턴이 존재하나 본 SPEC 승인 범위 밖) — 수정 금지. (사전 조사 메모의
  라인 인용 오류 정정 — Context 절 참고.)
- `_get_theme_cluster_candidates`(테마클러스터 후보 생성기, `surge_detector.py:363-384`,
  SPEC-AI-038 소유)의 뉴스 언급 종목 한정 NULL 시총 조건부 포함 로직(F-4 참고) — 이미 정상 동작
  중이며 본 SPEC의 REQ-001~008 대상이 아니다. 수정 금지.

### Out of Scope — 키워드 갱신(refresh) 스케줄링
- 이미 태깅된 종목의 `keywords` 재계산을 수행하는 `refresh_stock_keywords()`의 정기 스케줄 등록은 본
  SPEC의 범위 밖이다 — root cause 3은 NULL 미태깅 종목에 한정되며, 기존 태그의 staleness는 별개 이슈다.

### Out of Scope — 탐지·매매 로직
- 탐지기 본체 앙상블 가중치, 적응형 임계값, 발신 게이팅, 매매(SPEC-AI-043 예측기록모드) 로직은 무변경.
- `near_limit_up` 탐지기(SPEC-AI-077)의 기존 구현은 소스 패턴으로만 참조하며 수정하지 아니한다.

### Out of Scope — 과거 데이터 백필
- 과거 market_cap/keywords 값의 소급 백필은 수행하지 않는다(전진 적용만 — SPEC-AI-076/086 관례 계승).

### Out of Scope — 신규 DB 스키마
- 본 SPEC은 신규 마이그레이션을 요구하지 않는다(Pydantic 설정 필드 추가 + 스케줄러 잡 등록만).

## Ownership

- **본 SPEC**: 시총 업데이트 커버리지 확장(REQ-001/002) + 3개 탐지기 후보풀 NULL 시총 편입
  (REQ-003~006) + 키워드 백필 스케줄링(REQ-007/008).
- **SPEC-AI-077**: NULL 시총 floor-quota + 날짜 로테이션 패턴의 원 소유자(near_limit_up 전용). 본
  SPEC은 volume_anomaly에 그 패턴을 이식하되(REQ-003), cascade/gap_up_runners는 후보풀이 이미 작고
  상한이 걸려 있어(REQ-004/005) 더 단순한 boolean 토글로 구현한다.
- **SPEC-AI-084/085**: `stocks.keywords` 테마 바스켓의 소비자(매칭 로직 소유). 본 SPEC은 백필
  스케줄링만 추가하며 084/085의 매칭 로직은 무변경.
- **SPEC-AI-086**: `build_scan_universe` 측정 전용 그림자 유니버스 소유자. 본 SPEC이 다루는 3개
  탐지기 후보 쿼리와는 다른 층위(§Out of Scope 참고).
