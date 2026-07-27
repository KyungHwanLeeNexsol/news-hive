# SPEC-AI-088 인수 기준

> 각 인수 기준(AC)의 정본은 EARS 문장이다. 그 아래 "테스트 시나리오(Given/When/Then)"는 구현 검증을
> 위한 내부 교차참조이며, 정본 EARS 문장을 대체하지 않는다.

## Acceptance Criteria (EARS + 테스트 시나리오)

### AC-088-001 (REQ-001, fund_manager.py same_day 경로 계측)
- **EARS**: **Where** `_intraday_horizon == "same_day"`인 경우, **when**
  `_gather_surge_candidates()`가 신규 `surge_candidate` 시그널을 생성하면, the system **shall**
  `surge_metadata["pre_signal_change_pct"]`에 `fetch_current_price_with_change_sync()`가 이미
  반환한 `change_rate` 값을 저장하며, 추가 네트워크 호출을 발생시키지 아니한다.
- 테스트 시나리오: **Given** `_intraday_horizon="same_day"`로 설정, mock
  `fetch_current_price_with_change_sync`가 `{"current_price": 12540, "change_rate": 5.91}` 반환,
  **When** 신규 candidate에 대해 `_gather_surge_candidates()` 실행, **Then** 생성된
  FundSignal의 `surge_metadata`를 파싱하면 `"horizon": "same_day"`와
  `"pre_signal_change_pct": 5.91`이 모두 존재하고, mock 호출 횟수가 SPEC 적용 전 특성화
  테스트와 동일(1회)함을 확인.

### AC-088-002 (REQ-001, non-same_day 경로 무변경) [HARD]
- **EARS**: **Where** `_intraday_horizon != "same_day"`(예: 15:20 KST 정기 배치 스캔)인 경우,
  the system **shall NOT** `surge_metadata`에 `pre_signal_change_pct` 키를 포함시킨다.
- 테스트 시나리오: **Given** `_intraday_horizon` mock을 `"next_day"` 또는 미설정으로 구성,
  **When** `_gather_surge_candidates()` 실행, **Then** 생성된 `surge_metadata`에
  `pre_signal_change_pct` 키가 존재하지 않음(기존 `horizon` 키 생략 패턴과 동일 — SPEC-AI-083
  REQ-AI083-005의 바이트 동일 보존 관례를 그대로 계승).

### AC-088-003 (REQ-002, disclosure_impact_scorer.py same_day 즉시발화 계측)
- **EARS**: **Where** `_create_immediate_surge_signal()`이 부여한 `horizon`이 `"same_day"`인
  경우, the system **shall** `fetch_current_price_with_change()`로 교체된 호출의 반환값에서
  `current_price`는 기존과 동일한 코드 경로로 `price_at_signal`에, `change_rate`는 신규로
  `surge_metadata["pre_signal_change_pct"]`에 저장한다(단, 폴백 경로의 실제 조회 성공률은
  엔드포인트 차이로 달라질 수 있음 — plan.md R-2 참고).
- 테스트 시나리오: **Given** disclosure가 `_classify_disclosure_horizon`에 의해 `"same_day"`로
  분류되도록 시각 mock, `fetch_current_price_with_change`가 `{"current_price": 12540,
  "change_rate": 5.91}` 반환하도록 mock(기존 `fetch_current_price` 단일값 mock을 교체),
  **When** `_create_immediate_surge_signal()` 실행, **Then** 생성된 FundSignal의
  `price_at_signal == 12540`(SPEC 적용 전과 동일값) 이고 `surge_metadata["pre_signal_change_pct"]
  == 5.91`(신규), Naver fetch 호출 횟수는 SPEC 적용 전 특성화 테스트와 동일(1회).
- 테스트 시나리오(폴백 엔드포인트 델타, plan-auditor iteration 1 D2 지적 반영): **Given** 1차
  조회(시가총액 상위 50위, `fetch_naver_stock_list`)에서 종목이 발견되지 않아 모바일 API 폴백이
  실행되는 상황을 mock(두 시장 모두 빈 리스트 반환), 폴백 대상 엔드포인트가
  `/api/stock/{code}/price`(신)와 `/api/stock/{code}/integration`(구, 폐기)로 서로 다름을
  코드 확인(`naver_finance.py:1268` vs `:1307`), **When** `_create_immediate_surge_signal()`
  실행, **Then** 이 엔드포인트 델타는 REQ-002가 명시하는 의도된 계측 정확도 개선(§Out of Scope의
  "탐지기 판정 로직 변경 아님" 원칙과 상충하지 않음)으로 특성화 테스트에 명시 기록되며 회귀로
  취급되지 않는다. 판정 로직(신뢰도 스코어링/앙상블 가중치) 무영향은
  `_is_same_day_event_horizon_signal()` 반환값 무변경으로 별도 확인(AC-088-006과 공유).

### AC-088-004 (REQ-002, next_day 경로 무변경)
- **EARS**: **Where** `horizon == "next_day"`인 경우, the system **shall NOT**
  `surge_metadata`에 `pre_signal_change_pct` 키를 포함시킨다.
- 테스트 시나리오: **Given** disclosure가 T-1 종가 이후 접수(next_day 분류)로 시각 mock,
  **When** `_create_immediate_surge_signal()` 실행, **Then** `surge_metadata`에
  `pre_signal_change_pct` 키 부재.

### AC-088-005 (REQ-003, near_limit_up_carry 불변식 계측)
- **EARS**: **When** `detect_near_limit_up_carries()`가 `near_limit_up_carry` FundSignal을
  생성하면, the system **shall** `surge_metadata["pre_signal_change_pct"]`를 `0.0`으로 설정하며,
  이는 `price_at_signal == t1_close`라는 기존 불변식(SPEC-AI-072/075)의 직접적 결과다.
- 테스트 시나리오: **Given** 상한가 근접 후보 종목의 일봉 이력에서 `t1_close=19220`,
  `change_rate=8.5`(근접 조건 충족)로 계산되도록 mock, **When**
  `detect_near_limit_up_carries()` 실행, **Then** 생성된 FundSignal의
  `price_at_signal == 19220 == t1_close`이고 `surge_metadata["pre_signal_change_pct"] == 0.0`,
  이 계산 과정에서 신규 네트워크 fetch가 발생하지 않음(기존
  `fetch_stock_price_history_sync` 호출 횟수 불변).

### AC-088-006 (REQ-004, 하위 호환 — 필드 부재 시 안전 처리) [HARD]
- **EARS**: **When** 소비자가 `pre_signal_change_pct` 키가 없는(이 SPEC 이전 생성 또는
  `detect_theme_news_carry` 등 미커버 경로가 생성한) `surge_metadata`를 읽으면, the system
  **shall** 예외 없이 `None`(API 응답에서는 `null`)을 반환하며, 기존
  `_is_same_day_event_horizon_signal()`/`_is_near_limit_up_carry_signal()`의 판별 결과는
  이 SPEC 적용 전후로 완전히 동일하다.
- 테스트 시나리오: **Given** `pre_signal_change_pct` 키가 없는 기존 형식의 `surge_metadata`
  JSON 문자열(3종: near_limit_up_carry 마커 포함, same_day horizon 마커 포함, 둘 다 없음)과
  `surge_metadata=None`, 그리고 손상된 JSON 문자열, **When** 신규 헬퍼
  `_extract_pre_signal_change_pct()`를 각각에 대해 호출, **Then** 모든 경우 예외 없이 `None`을
  반환. **또한 When** 동일한 4종 입력에 대해 `_is_same_day_event_horizon_signal()`/
  `_is_near_limit_up_carry_signal()`을 호출, **Then** 반환값이 이 SPEC 적용 전 특성화 테스트
  스냅샷과 완전히 동일(회귀 없음).

### AC-088-007 (REQ-005, evaluation/{date} API 노출)
- **EARS**: **When** `GET /api/surge-trading/evaluation/{date_str}`가 `pre_signal_change_pct`를
  포함한 `surge_metadata`를 가진 `surge_candidate` 시그널을 대상 날짜에서 조회하면, the system
  **shall** 응답의 `signal_details` 리스트 내 해당 종목 항목에 `"pre_signal_change_pct"` 키를
  올바른 값으로 포함시킨다.
- 테스트 시나리오: **Given** DB에 `surge_metadata`가 `{"pre_signal_change_pct": 5.91, ...}`를
  포함하는 FundSignal 행 존재, **When** `GET /api/surge-trading/evaluation/{date_str}` 호출,
  **Then** 응답 JSON의 `signal_details[i]["pre_signal_change_pct"] == 5.91`.

### AC-088-008 (REQ-005, prediction-history API 노출 — 양쪽 분기)
- **EARS**: **When** `GET /api/surge-trading/prediction-history`가 "오늘 미평가" 분기(`:449-490`)
  또는 "과거 평가완료" 분기(`:492-` 이하)에서 시그널 item dict를 구성하면, the system **shall**
  두 분기 모두에서 `"pre_signal_change_pct"` 키를 포함시킨다(값이 없으면 `null`).
- 테스트 시나리오: **Given** 오늘 생성된 미평가 signal 1건(`pre_signal_change_pct=3.2` 포함)과
  과거 평가완료 signal 1건(`pre_signal_change_pct` 키 부재, 하위호환 케이스), **When**
  `GET /api/surge-trading/prediction-history` 호출, **Then** 오늘 미평가 분기 item에
  `"pre_signal_change_pct": 3.2`, 과거 평가완료 분기 item에 `"pre_signal_change_pct": null`.

### AC-088-009 (REQ-AI088-001~005 전체, cross-cutting 백워드 호환) [HARD]
- **EARS**: **While** 이 SPEC이 다루지 않는 모든 기존 시그널 생성/평가 경로(표준 T-1→T
  앙상블, `detect_theme_news_carry`, 탐지기 신뢰도/임계값)가 그대로인 동안, the system
  **shall** 이 SPEC 적용 이전과 바이트 동등한 시그널 생성·평가 결과를 낸다(단
  `surge_metadata`에 추가된 `pre_signal_change_pct` 키 자체는 제외).
- 테스트 시나리오: **Given** 이 SPEC의 3개 계측 경로가 정상 동작하는 상태, **When** 전체
  백엔드 테스트 스위트 실행(`uv run pytest tests/ --tb=short -q -m "not slow"`, backend/에서
  실행), **Then** 무회귀(기존 통과 테스트 전부 유지) + `ruff check .` 통과.

## REQ ↔ AC 추적성 매트릭스

| REQ | 대응 AC |
|-----|---------|
| REQ-AI088-001 | AC-088-001, AC-088-002 |
| REQ-AI088-002 | AC-088-003, AC-088-004 |
| REQ-AI088-003 | AC-088-005 |
| REQ-AI088-004 | AC-088-006 |
| REQ-AI088-005 | AC-088-007, AC-088-008 |
| REQ-AI088-001~005 (전체, cross-cutting) | AC-088-009 |

REQ-001~005 전량이 최소 1개 AC로 커버됨(5/5, 미커버 REQ 0건). AC-088-009는 개별 REQ가 아닌 SPEC
전체의 부가 전용(additive-only) 설계 원칙을 검증하는 cross-cutting AC로, REQ-001~005 전량을
대상으로 한다(plan-auditor iteration 1 D3 지적 반영 — 이전에는 REQ 역참조가 추적성 매트릭스에
누락되어 있었음).

## 엣지 케이스

- `fetch_current_price_with_change_sync`/`fetch_current_price_with_change`가 `None`을 반환하거나
  `change_rate` 키가 없는 dict를 반환 → `pre_signal_change_pct` 키를 생략(저장하지 않음, `None`
  값으로 저장하지도 않음 — 기존 `_signal_current_price is None` 관용 폴백과 동일 fail-safe
  원칙).
- `_gather_surge_candidates()`의 기존 시그널 갱신 분기에서 `_existing_is_immediate=True`(마커
  인지형 스킵, SPEC-AI-080)인 경우 → `surge_metadata` 자체가 갱신되지 않으므로
  `pre_signal_change_pct`도 갱신되지 않음(기존 마커 보존 로직과 완전히 동일 동작, 특별 처리
  불필요).
- `detect_theme_news_carry()`(SPEC-AI-084)가 생성한 `horizon: "same_day"` 시그널 →
  `pre_signal_change_pct` 키 부재(§Out of Scope에 명시된 의도적 갭). AC-088-006의 하위 호환
  경로로 안전하게 `None` 처리됨을 확인.
- near_limit_up_carry 후보 종목의 일봉 이력 조회 자체가 실패(`fetch_stock_price_history_sync`가
  빈 리스트 반환) → 해당 종목은 애초에 시그널 자체가 생성되지 않음(기존
  `if not history: continue` 로직 불변, `pre_signal_change_pct` 계측과 무관).

## Definition of Done

- [ ] REQ-001~005 전량이 대응 AC(AC-088-001~009)로 커버됨 — 추적성 매트릭스 기준 미커버 REQ 0건
- [ ] AC-088-001~009 전부 특성화 테스트 통과 (RED→GREEN)
- [ ] AC-088-002/004/006/009 백워드 호환(바이트 동등/안전 처리) 통과 [HARD]
- [ ] AC-088-001/002/003 신규 fetch 비용 0 확인(mock call-count assert)
- [ ] 전체 스위트 무회귀 (`uv run pytest tests/ --tb=short -q -m "not slow"`, backend/에서 실행)
- [ ] `uv run ruff check .` 통과
- [ ] 신규 DB 마이그레이션 0건
- [ ] `_is_same_day_event_horizon_signal()`/`_is_near_limit_up_carry_signal()` 코드 무변경 확인(diff 0)
