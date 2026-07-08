# SPEC-AI-074 Acceptance Criteria

Given-When-Then 시나리오와 엣지케이스. 모든 기준은 관찰 가능(테스트 출력/`pool_b_codes` 내용/로그
문자열)해야 하며, 탐지기/앙상블/발신 게이팅/매수 로직 diff는 0이어야 한다. 신규 테이블/마이그레이션은
없다.

**재현 우선(CLAUDE.md Rule 4)**: AC-074-001의 재현 테스트는 수정 **전**에 작성되어 실패(genuine 종목이
크라우딩아웃으로 Pool B에 못 듦)함을 확인한 뒤, 수정 후 통과해야 한다.

---

## AC-074-001 (REQ-001/002/003) — 크라우딩아웃 재현 → 수정 후 genuine 종목 표면화

**Given** `fetch_volume_leaders_sync`가 반환하는 절대 거래량 순위 후보가 레버리지/인버스 ETF·ETN 코드
(예 `252670`, `114800`, `252710`, `233740`, `069500`)로 상위를 지배하고, 그 아래에 `stocks`에 존재하며
20일 평균 대비 비율 6.86x(>= `_min_ratio` 2.0)인 genuine 종목 `109610`이 있도록 픽스처가 구성된 상태
(`stocks` 교집합·history/volume은 mock)

**When** `build_scan_universe`(그 Pool B 조립)가 실행되면

**Then**:
- (수정 전, 재현) 현행 코드에서는 `109610`이 후보 top-N 밖으로 밀려 `pool_b_codes`에 **포함되지 않는다** —
  이 테스트가 수정 전 실패함을 확인한다.
- (수정 후) 레버리지/인버스 ETF·ETN 코드가 후보에서 **배제**되고, `109610`이 `pool_b_codes`에 **포함**된다.
- ETF·ETN 코드는 `pool_b_codes`에 **결코 포함되지 않는다**(비율 미달 + `stocks` 부재 이중 배제).
- 탐지기/앙상블/발신 게이팅 diff 0. `_min_ratio`(2.0)·`max_scan_universe`(150)는 변경되지 않는다.

---

## AC-074-002 (REQ-001) — 분류가 `stocks` 교집합으로 이뤄지고 규칙은 단일 출처

**Given** 후보 코드 목록이 `stocks`에 존재하는 코드와 존재하지 않는 코드(ETF·ETN + 미추적)를 섞은 상태

**When** Pool B 후보 정제가 실행되면

**Then**:
- 배제 판정은 앱 `stocks` 테이블 존재 여부(SPEC-AI-071 `_fetch_tracked_stock_codes` 규칙)로만 이뤄진다 —
  코드대역/정규식 휴리스틱을 사용하지 않는다.
- 분류 헬퍼는 SPEC-AI-071 정답 경로와 **동일한 단일 공유 헬퍼**다(규칙 이중화 없음). 헬퍼 추출 후
  `test_surge_actual_outcome_service.py`(071)가 전량 통과한다(거동 불변 회귀 가드).

---

## AC-074-003 (REQ-002) — 배제가 순 genuine 후보를 감소시키지 않음 (크라우딩아웃 보상)

**Given** ETF·ETN이 원본 절대 거래량 순위 상위 fraction을 점유하는 픽스처

**When** 후보 소스가 오버페치되고 `stocks` 교집합이 적용된 뒤 ratio 루프가 도는 상황

**Then**:
- 배제 후 실제 검사되는 **genuine-stock 후보 수가 배제 전(현행)보다 줄지 않는다** — 배제로 확보된 슬롯을
  genuine 종목이 채운다.
- 정제는 top-N 절단 **이후**의 단순 출력 필터가 아니라 후보 소스 단계에서 이뤄진다(밀려난 종목 복구 가능).
- 발신량(신호 수)이 정제로 인해 구조적으로 증가하도록 설계되지 않는다 — 발신은 여전히 `_min_ratio`·앙상블·
  적응형 임계·우선순위 절단이 게이팅한다(입력 확대이지 발신 완화 아님).

---

## AC-074-004 (REQ-004) — `stocks` 조회 실패 시 fail-open

**Given** 후보 정제용 `stocks` 교집합 조회가 예외를 던지는 상태(mock으로 DB/SSL 실패 유도)

**When** Pool B 조립이 실행되면

**Then**:
- `_fetch_tracked_stock_codes`(공유 헬퍼)가 `None`을 반환하고, Pool B는 **미필터로 진행**(현행 거동 보존)한다.
- 세션이 `db.rollback()`으로 복구되어 후속 쿼리에서 `PendingRollbackError`가 발생하지 않는다.
- Pool B가 조회 실패로 **비워지지 않는다**(fail-open, 071 EC-1 일관).

---

## AC-074-005 (REQ-005) — 배제 관측 로깅

**Given** 후보 정제가 하나 이상의 비-`stocks` 코드를 배제하는 상태

**When** Pool B 정제가 실행되면

**Then**:
- 배제된 코드 수(및 예시 일부)가 로그로 남는다(SPEC-AI-071 REQ-004 형식 일관, `[스캔유니버스]` Pool B
  로깅 관례 정합).
- 배제가 0건이면 불필요한 로그를 남기지 않는다(노이즈 억제).

---

## AC-074-006 (범위 경계) — 공유 fetch 수정 시 detect_volume_breakout 거동 불변

**Given** 크라우딩아웃 보상을 위해 `fetch_volume_leaders_sync`(공유 함수)가 수정된 경우(오버페치/limit
확장)

**When** `detect_volume_breakout`(AI-062/063/066)가 그 fetch를 사용하면

**Then**:
- `detect_volume_breakout`의 임계(3.0x)·가중치·bypass·출력 거동 diff 0 — 후보 수 증가만 허용되고,
  그 증가분은 탐지기 자체 임계로 필터된다.
- (limit 상향만으로 크라우딩아웃이 해소되어 fetch 함수를 수정하지 않은 경우 이 AC는 자명 충족.)

---

## 엣지케이스

- **EC-1 정제 후 후보 0**: 교집합·오버페치 후 genuine 후보가 없으면 Pool B는 빈 채로 진행하고 A>C
  우선순위·`max_scan_universe` 절단은 정상 동작(현행에서도 가능한 정상 상태).
- **EC-2 Pool A가 이미 claim한 코드**: Pool A가 선점한 코드는 Pool B에서 스킵된다(현행 `entry_pool_map`
  dedup). 교집합/오버페치가 이 우선순위를 깨지 않는다.
- **EC-3 미추적 실제 기업**: `stocks`에 없는 (ETN이 아닌) 실제 기업 코드도 동일 논리로 자연 배제된다
  (권위 신호=`stocks`). 이는 회귀가 아니라 의도된 일관성.
- **EC-4 ETF·ETN이 비율 2.0+를 우연히 넘는 경우**: 설령 어떤 ETF·ETN이 비율 필터를 통과하더라도
  `stocks` 부재로 후보 단계에서 이미 배제되어 Pool B에 들어오지 않는다(이중 방어).
- **EC-5 오버페치 상한**: limit/페이지 증가는 유계여야 하며, 스캔당 `fetch_stock_price_history_sync`
  호출/지연이 수용 범위임을 확인(비용 폭증 없음).
- **EC-6 병렬 테스트(`-n 4`)**: Pool B/헬퍼 테스트가 pytest-xdist 4워커 환경에서 결정적으로 통과한다
  (공유 상태 오염 주의).

---

## Definition of Done

- [ ] **재현 우선**: genuine 종목이 크라우딩아웃으로 Pool B에 못 드는 현행 상태를 재현하는 실패
      characterization 테스트가 수정 **전** 작성·실패 확인됨(AC-074-001, Rule 4).
- [ ] Pool B 후보가 비율 필터 이전에 `stocks`-교집합으로 비-`stocks`(레버리지/인버스 ETF·ETN + 미추적)를
      배제함(AC-074-001/002, REQ-001).
- [ ] 분류 규칙이 SPEC-AI-071과 **단일 공유 헬퍼**로 통합되고 071 테스트가 전량 통과함(AC-074-002).
- [ ] 배제가 순 genuine 후보를 감소시키지 않고 크라우딩아웃을 완화함(AC-074-003, REQ-002).
- [ ] `109610`(또는 합성 픽스처)이 수정 후 Pool B에 표면화되고 ETF·ETN은 결코 포함되지 않음
      (AC-074-001, REQ-003).
- [ ] `stocks` 조회 실패 시 Pool B가 미필터 fail-open으로 진행함(AC-074-004, REQ-004).
- [ ] 배제 종목 수가 로깅됨(AC-074-005, REQ-005).
- [ ] 공유 fetch 수정 시 `detect_volume_breakout` 거동 diff 0(AC-074-006, 범위 경계).
- [ ] 모든 엣지케이스(EC-1~EC-6) 테스트/확인 커버.
- [ ] 테스트 커버리지 85%+, `ruff check` 무경고, 전체 백엔드 스위트 회귀 없음(`-n 4` 병렬 포함).
- [ ] 탐지기/앙상블/발신 게이팅/매수 로직 diff 0. `_min_ratio`(2.0)·`max_scan_universe`(150) 불변.
      신규 테이블/마이그레이션 없음.
- [ ] 과거 데이터 소급 재계산/백필 없음(Exclusion 7 준수).
