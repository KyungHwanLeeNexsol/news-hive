---
id: SPEC-AI-081
version: 0.3.0
status: draft
created: 2026-07-15
created_at: "2026-07-15"
updated: 2026-07-15
author: Nexsol
priority: High
issue_number: null
lifecycle_level: 1
labels: [disclosure-scoring, surge-detection, backend]
---

# SPEC-AI-081: 공시 충격 스코어링 flat-base 카테고리의 콘텐츠 인식 정밀화 (Disclosure Impact Scoring — Content-Aware Refinement for Flat-Base Categories)

## HISTORY

- 2026-07-15 (v0.1.0): 최초 작성. 2026-07-13→07-14 및 2026-07-09→07-10 두 독립 일자쌍 실거래
  포렌식(SSH+DB+코드 대조)에서 확정된 "scannable 미탐 100%(4/4, 14/14)" 근본원인 조사를 이어받아,
  그중 `disclosure_impact_scorer.py`의 `_BASE_IMPACT_BY_TYPE` flat 카테고리(주요사항보고/지분공시
  등 5종) 문제를 SPEC화. 연구 단계에서 제시된 2개 개선 후보(ai_summary 콘텐츠 인식 확장, report_name
  키워드 기반 재분류)를 코드 재검증한 결과 **2건의 중대 정정**이 발견되어 요구사항을 재설계함
  (§2 연구 정정 참조). 상세 근거는 `C:\Users\Nexsol\.claude\projects\C--Users-Nexsol-Documents-news-hive\memory\project_surge_disclosure_scoring_root_cause_2026_07_15.md`(스냅샷, 코드 대조로 재검증 완료).
- 2026-07-15 (v0.2.0): plan-auditor 독립 검토(iteration 1, FAIL) 결과를 반영해 개정. (1) acceptance.md
  8개 AC를 Given/When/Then에서 EARS 문장 패턴으로 전면 재작성(수치 단정값은 그대로 보존). (2)
  YAML frontmatter에 `created_at`/`labels` 필드 추가. (3) REQ-003에 대응 AC(AC-081-009)와 plan.md
  구현 단계 부재를 보완. (4) REQ-001/002/004/006/007의 SHALL 절 본문에 섞여 있던 코드 리터럴·내부
  함수명·설정키 리터럴을 근거(rationale) 각주로 이동하고 SHALL 절 본문은 행위/결과 서술로 재작성.
  (5) OQ-1(REQ-002 재분류 스코어 값 미확정)을 설계 결정으로 승격 — 발행공시 flat 기본값 `-10`을
  그대로 상속하는 것으로 확정하고 열린 질문에서 제거, plan.md와 일관화. priority 대소문자(`High`)는
  이 프로젝트의 SPEC-AI 계열 전체가 일관되게 대문자를 사용함을 확인하여 그대로 유지(다른 SPEC과의
  불일치 방지).
- 2026-07-15 (v0.3.0): plan-auditor 독립 검토(iteration 2, FAIL — MP-2 EARS 형식 준수만 미충족)
  결과를 반영해 개정. (1) acceptance.md의 WHILE+WHEN 혼합 문장 5건을 각각 단일 EARS 패턴으로 분리
  (AC-081-001/002 RED 특성화 bullet은 WHILE 전제를 비-EARS 서술 전제문으로 분리 후 순수 WHEN 문장화,
  AC-081-005 bullet 1-2는 WHEN 키워드를 제거하고 순수 State-Driven(WHILE) 문장화, AC-081-006 bullet
  1은 WHILE 전제를 제거하고 순수 Event-Driven(WHEN) 문장화). (2) AC-081-002의 "(명시 비검증)" 항목을
  정규 SHALL 기준 bullet 목록에서 분리해 비정규(non-EARS) 참고 문단으로 재구성(범위 편차 고지의 로컬
  재확인, 통과 기준 아님을 명시). (3) Optional 패턴(AC-081-008 bullet 1, REQ-AI081-008)에서 관례에
  어긋나는 `MAY`를 `SHALL`로 교체 — 이 프로젝트의 SPEC-AI-078/079가 확립한 "WHERE [조건], the system
  SHALL [응답]" Optional 패턴 관례(진정한 선택성은 P2/선택 라벨과 WHERE 조건으로 표현, MAY는 모달
  동사로 사용하지 않음)에 정합화.

---

## 1. Overview (개요)

### 문제

`evaluate_surge_predictions()`의 `scannable_recall`(사전 선별된 T-1 스캔 유니버스 내 실제 급등 종목
탐지율)이 두 독립 일자쌍(2026-07-13→07-14: 4/4, 2026-07-09→07-10: 14/14)에서 **100% 미탐**으로
확정되었다. 2026-07-14 조사(`disclosures` 테이블 07-13 접수분 포렌식)로 그중 3건의 미탐이 공통 원인을
공유함이 드러났다: `disclosure_impact_scorer.py`의 `score_disclosure_impact()`가 특정 `report_type`
카테고리(주요사항보고/지분공시 등)에 대해 **콘텐츠와 무관한 flat 기본값**을 부여해, 실제로는 재료가
있는 공시도 어떤 시그널 임계(기준가 스냅샷 ≥20 / gap_pullback ≥25 / 섹터파급 ≥30 / SPEC-AI-080
즉시발화 min_impact 기본 40)도 넘지 못하는 문제다.

**실증 사례 (2026-07-13 접수 → 2026-07-14 실제 급등):**

| 종목 | report_name | report_type | impact_score | 실제 익일 변동 |
|------|-------------|-------------|---------------|----------------|
| 465770 STX그린로지스 | "투자판단관련주요경영사항"(범용 캐치올) | 주요사항보고 | 20 | **+29.92%** |
| 038880 아이에이 | "주요사항보고서(전환사채권발행결정)" | 주요사항보고 | 20 | **+16.62%** |
| 006340 대원전선 | "최대주주등소유주식변동신고서" | 지분공시 | 25 | **+17.84%** |

같은 날 4번째 scannable 미탐 006120 SK디스커버리(+11.87%)는 공시·뉴스가 전혀 없는 순수 가격/거래량
급등이며, 이는 탐지 아키텍처 사안(볼륨/모멘텀 탐지기)이지 공시 스코어링 문제가 아니므로 본 SPEC
범위에서 **명시 제외**한다(§4 [X-7]).

07-09→07-10 일자쌍(14/14 scannable 미탐, SPEC-AI-080 기폭제였던 226330 신테카바이오 포함)이 동일
recall=0 패턴을 재확인하지만, `disclosures` 5일 보존 정책(`scheduler.py`, 의도된 설계)으로 인해
2026-07-15 현재 `rcept_dt < 20260710` 행이 이미 삭제되어 공시별 정밀 포렌식은 불가능하다 — 이
일자쌍에 대한 증거는 recall=0이라는 집계 사실로 한정된다(§2 제약).

### 목표

`score_disclosure_impact()`가 이미 보유한 콘텐츠 인식 메커니즘(키워드 Tier 배수, 계약금액/시총 비율,
실적변동 %추출)을 flat-base 카테고리(주요사항보고/지분공시)까지 정밀하게 확장하여, (a) 실제 재료가
있는 공시가 정당한 근거로 더 높게 평가되고, (b) 재료 없는 공시는 인위적으로 부풀려지지 않도록 한다.

---

## 2. Environment & Assumptions (환경 및 가정)

- Backend: Python 3.13+, FastAPI, SQLAlchemy 2.0, PostgreSQL(프로덕션)/SQLite(테스트).
  개발 방법론: DDD(ANALYZE-PRESERVE-IMPROVE, `.moai/config/sections/quality.yaml`
  `development_mode: ddd`).

### 코드 검증 완료 (2026-07-15, read-only) — 연구 단계 대비 정정 사항

- [E-1] **`score_disclosure_impact()`(disclosure_impact_scorer.py:167-217)의 실제 흐름을 확인함.**
  루틴 거버넌스 캡(`:182-183`, 5.0 조기 반환) → 계약공시 경로(`:186-194`, 존재 시 조기 반환) →
  실적변동 %추출(`:197-206`, 존재 시 조기 반환) → **위 세 경로 모두 해당 없을 때만** `base =
  _BASE_IMPACT_BY_TYPE.get(report_type, 10)`(`:209`) 적용 후 **키워드 Tier 배수는 이 flat 분기에도
  이미 적용된다**(`:215-217`, `multiplier = _get_keyword_tier_multiplier(report_name, ai_summary)`).
- [E-2] **[연구 정정 #1] "flat 카테고리는 ai_summary를 전혀 읽지 않는다"는 원 조사 서술은 부정확하다.**
  `_get_keyword_tier_multiplier(report_name, ai_summary)`(`:96-109`)는 `text = report_name + " " +
  (ai_summary or "")`로 **모든 report_type에 대해 report_name+ai_summary를 함께 읽는다** — 실제
  차이는 "ai_summary를 읽는지 여부"가 아니라, **Tier1/2/3 키워드 목록(`:89-93`, 총 14개 리터럴
  문자열)이 실제 DART 표준 제목 변형을 충분히 포괄하지 못한다**는 것이다. 3건 실증 사례를 키워드
  목록과 대조하면: 465770("투자판단관련주요경영사항")은 14개 키워드 어디에도 매칭되지 않고(진짜
  무신호), 038880("주요사항보고서(전환사채권발행결정)")도 매칭 없음(전환사채 관련 키워드 자체가
  Tier 목록에 부재), 006340("최대주주등소유주식변동신고서")은 Tier1 "최대주주 변경"(공백 포함
  리터럴)과 **"등소유주식변동" 접미부 불일치로 매칭 실패** — DART 표준 제목은 "최대주주 변경"이
  아니라 "최대주주{등}소유주식{변동}신고서" 형태이기 때문. 즉 **006340은 키워드 커버리지 갭 문제이며,
  ai_summary 존재 여부와 무관**.
- [E-3] **[연구 정정 #2 — 핵심] `ai_summary`는 DART 수집 시점(`score_disclosure_impact()` 실행
  시점)에 사실상 항상 `None`이다.** `dart_crawler.py`의 `Disclosure(...)` 생성자 호출(`:203-213`)은
  `ai_summary`를 전달하지 않는다(nullable 컬럼, 기본 `None`). `ai_summary`를 채우는 유일한 경로는
  `disclosures.py` 라우터의 `POST /api/disclosures/{id}/summary`(`:78-107`) — **프런트엔드에서
  사용자가 공시 상세를 조회할 때만 온디맨드로 생성**되며, DART 수집 파이프라인(`dart_crawler.py` →
  `_score_new_disclosures()` → `process_disclosure_impact()`)과는 **연결되어 있지 않다**. 또한 이
  생성 함수(`ai_classifier.generate_disclosure_summary`, `:622-644`)는 `report_name`+`report_type`+
  `corp_name`만 인자로 받는 LLM 프롬프트로, **DART 공시 원문 본문을 조회하지 않는다** — 즉 나중에
  채워지더라도 `report_name`에 이미 없는 새 정보(금액·비율 등)를 제공하지 못한다. 따라서 원 개선
  후보 #1("ai_summary가 비어있지 않을 때 콘텐츠 인식 확장")은 **전제 자체가 실무에서 거의 발동하지
  않는다** — 1차 신호원은 `report_name`이어야 한다(REQ-003).
- [E-4] **[연구 정정 #3] "DART 자체 분류"라는 원 조사 서술도 부정확하다.** `report_type`은 DART API가
  제공하는 값이 아니라, **이 프로젝트 자체의 `dart_crawler._classify_report_type()`**(`:90-95`)가
  `_REPORT_TYPE_PATTERNS`(`:29-72`, 순서 있는 리스트, 첫 매칭 우선)로 `report_name`을 정규식이 아닌
  단순 부분 문자열 매칭한 결과다. **버그의 정확한 메커니즘 확인**: 패턴 리스트에 `("전환사채",
  "발행공시")`(`:45`)가 이미 존재하지만, 그보다 **앞에** `("주요사항보고서", "주요사항보고")`(`:36`)가
  있다. DART의 CB 발행결정 공시 제목은 관례적으로 "주요사항보고서(전환사채권발행결정)"처럼
  **"주요사항보고서" 래퍼 접두사 안에 세부 결정 유형을 괄호로 담는 형식**이므로, 첫 패턴("주요사항
  보고서")이 먼저 매칭되어 반환되고 뒤쪽의 "전환사채" 패턴에 도달하지 못한다(첫 매칭 우선 루프,
  `:92-94`). **이것은 DART 기준의 오분류가 아니라 이 프로젝트 자체 분류기의 패턴 우선순위 버그다.**
- [E-5] 루틴 거버넌스 캡(`_ROUTINE_GOVERNANCE_KEYWORDS`, `:57-71`)은 스코어링 함수 최상단에서 조기
  반환(`:182-183`)하므로, 본 SPEC의 신규 로직(Tier 배수 이후 단계)과 **상호 배타적**이다 — 루틴으로
  판정된 공시는 신규 로직 도달 전에 5.0으로 확정된다(회귀 위험 낮음).
- [E-6] 계약금액 추출(`extract_contract_amount`, `:139-164`)은 조/억/백만원 단위 한국어 금액 문자열
  파서로, 계약공시 경로 전용이 아닌 범용 함수다. 038880/465770/006340 세 실증 사례의 `report_name`
  어디에도 금액 문자열이 없어(직접 확인) 이 함수로 새 정보를 추출할 수 없다 — 즉 이 세 사례에 대해
  "얼마나 더 높일지"를 계산할 수 있는 근거 데이터가 없다(§ REQ-002 범위 결정에 영향).

### 가정

- [A-1] `report_name`은 500자 컬럼(`disclosure.py:17`)이며 DART 원문 요약 제목만 담는다 — 원문 본문은
  이 시스템에 저장/조회되지 않는다(§4 [X-1]).
- [A-2] Tier1/2/3 키워드 목록(`_KEYWORD_TIER1/2/3`)과 `_ROUTINE_GOVERNANCE_KEYWORDS`/`_MNA_KEYWORDS`는
  모두 **리터럴 부분 문자열 매칭**(정규식 아님) 방식이며, 본 SPEC도 이 기존 스타일을 따른다(일관성,
  Run 단계에서 정규식 전환은 별도 결정 없이는 하지 않음).
- [A-3] `_REPORT_TYPE_PATTERNS`가 이미 "전환사채"→"발행공시" 매핑을 보유하므로, 038880형 재분류는
  **새 개념을 도입하는 것이 아니라 이미 존재하는 이 프로젝트 자체 분류 의도를 스코어링 단계에서
  로컬로 복원하는 것**이다(§4 [X-2] — `dart_crawler.py` 자체는 변경하지 않음, 블라스트 반경 최소화).

---

## 3. Requirements (EARS)

### REQ-AI081-001 (Ubiquitous, P0) — 최대주주 지배권 변경 키워드 커버리지 확장

the system **SHALL** 최대주주 지배권 변경을 나타내는 DART 표준 공시 제목 형식(예: "최대주주등소유
주식변동신고서" — 공백·조사 변형 포함)을 기존 Tier1(×2.0) 수준의 신호로 인식하도록 키워드 커버리지를
확장해야 한다. 이 인식은 공백·특수문자 표기 변형을 정규화한 후 수행 SHALL 한다(기존 루틴 여부 판정이
사용하는 정규화 방식과 일관되게).

- 근거(§2 [E-2]): 006340 사례가 현재 미탐지되는 이유는 ai_summary 부재가 아니라 기존 Tier1 키워드
  "최대주주 변경"의 리터럴 문자열이 실제 DART 표준 제목과 불일치하기 때문이다. 구현 참고: 기존
  키워드 Tier 배수 판정 함수(`_get_keyword_tier_multiplier`)에서 매칭 전 텍스트를 기존 루틴 판정
  (`_ROUTINE_GOVERNANCE_KEYWORDS`) 매칭이 이미 사용하는 정규화 패턴(`.replace(" ",
  "").replace("·", "")`)과 일관되게 처리한다(구체 구현은 plan.md §2 참조).

### REQ-AI081-002 (Event-Driven, P0) — 희석성 증권 발행결정의 로컬 재분류

**WHEN** 공시의 report_type이 "주요사항보고"이고 report_name이 희석성 증권 발행 결정을 나타내는
키워드(전환사채/신주인수권/교환사채/유상증자/무상증자/파생결합증권)를 포함하면, the system **SHALL**
이 공시를 "발행공시" 카테고리와 동일한 스코어링 경로로 처리해야 한다 — 이 경로는 발행공시 카테고리의
기존 flat 기본값을 그대로 상속하며, 별도의 완화된 로직(예: 하한 클램핑)은 신설하지 않는다(설계 결정,
§7 참고 — 舊 OQ-1 확정).

- **SHALL NOT** 이 재분류는 공시의 report_type 저장값이나 이 프로젝트 자체 report_type 분류기의
  판정 순서를 변경해서는 안 된다 — 변경 범위는 공시 충격 스코어링 로직 내부로 국한한다(§4 [X-2]).
- 근거(§2 [E-4]): DART 표준 제목의 "주요사항보고서(...)" 래퍼 접두사가 이 프로젝트 자체 분류기의
  더 구체적인 "발행공시" 패턴을 가로채는 우선순위 버그가 근본 원인이며, report_type 자체를
  재정렬하면 이 값을 소비하는 다른 화면/필터(disclosures 라우터 report_type 쿼리, SPEC-AI-028
  disclosure_type_filter)까지 블라스트 반경이 넓어지므로 스코어링 국소 재분류로 범위를 좁힌다.
  구현 참고: 재분류 키워드 세트는 `dart_crawler._REPORT_TYPE_PATTERNS`의 "발행공시" 매핑 키워드와
  동일 세트를 스코어링 전용으로 로컬 재사용하며, `Disclosure.report_type` 저장값이나
  `dart_crawler._classify_report_type()`의 패턴 순서는 변경하지 않는다(구체 구현은
  `disclosure_impact_scorer.py` 내부, plan.md §3 참조).
- 설계 결정(舊 OQ-1 확정, 단순성 우선 — CLAUDE.md Agent Core Behavior #4): 재분류된 공시는 발행공시
  카테고리의 기존 flat 기본값(`-10`)을 그대로 상속한다. 이 결정의 목적은 038880형 사례의 점수를
  상향시키는 것이 아니라 "동일 경제적 사건에 대한 일관된 처리"이며, report_name만으로는 희석 신호의
  방향성(호재/악재)을 판별할 근거 데이터가 없으므로(§2 [E-6]) 인위적 상향은 명시적으로 배제한다
  (§4 [X-9]).

### REQ-AI081-003 (Unwanted, P0) — ai_summary를 1차 신호원으로 의존 금지 [HARD]

**WHILE** REQ-001/002의 콘텐츠 인식 로직을 설계·구현하는 동안, the system **SHALL NOT** `ai_summary`
필드의 값 존재를 1차 또는 필수 신호원으로 의존해서는 안 된다.

- 근거(§2 [E-3]): DART 수집 직후 `process_disclosure_impact()` 실행 시점에 `ai_summary`는 사실상
  항상 `None`이다(생성 경로가 프런트엔드 온디맨드 API 호출로만 존재, DART 수집 파이프라인과
  미연결). 1차 신호원은 `report_name`으로 하고, 기존 `report_name + ai_summary` 병합 검색 텍스트
  패턴(`_get_keyword_tier_multiplier`)은 우연히 채워진 경우를 위한 방어적 보강으로만 유지한다
  (기존 거동 보존, 신규 별도 ai_summary 전용 경로를 만들지 않음).

### REQ-AI081-004 (State-Driven, P0) — 설정 플래그 게이팅, 기본값 비활성 [HARD]

**WHILE** 콘텐츠 인식 스코어링을 제어하는 신규 설정 플래그가 비활성(기본값)인 동안, the system
**SHALL** 공시 충격 스코어링의 기존(레거시) 거동을 7개 report_type 카테고리 전부에 대해 정확히
보존해야 한다 — 기존 회귀 테스트 전량이 코드 변경 없이 그대로 통과.

- 근거: SPEC-AI-079(상대 스코어링 z-score 게이팅)/SPEC-AI-080(즉시발화 게이팅)이 확립한 공유 고
  fan-in 스코어링 코드 변경 시 기본값 OFF 롤아웃 패턴을 계승한다(공시 제약 사항). 구현 참고: 플래그
  키 예시 `disclosure_content_aware_scoring.enabled`, 대상 함수 `score_disclosure_impact()`, 회귀
  테스트 파일 `test_disclosure_impact_scorer.py`(구체 구현은 plan.md §1 참조).

### REQ-AI081-005 (Unwanted, P0) — 무신호 공시 인플레이션 금지 (오탐 회귀 방지) [HARD]

**IF** 대상 카테고리(주요사항보고/지분공시)의 공시 `report_name`(및 우연히 존재하는 `ai_summary`)에
REQ-001/002가 정의한 신호 키워드가 전혀 매칭되지 않으면(예: 465770형 범용 캐치올 제목
"투자판단관련주요경영사항"), **THEN** the system **SHALL NOT** 기존 flat 기본값(주요사항보고 20 /
지분공시 25) 대비 점수를 상향해서는 안 된다.

- 근거: 신호가 없는 공시에 점수를 인위적으로 부풀리면 오탐(false positive) 표면이 넓어진다 —
  신호 부재 시 flat 기본값이 정직한 하한으로 유지되어야 한다.

### REQ-AI081-006 (Ubiquitous, P0) — 범위 한정 (다른 카테고리·소비자·필드 불변) [HARD]

the system **SHALL NOT** 다음을 변경해서는 안 된다:

- (a) 주요사항보고/지분공시 외 5개 report_type 카테고리(실적변동/기업지배구조/발행공시/정기공시/
  기타공시)의 기존 스코어링 로직 및 관련 기존 테스트 결과값.
- (b) 공시 충격 점수를 입력으로 사용하는 하위 소비 기능(기준가 스냅샷 트리거, 갭 되돌림 트리거,
  섹터 파급 탐지, 즉시발화 게이팅 등)의 임계값·게이팅 로직 자체 — 이들이 입력받는 impact_score
  **값**만 변경될 수 있을 뿐, 게이팅 **로직**은 무변경.
- (c) 공시의 report_type 저장값 또는 이 프로젝트 자체 report_type 분류기의 패턴 정의·순서(REQ-002
  근거 참조).

- 구현 참고: 하위 소비 함수는 `process_disclosure_impact`/`_create_immediate_surge_signal`/
  `detect_sector_ripple`/`detect_unreflected_gap`이며, 임계값은 ≥20 기준가 스냅샷 / ≥25
  gap_pullback / ≥30 섹터파급 / `immediate_surge.min_impact` 즉시발화다. report_type 저장값은
  `Disclosure.report_type`, 분류기는 `dart_crawler._classify_report_type()`이다(구체 구현은
  plan.md §3 참조).

### REQ-AI081-007 (Unwanted, P0) — 변경 전 특성화 테스트 선행 [HARD]

**IF** 공시 충격 스코어링 함수 또는 그 하위 소비자에 대한 변경이 이루어지면, **THEN** 그 변경
이전에 기존 거동을 고정하는 특성화 테스트가 작성·통과되어 있어야 SHALL 한다(DDD ANALYZE-PRESERVE,
재현 우선 원칙 — CLAUDE.md Rule 4). 이 함수는 이미 상당한 기존 테스트 커버리지가 있으므로, 신규로
필요한 것은 (i) 3개 실증 사례(465770/038880/006340)형 시나리오의 수정 전 flat 거동 재현 테스트,
(ii) 하위 소비자 게이팅 임계 로직이 새 점수값에도 동일하게 동작함을 확인하는 통합 테스트.

- 구현 참고: 대상 함수는 `score_disclosure_impact()`이며, 기존 테스트 스위트는
  `TestScoreDisclosureImpact`다(구체 구현은 plan.md §5 참조).

### REQ-AI081-008 (Optional, P2) — 관측성 (선택)

**WHERE** REQ-001/002의 재분류·키워드 확장이 실제로 트리거된 경우, the system **SHALL** flat 기본값
대비 점수가 변경되었음을 나타내는 로그를 방출한다. 신규 테이블/컬럼/마이그레이션 금지, 종목별 INFO
스팸 금지. (본 REQ 전체가 P2/선택 요구사항이며, 선택성은 이 라벨과 트리거 조건으로 표현한다 — SHALL
자체는 조건 충족 시 확정적 응답을 서술한다.)

---

## 4. Exclusions (What NOT to Build) [HARD]

본 SPEC은 다음을 **명시적으로 범위에서 제외**한다:

- [X-1] **DART 공시 원문 본문 수집/파싱 기능 신설 금지.** 465770형(범용 캐치올 제목 "투자판단관련
  주요경영사항") 사례는 `report_name`에도 `ai_summary`(§2 [E-3], 제목 기반 생성이라 동일하게
  무정보)에도 추출 가능한 신호가 전혀 없다 — 이 시스템은 DART 원문 본문을 저장/조회하지 않는다.
  이 유형의 미탐은 본 SPEC으로 해결 불가하며, 별도의 훨씬 큰 SPEC(원문 수집 파이프라인 신설)이
  필요한 후속 후보다(§8). 본 SPEC에서는 이 사례를 **오탐 방지(REQ-005) 음성 대조군**으로만 사용한다.
- [X-2] **`dart_crawler.py::_classify_report_type()` 및 `Disclosure.report_type` 저장값 변경
  금지.** REQ-002의 재분류는 `disclosure_impact_scorer.py` 내부 스코어링 로직에 국한한다(REQ-006
  (c)). `report_type` 저장값은 disclosures 라우터 필터, SPEC-AI-028 `disclosure_type_filter` 등
  다른 소비자가 의존하므로 변경 시 블라스트 반경이 크게 확대된다.
- [X-3] **SPEC-AI-080 `immediate_surge.enabled` 활성화 또는 이벤트 클래스 화이트리스트 변경
  금지.** 게이팅 로직·임계값은 그대로, 입력되는 `impact_score` 값만 영향받을 수 있다.
- [X-4] **`auto_improve_enabled` 플래그 변경 금지.**
- [X-5] **`disclosures` 5일 보존 정책 변경 금지** — `scheduler.py`의 의도된 설계.
- [X-6] **`near_limit_up_carry`(SPEC-AI-072/075) 로직 변경 금지.**
- [X-7] **006120형(공시·뉴스 전무 순수 가격/거래량 급등) 탐지 아키텍처 개선은 범위 밖** — 공시
  스코어링과 무관한 볼륨/모멘텀 탐지기 사안.
- [X-8] **신규 테이블/스키마/마이그레이션 금지, 과거 데이터 소급 재계산·백필 금지**(전진 적용만,
  SPEC-AI-071/079/080 관례 계승).
- [X-9] **[핵심 — 연구 정정 반영] 038880형(전환사채 등 재분류 대상) 사례가 이 SPEC 완료 후 반드시
  flat +20보다 "더 높은" 점수를 받는다고 보장하지 않는다.** 희석성 증권 발행은 본질적으로 양면적
  신호(희석 부담 vs. 자금조달 용도에 따른 호재 가능성)이며, `report_name`만으로는 이 방향성을
  판별할 근거 데이터가 없다(§2 [E-6], 세 사례 모두 금액/용도 문자열 부재 확인). REQ-002의 목적은
  "동일 경제적 사건(희석성 증권 발행)에 대한 일관된 처리"이지 "이 특정 과거 사례의 사후적 점수
  상향"이 아니다. 이 방향성을 인위적으로 상향 고정하면 실제로는 하락 압력이 큰 통상적 CB/증자
  공시 전반에 오탐을 유발할 위험이 커지므로 명시적으로 배제한다(acceptance.md에서 "차등 처리"로
  검증, "상향"으로 검증하지 않음).

---

## 5. Risks (리스크)

- [R-1] **키워드 확장 오탐 리스크.** 최대주주 키워드 정규화 매칭 범위를 너무 넓히면 루틴 지분 변동
  공시까지 상향될 수 있다. 완화: (i) 매칭은 "최대주주" + 변경/변동 계열 어근 공존으로 한정(§2 [A-2]
  일관된 리터럴 매칭 스타일 유지), (ii) 기존 루틴 캡(`_ROUTINE_GOVERNANCE_KEYWORDS`)이 스코어링
  함수 최상단에서 먼저 조기 반환되므로(§2 [E-5]) 이미 루틴으로 판정된 지분공시는 신규 로직에
  도달하지 않아 상호 배타적, (iii) 루틴이 아니면서 "최대주주"가 없는 일반 지분공시(예: 5%/10% 룰
  비지배주주 신고)는 신규 키워드에 매칭되지 않아 flat 25 유지(REQ-005 검증).
- [R-2] **공유 고 fan-in 스코어링 함수 회귀 리스크.** `score_disclosure_impact()`는
  `process_disclosure_impact`/`_create_immediate_surge_signal`(SPEC-AI-080)/`detect_sector_ripple`
  /`detect_unreflected_gap`의 입력이다. 완화: REQ-007 특성화 테스트 + 전체 백엔드 회귀 스위트
  (기본 실행 + `-n 4` xdist 병렬) + ruff.
- [R-3] **038880 사례 기대치 불일치 리스크.** 연구 단계 개선 후보는 3개 실증 사례 모두 "점수 상향"을
  암묵적으로 기대했으나, 038880형은 방향성 보장이 불가능함을 코드 재검증으로 확인(§2 [E-6]).
  완화: [X-9]에 명시적으로 문서화, acceptance.md는 038880을 "차등 처리(differentiation)" 기준으로
  검증하고 "상향(increase)" 기준으로는 검증하지 않는다 — 사용자/오케스트레이터에게 이 편차를 명확히
  전달(본 SPEC 최상위 편차).
- [R-4] **Tier1 키워드 정규화가 기존 정확-문자열 매칭 테스트에 영향을 줄 위험.** 완화: 정규화는
  매칭 폭 확장(추가 변형 인식)만 수행하고 기존 정확 매칭 사례("합병계약 체결" 등)의 결과값은
  그대로 유지되어야 한다 — 기존 회귀 테스트로 확인.

---

## 6. Related SPECs (관련 SPEC)

- **SPEC-AI-004 (선행)**: `disclosure_impact_scorer.py`/`score_disclosure_impact` 원 소유. 본 SPEC은
  이를 확장.
- **SPEC-AI-051 (선행, 메커니즘 소유 불변)**: Tier1/2/3 키워드-배수 메커니즘(`_get_keyword_tier_multiplier`)
  소유. 본 SPEC은 키워드 **커버리지**만 확장하고 메커니즘(곱셈 배수 구조) 자체는 변경하지 않는다.
- **SPEC-AI-080 (인접/소비자, 불변)**: `impact_score`를 즉시발화 게이팅(`min_impact`)에 사용. 게이팅
  임계·로직 불변, 입력값만 영향받을 수 있음(REQ-006 (b)).
- **SPEC-AI-028 (인접, 불변)**: `disclosure_type_filter`가 `report_type` 저장값을 사용. 본 SPEC은
  `report_type`을 변경하지 않으므로 무관/불변([X-2]).
- **SPEC-AI-079 (참고 패턴)**: 공유 고 fan-in 코드 변경 시 config 플래그 기본값 OFF 롤아웃 패턴을
  계승(REQ-004).

---

## 7. Open Questions (열린 질문 — Run 단계 확정)

- [OQ-1] **최대주주 키워드 정규화의 정확한 패턴 세트.** "최대주주" + {변경, 변동, 교체} 등 어근
  공존 판정의 정확한 구현(정규화 문자열 치환 vs. 다중 키워드 리스트)은 Run 단계에서 실제 DART 표준
  제목 샘플 몇 건을 추가 확인 후 확정.
- [OQ-2] **REQ-008 관측성 로그의 정확한 트리거 조건과 필드 구성.** P2 선택 사항이며 001~007의
  블로커가 아니다.

**참고 (舊 OQ-1 해소)**: REQ-002 재분류 시 어떤 스코어 로직을 재사용할지는 舊 OQ-1이었으나, 발행공시
flat `-10`을 그대로 상속하는 것으로 확정되어 REQ-AI081-002의 "설계 결정"으로 승격되었다(열린
질문에서 제거). 계약금액 추출을 CB/증자 발행 규모에도 시도해볼지(대부분 실패할 것으로 예상, §2
[E-6])는 여전히 Run 단계에서 비용 대비 가치로 판단할 사항이나 블로커는 아니다.

---

## 8. Follow-up Candidates (후속 후보 — 본 SPEC 범위 밖)

- DART 공시 원문 본문 수집/파싱 파이프라인 신설([X-1]) — 465770형 캐치올 제목 문제의 근본 해결.
  별도 대형 SPEC, 외부 API/파싱 리스크 있어 충분한 별도 조사 필요.
- 006120형 순수 가격/거래량 급등(무재료) 탐지기 신설([X-7]) — SPEC-AI-080 [X-5]에서도 이미 유예된
  동일 계열 사안. 오탐 위험 커 수일 관찰 후 판단.
