---
id: SPEC-AI-025
version: 0.2.0
status: implemented
created: 2026-05-29
updated: 2026-07-02
author: MoAI
priority: High
issue_number: 0
title: 테마 그룹 강세 carry-forward 시그널 (Theme Group Strength Carry-Forward)
---

# SPEC-AI-025: 테마 그룹 강세 carry-forward 시그널

## HISTORY

- 2026-05-29 (v0.1.0): 초안 작성. SPEC-AI-022가 도입한 `theme_propagation` 시그널은 surge_detector 앙상블이 **anchor 종목을 surge_candidate로 식별한 경우에만** 전파를 트리거한다. 그러나 2026-05-29 KST 라이브에서 LG전자(+29.93%), LG이노텍(+28.57%), LG(+26.60%) 3종이 동시에 +25% 이상 급등했음에도 같은 LG그룹 멤버인 LG씨엔에스(064400, +29.91%)와 솔루스첨단소재(336370, +25.70%)에 시그널이 발행되지 않았다. 원인은 (a) 앵커 자체의 `theme_cluster_score`가 `0.80` 임계값 미달로 propagation 트리거 조건을 충족하지 못했거나, (b) 앵커가 surge_candidate에 잡혔으나 propagation 단계의 `theme_cluster_score < 0.80` 조건에서 탈락한 경우다. 본 SPEC은 **앙상블 결과와 독립적으로 종가 강세를 기반으로 그룹 carry-forward를 트리거하는 end-of-day 보강 계층**을 추가한다. SPEC-AI-022는 intraday 앙상블 기반 전파, SPEC-AI-025는 EOD 종가 기반 carry-forward로 양자가 상호 보완한다.
- 2026-07-02 (v0.2.0, DDD 버그픽스): `detect_theme_group_carry_forward()` 구현이 본 SPEC 요구사항과 불일치하던 2건 수정 — (1) `surge_metadata` 키명을 `anchor_stock_id`/`anchor_change_rate`/`theme_group`에서 SPEC 요구 키명 `anchor_stock_code`/`anchor_change_pct`/`theme_group_id`/`theme_group_name`으로 정정(누락됐던 `theme_group_id` 신설 포함), (2) 완료 로그 포맷을 `"[theme_group_carry] 시그널 %d건 생성"`에서 SPEC 요구 포맷 `"[테마그룹강세] 평가 %d개 그룹, 시그널 %d건 생성"`(groups_evaluated 포함)으로 정정. 다운스트림 소비자는 테스트 파일 외 없음을 grep으로 확인 후 전면 교체(하위호환 키 병기 불필요). confidence 공식·max_signals_per_group·anchor 제외·크로스그룹 중복방지 로직은 이미 SPEC과 일치하여 무변경. status: planned → implemented.

---

## Overview

SPEC-AI-022 (`propagate_theme_group_signals`)는 `gather_surge_candidates()`가 식별한 후보군 중 anchor 종목이 `theme_cluster_score >= 0.80`을 받았을 때만 그룹 propagation을 트리거한다. 이는 다음 사각지대를 갖는다:

1. **앵커 자체의 앙상블 점수 부족**: anchor 종목이 +29% 급등했더라도 뉴스·공시 결합 부족으로 `theme_cluster_score`가 `0.80` 미만이면 propagation이 시작되지 않는다. 가격 정보 자체가 강한 시그널인 사례를 놓친다.
2. **EOD 관점 부재**: 현재 시스템은 intraday 9:05 batch 중심이다. 장 종료 후 종가가 확정된 상태에서 "오늘 그룹 앵커가 +5% 이상 마감했다"는 사실은 익일 추격 매수에 가치 있는 정보임에도, 종가 기반 carry-forward 메커니즘이 부재하다.
3. **SPEC-AI-022 propagation 누락 그룹 보완 부재**: SPEC-AI-022가 같은 영업일에 propagation을 발행했다면 본 SPEC은 중복 발행하지 않아야 한다. 반대로 SPEC-AI-022가 침묵했고 anchor가 종가 기준 강세라면 본 SPEC이 보완 신호를 발행해야 한다.

본 SPEC은 위 사각지대를 보정하는 **단일 backend-only 요구사항 3건**을 정의한다. 핵심 설계 원칙은 SPEC-AI-022와 동일하게 **기존 surge_candidate / theme_propagation 시그널 로직을 변경하지 않는 가법적(additive) 확장**이며, 신규 시그널은 `surge_basis: ["theme_group_carry"]`로 식별되어 별도 관측이 가능하다.

### Problem Background (2026-05-29 KST 실제 사례)

| 종목 | 코드 | 당일 등락 | 그룹 | SPEC-AI-022 propagation? | 원인 가설 |
|------|------|-----------|------|--------------------------|-----------|
| LG전자 | 066570 | +29.93% | LG그룹 anchor | (앵커 자신) | — |
| LG이노텍 | 011070 | +28.57% | LG그룹 | (앵커 자신, 별도) | — |
| LG | 003550 | +26.60% | LG그룹 | (앵커 자신, 별도) | — |
| LG씨엔에스 | 064400 | +29.91% | LG그룹 peer | **누락** | anchor의 `theme_cluster_score < 0.80` 추정 |
| 솔루스첨단소재 | 336370 | +25.70% | LG그룹 peer | **누락** | anchor의 `theme_cluster_score < 0.80` 추정 |

LG그룹의 3개 앵커가 동시에 +25% 이상 마감했다는 사실 자체는 **이론적으로 가장 강력한 그룹 강세 신호**이다. 그럼에도 앙상블 기반 propagation은 점수 임계값에 막혀 발화하지 않았다.

### Root Cause Analysis

1. **앙상블 점수와 종가 강세의 디커플링**: `theme_cluster_score`는 뉴스 클러스터 + 거래량 + 가격 모멘텀의 가중 합산이다. 종목이 +29% 마감했더라도 뉴스가 적으면 점수가 낮다. 종가 자체를 독립적인 강세 지표로 활용하는 별도 트리거가 필요하다.
2. **Intraday vs EOD 시점 차이**: SPEC-AI-022는 09:05 batch에서 실행되어 장중 데이터를 기반으로 한다. 본 SPEC은 장 마감 후 또는 익일 batch 시작 시점에 어제 종가를 활용하는 end-of-day 보강 계층이다. SPEC-AI-023(`detect_near_limit_up_carries`)와 유사하나, 그룹 단위 전파 로직을 추가한다.
3. **그룹 단위 강세 집계 부재**: 현재는 종목 단위 carry-forward(SPEC-AI-023)만 존재한다. "LG그룹 anchor가 +5% 이상 마감 → 같은 그룹 peer에게 carry 전파"라는 그룹 단위 cascade는 미구현이다.

본 SPEC은 위 3가지 원인을 보정한다. 신규 DB 마이그레이션은 없으며(SPEC-AI-022의 `theme_groups`/`stock_theme_groups` 재사용), `_run_coverage_expansion()`에 5번째 try/except 블록으로 통합된다.

### 전제 조건 (Assumptions)

- `theme_groups` 및 `stock_theme_groups` 테이블은 SPEC-AI-022 마이그레이션 037로 이미 존재한다. LG그룹·삼성그룹·현대차그룹·SK그룹 + 멤버 종목이 시드되어 있다.
- `ThemeGroup.anchor_stock_id`는 NULL 허용이며, 본 SPEC은 NULL인 그룹을 스킵한다(앵커 미정 그룹은 본 SPEC의 대상이 아님).
- `naver_finance.fetch_current_price_with_change_sync(code) -> dict | None`은 동기 호출 가능하며 `{"change_rate": float, ...}` 형식을 반환한다 (SPEC-AI-023에서 동일 함수를 사용).
- `FundSignal` 테이블은 `stock_id`, `signal`, `signal_type`, `confidence`, `reasoning`, `surge_metadata`(JSON), `paper_executed`, `created_at` 컬럼을 보유한다.
- `_run_coverage_expansion(db, surge_results)`은 surge_candidate 저장 완료 직후 호출되며, 내부에서 다음 4개의 보강 단계가 격리된 try/except로 실행된다: (1) 테마 전파, (2) 거래량 이상, (3) 상한가 근접 carry-forward. 본 SPEC은 5번째 단계(테마 그룹 강세 carry-forward)를 추가한다.
- 본 SPEC의 신규 시그널은 `signal_type="surge_candidate"`로 발행되며 `surge_basis: ["theme_group_carry"]` 메타데이터로 식별된다. `paper_executed=True`로 익일 매수 큐에 자동 포함된다. (이는 SPEC-AI-022의 `theme_propagation`과 다른 정책 — SPEC-AI-022는 관측 우선이었으나 본 SPEC은 종가 강세 기반이므로 실제 매수 가치가 더 높다.)
- 기존 API 계약(`POST /surge/execute`, `GET /surge/portfolio`, `GET /fund/signals`, `GET /api/surge-trading/coverage`)의 응답 스키마는 변경하지 않는다.

---

## EARS Requirements

### REQ-AI025-001: 테마 그룹 앵커 강세 감지 및 peer carry-forward 발행

**WHERE** `_run_coverage_expansion()` 실행 단계의 5번째 블록으로, the system SHALL `theme_groups` 테이블에 존재하는 모든 그룹을 순회하며 각 그룹의 `anchor_stock`이 NULL이 아닌 경우 anchor 종목의 당일 종가 변화율(`change_rate`)을 `fetch_current_price_with_change_sync(anchor.stock_code)`로 조회한다.

**WHERE** `ThemeGroup.anchor_stock_id`가 NULL인 그룹은, the system SHALL 본 단계에서 즉시 스킵한다(로그만 debug 레벨로 기록).

**WHEN** anchor 종목 가격 조회가 성공하고 `change_rate >= config.anchor_surge_min_pct`(기본 `5.0`%)일 때, the system SHALL 동일 그룹의 다른 멤버 종목(앵커 자신 제외) 각각에 대해 다음 조건을 모두 검사한다:
- (a) 당일 KST 00:00:00 이후 해당 peer 종목에 대한 `FundSignal`이 **`signal_type`을 가리지 않고** 부재하다. surge_candidate, theme_propagation, volume_anomaly, disclosure_impact 등 어떤 시그널도 없어야 한다.
- (b) peer 종목이 `stocks` 테이블에 존재한다.

**IF** 조건 (a)와 (b)가 모두 충족되면, **then** the system SHALL `signal_type="surge_candidate"`의 신규 `FundSignal` 레코드를 다음 값으로 생성한다:
- `confidence = round(anchor_change_rate / 30.0 * 0.4, 4)` (앵커 등락률 비례 confidence, 최댓값 `0.40` — anchor가 +30%이면 0.40)
- `signal = "buy"` (NOT NULL 제약 준수)
- `reasoning` = `f"[SPEC-AI-025] 테마그룹 강세 carry-forward — {group.name} 앵커 {anchor.name}({anchor.stock_code}) {anchor_change_rate:.2f}% 마감"`
- `paper_executed = True` (익일 매수 큐에 자동 포함 — SPEC-AI-023과 동일 정책)
- `surge_metadata` JSON(`json.dumps(..., ensure_ascii=False)`):
  ```json
  {
    "surge_basis": ["theme_group_carry"],
    "anchor_stock_code": "<anchor.stock_code>",
    "anchor_change_pct": <round(anchor_change_rate, 2)>,
    "theme_group_id": <group.id>,
    "theme_group_name": "<group.name>"
  }
  ```

**WHEN** 같은 그룹 내 carry-forward 시그널 발행 개수가 `config.max_signals_per_group`(기본 `5`)에 도달할 때, the system SHALL 해당 그룹의 추가 peer 평가를 중단하고 다음 그룹으로 진행한다.

**WHERE** anchor 종목 자체는, the system SHALL carry-forward 대상에서 제외한다(자기 자신에 대한 중복 발행 방지).

**WHEN** 동일 peer 종목이 복수 그룹(예: 삼성SDI가 "삼성그룹"과 "2차전지 밸류체인" 양쪽 멤버)의 carry-forward 후보일 때, the system SHALL 그룹 순회 순서대로 처리하되, **이미 본 SPEC 실행 중에 peer에 시그널을 발행했다면 추가 발행을 스킵한다**. 결과적으로 동일 peer는 본 SPEC 실행 1회당 최대 1건의 시그널만 받는다.

**WHEN** anchor의 `change_rate < config.anchor_surge_min_pct`이거나 가격 조회가 실패할 때, the system SHALL 해당 그룹을 스킵한다(에러를 발생시키지 않음, debug 로그만 기록).

**WHERE** 본 단계 전체는, the system SHALL `_run_coverage_expansion()` 내부의 별도 try/except 블록으로 격리되며, 예외 발생 시 로그만 기록하고 surge_candidate / theme_propagation / volume_anomaly / near_limit_up 단계의 결과를 손상시키지 않는다.

**WHEN** 본 단계가 완료될 때, the system SHALL 평가한 그룹 수와 생성된 시그널 수를 INFO 레벨로 로깅한다 (`logger.info("[테마그룹강세] 평가 %d개 그룹, 시그널 %d건 생성", groups_evaluated, total_created)`).

`[NEW]` `backend/app/services/surge_detector.py` — `detect_theme_group_carry_forward(db, config) -> list[FundSignal]` 신규 함수
`[MODIFY]` `backend/app/services/fund_manager.py` — `_run_coverage_expansion()` 내부에 5번째 try/except 블록 추가하여 `detect_theme_group_carry_forward()` 호출

---

### REQ-AI025-002: 설정 클래스 정의

**WHERE** 본 기능의 토글 및 임계값을 운영 가능하게 하기 위해, the system SHALL `backend/app/surge_config/surge_settings.py`에 `ThemeGroupCarryConfig(BaseModel)` 신규 Pydantic 클래스를 정의한다.

**WHEN** 클래스가 정의될 때, the system SHALL 다음 필드를 갖는다:
- `enabled: bool = True` — 기능 활성화 토글
- `anchor_surge_min_pct: float = 5.0` — anchor 등락률 최소 임계값 (%)
- `max_signals_per_group: int = 5` — 그룹별 최대 발행 시그널 수

**WHERE** `SurgeDetectionConfig`에 본 클래스를 필드로 통합할지 여부는, the system SHALL 본 SPEC 범위에 포함하지 않는다. `_run_coverage_expansion()`은 `ThemeGroupCarryConfig()`를 직접 인스턴스화하여 기본값으로 사용한다(SPEC-AI-023의 `NearLimitUpConfig()` 패턴과 동일).

`[MODIFY]` `backend/app/surge_config/surge_settings.py` — `ThemeGroupCarryConfig` 클래스 추가

---

### REQ-AI025-003: `_run_coverage_expansion()` 통합

**WHERE** `_run_coverage_expansion()`의 기존 4개 try/except 블록(테마 전파, 거래량 이상, 상한가 근접 carry-forward)에 이어, the system SHALL 5번째 try/except 블록을 추가하여 `detect_theme_group_carry_forward()`를 호출한다.

**WHEN** 5번째 블록이 실행될 때, the system SHALL 다음 구조를 따른다:

```python
# 4. SPEC-AI-025: 테마 그룹 강세 carry-forward
try:
    from app.services.surge_detector import detect_theme_group_carry_forward
    from app.surge_config.surge_settings import ThemeGroupCarryConfig
    tgc_cfg = ThemeGroupCarryConfig()
    tgc_signals = detect_theme_group_carry_forward(db, tgc_cfg)
    logger.info("[테마그룹강세] 완료 — %d건", len(tgc_signals))
except Exception as e:
    logger.error("[테마그룹강세] 예외 발생: %s", e, exc_info=True)
```

**WHERE** 본 블록은, the system SHALL 4번째 블록(`detect_near_limit_up_carries`) 직후에 위치한다. 순서는 의미가 있으며, near_limit_up_carry가 먼저 발행한 시그널이 있는 peer는 본 SPEC의 (a) 조건(시그널 부재)에 의해 자동 제외된다.

**WHERE** `ThemeGroupCarryConfig.enabled == False`인 경우, the system SHALL `detect_theme_group_carry_forward()`가 즉시 빈 리스트를 반환하도록 함수 본체 진입 직후에 가드 분기를 둔다.

`[MODIFY]` `backend/app/services/fund_manager.py` — `_run_coverage_expansion()` 함수 본체에 5번째 try/except 블록 추가

---

## Acceptance Criteria

각 요구사항별 검증 가능한 인수 기준. 모든 테스트는 신규 파일 또는 기존 테스트 파일에 추가한다. 외부 의존성(`fetch_current_price_with_change_sync`, DB)은 mock으로 격리한다.

### AC-001: anchor +8% → group peers 시그널 생성, confidence ≈ 0.107 (REQ-AI025-001)

**Given**:
- DB에 `ThemeGroup(id=1, name="LG그룹", anchor_stock_id=lg_elec.id)` 존재
- LG전자(066570, anchor), LG씨엔에스(064400, peer), 솔루스첨단소재(336370, peer)가 모두 LG그룹 멤버
- `fetch_current_price_with_change_sync("066570")` mock 반환: `{"change_rate": 8.0}`
- LG씨엔에스, 솔루스첨단소재에 대한 당일 `FundSignal` 부재 (모든 signal_type)
- `ThemeGroupCarryConfig(enabled=True, anchor_surge_min_pct=5.0, max_signals_per_group=5)`

**When**: `detect_theme_group_carry_forward(db, config)` 호출

**Then**:
- LG씨엔에스에 대해 시그널 1건 생성, `signal_type="surge_candidate"`, `confidence=round(8.0/30.0*0.4, 4)=0.1067`, `paper_executed=True`
- 솔루스첨단소재에 대해 동일 confidence로 시그널 1건 생성
- LG전자(앵커 자신)에 대해서는 시그널 미생성
- 각 시그널의 `surge_metadata` JSON에 `surge_basis=["theme_group_carry"]`, `anchor_stock_code="066570"`, `anchor_change_pct=8.0`, `theme_group_id=1`, `theme_group_name="LG그룹"` 포함
- 함수 반환값 `len(result) == 2`
- 로그에 `"[테마그룹강세] 평가 1개 그룹, 시그널 2건 생성"` 포함

### AC-002: anchor +3% (미달) → 생성 안 함 (REQ-AI025-001)

**Given**:
- AC-001과 동일한 그룹 설정
- `fetch_current_price_with_change_sync("066570")` mock 반환: `{"change_rate": 3.0}`
- `anchor_surge_min_pct = 5.0`

**When**: `detect_theme_group_carry_forward(db, config)` 호출

**Then**:
- 시그널 0건 생성
- 함수 반환값 `len(result) == 0`
- debug 로그에 anchor 미충족 메시지

### AC-003: 이미 시그널 있는 peer → 스킵 (REQ-AI025-001)

**Given**:
- AC-001과 동일한 그룹 설정 + anchor +8% mock
- LG씨엔에스에 대한 당일 `signal_type="theme_propagation"` 시그널이 이미 존재 (SPEC-AI-022가 발행)
- 솔루스첨단소재에 대해서는 당일 시그널 부재

**When**: `detect_theme_group_carry_forward(db, config)` 호출

**Then**:
- LG씨엔에스에 대해서는 시그널 미생성 (이미 존재 — signal_type 무관)
- 솔루스첨단소재에 대해서는 시그널 1건 생성
- 함수 반환값 `len(result) == 1`

### AC-004: anchor_stock_id == NULL → 해당 그룹 스킵 (REQ-AI025-001)

**Given**:
- DB에 `ThemeGroup(id=99, name="미정그룹", anchor_stock_id=None)` 존재
- 다른 정상 그룹은 모두 비어있음 또는 anchor 미달

**When**: `detect_theme_group_carry_forward(db, config)` 호출

**Then**:
- 시그널 0건 생성
- 함수 반환값 `len(result) == 0`
- `fetch_current_price_with_change_sync` 호출 0회 (mock assert)
- debug 로그에 "anchor 미설정 그룹 스킵" 메시지

### AC-005: 가격 API 예외 발생 시 다른 그룹 계속 처리 (REQ-AI025-001)

**Given**:
- LG그룹(anchor=LG전자, +8% mock), 삼성그룹(anchor=삼성전자, +6% mock) 두 그룹 존재
- `fetch_current_price_with_change_sync("066570")` mock이 `Exception("API timeout")` 발생
- `fetch_current_price_with_change_sync("005930")` mock이 `{"change_rate": 6.0}` 반환
- LG씨엔에스(LG그룹 peer), 삼성SDI(삼성그룹 peer)에 당일 시그널 부재

**When**: `detect_theme_group_carry_forward(db, config)` 호출

**Then**:
- LG그룹은 anchor 가격 조회 실패로 스킵 (peer 시그널 0건)
- 삼성그룹은 정상 처리 (peer 시그널 ≥1건)
- 함수 반환값 `len(result) >= 1` (삼성그룹 분)
- 함수 본체는 예외를 raise하지 않음
- 로그에 LG그룹 가격 조회 실패 경고

### AC-006: max_signals_per_group 도달 시 추가 발행 중단 (REQ-AI025-001)

**Given**:
- LG그룹에 anchor=LG전자 + peer 8종 등록 (총 9개 멤버)
- anchor mock `{"change_rate": 8.0}` (≥ 5%)
- 모든 peer에 당일 시그널 부재
- `max_signals_per_group = 5`

**When**: `detect_theme_group_carry_forward(db, config)` 호출

**Then**:
- LG그룹에서 5건의 시그널만 생성 (peer 처리 순서대로 상위 5건)
- 나머지 3개 peer는 미발행
- 함수 반환값 `len(result) == 5`
- 다음 그룹이 있다면 정상 진행 (max는 그룹별 한도)

### AC-007: 동일 peer가 복수 그룹 멤버일 때 1회만 발행 (REQ-AI025-001)

**Given**:
- LG그룹(anchor=LG전자, +8% mock), 2차전지밸류체인(anchor=LG에너지솔루션 또는 다른 그룹, +6% mock) 두 그룹
- LG화학이 두 그룹 모두 멤버로 등록
- LG화학에 당일 시그널 부재

**When**: `detect_theme_group_carry_forward(db, config)` 호출

**Then**:
- LG화학에 대해 시그널 1건만 생성 (그룹 순회 순서상 먼저 등장한 그룹)
- 동일 peer 중복 발행 방지 보장

### AC-008: ThemeGroupCarryConfig.enabled == False 시 즉시 종료 (REQ-AI025-002)

**Given**:
- 그룹 다수 존재, anchor 강세 다수 존재 (정상 시나리오)
- `ThemeGroupCarryConfig(enabled=False)`

**When**: `detect_theme_group_carry_forward(db, config)` 호출

**Then**:
- 함수 반환값 `len(result) == 0`
- DB 쿼리 0회 발생 (mock assert)
- `fetch_current_price_with_change_sync` 호출 0회

### AC-009: `_run_coverage_expansion` 통합 — 예외 시 다른 단계 무영향 (REQ-AI025-003)

**Given**:
- `_run_coverage_expansion()`이 호출되어 4단계(propagation, volume_anomaly, near_limit_up) 정상 완료
- `detect_theme_group_carry_forward`가 내부에서 예외 발생 (mock)

**When**: `_run_coverage_expansion(db, surge_results)` 호출 완료

**Then**:
- propagation, volume_anomaly, near_limit_up 단계 결과는 정상 보존 (DB에 시그널 존재)
- 5번째 블록의 예외는 로그만 출력 (`logger.error("[테마그룹강세] 예외 발생: ...")`)
- `_run_coverage_expansion()` 자체는 정상 종료 (예외 외부로 전파 안 됨)

### AC-010: paper_executed=True로 익일 매수 큐 자동 포함 확인 (Cross-cutting)

**Given**:
- 본 SPEC이 발행한 시그널 1건 (`signal_type="surge_candidate"`, `paper_executed=True`)
- `surge_trading_service.get_today_signals(db, min_probability=Decimal("0.10"))` 호출

**Then**:
- 반환된 list에 본 SPEC 시그널이 포함됨 (signal_type 필터 + confidence 통과)
- 실제 매수 실행 단계(`execute_buy_orders`)에서 정상 평가됨
- 단, `confidence >= min_probability` 조건에 따라 anchor +5% (confidence=0.067)는 제외, anchor +8% (confidence=0.107)는 포함

---

## Implementation Notes

### 신규 함수 시그니처

```python
# surge_detector.py
def detect_theme_group_carry_forward(
    db: Session,
    config: "ThemeGroupCarryConfig",  # noqa: F821
) -> list[FundSignal]:
    """SPEC-AI-025: 테마 그룹 anchor 강세 기반 익일 carry-forward 시그널 발행."""
```

### Pydantic 설정 클래스 추가 (surge_settings.py)

```python
class ThemeGroupCarryConfig(BaseModel):
    """SPEC-AI-025: 테마 그룹 강세 carry-forward 설정."""

    enabled: bool = True
    # anchor 등락률 최소 임계값 (%)
    anchor_surge_min_pct: float = 5.0
    # 그룹별 최대 발행 시그널 수
    max_signals_per_group: int = 5
```

### fund_manager._run_coverage_expansion 5번째 블록

```python
# 4. SPEC-AI-025: 테마 그룹 강세 carry-forward
try:
    from app.services.surge_detector import detect_theme_group_carry_forward
    from app.surge_config.surge_settings import ThemeGroupCarryConfig
    tgc_cfg = ThemeGroupCarryConfig()
    tgc_signals = detect_theme_group_carry_forward(db, tgc_cfg)
    logger.info("[테마그룹강세] 완료 — %d건", len(tgc_signals))
except Exception as e:
    logger.error("[테마그룹강세] 예외 발생: %s", e, exc_info=True)
```

### 함수 본체 의사 코드

```python
def detect_theme_group_carry_forward(db, config) -> list[FundSignal]:
    import json as _json
    from zoneinfo import ZoneInfo
    from app.models.fund_signal import FundSignal
    from app.models.stock import Stock
    from app.models.theme_group import ThemeGroup, StockThemeGroup
    from app.services.naver_finance import fetch_current_price_with_change_sync

    if not config.enabled:
        return []

    KST = ZoneInfo("Asia/Seoul")
    signals: list[FundSignal] = []
    groups_evaluated = 0

    try:
        today_kst_start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
        today_utc_start = today_kst_start.astimezone(timezone.utc)

        # 오늘 이미 시그널 있는 stock_id 집합 (signal_type 불문)
        existing_ids: set[int] = set(
            row[0] for row in (
                db.query(FundSignal.stock_id)
                .filter(FundSignal.created_at >= today_utc_start)
                .distinct()
                .all()
            )
        )

        # 본 SPEC 실행 중 이미 발행한 peer 추적 (중복 방지)
        emitted_in_this_run: set[int] = set()

        # 모든 그룹 순회
        all_groups = db.query(ThemeGroup).all()

        for group in all_groups:
            if group.anchor_stock_id is None:
                logger.debug("[테마그룹강세] %s 그룹 anchor 미설정, 스킵", group.name)
                continue

            anchor = db.query(Stock).filter(Stock.id == group.anchor_stock_id).first()
            if anchor is None:
                continue

            groups_evaluated += 1

            try:
                price_data = fetch_current_price_with_change_sync(anchor.stock_code)
            except Exception as e:
                logger.warning("[테마그룹강세] %s 가격 조회 실패: %s", anchor.stock_code, e)
                continue

            if price_data is None:
                continue

            anchor_change_rate: float = price_data.get("change_rate", 0.0)
            if anchor_change_rate < config.anchor_surge_min_pct:
                logger.debug(
                    "[테마그룹강세] %s anchor %.2f%% (임계 %.1f%%) 미달",
                    group.name, anchor_change_rate, config.anchor_surge_min_pct,
                )
                continue

            # 그룹 내 peer 조회 (anchor 제외)
            peers = (
                db.query(Stock)
                .join(StockThemeGroup, StockThemeGroup.stock_id == Stock.id)
                .filter(
                    StockThemeGroup.theme_group_id == group.id,
                    Stock.id != anchor.id,
                )
                .all()
            )

            signals_in_group = 0
            confidence = round(anchor_change_rate / 30.0 * 0.4, 4)
            metadata = {
                "surge_basis": ["theme_group_carry"],
                "anchor_stock_code": anchor.stock_code,
                "anchor_change_pct": round(anchor_change_rate, 2),
                "theme_group_id": group.id,
                "theme_group_name": group.name,
            }

            for peer in peers:
                if signals_in_group >= config.max_signals_per_group:
                    break
                if peer.id in existing_ids or peer.id in emitted_in_this_run:
                    continue

                reasoning = (
                    f"[SPEC-AI-025] 테마그룹 강세 carry-forward — "
                    f"{group.name} 앵커 {anchor.name}({anchor.stock_code}) "
                    f"{anchor_change_rate:.2f}% 마감"
                )

                signal = FundSignal(
                    stock_id=peer.id,
                    signal="buy",
                    signal_type="surge_candidate",
                    confidence=confidence,
                    reasoning=reasoning,
                    surge_metadata=_json.dumps(metadata, ensure_ascii=False),
                    paper_executed=True,
                )
                db.add(signal)
                signals.append(signal)
                emitted_in_this_run.add(peer.id)
                signals_in_group += 1

        if signals:
            db.commit()

        logger.info(
            "[테마그룹강세] 평가 %d개 그룹, 시그널 %d건 생성",
            groups_evaluated, len(signals),
        )

    except Exception as e:
        logger.error("[테마그룹강세] 예외 발생: %s", e, exc_info=True)
        return []

    return signals
```

### @MX Tag 계획

- `detect_theme_group_carry_forward()`: `@MX:ANCHOR` (fan_in 예상 1, fund_manager._run_coverage_expansion에서만 호출하지만 핵심 진입점), `@MX:SPEC: SPEC-AI-025 REQ-001`, `@MX:REASON`: 그룹별 anchor 가격 조회 + peer 시그널 발행 복합 로직, 외부 API 호출 포함.
- `ThemeGroupCarryConfig`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-025 REQ-002`.
- `_run_coverage_expansion` 5번째 블록: 인라인 주석 `# @MX:NOTE: [AUTO] SPEC-AI-025 테마 그룹 강세 carry-forward 단계`.

### 테스트 전략

- `backend/tests/test_theme_group_carry.py` (신규) — REQ-AI025-001, REQ-AI025-002 (AC-001~AC-008)
- `backend/tests/test_coverage_expansion_integration.py` (확장, 또는 기존 통합 테스트 파일에 추가) — REQ-AI025-003, Cross-cutting (AC-009, AC-010)
- `fetch_current_price_with_change_sync` mock 주입 (SPEC-AI-023 테스트 패턴 재사용)
- SQLite in-memory DB에 ThemeGroup + Stock + StockThemeGroup 시드 후 검증
- 목표 coverage: 신규 함수 90%+, 수정된 `_run_coverage_expansion` 85%+

### 운영 고려사항

- 그룹당 anchor 가격 API 호출 1회 + peer 멤버 수만큼의 DB INSERT. 4개 그룹 × 1회 = 4회 API 호출 / 일. 부담 미미.
- 5단계가 순차 실행되며, 본 SPEC은 마지막 단계로서 앞선 단계의 시그널 발행 후 잔여 peer만 평가한다.
- anchor가 +5% 이상 마감했는데 peer가 모두 (a) 조건에 걸려 시그널을 받지 못하는 경우(이미 다른 시그널 보유)는 정상 동작이며 0건 발행으로 처리한다.
- `surge_basis: ["theme_group_carry"]` 메타데이터로 SPEC-AI-022의 `theme_propagation`과 명확히 구분되어 추후 적중률 분석 가능.

---

## Exclusions (What NOT to Build)

- **SPEC-AI-022의 `propagate_theme_group_signals` 로직 변경**: 본 SPEC은 완전히 독립적인 함수 추가. SPEC-AI-022 코드 무변경.
- **SPEC-AI-023의 `detect_near_limit_up_carries` 로직 변경**: 본 SPEC은 다른 함수. SPEC-AI-023 코드 무변경.
- **신규 DB 마이그레이션**: `theme_groups`/`stock_theme_groups` 테이블은 SPEC-AI-022 마이그레이션 037을 재사용. ALTER TABLE 금지.
- **신규 signal_type 도입**: 본 SPEC은 `signal_type="surge_candidate"`를 재사용하고 `surge_basis: ["theme_group_carry"]`로 구분. 신규 signal_type 값(예: `theme_group_carry`) 도입 금지 — 익일 매수 큐와의 통합 단순성을 위해.
- **`get_today_signals` 함수 변경**: 본 SPEC 시그널은 `signal_type="surge_candidate"`이므로 자동으로 큐에 포함됨. 함수 코드 변경 불필요.
- **anchor 점수 0.80 임계값 변경**: SPEC-AI-022의 `anchor_score_threshold = 0.80`은 손대지 않음. 본 SPEC은 종가 기반의 별개 트리거.
- **`SurgeDetectionConfig`에 `ThemeGroupCarryConfig` 통합**: 본 SPEC은 NearLimitUpConfig 패턴을 따라 `_run_coverage_expansion()`에서 직접 인스턴스화. YAML 로더 변경 불필요.
- **anchor 후보 다중화**: 한 그룹은 1개의 `anchor_stock`만 사용 (현재 스키마 제약). 복수 anchor 평가는 본 SPEC 범위 외 (`stock_theme_groups`의 모든 멤버를 anchor 후보로 평가하는 확장은 후속 SPEC).
- **peer 종목별 가격 조회**: 본 SPEC은 anchor 가격만 조회. peer 가격 조회는 부담 + recent_surge_penalty 등 추가 로직이 필요하므로 미포함. (SPEC-AI-022가 5일 트렌드 페널티를 이미 갖고 있으나, 본 SPEC은 anchor 종가 강세만으로 판단.)
- **2단계 cascade (peer → peer'의 추가 전파)**: anchor → peer 한 단계만. SPEC-AI-022와 동일 정책.
- **신규 그룹 시드 데이터**: 4개 재벌 그룹(LG/삼성/현대차/SK)은 SPEC-AI-022 마이그레이션 037이 이미 시드. 본 SPEC은 추가 그룹 시드 안 함.
- **frontend 변경**: backend-only SPEC. UI 표시는 별도 작업.
- **`POST /api/surge-trading/coverage/refresh` 등 새 엔드포인트**: 본 SPEC은 시그널 생성 로직만. 관측은 SPEC-AI-022의 coverage 엔드포인트가 이미 `by_signal_type`로 집계하므로 추가 변경 불필요.
- **`paper_executed=False` 옵션**: 본 SPEC은 항상 `paper_executed=True` (익일 매수 큐 포함). 관측 전용 모드는 별도 SPEC.
- **본 SPEC 시그널의 적중률 분석/검증 로직**: 시그널 생성만. 가격 후속 추적은 별도 SPEC.
- **anchor 등락률 음수(하락) 처리**: 본 SPEC은 `change_rate >= +5.0%`만 대상. 그룹 약세 carry-forward(매도 신호)는 범위 외.

---

## Delta Markers Summary

| Marker | File | Requirements |
|--------|------|--------------|
| `[NEW]` | `backend/app/services/surge_detector.py` (추가 함수) | REQ-AI025-001 |
| `[MODIFY]` | `backend/app/services/fund_manager.py` (`_run_coverage_expansion`에 블록 추가) | REQ-AI025-003 |
| `[MODIFY]` | `backend/app/surge_config/surge_settings.py` (`ThemeGroupCarryConfig` 추가) | REQ-AI025-002 |
| `[NEW]` | `backend/tests/test_theme_group_carry.py` | AC-001~AC-008 |
| `[MODIFY/NEW]` | `backend/tests/test_coverage_expansion_integration.py` | AC-009, AC-010 |

---

## Related SPECs

- **SPEC-AI-022** (선행, 필수): 테마 전파 시그널 — `theme_groups`/`stock_theme_groups` 스키마, `propagate_theme_group_signals` 함수 도입. 본 SPEC은 동일 스키마를 재사용하며 anchor 점수 부족 사각지대를 보완한다.
- **SPEC-AI-023** (선행, 패턴 reference): 상한가 근접 carry-forward — `detect_near_limit_up_carries` 함수와 `NearLimitUpConfig` 패턴. 본 SPEC은 종가 기반 carry-forward 패턴을 그룹 단위로 확장.
- **SPEC-AI-018** (관련): 시장 레짐 분류와 recent_surge_penalty — peer 5일 수익률 페널티 정책. 본 SPEC은 anchor 종가만으로 판단하므로 직접 의존하지 않음.
- **SPEC-AI-021** (관련): 손절 후 회복 confidence_boost — surge_trading_service 단의 보정. 본 SPEC 시그널도 `signal_type="surge_candidate"`로 발행되므로 SPEC-AI-021의 부스트 대상에 자동 포함.
- **SPEC-AI-012** (배경): 급등 징후 탐지 — surge_detector 4개 탐지기. 본 SPEC은 surge_detector.py에 5번째 entry function을 추가하나 기존 탐지기는 변경하지 않음.

---

## Verification Checklist

- [ ] 모든 EARS 요구사항이 검증 가능한 인수 기준을 가진다 (AC-001 ~ AC-010)
- [ ] 신규 DB 마이그레이션 없음 확인 (SPEC-AI-022의 037 재사용)
- [ ] 기존 `propagate_theme_group_signals`, `detect_near_limit_up_carries` 함수 무변경 확인
- [ ] `_run_coverage_expansion()`의 기존 4개 try/except 블록 무변경, 5번째 블록만 추가
- [ ] 신규 시그널의 `signal_type="surge_candidate"`로 `get_today_signals` 자동 통합
- [ ] `paper_executed=True` 정책 명시 (익일 매수 큐 포함)
- [ ] `surge_basis: ["theme_group_carry"]` 메타데이터로 SPEC-AI-022 `theme_propagation`과 구분
- [ ] try/except 격리로 다른 단계 결과 보존 보장
- [ ] mock 기반 격리 테스트로 외부 API(`fetch_current_price_with_change_sync`) 차단
- [ ] target coverage 85%+ 명시, 신규 함수 90%+
- [ ] @MX 태그 계획 포함 (ANCHOR/NOTE/SPEC)
- [ ] 동일 peer 중복 발행 방지 로직 명시 (`emitted_in_this_run` set)
- [ ] `anchor_stock_id=None` 그룹 안전 스킵 보장
