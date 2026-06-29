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

# SPEC-AI-065 구현 계획 (Implementation Plan)

상위 요구사항은 `spec.md` 참조. 본 문서는 마일스톤·기술 접근·위험을 다룬다(시간 추정 없음, 우선순위 기반).

## 1. Technical Approach (기술 접근)

핵심 통찰: 문제는 탐지기가 아니라 **입력 종목 유니버스**다. 따라서 구현은 (1) 입력 확장, (2) 상대 채점의 두 축으로 진행하며, 둘 다 기존 시그널 발신 게이팅(min_score + 적응형 임계 + 상위 랭킹)은 건드리지 않는다. 유니버스 확장은 평가 대상 후보를 넓힐 뿐, 발신량을 늘리지 않는다.

데이터·라이브러리 제약(spec.md 2.6)을 전제로:
- z-score / 로지스틱 회귀는 순수 파이썬(numpy/scipy/sklearn 미사용).
- 모든 등락률은 전일 종가 대비 `change_rate`(일봉). `open_price` 미사용.
- `FundSignal`은 `Stock` 조인으로 `stock_code` 획득.
- 마이그레이션 `down_revision=062`.

## 2. Milestones (우선순위 기반)

### M1 (Priority High) — 데이터 기반: 베이스라인 + 마이그레이션
- migration 063: `stock_signal_baselines` 테이블 생성 + `surge_prediction_evaluation` 컬럼 4종 추가.
- `app/models/stock_signal_baseline.py` 모델.
- `surge_baseline_service.py`: 순수 파이썬 롤링 평균/표준편차, 영속화/조회/일별 갱신.
- 산출: REQ-1.1, REQ-1.4, REQ-1.5, REQ-1.6, REQ-5.1.

### M2 (Priority High) — 상대 채점 통합 (z-score)
- `compute_ensemble_score` 입력을 절대값 → z-score로 전환, 콜드스타트 fallback(REQ-1.3).
- 발신 시그널의 z-score 근거를 `surge_metadata`에 기록.
- 산출: REQ-1.2, REQ-1.3.

### M3 (Priority High) — 유니버스 확장 (3 풀)
- 유니버스 빌더(장마감 후): Pool A(공시), Pool B(거래량 200%), Pool C(모멘텀 5~15%).
- 풀 태그 기록(`entry_pool`), 합집합·중복 제거, `max_scan_universe` 상한 절단.
- Pool C 2단계 조회 보완(REQ-2.6).
- scheduler 잡 연결(`timezone="Asia/Seoul"`, KST 직접; 기존 09:05 잡들과 distinct id로 공존).
- 산출: REQ-2.1 ~ REQ-2.7.

### M4 (Priority Medium) — 모멘텀 연속 탐지기
- `momentum_continuation` 신규 탐지기(전일 5~15% 상승 연속성, 과열 차단).
- `EnsembleWeightsConfig` 8번째 필드 + `validate_ensemble_weights` 합=1.0 갱신 + 비례 재조정.
- yaml/auto.yaml 섹션 추가.
- 산출: REQ-3.1 ~ REQ-3.5.

### M5 (Priority Medium) — 평가 지표 + 풀별 귀속
- `surge_evaluation_service.py`: 유니버스 크기·풀별 카운트 기록, 풀별 정밀도/리콜 집계(Stock 조인).
- 산출: REQ-5.2, REQ-5.3.

### M6 (Priority Low) — 가중치 오프라인 재보정
- `scripts/recalibrate_ensemble_weights.py`: 순수 파이썬 로지스틱 회귀 `(T-1 점수)→(T was_surge)`.
- TP 5 vs FN 850 차별 팩터 분석, auto.yaml 시드 갱신(클램프 준수).
- 산출: REQ-4.1 ~ REQ-4.5.

## 3. Dependencies & Ownership (의존·소유)

- 선행: SPEC-AI-041(온라인 가중치 보정 — M6 시드 이후 이어받음), SPEC-AI-012(앙상블/surge_metadata), SPEC-AI-062(volume_breakout 7탐지기 기준선).
- 비충돌: SPEC-AI-029/038(임계값·레짐), SPEC-AI-044(technical_momentum와 momentum_continuation 의미 구분), SPEC-AI-022(dormant 종목 별도 signal_type).

## 4. Verification (검증 — `CLAUDE.local.md` 기준)

- 백엔드: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`
- 린트/타입: `cd backend && uv run ruff check . && uv run mypy app/`
- import 점검: `cd backend && uv run python -c "from app.main import app; print('OK')"`
- 가중치 합 검증: `validate_ensemble_weights` 단위 테스트로 8탐지기 합=1.0 강제.

## 5. Risks (위험)

spec.md 7절 참조. 최우선: (1) 유니버스 확장발 정밀도 하락 — 발신 게이팅 유지로 완화, (2) 8탐지기 가중치 검증 누락 — 모델+검증 동시 수정.
