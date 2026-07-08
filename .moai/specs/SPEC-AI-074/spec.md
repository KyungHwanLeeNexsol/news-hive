---
id: SPEC-AI-074
version: 0.1.0
status: completed
created: 2026-07-08
updated: 2026-07-08
author: MoAI
priority: Medium
issue_number: 0
---

# SPEC-AI-074: Pool B 거래량 순위 후보에서 레버리지/인버스 ETF·ETN 제외 (Pool B Volume-Leader Candidate De-pollution)

## HISTORY

- 2026-07-08 (v0.1.0): 최초 작성. 프로덕션 read-only 라이브 API 조사로 확정된 스캔 유니버스 Pool B의
  데이터 품질 버그를 SPEC화.
  - **버그 (급등 미탐지 유발)**: `build_scan_universe`(`surge_detector.py:4113`)의 **Pool B(거래량
    200%+ 당일 종목)**는 `fetch_volume_leaders_sync(limit=100)`(`:4179`, `naver_finance.py:840`)로
    Naver `sise_quant.naver`(절대 거래량 순위) 상위 종목을 후보로 가져온 뒤, 종목별 20일 평균 대비
    `_min_ratio=2.0`(200%+) 배율로 필터링한다. 그런데 절대 거래량 순위 상위는 **레버리지/인버스
    ETF·ETN이 구조적으로 점유**한다(라이브 `fetch_volume_leaders_sync(limit=20)` 테스트: `252670`
    KODEX 200선물인버스2X, `114800` KODEX 인버스, `252710` TIGER 200선물인버스2X, `233740` KODEX
    코스닥150레버리지, `069500` KODEX 200 등이 상위 다수). 이 상품들은 설계상 시장 최대 거래량
    상품이라 baseline 자체가 거대해 200%+ 비율 스파이크가 나지 않지만(관측 비율 0.27x~0.53x), 여전히
    상위 순위 슬롯을 점유해 **실제 200%+ 비율 스파이크가 난 중·소형주를 후보 집합에서 밀어낸다**
    (중·소형주는 200%+ 상대 급증에도 절대 거래량이 지수 파생상품에 못 미쳐 절대 순위 top-N에 진입하지
    못함).
  - **실증 (실제 미탐지)**: 2026-07-07 `109610`(에스와이)는 change_rate +29.95%, 거래량 비율 6.86x
    (임계 2.0x 크게 초과)였으나 급등 예측에서 미탐지. 중·소형주의 절대 거래량이 ETF·ETN 절대 거래량과
    경쟁하지 못해 Naver 절대 거래량 top-100에 진입하지 못한 것과 일치한다.
  - **선례 (입력 측 등가 수정)**: SPEC-AI-071(완료 2026-07-03)이 동일한 레버리지/인버스 ETN 오염을
    **정답(출력) 측**에서 이미 수정했다 — `collect_daily_surge_outcomes()`(정답 급등 모집단)를 앱
    `stocks` 테이블 존재 종목과 **교집합**하여 미추적 상품을 배제. **[중요 정정]** SPEC-AI-071은
    코드대역 휴리스틱(500000-599999/700000-799999)이 아니라 **`stocks` 테이블 교집합**
    (`_fetch_tracked_stock_codes`, `surge_actual_outcome_service.py:40`)을 사용했다. 코드베이스에
    코드대역 상수/`korea_stock_classification` 모듈은 **존재하지 않는다**(2026-07-08 확인). 본 SPEC
    (074)은 그 동일한 `stocks`-교집합 분류를 **입력 측**(Pool B 후보 소스)에 적용한다.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

각 항목은 2026-07-08 코드 재확인 결과다. 본 SPEC은 Pool B의 **후보 집합 구성(입력)**만 정제하며,
탐지기·앙상블 점수·발신 게이팅·매매 로직을 바꾸지 않는다.

- **SPEC-AI-071 (정답 수집 stocks 교집합) — 분류 로직의 단일 출처(재사용 대상)**: `_fetch_tracked_stock_codes`
  (`surge_actual_outcome_service.py:40`, `db.query(Stock.stock_code).filter(Stock.stock_code.in_(codes))`)는
  "앱이 추적하는 종목만 유효 후보"라는 권위적 분류를 이미 구현했다(코드대역 휴리스틱 아님). 본 SPEC은
  이 규칙을 **중복 구현하지 않고 재사용**한다. 규칙이 두 곳에 흩어지지 않도록 **단일 공유 헬퍼로 추출**해
  071 정답 경로와 074 Pool B 경로가 함께 import한다(구체 위치는 plan.md 결정). 071의 기존 테스트
  (`test_surge_actual_outcome_service.py`)가 추출 후 거동 불변의 회귀 가드다.
- **SPEC-AI-065 (build_scan_universe / Pool A~C) — 본 SPEC이 소유하는 대상 함수의 상위 SPEC**: Pool
  A/B/C 조합과 `max_scan_universe=150` 우선순위 절단(A>B>C>existing)은 AI-065 소유다. 본 SPEC은
  **Pool B의 후보 소스 정제만** 담당하며, Pool A/C, 우선순위, `max_scan_universe`는 불변으로 둔다.
- **SPEC-AI-067 (Pool B 당일 거래량 실시간성) — 인접·비충돌**: AI-067 REQ-004가 Pool B의
  `today_vol`을 장중 실시간 값으로 교정(`_resolve_today_volume`, `surge_detector.py:4192`). 본 SPEC은
  **후보 집합(어떤 종목을 검사하는가)**을 정제할 뿐 거래량 값 소스(AI-067)는 변경하지 않는다. 두 수정은
  직교한다(067=값의 정확성, 074=후보의 구성).
- **SPEC-AI-062/063/066 (detect_volume_breakout) — 동일 fetch 공유, 범위 밖**: 7번째 탐지기
  `detect_volume_breakout`(`surge_detector.py:3906`)도 `fetch_volume_leaders_sync`를 사용하며 동일한
  ETF·ETN 오염에 노출된다. 그러나 이 탐지기의 유니버스/임계/가중치/bypass는 AI-062/063/066 소유이므로
  **본 SPEC 범위 밖**이다. 본 SPEC의 수정은 Pool B(`build_scan_universe`)의 후보 조립에 국한하며,
  공유 fetch 함수를 수정할 경우에도 `detect_volume_breakout`의 거동(임계 3.0x·가중치·bypass)을
  바꾸지 않아야 한다.
- **SPEC-AI-073 (Pool B ETF 오염을 명시적 미래 SPEC로 유예)**: AI-073 Exclusion 2가 "Pool B 레버리지/
  인버스 ETF 오염 — 별도 미래 SPEC"이라고 유예했다. 본 SPEC이 그 후속이다.

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, PostgreSQL 16. 급등 예측은 예측 기록 전용 모드
  (실매매 비활성, SPEC-AI-043). 자금 리스크 없음.
- 대상 코드:
  - `backend/app/services/surge_detector.py` — `build_scan_universe`(`:4113`)의 Pool B 블록(`:4174-4212`),
    특히 `fetch_volume_leaders_sync(limit=100)` 호출부(`:4179`)와 후속 ratio 루프(`:4183-4208`).
  - `backend/app/services/surge_actual_outcome_service.py` — 재사용 대상 `_fetch_tracked_stock_codes`(`:40`).
  - `backend/app/services/naver_finance.py` — `fetch_volume_leaders_sync`(`:840`, 순수 Naver 스크레이퍼,
    `db` 세션 없음, 현재 sosok별 단일 페이지 스크레이프).
- **데이터 사실 (2026-07-08 확인)**:
  - 레버리지/인버스 ETF·ETN은 앱 `stocks` 테이블에 **부재**하다(SPEC-AI-071 전제 재확인). `stocks`
    교집합은 이들을 권위적으로 배제한다(코드대역 휴리스틱 불필요).
  - Pool B의 fetch 한도는 함수 인자에 **하드코딩된 `limit=100`**(`:4179`)이며 `max_scan_universe`(150)와
    무관하다. `_min_ratio=2.0`도 Pool B 블록 내 하드코딩(`:4181`)이다. 크라우딩아웃의 레버는 이
    후보-소스 한도이지 전역 유니버스 상한이 아니다.
  - `_fetch_tracked_stock_codes`는 `stocks` 조회 실패 시 `None`을 반환해 호출부가 **fail-open**(미필터
    진행)하도록 위임한다(SPEC-AI-071 EC-1 관례).
- 운영 모드: 예측 기록 전용. 본 SPEC은 스캔 유니버스 입력 품질 복구이며 발신량/매수 로직을 바꾸지 않는다.

---

## Requirements (EARS)

### REQ-AI074-001 (P0, Event-Driven) — Pool B 후보에서 비-`stocks` 상품(레버리지/인버스 ETF·ETN) 배제

**WHEN** `build_scan_universe`가 Pool B의 거래량 순위 후보 집합을 조립하면, **the system SHALL** 비율
(`ratio >= _min_ratio`) 필터링 **이전에** 앱 `stocks` 테이블에 존재하지 않는 코드(레버리지/인버스
ETF·ETN 및 기타 미추적 상품)를 후보에서 제외해야 한다.

- 분류는 SPEC-AI-071의 `stocks`-교집합 방식을 **재사용**한다(코드대역 휴리스틱·정규식 금지). "앱이
  추적하는 `stocks` 종목만 유효 후보"라는 권위적 규칙을 사용하며, 이는 Pool B가 결국 `stocks` 기반
  탐지기에 후보를 공급한다는 사실과도 일치한다(비-`stocks` 코드는 어떤 탐지기도 후보로 삼을 수 없는
  영구 false negative).
- **[HARD]** 분류 규칙이 두 곳에 중복되지 않도록 `_fetch_tracked_stock_codes`를 **단일 공유 공개
  헬퍼로 추출**하고, SPEC-AI-071의 정답 경로와 본 Pool B 경로가 동일 헬퍼를 import한다. 추출 후
  SPEC-AI-071의 거동은 불변이어야 하며 기존 `test_surge_actual_outcome_service.py`가 회귀 가드다.
  (판단 근거·대안은 plan.md; 규칙 이중화 방지가 핵심 계약이다.)
- **[HARD]** `_min_ratio`(2.0) 임계와 `max_scan_universe`(150)는 **변경하지 않는다** — 본 요구는 후보
  집합에서 비-`stocks` 상품을 제거하는 것이지 급등 판정 기준을 완화하는 것이 아니다.

### REQ-AI074-002 (P0, State-Driven) — 배제가 실제 중·소형주 슬롯을 확보

**WHILE** 레버리지/인버스 ETF·ETN이 원본 절대 거래량 순위 상위를 점유하는 조건에서, **the system
SHALL** 이들을 배제함으로써 확보된 슬롯을 실제 `stocks` 종목이 채우도록 하여, 배제 후 검사되는
**genuine-stock 후보 수가 배제 전보다 줄지 않도록** 해야 한다.

- 배제를 top-N 절단 **이후**에만 적용하면(현행처럼 top-100을 먼저 자른 뒤 필터) 이미 밀려난 중·소형주는
  복구되지 않는다. 따라서 배제는 후보 소스가 **충분한 genuine-stock 후보를 공급하도록** 원본 fetch가
  ETF·ETN 점유분을 보상해야 한다(크라우딩아웃 해소).
- 원본 후보 fetch 한도(`limit`)를 올려 보상할지, 아니면 스크레이프 단계에서 비-`stocks` 코드를 건너뛰어
  `limit`이 genuine 종목만 세도록 할지는 **plan.md의 설계 판단**이다. 스크레이핑 비용/지연 상한을
  고려하여 유계(bounded) 증가로 결정한다. 본 요구의 계약은 "배제가 순 genuine 후보를 감소시키지 않고
  오히려 크라우딩아웃을 완화한다"는 **결과**이지 특정 메커니즘이 아니다.
- **[HARD]** 후보 소스 정제로 인해 발신량(신호 수)이 구조적으로 증가하도록 설계하지 않는다 — 발신은
  여전히 `_min_ratio`·앙상블·적응형 임계·우선순위 절단이 게이팅한다. 본 요구는 **평가 대상(입력)** 확대이지
  발신 완화가 아니다(SPEC-AI-065 설계 원칙과 일관).

### REQ-AI074-003 (P0, Event-Driven) — 밀려났던 genuine 중·소형주 급증의 검증 가능한 표면화

**WHEN** 비-ETF/ETN `stocks` 종목이 `_min_ratio`(2.0) 이상의 거래량 비율을 갖는데 레버리지/인버스
상품이 원본 절대 거래량 순위를 지배하는 상황이면, **the system SHALL** 그 종목이 Pool B에 표면화되도록
해야 한다(수정 전에는 크라우딩아웃으로 미표면화되던 것을 수정 후 표면화).

- 이 요구는 관찰 가능한 수용 신호를 갖는다: 2026-07-07 `109610`(에스와이, 비율 6.86x) 사례 또는 이를
  본뜬 합성 픽스처(ETF·ETN이 절대 거래량 상위를 지배하는 순위 + 그 아래 200%+ 비율의 genuine 종목)에서,
  수정 후 그 genuine 종목이 Pool B(`pool_b_codes`)에 포함됨을 characterization 테스트로 증명한다.

### REQ-AI074-004 (P0, State-Driven) — `stocks` 조회 실패 시 fail-open

**IF** 후보 정제를 위한 `stocks` 교집합 조회가 실패하면(예: DB/SSL 끊김), **THEN the system SHALL**
Pool B를 **미필터로 진행**(현행 거동 보존)하여 조회 실패가 Pool B를 비우지 않도록 해야 한다.

- SPEC-AI-071 `_fetch_tracked_stock_codes`의 `None` 반환 → 미필터 진행(EC-1) 관례를 그대로 계승한다.
  조회 실패 시 `db.rollback()`으로 세션을 복구하고 정제 없이 후보를 진행한다.

### REQ-AI074-005 (P1, Event-Driven) — 배제 관측 로깅

**WHEN** Pool B 후보 정제가 하나 이상의 코드를 배제하면, **the system SHALL** 배제된 코드 수(및 예시
일부)를 로그로 남겨 오염 규모를 관측 가능하게 해야 한다.

- SPEC-AI-071 REQ-004의 배제 로깅 형식(`제외=%d건 (예: %s)`)과 일관되게 남긴다. 로그 레벨/문구는
  기존 `[스캔유니버스]` Pool B 로깅(`:4210`) 관례와 정합한다.

---

## Exclusions (What NOT to Build) [HARD]

1. **Pool A / DART 공시 파이프라인 — 범위 밖.** SPEC-AI-073에서 별도 처리됨. 본 SPEC은 Pool A를 건드리지
   않는다.
2. **Pool C 구조적 후행성 한계 — 범위 밖.** Pool C의 backward-looking 설계·지배/우선순위 로직은 별도
   유예 SPEC 사안이며 본 SPEC에서 손대지 않는다.
3. **탐지기·앙상블·발신 게이팅·매매 로직 무변경.** `compute_ensemble_score`, `gather_surge_candidates`,
   개별 탐지기, 적응형 임계/가중치, 매수 로직은 불변. `detect_volume_breakout`(AI-062/063/066)의 임계
   (3.0x)·가중치·bypass도 불변 — 공유 fetch를 수정하더라도 이 탐지기 거동은 바뀌지 않아야 한다.
4. **`_min_ratio`(2.0) 임계 완화 금지.** Pool B의 200%+ 판정 기준은 유지한다. 본 SPEC은 후보 오염
   제거이지 기준 완화가 아니다.
5. **`max_scan_universe`(150) 상향 금지.** 크라우딩아웃의 레버는 Pool B의 후보-소스 한도(`limit=100`)이지
   전역 유니버스 상한이 아니다. 후자는 건드리지 않는다.
6. **코드대역/정규식 휴리스틱 분류 금지.** 레버리지/인버스 식별은 `stocks`-교집합(SPEC-AI-071 방식)으로만
   한다. 500000-599999/700000-799999 같은 코드대역 상수를 신설하지 않는다(권위적 신호는 `stocks`이며,
   미추적 실제 기업도 동일 논리로 자연 제외됨).
7. **과거 데이터 소급 재계산/백필 금지.** 과거 스캔 유니버스/평가 재계산 없음. 수정일 이후 전진 적용만.
8. **발신량 확대 금지.** 후보(평가 대상) 확대이지 신호 발신 완화가 아니다(REQ-002 [HARD]).
9. **신규 테이블/마이그레이션 없음.** 기존 함수의 후보 조립 로직 변경 + 헬퍼 추출 리팩터에 국한한다.

---

## Success Criteria

- Pool B의 거래량 순위 후보가 비율 필터링 이전에 비-`stocks` 상품(레버리지/인버스 ETF·ETN + 미추적)을
  `stocks`-교집합으로 배제한다(REQ-001). 분류 규칙은 SPEC-AI-071과 **단일 공유 헬퍼**로 통합된다.
- 배제가 top-N 절단 이후가 아니라 후보 소스 단계에서 이뤄져, 배제 후 genuine-stock 후보 수가 배제 전보다
  줄지 않고 크라우딩아웃이 완화된다(REQ-002).
- `109610` 사례(또는 합성 픽스처)로 "ETF·ETN이 절대 거래량을 지배해도 200%+ 비율 genuine 종목이 Pool
  B에 표면화됨"이 characterization 테스트로 증명된다(REQ-003).
- `stocks` 조회 실패 시 Pool B가 미필터 fail-open으로 진행한다(REQ-004).
- 배제 종목 수가 로깅된다(REQ-005).
- **재현 우선(CLAUDE.md Rule 4)**: 현행 오염(ETF·ETN이 후보 슬롯을 점유해 genuine 종목이 Pool B에 못
  드는 상태)을 재현하는 실패 characterization 테스트가 수정 **전**에 작성·실패 확인되고, 수정 후 통과한다.
- SPEC-AI-071 거동 불변 — 기존 `test_surge_actual_outcome_service.py`가 헬퍼 추출 후에도 전량 통과.
- 신규/변경 로직 테스트 커버리지 85%+, `ruff` 무경고, 전체 백엔드 스위트 회귀 없음(`-n 4` 병렬 포함).
- 탐지기/앙상블/발신 게이팅/매수 로직 diff 0. 신규 테이블/마이그레이션 없음.

---

## MX Tag 대상 (Run 단계 식별)

- `build_scan_universe`(`surge_detector.py:4113`) Pool B 블록 — 스캔 유니버스 입력 계약의 경계. 후보
  정제 삽입점에 `@MX:NOTE`(SPEC-AI-074 의도)로 "비-stocks 배제 + 크라우딩아웃 보상" 기록.
- 추출된 공유 `stocks`-교집합 헬퍼 — 다수 호출부(071 정답 경로 + 074 Pool B) fan_in >= 2, 규칙의 단일
  출처. `@MX:ANCHOR`(+`@MX:REASON`)로 "앱 추적 종목만 유효 후보" 불변 계약 고정.

---

## Implementation Notes (2026-07-08)

manager-ddd가 DDD(ANALYZE-PRESERVE-IMPROVE)로 계획대로 구현. plan.md가 제시한 축 1(오염 제거)·
축 2(유계 오버페치)를 모두 채택했고, 계획 대비 범위 이탈 없음(커밋 1건, `e41cde6`).

- `_fetch_tracked_stock_codes`(SPEC-AI-071, `surge_actual_outcome_service.py`)를 신규
  `stock_registry_service.fetch_tracked_stock_codes`로 추출해 071(정답 경로)과 074(Pool B 경로)가
  동일 헬퍼를 import하는 단일 출처로 통합(거동 불변, 071 기존 테스트 무회귀로 확인).
- `build_scan_universe`의 Pool B 블록에서 비율 필터링 이전에 `stocks` 교집합을 삽입해 비-`stocks`
  상품(레버리지/인버스 ETF·ETN)을 배제.
- `naver_finance.fetch_volume_leaders_sync`에 유계 페이지네이션(`max_pages`, 기본값 1=기존 거동
  하위호환)을 추가하고, Pool B는 `limit=140`/`max_pages=3`으로 오버페치해 배제로 인한
  crowding-out을 보상(plan.md가 제시한 `limit≈130~150` 추정 범위 내에서 확정).
  `detect_volume_breakout`(SPEC-AI-062/063/066)은 기존 호출부를 그대로 사용해 영향 없음(diff 0
  테스트로 확인).
- `stocks` 조회 실패 시 fail-open(미필터 진행) + 배제 종목 수 로깅을 REQ-004/005대로 구현.
- 계획과의 divergence 없음 — SPEC-AI-073과 달리 배포 중 추가 프로덕션 이슈는 발견되지 않음(서비스
  재시작 정상, 에러 없음).

**최종 검증**:
- 로컬 전체 스위트: `pytest tests/ -n 4 -m "not slow"` **1860 passed, 4 skipped, 3 xpassed**
  (2026-07-08 재확인, `backend/tests/test_spec_ai_074.py` 479줄 신규,
  `test_surge_actual_outcome_service.py`(071) 전량 통과로 헬퍼 추출 회귀 없음 확인)
- 배포 확인: 프로덕션 `newshive.service` 재시작 후 `active (running)` 상태 유지, 재시작 직후
  에러 로그 없음(2026-07-08 SSH 확인). Pool B 크라우딩아웃 해소(`109610`류 genuine 종목 표면화)는
  급등 스캔 사이클의 특성상 다음 실제 거래일 관찰로 확인 예정(EC-5/롤아웃 전략에 따른 전진 관측).
- 상태: completed (커밋 `e41cde6`)
