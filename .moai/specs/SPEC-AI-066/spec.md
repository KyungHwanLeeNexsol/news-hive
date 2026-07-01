---
id: SPEC-AI-066
version: 0.2.0
status: completed
created: 2026-07-01
updated: 2026-07-01
author: MoAI
priority: High
issue_number: null
---

# SPEC-AI-066: 확신도 기반 선행 급등 신호 정밀화 (Conviction-Based Leading Surge Signal Precision)

## HISTORY

- 2026-07-01 (v0.2.0): 사용자 결정 4건 반영. (1) REQ-004/005 분리하지 않고 단일 SPEC 유지.
  (2) REQ-002 판별 방식 Option A(확신도 2단 이산) 확정. (3) REQ-003 페널티를 완전 면제가
  아닌 **부분 완화(0.3→0.7)** 로 확정. (4) 스캔 주기/이벤트 트리거를 Non-Goal에서 범위 내로
  전환 — **REQ-AI066-007(고임팩트 뉴스 이벤트 구동 재스캔)** 신규 추가. 뉴스 크롤러
  저장 완료 훅 방식(경량), 쿨다운 30분·일일 상한 20회로 LLM 예산 보호, 정기 스캔은 불변.
- 2026-07-01 (v0.1.0): 최초 작성. 목표는 "이미 오른 종목을 뒤늦게 재포착"이 아니라
  **선행지표 탐지의 근본 개선** — 확정된 강한 촉매(M&A·경영권 매각·지속적 다출처
  뉴스·공시 뒷받침)를 초기 단계에서 포착하는 것이다. 2026-07-01 위메이드(112040)
  사례: 2026-06-30 17:14 KST 경영권 매각/M&A 뉴스가 밤새 15+건으로 확산되었고 당일
  +29.85%(상한가 근접) 급등했으나, **하루 전체(08:00/09:05/10:00/15:20 스캔)에서
  fund_signal 0건**으로 완전히 놓쳤다. 코드 재확인 결과 위메이드는 4개 경로 모두에서
  구조적으로 차단됨이 밝혀졌다:
  1. `volume_news_combo`(가중치 최대 0.25) — SPEC-AI-030의 고정 과열 컷오프
     `overheat_change_pct=5.0`이 **당일 +5% 이상 종목을 촉매 강도와 무관하게 전부 제외**.
     위메이드처럼 확정 뉴스에 개장 갭업하는 종목은 수분 내 5%를 돌파해 최대 가중 탐지기가
     구조적으로 발동 불가.
  2. `detect_theme_news_cluster`(가중치 0.19) — 키워드→섹터 맵 기반. M&A/경영권 매각 같은
     **이벤트 촉매는 사전 정의된 20개 섹터-테마 키워드에 없어** 테마가 활성화되지 않음.
     ("게임"은 키워드에 있으나 M&A 기사 본문은 종목·딜 고유어를 쓰므로 매칭 불안정.)
  3. `detect_disclosure_surge_pattern`(가중치 0.14) — SPEC-AI-028 페널티 필터가
     **"최대주주변경"을 역신호로 간주해 점수를 penalty_factor 0.3배로 삭감**
     (surge_detector.py:976,986). M&A/전략적 인수에 의한 최대주주변경(호재)을 부실 매각
     최대주주변경(악재)과 구분하지 못해, 위메이드의 인수 공시 점수를 bypass 임계 이하로 눌러버림.
  4. `detect_volume_breakout`(가중치 0.11, 단독 bypass 존재) — 고정 3.0x 거래량 배율 컷오프가
     **20일 평균이 이미 높은 중대형주에는 과도**. 게다가 유니버스가 Naver 거래량 순위 상위
     50종목으로 제한되어 촉매 중대형주가 후보에 포함되지 않을 수 있음.
  본 SPEC은 **촉매 확신도(catalyst conviction)** 라는 공통 판별 신호를 도입해, 확정 강한
  촉매를 애매한 거래량 급증과 구분하고, 확신도가 높을 때만 각 탐지기의 게이트를 통제된
  범위에서 완화한다. SPEC-AI-030의 추격매수 방지 설계는 **무효화하지 않고 보존**한다.

---

## 선행 SPEC (전제 조건 / Assumptions)

본 SPEC은 다음 기존 자산 위에서 동작하며 신규 탐지기나 매매 엔진을 만들지 않는다.
각 항목은 코드 재확인(2026-07-01) 결과다.

- **SPEC-AI-012 / AI-018 (급등 징후 탐지 + 앙상블 정밀화)**: 8개 탐지기 앙상블,
  `SurgeCandidate`, `compute_ensemble_score`, `gather_surge_candidates`,
  news(theme+combo)/disclosure/technical 그룹 컨센서스 배율 구조. 본 SPEC은 앙상블 가중치와
  컨센서스 배율을 변경하지 않는다.
- **[HARD] SPEC-AI-030 (거래량콤보 추격매수 방지) — 본 SPEC이 정밀화하는 직접 대상**:
  `combo_chase_guard`(surge_detection.yaml:156~164) 4개 게이트가 현재 활성이다.
  Gate 1 과열(`overheat_change_pct=5.0`, surge_detector.py:641), Gate 2 신선도
  (`min_freshness_ratio=1.5`, :649~656), Gate 3 분산(`distribution_change_pct=0.0`,
  :660~665), Gate 4 combo 단독 차단(`require_companion_detector=true`, :1571~1584).
  - **[HARD] 이 게이트는 오설계가 아니라 실증 대응이다**: 2026-06-02 volume_news_combo
    6건 신호가 **100% 실패**(평균 -7.7%, 급등 0/급락 5)했고, 그 원인은 거래량 z-score가
    임계를 넘을 때쯤엔 스마트머니가 이미 매수를 끝내 우리가 천장을 추격했다는 것이었다.
    유일한 성공(쎄노텍 +10.6%)은 immediate_disclosure+theme_cluster였고 combo는 미관여.
  - **[HARD] 본 SPEC은 `overheat_change_pct`를 단순히 올리거나 제거하지 않는다.** 그 방식은
    SPEC-AI-030이 고친 추격매수 실패를 그대로 재현할 위험이 크다. 본 SPEC이 해결할 진짜
    문제는 **"애매한 거래량 급증(스마트머니 이미 이탈, 나쁨)"과 "확정 강한 촉매(M&A·지속
    다출처 뉴스·공시 뒷받침, 초기)"를 구분**하는 것이다. 고정 등락률 컷오프 아래에서 둘은
    동일하게 보이지만 본질이 다르다. 확신도가 높을 때만, 그리고 신선도/분산 게이트는
    유지한 채 과열 상한만 완화한다.
- **SPEC-AI-028 (공시 역신호 필터링) — 본 SPEC이 예외 규칙을 추가하는 대상**:
  `disclosure_type_filter.penalty_patterns`에 "최대주주변경"/"손실"/"영업손실"이 있고
  `penalty_factor=0.3`이 `detect_disclosure_surge_pattern`(surge_detector.py:976,986)과
  매수 실행(surge_trading_service.py:261)에서 적용된다. 본 SPEC은 이 페널티를 삭제하지
  않고, **전략적 인수/경영권 프리미엄 맥락일 때만 면제/완화**하는 예외를 추가한다.
- **SPEC-AI-039 (고임팩트 뉴스 키워드)**: `high_impact_news` 섹션(기술이전/임상/수주 +
  배율)이 이미 존재한다. 본 SPEC의 확신도 산출은 이 키워드 집합을 재사용·확장(인수/합병/
  경영권)한다.
- **SPEC-AI-062 / AI-063 (volume_breakout 탐지기 + 단독 bypass)**:
  `detect_volume_breakout`(surge_detector.py:3165)는 `fetch_volume_leaders_sync`
  상위 종목 중 20일 평균 대비 `volume_ratio_threshold=3.0`배 이상을 후보로 만들고,
  `volume_breakout_bypass_threshold=0.30` 단독 bypass 경로(surge_detector.py:1664~1685)가
  이미 존재한다. **[정정] volume_breakout이 위메이드를 놓친 원인은 "가중치 0.11이
  임계에 미달"이 아니다** — 단독 bypass가 있으므로 가중치는 무관하다. 진짜 원인은 유니버스
  제한(상위 50 거래량 리더)과 중대형주에 과도한 고정 3.0x 컷오프다. 본 SPEC은 AI-062/063이
  소유한 가중치·bypass 임계는 변경하지 않고 유니버스와 상대 임계만 보강한다.
- **SPEC-AI-065 (z-score 상대 채점 + 유니버스 확장)**: `stock_signal_baselines` 테이블과
  `surge_baseline_service.py`(순수 파이썬, numpy/sklearn 금지)로 종목별 롤링 z-score
  정규화를 도입했다. 본 SPEC REQ-AI066-005는 volume_breakout의 상대 임계에 이 기존
  베이스라인 서비스를 **재사용**한다(신규 통계 라이브러리 도입 금지).
- **[HARD] 데이터 가용성 사실 확인 (2026-07-01)**:
  - `volume_news_combo`는 이미 종목별 뉴스를 `NewsStockRelation.news_id →
    NewsArticle.id → Stock` 조인으로 조회한다(surge_detector.py:539~558). 현재는
    종목당 **최대 감성 점수만** 보관(`positive_news_stocks: dict[code→max sentiment]`).
    확신도의 "지속적 다출처 커버리지"(기사 수 + 첫~마지막 기사 시간 span)는 **이미 조회
    중인 동일 행 집합을 집계 확장**하면 얻을 수 있어 신규 데이터 소스가 필요 없다.
  - `_fetch_price_change_sync`는 `{"current_price", "change_rate"}`만 반환하며
    **시가(open_price)는 이 동기 경로에서 미가용**. 본 SPEC의 등락률 판정은 SPEC-AI-030과
    동일하게 `change_rate`(전일 종가 대비)로 작성한다.
  - `NewsArticle`에는 stock_code 컬럼이 없어 종목 매칭은 항상 NewsStockRelation 조인이
    필요하다(SPEC-AI-060에서 확인).
  - `Disclosure` 실제 컬럼은 `report_name`/`report_type`/`ai_summary`/`rcept_dt`
    (YYYYMMDD 문자열)/`disclosed_at`이며 페널티 매칭은 report_name+ai_summary 결합
    문자열에 대해 수행된다(SPEC-AI-060에서 확인).

---

## Overview

본 SPEC은 급등 예측 시스템이 **확정 강한 촉매를 가진 중대형주 급등을 구조적으로 놓치는**
결함을 교정한다. 원인은 각 탐지기의 게이트가 소형주 거래량 추격의 거짓 양성을 막도록
튜닝되어 있고, 그 동일 게이트가 고확신 촉매성 급등까지 함께 눈멀게 만든다는 것이다.
핵심 아이디어는 **촉매 확신도(catalyst conviction)** 라는 공통 판별 신호를 도입해,
확신도가 높을 때만 통제된 완화 경로를 여는 것이다.

정의하는 요구사항(우선순위 표기):

- **[P0] REQ-AI066-001 — 촉매 확신도 산출**: 이미 조회 중인 뉴스/공시 데이터로부터 종목별
  확신도(LOW/MEDIUM/HIGH)를 산출한다. 근거: (a) 커버리지 기사 수, (b) 커버리지 지속시간,
  (c) 감성 강도, (d) 고임팩트 촉매 키워드 존재, (e) 공시 뒷받침 여부.
- **[P0] REQ-AI066-002 — combo 과열 게이트 확신도 차등 완화**: 확신도 HIGH일 때만 과열
  상한을 상향한다. 신선도·분산 게이트는 불변. SPEC-AI-030 기본 동작 보존.
- **[P0] REQ-AI066-003 — 전략적 인수 공시 페널티 예외**: 최대주주변경 등 페널티 대상
  공시가 인수/경영권 프리미엄 호재 맥락이면 penalty_factor를 부분 완화(0.3→0.7)한다
  (완전 면제가 아님 — 최대주주변경의 잔여 리스크를 반영해 비페널티 신호보다는 낮게 유지).
- **[P1] REQ-AI066-004 — 뉴스 공동언급 기반 테마 자동 확장**: 키워드→섹터 맵의 취약성을
  보완해, 동일 기사에서 반복 co-mention되는 종목 클러스터를 자동 식별한다.
- **[P1] REQ-AI066-005 — volume_breakout 유니버스 확장 + 상대 임계**: 촉매 종목을 후보
  유니버스에 포함하고, 고정 3.0x 배율을 종목별 상대 임계로 보강한다.
- **[P1] REQ-AI066-007 — 고임팩트 뉴스 이벤트 구동 재스캔**: 확신도 HIGH 기준을 만족하는
  고임팩트 뉴스가 저장되면, 다음 정기 스케줄을 기다리지 않고 즉시 급등 신호 생성을 1회
  트리거하는 보강 경로를 추가한다(쿨다운·일일 상한으로 남용 방지).
- **REQ-AI066-006 — 설정 추가**: `catalyst_conviction` 섹션 및 관련 설정.

이 SPEC은 **무엇을(WHAT)**과 **왜(WHY)**를 정의하며, 확신도 산출 공식의 구체 수치·함수
시그니처·데이터 파이프라인 상세는 plan.md 및 Run 단계로 이연한다.

### 문제 맥락 — 2026-07-01 위메이드 사례 (Evidence)

| 항목 | 값 |
|---|---|
| 종목 | 위메이드 (112040) |
| 촉매 | 경영권 매각/M&A, 2026-06-30 17:14 KST 최초 보도 |
| 뉴스 확산 | 밤새 ~2026-07-01 오전까지 15+건, 다출처, 다시간대 지속 |
| 당일 결과 | +29.85% (상한가 근접) |
| 우리 신호 | **0건** (08:00 / 09:05 / 10:00 / 15:20 스캔 전부) |

**4개 경로 동시 차단(코드 재확인):**

| 경로 | 차단 원인 | 코드 위치 |
|---|---|---|
| volume_news_combo | 개장 갭업으로 change_rate>=5% → 과열 게이트 제외 | surge_detector.py:641 |
| theme_cluster | M&A/경영권 이벤트가 20개 섹터-테마 키워드에 부재 | surge_detector.py:230~254 |
| disclosure_pattern | "최대주주변경" 페널티로 점수×0.3 → bypass 임계 미달 | surge_detector.py:976,986 |
| volume_breakout | 상위 50 거래량 리더 유니버스 밖 + 중대형주에 3.0x 과도 | surge_detector.py:3182,3211 |

이 사례는 "이미 오른 종목 재포착"이 아니라, **확정 촉매를 초기에 포착하지 못하는 선행
지표 감도 결함**을 보여준다. 소형주 추격 방지 게이트들이 고확신 촉매성 급등까지 일괄
차단한 결과다.

### 확신도 차등 게이트 시나리오 (REQ-002 예시)

| 시나리오 | change_rate | 확신도 근거 | 확신도 | 과열 게이트 동작 |
|---|---|---|---|---|
| 애매한 거래량 급증 (AI-030 사례) | +7% | 뉴스 얇음/단발, 공시 없음 | LOW | 기존대로 제외 (5% 컷오프 유지) |
| 확정 M&A 갭업 (위메이드) | +12% | 15+건 다출처 지속 커버리지 + 인수 맥락 | HIGH | 상향 상한(15%)으로 통과 |
| 확정 촉매지만 분산 중 | +6% | 커버리지 강하나 change_rate<0 후퇴 | HIGH | 분산 게이트(Gate3)로 여전히 제외 |
| 고확신 + stale 거래량 | +3% | 커버리지 강하나 오늘/어제 거래량비 0.6 | HIGH | 신선도 게이트(Gate2)로 여전히 제외 |

핵심: 확신도 HIGH는 **과열 상한만** 완화하며, 신선도(Gate2)·분산(Gate3)·combo 단독 차단
(Gate4)은 전 구간 유지된다. 따라서 고확신을 가장해도 하락 중 분산 물량이나 stale 급증은
계속 걸러진다.

---

## Root Cause (근본 원인)

### Root Cause 1 — 고정 등락률 컷오프는 촉매 강도를 보지 못한다

SPEC-AI-030 `overheat_change_pct=5.0`은 당일 +5% 이상 종목을 **촉매 근거와 무관하게** 전부
제외한다. 이는 소형주 거래량 추격(스마트머니 이미 이탈)에는 옳지만, 확정 M&A·지속 다출처
뉴스에 개장 갭업하는 종목(스마트머니 진입 초기)에는 잘못이다. 두 상황은 등락률만으로는
구분 불가하며, **촉매의 확신도**라는 별도 축이 있어야 구분된다.

### Root Cause 2 — 테마 탐지의 키워드 취약성 및 이벤트 촉매 맹점

`detect_theme_news_cluster`는 사전 정의된 20개 섹터-테마 키워드가 뉴스 본문에 나타난 횟수로
테마를 활성화한다. (a) "건설부동산"/"해운물류"/"화학소재" 같은 **복합 분석 라벨은 실제 기사
본문에 거의 등장하지 않아** 활성화되지 못하고, (b) M&A·경영권 매각·지분 인수 같은 **이벤트
촉매는 어떤 섹터-테마 키워드에도 매핑되지 않아** 테마 경로가 원천적으로 눈멀다. 이 탐지기는
`stock_theme_groups` 테이블을 사용하지 않는다(브리핑 오해 정정) — 실제 병목은 키워드→섹터
맵의 표현력이다.

### Root Cause 3 — 공시 역신호 페널티의 무차별성

SPEC-AI-028은 "최대주주변경"을 역신호로 보고 점수를 0.3배로 삭감한다. 부실 매각·경영권
분쟁성 최대주주변경에는 옳지만, 프리미엄을 지불한 **전략적/재무적 인수자의 최대주주변경은
강력한 호재**다. 페널티는 이 둘을 구분하지 못하고, 호재성 인수 공시의 점수까지 눌러 bypass
임계 이하로 만든다.

### Root Cause 4 — volume_breakout 유니버스 제한 + 고정 배율

`detect_volume_breakout`의 유니버스는 Naver 거래량 순위 상위 50종목(`max_candidates//2`)으로
제한되어, 촉매성 중대형주가 거래대금은 크되 거래량 순위 상위 50에 없으면 평가조차 되지
않는다. 또 고정 `volume_ratio_threshold=3.0`은 20일 평균 거래량이 이미 높은 중대형주에는
과도한 문턱이며(강한 촉매일에도 2~2.5x에 그칠 수 있음), 오전 스캔에서는 당일 누적 거래량이
아직 부분값이라 배율이 더욱 과소평가된다.

---

## 설계 원칙 (Design Principles)

1. **확신도는 판별 신호이지 완화 지시가 아니다**: 확신도는 게이트를 자동으로 여는 것이
   아니라, 확신도가 HIGH일 때만 명시된 완화 경로(과열 상한 상향, 공시 페널티 면제)를
   조건부로 연다. 나머지 안전 게이트는 전 구간 유지된다.
2. **SPEC-AI-030 보존**: 신선도(Gate2)·분산(Gate3)·combo 단독 차단(Gate4)은 확신도와
   무관하게 항상 활성. 과열(Gate1)만 확신도 HIGH에서 상한이 완화된다. `catalyst_conviction.enabled=false`
   이면 본 SPEC의 모든 완화가 꺼지고 SPEC-AI-030/028 동작이 그대로 복원된다.
3. **기존 데이터·조회 재사용**: 확신도는 combo 탐지기가 이미 조회하는 NewsStockRelation
   행 집합의 집계 확장으로 산출한다. 신규 외부 API·신규 데이터 소스를 추가하지 않는다.
   volume_breakout 상대 임계는 SPEC-AI-065 `surge_baseline_service`를 재사용한다.
4. **가용 신호 정직성**: 시가(open_price)는 동기 경로에서 미가용하므로 등락률 판정은
   `change_rate`(전일대비)로 작성한다.
5. **설정 기반·하위 호환**: 모든 임계·스위치는 `surge_detection.yaml`에서 조정 가능하며,
   섹션 부재 시 문서화된 기본값으로 동작한다.
6. **범위 고정·영역 분리**: 앙상블 가중치(AI-039/044/062/065), 컨센서스 배율(AI-018),
   적응형 임계값(AI-029/038), 가중치 자동보정(AI-041), volume_breakout bypass 임계(AI-063)는
   변경하지 않는다. 본 SPEC은 확신도 판별과 그 위의 조건부 완화만 소유한다.

---

## EARS Requirements

### REQ-AI066-001: 촉매 확신도(Catalyst Conviction) 산출

**When** the surge scan evaluates a candidate that has same-day or overnight news
coverage, the system **shall** compute a catalyst conviction level for that candidate
from evidence already retrievable in the detector path, comprising at minimum:
(a) the count of distinct news articles covering the stock within the news window,
(b) the coverage duration (time span between the earliest and latest covering article),
(c) the aggregate sentiment strength of that coverage,
(d) the presence of high-impact catalyst keywords (기술이전/임상/수주 and, newly,
인수/합병/경영권), and
(e) whether a same-day or overnight disclosure backs the candidate.

**The system shall** classify conviction into at least two operative tiers — a HIGH
tier that unlocks the conditional relaxations of REQ-AI066-002 and REQ-AI066-003, and
a default (non-HIGH) tier under which all legacy SPEC-AI-030/AI-028 behavior is
unchanged.

**Where** the covering-article rows are already fetched by
`detect_volume_surge_news_combo` (`NewsStockRelation → NewsArticle → Stock` join), the
system **shall** derive (a)/(b)/(c) by aggregating that existing row set (article count,
min/max `published_at`, sentiment distribution) rather than issuing a new query per
candidate.

**Where** a candidate has no news coverage and no backing disclosure, the system
**shall** assign the lowest conviction tier (a stock with no catalyst evidence can
never be HIGH conviction).

### REQ-AI066-002: combo 과열 게이트 확신도 차등 완화

**When** `detect_volume_surge_news_combo` applies its overheat gate (SPEC-AI-030 Gate 1)
to a candidate, the system **shall** select the overheat ceiling based on that
candidate's conviction level: the default ceiling `combo_chase_guard.overheat_change_pct`
(current `5.0`) for non-HIGH conviction, and a higher ceiling
`combo_chase_guard.overheat_change_pct_high_conviction` (default `15.0`) for HIGH
conviction.

**If** a HIGH-conviction candidate's `change_rate` is below the high-conviction ceiling
but at or above the default ceiling, **then** the system **shall** allow the candidate
through the overheat gate (a confirmed strong catalyst still early in its move is not a
chase-buy).

**While** the overheat ceiling is relaxed for HIGH conviction, the system **shall** keep
the freshness gate (Gate 2, REQ-AI030-002), the distribution gate (Gate 3,
REQ-AI030-003), and the combo-only companion gate (Gate 4, REQ-AI030-004) fully active
and unchanged — a HIGH-conviction candidate that is stale, distributing (falling price on
high volume), or has no companion detector **shall** still be excluded.

**If** `catalyst_conviction.enabled` is `false`, **then** the system **shall** use the
default overheat ceiling for all candidates regardless of conviction (SPEC-AI-030 legacy
behavior fully restored).

### REQ-AI066-003: 전략적 인수/경영권 프리미엄 공시 페널티 예외

**When** `detect_disclosure_surge_pattern` would apply the SPEC-AI-028
`disclosure_type_filter.penalty_factor` to a disclosure whose text matches a
penalty pattern (e.g. "최대주주변경"), the system **shall** first check whether the
disclosure represents a strategic-acquisition / control-premium catalyst rather than a
distress event.

**If** the penalty-matched disclosure co-occurs with positive catalyst evidence — an
acquisition/merger high-impact keyword (인수/합병/경영권) AND positive-or-stronger news
sentiment AND a non-negative `change_rate` — **then** the system **shall** reduce the
penalty factor to `disclosure_type_filter.acquisition_penalty_factor` (default `0.7`,
i.e. **partial mitigation, not a full waiver**) for that candidate — a premium
acquisition is bullish, so the penalty is softened (0.3 → 0.7) but the disclosure score
is not fully restored (it stays capped below a non-penalized signal because
최대주주변경 always carries residual dilution/control-change risk).

**Where** the penalty-matched disclosure lacks positive catalyst evidence (no
acquisition keyword, or negative sentiment, or declining price), the system **shall**
retain the full SPEC-AI-028 penalty (distress-sale / control-dispute 최대주주변경 stays
penalized).

**If** `catalyst_conviction.enabled` is `false` OR the acquisition-exemption switch
`disclosure_type_filter.acquisition_exemption_enabled` is `false`, **then** the system
**shall** apply the full SPEC-AI-028 penalty unconditionally (legacy behavior).

### REQ-AI066-004: 뉴스 공동언급 기반 임시 테마 자동 확장

**When** the theme-detection path evaluates the recent news window, the system
**shall**, in addition to the existing keyword→sector-map matching, identify ad-hoc
thematic clusters as sets of stocks that are repeatedly co-mentioned together within the
same articles above a configurable co-mention threshold.

**Where** an auto-derived co-mention cluster is identified, the system **shall** use it
to contribute additional theme/conviction evidence for its member stocks, so that
event-driven or emergent themes not present in the predefined keyword→sector map (e.g.
an M&A cluster, a sector rally across unrelated issuers) can still surface leading
signals.

**Where** an auto-derived cluster corresponds to a corporate group / affiliate cascade
already handled by SPEC-AI-027 / SPEC-AI-035 (group_cascade), the system **shall not**
double-count it — this requirement owns only **non-affiliate co-moving clusters**;
affiliate cascades remain owned by group_cascade.

**If** the co-mention derivation is disabled via
`catalyst_conviction.comention_theme_enabled` (default may be `false` for staged
rollout), **then** the system **shall** fall back to keyword→sector-map matching only
(legacy behavior).

### REQ-AI066-005: volume_breakout 유니버스 확장 + 상대(relative) 임계 보강

**When** `detect_volume_breakout` assembles its candidate universe, the system
**shall** include, in addition to the top volume-rank leaders
(`fetch_volume_leaders_sync`), stocks that carry same-day/overnight catalyst evidence
(a backing disclosure or news coverage) so that a catalyzed mid/large-cap not present in
the top volume-rank list is still evaluated.

**When** `detect_volume_breakout` decides whether a candidate's volume constitutes a
breakout, the system **shall** support a per-stock relative threshold — derived from the
stock's own rolling volume baseline (reusing SPEC-AI-065 `surge_baseline_service` /
`stock_signal_baselines`, pure-Python, no numpy/sklearn) — as an alternative or
complement to the flat `volume_ratio_threshold`, so that a mid/large-cap whose absolute
ratio stays under `3.0` can still qualify when its volume is anomalous relative to its
own history.

**Where** the per-stock baseline is unavailable (cold start, insufficient samples), the
system **shall** fall back to the existing flat `volume_ratio_threshold=3.0` behavior
(conservative, no regression).

**If** the relative-threshold path is disabled via
`volume_breakout.relative_threshold_enabled` (default may be `false` for staged
rollout), **then** the system **shall** use only the flat ratio (legacy behavior). This
requirement **shall not** modify the SPEC-AI-062 weight or the SPEC-AI-063
`volume_breakout_bypass_threshold`.

### REQ-AI066-007: 고임팩트 뉴스 이벤트 구동 재스캔 (Event-Driven Rescan)

**When** the periodic news crawl job (`_run_crawl_job` → `crawl_all_news` +
`_run_keyword_matching`, scheduler.py:37~81) persists newly crawled articles and their
`NewsStockRelation` links, the system **shall** evaluate whether any newly stored article
meets the HIGH-conviction catalyst bar of REQ-AI066-001 (an acquisition/high-impact
keyword AND the required sentiment).

**If** at least one newly stored article meets the HIGH-conviction bar for a stock,
**then** the system **shall** trigger one asynchronous surge signal generation pass
(`run_surge_signal_generation`, fund_manager.py:2976, or a lightweight scoped variant)
for that event, without waiting for the next scheduled scan (08:00 / 09:05 / 10:00 /
15:20 KST).

**While** the event-driven rescan path is active, the system **shall** enforce abuse and
budget guards: a per-stock cooldown (`catalyst_conviction.event_rescan_cooldown_minutes`,
default `30`) that prevents re-triggering the same stock within the window, and a daily
cap (`catalyst_conviction.max_daily_event_triggers`, default `20`) on the total number of
event-driven triggers — the daily cap is REQUIRED because each pass consumes limited LLM
budget (Gemini free tier).

**Where** the daily cap is reached or the stock is within its cooldown window, the system
**shall** skip the event-driven trigger and defer to the next periodic scan (the event
path is a supplementary booster, never a replacement).

**The system shall not** remove, replace, or reschedule the existing periodic scans
(08:00 / 09:05 / 10:00 / 15:20 KST) — the event-driven pass runs in addition to them.

**If** `catalyst_conviction.event_rescan_enabled` is `false`, **then** the system
**shall** perform no event-driven triggering and rely solely on the periodic scans
(legacy behavior).

### REQ-AI066-006: catalyst_conviction 설정 추가

The system **shall** add a `catalyst_conviction` section under `surge_detection:` in
`backend/app/surge_config/surge_detection.yaml`, parsed by a new Pydantic model in
`backend/app/surge_config/surge_settings.py` and attached to `SurgeDetectionConfig` via
`Field(default_factory=...)`. The section **shall** define at minimum:

- `enabled`: bool master switch for all conviction-based relaxations (REQ-002/003).
  Default: `true`.
- `min_article_count_high`: int. Minimum distinct covering articles for HIGH conviction.
- `min_coverage_hours_high`: float. Minimum coverage duration (hours) for HIGH conviction.
- `min_sentiment_high`: float. Minimum aggregate sentiment strength for HIGH conviction.
- `acquisition_keywords`: list[str]. High-impact acquisition keywords (인수/합병/경영권 …).
- `comention_theme_enabled`: bool. REQ-004 toggle (default `false` staged).
- `comention_min_pairs`: int. Co-mention threshold for cluster derivation (REQ-004).
- `event_rescan_enabled`: bool. REQ-007 master toggle. Default: `false` (staged rollout).
- `event_rescan_cooldown_minutes`: int. Per-stock re-trigger cooldown (REQ-007). Default: `30`.
- `max_daily_event_triggers`: int. Daily cap on event-driven triggers (REQ-007, LLM budget
  guard). Default: `20`.

The system **shall** also add:
- `combo_chase_guard.overheat_change_pct_high_conviction`: float, default `15.0` (REQ-002).
- `disclosure_type_filter.acquisition_exemption_enabled`: bool, default `true` (REQ-003).
- `disclosure_type_filter.acquisition_penalty_factor`: float, default `0.7` — mitigated
  penalty factor for strategic-acquisition 최대주주변경 (REQ-003, partial mitigation).
- `volume_breakout.relative_threshold_enabled`: bool, default `false` staged (REQ-005).

**When** any of these keys is absent from the YAML, the loader **shall** apply the
documented defaults (backward compatible). All thresholds **shall** be adjustable without
code changes.

---

## Implementation Scope

| 파일 | 변경 내용 | 관련 REQ |
|---|---|---|
| `backend/app/surge_config/surge_settings.py` | `CatalystConvictionConfig` 신규 모델 + `SurgeDetectionConfig` 연결; `combo_chase_guard`/`disclosure_type_filter`/`volume_breakout` 모델에 신규 필드 추가 | REQ-006 |
| `backend/app/surge_config/surge_detection.yaml` | `catalyst_conviction` 섹션 + 3개 신규 필드 추가 | REQ-006 |
| `backend/app/services/surge_detector.py` | 확신도 산출 헬퍼 신규(NewsStockRelation 집계 확장); `detect_volume_surge_news_combo` 과열 게이트 확신도 분기(:641 인근); `detect_disclosure_surge_pattern` 페널티 예외(:976,986 인근); `detect_theme_news_cluster` co-mention 보강(:216~ 인근); `detect_volume_breakout` 유니버스+상대 임계(:3182,3211 인근) | REQ-001~005 |
| `backend/app/services/scheduler.py` | `_run_crawl_job`(:37~81) 뉴스 크롤+`_run_keyword_matching` 완료 직후에 HIGH-conviction 판정→이벤트 재스캔 트리거 훅 추가; 쿨다운·일일 상한 상태 관리 | REQ-007 |
| `backend/app/services/fund_manager.py` | `run_surge_signal_generation`(:2976) 이벤트 경로에서 비동기 1회 호출(또는 경량 스코프 변형 신규 함수). 기존 정기 호출 경로는 불변 | REQ-007 |
| `backend/tests/test_surge_ai066.py` (신규) | 확신도 tier 분류·과열 완화(HIGH 통과/분산·stale 여전히 차단)·페널티 부분완화(호재 인수 0.7/부실 매각 0.3 유지)·co-mention 클러스터·volume_breakout 상대 임계·이벤트 재스캔(쿨다운/일일상한/정기스캔 불변)·enabled=false 폴백·설정 부재 기본값 | 전체 |

---

## Non-Goals (What NOT to Build)

- **`overheat_change_pct` 자체를 단순 상향/제거하지 않는다.** SPEC-AI-030의 5% 기본 컷오프는
  non-HIGH 확신도에 대해 그대로 유지된다. 본 SPEC은 HIGH 확신도에 한해 별도 상한을 조건부로
  적용할 뿐이다.
- **신선도(Gate2)·분산(Gate3)·combo 단독 차단(Gate4)은 변경하지 않는다.** 확신도와 무관하게
  항상 활성.
- **시가(open_price) 기준 판정은 구현하지 않는다.** 동기 경로에 시가가 없으므로 등락률은
  `change_rate`(전일대비)로 판정한다. 시가/분봉 데이터 도입은 별도 후속 SPEC.
- **앙상블 가중치·컨센서스 배율·적응형 임계값·가중치 자동보정은 변경하지 않는다**
  (AI-018/029/038/041/044/062/065 소유 영역). volume_breakout 가중치(AI-062)와 bypass
  임계(AI-063)도 불변.
- **분(minute) 단위 실시간 스트리밍 인프라는 도입하지 않는다.** REQ-007 이벤트 트리거는
  기존 뉴스 크롤러(`_run_crawl_job`)의 **저장 완료 시점을 훅(hook)으로 사용하는 경량 방식**
  이며, WebSocket 실시간 가격/뉴스 스트림, 메시지 큐, 별도 상시 리스너 프로세스 등의
  스트리밍 인프라를 새로 도입하지 않는다. 트리거 해상도는 뉴스 크롤 주기에 종속된다.
- **정기 스캔(08:00/09:05/10:00/15:20 KST)을 제거·대체·재조정하지 않는다.** REQ-007
  이벤트 재스캔은 정기 스캔에 **추가되는 보강 경로**일 뿐이다.
- **이벤트 트리거는 무제한이 아니다.** 종목당 쿨다운과 일일 상한(REQ-007)으로 LLM 예산
  (Gemini 무료 tier)을 보호하며, 상한 초과 시 정기 스캔으로 위임한다.
- **LLM 기반 촉매 판정은 도입하지 않는다.** 확신도는 규칙 기반(기사 수/지속시간/감성/키워드/
  공시)으로 산출한다. LLM 원인분석은 SPEC-AI-060 소유.
- **분(minute) 단위 실시간 거래량 스트림은 도입하지 않는다.** 거래량은 일봉 해상도
  (`_get_volume_history`)로 판정한다.
- **REQ-004(co-mention 테마)와 REQ-005(volume_breakout 상대 임계)는 규모에 따라 별도
  자매 SPEC으로 분리 가능하다** — plan.md에서 분리 옵션을 제시한다. 두 요구는 P0 확신도
  코어(001~003)와 데이터 파이프라인이 상이하다.
- **GitHub 이슈 생성·백테스트 하네스 구축은 포함하지 않는다.** 효과 측정은 SPEC-AI-041
  평가 루프의 기존 지표로 관측한다.

---

## References

### 코드 위치 (수정/신규 대상, 2026-07-01 재확인)

- `backend/app/services/surge_detector.py`
  - `detect_volume_surge_news_combo()` (라인 487~680) — 뉴스 조회 :539~558(확신도 집계
    재사용), 과열 게이트 :641(REQ-002 분기점)
  - `detect_theme_news_cluster()` (라인 191~) — co-mention 보강(REQ-004)
  - `detect_disclosure_surge_pattern()` — 페널티 적용 :976, :986(REQ-003 예외 삽입점)
  - `detect_volume_breakout()` (라인 3165~3235) — 유니버스 :3182, 배율 컷 :3211(REQ-005)
  - `gather_surge_candidates()` (라인 1313~) — Gate 4 :1571~1584, bypass :1664~1685(불변)
- `backend/app/surge_config/surge_settings.py`
  - `CatalystConvictionConfig` 신규; `ComboChaseGuardConfig`/`DisclosureTypeFilterConfig`/
    `VolumeBreakoutConfig`(:214~223) 필드 추가 (REQ-006)
- `backend/app/surge_config/surge_detection.yaml`
  - `catalyst_conviction` 섹션 신규; `combo_chase_guard`(:156~164)/`disclosure_type_filter`
    (:123~134)/`volume_breakout`(:193~204) 필드 추가 (REQ-006)
- `backend/app/services/surge_baseline_service.py` (SPEC-AI-065) — REQ-005 상대 임계 재사용
- `backend/app/services/scheduler.py` (REQ-007)
  - `_run_crawl_job()` (라인 37~81) — `crawl_all_news`(news_crawler)로 NewsArticle 저장 →
    `_run_keyword_matching()`(:81)로 NewsStockRelation 생성. **이벤트 재스캔 훅 삽입점**
  - `_run_dart_crawl()` (라인 128~) — `fetch_dart_disclosures`; 공시 기반 촉매 트리거 보조
  - `_run_surge_signal_generate()` (라인 905~928) — 정기 급등 스캔 래퍼(15:20 KST +
    intraday); 이벤트 경로가 재사용할 대상, 정기 잡 등록은 불변
- `backend/app/services/fund_manager.py` (REQ-007)
  - `run_surge_signal_generation(db)` (라인 2976) — 이벤트 경로에서 비동기 1회 호출 대상

### 데이터·동작 사실 확인

- combo 탐지기 뉴스 조회: `NewsStockRelation.news_id → NewsArticle.id → Stock` 조인,
  현재 종목당 max sentiment만 보관(surge_detector.py:539~558). 확신도의 기사 수/지속시간은
  동일 행 집계로 산출 가능.
- 공시 페널티: `penalty_applied = any(kw in combined for kw in penalty_patterns)` →
  `best_score * penalty_factor(0.3)` (surge_detector.py:976,986). combined = report_name +
  ai_summary. 매수 실행 경로에도 `skip_bearish_in_today_signals`로 반영(surge_trading_service.py:261).
- volume_breakout 유니버스: `fetch_volume_leaders_sync(limit=max_candidates//2=50)`
  (surge_detector.py:3182); breakout 판정 `ratio = today_vol/mean_vol`,
  `ratio < volume_ratio_threshold(3.0)` 제외(:3211); 단독 bypass 임계 0.30 이미 존재(불변).
- `_fetch_price_change_sync` → `{"current_price","change_rate"}` 만, 시가 미가용.
- SPEC-AI-065 `stock_signal_baselines`/`surge_baseline_service.py` 순수 파이썬 z-score
  베이스라인 존재(numpy/sklearn 금지) — REQ-005 재사용 대상.

### 선행 SPEC

- SPEC-AI-012 / AI-018: 급등 탐지 시스템 + 앙상블 정밀화 (탐지기·그룹·컨센서스)
- SPEC-AI-028: 공시 역신호 필터링 (본 SPEC REQ-003이 예외 추가)
- SPEC-AI-030: 거래량콤보 추격매수 방지 (본 SPEC REQ-002가 확신도 차등 완화 — 보존)
- SPEC-AI-039: 고임팩트 뉴스 키워드 (확신도 키워드 재사용·확장)
- SPEC-AI-062 / AI-063: volume_breakout 탐지기 + 단독 bypass (REQ-005가 유니버스·임계 보강)
- SPEC-AI-065: z-score 상대 채점 + surge_baseline_service (REQ-005 재사용)
- SPEC-AI-027 / AI-035: group_cascade (REQ-004와 영역 분리 — 계열사 vs 비계열)

---

## Implementation Notes

### 마일스톤 완료 요약 (2026-07-01)

모든 6개 마일스톤(M1-M6)을 완료하여 REQ-AI066-001~007을 구현했다.

**구현 대상 파일:**
- `backend/app/services/surge_detector.py` — 확신도 산출, combo 과열 완화, 공시 페널티 예외, co-mention 테마, volume_breakout 유니버스/임계
- `backend/app/surge_config/surge_settings.py` — `CatalystConvictionConfig` 신규 모델 및 관련 필드 추가
- `backend/app/surge_config/surge_detection.yaml` — `catalyst_conviction` 섹션 및 관련 설정 추가
- `backend/app/services/scheduler.py` — 이벤트 재스캔 훅(REQ-007) 삽입
- `backend/app/services/fund_manager.py` — 이벤트 재스캔 트리거 호출
- `backend/tests/test_surge_ai066.py` (신규) — 40개 테스트, AC-1~AC-7 및 Edge Cases 커버

### 검증 결과 (2026-07-01)

**테스트 실행:**
```bash
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"
```
**결과: 1684 passed, 4 skipped, 3 xpassed, 0 failed** (403초 소요)

**린트 검사:**
```bash
uv run ruff check .
```
**결과: 모든 검사 통과**

**테스트 파일 통계:**
- `test_surge_ai066.py`: 40개 신규 테스트, AC 기준 커버리지 100%
- 회귀: SPEC-AI-030/028/062/063/065 관련 기존 테스트 전량 통과 (xpassed 3개는 이전 skip 마크된 테스트가 실제로 통과한 사례)

### 구현 편차 3건 (정직한 보고)

다음 3건의 편차는 plan.md 및 spec.md와 구현 실제 사이에 발생했으며, 모두 필요한 근거를 가짐:

#### 편차 1: REQ-003 참고자료 함수명 오류
- **plan.md / spec.md (라인 976/986)**: 함수를 `detect_disclosure_surge_pattern`이라 명시
- **실제 코드**: 해당 라인에 있는 함수는 `detect_immediate_disclosure_signal`
- **수정 대상 위치**: 라인 번호는 정확했으나 함수명이 맞지 않음
- **해결**: 실제 코드 위치에서 수정 적용

#### 편차 2: REQ-005 게이팅 범위 확대
- **plan.md 의도**: volume_breakout의 상대 임계(relative threshold) 경로만 `relative_threshold_enabled` 플래그로 제어
- **실제 구현**: 유니버스 확장(universe expansion) **및** 상대 임계 경로 **모두** 단일 `relative_threshold_enabled` 플래그로 제어
- **근거**: 상대 임계만 게이트하고 유니버스 확장은 항상 활성 상태로 두면, disabled 상태에서 default(레거시) 동작과 미묘한 차이가 발생할 수 있음 → 이 SPEC의 staged-rollout 설계가 의존하는 "비활성화 시 레거시와 동등" 보장 위반
- **해결**: 두 기능을 단일 플래그로 묶음 (비활성화 시 완전히 레거시로 복원)

#### 편차 3: REQ-003 공시 제거 로직 추가
- **spec.md**: "penalty_factor를 0.3→0.7로 완화"
- **실제 구현**: penalty_factor 완화 **외에도** 해당 공시를 `penalized_stocks` 집합에서 제거
- **근거**: 공시를 `penalized_stocks`에 두면 `skip_bearish_in_today_signals` 필터가 해당 신호 전체를 차단하게 됨 → REQ-003이 "호재성 인수 공시의 신호를 살린다"는 취지를 달성 불가
- **해결**: penalized_stocks 제거를 REQ-003 범위에 포함 (신호 구조 보존)

### Staged Rollout 배치 현황

**M1/M2/M3 (기본 활성):**
- `catalyst_conviction.enabled=true` (마스터 스위치)
- 확신도 산출, combo 과열 완화, 공시 페널티 예외 즉시 적용
- 기존 SPEC-AI-030/028 동작과의 호환성 검증됨

**M4/M5/M5.5 (기본 비활성 — 단계적):**
- `comention_theme_enabled=false` (M4: co-mention 테마)
- `relative_threshold_enabled=false` (M5: volume_breakout 상대 임계)
- `event_rescan_enabled=false` (M5.5: 이벤트 재스캔)
- 초기 배포 시 보수적(disabled)으로 설정 → 관찰 후 점진적 활성화

### 위메이드(112040) 회귀 시험

SPEC의 근본 동기인 2026-06-30 위메이드 사례에 대해 `TestWemadeRegression` 테스트 클래스가 검증:

- **시나리오**: 15+건 다출처 M&A 뉴스, +29.85% 급등, 하루 4번 정기 스캔 전부 신호 0건 (구 시스템)
- **현재 동작**: 확신도 산출 HIGH → combo 과열 완화 통과 → 신호 생성 최소 1개 경로 보장
- **테스트**: 위메이드 + 구 시스템 조건 시뮬레이션 → 신호 발생 검증

### 설정 기본값 및 호환성

모든 신규 설정(`catalyst_conviction`, `combo_chase_guard.overheat_change_pct_high_conviction` 등)은 `surge_detection.yaml`에 명시적으로 선언되었으며, 섹션/필드 부재 시 코드에 hardcode된 기본값으로 fallback되어 **전체 하위 호환성 보장**.

예:
- `catalyst_conviction.enabled` 없음 → `true` 기본값
- `catalyst_conviction.min_article_count_high` 없음 → 3 기본값
- `event_rescan_enabled` 없음 → `false` 기본값 (staged)

### 의도적 불변성 (회귀 보호)

다음 요소는 변경되지 않았으며, 회귀 테스트로 검증:
- SPEC-AI-030 Gate2(신선도)/Gate3(분산)/Gate4(combo 단독) — 확신도 무관 항상 활성
- SPEC-AI-062/063 가중치(0.12) 및 bypass 임계(0.30)
- SPEC-AI-028 페널티 factor(0.3) — 예외 케이스 외 전면 유지
- 정기 스캔 일정(08:00/09:05/10:00/15:20 KST) — 이벤트 재스캔은 추가만, 대체 아님
