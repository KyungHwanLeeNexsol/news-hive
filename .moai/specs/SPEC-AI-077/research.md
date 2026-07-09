# SPEC-AI-077 Research — near_limit_up 후보 쿼리 NULL 시총 굶주림 (Near-Limit-Up NULL-Market-Cap Candidate Starvation)

조사 방식: `surge_detector.py`/`surge_settings.py`/`fund_manager.py`/`surge_detection.yaml`/`test_near_limit_up_carry.py`
**직접 코드 read-only** + 2026-07-09 라이브 DB 실측(`stocks` 테이블 카운트). 로그 추정이 아닌 코드 경로 확인.
작업 지시가 제공한 근본 원인은 코드·DB로 재검증됐고 이하 사실은 전부 현행 코드와 일치한다.

---

## 1. 대상 함수와 정확한 버그 지점

`detect_near_limit_up_carries(db, config)` — `backend/app/services/surge_detector.py:2649-2784` (SPEC-AI-023/072 소유).
전일(T-1) 종가-대-종가 change_rate가 `near_limit_up_min_pct`(15.0)~`near_limit_up_max_pct`(29.99)인 종목에 익일
`surge_candidate` 시그널을 발행한다(상한가 근접 모멘텀 이월).

**버그 지점 — 후보 풀 쿼리(`:2705-2716`)**:

```python
candidates = (
    db.query(Stock)
    .filter(or_(Stock.market_cap.is_(None), Stock.market_cap >= config.min_market_cap_eok))
    .order_by(nullslast(Stock.market_cap.desc()))
    .limit(config.max_stocks_to_check)   # 1200
    .all()
)
```

`nullslast(Stock.market_cap.desc())`는 시총 non-null 종목 **전체를 내림차순으로 먼저** 배치하고, 그 **뒤에** NULL
시총 종목 전체를 붙인다 — "상위 N by cap"에 NULL을 비례 삽입하지 않는다. `.limit(1200)`과 결합하면, non-null 종목
수가 한도에 근접·초과할수록 NULL 종목이 후보 풀에서 밀려난다.

## 2. 라이브 실증 (2026-07-09, DB 직접 조회)

| 항목 | 값 | 비고 |
|---|---|---|
| `stocks` 총 행 수 | 2605 | |
| non-null `market_cap` | 957 | |
| NULL `market_cap` | 1648 | 전체의 **63.3%** |
| `max_stocks_to_check` | 1200 | `NearLimitUpConfig` 기본값 |

957 < 1200이므로 쿼리는 non-null 957개를 먼저 모두 반환하고, 남는 `1200 − 957 = 243` 슬롯만 NULL 종목으로
채운다(그마저도 NULL 간 2차 정렬 키가 없어 **비결정적/물리적 PK 순서**). 결과: **`1648 − 243 = 1405`개 NULL 시총
종목(전체 NULL의 85%, 전체 `stocks`의 약 54%)이 이 탐지기에서 매일 통째로 평가되지 않는다** — 얼마나 급등했든 무관.

### 2.1 라이브 실세계 영향 (2026-07-09)

07-08 예측 대비 당일 실제 급등주 조사에서, 오늘의 실제 ~15-30% 급등주 4종(263800 데이타솔루션, 038870 에코바이오,
189330 씨이랩, 214330 금호에이치티)이 **NULL market_cap**이라 07-08 이 탐지기의 후보 풀에서 배제됐다. 모두 07-08
종가 기준 ~15-30% 상승한 정당한 near-limit-up-carry 후보였으나 탐지기가 **쳐다보지도 않았다**.

## 3. 왜 "숫자만 올리는" 이전 수정이 재발했나 (증상 vs 메커니즘)

코드 주석 이력(`:2701-2704`)이 이 버그가 **이미 한 번 발현**했음을 증언한다:

```
# 시총 상위 N 종목 — market_cap NULL 종목(전체의 60%+)도 후보 풀에 포함.
# 이전에는 NULL 제외로 남광토건 등 실제 상한가 근접 종목이 통째로 누락됐음.
# NULL은 nullslast()로 순위 뒤로 밀려 배치되며, max_stocks_to_check 확대로 도달 가능.
```

즉 이전 수정은 실제 종목(남광토건)이 NULL 배제로 누락되자 `max_stocks_to_check`를 **500 → 1200으로 올렸다**. 이것은
**증상 처치**(한도를 올려 NULL이 "도달 가능"하게)일 뿐 **메커니즘**(`nullslast`가 모든 non-null을 모든 NULL 앞에
배치)은 그대로 뒀다. non-null 종목 수가 상장/추적 확대로 시간에 따라 1200에 가까워지면 버그는 **더 큰 규모로 조용히
재발**한다. 지금(957)도 1405개가 이미 굶고 있다.

**→ 본 SPEC은 숫자를 다시 올리지 않는다.** 한도 상향은 (1)비용 무한 증가, (2)비굶주림 **미보장**(non-null이 한도를
넘으면 어떤 한도든 NULL=0). 반드시 배분 **메커니즘**을 고쳐야 한다(작업 지시의 명시적 요구).

## 4. 비용 제약 — 무엇을 보존해야 하나 (SPEC-AI-076 max_scan_universe와 유사)

후보 풀 쿼리를 통과한 각 종목마다(이미 오늘 시그널 있는 종목 스킵 후) `:2731`에서
`fetch_stock_price_history_sync(stock.stock_code)`를 호출한다 — 이것은 **Naver Finance 실 네트워크 스크레이프**(DB
읽기 아님)다. `max_stocks_to_check`가 제한하려는 실제 비용은 DB 쿼리 비용이 아니라 **후보당 네트워크 fetch 예산**이다.

- **핵심**: `max_signals_per_day` 기본값이 `None`(무제한, `surge_settings.py:569`)이라 루프는 조기 중단 없이 후보 풀의
  **모든** 종목(이미 시그널 있는 종목 제외)에 대해 fetch를 호출한다. 즉 실제 fetch 수 ≈ 후보 풀 크기 ≈
  `max_stocks_to_check`. → **비용 상한은 전적으로 "어느 1200개가 후보 SET에 들어오나"의 문제**이지 루프 순서 문제가
  아니다. 후보 SET만 고치면 되고 루프/`max_signals_per_day`는 건드릴 필요가 없다.
- **[HARD] 한도 제거 금지**: `.limit()`을 없애고 2605개 전부 평가하면 네트워크 fetch 예산이 2배 이상으로 폭증하고
  레이트리밋에 걸린다. 총 평가 후보 수 <= `max_stocks_to_check`(≈1200)를 반드시 유지한다.

## 5. 설정의 실제 성격 — SPEC-AI-076과의 결정적 차이 (yaml 비구동)

`NearLimitUpConfig`(`surge_settings.py:557-571`) 필드: `enabled`(True), `near_limit_up_min_pct`(15.0),
`near_limit_up_max_pct`(29.99), `max_stocks_to_check`(1200), `max_signals_per_day`(None), `min_market_cap_eok`(300).

- **[검증됨] `NearLimitUpConfig`는 yaml로 구동되지 않는다.** 유일한 생성 지점은 `fund_manager.py:3919`의
  `nlu_cfg = NearLimitUpConfig()` — **인자 없는 bare 생성**이다. `surge_detection.yaml` 전체에서 `near_limit_up`
  문자열은 **한 번도 등장하지 않는다**(grep 0건). → 값은 전적으로 Pydantic 기본값에서 온다.
- **함의(SPEC-AI-076과의 차이)**: AI-076의 `SurgeDetectionConfig`는 `get_surge_config()`로 yaml 로드되므로 floor
  키를 yaml에 추가했다. **AI-077은 그러면 안 된다** — `NearLimitUpConfig`에 추가하는 신규 필드는 **기본값 전용**이며
  yaml에 키를 넣어도 소비되지 않는 dead config가 된다. DDD 구현이 yaml 배선에 헛수고하지 않도록 이 사실을 명시한다.
- **[검증됨] 필드 충돌 없음**: AI-076이 추가한 `pool_b_min_slots`(:495)/`pool_c_min_slots`(:499)는 **`SurgeDetectionConfig`**
  소속이며 `NearLimitUpConfig`와 별개 클래스다. 이름 충돌 없음. 다만 신규 필드는 그 `*_min_slots` 명명 관례를 따른다.

## 6. 이 프로젝트의 기존 rotation/공정성 관례 (재사용 대상 — 새로 발명 금지)

작업 지시가 "새 관례를 발명하기 전에 기존 관례를 조사하라"고 했다. 코드베이스에 이미 두 가지가 있다:

- `crawlers/us_news.py:18,156` — 모듈 전역 `_us_rr_index`를 **사이클 간 지속**시키는 라운드로빈: `idx = (_us_rr_index + i) % len(queries)`
  후 `_us_rr_index = (_us_rr_index + MAX_US_QUERIES) % len(queries)`로 전진. 주석: "round-robin rotation for even
  coverage". → **정확히 우리가 필요한 "한도 초과 집합을 여러 사이클에 걸쳐 고르게 커버"하는 패턴**이다.
- `ai_client.py:103` — `rotated_free = free_indices[start:] + free_indices[:start]` 리스트 회전(API 키 분산).

→ NULL 서브셋 선택에 이 라운드로빈 "even coverage" 관례를 재사용한다. 단, 모듈 전역 커서는 **배포/재시작 시 0으로
리셋**되어 같은 head 종목을 재굶주림시키는 약점이 있으므로, 본 건에는 **스캔 날짜에서 유도한 결정적 offset**(무상태,
재배포 무관, 테스트에서 날짜 주입으로 정확히 재현 가능)을 권장한다. 두 방식 모두 "라운드로빈 even coverage" 관례의
구현 변형이다(발명 아님).

## 7. 기존 테스트 자산 (DDD characterization 대상)

`backend/tests/test_near_limit_up_carry.py` — AC-001~015(SPEC-AI-023) + AC-072-001~005 + EC-1~5. 인메모리 SQLite,
`fetch_stock_price_history_sync` mock, `_make_stock(db, code, name, market_cap=...)`, `_make_config(**kwargs)`.

- **중요**: `AC-014`(`:516`)는 **단일** NULL 시총 종목이 후보에 포함되는지만 본다(경쟁하는 non-null 없음). **현행
  테스트 중 어느 것도 "다수 non-null이 NULL을 한도에서 밀어내는 굶주림"을 재현하지 않는다.** 신규 characterization은
  non-null 수 > `max_stocks_to_check` 상황을 만들어 NULL 대표가 0으로 붕괴함을 재현해야 한다(재현 우선, Rule 4).
- `max_stocks_to_check`는 `_make_config(max_stocks_to_check=N)`로 테스트에서 축소 가능 → 소규모(N=3)로 굶주림 재현
  용이. `market_cap=None`으로 NULL 종목 생성 가능(AC-014 선례).
- 회귀 보호 필수: AC-001~015, AC-072-001~005, EC-1~5 전량. 특히 `min_market_cap_eok` 필터(소형주 배제,
  `test_bugfix_ai023_min_market_cap_eok_filters_small_cap_stock`)와 confidence 공식/surge_basis/paper_executed.

## 8. 별개 사안 (스코프 경계 — 본 SPEC 아님)

- **다른 탐지기의 유사 패턴**: `detect_bollinger_squeeze`(`:3636`)/group_cascade(`:3375`)/`:3752`는
  `Stock.market_cap.desc()`를 **`nullslast` 없이** 쓴다 → NULL 종목을 아예 전량 배제(더 심한 굶주림일 수 있으나 별개
  탐지기·별개 config). 본 SPEC은 **`detect_near_limit_up_carries` 한 함수만** 다룬다(스코프 규율, AI-072/074/076 관례).
- **NULL 종목 same-day 완전 커버리지**: 비용 상한(≈1200) 하에서 매일 1648개 NULL 전부 평가는 불가능하다. 본 SPEC은
  (a)비굶주림 floor + (b)날짜 로테이션으로 **시간에 걸친 커버리지**를 보장하되, 특정일에 로테이션 창 밖 NULL이 미평가될
  수 있음을 인정한다. NULL을 "급등 가능성" 신호(거래량/최근활동)로 사전 우선순위화하는 더 스마트한 선정은 별개 후속
  SPEC(스코프 밖).
- **market_cap 데이터 품질**: 63%가 NULL인 근본은 시총 수집 파이프라인 문제일 수 있으나, 데이터 백필/시총 채우기는
  본 SPEC 밖(AI-071/074 무백필 관례 계승).

## 9. SPEC-AI-076 선례 비교 (같은 병리, 다른 함수·다른 배선)

| 항목 | SPEC-AI-076 | SPEC-AI-077 (본 건) |
|---|---|---|
| 병리 | 나이브 정렬+절단이 하위 그룹을 굶김 | 동일(NULL 시총 서브그룹 굶김) |
| 대상 | `build_scan_universe` 최종 배분(집합 배분) | `detect_near_limit_up_carries` 후보 쿼리(SQL LIMIT) |
| 굶는 그룹 | Pool B/C(소규모, floor로 대부분 커버) | NULL 시총(1648, 거대 — floor로 일부만 커버) |
| 해법 | 풀별 min-slot quota | non-null 우선 + NULL floor quota **+ 날짜 로테이션** |
| 로테이션 필요성 | 낮음(풀 작아 floor로 충분) | **높음**(NULL 방대 → floor만으론 ~1400 영구 굶주림, 로테이션 필수) |
| 설정 배선 | `SurgeDetectionConfig` yaml **구동** → yaml 키 추가 | `NearLimitUpConfig` yaml **비구동**(bare) → **기본값 전용, yaml 금지** |
| 비용 상한 | `max_scan_universe`(150) 보존 | `max_stocks_to_check`(1200) 보존 |

→ 배분 quota 패턴은 계승하되, **NULL 서브그룹이 방대**하다는 차이 때문에 로테이션을 추가하고, **config가 yaml 비구동**
이라는 차이 때문에 yaml 배선을 배제한다. 기계적 복사가 아니라 상황 차이를 반영한 적응.

## 10. 설계 결론 (spec.md REQ의 근거)

1. **후보 쿼리를 두 개로 명시 분리**(AI-076의 그룹별 처리 계승): (a) non-null: `market_cap >= min_market_cap_eok`
   `ORDER BY market_cap DESC LIMIT K`; (b) NULL: `market_cap IS NULL` `ORDER BY <안정키> LIMIT M OFFSET rot`.
2. **NULL floor quota**: `reserved_null = min(null_count, null_cap_min_slots)`; non-null은 `max_stocks_to_check −
   reserved_null`까지; non-null이 미달이면 남은 슬롯을 NULL에 환원(오늘처럼 여유 있으면 거동 사실상 불변, 단 이제
   NULL >= floor **보장**). 총합 <= `max_stocks_to_check` → **비용 동일**.
3. **날짜 로테이션**: NULL 후보 수 > NULL 예산이면 스캔 날짜 유도 offset으로 서브셋 회전 → `ceil(null_count/M)` 스캔일
   내 모든 NULL이 최소 1회 평가(라운드로빈 even-coverage, us_news 관례 재사용). 07-08 실증 미탐지를 근본적으로 해소.
4. **백워드 호환 탈출구**: `null_cap_min_slots == 0`이면 후보 **집합**이 레거시 nullslast 거동과 동일(회귀 가드).
5. **비용 상한 보존**: `max_stocks_to_check` 상향 금지, `.limit()` 제거 금지. 총 후보 <= 1200.
6. **관측성**: non-null vs NULL 평가 수 + 로테이션 offset 로깅(굶주림이 로그에서 보이게). 스키마 0.
7. **설정**: `null_cap_min_slots`를 `NearLimitUpConfig`에 Pydantic 기본값으로 추가(**yaml 배선 없음**). `*_min_slots`
   명명 관례 계승. `null_cap_min_slots > max_stocks_to_check` 오설정은 clamp + 경고.

07-09 재현(축소 스케일, `max_stocks_to_check=3`, non-null 3 + NULL 2, `null_cap_min_slots=1`): 현행 = non-null 3만
후보, NULL 0 fetch(굶주림 재현). 수정 후 = non-null 2 + NULL 1(floor 보장) → NULL 최소 1건 fetch. 비용(총 3) 불변.
