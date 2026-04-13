# SPEC-AI-007 Acceptance Criteria

## Scenario 1: Confidence 임계값 일관성

**Given** SPEC-AI-007이 구현된 상태에서
**When** `fund_manager.py`의 `_MIN_ACTION_CONFIDENCE`와 `paper_trading.py`의 실행 임계값을 비교하면
**Then** 두 값의 차이는 0.05 이내여야 한다

**Given** SPEC-AI-007이 구현된 상태에서
**When** `fund_manager.py`의 프롬프트 텍스트에서 confidence 임계값을 확인하면
**Then** 프롬프트에 명시된 값과 코드 가드 값의 차이는 0.10 이내여야 한다

---

## Scenario 2: 모델별 적중률 분리

**Given** DB에 gemini-2.5-flash 시그널 20건, unknown 모델 시그널 100건이 존재할 때
**When** `get_accuracy_stats(db, days=30, ai_model="gemini-2.5-flash")`를 호출하면
**Then** 반환된 통계는 gemini-2.5-flash 시그널 20건만 기반으로 계산되어야 한다

**Given** DB에 gemini-2.5-flash 시그널 20건, unknown 모델 시그널 100건이 존재할 때
**When** `get_accuracy_stats(db, days=30, ai_model=None)`를 호출하면
**Then** 반환된 통계는 전체 120건 기반으로 계산되어야 한다 (하위 호환)

---

## Scenario 3: 최소 샘플 수 가드

**Given** DB에 gemini-2.5-flash 검증 시그널이 3건만 존재할 때
**When** `get_accuracy_stats(db, days=30, ai_model="gemini-2.5-flash")`를 호출하면
**Then** 적중률 수치 대신 "데이터 부족 (3건)" 형태의 메시지가 포함되어야 한다

**Given** DB에 gemini-2.5-flash 검증 시그널이 10건 존재할 때
**When** `get_accuracy_stats(db, days=30, ai_model="gemini-2.5-flash")`를 호출하면
**Then** 정상적인 적중률 수치가 반환되어야 한다

---

## Scenario 4: analyze_stock()에서 모델명 전달

**Given** AI 모델이 gemini-2.5-flash로 설정되어 있을 때
**When** `analyze_stock()`가 `get_accuracy_stats()`를 호출하면
**Then** `ai_model="gemini-2.5-flash"` 파라미터가 전달되어야 한다

---

## Edge Cases

| 케이스 | 예상 동작 |
|--------|----------|
| `ai_model`에 존재하지 않는 모델명 전달 | 빈 통계 반환 (0건), 최소 샘플 가드 작동 |
| `days=0`으로 호출 | 빈 통계 반환 |
| `FundSignal.ai_model`이 NULL인 레코드 | `ai_model=None` 호출 시 포함, 특정 모델 필터 시 제외 |
| confidence가 정확히 임계값과 같은 경우 | 통과 (>= 비교) |

---

## Quality Gate Criteria

- [ ] `get_accuracy_stats()`에 `ai_model` 파라미터 존재
- [ ] `ai_model` 지정 시 해당 모델만 필터링됨
- [ ] `ai_model=None` 시 기존 동작과 동일 (하위 호환)
- [ ] `_MIN_ACTION_CONFIDENCE`와 paper_trading 임계값 차이 <= 0.05
- [ ] 프롬프트 텍스트 임계값과 코드 가드 차이 <= 0.10
- [ ] 검증 시그널 5건 미만 시 "데이터 부족" 표시
- [ ] 기존 테스트 전체 통과 (회귀 없음)

---

## Definition of Done

1. 3개 파일(`signal_verifier.py`, `fund_manager.py`, `paper_trading.py`) 수정 완료
2. 모든 acceptance scenario 통과
3. 기존 테스트 회귀 없음
4. confidence 임계값이 단일 소스에서 관리됨
5. gemini 프롬프트에 gemini-only 적중률이 주입됨
