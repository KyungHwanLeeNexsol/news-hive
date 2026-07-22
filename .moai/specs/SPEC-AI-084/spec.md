---
id: SPEC-AI-084
version: 0.2.0
status: in-progress
created: 2026-07-22
created_at: "2026-07-22"
updated: 2026-07-22
author: Nexsol
priority: High
issue_number: null
lifecycle_level: 1
labels: [surge-detection, theme-propagation, keyword-basket, news-urgency, keyword-tagging, recall, backend]
---

# SPEC-AI-084: 뉴스 기반 산업 테마 전파 예측 (News-Driven Industry-Theme Surge Propagation)

## HISTORY

- 2026-07-22 (v0.1.0): 최초 작성 (Plan 단계 — 구현 미포함). 2026-07-22 라이브 감사에서
  **삼성전자 로봇 전담조직(RX사업추진실) 발표발 로봇 테마 전 시장 랠리**를 시스템이 구조적으로
  놓친 사건을 근본원인으로 삼는다. 당일 실제 +10% 이상 급등한 52종목 중 **후보 신호가 하나라도
  발신된 것은 5종(9.6%)**, 그중 진짜 사전예측은 1종뿐(나머지는 이미 움직인 뒤 사후 태깅 — 
  `fund_signals.price_at_signal`을 전일 종가와 대조해 확정). 47건 미탐 중 10건 이상이 단일 사건
  (로봇 테마 랠리, 비계열 종목으로 전파)에 귀속됨을 확인했다. 사용자가 AskUserQuestion으로 세
  개선 방향을 **모두 함께** 추진하기로 선택함에 따라, 상호 의존하는 세 역량(키워드 인프라 →
  긴급도 재보정 → 뉴스 테마 전파 탐지기)을 하나의 SPEC에 **세 REQ 그룹**으로 명세한다.
  단일 SPEC vs 분할 판단 근거는 plan.md §단일 SPEC 결정 참조.
  - **코드 근거 확정(read-only, 2026-07-22)**: 세 근본원인 모두 실제 코드로 검증됨(§2 [E-1]~[E-3]).
  - **범위 명시적 제외(사용자 확인 완료)**: "제로 리드타임 동일-순간 뉴스발 첫 급등 종목(first mover)
    예측"은 인사이더 정보 없이는 물리적으로 불가능하므로 본 SPEC의 목표·인수기준에서 명시적으로
    제외한다(§4 [X-1]). 현실적·측정가능한 목표는 "테마 앵커 이벤트가 확인된 후, 아직 움직이지
    않은 동일 테마 바스켓 멤버에게 그들의 가격 이동 이전에 리드타임(분~시간)을 두고 후보 신호를
    전파"하는 것이다(계열 그룹에 대해 `theme_group_carry`가 하는 일을 키워드 정의 산업 테마로 확장).

- 2026-07-22 (v0.2.0): plan-auditor 반복 1 FAIL 대응(iteration 2). 감사 보고서
  `.moai/reports/plan-audit/SPEC-AI-084-review-1.md` 3개 지적 반영.
  - **(MP-2, critical)** acceptance.md 17개 AC 전부를 Given-When-Then 단독 서술에서 **볼드 EARS 정규
    문장**(the system **SHALL**/**SHALL NOT** + 단일 트리거)으로 전환하고, 기존 GWT는 비규범 재현
    시나리오로 병기. SPEC-AI-081 iteration 2 교정 패턴을 준수한다 — 각 EARS 문장은 트리거 키워드
    1개(**WHEN**/**WHILE**/**IF**/**WHERE**) + SHALL/SHALL NOT 절 1개만 포함하며, 복합 2-절 문장·
    em-dash 결합 2차 정규 절·볼드 SHALL과 비형식 한국어 모달 혼용을 금지한다(SPEC-AI-081-review-3.md
    D1/D2 교훈).
  - **(REQ-013 major)** REQ-AI084-013/AC-084-013의 same-day 지평 귀속을 구체 계약으로 명명.
    전파-생성 `fund_signals` 신호는 `surge_metadata["horizon"] = "same_day"`를 **설정**해야 하며
    (REQ-009의 `surge_basis=["theme_news_carry"]` 명명과 동형), 기존
    `_is_same_day_event_horizon_signal`(`surge_evaluation_service.py:506-524`, 계약
    `surge_metadata.get("horizon") == "same_day"`)이 인식한다. 이 필드/값 계약은 **열린 질문이 아닌
    확정 통과 기준**이며 DB 어서션으로 검증한다. *어떤* 후보에 same_day를 부여할지의 트리거 임계
    (전량 vs 조건)만 OQ-5/DP-5에 위임한다.
  - **(D2 minor)** AC-084-016 first-mover 비목표에 명명된 기계적 음성 테스트
    `test_first_mover_excluded_from_theme_news_carry_scope`를 부여(기존
    `excluded_near_limit_up_carry_codes` 제외 패턴 동형).

---

## 1. Overview (개요)

### 문제 — 뉴스발 산업 테마 랠리의 구조적 미탐

급등예측 시스템(`backend/app/services/surge_detector.py`)은 change_rate >= 10.0%
(`surge_actual_outcome_service.py`, was_surge 임계) 급등을 급등 전/급등 직전에 포착해 사전 진입
가능하게 하는 것이 목적이다. 그러나 2026-07-22 라이브 감사 결과, 당일 실제 +10% 이상 급등 52종목
중 **후보 신호가 하나라도 발신된 것은 5종(9.6%)**, 그중 진짜 사전예측은 1종뿐이었다.

미탐의 최소 10건 이상은 **단일 실세계 이벤트**에 귀속된다: 07-22 오전 삼성전자가 로봇 전담조직
("RX사업추진실") 신설을 발표하자, 삼성과 **지분/계열 관계가 전혀 없는** 로봇 테마 전반이 동반
급등했다 — 레인보우로보틱스(277810, +16.8%), 로보스타(090360, +13.1%), 로보티즈(108490, +12.4%),
씨메스(475400, +11.1%), 아이로보틱스(066430, +29.9%), 케이엔에스(432470, +29.9%),
코닉오토메이션(391710, +29.9%) 등. 뒤늦게 잡은 종목(두산로보틱스, 앤로보틱스, 휴림로봇, 나노,
한라캐스트, 현대모비스)도 있었다.

DB(`news_articles`) 실측 뉴스 타임라인:

- **09:14 KST**(개장 14분 후) — 이미 "특징주" 기사가 상한가 도달을 보도("로봇주 '불기둥'…삼성전자
  로봇 승부수에 줄줄이 '상한가'"). 이 **1차 파동(동일-순간 이동)은 현실적으로 사전예측 불가** —
  발표에 대한 DART 공시가 존재하지 않고(`disclosures` 테이블 stock_code='005930' 조회 시 무관한
  최대주주지분 신고만 존재), 언론/보도로만 전파됐으며, 최초 기사 자체가 이미 완료된 상한가를 보도.
  → **§4 [X-1]로 명시 제외.**
- **09:58~11:12 KST** — 2차 종목 이익 실현 보도(두산로보틱스, 레인보우로보틱스).
- **14:20~14:36 KST** — 3차/로테이션 파동(로보스타, 앤로보틱스, 나노, 휴림로봇, 한라캐스트) —
  테마가 이미 알려진 지 **수 시간 후**. 이것이 **현실적·측정가능한 타겟**이다: 테마가 활성으로
  확인된 뒤, 아직 안 움직인 바스켓 멤버를 그들의 가격 이동 전에 포착.

### 근본원인 3종 (모두 2026-07-22 코드/DB 검증)

1. **뉴스 긴급도 오분류.** 이 사건 관련 15개 `news_articles` 행이 전부 `urgency='routine'`
   (`_classify_urgency`, `news_crawler.py:48`) — 전 시장 촉매인데도 breaking/important 하나 없음.
   `disclosure_impact_scorer`의 즉시발화 파이프라인이 이 사건에서 **애초에 트리거되지 못했다.**
2. **뉴스 기반 산업 테마 전파 메커니즘 부재.** `theme_group_carry`(`surge_detector.py:3012`,
   SPEC-AI-025)는 **사전 정의된 지분/계열 그룹**(삼성/SK/LG/현대차 — `theme_group_id`/
   `theme_group_name`/`anchor_stock_code`) 내에서만 전파한다. 로봇 테마 종목은 삼성과 지분 관계가
   없어 이 메커니즘이 구조적으로 도달할 수 없다. 코드베이스에 **키워드 바스켓 기반 테마 전파** 개념이
   오늘 존재하지 않는다.
3. **`stocks.keywords` 컬럼 전면 미채움.** `app/models/stock.py:18`에 `keywords ARRAY(Text)`
   컬럼이 이미 존재하나(nullable), 오늘 조회한 모든 종목이 `keywords = NULL`. 자동 파이프라인 중
   이 컬럼을 채우는 것은 하나도 없다(쓰기 지점은 seed=None / registry=[] / 수동 API뿐). 즉
   이 종류의 테마 태깅을 위해 마련된 인프라이나 한 번도 사용되지 않았다 — (2)가 의존하는 데이터.

### 접근 (사용자 승인 3개 방향, 상호 의존)

세 역량을 **의존 순서**로 명세한다:

- **그룹 C — 키워드 태깅 인프라(선행조건).** 기존 뉴스/공시 텍스트에서 테마 키워드("로봇",
  "2차전지" 등)를 추출해 `stocks.keywords`를 채우는 배치 백필 + 지속 파이프라인. 그룹 A가 이
  데이터 존재에 의존한다.
- **그룹 B — 뉴스 긴급도 재보정(독립).** 진짜 시장을 움직이는 이벤트가 더 이상 일괄 'routine'으로
  분류되지 않도록 `_classify_urgency`를 재보정. 이미 함수에 구현됐으나 수집 시점에 미공급되는
  co-mention/테마 볼륨 경로를 활성화하고 촉매 신호 커버리지를 확장.
- **그룹 A — 뉴스 기반 산업 테마 전파 탐지기(핵심·권장).** `theme_group_carry` 패턴을
  **`stocks.keywords` 바스켓 멤버십**으로 재키잉한 신규 탐지기: 바스켓 멤버 하나가 앵커 임계(가격
  및/또는 고긴급 뉴스)를 넘으면, 아직 안 움직인 나머지 바스켓 멤버에게 후보 신호를 전파.

### 목표

테마 앵커 이벤트가 확인된 뒤(뉴스 긴급도 + 키워드 바스켓 멤버십으로), **아직 안 움직인 바스켓
멤버**에게 그들의 가격 이동 이전에 측정가능한 리드타임(분~시간)을 두고 후보 신호를 전파한다.
계열 그룹에 대해 `theme_group_carry`가 이미 하는 일을, 키워드로 정의된 산업 테마로 확장한 것이다.
단, 기존 7종 탐지기·앙상블·매매 로직은 불변으로 유지하고 예측 기록 모드(SPEC-AI-043)를 계승한다.

---

## 2. Environment & Assumptions (환경 및 가정)

- Backend: Python 3.12+, FastAPI 0.115, SQLAlchemy 2.0, PostgreSQL 16(프로덕션)/SQLite(테스트).
  APScheduler 기반 크론/인터벌 잡. 개발 방법론: DDD(ANALYZE-PRESERVE-IMPROVE,
  `.moai/config/sections/quality.yaml`). 검증 명령:
  `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` (CLAUDE.local.md).
- 운영 모드: **예측 기록 모드**(SPEC-AI-043) — 실매수/포트폴리오 실행 비활성, `surge_trades` 0건.
  본 SPEC의 모든 변경은 예측 기록만 확장한다.

### 코드 검증 완료 (2026-07-22, read-only)

- **[E-1] 긴급도 분류는 제목 키워드 기반 + co-mention 경로 미활성.** `_classify_urgency(title,
  recent_topic_counts=None)`(`news_crawler.py:48-72`)는 (a) `_BREAKING_RE`(`[속보]/[긴급]/[단독]/
  [breaking]/[exclusive]`, `:36-39`) 매칭 시 'breaking', (b) `recent_topic_counts` 중 count>=5 존재
  시 'breaking', (c) `_IMPORTANT_KEYWORDS`(실적/인수/합병/M&A/규제/소송/배당/상장폐지/유상증자/
  감사의견/워크아웃/법정관리/공시/IPO/상폐, `:41-45`) 제목 부분일치 시 'important', 그 외 'routine'을
  반환한다. **핵심**: 수집 시점 호출부(`:577`)는 `_classify_urgency(ad["title"])`로 **`recent_topic_counts`를
  전혀 전달하지 않아** (b) 경로가 항상 비활성이다. → 로봇 랠리처럼 "같은 테마 다수 기사가 동시에
  쏟아지는" 시장 촉매가 제목 키워드에 안 걸리면 일괄 'routine'이 된다. (b) 경로는 함수에 **이미
  존재**하므로, 이를 활성화하는 것이 그룹 B의 최소 변경 축이다.
- **[E-2] 테마 전파는 계열/지분 그룹 전용, 키워드 바스켓 부재.** `detect_theme_group_carry_forward`
  (`surge_detector.py:3012`, SPEC-AI-025, `@MX:ANCHOR` fan_in>=3, `fund_manager._run_coverage_expansion()`
  에서 호출)는 `ThemeGroup`/`StockThemeGroup`(`app/models/theme_group.py`) 내에서만 전파한다 —
  `anchor_stock_id`가 있는 그룹의 앵커 등락률이 `anchor_surge_min_pct` 이상이면 그룹 내 미시그널
  종목(`existing_ids` 제외)에 `surge_metadata={"surge_basis":["theme_group_carry"], "anchor_stock_code":...,
  "theme_group_id":..., "theme_group_name":...}` / `signal_type="surge_candidate"` /
  `confidence=round(change_rate/30.0*0.4, 4)` / `paper_executed=True` 신호를 발행하고, `max_signals_per_group`
  캡 + 크로스그룹 dedup(`emitted_codes`) + 예외 격리(오류 시 `[]` 반환) 패턴을 갖는다.
  로봇 테마 종목은 삼성과 지분 관계가 없어 이 경로가 구조적으로 도달 불가. 별도로 `theme_cluster`가
  쓰는 `sector_theme_map`(theme→섹터 리스트, `surge_settings.py:42`, `surge_detector.py:339/3619`)이
  있으나 **섹터 키잉**이지 `stocks.keywords` 바스켓 키잉이 아니다. → 키워드 바스켓 기반 전파는
  코드베이스에 부재.
- **[E-3] `stocks.keywords`는 존재하나 전면 미채움.** `Stock.keywords: Mapped[list[str] | None] =
  mapped_column(ARRAY(Text), nullable=True)`(`app/models/stock.py:18`). 2026-07-22 DB 조회: 확인한
  모든 종목이 `keywords = NULL`. 코드베이스 쓰기 지점: `seed/stocks.py:104/124`(=None),
  `stock_registry_service.py:154`(=[]), `routers/stocks.py:97`(수동 API `body.keywords`) — **자동
  추출·채움 파이프라인은 하나도 없다.** 읽기 지점은 `sectors.py:117`/`routers/stocks.py` 패스스루뿐.
  → 그룹 A가 의존하는 데이터가 부재하므로 그룹 C가 선행조건. **컬럼은 이미 존재 → 신규
  마이그레이션 불필요(데이터 UPDATE만).**
- **[E-4] 재사용 가능한 키워드 추출 자산 존재.** `ai_classifier._extract_sector_keywords(sector_name)`
  (`:1000`, `news_crawler`에 이미 import), `keyword_generator.generate_keywords`(`:164`, following
  시스템용 AI 키워드 생성), `keyword_matcher`(사용자 관심 키워드 매칭), `NewsStockRelation`
  (종목↔뉴스 조인, NewsArticle에 stock_code 컬럼 없음 → 조인 필수). → 그룹 C는 신규 LLM 인프라를
  새로 만들기보다 이 자산을 우선 재사용해야 한다(예산 가드 계승).
- **[E-5] 탐지기 배선 지점 + 장중 반복 실행.** `detect_theme_group_carry_forward`는
  `fund_manager._run_coverage_expansion()`(fan_in>=3)에서 호출되며, 이 파이프라인은 SPEC-AI-083의
  장중 고빈도 재스캔(09:05~BUY_CUTOFF, `event_rescan_enabled: true` `surge_detection.yaml:265`으로
  뉴스 이벤트 재스캔 활성) 잡들에서 반복 실행된다. → 그룹 A 탐지기를 동일 확장 파이프라인에 배선하면
  장중 반복 평가를 자동으로 얻는다(신규 스케줄 불필요). 단 그 후보의 same-day 지평 귀속이 없으면
  recall이 안 움직인다(SPEC-AI-083 REQ-005 교훈, 아래 [A-2]).
- **[E-6] 즉시발화 인프라(공시)와 same-day 지평 평가 경로 이미 존재.** `immediate_surge.enabled: true`
  (`surge_detection.yaml`, SPEC-AI-080/083)와 same-day 지평 평가 경로 `_is_same_day_event_horizon_signal`
  (`surge_evaluation_service.py:506`)이 배선 완료. → 그룹 A의 same-day 귀속은 이 기존 지평 태깅/평가
  경로를 재사용해 스키마 변경 없이 달성한다.

### 가정

- **[A-1]** 그룹 A(전파 탐지기)는 그룹 C(키워드 채움)에 데이터 의존한다 — `stocks.keywords`가
  NULL이면 그룹 A는 오류가 아니라 **무해한 no-op**로 degrade해야 한다(REQ-AI084-012). 따라서
  구현 순서는 C → (B) → A이나, A는 C 미완 시에도 안전하게 배포 가능(빈 바스켓 = 전파 없음).
- **[A-2]** 그룹 A 탐지기는 장중(예: 14:20~14:36 로테이션 파동)에 당일 급등을 예측하므로, 그 후보를
  same-day 지평으로 귀속하지 않으면 표준 T-1→T 버킷에서 하루 늦은 날과 비교되어 recall이 구조적으로
  안 움직인다(SPEC-AI-075/080/083이 교정·재사용한 지평 함정). → same-day 귀속은 그룹 A의 필수 부속
  요구사항(REQ-AI084-013, P0 HARD).
- **[A-3]** 그룹 B의 co-mention 경로 활성화는 진짜 routine 뉴스의 대량 오상향(precision 저하)을 유발할
  수 있으므로 음성 대조(무촉매 routine 다수 → routine 유지)를 인수 기준으로 고정한다.
- **[A-4]** 예측 기록 모드가 유지되므로 그룹 A/B/C의 어떤 경로도 실매수를 트리거하지 않는다 —
  자금 리스크 0, 리스크는 precision·LLM 예산·데이터 품질에 국한.

---

## 3. Requirements (EARS)

> 표기: 요구사항은 의존 순서(그룹 C → B → A → 공통)로 배치한다. 그룹 A가 핵심 산출물이며
> 그룹 C(데이터)·그룹 B(긴급도)를 소비한다. WHAT/관찰가능 행위 수준으로 기술하고, 구체적
> 함수·설정키·임계값은 plan.md/Run 단계에서 확정한다.

### 그룹 C — 키워드 태깅 인프라 (Keyword Tagging Infrastructure)

#### REQ-AI084-001 (Event-Driven, P0) — 뉴스/공시 텍스트 기반 키워드 태깅

**WHEN** 추적 종목(`stocks`)에 대해 키워드 태깅이 수행되면, the system **SHALL** 그 종목과 연결된
뉴스(`NewsStockRelation` 조인) 및 공시 텍스트에서 테마/산업 키워드(예: "로봇", "2차전지", "반도체")를
추출해 `stocks.keywords`(ARRAY(Text), 현재 전면 NULL)를 채워야 한다.

- 근거([E-3]/[E-4]): 그룹 A가 의존하는 `stocks.keywords`를 채우는 자동 파이프라인이 부재. 신규 LLM
  인프라를 새로 만들기보다 기존 추출 자산(`_extract_sector_keywords`, `keyword_generator`,
  `sector_theme_map`)을 우선 재사용한다. 추출 방식(규칙/사전/LLM 혼합)은 plan.md에서 확정.

#### REQ-AI084-002 (Event-Driven, P0) — 1회성 배치 백필 (기존 유니버스)

**WHEN** 백필이 실행되면, the system **SHALL** 기존 추적 종목 유니버스에 대해 키워드를 1회 채워야
하며, 이 백필은 **유계(bounded)이고 멱등(재실행 안전)**이어야 한다.

- 이미 채워진 키워드를 재실행이 파괴하지 않아야 하며(멱등), 유니버스 크기에 비례한 유계 비용으로
  수행되어야 한다(LLM 사용 시 예산 가드).

#### REQ-AI084-003 (State-Driven, P1) — 지속 태깅 파이프라인 (신규 유입 반영)

**WHILE** 신규 뉴스/공시가 유입되는 동안, the system **SHALL** `stocks.keywords`를 주기적/훅 기반으로
갱신해 신선하게 유지하되, 종목당 키워드 수를 유계로 캡해 무한 증식을 방지해야 한다.

- 갱신 주기·트리거(스케줄 vs 수집 훅)와 종목당 키워드 상한은 plan.md에서 확정. 정규화된 테마 태그
  어휘(노이즈 키워드 억제)를 사용한다.

#### REQ-AI084-004 (Unwanted, P0) — 기존 데이터 오염·비용 폭발 금지 [HARD]

the system **SHALL NOT** (a) 수동 설정된 `stocks.keywords`나 following 시스템의 사용자 키워드 데이터
(`keyword_matcher`/`following`)를 덮어쓰거나 오염시켜서는 안 되며, (b) 무유계 LLM 호출로 비용을
폭발시켜서는 안 된다(무료 티어 우선 + 예산 가드, 기존 관례 계승).

### 그룹 B — 뉴스 긴급도 재보정 (News Urgency Recalibration)

#### REQ-AI084-005 (Event-Driven, P0) — 테마 볼륨(co-mention) 신호로 긴급도 승격

**WHEN** 뉴스 기사 긴급도를 분류하면, the system **SHALL** 동일 테마/종목에 대한 최근 기사 폭증
(co-mention/테마 볼륨) 신호를 반영해, 같은 테마 기사가 다수 쏟아지는 시장 촉매가 일괄 'routine'으로
분류되지 않도록 해야 한다.

- 근거([E-1]): `_classify_urgency`의 `recent_topic_counts>=5 → breaking` 경로는 **이미 함수에 존재**하나
  수집 호출부(`:577`)가 카운트를 미공급해 항상 비활성. 본 REQ는 그 카운트를 수집 시점에 공급해 기존
  경로를 활성화하는 것이며(최소 변경 축), 정확한 카운트 산정(윈도우/테마 키)은 plan.md에서 확정.

#### REQ-AI084-006 (Ubiquitous, P0) — 시장 촉매 신호 커버리지 확장

the system **SHALL** 진짜 시장을 움직이는 촉매 신호(예: 산업 테마 랠리를 시사하는 표현) 커버리지를
확장해, 로봇 테마 랠리 같은 이벤트가 'routine' 이상으로 분류될 수 있게 해야 한다.

- WHAT 수준: "진짜 시장을 움직이는 이벤트가 일괄 routine으로 오분류되지 않는다." 구체 키워드/규칙
  확장은 plan.md에서 확정하되, REQ-AI084-007 음성 대조를 통과해야 한다.

#### REQ-AI084-007 (Unwanted, P0) — routine 오상향 금지 (precision 가드) [HARD]

the system **SHALL NOT** 진짜 일상(routine) 뉴스의 긴급도를 부당하게 상향해서는 안 된다 — 재보정이
routine 기사 다수를 breaking/important로 뒤집어서는 안 된다(음성 대조군).

- 근거([A-3]): 긴급도 상향은 즉시발화/이벤트 재스캔 표면을 넓혀 precision을 떨어뜨릴 수 있다. 무촉매
  일상 뉴스 표본이 재보정 후에도 routine으로 유지됨을 관찰 가능 증거로 검증(acceptance.md).

#### REQ-AI084-008 (State-Driven, P1) — 설정 게이팅 + 단계적 롤아웃

**WHILE** 긴급도 재보정이 배포되는 동안, the system **SHALL** 재보정을 설정 플래그로 게이팅하고
(기본 보수값) SPEC-AI-079의 단계적 롤아웃 관례를 따라야 한다 — 롤백=플래그 복귀로 완전 레거시.

### 그룹 A — 뉴스 기반 산업 테마 전파 탐지기 (News-Driven Theme Propagation Detector)

#### REQ-AI084-009 (Event-Driven, P0) — 키워드 바스켓 앵커 → 미이동 멤버 전파

**WHEN** 어떤 키워드 바스켓(공유 `stocks.keywords`로 정의된 테마)의 멤버가 앵커로 활성화되면 — 즉
그 멤버의 가격 변화 및/또는 고긴급 뉴스가 앵커 임계를 넘으면 — the system **SHALL** 아직 움직이지
않은 **다른 바스켓 멤버**에게 `surge_candidate` 후보 신호를 전파해야 한다.

- `detect_theme_group_carry_forward` 패턴을 재사용/미러링한다([E-2]): 앵커 임계 → 미시그널 멤버
  전파, 바스켓당 신호 캡, 크로스바스켓 dedup, `surge_metadata.surge_basis=["theme_news_carry"]`,
  예외 격리. 계열/지분 그룹이 아닌 **키워드 바스켓 멤버십**으로 키잉한다는 점이 유일한 구조 차이.

#### REQ-AI084-010 (State-Driven, P0) — 미이동 멤버로 타겟 한정 (리드타임 확보)

**WHILE** 전파 대상을 선정하는 동안, the system **SHALL** 아직 움직이지 않은 멤버만 타겟해야 한다 —
이미 급등했거나 당일 이미 신호가 있는 멤버(`existing_ids` 패턴)는 제외한다.

- 근거(§1): 현실적 타겟은 3차/로테이션 파동(아직 안 움직인 바스켓 멤버)이며, 그들의 가격 이동 이전에
  측정가능한 리드타임을 확보하는 것이 목적이다.

#### REQ-AI084-011 (Ubiquitous, P0) — 테마 활성 확인 게이트 (오전파 통제) [HARD]

the system **SHALL** 단일 모호한 이동만으로 전파해서는 안 되며, **테마 활성 확인**(예: 복수 바스켓
멤버 동반 이동, 또는 고긴급 테마 뉴스 + 최소 1개 앵커 이동)을 요구해 오전파(false propagation)를
통제해야 한다.

- 근거: 키워드 바스켓은 계열 그룹과 달리 지정 앵커가 없으므로, 단일 종목의 우연한 이동이 바스켓 전체
  전파로 번지지 않도록 "테마가 실제로 활성인가"를 확인하는 게이트가 필수다. 이 지점에서 그룹 B(고긴급
  테마 뉴스)가 그룹 A의 확인 입력으로 기여한다. 확인 임계(멤버 수/긴급도 조합)는 plan.md에서 확정.

#### REQ-AI084-012 (Unwanted, P0) — 바스켓 데이터 부재 시 안전 degrade [HARD]

**IF** 대상 종목의 `stocks.keywords`가 NULL/빈 값이면, **THEN** the system **SHALL** 오류 없이 그 종목에
대해 전파를 조용히 건너뛰어야 한다(무해한 no-op) — 그룹 C 미완/부분완 상태에서도 안전.

- 근거([A-1]): 그룹 A는 그룹 C 데이터에 의존하나, 데이터 부재를 예외가 아닌 no-op로 처리해 C→A 배포
  순서 독립성을 확보한다(빈 바스켓 = 전파 없음).

#### REQ-AI084-013 (State-Driven, P0) — 당일 후보의 same-day 지평 귀속 [HARD]

**WHILE** 그룹 A 전파 탐지기가 당일(same-day) 급등을 예측하는 후보를 `fund_signals`에 영속화하는
동안, the system **SHALL** 그 후보의 `surge_metadata["horizon"]` 필드를 문자열 `"same_day"`로 설정해,
기존 `_is_same_day_event_horizon_signal`(`surge_evaluation_service.py:506-524`, 계약
`surge_metadata.get("horizon") == "same_day"`) 평가 경로가 그 후보를 same-day 지평에 귀속시켜
올바른 날(당일 T)의 실제 급등과 비교하도록 해야 한다.

- **구체 필드/값 계약 (REQ-009 동형, 확정 — 열린 질문 아님)**: REQ-009가 전파 신호의
  `surge_metadata.surge_basis=["theme_news_carry"]`를 명명하듯, 본 REQ는 전파-생성 신호가 반드시
  `surge_metadata["horizon"] = "same_day"`를 **설정**하도록 못박는다. 이 필드/값 계약은 Run 착수
  시점에 필드 수준 PASS/FAIL 테스트(전파 `fund_signals` 행의 `surge_metadata.horizon` DB 어서션,
  AC-084-013)를 갖는 **확정 통과 기준**이다. 단 *어떤* 전파 후보에 same_day를 부여할지의 트리거
  임계(전량 vs 특정 조건)만 OQ-5/DP-5에 위임한다 — 트리거 임계는 열린 질문이나, 필드/값 계약 자체는
  열린 질문이 아니다.
- 근거([A-2]/[E-6]): 장중 생성 후보에 지평 태깅이 없으면 표준 T-1→T 버킷이 T 대신 T+1과 비교되어
  전파를 추가해도 recall이 구조적으로 안 움직인다(SPEC-AI-083 REQ-005 최상위 교훈). SPEC-AI-080의
  지평 메타데이터 + `_is_same_day_event_horizon_signal` 경로를 스키마 변경 없이 재사용한다. 이 REQ
  누락 시 SPEC 목적이 무효화되므로 P0 HARD로 고정.

#### REQ-AI084-014 (Unwanted, P0) — 실매매 미트리거 (예측 기록 모드) [HARD]

the system **SHALL NOT** 그룹 A/B/C의 어떤 경로에서도 `execute_signal_trade`를 호출하거나 실제 매수를
트리거해서는 안 된다 — 예측 기록 전용(SPEC-AI-043 계승).

#### REQ-AI084-015 (State-Driven, P1) — 설정 게이팅 + 자원 가드 + 기존 경로 불변

**WHILE** 그룹 A 탐지기가 배포되는 동안, the system **SHALL** (a) 신규 설정 플래그로 게이팅(기본 보수,
단계적 롤아웃), (b) 바스켓당 신호 캡·크로스바스켓 dedup·LLM/자원 예산 가드를 적용하고, (c) 기존 7종
탐지기·앙상블 점수/가중치/임계값·스캔 유니버스 구성을 변경하지 않아야(additive detector) 한다.

### 공통 제약

#### REQ-AI084-016 (Unwanted, P0) — 계열 그룹 전파 메커니즘 불변 [HARD]

the system **SHALL NOT** 기존 `detect_theme_group_carry_forward`(SPEC-AI-025)·`ThemeGroup`/
`StockThemeGroup` 테이블·`theme_group_carry` 로직을 변경해서는 안 된다 — 본 SPEC의 키워드 바스켓
전파는 **별개의 additive 메커니즘**이며 계열/지분 전파를 대체하지 않는다.

#### REQ-AI084-017 (Unwanted, P0) — first-mover 예측 비목표화 [HARD]

the system **SHALL NOT** 제로 리드타임의 동일-순간 뉴스발 첫 급등 종목(first mover)을 예측하는 것을
목표로 삼거나 그 성능을 인수 기준으로 삼아서는 안 된다(§4 [X-1]). 본 SPEC의 목표는 테마 앵커 확인
**이후** 미이동 멤버 전파에 국한된다.

- **명명된 기계적 제외 테스트(D2)**: first-mover 비목표는 문서 서술이 아닌 명명된 음성 테스트
  `test_first_mover_excluded_from_theme_news_carry_scope`로 검증한다 — `surge_basis=["theme_news_carry"]`
  전파 근거(및 same-day 바스켓 전파 근거)가 없는 first-mover 후보가 본 SPEC 채점 `predicted_set`/
  `actual_set` 멤버십에 포함되지 않음을 확인한다(기존 `excluded_near_limit_up_carry_codes`/
  `excluded_same_day_event_codes` 제외 패턴, `surge_evaluation_service.py:602-607`과 동형). AC-084-016.

#### REQ-AI084-018 (State-Driven, P1) — DDD 회귀 안전 (재현 우선)

**WHILE** 그룹 B(공유 `_classify_urgency`)와 그룹 A(공유 커버리지 확장 파이프라인)를 변경하는 동안,
the system **SHALL** 변경 전 특성화 테스트(characterization test)를 선행해(DDD ANALYZE-PRESERVE-IMPROVE)
기존 긴급도 분류·기존 탐지기 발신의 무회귀를 검증해야 한다.

---

## 4. Exclusions (What NOT to Build) [HARD]

본 SPEC은 다음을 **명시적으로 범위에서 제외**한다:

- **[X-1] 제로 리드타임 first-mover 예측 금지 (사용자 확인 완료).** 동일-순간 뉴스발 상한가의 **첫
  급등 종목**(예: 07-22 09:14 특징주 기사가 이미 완료된 상한가를 보도한 1차 파동)은 공개 정보가 존재하기
  전에 예측해야 하므로 인사이더 정보 없이는 물리적으로 불가능하다. 이는 본 SPEC의 목표·인수기준·성능
  측정 대상이 **아니다**(REQ-AI084-017). 현실적 타겟은 테마 확인 후 미이동 멤버 전파(2차/3차 파동).
- **[X-2] 기존 7종 탐지기·앙상블 가중치·임계값·스캔 유니버스 구성 무변경** (REQ-AI084-015/016). 그룹 A는
  additive 8번째 유형의 전파 탐지기로 추가되며 기존 발신 경로를 바꾸지 않는다.
- **[X-3] 계열/지분 그룹 전파(`theme_group_carry`, SPEC-AI-025) 및 `ThemeGroup`/`StockThemeGroup`
  테이블 무변경** (REQ-AI084-016) — 키워드 바스켓 전파는 별개 메커니즘.
- **[X-4] 신규 테이블/스키마 마이그레이션 지양.** `stocks.keywords` 컬럼은 **이미 존재**([E-3]) →
  데이터 UPDATE만으로 채움(마이그레이션 불필요). 신호 태깅은 기존 `surge_metadata`(JSON) + SPEC-AI-080
  지평 경로 재사용. 부득이한 스키마 확장(예: 태깅 타임스탬프)은 Run 단계 사용자 승인 후 별도 결정.
- **[X-5] 매수·매매·포트폴리오 로직 무변경** (예측 기록 모드, SPEC-AI-043). `execute_signal_trade`
  미호출(REQ-AI084-014).
- **[X-6] 과거 데이터 소급 재계산/recall 백필 금지** — 이후 수집·평가 실행에만 전진 적용(SPEC-AI-071/
  080/083 무백필 관례 계승). 키워드 백필(그룹 C)은 종목 태깅 데이터 채움이지 과거 recall 재계산이 아니다.
- **[X-7] 텍스트-무관 순수 수급 급등(무재료 급등) 탐지는 범위 밖** — 본 SPEC은 뉴스/키워드 기반 테마
  촉매를 다룬다(오탐 위험 커 별도 관찰/SPEC).
- **[X-8] following 시스템 사용자 키워드(`keyword_matcher`/`following`)와의 통합/변경 금지** — 그룹 C는
  `stocks.keywords`(종목 테마 태그)만 다루며 사용자 관심 키워드와 별개 데이터(REQ-AI084-004).

---

## 5. Risks (리스크)

- **[R-1] 오전파/precision 리스크 (그룹 A 핵심).** 키워드 바스켓 전파는 잘못된 테마 확인 시 무관 종목에
  후보를 뿌려 precision을 떨어뜨릴 수 있다. 완화: 테마 활성 확인 게이트(REQ-AI084-011), 미이동 멤버 한정
  (REQ-AI084-010), 바스켓당 캡·dedup(REQ-AI084-015), 설정 게이팅+단계적 롤아웃. **자금 리스크 0**(예측
  기록 모드).
- **[R-2] 키워드 품질 리스크 (그룹 C).** 추출 키워드가 노이즈(너무 광범위/무의미)면 바스켓이 과대·과소
  형성돼 그룹 A 신호 품질이 저하된다. 완화: 정규화 테마 어휘, 종목당 캡, 배치 백필 후 표본 검수. 반복
  개선은 후속.
- **[R-3] 긴급도 오상향 리스크 (그룹 B).** co-mention 경로 활성화·키워드 확장이 진짜 routine을 대량
  상향하면 즉시발화/이벤트 재스캔 표면이 과도하게 넓어져 precision 저하 + LLM 예산 소모. 완화: 음성
  대조군(REQ-AI084-007), 설정 게이팅(REQ-AI084-008), 활성화 후 첫 수 거래일 관측.
- **[R-4] same-day 귀속 누락 리스크 (그룹 A 최상위).** 전파 후보에 same-day 귀속을 배선하지 않으면
  recall이 전혀 안 움직여 SPEC 목적이 무효화된다(SPEC-AI-083 R-4와 동형). 완화: REQ-AI084-013을 P0 HARD로
  고정, acceptance에서 same-day 편입을 관찰 가능 증거로 검증.
- **[R-5] 공유 코드 회귀 리스크.** 그룹 B는 공유 `_classify_urgency`를, 그룹 A는 공유 커버리지 확장
  파이프라인을 건드린다 — 결함 시 기존 긴급도 분류/기존 탐지기 발신을 조용히 회귀시킬 수 있다. 완화:
  재현 우선 특성화 테스트(REQ-AI084-018), 설정 플래그 OFF=완전 레거시.
- **[R-6] LLM 예산 리스크 (그룹 C).** 키워드 추출이 LLM을 쓰면(Gemini free 20req/day 한도, OpenRouter
  폴백) 배치 백필·지속 태깅이 예산을 소모한다. 완화: 무료 티어 우선 + 규칙/사전 추출 우선 + 예산 가드
  (REQ-AI084-004), 배치는 유계·멱등.

---

## 6. Related SPECs (관련 SPEC)

- **SPEC-AI-025 (미러링 대상·불변)**: `detect_theme_group_carry_forward`(계열/지분 그룹 전파) 소유. 그룹
  A는 이 패턴을 키워드 바스켓으로 미러링하되 원 로직/테이블은 불변(REQ-AI084-016, [X-3]).
- **SPEC-AI-080 (재사용)**: 공시 즉시발화 + same_day 지평 평가 경로(`_is_same_day_event_horizon_signal`)
  소유. 그룹 A same-day 귀속(REQ-AI084-013)이 이 경로를 재사용.
- **SPEC-AI-083 (인접·계승)**: 장중 고빈도 재스캔 + 뉴스 이벤트 재스캔 활성화. 그룹 A 탐지기는 그
  확장 파이프라인에서 반복 실행되며([E-5]), same-day 귀속 필수 교훈(REQ-005→본 REQ-013)을 계승.
- **SPEC-AI-066 (인접)**: 뉴스 co-mention 자동 테마(REQ-004)·이벤트 구동 재스캔(REQ-007) 인프라. 그룹 B
  긴급도 신호가 이벤트 재스캔 트리거 품질에 기여.
- **SPEC-AI-079 (참고 패턴)**: 설정 플립 활성화 + 단계적 롤아웃 관례 — 그룹 B/A 게이팅에 계승.
- **SPEC-AI-043 (계승)**: 예측 기록 모드(실매매 비활성) — 매매 무변경(REQ-AI084-014, [X-5]).
- **SPEC-AI-041/068 (평가 확장 대상)**: `evaluate_surge_predictions`·scannable_recall/coverage 소유.
  그룹 A same-day 서브지표 편입이 이 함수에서 이루어짐.

---

## 7. Open Questions (열린 질문 — Run/Annotation 단계 확정)

- **[OQ-1] 키워드 추출 방식(그룹 C).** 규칙/사전 기반(`sector_theme_map`·`_extract_sector_keywords`
  재사용) vs LLM(`keyword_generator`) vs 혼합. 예산·품질 트레이드오프. plan.md 권고 + annotation 확정.
- **[OQ-2] 바스켓 정의 세밀도(그룹 A/C).** `stocks.keywords`의 어느 입도가 테마 바스켓을 형성하는가
  (단일 키워드 교집합 vs 키워드 클러스터). 너무 광범위하면 오전파, 너무 좁으면 미탐.
- **[OQ-3] 테마 활성 확인 임계(그룹 A, REQ-011).** "복수 멤버 동반 이동"의 N, "고긴급 뉴스 + 앵커
  이동"의 조합 규칙. 라이브 07-22 로봇 랠리를 replay 표본으로 임계 캘리브레이션.
- **[OQ-4] co-mention 카운트 산정(그룹 B, REQ-005).** `recent_topic_counts`의 윈도우·테마 키(섹터/
  키워드/클러스터)를 무엇으로 잡을지. 기존 크롤 배치 내 집계 vs 별도 조회.
- **[OQ-5] same-day 귀속 트리거 조건(그룹 A, REQ-013).** 전파 후보 전량 same_day vs 특정 조건.
  SPEC-AI-080의 시간 기반 지평 분류 규칙 재사용안이 유력.
- **[OQ-6] 지속 태깅 트리거(그룹 C, REQ-003).** 스케줄 크론 vs 뉴스 수집 완료 훅. 신선도 vs 비용.

---

## 8. Follow-up Candidates (후속 후보 — 본 SPEC 범위 밖)

- (a) **키워드 품질 반복 개선 루프** — 배치 백필 후 바스켓 형성 품질을 관측·자동 개선(그룹 C 확장).
- (b) **텍스트-무관 순수 수급 테마 확산 탐지**([X-7]) — 무재료 테마 확산 포착(오탐 위험 커 별도 관찰).
- (c) **1차 파동(first-mover) 근사 포착 연구**([X-1]) — 인사이더 없이 불가능하나, 초저지연 뉴스/거래량
  이상으로 리드타임을 초 단위까지 좁히는 별도 연구(측정 전용, 매매 비목표).
- (d) **긴급도 재보정 효과 라이브 계측** — 그룹 B 활성화 후 즉시발화/이벤트 재스캔 발화 품질·precision
  사후 검증(관측 전용).
