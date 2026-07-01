# SPEC-AI-067 구현 계획 (Implementation Plan)

## 기술 접근 개요

본 SPEC은 3개 탐지기가 "당일 거래량"으로 사용하는 값을 장중에 한해 Naver 모바일 API
`accumulatedTradingVolume`(실시간 정확)로 교체한다. 신규 탐지기·매매 엔진·스트리밍 인프라를
만들지 않고, **이미 사용 중인 모바일 필드**를 동기 경로에서 추출·주입하는 경량 데이터 계층
변경이다. 판별 로직(SPEC-AI-030/062/063/065/066)은 일절 손대지 않는다.

핵심 불변식(모든 마일스톤에서 유지):
- 게이트·임계·가중치·bypass·확신도·앙상블은 무변경. 오직 "당일 거래량" 입력값만 신선화.
- 과거 베이스라인 원소는 계속 `sise_day`(모바일은 과거일 미제공).
- 장외에는 모바일 호출 없음(완결된 sise_day 당일 값이 이미 정확).
- `intraday_live_volume.enabled=false`이면 전 호출부가 sise_day 당일 값으로 복원(레거시 동등).

---

## 마일스톤 (우선순위 기반, 시간 추정 없음)

### Milestone 1 (P0) — 공유 실시간 거래량 메커니즘 + config 골격 (REQ-001, REQ-007)

- `IntradayLiveVolumeConfig` Pydantic 모델 및 `surge_detection.yaml` 섹션 추가.
- naver_finance.py에 모바일 `accumulatedTradingVolume` 동기 취득 경로 마련
  (설계 결정 1 참조: 신규 전용 헬퍼 vs 기존 함수 반환 확장).
- surge_detector.py에 **공유 스플라이스/결정 헬퍼** 신규: 입력(stock_code + sise_day 당일값)
  → 장중 게이트(`_is_market_open()`) 통과 시 모바일 조회, fail-open 폴백, 예산 상한 적용,
  당일-원소 대체값 반환. 순수 결정 로직은 단위 테스트로 고정.

### Milestone 2 (P0) — combo 탐지기 당일 거래량 교정 (REQ-002)

- `detect_volume_surge_news_combo`의 `current_vol = volumes[-1]`(surge_detector.py:911)을
  공유 헬퍼 반환값으로 대체. `mean=statistics.mean(volumes[:-1])` baseline은 불변.
- 테스트: 위메이드형(stale 64,418 → 실시간 258,945) 시 z-score 부호가 음→양으로 교정됨을
  고정. `volume_zscore_threshold` 및 Gate 구조 불변 회귀.

### Milestone 3 (P0) — volume_breakout 당일 거래량 교정 (REQ-003)

- `detect_volume_breakout`의 `today_vol = history[0].volume`(:3677)을 공유 헬퍼 반환값으로
  대체. `baseline_vols = history[1:baseline_days+1]` 불변.
- AI-062 가중치·AI-063 bypass·AI-066 상대임계/유니버스 경로 불변 회귀.

### Milestone 4 (P0) — Pool B 당일 거래량 교정 (REQ-004)

- `build_scan_universe` Pool B의 `today_vol = history[0].volume`(:3928)을 공유 헬퍼로 대체.
- Pool A/B/C 우선순위·`max_scan_universe`·`_min_ratio=2.0` 불변 회귀.

### Milestone 5 (P0) — fail-open · 장외 폴백 · 예산 상한 (REQ-005, REQ-001, REQ-007)

- 모바일 실패 시 sise_day 당일 값 폴백(예외 삼킴, 탐지 지속). 장외 시 모바일 미호출.
- 스캔당 `max_live_fetches_per_scan` 상한 도달 시 이후 후보는 sise_day 폴백.
- 실시간 값이 sise_day보다 작으면 큰 값 채택(누적 거래량 단조 비감소, REQ-005).
- 테스트: 모바일 예외 → sise_day 동등, 장외 → 모바일 미호출, 상한 초과 → 폴백.

### Milestone 6 (P1) — 베이스라인 무결성 점검 (REQ-006)

- 과거 베이스라인 원소가 모바일 교체 대상이 아님을 명시 테스트로 고정.
- 완결일 sise_day 값 정확성 가정에 대한 spot-check 절차(acceptance AC-6) 문서화·경량 검증
  (D4 확정: 경량 점검만, 별도 검증 파이프라인/잡 미구축).

### Milestone 6.5 (P2) — `_PriceHistoryCache` 장중 인지형 TTL (REQ-008)

- `PRICE_CACHE_TTL=3600`(naver_finance.py:375) 사용처(:669, :731, :788)를 `_cache_ttl()`
  (:48~49)로 전환. 캐시 무효화/eviction/max-size/Redis 복구 의미는 불변(최소 변경).
- **핵심 수정과 독립**: REQ-008만으로는 오늘 위메이드 지연 재발이 방지되지 않음을 문서·
  테스트 주석에 명시(핵심은 REQ-001~005). blast radius(비동기 `fetch_stock_price_history`
  광범위 사용) 최소화 — TTL 값 치환만.
- 테스트: 장중 시 짧은 TTL 적용, 장외 시 긴 TTL 적용을 `_is_market_open()` 모킹으로 검증.

### Milestone 7 — 통합 검증

- `enabled=false` 전체 폴백이 sise_day-only 레거시와 바이트 동등인지 검증.
- 위메이드형 합성 시나리오에서 combo z-score 부호 교정 + breakout/PoolB 편입 개선 확인.
- 회귀: 기존 surge 테스트 스위트 통과.

---

## 설계 결정 1 (핵심) — 공유 헬퍼 vs 3개 독립 패치

task 요청에 따라 "당일 거래량 모바일 조회+스플라이스"를 3회 중복할지, 공유 메커니즘으로
묶을지 결정한다.

### 결정: **공유 메커니즘 (권장)**

두 조각으로 구성한다:
1. **naver_finance 동기 fetch** — 모바일 `accumulatedTradingVolume`를 반환하는 단일 함수.
2. **surge_detector 공유 스플라이스/결정 헬퍼** — 입력(stock_code, sise_day 당일값) →
   장중 게이트 + (1) 호출 + fail-open + 예산 상한 + max(live, sise_day) → 당일-원소 대체값.

세 호출부(combo `volumes[-1]`, breakout `history[0]`, Pool B `history[0]`)는 이 헬퍼를
호출만 한다.

**근거:**
- 장중 게이팅·fail-open·예산 상한·max 선택 로직이 **비자명(non-trivial)** 하며, 3회 복제
  시 드리프트 위험(한 곳만 폴백을 빠뜨리면 그 경로에서 탐지 중단 가능)이 크다.
- 단일 지점에서 튜닝(상한·게이트)·롤백·테스트 가능. staged-rollout의 "비활성 시 레거시
  동등" 보장을 한 곳에서 검증(SPEC-AI-066 편차 2에서 학습한 교훈: 부분 게이팅은 미묘한
  레거시 불일치를 만든다).
- 세 호출부의 형태 차이(combo는 `list[float]`의 마지막 원소, breakout/PoolB는
  `list[PriceRecord]`의 0번 원소)는 헬퍼가 "당일 정수 거래량"만 반환하고 각 호출부가
  자기 자료구조에 주입하면 흡수된다.

### 반대안: 3개 독립 패치 (기각)

- 장점: 각 호출부에 국소적, 헬퍼 추상화 없음.
- 단점: fail-open try/except + 장중 게이트 + 예산 상한을 3중 복제 → 유지보수·회귀 위험.
  Enforce-Simplicity 관점에서도 중복이 오히려 복잡. 기각.

---

## 설계 결정 2 — naver_finance 동기 취득: 신규 헬퍼 vs 기존 함수 확장

`fetch_current_price_with_change_sync`(:847~880)는 이미 동일 모바일 엔드포인트를 호출하며
`closePrice`/`fluctuationsRatio`만 추출한다. 거래량을 얻는 방법 2가지:

### 옵션 A — 신규 전용 동기 헬퍼 `fetch_live_today_volume_sync(code) -> int | None` (권장)

- 단일 책임(당일 누적 거래량만 반환). 기존 함수의 반환 계약 불변 → 회귀 위험 0.
- 단점: 동일 엔드포인트를 combo/breakout/PoolB에서 각각 호출 시, 현재가 조회 경로와
  중복 HTTP 가능(단, combo/breakout/PoolB는 현재가를 이 시점에 조회하지 않으므로 실제
  중복은 제한적).

### 옵션 B — `fetch_current_price_with_change_sync` 반환에 `volume` 추가

- 한 번의 호출로 price+change+volume 취득(엔드포인트 응답에 이미 포함).
- 단점: 이 함수는 `@MX:ANCHOR`(다수 호출처: fund_manager, disclosure_impact_scorer 등)
  로 표시된 고 fan-in 함수다. 반환 dict에 키 추가는 하위 호환이나, ANCHOR 계약 변경은
  신중해야 하며 본 SPEC 범위를 넘어 파급.

### 잠정 권장: **옵션 A** (Run 단계에서 실제 호출 중복 여부 측정 후 확정)

ANCHOR 함수를 건드리지 않아 blast radius가 최소. 만약 Run 단계에서 동일 스캔 내 현재가
조회와의 중복이 실측상 유의하면, 공유 헬퍼 내부에서 짧은 인메모리 메모이즈(스캔 스코프)로
흡수한다. **이 확정은 Run 단계 결정 사항**(블로킹 아님).

---

## 설계 결정 3 — 롤아웃 posture (active-by-default vs staged)

이것이 사용자 입력이 필요한 핵심 열린 결정이다. HTTP 비용 프로파일이 호출부마다 다르다:

| 호출부 | 스캔당 대략 후보 수 | 추가 HTTP(장중) | 교정 가치 |
|---|---|---|---|
| combo (`positive_news_stocks`) | 뉴스 커버 종목(수~수십) | 소~중 | **최고** (z-score 부호 오류 교정) |
| detect_volume_breakout (universe) | 최대 ~100 | 중~고 | 중 (배율 과소 교정) |
| build_scan_universe Pool B (leaders=100) | 최대 100 | 중~고 | 중 (편입 실패 교정) |

- **위험**: breakout+PoolB가 각 ~100 → 장중 스캔당 최대 ~200 추가 모바일 호출. 본 코드베이스는
  이미 Naver News API 401(레이트리밋/키) 이슈가 있어 모바일 API 레이트리밋 노출이 실질 우려.
- **방어**: (a) 장중 게이팅으로 장외 비용 0, (b) `max_live_fetches_per_scan` 상한으로 스캔당
  호출 유계, (c) fail-open으로 레이트리밋 발생 시 자동 sise_day 폴백(무중단).

### 확정: **전체 활성화 + 상한** (2026-07-01 사용자 승인)

- **마스터 `enabled=true`** + **`max_live_fetches_per_scan=80`(D2 확정)** 상한으로 3개
  호출부(combo/breakout/PoolB) **전부 기본 활성화**. combo는 후보가 적어 사실상 항상 실시간,
  breakout/PoolB는 상한 내에서 우선 소비 후 초과분 `sise_day` 폴백.
- **staged 단계적 옵션(combo만 활성 + breakout/PoolB 서브플래그 off)은 채택하지 않는다.**
  fail-open + 장중 게이팅 + 스캔당 상한(80) 3중 방어로 레이트리밋 노출이 유계이므로,
  분리 플래그의 추가 복잡성 없이 전체 활성화가 recall 개선을 최대화한다.
- 회귀 안전망: `enabled=false`이면 즉시 레거시(`sise_day`-only)로 복원.

---

## 설계 결정 4 — 부차 발견(`_PriceHistoryCache` 평면 TTL) 처리

- `_PriceHistoryCache`만 `PRICE_CACHE_TTL=3600`(평면)을 쓰고, 형제 캐시는 `_cache_ttl()`
  (장중 10초/장외 300초)을 쓴다. 오늘 실측 불일치의 원인은 **아님**(신선 fetch에서도 지연).
- **확정: 본 SPEC 범위로 포함 (REQ-AI067-008, D3 사용자 승인 2026-07-01).** 형제 캐시와의
  일관성 회복을 위한 부수적 견고성 개선으로 처리한다.
- **[HARD] 오해 방지 명시**: REQ-008만으로는 오늘 같은 지연 문제가 재발하지 않는다는 보장이
  안 된다(신선 fetch에서도 `sise_day` 페이지 자체가 stale). 핵심 수정은 여전히 REQ-001~005
  (실시간 모바일 소스 전환). REQ-008은 REQ-001~005의 전제도 대체도 아니다.
- **blast radius 통제**: 이 캐시는 비동기 `fetch_stock_price_history`(광범위 사용)와 공유
  되므로, 변경은 **TTL 값 치환에 한정**하고 무효화/eviction/max-size/Redis 복구 의미는
  건드리지 않는다(Milestone 6.5).

---

## 기술 리스크 및 완화

| 리스크 | 완화 |
|---|---|
| 모바일 API 레이트리밋(스캔당 ~200 호출) | 장중 게이팅 + `max_live_fetches_per_scan` 상한 + fail-open 폴백. `enabled=false` 즉시 롤백. |
| 공유 헬퍼가 한 경로에서 폴백 누락 → 탐지 중단 | fail-open을 헬퍼 단일 지점에 집중(3중 복제 금지). enabled=false 레거시 동등 명시 테스트. |
| 실시간 값과 sise_day baseline의 단위/스케일 불일치 | 둘 다 "주식 수(shares)" 정수. 당일 원소만 교체, baseline 불변으로 z-score 일관성 유지. |
| 완결 과거일 sise_day 정확성 가정 오류 | REQ-006 spot-check로 검증 후 신뢰. baseline은 본 SPEC이 변경 안 함(회귀 없음). |
| ANCHOR 함수(`fetch_current_price_with_change_sync`) 계약 변경 파급 | 설계 결정 2 옵션 A(신규 전용 헬퍼)로 ANCHOR 불변. |
| 동일 스캔 내 현재가 조회와 HTTP 중복 | Run 단계 실측 후 필요 시 스캔-스코프 메모이즈로 흡수(블로킹 아님). |
| REQ-008 TTL 전환이 비동기 `fetch_stock_price_history`(광범위 사용) 회귀 유발 | 변경을 TTL 값 치환에 한정, 무효화/eviction/max-size/Redis 복구 의미 불변. 장중/장외 TTL 적용을 명시 테스트로 고정. |

---

## 결정 사항 (사용자 확정 2026-07-01)

1. **D1 (롤아웃 범위)** → **전체 활성화 + 상한 확정.** 마스터 `enabled=true` + 스캔당 상한으로
   combo/breakout/PoolB 3개 전부 기본 활성. staged 단계적 서브플래그는 미채택.
2. **D2 (`max_live_fetches_per_scan` 기본값)** → **80 확정.** REQ-007 config 및 yaml에
   기본값 80으로 명시.
3. **D3 (평면 `PRICE_CACHE_TTL` 교정 범위)** → **본 SPEC 범위로 포함 확정.** 신규
   REQ-AI067-008 추가. 단, 핵심 수정(REQ-001~005)의 전제·대체가 아닌 부수적 견고성 개선임을
   spec.md/plan.md에 명시. 관련 Non-Goal 제거.
4. **D4 (베이스라인 spot-check 강도)** → **경량 점검 + 가정 명시 확정.** acceptance AC-6
   경량 점검만 채택, 별도 검증 잡/파이프라인은 구축하지 않음.

## 잔여 튜닝 항목 (구현 시 확정, 블로킹 아님)

- 설계 결정 2(신규 헬퍼 vs 반환 확장) 최종안 — Run 단계 중복 HTTP 실측 후.
- 스캔-스코프 메모이즈 필요 여부 — Run 단계 실측 후.
