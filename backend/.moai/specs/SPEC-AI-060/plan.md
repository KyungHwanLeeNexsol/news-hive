---
id: SPEC-AI-060
type: plan
version: 0.1.0
created: 2026-06-22
updated: 2026-06-22
---

# SPEC-AI-060 구현 계획 (Implementation Plan)

## 1. 기술 접근 (Technical Approach)

SPEC-AI-041이 만든 18:30 KST 평가 잡(`_run_surge_verify_predictions`)의 FN 분석 단계를 "추정 분석"에서 "컨텍스트 기반 인과 분석"으로 교체하고, TP 강화 분석을 신설한다. 핵심은 **데이터 결손 내성**과 **LLM 호출 예산 관리** 두 축이다.

핵심 원칙:
- 기존 `analyze_misses_with_llm()` 시그니처 동결 → 스케줄러 호출부 무변경(R6).
- 모든 종목-데이터 매칭은 실제 스키마 제약을 따른다: 뉴스는 `NewsStockRelation` 조인, 공시는 `rcept_dt` 문자열 비교, 시그널은 `Stock.stock_code` 조인.
- LLM은 무료 키 경로 우선, 호출 상한·지연·fallback 3중 가드.
- 탐지기 개선 제안은 **생성만** — 자동 적용은 명시적 제외(R4.4, Section 6).

## 2. DB 저장 방식 결정 (Option A vs B)

| 기준 | Option A: `SurgePredictionEvaluation.per_stock_analysis_json` | Option B: 신규 `SurgeStockAnalysis` 테이블 |
|---|---|---|
| 구현 비용 | 낮음(컬럼 1개 + 마이그레이션 1개) | 높음(모델+마이그레이션+CRUD) |
| 종목 단위 조회 | JSON 파싱 필요 | 인덱스 쿼리 가능 |
| 집계/통계 | 약함 | 강함(GROUP BY 탐지기) |
| AI-041 정합성 | 기존 `miss_analysis_json` 옆 자연 확장 | 별도 테이블 — 조인 필요 |
| 마이그레이션 리비전 | 061 (단일) | 061 (단일, 테이블 생성) |

**결정(잠정): Option A**. 사유 — 본 SPEC은 평가일 단위 분석 묶음 저장이 1차 목표이며, 종목 단위 통계 쿼리는 현 요구에 없음. SPEC-AI-041 `improvements_applied_json`/`miss_analysis_json`과 동일 패턴으로 일관성 유지. 향후 종목 단위 통계 수요가 생기면 Option B로 승격(별도 SPEC). Annotation 단계에서 사용자 확정 필요.

## 3. 마일스톤 (Milestones — 우선순위 기반, 시간 추정 없음)

### M1 (Priority High): 컨텍스트 보강 엔진
- `enrich_surge_stock_context()` 구현
  - 공시 조회: `Disclosure.stock_code` + `rcept_dt` 문자열 당일/전일 매칭
  - 뉴스 조회: `NewsArticle` ⋈ `NewsStockRelation`(stock_id) ⋈ `Stock`(stock_code) + `published_at` 범위
  - 거래량 배수: 일봉 이력 5일 평균 대비 당일 배수
  - 우리 시그널: `FundSignal` ⋈ `Stock` + T-1 `created_at`
- 데이터 결손 내성(R1.5/R10): 각 소스 try/except → 빈 값, 전무 시 "데이터 없음" 마킹
- 산출물: 구조화 dict 반환 + 단위 테스트(데이터 있음/없음/부분 결손 케이스)

### M2 (Priority High): 종목별 인과 분석 + 예산 가드
- `analyze_surge_cause_with_llm()` — JSON 스키마 프롬프트 + 파싱 + fallback(R2)
- LLM 호출 예산 헬퍼: 호출 카운터(상한 8), 호출 간 지연, 무료 키 경로, 한도/연속실패 → fallback 전환(R3)
- 산출물: 구조화 dict + fallback 경로 테스트(JSON 깨짐·LLM None·한도 도달)

### M3 (Priority Medium): TP 분석 + 탐지기 제안 집계
- `analyze_true_positives_with_llm()` — TP 강화 분석(R5), 예산 공유
- `generate_detector_improvement_suggestions()` — 탐지기별 그룹화·빈도 우선순위(R4)
- 산출물: TP/FN 분리 구조 + 집계 결과 정렬 검증 테스트

### M4 (Priority Medium): 저장 + 호환 래퍼
- (Option A) `SurgePredictionEvaluation.per_stock_analysis_json` 컬럼 + 마이그레이션 `061`
- `analyze_misses_with_llm()` 수정 — 내부 강화, 시그니처·반환타입(str) 동결(R6)
- 산출물: 마이그레이션 up/down 검증 + 기존 호출부 호환 테스트

### M5 (Priority Medium): 스케줄러 통합 + 설정
- `_run_surge_verify_predictions()` 수정 — FN 강화 + TP 분석 호출, 예외 격리(R8.3)
- `surge_detection.yaml` `per_stock_analysis` 섹션 추가
- 산출물: 잡 통합 후 평가 결과 보존 검증 + 거래일 가드(R9) 회귀 테스트

## 4. 파일별 변경 요약

| 파일 | 변경 | 마일스톤 |
|---|---|---|
| `app/services/surge_evaluation_service.py` | `enrich_surge_stock_context`/`analyze_surge_cause_with_llm`/`analyze_true_positives_with_llm`/`generate_detector_improvement_suggestions` 신규 + `analyze_misses_with_llm` 수정 | M1~M4 |
| `app/models/surge_prediction_evaluation.py` | `per_stock_analysis_json` 컬럼 추가 (Option A) | M4 |
| `alembic/versions/061_surge_per_stock_analysis.py` | 신규 마이그레이션 (down_revision=060) | M4 |
| `app/services/scheduler.py` | `_run_surge_verify_predictions` 강화 분석 통합 + 예외 격리 | M5 |
| `app/surge_config/surge_detection.yaml` | `per_stock_analysis` 섹션 | M5 |
| `backend/tests/` | 각 함수 단위 + 통합 테스트 | M1~M5 |

> 변경 파일 3개 이상 → CLAUDE.md Rule 2(Multi-File Decomposition)에 따라 마일스톤 단위 순차 실행. 마이그레이션·모델·스케줄러는 의존성 순서(M4 → M5) 준수.

## 5. 데이터 매칭 구현 주의 (실제 스키마 기반)

- **뉴스**: `NewsArticle`에 `stock_code` 없음. 반드시 `join(NewsStockRelation, NewsArticle.id == NewsStockRelation.news_id).join(Stock, NewsStockRelation.stock_id == Stock.id).filter(Stock.stock_code == code)`.
- **공시**: `Disclosure.rcept_dt`는 `YYYYMMDD` **문자열**. `trading_date.strftime("%Y%m%d")` 및 직전 영업일 문자열과 비교. `disclosed_at`(DateTime, nullable)도 보조 활용 가능하나 결측 잦음.
- **시그널**: `FundSignal`에 `stock_code` 없음 — `join(Stock, FundSignal.stock_id == Stock.id)`. surge 기여 점수는 `surge_metadata` JSON 내부(실 컬럼 아님).
- **거래량**: `SurgeActualOutcome`에 거래량 없음. 일봉 이력 헬퍼 재사용(인트라데이 불가).
- **공시 필드명**: `report_name`(제목 역할)·`ai_summary`·`report_type` 사용. `title`/`content`/`disclosure_type`는 **존재하지 않음** — 코드에서 참조 금지.

## 6. 테스트 전략

- **단위 테스트**: 각 신규 함수. 데이터 있음/없음/부분 결손, LLM 성공/JSON깨짐/None/한도도달, 예산 상한 초과 시 우선순위 컷, 탐지기 집계 정렬.
- **통합 테스트**: `_run_surge_verify_predictions` 호출 시 (a) 평가 저장 보존, (b) 강화 분석 예외가 평가를 막지 않음(R8.3), (c) 주말 스킵(R9).
- **호환 테스트**: 기존 `analyze_misses_with_llm(missed, db)` 호출이 str 반환 + 저장 가능.
- LLM 호출은 mock 처리(`ask_ai_with_openai_fallback`/`ask_ai_free_standard` patch). 실제 API 미호출.
- 검증 명령(CLAUDE.local.md): `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`, `uv run ruff check . && uv run mypy app/`.
- 커버리지 목표: 신규 함수 85%+.

## 7. 의존성 / 선행 조건

- SPEC-AI-041 완료 상태(평가 루프·모델·스케줄러 잡 존재) — verified.
- 마이그레이션 head가 `060_surge_auto_improvement_log`인지 배포 전 확인 → `alembic upgrade head` 후 `061` 적용.
- `NewsStockRelation` 데이터가 채워져 있어야 뉴스 매칭 유효(미연결 종목은 R10 데이터 없음 처리).

## 8. @MX 태그 대상

- `enrich_surge_stock_context`: `@MX:ANCHOR`(다중 호출 진입점, 외부 모델 4종 조인) + `@MX:SPEC: SPEC-AI-060 R1`
- `analyze_surge_cause_with_llm`: `@MX:NOTE`(LLM JSON 파싱·fallback 분기) + `@MX:WARN`(외부 LLM 의존·한도) `@MX:REASON: Gemini 일일 20회 한도 공유`
- `analyze_misses_with_llm`: `@MX:ANCHOR`(스케줄러 fan_in, 시그니처 동결 계약) + `@MX:REASON: scheduler.py:652 호출부 호환 유지 필수`
- 마이그레이션·모델 변경: `@MX:NOTE: [AUTO] SPEC-AI-060`
