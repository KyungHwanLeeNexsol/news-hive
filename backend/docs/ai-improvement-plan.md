# AI 모델 개선 계획 (데이터 축적 후 적용)

> 즉시 적용된 개선 목록은 git log 참조. 이 문서는 데이터가 쌓인 후 판단·적용해야 하는 항목을 기술한다.

---

## PLAN-001: Bayesian 부분 보정 (5~9 샘플 구간)

### 현재 문제

`signal_verifier.py`의 `calibrate_confidence()`는 `accuracy["total"] >= 10` 이진 스위치로 동작한다.

- 9건 이하: 보정 완전 무시 (raw confidence 그대로)
- 10건 이상: 즉시 전면 Bayesian 보정 적용

5~9 샘플 구간에서 보정이 전혀 없다는 것은 초기 노이즈가 많은 데이터를 무시하는 것이므로
오히려 초기 품질을 떨어뜨릴 수 있다.

### 개선 방향

샘플 수에 따라 보정 가중치를 선형 증가시키는 **점진적 Bayesian 보정** 도입.

```python
# 현재 (fund_manager.py line ~2209)
if accuracy["total"] >= 10:
    signal.confidence = calibrate_confidence(signal.confidence, accuracy)

# 개선 후
def _bayesian_blend_weight(total: int) -> float:
    """샘플 수에 따른 Bayesian 보정 가중치 (0.0~1.0)."""
    if total < 5:
        return 0.0   # 데이터 부족, 보정 없음
    if total >= 30:
        return 1.0   # 충분한 데이터, 전면 보정
    return (total - 5) / 25  # 5~30 구간 선형 증가

blend = _bayesian_blend_weight(accuracy["total"])
if blend > 0:
    calibrated = calibrate_confidence(signal.confidence, accuracy)
    signal.confidence = signal.confidence * (1 - blend) + calibrated * blend
```

### 적용 조건

- 각 모델(gemini-2.5-flash, fallback 포함)별 시그널 **누적 50건 이상** 달성 후
- A/B 테스트: 짝수 stock_id → 기존 이진 방식 / 홀수 → 점진적 방식
- 평가 기준: 14일 후 `is_correct` 필드로 두 그룹의 정확도 비교
- 유의미한 차이(≥5%p) 확인 시 전면 전환

### 대기 중 지표

```sql
-- 현재 시그널 건수 확인
SELECT ai_model, COUNT(*) as total, 
       SUM(CASE WHEN is_correct IS NOT NULL THEN 1 ELSE 0 END) as verified
FROM fund_signals
GROUP BY ai_model;
```

---

## PLAN-002: signal_type별 accuracy 분리

### 현재 문제

`get_accuracy_stats()`는 buy/sell만 구분하며, signal_type(일반/선행탐지/공시 기반)을 하나로 합산한다.

- 일반 시그널(analyze_stock): 뉴스+기술적+수급 종합 판단
- 선행 탐지 시그널(SPEC-AI-010): BB압축/조용한 축적/섹터 후발주 등 특수 조건
- 공시 기반 시그널(SPEC-AI-004): DART 공시 임팩트 기반

이 세 타입의 성과가 혼재되면 Bayesian 보정의 신호가 오염된다.

### 개선 방향

`signal_verifier.py`의 `get_accuracy_stats()`에 `signal_type` 파라미터 추가:

```python
def get_accuracy_stats(
    db: Session,
    days: int = 30,
    ai_model: str | None = None,
    signal_type: str | None = None,  # None=전체, "leading"=선행탐지, "disclosure"=공시
) -> dict:
    query = db.query(FundSignal).filter(...)
    if signal_type is not None:
        query = query.filter(FundSignal.signal_type == signal_type)
    elif signal_type == "normal":
        query = query.filter(FundSignal.signal_type.is_(None))
    ...
```

`analyze_stock()`에서 `calibrate_confidence()` 호출 시 signal_type별 accuracy 전달:

```python
normal_accuracy = get_accuracy_stats(db, days=30, ai_model=..., signal_type="normal")
if normal_accuracy["total"] >= 10:
    signal.confidence = calibrate_confidence(signal.confidence, normal_accuracy)
```

### 적용 조건

- 각 signal_type별 검증 완료 시그널 **30건 이상** 달성 후 의미 있는 분리 가능
- 현재 DB의 signal_type 분포 확인:

```sql
SELECT signal_type, COUNT(*) as total,
       SUM(CASE WHEN is_correct = true THEN 1 ELSE 0 END) as correct
FROM fund_signals
WHERE verified_at IS NOT NULL
GROUP BY signal_type;
```

- 타입별 정확도 차이가 통계적으로 유의(≥10%p)할 때 분리 보정 적용

---

## 검토 일정 기준

| 항목 | 검토 시점 | 필요 데이터 |
|------|-----------|-------------|
| PLAN-001 (Bayesian 부분 보정) | 검증 시그널 50건 달성 시 | `is_correct IS NOT NULL` 건수 |
| PLAN-002 (signal_type별 분리) | 타입별 검증 30건 달성 시 | signal_type별 `verified_at` 건수 |

위 쿼리를 주기적으로 실행하여 조건 충족 여부를 확인한다.
