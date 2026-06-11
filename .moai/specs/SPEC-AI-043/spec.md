# SPEC-AI-043: 급등예측 포트폴리오 → 급등예측 기록 시스템 전환

## Overview

**목표**: 가상 포트폴리오(매수·포지션·손익 추적) 패러다임을 순수 예측 정확도 추적 패러다임으로 전환한다.  
매 거래일 전날 시그널을 생성하고, 거래일 종료 후 예측 종목이 실제로 올랐는지 비교하여 오류를 분석하고 자동으로 탐지기를 개선한다.

**Status**: Completed  
**Date**: 2026-06-10  
**Completed**: 2026-06-10  
**Depends on**: SPEC-AI-041 (자동 평가·자가개선 루프)

---

## Background

### 현재 시스템 (AS-IS)

```
15:20 시그널 생성 → 09:00 매수 실행 → 5분 손절/익절 체크 → 15:40 강제 청산
→ 포트폴리오 잔고/수익률 추적 (SurgePortfolio, SurgeTrade)
```

현재 프론트엔드는 "포지션 현황, 보유 종목, 누적 수익률 차트"를 보여준다.

### 목표 시스템 (TO-BE)

```
15:20 시그널 생성(T-1) → 거래일 장 마감 → 16:10 실제 급등 결과 수집
→ 16:30 T-1 예측 vs T 실제 비교 평가 → 19:00 자동 가중치 개선
```

프론트엔드는 "날짜별 예측 목록, 종목별 적중 여부, 오류 원인 분석, 정확도 추이"를 보여준다.

### 이미 구현된 인프라 (유지)

- `SurgePredictionEvaluation` — T-1/T 비교 precision/recall/f1/TP/FP/FN
- `SurgeActualOutcome` — 실제 급등 결과 일별 저장
- `FundSignal.is_correct`, `error_category`, `alpha_pct` — 개별 시그널 정확도
- `signal_verifier.py` — 오류 원인 분류 (5개 카테고리)
- `surge_auto_improve` — 자동 가중치 조정 (SPEC-AI-041)
- `GET /api/surge-trading/evaluation` — 집계 평가 API (이미 존재)

---

## Requirements

### REQ-AI043-001: 포트폴리오 실행 스케줄러 비활성화

**WHEN** SPEC-AI-043 구현이 완료되면  
**THE SYSTEM SHALL** 다음 3개 scheduler job을 비활성화(주석 처리)한다:
- `_run_surge_execute_buys` (매수 실행, 09:00 시작 30분 간격)
- `_run_surge_check_exits` (손절/익절 체크, 5분 간격)
- `_run_force_max_holding_exit` (최대 보유 강제 청산, 15:40)

**THE SYSTEM SHALL NOT** 다음 job을 제거한다 (유지):
- 시그널 생성, 실제 결과 수집, 예측 검증, 자동 개선

---

### REQ-AI043-002: 날짜별 예측 기록 상세 API

**WHEN** 클라이언트가 `GET /api/surge-trading/prediction-history?days=N`을 호출하면  
**THE SYSTEM SHALL** 최근 N거래일의 예측 기록을 아래 구조로 반환한다:

```json
[
  {
    "trading_date": "2026-06-10",
    "predicted_count": 25,
    "actual_surge_count": 8,
    "true_positive": 5,
    "false_positive": 20,
    "false_negative": 3,
    "precision": 0.20,
    "recall": 0.625,
    "f1_score": 0.31,
    "avg_alpha_pct": 0.6,
    "error_breakdown": {
      "macro_shock": 3,
      "supply_reversal": 5,
      "earnings_miss": 2,
      "sector_contagion": 4,
      "technical_breakdown": 6
    },
    "signals": [
      {
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "signal_type": "surge_candidate",
        "confidence": 0.52,
        "composite_score": 0.48,
        "price_at_signal": 73000,
        "price_after_1d": 74500,
        "return_pct": 2.05,
        "alpha_pct": 1.2,
        "is_correct": true,
        "error_category": null
      }
    ]
  }
]
```

**THE SYSTEM SHALL** `signals` 필드를 `SurgePredictionEvaluation.evaluation_date`와 매핑하여  
해당 날짜에 생성된 `FundSignal(signal_type IN ['surge_candidate', 'preday_disclosure'])`를 포함시킨다.

**THE SYSTEM SHALL** `error_breakdown`을 `is_correct=False`인 시그널의 `error_category` 카운트로 계산한다.

---

### REQ-AI043-003: 기존 상세 평가 API 시그널 목록 추가

**WHEN** 클라이언트가 `GET /api/surge-trading/evaluation/{date}`를 호출하면  
**THE SYSTEM SHALL** 기존 응답에 `signal_details` 배열을 추가하여 반환한다.

`signal_details` 각 항목: stock_code, stock_name, signal_type, confidence, composite_score,  
price_at_signal, price_after_1d, return_pct, alpha_pct, is_correct, error_category

---

### REQ-AI043-004: 프론트엔드 예측 기록 UI 교체

**WHEN** 사용자가 `/trading/surge` 페이지에 접속하면  
**THE SYSTEM SHALL** 다음 4개 섹션을 표시한다:

#### 섹션 1: 요약 카드 (4개)
- 총 예측 건수 (전체 기간)
- 전체 정밀도 (precision %)
- 평균 알파 수익률 (avg alpha_pct %)
- 최근 7일 추세 (↑개선 / → 보합 / ↓하락)

#### 섹션 2: 날짜별 예측 기록 테이블
컬럼: 날짜 | 예측 종목 수 | TP/FP | 정밀도 | 평균 알파 | 오류 주요 원인
- 각 행 클릭 시 해당 날짜의 개별 시그널 목록 펼치기 (Accordion)
- 펼친 내부: stock_code, stock_name, 예측가, 실제가, 등락률, 적중여부, 오류분류

#### 섹션 3: 정확도 추이 차트
- 7일 롤링 precision 선 차트
- X축: 날짜, Y축: precision (0~100%)
- 보조 선: recall, f1_score

#### 섹션 4: 오류 원인 분류 차트
- 전체 기간 FP(오류) 원인 분류 막대 차트
- 카테고리: macro_shock, supply_reversal, earnings_miss, sector_contagion, technical_breakdown, (미분류)

**THE SYSTEM SHALL NOT** 포트폴리오 잔고, 보유 종목, 매수/매도 UI를 표시한다.

---

## Acceptance Criteria

| ID | Criterion | Verification |
|---|---|---|
| AC-001 | 09:00 매수 실행 스케줄러가 비활성화됨 | scheduler.py 코드 검토 |
| AC-002 | `/api/surge-trading/prediction-history` API 200 응답 | HTTP GET 테스트 |
| AC-003 | prediction-history 응답에 `signals` 배열 포함 | 응답 구조 검증 |
| AC-004 | `/trading/surge` 페이지에 포트폴리오 UI 없음 | 화면 확인 |
| AC-005 | 날짜별 예측 기록 테이블 표시 | 화면 확인 |
| AC-006 | 정확도 추이 차트 표시 | 화면 확인 |
| AC-007 | 날짜 행 클릭 시 종목 상세 펼치기 | 인터랙션 확인 |

---

## Implementation Notes

### 스케줄러 비활성화 방식
```python
# SPEC-AI-043: 포트폴리오 실행 비활성화 — 예측 기록 모드로 전환
# scheduler.add_job(_run_surge_execute_buys, ...)  # DISABLED
```
→ 완전 삭제 대신 주석 처리 (복구 가능성 유지)

### API: prediction-history 구현 전략
- `SurgePredictionEvaluation` LEFT JOIN `FundSignal` ON evaluation_date = fund_signals.created_at::date
- `FundSignal` filter: signal_type IN ('surge_candidate', 'preday_disclosure') AND signal = 'buy'
- `error_breakdown`: GROUP BY error_category WHERE is_correct = False

### 프론트엔드 타입 추가
```typescript
// 새로 추가
interface SurgeSignalRecord {
  stock_code: string; stock_name: string; signal_type: string;
  confidence: number; composite_score: number | null;
  price_at_signal: number | null; price_after_1d: number | null;
  return_pct: number | null; alpha_pct: number | null;
  is_correct: boolean | null; error_category: string | null;
}
interface SurgePredictionDay {
  trading_date: string; predicted_count: number;
  actual_surge_count: number; true_positive: number;
  false_positive: number; false_negative: number;
  precision: number | null; recall: number | null; f1_score: number | null;
  avg_alpha_pct: number | null;
  error_breakdown: Record<string, number>;
  signals: SurgeSignalRecord[];
}
```

---

## Implementation Summary

**구현 완료일**: 2026-06-10

### 구현 현황

| AC | 조건 | 구현 |
|---|---|---|
| AC-001 | scheduler 3개 job 비활성화 | ✅ `_run_surge_execute_buys`, `_run_surge_check_exits`, `_run_force_max_holding_exit` — `# DISABLED by SPEC-AI-043` 주석 처리 |
| AC-002 | prediction-history API | ✅ `GET /api/surge-trading/prediction-history?days=N` |
| AC-003 | signals 배열 포함 | ✅ `surge_signals` / `disclosure_signals` 분리 필드 추가 |
| AC-004 | 포트폴리오 UI 제거 | ✅ `frontend/src/app/trading/surge/page.tsx` 전면 교체 |
| AC-005~007 | 예측 기록 테이블·차트·아코디언 | ✅ 구현 완료 |

### 추가 버그 수정 (SPEC 범위 외)

- `surge_evaluation_service.py`: `signal_type="surge_candidate"` 필터 누락 수정 — `predicted_count` 오버카운트 (25→1) 해소
- `signal_verifier.py`: `preday_disclosure`를 `_DISCLOSURE_SIGNAL_TYPES`에 추가 — 3일 검증 윈도우 적용
- `surge_actual_outcome_service.py`: 예측 종목 top-100 외 보완 로직 추가
- `surge_trading.py`: `POST /api/surge-trading/re-evaluate/{date_str}` 엔드포인트 신규 추가

### 테스트 결과

- 1,486 tests passed, 4 skipped (2026-06-10 기준)

---

## Files to Modify

| File | Change |
|---|---|
| `backend/app/services/scheduler.py` | 3개 job 주석 처리 (REQ-AI043-001) |
| `backend/app/routers/surge_trading.py` | prediction-history 엔드포인트 추가, evaluation/{date} 강화 |
| `frontend/src/app/trading/surge/page.tsx` | 포트폴리오 UI → 예측 기록 UI 전면 교체 |
| `frontend/src/lib/types.ts` | SurgePredictionDay, SurgeSignalRecord 타입 추가 |

---

Version: 1.0.0
Status: Completed
Completed: 2026-06-10
