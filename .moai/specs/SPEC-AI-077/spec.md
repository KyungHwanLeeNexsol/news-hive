---
id: SPEC-AI-077
version: 1.0.0
status: completed
created: 2026-07-09
updated: 2026-07-09
author: MoAI
priority: High
issue_number: 0
---

# SPEC-AI-077: near_limit_up 후보 쿼리 NULL 시총 굶주림 교정 (Near-Limit-Up NULL-Market-Cap Candidate Starvation Fix)

## HISTORY

- 2026-07-09 (v1.0.0): **구현 완료** — near_limit_up 탐지기 후보 풀 쿼리에서 NULL 시총 종목 85% 미평가 버그 수정.
  commit: `9036490`, 테스트: `test_near_limit_up_carry.py` 356 라인 확장, 전체 1905건 PASS.
  AC-077-001~004 전부 충족. NULL 종목에 최소 슬롯 quota + 날짜 로테이션으로 균등 평가 보장.

- 2026-07-09 (v0.1.0): 최초 작성. 별도 조사(read-only 코드 검증 + 2026-07-09 라이브 DB 실측)로 확정된
  **near_limit_up 후보 풀 쿼리의 NULL 시총 굶주림 버그**를 SPEC화.
  - **버그**: `detect_near_limit_up_carries()`(`surge_detector.py:2649-2784`, SPEC-AI-023/072 소유)의 후보 풀
    쿼리(`:2705-2716`)가 `.order_by(nullslast(Stock.market_cap.desc())).limit(config.max_stocks_to_check)`를
    쓴다. `nullslast`는 non-null 시총 종목 **전체를 먼저**, NULL 시총 종목 전체를 **그 뒤에** 배치하므로,
    non-null 수가 한도에 근접·초과하면 NULL 종목이 후보에서 밀려난다. 어떤 NULL 대표 슬롯도 보장되지 않는다.
  - **정량 근거(라이브, 2026-07-09 DB 직접 조회)**: `stocks` 2605행 중 non-null `market_cap` **957**, NULL
    **1648**(63.3%). 957 < `max_stocks_to_check`(1200)이므로 쿼리는 non-null 957 전부 + 남은 243 슬롯만 NULL로
    채운다(NULL 간 2차 정렬 키 없어 비결정적). 결과: **NULL 1405개(전체 NULL의 85%, 전체 stocks의 ~54%)가 매일
    이 탐지기에서 통째로 미평가** — 얼마나 급등했든 무관.
  - **라이브 실세계 영향**: 07-08 실제 ~15-30% 급등주 4종(263800/038870/189330/214330)이 NULL market_cap이라
    07-08 후보 풀에서 배제됨(전부 정당한 near-limit-up-carry 후보였으나 탐지기가 쳐다보지 않음).
  - **선택 접근**: 후보 쿼리를 non-null/NULL 두 쿼리로 분리 + NULL 최소 슬롯 quota(floor) + **날짜 로테이션**으로
    교체. `max_stocks_to_check`(1200) 상향 없음, `.limit()` 제거 없음(비용 상한 보존). 상세는 아래 "증상-처치
    슈퍼시드 결정" 절.

---

## 증상-처치 슈퍼시드 결정 (Symptom-Fix Supersession Decision) [HARD]

이 코드 영역에 이전 저자가 남긴 **증상 처치**를 명시적으로 다룬다:
- `:2701-2704` 주석: "이전에는 NULL 제외로 남광토건 등이 누락됐음. NULL은 nullslast()로 뒤로 밀리며,
  `max_stocks_to_check` **확대(500→1200)**로 도달 가능."

**결정: 배분 메커니즘 교체(숫자 상향 폐기).** 이전 수정은 실제 종목 누락에 대응해 한도를 500→1200으로 올렸으나,
이는 **증상 처치**다 — `nullslast`가 "모든 non-null을 모든 NULL 앞에" 배치하는 **메커니즘**을 그대로 뒀다.

**왜 숫자 상향이 틀렸나(작업 지시의 명시적 요구)**: (1)한도를 올리면 후보당 네트워크 fetch(`:2731`) 비용이 비례
증가한다. (2)비굶주림을 **보장하지 못한다** — non-null이 한도를 넘으면(시간이 흐르면 필연) 어떤 한도든 NULL 슬롯은
0으로 붕괴한다. 지금(non-null 957 < 1200)도 이미 1405개 NULL이 굶고 있고, non-null이 늘수록 악화된다. 숫자만
올리면 **재발을 지연시킬 뿐**이다.

**보존**: `max_stocks_to_check`(1200)의 실제 목적은 **후보당 네트워크 fetch 예산 상한**이다(각 후보마다 Naver
스크레이프 1회). 상향하지 않는다. 총 평가 후보 수 <= `max_stocks_to_check` 유지 → **스캔 비용 동일**.

**슈퍼시드**: 후보 **선정 메커니즘**만 — 단일 `nullslast` 쿼리 → (a) non-null 우선 쿼리 + (b) NULL floor quota
쿼리(날짜 로테이션). `:2701-2704` 주석을 "NULL 대표는 이제 floor quota + 날짜 로테이션으로 보장(SPEC-AI-077 소유),
`max_stocks_to_check`는 비용 상한으로 불변"으로 갱신한다.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

각 항목은 2026-07-09 코드 재확인 결과다. 본 SPEC은 **후보 풀 선정만** 바꾸며 탐지 임계·confidence 공식·metadata
소스·신호 발신·매매 로직을 바꾸지 않는다.

- **SPEC-AI-023 / SPEC-AI-072 (`detect_near_limit_up_carries` 본체) — 후보 선정만 인수**: AI-023이 탐지기 원본,
  AI-072가 change_rate 소스를 T-1 종가-대-종가로 교정(`_compute_t1_change_from_history`). 본 SPEC은 그 **입력
  후보 SET**만 고친다. change_rate 계산·`price_at_signal`·임계(15/29.99)·confidence(`change_rate/30*0.5`)·
  `surge_basis`·`paper_executed`·`metadata`는 전부 불변.
- **SPEC-AI-076 (`build_scan_universe` 절단 quota) — 배분 패턴 계승, 별개 함수**: 동일 병리(나이브 정렬+절단이
  하위 그룹 굶김)의 quota 해법을 계승하되 **다른 함수·다른 굶는 그룹(NULL 시총)**에 적용. AI-076의 `pool_b/c_min_slots`
  는 `SurgeDetectionConfig` 소속으로 본 SPEC의 `NearLimitUpConfig`와 **필드 충돌 없음**. 명명 관례(`*_min_slots`)만 계승.
- **[결정적 차이] `NearLimitUpConfig`는 yaml 비구동**: 유일 생성 지점 `fund_manager.py:3919` `NearLimitUpConfig()`
  bare 생성, `surge_detection.yaml`에 `near_limit_up` 0건. → 신규 설정 필드는 **Pydantic 기본값 전용**이며 yaml에
  넣으면 dead config. AI-076이 yaml 키를 추가한 것과 정반대로 **본 SPEC은 yaml을 건드리지 않는다**.
- **기존 rotation 관례 재사용**: `crawlers/us_news.py`(모듈 전역 라운드로빈 "even coverage")/`ai_client.py`(리스트
  회전)가 이미 존재 → NULL 서브셋 로테이션에 이 관례를 재사용(신규 발명 아님). 무상태·테스트 결정성을 위해 스캔
  날짜 유도 offset 권장.
- **SPEC-AI-043 (예측 기록 모드) — 매매 무개입**: 실매매 비활성. 매수 로직 diff 0. 자금 리스크 없음.

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, PostgreSQL 16(프로덕션) / SQLite(테스트). 배포: OCI VM
  베어메탈 + systemd(`newshive`). 운영 모드: **예측 기록 전용(실매매 비활성)** — 자금 리스크 없음.
- 대상 코드: `backend/app/services/surge_detector.py` `detect_near_limit_up_carries` 후보 쿼리(`:2705-2716`).
  설정: `app/surge_config/surge_settings.py` `NearLimitUpConfig`(`:557-571`). 호출부: `fund_manager.py:3919-3921`
  (`_run_coverage_expansion` 내부, `:3855` 정의, `:3052`에서 호출).
- 대상 테스트: `backend/tests/test_near_limit_up_carry.py`(탐지기 정본 테스트) 확장.
- 데이터/코드 사실(실측 2026-07-09):
  - 후보 쿼리는 `nullslast(market_cap.desc())` + `.limit(max_stocks_to_check)` 단일 쿼리이며 NULL 슬롯 보장 없음.
  - `stocks`: 2605행 = non-null 957 + NULL 1648. non-null(957) < 한도(1200) → NULL 243만 도달, 1405 굶주림.
  - 후보당 `fetch_stock_price_history_sync`(`:2731`) 실 네트워크 fetch. `max_signals_per_day=None`(무제한)이라
    후보 풀 전체가 fetch됨 → 비용 상한 = 후보 SET 크기 = `max_stocks_to_check`.
  - `NearLimitUpConfig`는 yaml 비구동(bare 생성) → 신규 필드는 기본값 전용.
- **신규 테이블/마이그레이션/스키마/yaml 변경 없음**(후보 쿼리 로직 변경 + `NearLimitUpConfig` 기본값 필드 추가만).

---

## Requirements (EARS)

### REQ-AI077-001 (P0, Unwanted Behavior) — NULL 시총 굶주림(starvation) 금지

**IF** non-null 시총 후보 수가 커서 레거시 `nullslast`+`limit`가 NULL 시총 종목을 후보 SET에서 `min(null_count,
null_cap_min_slots)` 미만으로 만들면, **THEN the system SHALL NOT** NULL 시총 후보를 그 값 미만으로 축소해서는
안 된다 — NULL 후보가 존재하면(`null_count > 0`) 후보 SET은 최소 `min(null_count, null_cap_min_slots)`개의 NULL
시총 종목을 **보유해야 한다**.

- 구체 보장(테스트 가능): non-null 후보 수와 무관하게, `null_cap_min_slots <= max_stocks_to_check`인 한 NULL 그룹은
  `min(null_count, null_cap_min_slots)` 슬롯을 확보한다. 예(라이브): non-null=957, NULL=1648, cap=1200,
  `null_cap_min_slots=300`이면 후보 SET의 NULL 시총 종목 수 >= 300(현행 243 및 미래 붕괴 0에서 교정).
- **[HARD]** 이는 **후보 선정 메커니즘 교체**다 — 탐지 로직·임계·metadata·루프·`max_signals_per_day`는 무변경.

### REQ-AI077-002 (P0, Ubiquitous) — 비용 상한 보존 (한도 상향/제거 금지)

The system **SHALL** `max_stocks_to_check`(1200) 값을 상향하지 않고 후보 풀의 `.limit()`(총 상한)을 제거하지
않으며, **총 평가 후보 수 <= `max_stocks_to_check`**를 항상 유지해야 한다.

- 후보당 `fetch_stock_price_history_sync` 네트워크 호출 예산이 변경 전과 동일하게 상한 이내로 유지된다.
- **[HARD]** non-null이 남은 슬롯을 채우는 **시총 내림차순 우선순위**는 보존한다(NULL floor 예약 후 잔여는 non-null
  우선). 굶주림 교정이 비용을 늘리지 않는다.

### REQ-AI077-003 (P0, State-Driven) — floor 예약 후 잔여는 non-null 우선으로 채움

**WHILE** NULL 최소 슬롯 예약을 확보한 뒤 남은 후보 예산을 배분하는 동안, the system **SHALL** non-null 종목을
시총 내림차순 우선순위로 먼저 채우고, non-null이 예산을 다 채우지 못하면 남은 슬롯을 추가 NULL 종목으로 채운 뒤,
전체를 중복 제거(순서 보존)해야 한다.

- 배분(권장 구현): (1) `reserved_null = min(null_count, null_cap_min_slots)`; (2) `non_null_limit =
  max_stocks_to_check − reserved_null`; (3) non-null을 `market_cap DESC LIMIT non_null_limit`로 조회(`nn`개);
  (4) `null_limit = max_stocks_to_check − len(nn)`(항상 >= `reserved_null` — 미달 non-null 슬롯을 NULL에 환원);
  (5) NULL을 `LIMIT null_limit` (+ 로테이션 offset)으로 조회; (6) `nn + null_rows` dedup, 총 <= cap.
- 절단 압력이 없으면(오늘처럼 여유) 거동은 사실상 현행과 동일(NULL 243)하되, 이제 floor가 **보장**되고 로테이션이
  적용된다.

### REQ-AI077-004 (P0, Event-Driven) — NULL 서브셋 날짜 로테이션 (공정성/시간 커버리지)

**WHEN** NULL 시총 후보 수가 해당 스캔의 NULL 예산(REQ-003의 `null_limit`)을 초과하면, the system **SHALL** NULL
서브셋을 **스캔 날짜에 대해 결정적인** 로테이션(라운드로빈 offset)으로 선정하여, 유계 스캔일 수(약 `ceil(null_count
/ null_limit)`) 내에 모든 NULL 시총 후보가 최소 1회 평가되도록 해야 한다 — 어떤 NULL 서브셋도 영구히 굶기지 않는다.

- **[HARD] 결정적(deterministic)**: 동일 스캔 날짜에는 동일 offset(같은 날 2회 실행 10:00/15:20이 동일 서브셋 —
  T-1 carry라 동일 데이터를 보므로 정합). 이는 07-08 실증 미탐지(안정 순서였다면 특정 NULL이 영구 배제)를 근본
  해소한다.
- 기존 프로젝트 관례(`us_news.py` 라운드로빈 "even coverage") 재사용. 모듈 전역 커서가 아닌 **무상태 날짜 유도
  offset**을 권장(재배포 리셋 없음, 테스트에서 날짜 주입으로 정확 재현).

### REQ-AI077-005 (P0, Event-Driven) — 절단 압력 없음 레거시 동등성 + 백워드 탈출구

**WHEN** 전체 후보(non-null + NULL) 수가 `max_stocks_to_check` 이하이면, the system **SHALL** 모든 후보를 후보
SET에 포함해야 하고(어떤 그룹도 탈락 없음), 결과 종목코드 **집합(set)**은 기존 거동과 동일해야 한다.

- **[HARD] 백워드 호환 탈출구**: `null_cap_min_slots == 0`이면 후보 선정 결과 **집합**이 레거시 단일 `nullslast`
  쿼리와 **동일**해야 한다(회귀 검증 속성 — floor·로테이션 무효화 시 레거시 복원).

### REQ-AI077-006 (P1, Ubiquitous) — 설정: NearLimitUpConfig 기본값 필드 (yaml 비구동)

The system **SHALL** `null_cap_min_slots`를 `NearLimitUpConfig`의 Pydantic **기본값 필드**로 추가하고, `null_cap_min_slots
> max_stocks_to_check`인 오설정 시 안전하게 축소(clamp)하고 경고 로그를 남겨야 한다.

- **[HARD] yaml 금지**: `NearLimitUpConfig`는 yaml로 구동되지 않으므로(bare 생성) 이 필드를 `surge_detection.yaml`에
  추가하지 않는다 — dead config 방지. 값은 기본값에서만 온다(향후 yaml 구동이 필요하면 별개 SPEC).
- 기본값(Run 단계 튜닝 시작점, 하드 불변 아님): `null_cap_min_slots ≈ 300`(현행 도달 NULL 243보다 크게 잡아 floor가
  실제 하한으로 작동). `null_cap_min_slots == 0`은 레거시 탈출구(REQ-005).

### REQ-AI077-007 (P1, Event-Driven) — 재현 우선 characterization + 회귀 보호

**WHEN** 굶주림 시나리오(non-null 후보 수 >= `max_stocks_to_check`, NULL 후보 존재)가 재현되면, the system
**SHALL** 수정 **전**에 "현행 쿼리에서 NULL 시총 종목이 후보로 도달한 수 = 0"임을 포착하는 실패 테스트가 작성·확인
되고, 수정 **후** 그 수가 `min(null_count, null_cap_min_slots)` 이상이 되어 통과해야 한다.

- **[HARD] 재현 우선(CLAUDE.md Rule 4)**: 수정 전 실패 테스트 먼저. 검증은 **관찰 가능한 사실**(`fetch_stock_price_history_sync`
  호출된 종목코드 집합 / 생성 시그널의 stock_id 집합)로 고정한다.
- 신규 characterization은 `test_near_limit_up_carry.py`에 추가한다. 기존 AC-001~015, AC-072-001~005, EC-1~5 전량
  무회귀(특히 `min_market_cap_eok` 소형주 배제, confidence 공식, `surge_basis`, `paper_executed`).

### REQ-AI077-008 (P1, Ubiquitous) — 굶주림 관측성

The system **SHALL** 후보 선정 시 non-null 대 NULL 시총 종목의 평가 수(및 적용된 로테이션 offset)를 로그로 남겨
굶주림/로테이션 진행이 로그에서 관측 가능하도록 해야 한다.

- 예: `[near_limit_up] 후보 non-null=957 NULL=300 (rot_offset=…) / 총 1200`. 신규 테이블/컬럼 없음(로그 전용,
  스키마 0).

---

## Exclusions (What NOT to Build) [HARD]

1. **`max_stocks_to_check`(1200) 상향 금지.** 비용 상한 보존(REQ-002). 숫자 상향은 재발을 지연시킬 뿐(증상-처치
   슈퍼시드 결정). 총 후보 <= 1200 유지.
2. **후보 풀 `.limit()` 제거 금지.** 2605개 전량 평가는 네트워크 fetch 예산 폭증 → 금지.
3. **`surge_detection.yaml` 무변경.** `NearLimitUpConfig`는 yaml 비구동(bare 생성) — floor 필드는 Pydantic
   기본값 전용. yaml 키 추가 금지(dead config 방지).
4. **신규 DB 테이블/컬럼/마이그레이션 금지.** 로테이션은 무상태(날짜 유도), 관측성은 로그 전용. 071~076이 세운
   무마이그레이션 관례 계승 — SPEC-AI-073류 프로덕션 전용 위험(락 데드락, VARCHAR 초과) 해당 없음.
5. **탐지 임계/공식/metadata/발신 무변경.** `near_limit_up_min_pct`(15.0)·`near_limit_up_max_pct`(29.99)·
   confidence(`change_rate/30*0.5`)·`surge_basis`·`paper_executed`·`yesterday_change_pct`·`price_at_signal`·
   reasoning·앙상블·min_score·적응형 임계 전부 불변. 유니버스(후보) 확장은 입력이지 발신 증가가 아니다.
6. **`max_signals_per_day` / 루프 로직 무변경.** 기본값 None 유지. 버그는 후보 SET에 있지 루프에 없다(연구 §4).
7. **change_rate 소스(=SPEC-AI-072) 무변경.** `_compute_t1_change_from_history`·`fetch_stock_price_history_sync`
   T-1 종가-대-종가 로직 불변. 본 SPEC은 **어느 종목을 후보로 넣나**만 바꾼다.
8. **다른 탐지기의 유사 정렬+한도 패턴 무변경.** `detect_bollinger_squeeze`(`:3636`)·group_cascade(`:3375`)·
   `:3752` 등은 별개 함수·별개 config — 본 SPEC은 `detect_near_limit_up_carries` 한 함수만(스코프 규율).
9. **NULL 종목 same-day 완전 커버리지 미달성.** 비용 상한상 매일 1648 NULL 전부 평가 불가. floor+로테이션으로
   시간에 걸친 커버리지만 보장. NULL을 급등 가능성 신호(거래량/최근활동)로 사전 우선순위화하는 스마트 선정은 별개
   후속 SPEC 후보.
10. **market_cap 데이터 백필 금지.** 63% NULL의 근본(시총 수집 파이프라인)은 별개. 시총 채우기/백필 없음(AI-071/074
    무백필 관례).
11. **과거 데이터 소급 재계산/백필 금지.** 이후 스캔 실행에만 전진 적용.

---

## Success Criteria

- **비굶주림**: 절단 압력 하(non-null >= cap)에서 NULL 후보가 존재하면 후보 SET에 `min(null_count, null_cap_min_slots)`
  이상 대표된다. 라이브형 replay(non-null 957, NULL 1648, cap 1200, `null_cap_min_slots=300`)에서 후보 SET의 NULL
  종목 수 >= 300(현행 243 및 non-null 성장 시 0에서 교정), 총 후보 == 1200(REQ-001/003).
- **비용 상한 보존**: 총 평가 후보 <= 1200 항상. `max_stocks_to_check` 상수 값 diff 0, `.limit()` 유지(REQ-002).
- **로테이션**: NULL 예산 초과 시 스캔 날짜별로 다른 NULL 서브셋 선정, `ceil(null_count/null_limit)` 스캔일 내 전
  NULL 1회 이상 평가. 동일 날짜는 동일 서브셋(결정적)(REQ-004).
- **레거시 동등성**: 절단 압력 없을 때 전 후보 포함·집합 동일. `null_cap_min_slots==0`이면 레거시 nullslast 집합과
  정확히 동일(REQ-005).
- **관측성**: non-null/NULL 평가 수 + offset 로깅(REQ-008). 스키마 0.
- **재현 우선**(Rule 4): 굶주림 시나리오에서 "현행 NULL 후보 도달=0"을 재현하는 실패 테스트가 수정 전 작성·확인,
  수정 후 통과. 기존 AC-001~015/072/EC 전량 무회귀. 신규/변경 로직 커버리지 85%+, `ruff` 무경고, 전체 백엔드
  스위트 회귀 없음(`-n 4` 병렬 포함)(REQ-007).
- **설정 안전성**: floor는 `NearLimitUpConfig` 기본값에서 읽히고(yaml 아님) `> cap` 시 안전 축소+경고(REQ-006).
- 탐지 임계/metadata/change_rate 소스/신호 발신/앙상블/매수 로직 diff 0. 신규 테이블/마이그레이션/yaml 변경 없음.

---

## MX Tag 대상 (Run 단계 식별)

- `detect_near_limit_up_carries`(`surge_detector.py:2649`) — 기존 `@MX:ANCHOR`(`:2646-2648`) 유지·갱신. 후보 선정
  계약(floor quota + 날짜 로테이션이 nullslast를 슈퍼시드; 비용 상한 보존) 명시.
- 후보 쿼리 지점(`:2705-2716`) — 두 쿼리 분리 + NULL floor + 로테이션을 `@MX:NOTE`(+`@MX:SPEC: SPEC-AI-077`)로 기록.
- 기존 증상-처치 주석 갱신: `:2701-2704` — "NULL 대표는 floor quota + 날짜 로테이션으로 보장(SPEC-AI-077 소유),
  `max_stocks_to_check`는 비용 상한으로 불변"으로 정정.
