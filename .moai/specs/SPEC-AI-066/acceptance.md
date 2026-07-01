# SPEC-AI-066 인수 기준 (Acceptance Criteria)

Given-When-Then 형식. 모든 시나리오는 `catalyst_conviction.enabled=true` 전제이며, 명시된
경우에만 스위치를 off로 둔다. 등락률은 `change_rate`(전일 종가 대비)다.

---

## AC-1 (REQ-001) 확신도 tier 산출

### Scenario 1.1 — 확정 강한 촉매 → HIGH
- **Given** 한 종목이 news window 내 15건의 다출처 기사로 커버되고, 첫~마지막 기사 시간 span이
  16시간이며, 감성 강도가 min_sentiment_high 이상이고, 인수/합병/경영권 키워드가 포함되어 있다.
- **When** 확신도를 산출하면
- **Then** 해당 종목의 확신도는 HIGH로 분류된다.

### Scenario 1.2 — 얇은 단발 뉴스 → non-HIGH
- **Given** 한 종목이 news window 내 1건의 기사로만 커버되고 공시 뒷받침이 없다.
- **When** 확신도를 산출하면
- **Then** 확신도는 HIGH 미만(기본 tier)으로 분류된다.

### Scenario 1.3 — 촉매 근거 전무 → 최저 tier
- **Given** 한 종목이 news window 내 뉴스가 없고 backing 공시도 없다.
- **When** 확신도를 산출하면
- **Then** 확신도는 최저 tier이며, 결코 HIGH가 되지 않는다.

### Scenario 1.4 — 데이터 재사용(신규 쿼리 없음)
- **Given** combo 탐지기가 이미 NewsStockRelation 조인으로 뉴스 행을 조회했다.
- **When** 확신도의 기사 수/지속시간/감성을 산출하면
- **Then** 종목당 추가 DB 쿼리 없이 기존 행 집합의 인메모리 집계로 산출된다.

---

## AC-2 (REQ-002) combo 과열 게이트 확신도 차등 완화

### Scenario 2.1 — HIGH 확신도 + 과열 초과 → 통과
- **Given** 확신도 HIGH인 combo 후보의 change_rate가 +12%(기본 상한 5% 초과, 고확신 상한 15% 미만)이고,
  freshness>=1.5, change_rate>=0(분산 아님)이다.
- **When** 과열 게이트를 적용하면
- **Then** 후보는 과열 게이트를 통과한다(추격매수가 아니라 초기 확정 촉매).

### Scenario 2.2 — non-HIGH + 과열 → 기존대로 제외
- **Given** 확신도 non-HIGH인 combo 후보의 change_rate가 +7%(기본 상한 5% 초과)다.
- **When** 과열 게이트를 적용하면
- **Then** 후보는 기존 SPEC-AI-030대로 제외된다(기본 5% 상한 유지).

### Scenario 2.3 — HIGH 확신도이나 분산 중 → 여전히 제외 (안전 불변식)
- **Given** 확신도 HIGH인 후보의 change_rate가 -2%(분산, Gate3 위반)이다.
- **When** 게이트를 적용하면
- **Then** 확신도와 무관하게 분산 게이트로 제외된다(하락 물량 매수 금지).

### Scenario 2.4 — HIGH 확신도이나 stale 급증 → 여전히 제외 (안전 불변식)
- **Given** 확신도 HIGH인 후보의 오늘/어제 거래량비가 0.6(freshness<1.5)이다.
- **When** 게이트를 적용하면
- **Then** 확신도와 무관하게 신선도 게이트로 제외된다.

### Scenario 2.5 — 스위치 off → SPEC-AI-030 복원
- **Given** `catalyst_conviction.enabled=false`이고 HIGH 확신도 후보의 change_rate가 +12%다.
- **When** 과열 게이트를 적용하면
- **Then** 기본 상한 5%가 적용되어 후보는 제외된다(레거시 동작).

---

## AC-3 (REQ-003) 전략적 인수 공시 페널티 예외

### Scenario 3.1 — 호재성 인수 최대주주변경 → 페널티 부분 완화(0.7)
- **Given** "최대주주변경"을 포함한 공시가 (인수/합병/경영권 키워드) AND (positive+ 감성) AND
  (change_rate>=0)를 동반한다.
- **When** disclosure 페널티 적용 단계를 지나면
- **Then** penalty_factor가 `acquisition_penalty_factor`(기본 0.7)로 **부분 완화**된다
  (완전 면제 1.0 아님, 기존 0.3보다는 높음). 즉 disclosure 점수 = base × 0.7.

### Scenario 3.2 — 부실 매각형 최대주주변경 → 페널티 유지(0.3)
- **Given** "최대주주변경"을 포함한 공시가 인수 키워드 없이(또는 negative 감성/하락 등락)
  나타난다.
- **When** 페널티 적용 단계를 지나면
- **Then** SPEC-AI-028 penalty_factor(0.3)가 그대로 적용된다(완화 없음).

### Scenario 3.3 — 스위치 off → 전면 페널티
- **Given** `acquisition_exemption_enabled=false` 또는 `catalyst_conviction.enabled=false`이다.
- **When** 호재성 인수 최대주주변경 공시를 처리하면
- **Then** 예외 없이 SPEC-AI-028 페널티가 적용된다(레거시).

---

## AC-4 (REQ-004) co-mention 테마 자동 확장 *(기능 활성 시)*

### Scenario 4.1 — 비계열 동조 클러스터 식별
- **Given** `comention_theme_enabled=true`이고 여러 비계열 종목이 동일 기사들에서
  `comention_min_pairs` 이상 반복 동반 등장한다.
- **When** 테마 탐지를 수행하면
- **Then** 해당 종목들이 임시 클러스터로 묶여 테마/확신도 근거로 기여한다.

### Scenario 4.2 — 계열사 클러스터 중복 배제
- **Given** 파생 클러스터가 동일 사업그룹 계열사로만 구성된다.
- **When** 클러스터를 처리하면
- **Then** group_cascade(AI-027/035) 소관으로 간주되어 본 경로에서 이중 카운트되지 않는다.

### Scenario 4.3 — 비활성 폴백
- **Given** `comention_theme_enabled=false`이다.
- **When** 테마 탐지를 수행하면
- **Then** 키워드→섹터 맵 매칭만 수행된다(레거시).

---

## AC-5 (REQ-005) volume_breakout 유니버스 확장 + 상대 임계 *(기능 활성 시)*

### Scenario 5.1 — 촉매 중대형주 유니버스 포함
- **Given** 당일 공시/뉴스 커버리지를 가진 종목이 거래량 순위 상위 50 밖에 있다.
- **When** volume_breakout 유니버스를 구성하면
- **Then** 해당 종목이 후보 유니버스에 포함되어 평가된다.

### Scenario 5.2 — 상대 임계로 중대형주 포착
- **Given** `relative_threshold_enabled=true`이고 한 중대형주의 절대 거래량비가 2.5x(고정 3.0 미만)이나
  자체 롤링 베이스라인 대비 이상치(z-score 높음)다.
- **When** breakout 판정을 하면
- **Then** 상대 임계로 breakout 후보에 포함된다.

### Scenario 5.3 — cold start 폴백
- **Given** 종목의 베이스라인 표본이 부족하다.
- **When** breakout 판정을 하면
- **Then** 고정 3.0x 배율로 폴백한다(회귀 없음).

### Scenario 5.4 — 소유 경계 불변
- **When** REQ-005를 구현한 후
- **Then** AI-062 volume_breakout 가중치와 AI-063 `volume_breakout_bypass_threshold(0.30)`는
  변경되지 않는다(회귀 테스트로 확인).

---

## AC-7 (REQ-007) 고임팩트 뉴스 이벤트 구동 재스캔 *(기능 활성 시)*

### Scenario 7.1 — HIGH 촉매 기사 저장 → 즉시 트리거
- **Given** `event_rescan_enabled=true`이고, 뉴스 크롤(`_run_crawl_job`)이 인수/합병/경영권
  키워드 + 요구 감성을 만족하는 신규 기사를 종목에 대해 저장했다.
- **When** `_run_keyword_matching()` 완료 직후 훅이 실행되면
- **Then** 다음 정기 스캔을 기다리지 않고 `run_surge_signal_generation`이 비동기 1회 트리거된다.

### Scenario 7.2 — 종목당 쿨다운 내 재트리거 차단
- **Given** 한 종목이 최근 `event_rescan_cooldown_minutes`(30분) 내에 이미 이벤트 트리거되었다.
- **When** 동일 종목의 새 HIGH 기사가 저장되면
- **Then** 재트리거는 스킵되고 정기 스캔에 위임된다.

### Scenario 7.3 — 일일 상한 초과 시 스킵
- **Given** 당일 이벤트 트리거 횟수가 `max_daily_event_triggers`(20회)에 도달했다.
- **When** 새 HIGH 기사가 저장되면
- **Then** 이벤트 트리거는 스킵된다(LLM 예산 보호).

### Scenario 7.4 — 정기 스캔 불변
- **When** REQ-007을 구현한 후
- **Then** 정기 스캔 잡(`_run_surge_signal_generate` 15:20/intraday 및 08:00/09:05/10:00
  경로)은 제거·대체·재조정되지 않는다.

### Scenario 7.5 — 비활성 폴백
- **Given** `event_rescan_enabled=false`이다.
- **When** HIGH 기사가 저장되면
- **Then** 이벤트 트리거가 발생하지 않고 정기 스캔만 동작한다(레거시).

### Scenario 7.6 — 스트리밍 인프라 미도입 (경계)
- **When** REQ-007을 구현한 후
- **Then** 이벤트 경로는 뉴스 크롤러 저장 완료 훅만 사용하며, WebSocket/메시지 큐/상시
  리스너 등 신규 스트리밍 인프라를 도입하지 않는다.

## AC-6 (REQ-006) 설정 및 하위 호환

### Scenario 6.1 — 설정 부재 시 기본값
- **Given** `surge_detection.yaml`에 `catalyst_conviction` 섹션이 없다.
- **When** 설정을 로드하면
- **Then** 문서화된 기본값으로 동작하며 로드 에러가 없다.

### Scenario 6.2 — 전체 비활성 = 레거시 동등
- **Given** `catalyst_conviction.enabled=false`이다.
- **When** 전체 스캔을 수행하면
- **Then** SPEC-AI-030/AI-028과 동일한 신호 집합이 생성된다(완화 전면 비활성).

---

## Edge Cases

- **가격 조회 None**: SPEC-AI-030 `exclude_on_price_unavailable`(현재 false) 정책을 그대로
  따른다. 확신도 완화는 change_rate가 있을 때만 상한 판정에 관여.
- **커버리지 시간 span 0(단발 기사)**: 지속시간 요건 미충족 → HIGH 불가.
- **뉴스는 강하나 공시 없음(위메이드형)**: 뉴스 근거만으로 HIGH 승격 가능해야 한다(Option B의
  공시 한정 함정 회피). 이 케이스가 본 SPEC의 핵심 목표.
- **인수 키워드 있으나 감성 negative**: REQ-003 3중 조건 미충족 → 페널티 유지.
- **co-mention 클러스터가 1종목**: 쌍(pair) 부재 → 클러스터 미형성.
- **relative_threshold와 flat ratio 동시 충족**: 중복 후보 생성 금지(dedup).

---

## Quality Gate 기준

- 신규 테스트 파일 `backend/tests/test_surge_ai066.py`가 AC-1~AC-7과 Edge Cases를 커버.
- 기존 surge 테스트 스위트(SPEC-AI-030/028/062/063/065 관련 포함) 전량 통과(회귀 없음).
- `catalyst_conviction.enabled=false` 경로가 레거시와 동등함을 명시 테스트로 고정.
- 백엔드 검증: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과,
  `uv run ruff check .` 및 `uv run mypy app/` 통과.

---

## Definition of Done

- [ ] REQ-AI066-001~007 전체를 SPEC-AI-066 하나로 구현 완료(분리 없음, 사용자 확정 2026-07-01).
- [ ] AC-1~AC-7 및 Edge Cases 테스트 통과.
- [ ] REQ-003은 **부분 완화(0.3→0.7)** 로 구현(완전 면제 아님) 확인.
- [ ] SPEC-AI-030 Gate2/3/4, SPEC-AI-028 페널티(비예외 케이스 0.3 유지), AI-062/063
      가중치·bypass 불변 확인(회귀).
- [ ] REQ-007 이벤트 재스캔이 정기 스캔(08:00/09:05/10:00/15:20)을 제거·대체하지 않고
      추가 보강만 함을 확인; 쿨다운·일일 상한 동작 확인.
- [ ] `catalyst_conviction.enabled=false` 및 `event_rescan_enabled=false` 폴백이 레거시 동등.
- [ ] 위메이드형 합성 시나리오에서 최소 1개 경로가 신호를 생성.
- [ ] TRUST 5 품질 게이트 통과, 신규/변경 코드에 @MX 태그(NOTE/WARN/ANCHOR as appropriate) 부착.
- [ ] 매수 로직·포지션 사이징 무변경, 정기 스캔 스케줄 무변경(예측 기록 모드 유지, SPEC-AI-043).
