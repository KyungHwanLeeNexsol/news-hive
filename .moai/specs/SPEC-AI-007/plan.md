# SPEC-AI-007 Implementation Plan

## Technical Approach

### Milestone 1: Confidence 임계값 통일 (Priority: High)

**단계 1.1**: `fund_manager.py`에서 `MIN_ACTION_CONFIDENCE = 0.55`를 모듈 레벨 상수로 정의하고, 기존 `_MIN_ACTION_CONFIDENCE`를 이 상수로 대체.

**단계 1.2**: `paper_trading.py`의 실행 임계값을 `MIN_ACTION_CONFIDENCE - 0.05` (0.50)로 변경. fund_manager.py에서 import하거나 동일한 상수 참조 패턴 사용.

**단계 1.3**: `_CONFIDENCE_FLOOR`를 `MIN_ACTION_CONFIDENCE`와 정합되도록 조정 (0.55 또는 제거).

**단계 1.4**: 프롬프트 텍스트에서 "0.7 이상" 표현을 실제 적용 임계값과 일치하도록 수정.

### Milestone 2: get_accuracy_stats() ai_model 필터 (Priority: High)

**단계 2.1**: `signal_verifier.py`의 `get_accuracy_stats()` 시그니처에 `ai_model: str | None = None` 파라미터 추가.

**단계 2.2**: `ai_model`이 지정되었을 때 `FundSignal` 쿼리에 `.filter(FundSignal.ai_model == ai_model)` 조건 추가.

**단계 2.3**: 최소 샘플 수 가드 구현 -- 검증된 시그널 5건 미만 시 적중률 대신 "데이터 부족 (N건)" 반환.

### Milestone 3: analyze_stock() 모델명 전달 (Priority: High)

**단계 3.1**: `fund_manager.py`의 `analyze_stock()` 내에서 primary 모델명을 결정하는 로직 확인.

**단계 3.2**: `get_accuracy_stats(db, days=30, ai_model=primary_model_name)` 형태로 호출 수정.

**단계 3.3**: 폴백 모델 사용 시에도 올바른 모델명이 전달되는지 확인.

---

## Risks

| 리스크 | 영향 | 완화 전략 |
|--------|------|----------|
| 임계값 인상으로 시그널 수 급감 | 매수 기회 감소 | 0.55는 gemini 평균 confidence(0.55 근처)와 정합 -- 급격한 감소 없을 것 |
| 기존 `get_accuracy_stats` 호출처 영향 | 하위 호환 깨짐 | `ai_model=None` 기본값으로 하위 호환 보장 |
| 모델명 하드코딩 | 모델 변경 시 수동 수정 필요 | config에서 모델명을 읽는 것이 이상적이나, 현재 scope에서는 단순 전달로 충분 |
| 최소 샘플 가드가 정보 부족 초래 | AI가 충분한 맥락 없이 판단 | 5건 미만 시 "데이터 부족"으로 명시, AI가 자체 판단하도록 유도 |

---

## Dependencies

- `FundSignal` 모델의 `ai_model` 컬럼 존재 확인 (SPEC-AI-004에서 추가됨)
- `signal_verifier.py`의 `get_accuracy_stats()` 함수 구조 이해
- `fund_manager.py`의 `analyze_stock()` 호출 흐름 이해

---

## Implementation Order

1. `signal_verifier.py` -- `get_accuracy_stats()` 수정 (의존성 없음, 하위 호환)
2. `fund_manager.py` -- 상수 통일 + 호출 수정 + 프롬프트 수정
3. `paper_trading.py` -- 실행 임계값 수정
