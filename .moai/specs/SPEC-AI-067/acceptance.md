# SPEC-AI-067 인수 기준 (Acceptance Criteria)

Given-When-Then 형식. 별도 명시가 없으면 `intraday_live_volume.enabled=true` 및 장중
(`_is_market_open()`=true) 전제다. "당일 거래량"은 각 호출부의 오늘 원소(combo `volumes[-1]`,
breakout/PoolB `history[0].volume`)를 의미한다.

---

## AC-1 (REQ-001) 실시간 당일 거래량 소스 (공유 메커니즘)

### Scenario 1.1 — 장중 실시간 취득
- **Given** 시장이 개장 중(`_is_market_open()`=true)이고 한 종목의 모바일 API
  `accumulatedTradingVolume`이 정상 반환된다.
- **When** 공유 헬퍼로 당일 거래량을 요청하면
- **Then** 헬퍼는 모바일 실시간 값을 반환하며, sise_day "오늘" 값을 사용하지 않는다.

### Scenario 1.2 — 장외 시 모바일 미호출
- **Given** 시장이 마감 상태(장외, 예: 08:00 장전 또는 15:31 이후)다.
- **When** 공유 헬퍼로 당일 거래량을 요청하면
- **Then** 모바일 API를 호출하지 않고 기존 sise_day "오늘" 값을 반환한다.

### Scenario 1.3 — 당일 원소만 교체, 베이스라인 불변
- **Given** 장중이고 실시간 값이 취득되었다.
- **When** 헬퍼가 값을 반환하면
- **Then** 대체되는 것은 당일(오늘) 거래량 원소 하나뿐이며, 과거 베이스라인 원소는 sise_day
  원본 그대로다.

### Scenario 1.4 — 단일 공유 메커니즘 재사용
- **When** REQ-002/003/004를 구현한 후
- **Then** 장중 게이트·실시간 fetch·fail-open 폴백·값 스플라이스 로직은 세 호출부에서
  각각 재구현되지 않고 단일 공유 메커니즘을 통해 수행된다.

---

## AC-2 (REQ-002) combo 탐지기 당일 거래량 교정

### Scenario 2.1 — z-score 부호 교정 (위메이드형)
- **Given** 장중, 한 종목의 sise_day "오늘" 거래량이 stale 64,418이고 실시간
  `accumulatedTradingVolume`이 258,945이며, 20일 baseline 평균이 182,449다.
- **When** combo 탐지기가 Gate 1 z-score를 계산하면
- **Then** `current_vol`은 실시간 258,945가 사용되어 z-score가 음(-1.63)이 아니라 양(+1.05)
  방향으로 계산된다("거래량 감소 중" 오신호 제거).

### Scenario 2.2 — 게이트 임계·구조 불변
- **When** REQ-002를 구현한 후
- **Then** `volume_zscore_threshold` 및 SPEC-AI-030 Gate 1/2/3의 로직·임계는 변경되지
  않으며, 오직 z-score의 입력값(current_vol)만 신선화된다(회귀).

### Scenario 2.3 — baseline은 sise_day 유지
- **Given** 장중이고 실시간 당일 값이 취득되었다.
- **When** combo가 `mean=statistics.mean(volumes[:-1])`을 계산하면
- **Then** baseline(`volumes[:-1]`)은 sise_day 값으로 유지되고 실시간 값으로 오염되지 않는다.

---

## AC-3 (REQ-003) volume_breakout 당일 거래량 교정

### Scenario 3.1 — 실시간 배율로 breakout 포착
- **Given** 장중, 한 종목의 sise_day today_vol이 과소계상되어 배율이 임계 미만이나 실시간
  `accumulatedTradingVolume` 기준 배율은 임계 이상이다.
- **When** `detect_volume_breakout`이 배율을 계산하면
- **Then** `today_vol`에 실시간 값이 사용되어 배율이 실측 기반으로 계산된다.

### Scenario 3.2 — 소유 경계 불변
- **When** REQ-003을 구현한 후
- **Then** AI-062 가중치, AI-063 `volume_breakout_bypass_threshold(0.30)`,
  `volume_ratio_threshold`, AI-066 상대임계/유니버스 경로는 변경되지 않는다(회귀).

---

## AC-4 (REQ-004) Pool B 당일 거래량 교정

### Scenario 4.1 — 실시간 배율로 Pool B 편입
- **Given** 장중, 거래량 리더 종목의 sise_day today_vol이 과소계상되어 Pool B 배율(2.0x)
  미만이나 실시간 값 기준으로는 2.0x 이상이다.
- **When** `build_scan_universe` Pool B가 배율을 계산하면
- **Then** 실시간 값이 사용되어 해당 종목이 Pool B에 편입된다.

### Scenario 4.2 — Pool 우선순위·상한 불변
- **When** REQ-004를 구현한 후
- **Then** Pool A/B/C 우선순위, `max_scan_universe`, Pool B `_min_ratio=2.0`은 변경되지
  않는다(회귀).

---

## AC-5 (REQ-005) fail-open 폴백 · 예산 상한

### Scenario 5.1 — 모바일 실패 시 sise_day 폴백
- **Given** 장중, 모바일 API가 예외(레이트리밋/네트워크/HTTP 오류/종목 미존재)를 던지거나
  `accumulatedTradingVolume`이 부재/0이다.
- **When** 공유 헬퍼로 당일 거래량을 요청하면
- **Then** 예외를 삼키고 기존 sise_day "오늘" 값을 반환하며, 탐지는 중단 없이 계속된다.

### Scenario 5.2 — 실패 시 레거시 동등
- **Given** 특정 종목의 모바일 조회가 실패한다.
- **When** 해당 종목을 처리하면
- **Then** 그 종목의 판정 결과는 sise_day-only 레거시 동작과 동등하다(무중단·무예외 전파).

### Scenario 5.3 — 스캔당 상한 초과 폴백
- **Given** 한 스캔에서 `max_live_fetches_per_scan`(기본 80) 상한에 도달했다.
- **When** 이후 후보의 당일 거래량을 요청하면
- **Then** 모바일 호출 없이 sise_day "오늘" 값으로 폴백한다(레이트리밋 유계).

### Scenario 5.4 — 실시간 값이 더 작을 때 큰 값 채택
- **Given** 장중, 실시간 값이 일시적 API 상태로 sise_day "오늘" 값보다 작게 반환된다.
- **When** 헬퍼가 값을 결정하면
- **Then** 누적 거래량 단조 비감소 원칙에 따라 둘 중 큰 값을 채택한다.

---

## AC-6 (REQ-006) 과거 베이스라인 무결성 (가정 명시 + 점검)

### Scenario 6.1 — 베이스라인은 모바일 교체 대상 아님
- **When** REQ-002/003/004를 구현한 후
- **Then** 어떤 호출부에서도 과거(non-today) 베이스라인 원소는 모바일로 대체되지 않고
  sise_day에서 온다.

### Scenario 6.2 — 완결일 정확성 가정 spot-check
- **Given** 최근 완결된 한 거래일이 있다.
- **When** 그 완결일의 sise_day 거래량을 알려진 정확 기준(동일 완결일의 모바일 값 또는
  익일 조회 시 동일 날짜의 sise_day 값)과 비교하면
- **Then** 값이 일치함을 확인한다. 불일치 시 REQ-006 가정이 위반됨을 보고하고 후속 조치를
  기록한다(가정을 증명 없이 신뢰하지 않는다).

---

## AC-7 (REQ-007) 설정 및 하위 호환

### Scenario 7.1 — 설정 부재 시 기본값
- **Given** `surge_detection.yaml`에 `intraday_live_volume` 섹션이 없다.
- **When** 설정을 로드하면
- **Then** 문서화된 기본값(`enabled=true`, `market_hours_only=true`,
  `max_live_fetches_per_scan=80`)으로 동작하며 로드 에러가 없다.

### Scenario 7.2 — enabled=false 레거시 동등
- **Given** `intraday_live_volume.enabled=false`다.
- **When** 전체 스캔을 수행하면
- **Then** 세 호출부 모두 sise_day "오늘" 값을 사용하며, sise_day-only 레거시와 동일한
  당일 거래량·신호 집합이 생성된다.

### Scenario 7.3 — 스트리밍 인프라 미도입 (경계)
- **When** REQ-001~008을 구현한 후
- **Then** 실시간 경로는 기존 모바일 폴링 엔드포인트의 필드 추출만 사용하며,
  WebSocket/메시지 큐/상시 리스너 등 신규 스트리밍 인프라를 도입하지 않는다.

---

## AC-8 (REQ-008) `_PriceHistoryCache` 장중 인지형 TTL

### Scenario 8.1 — 장중 짧은 TTL 적용
- **Given** 시장이 개장 중(`_is_market_open()`=true)이다.
- **When** `_PriceHistoryCache`의 만료를 판정하면
- **Then** 형제 캐시와 동일하게 `_cache_ttl()`의 장중 TTL(`PRICE_CACHE_TTL_MARKET_OPEN`)이
  적용되며, 평면 `PRICE_CACHE_TTL=3600`은 더 이상 사용되지 않는다.

### Scenario 8.2 — 장외 긴 TTL 적용
- **Given** 시장이 마감 상태(장외)다.
- **When** `_PriceHistoryCache`의 만료를 판정하면
- **Then** `_cache_ttl()`의 장외 TTL(`PRICE_CACHE_TTL_MARKET_CLOSED`)이 적용된다.

### Scenario 8.3 — 캐시 동작 의미 불변
- **When** REQ-008을 구현한 후
- **Then** eviction·max-size·Redis 복구 등 캐시의 다른 동작 의미는 변경되지 않으며, 변경은
  TTL 값 치환에 한정된다(비동기 `fetch_stock_price_history` 광범위 사용 경로 회귀 없음).

### Scenario 8.4 — 핵심 수정 독립성 (경계, 오해 방지)
- **When** REQ-008만 적용하고 REQ-001~005를 적용하지 않는다면
- **Then** 오늘(위메이드형) 장중 지연 문제는 여전히 재발할 수 있다(신선 fetch에서도
  `sise_day` 페이지가 stale). 즉 REQ-008은 핵심 수정의 전제·대체가 아니며, 재발 방지의
  실질 수정은 REQ-001~005다.

---

## Edge Cases

- **모바일 응답 리스트 비어 있음**: `entries`가 빈 리스트/비-리스트 → fail-open으로 sise_day 폴백.
- **장중 경계 시각(15:20 스캔)**: 15:30 이전이므로 `_is_market_open()`=true → 실시간 적용.
  08:00 스캔은 장외 → sise_day(전일 완결) 사용.
- **combo `volumes` 길이 < 5**: 기존 스킵 로직(surge_detector.py:904) 불변 — 실시간 교체는
  스킵 판정 이후 today 원소에만 관여.
- **실시간 값 0 반환**: 유효 값 아님으로 간주 → fail-open 폴백(sise_day today).
- **동일 스캔 내 같은 종목 중복 요청**: 중복 HTTP는 선택적 스캔-스코프 메모이즈로 흡수
  가능(Run 단계 결정, 정확성에는 영향 없음).
- **주말/공휴일 실행**: `_is_market_open()`=false → 전부 sise_day.

---

## Quality Gate 기준

- 신규 테스트 파일 `backend/tests/test_surge_ai067.py`가 AC-1~AC-8 및 Edge Cases를 커버.
- 기존 surge 테스트 스위트(SPEC-AI-030/062/063/065/066 관련 포함) 전량 통과(회귀 없음).
- `intraday_live_volume.enabled=false` 경로가 sise_day-only 레거시와 동등함을 명시 테스트로 고정.
- 모바일 API는 테스트에서 mock/주입(실네트워크 금지) — combo `_volume_provider`와 유사한
  주입 지점 또는 monkeypatch로 결정 로직만 검증.
- 백엔드 검증: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과,
  `uv run ruff check .` 및 `uv run mypy app/` 통과.

---

## Definition of Done

- [ ] REQ-AI067-001~008 전체 구현 완료.
- [ ] AC-1~AC-8 및 Edge Cases 테스트 통과.
- [ ] 세 호출부(combo `volumes[-1]`, breakout `history[0]`, Pool B `history[0]`)가 단일
      공유 메커니즘으로 장중 실시간 당일 거래량을 취득 확인(D1: 3개 전부 기본 활성).
- [ ] fail-open 폴백(모바일 실패/장외/상한 80 초과)이 sise_day-only와 동등함을 명시 테스트로 확인.
- [ ] 과거 베이스라인이 모바일 교체 대상이 아님 확인, 완결일 정확성 가정 spot-check 수행
      (D4: 경량 점검, 별도 검증 잡 없음).
- [ ] REQ-008: `_PriceHistoryCache`가 `_cache_ttl()`로 전환됨(장중/장외 TTL) 확인, 캐시 다른
      동작 의미 불변. REQ-008 단독으로는 지연 재발 방지 불가(핵심은 REQ-001~005)임을 문서·
      테스트 주석에 명시.
- [ ] SPEC-AI-030 게이트 임계/구조, AI-062/063 가중치·bypass, AI-065 Pool 우선순위, AI-066
      게이트/확신도 로직 불변 확인(회귀).
- [ ] `intraday_live_volume.enabled=false` 폴백이 레거시 동등.
- [ ] 위메이드형 합성 시나리오에서 combo z-score 부호가 음→양으로 교정됨 확인.
- [ ] TRUST 5 품질 게이트 통과, 신규/변경 코드에 @MX 태그(NOTE/WARN/ANCHOR as appropriate) 부착.
- [ ] 매수 로직·포지션 사이징·정기 스캔 스케줄 무변경(예측 기록 모드 유지, SPEC-AI-043).
- [ ] 열린 결정 D1~D4(plan.md)가 구현 착수 전 사용자 확정으로 해소.
