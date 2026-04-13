# SPEC-AI-007: Confidence Threshold Unification & Per-Model Accuracy Isolation

| Field       | Value                                                     |
|-------------|-----------------------------------------------------------|
| SPEC ID     | SPEC-AI-007                                               |
| Title       | Confidence Threshold Unification & Per-Model Accuracy     |
| Version     | 1.0.0                                                     |
| Status      | Planned                                                   |
| Created     | 2026-04-13                                                |
| Updated     | 2026-04-13                                                |
| Author      | Nexsol                                                    |
| Priority    | High                                                      |
| Issue Number | -                                                        |
| Lifecycle   | spec-anchored                                             |
| Related     | SPEC-AI-003, SPEC-AI-004, SPEC-AI-006                     |

---

## HISTORY

| Version | Date       | Author  | Description                |
|---------|------------|---------|----------------------------|
| 1.0.0   | 2026-04-13 | Nexsol  | 초기 SPEC 작성              |

---

## Overview

AI 펀드매니저의 confidence 임계값이 3개 레이어(프롬프트 지시, 코드 가드, 거래 실행)에 걸쳐 불일치하며, `get_accuracy_stats()` 함수가 모델 필터 없이 전체 모델의 적중률을 합산하여 gemini 프롬프트에 오염된 통계를 주입하고 있다. 이로 인해 gemini가 실제보다 낮은 적중률을 참조하여 과도한 hold 시그널을 생성하는 자기강화 루프가 발생하고 있다.

---

## Background

### 문제 1: Confidence 임계값 3중 불일치

| 레이어 | 파일 | 위치 | 현재 값 |
|--------|------|------|---------|
| 프롬프트 지시 | `fund_manager.py` | line 1684 | 0.7 |
| 코드 가드 | `fund_manager.py` | line 1707 `_MIN_ACTION_CONFIDENCE` | 0.45 |
| 거래 실행 | `paper_trading.py` | line 125 | 0.4 |
| Confidence floor | `fund_manager.py` | line 1815 `_CONFIDENCE_FLOOR` | 0.42 |

영향: gemini-2.5-flash가 confidence 0.55로 매수 시그널을 생성하면 코드 가드(0.45)와 거래 실행(0.4)은 통과하지만, 프롬프트에서 지시한 0.7에는 미달. 과거 "unknown" 모델은 평균 confidence 0.263으로 1,668건의 매수 시그널을 생성 -- 코드 가드가 없었기 때문.

### 문제 2: 모델 무관 적중률 통계 오염

`signal_verifier.py:329`의 `get_accuracy_stats(db, days=30)`에 `ai_model` 필터가 없음.

`fund_manager.py:1553`에서:
```python
accuracy = get_accuracy_stats(db, days=30)  # 모델 필터 없음
```

결과: gemini가 unknown 모델의 1,029건 검증 시그널(적중률 31.5%)에 오염된 통계를 참조. gemini 실제 적중률은 45.5%. "과거 시그널의 낮은 적중률" 추론으로 hold 시그널을 과다 생성하는 자기강화 루프 발생.

### 관찰된 결과
- 마지막 매수 시그널: 2026-04-06 (7일 이상 전)
- 포트폴리오: 2026-04-10부터 100% 현금
- KOSPI 알파: -6.62%, 포트폴리오 유휴 상태에서 계속 악화

---

## Requirements

### REQ-AI-007-001: Confidence 임계값 단일 상수 통일

**The system shall** export `MIN_ACTION_CONFIDENCE = 0.55` from a single location and use it consistently across all layers.

| 항목 | 현재 상태 | 목표 상태 |
|------|----------|----------|
| `_MIN_ACTION_CONFIDENCE` (fund_manager.py:1707) | 0.45 | `MIN_ACTION_CONFIDENCE` (0.55) 참조 |
| 거래 실행 임계값 (paper_trading.py:125) | 0.4 | `MIN_ACTION_CONFIDENCE - 0.05` (0.50) |
| `_CONFIDENCE_FLOOR` (fund_manager.py:1815) | 0.42 | `MIN_ACTION_CONFIDENCE` (0.55) 와 정합 |
| 프롬프트 텍스트 (fund_manager.py:1684) | "0.7 이상" | 실제 적용 임계값과 일치하도록 수정 |

### REQ-AI-007-002: get_accuracy_stats()에 ai_model 필터 추가

**When** `ai_model` 파라미터가 제공되면, **the system shall** `FundSignal` 레코드를 해당 `ai_model` 값으로 필터링하여 적중률 통계를 반환한다.

| 항목 | 현재 상태 | 목표 상태 |
|------|----------|----------|
| `get_accuracy_stats` 시그니처 | `(db, days=30)` | `(db, days=30, ai_model: str \| None = None)` |
| ai_model 지정 시 동작 | 전체 모델 합산 | 해당 모델만 필터링 |
| ai_model 미지정 시 동작 | 전체 모델 합산 | 변경 없음 (하위 호환) |

### REQ-AI-007-003: analyze_stock()에서 모델명 전달

**When** `analyze_stock()` 함수가 `get_accuracy_stats()`를 호출할 때, **the system shall** 현재 설정된 AI 모델명을 `ai_model` 파라미터로 전달한다.

| 항목 | 현재 상태 | 목표 상태 |
|------|----------|----------|
| `get_accuracy_stats` 호출 (fund_manager.py:1553) | `get_accuracy_stats(db, days=30)` | `get_accuracy_stats(db, days=30, ai_model="gemini-2.5-flash")` |
| 폴백 모델 사용 시 | 동일하게 모델 필터 없음 | 해당 폴백 모델명 전달 |

### REQ-AI-007-004: 최소 샘플 수 가드

**If** `ai_model` 필터 적용 후 검증된 시그널이 5건 미만이면, **then the system shall** 적중률 수치 대신 "데이터 부족 (N건)" 메시지를 표시한다.

| 항목 | 현재 상태 | 목표 상태 |
|------|----------|----------|
| 샘플 수 체크 | 없음 | 5건 미만 시 "데이터 부족 (N건)" 표시 |
| 1-2건 샘플 시 | 100% 또는 0% 표시 (신뢰도 낮음) | "데이터 부족" 경고 |

---

## Exclusions (What NOT to Build)

- 시그널 생성 로직 변경 (프롬프트 전면 재작성 등) -- 임계값 텍스트 수정만 범위 내
- VIP 포트폴리오 스냅샷 생성 기능 -- 별도 SPEC
- manual_audit_cleanup exit reason 정리 -- 별도 SPEC
- 포트폴리오 재진입 트리거 메커니즘 -- 별도 SPEC
- 새로운 AI 모델 추가 또는 모델 선택 로직 변경
- FundSignal 테이블 스키마 변경 (기존 `ai_model` 컬럼 활용)

---

## Files to Modify

| 파일 | 변경 내용 |
|------|----------|
| `backend/app/services/signal_verifier.py` | `get_accuracy_stats()`에 `ai_model` 파라미터 추가, 쿼리 필터링 |
| `backend/app/services/fund_manager.py` | `_MIN_ACTION_CONFIDENCE` 통일, `_CONFIDENCE_FLOOR` 정합, 프롬프트 임계값 텍스트 수정, `get_accuracy_stats()` 호출 시 모델명 전달 |
| `backend/app/services/paper_trading.py` | 거래 실행 임계값을 통일된 상수 참조로 변경 |

---

## Technical Notes

- `ai_model_used` 변수는 `_ask_ai_with_model()` 호출 후에 결정됨 (fund_manager.py:1692). `get_accuracy_stats()`는 그 이전에 호출됨 (line 1553). 따라서 설정된 primary 모델명을 기반으로 전달해야 함.
- `FundSignal` 모델에는 이미 `ai_model` 컬럼이 존재하므로 스키마 변경 불필요.
- 하위 호환성: `ai_model=None`일 때 기존 동작 유지.
