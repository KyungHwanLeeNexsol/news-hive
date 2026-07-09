# SPEC-AI-076 Research — 스캔 유니버스 풀 절단 크라우딩아웃 (Scan-Universe Pool Truncation Starvation)

조사 방식: `surge_detector.py`/`surge_universe_pool_service.py`/`surge_universe_member.py`/`scheduler.py` **직접 코드 read-only** + 2026-07-08 15:20 KST 라이브 스캔 DB 실측. 로그 추정이 아닌 코드 경로 확인.

---

## 1. 대상 함수와 정확한 버그 지점

`build_scan_universe(db, config, existing_codes)` — `backend/app/services/surge_detector.py:4113-4314` (SPEC-AI-065 소유). Pool A/B/C + existing를 조합해 급등예측 스캔 유니버스를 구성한다.

- Pool A(`:4149-4172`): 당일 DART 공시 종목(`Disclosure.rcept_dt == today_str`).
- Pool B(`:4174-4238`): 20일 평균 대비 거래량 200%+ 종목. 후보 소스는 `fetch_volume_leaders_sync(limit=140, max_pages=3)`이며 SPEC-AI-074가 `fetch_tracked_stock_codes` stocks 교집합으로 레버리지/인버스 ETF·ETN 크라우딩아웃을 **자기 입력 소스에서** 이미 제거함.
- Pool C(`:4240-4275`): 당일 `change_rate >= 5%` 종목(`SurgeActualOutcome`).

**버그 지점 — 최종 병합/절단(`:4288-4303`)**:

```python
universe_ordered = (
    pool_a_codes + pool_b_codes + pool_c_codes
    + [c for c in existing_codes if c not in entry_pool_map]
)
# dedup preserving order
final_universe = universe_dedup[:max_universe]   # max_universe = config.max_scan_universe = 150
```

단순 concat 후 `[:150]` 슬라이스다. 우선순위가 엄격한 A>B>C>existing이므로 **상위 풀 하나가 150 슬롯을 다 소진하면 하위 풀은 최종 스캔에서 전량 탈락**한다. 어떤 풀에도 슬롯 보장(floor)이 없다.

## 2. 라이브 실증 (2026-07-08 15:20 KST 스캔, DB 직접 조회)

| 항목 | 값 | 비고 |
|---|---|---|
| Pool A raw | 232 | SPEC-AI-073 DART 복구로 0→232 급증(당일 공시량은 시스템 통제 밖) |
| Pool B raw | 0 | Pool B 자체 필터가 그날 0건(크라우딩아웃 아님, 코드 경로로 확인된 pre-truncation 값) |
| Pool C raw | 52 | 당일 5%+ 실현 급등 종목 |
| final `scan_universe_size` | 150 | 설정 상한 |

Pool A(232)만으로 이미 150 상한을 초과 → 우선순위 A>B>C 단순 슬라이스이므로 그날 `final_universe`는 사실상 `pool_a_codes[:150]`. **Pool C 52건이 100% 실제 스캔에서 조용히 배제**됐고, 만약 Pool B가 후보를 냈다면 그중 일부/전부도 A가 소진한 슬롯 양에 따라 배제됐을 것이다.

이는 이전에 알려지지 않은 **구조적 버그**다: 한 풀의 일일 공급 급증(Pool A는 그날 공시가 몇 건 나느냐에 전적으로 의존)이 나머지 두 풀의 후보를 실제 스캔에서 조용히 0으로 만든다.

## 3. 관측 불가능성(observability) 함정 — 왜 8일간 안 보였나

`pool_counts`(`:4282-4286`)는 각 풀 리스트의 **raw pre-truncation 길이**를 기록한다 — 절단 후 실제 스캔에 살아남은 수가 아니다.

- `surge_universe_pool_service.persist_pool_counts`(`:26-74`)가 이 raw 값을 `SurgeUniversePoolHistory.pool_a/b/c_count`에 저장.
- 그 DB 이력 테이블은 "각 풀이 스캔에 몇 건 기여했나"처럼 보이지만 실제로는 "각 풀이 절단 전 몇 건을 찾았나"라 스캔 커버리지 진단 시 조용히 오도한다. `pool_a=232, pool_c=52`가 정상처럼 보여도 실제 스캔은 100% Pool A였다.

**반례이자 자산**: SPEC-AI-068의 `SurgeUniverseMember`(`surge_universe_member.py`)는 최종 유니버스 종목코드를 **entry_pool 태그와 함께** 저장(`persist_universe_members`, `surge_universe_pool_service.py:104-167`). 즉 **절단 후(post-truncation) 풀별 실제 스캔 수는 이미 `SELECT entry_pool, COUNT(*) ... GROUP BY entry_pool`로 복원 가능**하다. 07-08엔 모든 멤버 entry_pool=="pool_a", "pool_c"는 0건으로 충실히 기록돼 있었다(진단만 안 됐을 뿐). → 신규 컬럼 없이도 영속 진단 경로가 이미 존재한다.

## 4. 기존 불변(invariant) 선언 — 반드시 명시적으로 다뤄야 함

`build_scan_universe` 코드 영역에 이전 SPEC들이 남긴 "불변" 주석 2건:

- `:4183`(SPEC-AI-074 REQ-002): "`_min_ratio(2.0)·max_scan_universe(150)는 불변(Exclusion 4/5)`"
- `:4217`(SPEC-AI-067 REQ-004): "`Pool A/B/C 우선순위·max_scan_universe·_min_ratio=2.0은 불변(SPEC-AI-065 소유)`"

즉 최소 두 명의 이전 SPEC 저자가 이 상수/순서를 **의도적으로 건드리지 않기로** 선택했다(각자 변경 범위를 최소화해 이미 취약한 탐지 파이프라인을 흔들지 않으려는 의도로 추정).

**결정적 맥락**: 이 두 주석은 **2026-07-01~07-08 기간, Pool A가 DART 크롤러 장애로 구조적 0이던 때**(SPEC-AI-073가 07-08 복구) 작성됐다. Pool A=0이면 A+B+C 합이 150을 넘는 일이 드물어 **절단의 크라우딩아웃 실패 모드가 아예 발현할 수 없었고 검증된 적도 없다**. 불변은 그 결함이 보이지 않는 조건에서 확인된 것이다. SPEC-AI-073의 DART 복구는 이전 저자들이 예상하지 못한 **진짜 새로운 사실**이다.

## 5. 상수/설정의 실제 성격 — 무엇을 보존해야 하나

- `max_universe = config.max_scan_universe`(`:4142`, 150). 목적은 **스캔 비용 상한** — Pool B 후보마다 `fetch_stock_price_history_sync(code, pages=3)` 네트워크 호출이 나가고, 스캔된 후보마다 탐지기(일부 LLM 예산 소모)가 돈다. 150은 임의 숫자가 아니라 비용/레이트리밋 가드다. → **전역 상향은 실제 비용 증가**를 유발한다.
- 불변 주석은 (1)비용 상한(150)과 (2)슬롯 배분 정책(엄격 A>B>C 슬라이스)을 **한 덩어리로 묶었지만 둘은 분리 가능**하다. 버그는 전적으로 (2)에 있다.

## 6. 호출부 / 테스트 자산 (fan_in, DDD characterization 대상)

`build_scan_universe` fan_in = 3:
- `surge_detector.py:1933` — `gather_surge_candidates` 내부(existing_codes 포함). 직후 `persist_pool_counts`(`:1953`)가 `scan_universe_size=len(_universe_codes)`(`:1960`) 주입 + `persist_universe_members`(SPEC-AI-068)로 종목코드+entry_pool 영속. **post-truncation 카운트 로깅/노출을 추가한다면 이 사이트가 자연 지점.**
- `scheduler.py:1226`, `:1243` — 별도 유니버스 진단/집계 잡.

기존 테스트: `test_spec_ai_065.py`(Pool A/B/C 조합 원본), `test_spec_ai_074.py`(Pool B ETF 배제). → 신규 characterization의 자연스러운 홈은 `test_spec_ai_065.py`(build_scan_universe 배분 로직의 정본 테스트).

`evaluate_surge_predictions`의 pool_counts 소비(`surge_evaluation_service.py:678-728`) 및 `get_pool_counts_for_date`(raw 카운트 T-1 조회, `:88-101`)는 **raw 의미에 의존** → SurgeUniversePoolHistory 컬럼 의미를 바꾸면 회귀. 보존 필요.

## 7. 별개 사안(스코프 경계 — 본 SPEC 아님)

- **Pool C 신호 품질(근본원인 #2)**: Pool C가 "당일 이미 급등한 종목"(후행성) 소스라 신호원으로 부적절할 수 있다는 별개 미해결 우려. 2026-07-11~07-14 관찰 후 판단 예정. 본 SPEC(절단/크라우딩아웃 메커니즘)과 **독립** — Pool C 신호가 좋든 나쁘든 절단 버그는 고쳐야 한다. **오히려 이 SPEC이 그 판단의 전제**: Pool C가 실제 스캔에서 100% 절단되면 "Pool C가 구조적으로 필요한가"를 판정할 근거(coverage) 자체가 오염된다 — 스캔되지 않은 풀의 가치는 측정 불가.
- **Pool A/B/C 후보 소싱 로직**: Pool A DART 쿼리, Pool B 거래량+ETF 필터(=074), Pool C outcome 쿼리 — 전부 불변. 본 SPEC은 **최종 배분/병합만** 바꾼다.

## 8. 설계 결론 (spec.md REQ의 근거)

1. **배분 메커니즘만 슈퍼시드**: 엄격 concat-then-slice → **풀별 최소 슬롯 예약(quota) 방식**. 각 풀에 후보가 있으면 `min(R_p, floor_p)` 슬롯 보장 후, 남은 용량을 기존 A>B>C>existing 우선순위로 채운다.
2. **비용 상한 보존**: `max_scan_universe=150` 상향 금지, `_min_ratio=2.0` 불변(074 소유). 총 유니버스 크기 <= 150 유지 → 스캔 비용 동일.
3. **백워드 호환 탈출구**: floors=0이면 quota == 엄격 슬라이스(= 레거시 거동). 회귀 가드 + 테스트 속성.
4. **관측성**: post-truncation 풀별 카운트를 계산·반환·로깅(신규 dict 키, 스키마 0). SurgeUniversePoolHistory raw 컬럼 의미는 보존. 영속 진단은 SurgeUniverseMember.entry_pool(SPEC-AI-068)로 이미 가능 → 신규 컬럼/마이그레이션 없음.

07-08 재현(floor_c=30, floor_b=20): reserved_c=min(52,30)=30, reserved_b=min(0,20)=0 → 보장 30(C); 잔여 120 → A 120; 최종 150 = A 120 + C 30. Pool C 0→30, 비용 불변.
