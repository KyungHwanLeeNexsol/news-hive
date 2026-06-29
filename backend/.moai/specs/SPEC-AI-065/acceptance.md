---
id: SPEC-AI-065
version: 1.0.0
status: completed
created: 2026-06-29
updated: 2026-06-29
author: Nexsol
priority: high
issue_number: null
---

# SPEC-AI-065 수용 기준 (Acceptance Criteria)

요구사항 ID는 `spec.md` 3절 참조. 모든 시나리오는 **예측 기록 모드**(매수 무변경)를 전제로 한다.

## 1. Given-When-Then 시나리오

### S1: Z-score 상대 채점 — 소형주 우대 (REQ-1)
- **Given** 평소 뉴스 0건인 소형주 X와 평소 뉴스 3건인 대형주 Y의 30거래일 베이스라인이 존재하고,
- **When** 두 종목 모두 당일 뉴스 3건이 관측되어 앙상블 점수를 계산하면,
- **Then** 소형주 X의 뉴스 탐지기 z-score(z≫0)가 대형주 Y의 z-score(z≈0)보다 높게 채점되어야 한다.

### S2: Z-score 콜드스타트 fallback (REQ-1.3)
- **Given** 베이스라인 `sample_count < min_baseline_samples`(기본 10)인 신규 종목 Z가 있고,
- **When** Z에 대한 앙상블 점수를 계산하면,
- **Then** 시스템은 z-score 정규화를 건너뛰고 절대값 fallback으로 채점하며, 오류 없이 후보로 평가되어야 한다.

### S3: 유니버스 확장 — Pool A/B/C 포함 (REQ-2)
- **Given** 당일 공시 종목 N_A개, 거래량 200%+ 종목 N_B개, change_rate 5~15% 종목 N_C개가 있고,
- **When** 장마감 후 유니버스 빌드가 실행되면,
- **Then** 익일 후보 유니버스는 기존 탐지 후보와 3개 풀의 합집합(중복 제거)이 되고, 각 후보에 `entry_pool` 태그가 붙으며, 크기는 `max_scan_universe`(150) 이하여야 한다.

### S4: 유니버스 크기 목표 (AC-3)
- **Given** 정상 거래일,
- **When** 유니버스 빌드가 완료되면,
- **Then** `scan_universe_size`가 80~150 범위에 들어야 한다(기존 20~30 대비 확장 확인).

### S5: 모멘텀 연속 탐지기 발화 (REQ-3.1, REQ-3.4)
- **Given** 전일 change_rate +8%(5~15% 범위)인 종목 M과 전일 +18%(과열)인 종목 H,
- **When** 익일 아침 앙상블을 계산하면,
- **Then** M은 `momentum_continuation`이 발화하고, H는 과열 차단으로 발화하지 않아야 한다.

### S6: 8탐지기 가중치 합 검증 (REQ-3.3, AC-5)
- **Given** `momentum_continuation`이 추가된 `EnsembleWeightsConfig`,
- **When** `validate_ensemble_weights`를 호출하면,
- **Then** 8개 가중치 합이 1.0으로 검증을 통과해야 한다(미통과 시 시그널 생성 차단).

### S7: 풀별 지표 기록 및 귀속 (REQ-5)
- **Given** 당일 평가가 실행되고 적중/미적중이 산출되었을 때,
- **When** 평가 결과를 저장하면,
- **Then** `surge_prediction_evaluation`에 `scan_universe_size`, `pool_a_count`, `pool_b_count`, `pool_c_count`가 기록되고, 각 적중을 `entry_pool`(FundSignal→Stock 조인)로 귀속하여 풀별 정밀도/리콜을 조회할 수 있어야 한다.

### S8: 오프라인 가중치 재보정 (REQ-4)
- **Given** 과거 `(T-1 탐지기 점수, T was_surge)` 데이터셋,
- **When** `recalibrate_ensemble_weights.py`(순수 파이썬 로지스틱 회귀)를 실행하면,
- **Then** 합=1.0 및 클램프 `[0.05, 0.45]`를 준수하는 가중치가 `surge_detection.auto.yaml`에 시드되고, TP/FN 차별 팩터 분석이 산출물로 남아야 한다.

### S9: 회귀 없음 (AC-7)
- **Given** 기존 7탐지기 시그널 생성 경로,
- **When** 본 SPEC 변경 적용 후 시그널을 생성하면,
- **Then** 매수 로직은 변경되지 않고(예측 기록 모드 유지), 기존 경로가 무손상으로 동작해야 한다.

## 2. Edge Cases (엣지 케이스)

- `rolling_std == 0`(무변동 종목) → z-score 분모 0 회피, fallback 적용.
- Pool C 후보 이력 미확보 → `fetch_top_movers_codes` + 코드별 조회 2단계 보완(REQ-2.6).
- 풀 합집합이 `max_scan_universe` 초과 → 풀 우선순위(A>B>C) + z-score 절단(REQ-2.7).
- 공시 `rcept_dt`(YYYYMMDD 문자열) 날짜 비교 시 형 변환 누락 방지.
- 동일 종목이 여러 풀에 동시 진입 → 중복 제거, 대표 `entry_pool` 결정 규칙 명시.

## 3. Quality Gate (품질 게이트)

- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과.
- `cd backend && uv run ruff check . && uv run mypy app/` 무오류.
- `validate_ensemble_weights` 단위 테스트로 8탐지기 합=1.0 강제.
- migration 063 up/down 무오류(`down_revision=062`).
- TRUST 5: 신규 공개 함수 85%+ 커버리지, 한국어 주석(code_comments=ko).

## 4. Definition of Done (완료 정의)

- [ ] REQ-1 ~ REQ-5 전 요구사항 구현 및 테스트 통과
- [ ] AC-1 ~ AC-7 측정 기준 충족(리콜 ≥3%, 정밀도 ≥15%, 유니버스 80~150)
- [ ] S1 ~ S9 시나리오 자동화 테스트 통과
- [ ] migration 063 적용, 신규 테이블/컬럼 운영 DB 반영
- [ ] 예측 기록 모드 유지(매수 로직 무변경) 확인
- [ ] numpy/scipy/sklearn 미도입 확인(순수 파이썬)
