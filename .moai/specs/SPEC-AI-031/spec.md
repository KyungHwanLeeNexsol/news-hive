---
id: SPEC-AI-031
version: 0.1.0
status: draft
created: 2026-06-02
updated: 2026-06-02
author: Nexsol
priority: High
issue_number: null
---

# SPEC-AI-031: 장 시작 직전 재확인 스캔 (Pre-Open Confirmation Scan)

## HISTORY

- 2026-06-02 (v0.1.0): 최초 작성. 15:20 KST 시그널 생성과 익일 09:05 KST 매수
  실행 사이의 **18시간 간극(18h gap)** 문제를 해결하기 위한 장 시작 직전
  재확인 스캔을 도입한다. 시그널 생성 파이프라인(15:20)은 변경하지 않고,
  매수 직전(08:45 KST)에 신선한 데이터로 후보를 재평가/재점수화하는 새 단계를
  추가한다.

---

## 선행 SPEC (Prerequisites)

- **SPEC-AI-012**: 급등예측 시그널 생성 파이프라인 — `surge_candidate` 시그널의
  탐지기 구성(`theme_cluster`, `immediate_disclosure`, `volume_news_combo`,
  `disclosure_pattern`) 및 `surge_metadata` 스키마를 정의한다. 본 SPEC 은
  이 시그널 풀을 입력으로 소비할 뿐 생성 로직을 변경하지 않는다.
- **SPEC-AI-013**: 급등예측 모의투자 포트폴리오 서비스 — `get_today_signals()`,
  `execute_buy_orders()`, `is_buy_eligible_hours()` 및 15:20 생성 / 09:05 매수
  스케줄 잡(`surge_signal_generate`, `surge_execute_buys`)을 정의한다. 본 SPEC
  은 이 위에 재확인 스캔 단계를 비침투적으로 얹는다.

> 본 SPEC 은 두 선행 SPEC 의 **시그널 생성 및 기존 매수 로직을 변경하지 않는다**.
> `get_today_signals()` 의 반환 형태(`(signal, stock, probability, boost_info)`
> 4-tuple, SPEC-AI-021 도입)와 호출 규약을 그대로 유지한 채, 그 결과를 입력으로
> 받아 필터링·재점수화하는 새 함수를 추가한다.

---

## Overview

뉴스하이브 급등예측 시스템은 장 마감 후 **15:20 KST** 에 익일 매수용 시그널을
생성하고, 다음 영업일 **09:05 KST** 에 이를 읽어 매수를 실행한다. 이 두 시점
사이에는 약 18시간의 간극이 존재하며, 그 사이 야간 공시·시장 환경 변화로 인해
전일 시그널의 유효성이 크게 달라질 수 있다.

본 SPEC 은 매수 실행 직전(**08:45 KST**, 개장 15분 전)에 전일 시그널을 신선한
데이터로 **재확인(confirm)** 하고 신선도 기반 점수(`confirmation_score`)를
부여하는 단계를 추가한다. `execute_buy_orders()` 는 08:45~09:05 구간에서 호출될
때 기존 `get_today_signals()` 대신 `get_confirmed_signals()` 의 결과를 사용한다.

이 SPEC 은 **무엇을(WHAT)** 과 **왜(WHY)** 를 정의한다. 함수 시그니처·내부
구현 세부는 Run 단계로 이연한다.

---

## Background — 18시간 간극 문제

### 1. 시점 불일치 (Time gap)

| 단계 | 시각 (KST) | 동작 |
|---|---|---|
| 시그널 생성 | 15:20 (전일) | 당일 장 데이터 기반 익일 후보 탐지 |
| 매수 실행 | 09:05 (당일) | 전일 시그널 읽어 시가 매수 |
| **간극** | **~18시간** | 야간 공시, 동종 섹터 선반영, 시장 환경 변화 |

### 2. 2026-06-02 운영 데이터 분석

당일 데이터 분석에서 시그널의 시점별 품질 차이가 확인되었다.

| 시그널 시각 | 탐지기 구성 | 확률 범위 | 실측 성과 |
|---|---|---|---|
| 09:31 (오전) | `immediate_disclosure + theme_cluster` | 0.38 ~ 0.71 | +10% ~ +15% (최우수) |
| 15:20 (오후) | `theme_cluster` only | 0.24 ~ 0.27 | 저조 |

오전의 `immediate_disclosure` 결합 시그널이 가장 우수한 성과를 보였다. 그러나
이 신선한 공시 신호도 09:05 매수 시점에는 이미 18시간이 경과하여 조건이
변했을 수 있다. 오후 15:20 의 `theme_cluster` 단독 시그널은 확률 자체가 낮아
야간 변화에 더 취약하다.

### 3. 핵심 통찰

- **신선한 공시/뉴스가 있는 시그널**은 매수 시점에도 유효성이 높다.
- **오래된 단독 모멘텀 시그널**(theme_cluster only)은 18시간 경과 시 thesis 가
  희석될 가능성이 크다.
- **동종 섹터 종목이 이미 크게 움직인 경우**(>+5%) 해당 테마의 1차 파동이 이미
  진행되어 추격 매수 위험이 높다.

따라서 매수 직전에 (a) 신규 공시 유무, (b) 동종 섹터 선반영 여부, (c) 시그널
경과 시간을 종합하여 후보를 재평가할 필요가 있다.

---

## Goal

- 15:20 시그널 생성 파이프라인을 **변경하지 않고**, 매수 직전 신선한 데이터로
  후보를 재확인하는 단계를 추가한다.
- 각 후보에 신선도 기반 `confirmation_score` 를 부여하여, 오래된 단독 모멘텀
  시그널은 신뢰도를 낮추고 신규 공시·뉴스가 뒷받침되는 시그널은 신뢰도를
  유지한다.
- 야간 악재(부정적 공시) 발생 시 후보 신뢰도를 강하게 감점하여 매수에서
  사실상 배제한다.
- 기능을 설정(`confirmation_scan.enabled`)으로 토글 가능하게 하여, 비활성화
  시 기존 `get_today_signals()` 경로로 **완전 후방 호환** 동작한다.

---

## EARS Requirements

### REQ-AI031-001: 장 시작 직전 재확인 스캔 함수

The system **shall** provide a new function `get_confirmed_signals(db)` in
`backend/app/services/surge_trading_service.py` that takes the output of
`get_today_signals(db)` as its candidate set and returns a filtered,
re-scored `confirmed_list`. **When** `get_confirmed_signals(db)` is invoked,
the system **shall** preserve the existing per-candidate tuple shape used by
`get_today_signals()` (currently `(signal, stock, probability, boost_info)`,
SPEC-AI-021) and **shall** attach a `confirmation_score` for each candidate
without modifying the underlying `FundSignal` records or the signal generation
pipeline.

### REQ-AI031-002: 신규 공시 재확인 (DART since 15:20)

**When** `get_confirmed_signals(db)` evaluates a candidate stock, the system
**shall** check whether any new DART disclosures were filed for that stock
since 15:20 KST of the signal generation day (i.e., after the signal was
created). **Where** a new disclosure exists since the cutoff, the system
**shall** classify the candidate's freshness as "fresh disclosure". The
disclosure lookup **shall** use the existing `Disclosure` model (`rcept_dt`
/ `created_at`) and **shall not** introduce a new external data source.

### REQ-AI031-003: 동종 섹터 선반영 점검

**When** `get_confirmed_signals(db)` evaluates a candidate stock, the system
**shall** check whether any companion stock in the same sector has already
moved significantly (defined as intraday change `> +5.0%` against the
previous close) at scan time. **If** a same-sector companion has already moved
`> +5.0%`, **then** the system **shall** record this as a "sector already
moved" condition for that candidate, surfaced in the candidate's confirmation
metadata so that `execute_buy_orders()` can account for chase-entry risk. The
sector move check **shall** reuse existing intraday change retrieval paths
(e.g., the helper used by SPEC-AI-027 group cascade detection) and **shall
not** add a new market data integration.

### REQ-AI031-004: 신선도 기반 confirmation_score 산출

The system **shall** compute, for each candidate, a confirmation score as
`confirmation_score = original_probability × freshness_multiplier`, where
`original_probability` is the candidate probability carried from
`get_today_signals()`. The `freshness_multiplier` **shall** be assigned as
follows:

- `1.0` **when** there is a new DART disclosure or fresh news for the stock
  since 15:20 KST of the signal day (REQ-AI031-002 "fresh disclosure").
- `0.8` **when** only the pre-existing (old) signal is present with no new
  disclosure/news since the cutoff.
- `0.5` **when** negative (bearish) news/disclosure has appeared overnight for
  the stock.

Additionally, **if** the original signal was created more than 20 hours before
scan time AND no new disclosure/news exists since 15:20, **then** the system
**shall** apply the "pre-open staleness filter" by treating the candidate as
the `0.8` (old-signal-only) tier or lower — the candidate's confidence
**shall** be reduced relative to a freshly-confirmed candidate. The bearish
classification **shall** reuse the disclosure sentiment convention established
in SPEC-AI-028 (`disclosure_sentiment == "bearish"`).

### REQ-AI031-005: execute_buy_orders 통합 및 후방 호환

**Where** `confirmation_scan.enabled` is `true` in `surge_detection.yaml` AND
`execute_buy_orders()` is invoked between 08:45 and 09:05 KST, the system
**shall** use `get_confirmed_signals(db)` (with `confirmation_score` as the
effective ranking/threshold probability) in place of `get_today_signals(db)`.
**If** `confirmation_scan.enabled` is `false`, **then** `execute_buy_orders()`
**shall** fall back to the existing `get_today_signals(db)` path with no
behavioral change. A new scheduler job `refresh_signal_confirmations()`
**shall** run at 08:45 KST on weekdays (mon-fri, `Asia/Seoul`) to populate the
confirmation scan results; **if** the 08:45 job is missed or fails, **then**
`execute_buy_orders()` **shall** still degrade gracefully to the
`get_today_signals()` fallback rather than blocking the 09:05 buy window.

---

## Configuration

`backend/app/surge_config/surge_detection.yaml` 의 `surge_detection:` 하위에
새 섹션 `confirmation_scan` 을 추가한다. 다른 섹션(`adaptive_threshold`,
`disclosure_type_filter`, `group_cascade` 등)과 동일하게 Pydantic 모델로
로드한다.

```yaml
surge_detection:
  # ... 기존 섹션 ...
  confirmation_scan:
    enabled: false                  # 기본 비활성 — 활성 시 08:45 재확인 스캔 사용
    scan_time: "08:45"              # KST, 개장 15분 전
    staleness_hours: 20             # 이 시간 초과 + 신규 뉴스 없으면 staleness 필터 적용
    sector_move_threshold: 5.0      # 동종 섹터 선반영 임계(전일비 %)
    freshness_multiplier_fresh: 1.0 # 신규 공시/뉴스 존재
    freshness_multiplier_stale: 0.8 # 구 시그널만 존재
    freshness_multiplier_bearish: 0.5  # 야간 악재 발생
```

> 기본값은 `enabled: false` 로, 본 SPEC 머지 직후에는 기존 동작이 유지된다.
> 운영 검증 후 사용자가 명시적으로 활성화한다.

---

## Implementation Scope (구현 범위 — 2~3 파일)

1. **`backend/app/services/surge_trading_service.py`**
   - 신규 함수 `get_confirmed_signals(db)` 추가 (REQ-AI031-001 ~ 004).
   - `execute_buy_orders()` 내부에 08:45~09:05 구간 + `confirmation_scan.enabled`
     조건부 분기 추가 (REQ-AI031-005). 비활성/구간 외에는 기존 경로 유지.
   - DART 신규 공시 조회(`Disclosure` 모델)와 동종 섹터 선반영 조회는 기존
     헬퍼(SPEC-AI-027 `_fetch_intraday_change_for_cascade` 등)를 재사용.

2. **`backend/app/services/scheduler.py`**
   - 신규 잡 `refresh_signal_confirmations()` 와 그 래퍼(`_run_refresh_...`)를
     추가하고 `add_job` 으로 08:45 KST (mon-fri, `Asia/Seoul`) 등록.
   - `surge_signal_generate`(15:20), `surge_execute_buys`(09:00~) 스케줄은
     **변경하지 않는다**.

3. **`backend/app/surge_config/surge_settings.py` + `surge_detection.yaml`**
   - `ConfirmationScanConfig` Pydantic 모델 정의 및 `surge_detection.yaml` 에
     `confirmation_scan` 섹션 추가 (Configuration 절 참조).

---

## Non-Goals (Exclusions — What NOT to Build)

본 SPEC 의 범위에서 **명시적으로 제외**되는 항목:

- **시그널 생성 파이프라인 변경 없음**. 15:20 KST 의
  `run_surge_signal_generation` / `surge_signal_generate` 잡은 로직·스케줄
  모두 그대로 유지한다.
- **신규 외부 데이터 소스 도입 없음**. DART 공시는 기존 `Disclosure` 모델을,
  섹터 선반영은 기존 인트라데이 가격 조회 헬퍼를 재사용한다. 새 API 연동을
  추가하지 않는다.
- **실시간(장중) 재확인 없음**. 본 SPEC 은 개장 직전 1회(08:45) 스캔만
  다룬다. 장중 연속 재평가는 별도 후속 SPEC 후보이다.
- **신규 뉴스 감성 분석 엔진 도입 없음**. bearish 판정은 SPEC-AI-028 의 기존
  `disclosure_sentiment` 규약을 재사용하며, 새 NLP 모델을 추가하지 않는다.
- **`execute_buy_orders()` 의 기타 인트라데이 필터(급락/과열/갭업 가드,
  섹터 한도, 포지션 한도) 변경 없음**. 본 SPEC 은 시그널 소스 교체와
  confirmation_score 부여까지만 다룬다.
- **적응형 임계값(SPEC-AI-029) 로직 변경 없음**. `confirmation_score` 는
  기존 임계값 비교에 들어가는 확률값을 대체할 뿐, 임계값 산출 방식은
  그대로 둔다.
- **백테스팅/A-B 테스트 하네스 구축 없음**. 신선도 배수의 효과 측정 인프라는
  별도 후속 SPEC 후보이다.

---

## Acceptance Summary (수용 기준 요약)

상세 Given-When-Then 시나리오는 `acceptance.md` 로 이연한다. 핵심 기준:

- `confirmation_scan.enabled: false` 일 때 `execute_buy_orders()` 의 동작이
  기존(`get_today_signals`)과 **완전히 동일**함을 회귀 테스트로 검증.
- 신규 공시가 있는 후보는 `freshness_multiplier == 1.0` 으로
  `confirmation_score == original_probability` 가 됨.
- 신규 공시가 없고 20시간 초과 경과한 후보는 `freshness_multiplier <= 0.8`
  으로 점수가 감점됨.
- 야간 bearish 공시 발생 후보는 `freshness_multiplier == 0.5` 로 강하게 감점됨.
- 08:45 잡 누락/실패 시 09:05 매수가 `get_today_signals` 폴백으로 정상 수행됨.

---

## References

### 코드 위치 (수정/추가 대상)

- `backend/app/services/surge_trading_service.py`
  `get_today_signals()`(L169~), `execute_buy_orders()`(L599~),
  `is_buy_eligible_hours()`(L122~) — 신규 `get_confirmed_signals()` 추가 및
  매수 분기 통합.
- `backend/app/services/scheduler.py`
  `surge_signal_generate`(15:20, L1448~), `surge_execute_buys`(L1462~) 인접
  위치에 `refresh_signal_confirmations`(08:45) 잡 추가.
- `backend/app/models/disclosure.py`
  `Disclosure.rcept_dt`(YYYYMMDD), `Disclosure.created_at` — 신규 공시 조회.
- `backend/app/services/surge_detector.py`
  `_fetch_intraday_change_for_cascade()`(L2058~) — 동종 섹터 선반영 조회 재사용.
- `backend/app/surge_config/surge_settings.py`,
  `backend/app/surge_config/surge_detection.yaml` —
  `ConfirmationScanConfig` 및 `confirmation_scan` 섹션.

### 선행 SPEC

- SPEC-AI-012: 급등예측 시그널 생성 파이프라인 (시그널 풀 입력).
- SPEC-AI-013: 급등예측 모의투자 포트폴리오 서비스 (매수 실행 / 스케줄 기반).
- SPEC-AI-021: `get_today_signals()` 4-tuple 반환 규약 (입력 형태 호환).
- SPEC-AI-027: 그룹 계열사 캐스케이드 탐지 (`_fetch_intraday_change_for_cascade`
  헬퍼 재사용).
- SPEC-AI-028: 공시 감성 분류 (`disclosure_sentiment == "bearish"` 규약 재사용).
- SPEC-AI-029: 적응형 급등 확률 임계값 (confirmation_score 가 비교 대상 확률을
  대체하되 임계값 산출은 불변).
