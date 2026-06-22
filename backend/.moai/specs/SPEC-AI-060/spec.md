---
id: SPEC-AI-060
version: 0.1.0
status: draft
created: 2026-06-22
updated: 2026-06-22
author: Nexsol
priority: high
issue_number: null
---

# SPEC-AI-060: 급등 종목 개별 원인 분석 및 탐지기 개선 피드백 강화

## HISTORY

- 2026-06-22 (v0.1.0): 최초 작성. SPEC-AI-041 자동평가 루프의 LLM 미스 분석을 "종목코드+등락률"만 전달하는 추정 분석에서, 종목별 공시·뉴스·거래량 컨텍스트를 주입한 인과 분석으로 강화. TP(적중) 분석 신설 + 탐지기 개선 제안 집계 추가. 선행 SPEC: SPEC-AI-041(자동평가·자가개선 루프), SPEC-AI-004(공시 충격 스코어링), SPEC-AI-012(surge_metadata).

---

## 1. Overview (개요)

### 목적

SPEC-AI-041이 구축한 일별 자동평가 루프의 **놓친 종목(FN) 분석 품질을 근본적으로 개선**한다. 현재 `analyze_misses_with_llm()`은 LLM에 종목코드와 등락률만 전달하여 "왜 시그널을 못 냈는지"를 **추정**하게 한다. 실제 급등 원인 데이터(공시/뉴스/거래량)가 없으므로 분석은 일반론에 그치고 탐지기 개선으로 이어지지 못한다.

본 SPEC은 다음을 도입한다.

1. **종목별 컨텍스트 보강**: 각 실제 급등주(T일)에 대해 당일 공시, 뉴스 헤드라인, 거래량 이상치, 우리의 T-1 시그널 유무를 수집한다.
2. **인과 분석 LLM 호출**: 보강된 컨텍스트를 입력으로 구조화된 종목별 분석을 생성한다 — 근본 원인 분류(공시/테마/거래량/모멘텀), 발화했어야 할 탐지기, 구체적 개선 제안.
3. **탐지기 개선 제안 집계**: 종목별 분석들을 탐지기 단위로 집계하여 실행 가능한 제안 목록을 만든다(예: "disclosure_impact: Tier 1 키워드에 '신약 승인' 추가").
4. **TP(적중) 분석**: 우리가 맞힌 종목을 왜 맞혔는지 분석하여 잘 작동하는 패턴을 강화 신호로 기록한다.

### 배경

`analyze_misses_with_llm()` 현재 구현(`surge_evaluation_service.py:141-190`)은 상위 5개 FN 종목에 대해 종목코드·등락률만 담은 단일 프롬프트로 1회 LLM 호출한다. 출력은 자유 텍스트이며 `SurgePredictionEvaluation.miss_analysis_json`에 그대로 저장된다. SPEC-AI-041의 `analyze_and_improve()`는 탐지기 가중치(YAML 파라미터)만 상관관계 기반으로 보정할 뿐, **탐지기 로직 자체(키워드 사전, 테마 목록, 임계값)에 대한 개선 신호는 생성하지 않는다.** 결과적으로 "신약 승인 공시로 급등했으나 disclosure_impact 키워드 사전에 해당 표현이 없어 미탐지" 같은 **구체적·실행 가능한 인과**가 평가 루프에서 소실된다.

### 선행 인프라 (재사용) 및 실제 데이터 제약

| 컴포넌트 | 위치 | 용도 / 제약 |
|---|---|---|
| `analyze_misses_with_llm()` | `surge_evaluation_service.py:141` | [MODIFY] 시그니처 유지 + 내부에서 보강 컨텍스트 사용 |
| `evaluate_surge_predictions()` | `surge_evaluation_service.py:25` | TP/FP/FN 산출(재사용). predicted_set/actual_set 집합 제공 |
| `SurgeActualOutcome` | `app/models/surge_actual_outcome.py` | `trading_date`, `stock_code`, `stock_name`, `change_rate`, `was_surge`. **거래량 컬럼 없음** |
| `SurgePredictionEvaluation` | `app/models/surge_prediction_evaluation.py` | `miss_analysis_json`(Text) 존재. [MODIFY] 종목별 분석 저장 필드 추가 |
| `Disclosure` | `app/models/disclosure.py` | 실제 컬럼: `stock_code`(String(6), nullable), `report_name`, `report_type`, `ai_summary`, `rcept_dt`(YYYYMMDD **문자열**), `disclosed_at`. **`title`/`content`/`disclosure_type`/`date` 컬럼 없음** |
| `NewsArticle` | `app/models/news.py` | `news_articles` 테이블. **`stock_code` 컬럼 없음** — 종목별 뉴스는 `NewsStockRelation.stock_id`(→`Stock.id`) 조인 필수. 보유 컬럼: `title`, `summary`, `ai_summary`, `published_at`, `sentiment`, `urgency` |
| `NewsStockRelation` | `app/models/news_relation.py` | `news_id`→`news_articles.id`, `stock_id`→`stocks.id`. 종목-뉴스 다대다 연결 |
| `FundSignal` | `app/models/fund_signal.py` | `stock_id`(FK, **stock_code 컬럼 없음** — Stock 조인 필수), `signal_type`, `confidence`, `surge_metadata`(JSON), `created_at` |
| `_get_volume_history()` | `surge_detector.py` | **일봉(daily) 거래량**만 반환. 거래량 이상치는 `volumes[-1]` vs 5일 평균으로만 판단 가능(인트라데이 불가) |
| `ask_ai_with_openai_fallback()` | `ai_client.py:179` | Gemini 우선 → OpenRouter fallback. `(텍스트, 모델명)` 반환 |
| `ask_ai_free_standard()` | `ai_client.py:245` | 무료 키 전용 Standard 모델. 배치 호출 비용 절감용 후보 |
| `_run_surge_verify_predictions()` | `scheduler.py:599` | [MODIFY] 18:30 KST 평가 잡. 현재 FN만 LLM 분석 |
| `_get_prev_business_day()` | `surge_trading_service.py` | T-1 영업일 역산(재사용) |

> **데이터 제약 핵심**: (1) 뉴스는 종목코드 직접 조회 불가 — `NewsStockRelation` 조인 필수. (2) 공시 날짜는 `rcept_dt`가 `YYYYMMDD` **문자열**이므로 날짜 비교 시 문자열 변환 필요. (3) 거래량은 일봉 해상도만 가용. (4) `FundSignal`/`SurgeActualOutcome` 매칭은 항상 `Stock.stock_code`를 통해 조인.

---

## 2. Requirements (요구사항 — EARS)

### R1: 종목별 컨텍스트 보강 (Event-Driven)

- **R1.1** When 특정 급등주(`stock_code`, `trading_date`)에 대한 컨텍스트 보강이 요청되면, the 시스템 **shall** 해당 종목·해당일의 공시를 `Disclosure`에서 조회한다. 조회 조건: `Disclosure.stock_code == stock_code` AND `Disclosure.rcept_dt`(YYYYMMDD 문자열)가 `trading_date` 또는 직전 영업일과 일치.
- **R1.2** The 시스템 **shall** 해당 종목·해당일의 뉴스를 `NewsArticle`에서 조회하되, `NewsStockRelation.stock_id`(→`Stock.id`) 조인을 통해 종목을 식별하고 `published_at`이 `trading_date` 당일 또는 직전 영업일 범위인 기사만 포함한다.
- **R1.3** The 시스템 **shall** 해당 종목의 거래량 이상 여부를 일봉 거래량 이력(최근 5거래일 평균 대비 당일 거래량 배수)으로 판정하여 컨텍스트에 포함한다.
- **R1.4** The 시스템 **shall** 해당 종목에 대한 우리의 T-1 시그널 유무(TP/FN 구분)와, 시그널이 있으면 `signal_type`·`confidence`·`surge_metadata`(탐지기별 기여 점수)를 컨텍스트에 포함한다.
- **R1.5** If 특정 데이터 소스(공시·뉴스·거래량) 조회가 실패하거나 데이터가 없으면, **then** the 시스템 **shall** 해당 항목을 빈 값(빈 리스트 또는 None)으로 설정하고 나머지 보강을 계속한다(전체 실패 금지).
- **R1.6** The 시스템 **shall** 보강 결과를 구조화된 dict(키: `disclosures`, `news_headlines`, `volume_ratio`, `our_signal`)로 반환한다.

### R2: 종목별 인과 분석 LLM 호출 (Event-Driven)

- **R2.1** When 한 급등주의 보강 컨텍스트가 준비되면, the 시스템 **shall** 종목코드·등락률·공시 내용(`report_name`+`ai_summary`)·뉴스 헤드라인·거래량 배수·우리 시그널을 포함한 프롬프트로 LLM 인과 분석을 1회 호출한다.
- **R2.2** The 시스템 **shall** LLM에 구조화된(JSON) 출력을 요구한다. 필수 필드: `root_cause`(공시|테마|거래량|모멘텀|복합), `should_have_fired`(발화했어야 할 탐지기명 또는 "none"), `improvement_suggestion`(자연어 1~2문장 개선안), `confidence_note`(분석 신뢰도 한 줄).
- **R2.3** If LLM이 유효한 JSON을 반환하지 않으면, **then** the 시스템 **shall** 자유 텍스트 응답을 `improvement_suggestion`에 담고 나머지 필드를 규칙 기반 추정값(예: 공시 존재 시 `root_cause="공시"`)으로 채운 fallback 구조를 생성한다.
- **R2.4** The 시스템 **shall** 분석 결과에 입력 컨텍스트의 핵심 요약(공시 유무, 뉴스 건수, 거래량 배수, 우리 시그널 여부)을 함께 보존하여 사후 검증이 가능하게 한다.

### R3: Rate Limit 보호 배치 처리 (State-Driven + Unwanted Behavior)

- **R3.1** The 시스템 **shall** 종목별 LLM 호출 총수를 1일 1회 평가 실행당 상한(`per_stock_analysis_max_calls`, 기본 8회)으로 제한한다. FN과 TP 분석 호출의 합이 이 상한을 초과하지 않는다.
- **R3.2** The 시스템 **shall** 분석 대상 종목을 등락률 내림차순으로 우선순위화하여 상한 내에서 상위 종목부터 처리한다.
- **R3.3** While 종목별 호출을 순차 실행하는 동안, the 시스템 **shall** 각 호출 사이에 설정된 지연(`per_stock_call_delay_sec`, 기본 1.0초)을 둔다.
- **R3.4** If Gemini 일일 한도(20회) 도달 또는 LLM 연속 실패가 발생하면, **then** the 시스템 **shall** 남은 종목에 대해 LLM 호출을 중단하고 규칙 기반 fallback 분석으로 전환한다(R2.3).
- **R3.5** The 시스템 **shall** 호출당 무료 키 우선 모델(`ask_ai_free_standard` 경로)을 사용하여 유료 Gemini 키 소진을 회피한다(브리핑·시그널 생성과의 한도 충돌 최소화).

### R4: 탐지기 개선 제안 집계 (Event-Driven)

- **R4.1** When 모든 종목별 분석이 완료되면, the 시스템 **shall** 분석 결과들을 `should_have_fired` 탐지기명 기준으로 그룹화하여 탐지기별 개선 제안 목록을 생성한다.
- **R4.2** The 시스템 **shall** 각 탐지기 그룹에 대해 (탐지기명, 미발화 종목 수, 대표 종목코드 목록, 통합 개선 제안 텍스트, 빈도 기반 우선순위)를 집계한다.
- **R4.3** The 시스템 **shall** 동일 탐지기에 대한 반복 제안(예: 키워드 사전 누락이 3종목 이상)에 더 높은 우선순위를 부여한다.
- **R4.4** The 집계 결과 **shall** 자동 적용되지 않는다(휴먼 검토용 제안만). 본 SPEC은 제안 생성·기록까지만 담당하며 탐지기 코드/사전 자동 수정은 제외 범위(Section 6)다.

### R5: TP(적중) 분석 (Event-Driven)

- **R5.1** When 평가가 완료되고 TP 종목이 1개 이상 존재하면, the 시스템 **shall** TP 종목 상위 N개(등락률 내림차순, R3.1 상한 공유)에 대해 R1 컨텍스트 보강을 수행한다.
- **R5.2** The 시스템 **shall** TP 종목에 대해 "어떤 탐지기·근거로 올바르게 예측했는가"를 분석하여 강화 신호(reinforcement)를 생성한다. 출력 필드: `winning_detector`(주효한 탐지기명), `pattern_summary`(작동한 패턴 요약), `reinforce`(true/false — 해당 패턴 가중치 유지·강화 권고 여부).
- **R5.3** The 시스템 **shall** TP 분석 결과를 FN 분석과 분리된 구조로 저장하여 강화 신호와 개선 신호를 구분한다.

### R6: 기존 미스 분석 호환성 (Ubiquitous)

- **R6.1** The 시스템 **shall** `analyze_misses_with_llm(missed_stocks: list[dict], db: Session) -> str` 의 기존 시그니처와 반환 타입(str)을 유지한다(스케줄러 `scheduler.py:652` 호출부 무변경 호환).
- **R6.2** The 시스템 **shall** `analyze_misses_with_llm()` 내부에서 R1 컨텍스트 보강과 R2 인과 분석을 수행하되, 반환 문자열은 기존처럼 `miss_analysis_json` 저장에 사용 가능한 형식(종목별 분석 요약을 직렬화한 텍스트/JSON 문자열)으로 구성한다.
- **R6.3** Where 종목별 상세 분석이 필요한 신규 호출 경로가 존재하면, the 시스템 **shall** 별도 함수 `analyze_surge_cause_with_llm(stock_code, context, our_signal, db)`로 구조화된 dict를 반환하여 상세 결과를 제공한다.

### R7: 분석 결과 저장 (Event-Driven)

- **R7.1** When 종목별 분석이 완료되면, the 시스템 **shall** 종목별 분석 결과(FN 인과 + TP 강화 + 탐지기 개선 제안)를 평가일과 함께 영속화한다.
- **R7.2** The 저장 방식 **shall** `SurgePredictionEvaluation`에 `per_stock_analysis_json`(Text) 컬럼을 추가하여 평가일 단위로 종목별 분석 묶음을 저장하는 것을 기본으로 한다. (대안: 종목 단위 행을 갖는 신규 `SurgeStockAnalysis` 테이블 — plan.md에서 트레이드오프 결정.)
- **R7.3** The 시스템 **shall** 저장 데이터에 각 종목의 `stock_code`, `change_rate`, `classification`(TP/FN), `root_cause`/`winning_detector`, `should_have_fired`, `improvement_suggestion`을 포함한다.

### R8: 스케줄러 통합 (Event-Driven)

- **R8.1** When 18:30 KST `_run_surge_verify_predictions()` 잡이 실행되면, the 시스템 **shall** 기존 `evaluate_surge_predictions()` 호출 이후 강화된 FN 분석(R1~R4)과 신규 TP 분석(R5)을 실행한다.
- **R8.2** The 시스템 **shall** 통합 후에도 단일 평가 잡 실행이 전체 LLM 호출 상한(R3.1) 내에서 완료되도록 한다.
- **R8.3** If 강화 분석 단계에서 예외가 발생하면, **then** the 시스템 **shall** 예외를 로깅하고 기존 평가 결과(precision/recall/f1) 저장은 보존한다(분석 실패가 평가 실패로 전파되지 않음).

### R9: 거래일 가드 (Unwanted Behavior)

- **R9.1** If 실행일이 주말이거나 KRX 휴장일이면, **then** the 시스템 **shall** 강화 분석을 포함한 평가 잡 전체를 스킵한다(기존 `_is_kr_market_open()` 가드 재사용).

### R10: 데이터 결손 내성 (State-Driven)

- **R10.1** While 특정 종목에 대해 공시·뉴스·거래량 데이터가 모두 비어 있는 동안, the 시스템 **shall** 해당 종목을 "데이터 없음(원인 미상)"으로 분류하고 LLM 호출을 생략하여 호출 예산을 절약한다.
- **R10.2** The 시스템 **shall** 데이터 없음 종목 수를 집계 결과에 명시하여(예: "12개 FN 중 4개는 컨텍스트 데이터 없음") 분석 한계를 투명하게 보고한다.

---

## 3. Architecture (아키텍처)

### 3.1 신규/수정 서비스 함수

**`backend/app/services/surge_evaluation_service.py`** (수정 + 신규)

- `def enrich_surge_stock_context(stock_code: str, trading_date: date, db: Session) -> dict` — [신규]
  - 공시: `Disclosure.stock_code == stock_code` + `rcept_dt`(YYYYMMDD 문자열) 당일/전일 매칭 → `report_name`+`ai_summary` 추출
  - 뉴스: `NewsArticle` ⋈ `NewsStockRelation`(stock_id) ⋈ `Stock`(stock_code) + `published_at` 범위 → `title`/`summary` 헤드라인
  - 거래량: 일봉 이력 최근 5거래일 평균 대비 당일 배수(`volume_ratio`)
  - 우리 시그널: `FundSignal` ⋈ `Stock`(stock_id) + T-1 `created_at` → `signal_type`/`confidence`/`surge_metadata`
  - 반환 dict: `{disclosures, news_headlines, volume_ratio, our_signal}`
- `async def analyze_surge_cause_with_llm(stock_code: str, context: dict, our_signal: dict | None, db: Session) -> dict` — [신규]
  - R2 구조화 JSON 분석. fallback 포함. 반환 dict(`root_cause`/`should_have_fired`/`improvement_suggestion`/`confidence_note`)
- `async def analyze_true_positives_with_llm(tp_stocks: list[dict], db: Session) -> list[dict]` — [신규]
  - R5 TP 강화 분석. 종목별 `winning_detector`/`pattern_summary`/`reinforce`
- `def generate_detector_improvement_suggestions(analysis_results: list[dict]) -> list[dict]` — [신규]
  - R4 집계. 탐지기별 (탐지기명, 미발화 종목수, 대표코드, 통합제안, 우선순위)
- `async def analyze_misses_with_llm(missed_stocks: list[dict], db: Session) -> str` — [수정, 시그니처 유지]
  - 내부에서 `enrich_surge_stock_context` + `analyze_surge_cause_with_llm` 사용
  - 반환 str: 종목별 분석 요약 직렬화(기존 `miss_analysis_json` 호환)

### 3.2 LLM 호출 예산 가드 (신규 헬퍼)

- 평가 1회당 종목별 호출 카운터(상한 `per_stock_analysis_max_calls`, 기본 8). FN+TP 합산.
- 호출 간 `per_stock_call_delay_sec`(기본 1.0초) `asyncio.sleep`.
- 무료 키 경로(`ask_ai_free_standard`) 우선. 연속 실패/한도 도달 시 잔여 종목 규칙 기반 fallback.

### 3.3 DB 변경 (택1 — plan.md에서 확정)

**기본안 (Option A): `SurgePredictionEvaluation` 컬럼 추가**

| 컬럼 | 타입 | 비고 |
|---|---|---|
| per_stock_analysis_json | Text (nullable) | 종목별 FN/TP 분석 + 탐지기 개선 제안 묶음(JSON 문자열) |

마이그레이션: `061_surge_per_stock_analysis.py` (down_revision=`060_surge_auto_improvement_log`). `060_surge_auto_improvement_log.py` 헤더 형식 준수.

**대안 (Option B): 신규 `SurgeStockAnalysis` 테이블** — 종목 단위 행(평가일·종목코드·분류·근원인·제안). 종목별 조회·집계가 빈번하면 채택. 트레이드오프는 plan.md 참조.

### 3.4 설정 (surge_detection.yaml 신규 섹션)

```yaml
per_stock_analysis:
  enabled: true
  max_calls_per_run: 8        # FN+TP 합산 LLM 호출 상한
  call_delay_sec: 1.0         # 호출 간 지연
  fn_priority_over_tp: true   # 예산 부족 시 FN 우선
  skip_if_no_context: true    # 공시·뉴스·거래량 전무 시 LLM 생략
```

### 3.5 수정 파일

- `backend/app/services/scheduler.py:599` `_run_surge_verify_predictions()` — 기존 FN 블록을 강화 분석 호출로 교체/확장(R8). 예외 격리(R8.3).
- `backend/app/models/surge_prediction_evaluation.py` — `per_stock_analysis_json` 컬럼 추가(Option A 채택 시).

### 3.6 데이터 흐름

```
18:30 evaluate_surge_predictions(T)            → TP/FP/FN 집합 + precision/recall/f1
       ├─ FN 종목 → enrich_surge_stock_context → analyze_surge_cause_with_llm  (예산 내 상위 N)
       ├─ TP 종목 → enrich_surge_stock_context → analyze_true_positives_with_llm (예산 공유)
       ├─ generate_detector_improvement_suggestions(전체 분석)
       └─ per_stock_analysis_json 저장 (+ 기존 miss_analysis_json 호환 유지)
```

---

## 4. Risks (위험)

| ID | 위험 | 완화책 |
|---|---|---|
| RISK-1 | Gemini 일일 한도(20회)를 브리핑·시그널 생성과 공유 → 강화 분석이 한도 소진 | R3 종목별 호출 상한(8) + 무료 키 경로 우선 + 한도 도달 시 규칙 기반 fallback |
| RISK-2 | 뉴스 종목 매칭 누락 — `NewsArticle`에 stock_code 없어 `NewsStockRelation` 미연결 종목은 뉴스 0건 | R1.5 빈 값 처리 + R10 데이터 없음 분류·집계로 투명 보고 |
| RISK-3 | `Disclosure.rcept_dt`가 YYYYMMDD 문자열 → 날짜 비교 오류 | 문자열 포맷 변환 후 비교, 당일+직전 영업일 2일 범위 매칭 |
| RISK-4 | LLM JSON 출력 불안정(자유 텍스트 혼입) | R2.3 JSON 파싱 실패 시 fallback 구조화. 프롬프트에 JSON 스키마 명시 |
| RISK-5 | 종목별 순차 호출로 평가 잡 소요시간 증가 | R3.1 상한 8 + R3.3 지연 1초 → 최대 추가 ~수십 초. R8.2 단일 잡 예산 내 완료 |
| RISK-6 | 거래량 이상치가 일봉 해상도만 가용 → 인트라데이 급등 패턴 누락 | volume_ratio는 일봉 5일 평균 대비 배수로 한정, 분석 신뢰도(confidence_note)에 명시 |
| RISK-7 | 탐지기 개선 제안이 환각(존재하지 않는 키워드/테마 제안) | R4.4 자동 적용 금지 — 휴먼 검토 전제. 제안은 후보일 뿐 |
| RISK-8 | `analyze_misses_with_llm` 반환 형식 변경이 기존 저장 호환 깨뜨림 | R6 시그니처·반환타입(str) 동결, 내부만 강화 |

---

## 5. Success Criteria (성공 기준)

- **SC-1**: FN 종목에 대한 분석이 공시/뉴스/거래량 컨텍스트 중 1개 이상을 포함한 비율 ≥ 70% (데이터 가용 종목 기준)
- **SC-2**: 종목별 분석 결과가 `root_cause` 4분류(공시/테마/거래량/모멘텀) 중 하나로 분류되며 `should_have_fired` 탐지기명이 채워짐
- **SC-3**: 평가 1회당 LLM 호출 총수가 상한(8) 이하로 유지되고 Gemini 한도 초과 시 fallback으로 무중단 완료
- **SC-4**: `analyze_misses_with_llm()` 시그니처·반환타입 무변경 — `scheduler.py:652` 호출부 수정 없이 동작
- **SC-5**: TP 분석이 적중 종목의 주효 탐지기(`winning_detector`)를 식별하여 강화 신호 생성
- **SC-6**: 탐지기 개선 제안이 빈도 기준 우선순위와 함께 집계되어 휴먼 검토 가능한 형태로 저장
- **SC-7**: 강화 분석 실패가 기존 precision/recall/f1 저장을 막지 않음(R8.3 예외 격리)

---

## 6. Exclusions (What NOT to Build / 제외 범위)

- **탐지기 코드/사전 자동 수정 없음**: 개선 제안은 **생성·기록**까지만. 키워드 사전·테마 목록·임계값의 자동 패치는 본 SPEC 범위 밖(휴먼 검토 후 별도 작업).
- **앙상블 가중치 자동 조정 없음**: 가중치 보정은 SPEC-AI-041 `analyze_and_improve()`의 책임. 본 SPEC은 **원인 분석·개선 제안**만 담당하며 가중치를 건드리지 않는다(영역 분리).
- **신규 탐지기 추가 없음**: 기존 탐지기에 대한 개선 제안만. 새 탐지기 도입은 별도 SPEC.
- **실시간 장중 분석 없음**: 분석은 장 마감 후 18:30 KST 배치 1회. 인트라데이 분석 미포함.
- **인트라데이 거래량/시가 데이터 신규 수집 없음**: 거래량은 기존 일봉 이력만 사용. `open_price`(시가)·분봉 데이터는 가용하지 않으며 신규 수집 경로를 만들지 않는다.
- **UI 대시보드 없음**: 결과는 DB 영속화 + 기존 텔레그램 리포트 경로(SPEC-AI-041)에 요약 포함 가능. 프론트엔드 화면 미구현.
- **매수/매도 실행 없음**: 평가·분석만. 거래 실행은 `surge_trading_service` 범위.
- **과거 데이터 소급 분석 없음**: 당일(T) 평가만. 과거 평가일 일괄 재분석 배치는 제외.

---

## 7. 관련 SPEC

- **SPEC-AI-041**: 급등예측 자동평가·자가개선 루프 (선행/의존 — 본 SPEC은 그 FN 분석 단계를 강화하고 TP 분석을 신설. 가중치 조정은 AI-041 유지, 본 SPEC은 원인 분석 담당으로 영역 분리)
- **SPEC-AI-043**: 예측 기록 패러다임 전환 (본 SPEC의 평가 데이터 기반)
- **SPEC-AI-004**: 공시 충격 스코어링 (`disclosure_impact` 탐지기·키워드 사전 — 개선 제안의 주 대상)
- **SPEC-AI-012**: surge_metadata JSON 도입 (탐지기별 기여 점수 — 우리 시그널 컨텍스트의 근거)
