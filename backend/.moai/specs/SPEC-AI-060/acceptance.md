---
id: SPEC-AI-060
type: acceptance
version: 0.1.0
created: 2026-06-22
updated: 2026-06-22
---

# SPEC-AI-060 인수 기준 (Acceptance Criteria)

Given-When-Then 형식. 각 시나리오는 자동화 테스트로 검증 가능해야 한다. LLM 호출은 mock 처리한다.

---

## AC-1: 컨텍스트 보강 — 데이터 완전 (R1)

- **Given** `Disclosure`에 종목 A의 당일 공시 1건(`report_name`, `ai_summary`), `NewsArticle`+`NewsStockRelation`에 종목 A 연결 뉴스 2건, 종목 A의 일봉 거래량 이력, T-1 `FundSignal` 1건이 존재하고,
- **When** `enrich_surge_stock_context("A", trading_date, db)`를 호출하면,
- **Then** 반환 dict의 `disclosures`에 공시 1건(report_name+ai_summary), `news_headlines`에 2건, `volume_ratio`에 5일 평균 대비 배수(>0), `our_signal`에 signal_type·confidence·surge_metadata가 채워진다.

## AC-2: 컨텍스트 보강 — 뉴스 미연결 종목 (R1.2, R1.5)

- **Given** 종목 B는 `NewsArticle`에 관련 기사가 있으나 `NewsStockRelation`로 연결되지 않았고,
- **When** `enrich_surge_stock_context("B", trading_date, db)`를 호출하면,
- **Then** `news_headlines`는 빈 리스트가 되고 예외가 발생하지 않으며, 나머지 항목(공시·거래량·시그널)은 정상 수집된다.

## AC-3: 공시 날짜 문자열 매칭 (R1.1, RISK-3)

- **Given** 종목 C의 공시 `rcept_dt`가 `trading_date`의 `YYYYMMDD` 문자열과 일치하고,
- **When** 컨텍스트를 보강하면,
- **Then** 해당 공시가 `disclosures`에 포함된다. `rcept_dt`가 2일 전(직전 영업일 이전)인 공시는 제외된다.

## AC-4: 종목별 인과 분석 — 정상 JSON (R2.1, R2.2)

- **Given** 종목 A의 보강 컨텍스트(공시 있음)와 우리 시그널 없음(FN)이 주어지고 LLM이 유효 JSON을 반환하도록 mock되어 있을 때,
- **When** `analyze_surge_cause_with_llm("A", context, None, db)`를 호출하면,
- **Then** 반환 dict에 `root_cause`(공시/테마/거래량/모멘텀/복합 중 하나), `should_have_fired`(탐지기명 또는 "none"), `improvement_suggestion`, `confidence_note`가 모두 존재한다.

## AC-5: 종목별 인과 분석 — JSON 깨짐 fallback (R2.3)

- **Given** LLM이 JSON이 아닌 자유 텍스트를 반환하도록 mock되어 있고 컨텍스트에 공시가 존재할 때,
- **When** `analyze_surge_cause_with_llm()`를 호출하면,
- **Then** `improvement_suggestion`에 원본 텍스트가 담기고 `root_cause`는 규칙 기반 추정값("공시")으로 채워지며, 함수는 예외 없이 구조화 dict를 반환한다.

## AC-6: LLM 호출 예산 상한 (R3.1, R3.2)

- **Given** FN 10개 + TP 6개(총 16종목)가 있고 `max_calls_per_run`이 8일 때,
- **When** 강화 분석 전체를 실행하면,
- **Then** 실제 LLM 호출 횟수는 8회를 초과하지 않고, 등락률 상위 종목부터 처리되며, 예산 초과 종목은 규칙 기반 fallback 또는 미분석으로 표시된다.

## AC-7: Gemini 한도 도달 시 fallback 전환 (R3.4)

- **Given** 분석 도중 LLM 호출이 한도/연속 실패로 None을 반환하기 시작할 때,
- **When** 남은 종목을 처리하면,
- **Then** 시스템은 추가 LLM 호출을 중단하고 남은 종목 전부를 규칙 기반 fallback으로 분석하며, 평가 잡은 예외 없이 완료된다.

## AC-8: 무료 키 경로 우선 (R3.5)

- **Given** 종목별 분석 호출이 실행될 때,
- **When** LLM을 호출하면,
- **Then** 무료 키 우선 경로(`ask_ai_free_standard` 또는 free_only=True 경로)가 사용되어 유료 Gemini 키 호출이 발생하지 않는다(mock 호출 인자로 검증).

## AC-9: 탐지기 개선 제안 집계 (R4.1, R4.3)

- **Given** FN 분석 결과 중 3종목이 `should_have_fired="disclosure_impact"`, 2종목이 `should_have_fired="theme_cluster"`로 분류될 때,
- **When** `generate_detector_improvement_suggestions(analysis_results)`를 호출하면,
- **Then** 탐지기별로 그룹화된 제안 목록이 반환되고, `disclosure_impact`(3종목)가 `theme_cluster`(2종목)보다 높은 우선순위로 정렬되며, 각 그룹에 미발화 종목 수·대표 코드·통합 제안이 포함된다.

## AC-10: TP 강화 분석 (R5.1, R5.2)

- **Given** TP 종목(우리가 맞힌 급등주) 3개와 각 종목의 보강 컨텍스트가 있을 때,
- **When** `analyze_true_positives_with_llm(tp_stocks, db)`를 호출하면,
- **Then** 종목별로 `winning_detector`(주효 탐지기명), `pattern_summary`, `reinforce`(bool)를 포함한 결과 리스트가 반환되고, FN 분석과 분리된 구조로 식별 가능하다.

## AC-11: 기존 시그니처 호환 (R6.1, R6.2)

- **Given** 스케줄러가 기존처럼 `analyze_misses_with_llm(missed_stocks, db)`를 호출할 때,
- **When** 함수가 실행되면,
- **Then** 반환 타입은 `str`이고 `SurgePredictionEvaluation.miss_analysis_json`에 저장 가능하며, `scheduler.py:652` 호출부 코드 수정 없이 동작한다.

## AC-12: 분석 결과 저장 (R7.1, R7.3) — Option A

- **Given** 평가일 T에 대해 FN 인과 + TP 강화 + 탐지기 제안이 생성되었을 때,
- **When** 결과를 저장하면,
- **Then** `SurgePredictionEvaluation.per_stock_analysis_json`에 각 종목의 `stock_code`/`change_rate`/`classification`(TP|FN)/`root_cause`또는`winning_detector`/`should_have_fired`/`improvement_suggestion`이 직렬화되어 저장된다.

## AC-13: 스케줄러 통합 — 평가 보존 (R8.1, R8.3)

- **Given** `_run_surge_verify_predictions()`가 실행되고 강화 분석 단계에서 예외가 발생하도록 mock되어 있을 때,
- **When** 잡이 실행되면,
- **Then** 예외는 로깅되고, 기존 `evaluate_surge_predictions()`가 산출한 precision/recall/f1 값은 정상 저장되며(분석 실패가 평가 실패로 전파되지 않음), 잡은 비정상 종료하지 않는다.

## AC-14: 거래일 가드 (R9.1)

- **Given** 실행일이 주말 또는 KRX 휴장일일 때,
- **When** 평가 잡이 트리거되면,
- **Then** 강화 분석을 포함한 전체 잡이 스킵되고 LLM 호출이 0회이다.

## AC-15: 데이터 없음 종목 처리 (R10.1, R10.2)

- **Given** FN 종목 중 일부가 공시·뉴스·거래량 데이터를 모두 갖지 못할 때,
- **When** 강화 분석을 실행하면,
- **Then** 해당 종목은 LLM 호출 없이 "데이터 없음(원인 미상)"으로 분류되고, 집계 결과에 데이터 없음 종목 수가 명시된다.

---

## Edge Cases (경계 조건)

- **EC-1**: FN=0 AND TP=0 → 강화 분석을 건너뛰고 빈 결과를 저장한다(LLM 호출 0).
- **EC-2**: `surge_metadata`가 None인 시그널 → `our_signal`은 signal_type/confidence만, 탐지기 기여는 빈 dict로 처리(KeyError 금지).
- **EC-3**: 동일 종목에 공시 다건 → 가장 최근/영향도 높은 1~2건만 컨텍스트에 포함(프롬프트 길이 제한).
- **EC-4**: T-1이 연휴 직후라 직전 영업일이 3일 전 → `_get_prev_business_day` 역산 결과를 신뢰하고 공시/시그널 매칭에 동일 날짜 사용.
- **EC-5**: `volume_ratio` 계산 시 일봉 이력 5일 미만 → 가용 일수로 평균 산출하되 신뢰도 낮음 표시.
- **EC-6**: LLM이 알 수 없는 탐지기명을 `should_have_fired`로 반환 → 알려진 탐지기 목록(theme_cluster/volume_news_combo/disclosure_impact/disclosure_pattern/news_delayed/legacy_detectors) 외 값은 "unknown"으로 정규화하여 집계.

---

## Quality Gate (품질 게이트)

- [ ] `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과
- [ ] `cd backend && uv run ruff check .` 무경고
- [ ] `cd backend && uv run mypy app/` 타입 오류 0
- [ ] 신규 함수 4종 단위 테스트 커버리지 85%+
- [ ] LLM 호출 전부 mock — 테스트 실행 중 실제 외부 API 미호출
- [ ] 마이그레이션 `061` up/down 양방향 검증(Option A 채택 시)
- [ ] 모든 Python 코드 주석 한국어(code_comments: ko)
- [ ] @MX 태그: `enrich_surge_stock_context`(ANCHOR), `analyze_misses_with_llm`(ANCHOR+REASON), LLM 함수(WARN+REASON) 부착

---

## Definition of Done (완료 정의)

- spec.md의 R1~R10 모든 요구사항이 구현되고 대응 AC가 통과한다.
- `analyze_misses_with_llm()` 시그니처·반환타입이 변경되지 않아 스케줄러 호출부 무수정으로 동작한다(SC-4).
- 강화 분석 실패가 기존 평가 저장을 막지 않음을 통합 테스트로 입증한다(SC-7).
- 탐지기 개선 제안이 자동 적용되지 않고 휴먼 검토용으로만 기록됨을 확인한다(Section 6 제외 범위 준수).
- 배포 전 `alembic upgrade head` 적용(Option A 채택 시 `061` 포함) 절차가 문서화된다.
