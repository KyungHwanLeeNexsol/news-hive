# SPEC-AI-074 Research — Pool B 거래량 순위 후보 ETF·ETN 오염

조사 완료일: 2026-07-08. 본 문서는 프로덕션 read-only 라이브 API 조사로 확정된 진단과, 그 진단을
2026-07-08 기준 코드에 대조 검증한 결과를 구조화한 것이다. 라인 번호는 2026-07-08 재확인 값이다.

---

## 1. 문제 요약

급등 예측의 스캔 유니버스 Pool B(거래량 200%+ 당일 종목)가 **레버리지/인버스 ETF·ETN 오염**으로 실제
중·소형주 거래량 급증을 후보에서 밀어내(crowd out) 급등을 놓친다.

- Pool B는 `build_scan_universe`(`surge_detector.py:4113`)에서 `fetch_volume_leaders_sync(limit=100)`
  (`:4179`)로 Naver **절대 거래량 순위** 상위 종목을 후보로 받아, 종목별 20일 평균 대비
  `_min_ratio=2.0`(200%+) 배율을 넘는 종목만 Pool B에 넣는다(`:4183-4208`).
- 절대 거래량 순위 상위는 레버리지/인버스 ETF·ETN이 구조적으로 점유한다. 이들은 설계상 거래소에서 가장
  많이 거래되는 상품이라 baseline 거래량 자체가 거대해 200%+ 스파이크가 거의 나지 않는다(관측 비율
  0.27x~0.53x). 즉 이들은 `_min_ratio=2.0` 필터에서 **어차피 탈락**한다.
- 문제는 탈락이 아니라 **점유**다. `limit`으로 잘린 상위 후보 슬롯을 ETF·ETN이 차지하면, 실제 200%+
  비율 급증이 난 중·소형주가 **애초에 후보 집합에 들어오지 못한다**(중·소형주는 200%+ 상대 급증에도
  절대 거래량이 지수 파생상품에 못 미쳐 절대 순위 top-N에 진입 못 함).

### 라이브 증거 (2026-07-08 read-only)

- `fetch_volume_leaders_sync(limit=20)` 반환 상위가 대부분 레버리지/인버스: `252670`(KODEX 200선물
  인버스2X), `114800`(KODEX 인버스), `252710`(TIGER 200선물인버스2X), `233740`(KODEX 코스닥150
  레버리지), `069500`(KODEX 200) 등. 이들의 20일 평균 대비 당일 비율은 0.27x~0.53x(모두 2.0x 미달).

### 실증 (실제 미탐지)

- 2026-07-07 `109610`(에스와이): change_rate +29.95%, 거래량 비율 **6.86x**(임계 2.0x 크게 초과)였으나
  급등 예측 미탐지. 중·소형주 절대 거래량이 ETF·ETN 절대 거래량과 경쟁하지 못해 Naver 절대 거래량
  top-100에 진입하지 못한 것과 일치한다.

---

## 2. 코드 위치 / 인과 사슬

- **후보 fetch**: `fetch_volume_leaders_sync(limit: int = 50)` — `naver_finance.py:840`.
  `finance.naver.com/sise/sise_quant.naver?sosok={0,1}`(0=KOSPI/1=KOSDAQ)를 각 1회 스크레이프,
  `a.tltle[href*='code=']`에서 6자리 코드를 최대 `limit`개까지 추출해 중복 없이 합산. **`db` 세션 없음**
  (순수 스크레이퍼). sosok별 **단일 페이지**만 조회하므로 페이지당 행 수(≈50)가 사실상의 상한이다.
- **Pool B 조립**: `surge_detector.py:4174-4212`.
  - `:4179` `volume_leader_codes = fetch_volume_leaders_sync(limit=100)` — **하드코딩 100**
    (`SurgeDetectionConfig.max_candidates=100`을 쓰지 않고 별도 하드코딩; `max_scan_universe`와도 무관).
  - `:4181` `_min_ratio = 2.0` — Pool B 블록 내 하드코딩.
  - `:4183-4208` 각 코드에 대해 `entry_pool_map` 중복 스킵 → `fetch_stock_price_history_sync(code, pages=3)`
    → `today_vol = _resolve_today_volume(...)`(SPEC-AI-067 REQ-004) → 20일 baseline 평균 → `ratio`
    계산 → `ratio >= _min_ratio`면 `pool_b_codes`에 추가.
  - **핵심**: 후보 집합 = `fetch_volume_leaders_sync`가 돌려준 코드에 국한. `stocks` 교집합·상품 유형
    필터 **없음**. 오염은 이 후보 집합 단계에서 발생.

### 왜 "출력 필터"로는 부족한가

`_min_ratio=2.0`은 이미 ETF·ETN을 **출력에서** 배제한다(비율 미달). 그러나 그것은 후보로 들어온 뒤의
탈락일 뿐, ETF·ETN이 차지한 **후보 슬롯**은 반환되지 않는다. 따라서 문제 해결은 **후보 집합(검사 대상
top-N)**을 바꿔야 하며, 단순 출력 필터 추가로는 `109610`류를 구제할 수 없다.

---

## 3. 분류 방법 결정 — `stocks` 교집합 (코드대역 아님)

### [중요 정정] SPEC-AI-071의 실제 구현

작업 지시의 2차 정보는 SPEC-AI-071이 코드대역(500000-599999/700000-799999)으로 필터링했다고 기술했으나,
`git show 03ff8dd`의 실제 diff는 다르다:

- SPEC-AI-071은 `_fetch_tracked_stock_codes(db, codes)`(`surge_actual_outcome_service.py:40`)로
  `db.query(Stock.stock_code).filter(Stock.stock_code.in_(codes))` — 즉 앱 **`stocks` 테이블 교집합**을
  사용했다. 코드대역 정규식·상수가 **아니다**.
- 코드베이스 전역 검색(2026-07-08): `korea_stock_classification` 모듈 **없음**, `500000`/`700000` 코드대역
  분류 상수 **없음**. 유일한 재사용 자산은 `_fetch_tracked_stock_codes`(현재 module-private).

### 왜 `stocks` 교집합이 옳은가

- **권위적**: 레버리지/인버스 ETF·ETN은 앱 `stocks` 테이블에 **부재**하다(SPEC-AI-071 전제, 본 조사 재확인).
  `stocks` 교집합은 이들을 정확히 배제한다.
- **탐지기 정합**: Pool B는 결국 `stocks` 기반 탐지기에 후보를 공급한다. 비-`stocks` 코드는 어떤
  탐지기도 후보로 삼을 수 없는 영구 false negative이므로, 후보 단계에서 제거하는 것이 이중으로 옳다.
- **미추적 실제 기업도 동일 논리로 자연 제외** — 코드대역 휴리스틱은 ETN만 겨냥하지만 `stocks` 교집합은
  "앱이 추적하지 않는 모든 것"을 일관되게 배제한다(휴리스틱보다 견고).
- **일관성**: 071과 074가 **같은 규칙**을 쓰면 분류가 한 곳에서 관리된다.

### 재사용 vs 추출 (판단)

`_fetch_tracked_stock_codes`는 `surge_actual_outcome_service.py`의 module-private(`_`) 함수다. 074가
`surge_detector.py::build_scan_universe`에서 쓰려면:

- (a) private 함수를 교차 모듈 import — 동작하나 `_`-private 교차 import는 코드 스멜 + surge_detector →
  surge_actual_outcome_service 결합 유발.
- (b) **중립 공유 헬퍼로 추출**(공개 함수) — 두 호출부가 함께 import. 규칙의 단일 출처, 결합 최소.
  **권장.** 추출 시 071 거동은 불변이어야 하며 기존 `test_surge_actual_outcome_service.py`(361줄)가
  회귀 가드.

plan.md가 최종 위치를 정한다. SPEC 계약은 "분류 규칙이 두 곳에 중복되지 않는다"(단일 출처).

---

## 4. 크라우딩아웃 해소 — limit 트레이드오프 (핵심 설계 쟁점)

`stocks` 교집합만으로는 부족할 수 있다. 이유:

- 현행 fetch는 sosok별 단일 페이지(≈50행)만 조회 → Pool B가 실제로 검사하는 후보는 시장당 ≈50,
  합계 ≈100. `limit=100`은 페이지 행 수에 막혀 사실상 상한이 아니다.
- top-N을 먼저 자른 **뒤** `stocks` 교집합을 적용하면, 이미 top-N 밖으로 밀려난 `109610`류는 복구되지
  않는다(교집합은 top-N 안의 ETF·ETN만 제거할 뿐, top-N 밖 genuine 종목을 끌어오지 못함).

따라서 크라우딩아웃을 실제로 해소하려면 **후보 소스가 genuine 종목을 더 공급**해야 한다. 두 가지 구현
경로:

- **경로 1 — 오버페치 후 교집합**: `fetch_volume_leaders_sync`의 페이지/limit을 늘려(예: `&page=N`
  페이지네이션) 더 많은 원본 후보를 받은 뒤 `build_scan_universe`에서 `stocks` 교집합. 장점: 교집합
  분류를 build_scan_universe(db 보유)에서 그대로 재사용. 단점: `fetch_volume_leaders_sync`는 공유
  함수라 페이지네이션 추가가 `detect_volume_breakout`에도 영향(단, 그 탐지기는 자체 3.0x 임계로 필터하므로
  후보 증가는 안전 방향); 후보 증가분만큼 `fetch_stock_price_history_sync(pages=3)` 호출 증가 → 스크레이핑
  비용/지연 상승.
- **경로 2 — 스크레이프 단계 비-stocks 스킵**: `fetch_volume_leaders_sync`가 스크레이프 중 비-`stocks`
  코드를 세지 않도록 해 `limit`이 genuine 종목만 세게 함. 장점: 고정 limit에서 크라우딩아웃 직접 해소.
  단점: 스크레이퍼에 `stocks` 조회(=db 세션)를 주입해야 해 "순수 스크레이퍼" 성격을 깨거나, db 없는
  분류(코드대역)로 회귀 → SPEC 원칙 위배.

### 비용 상한 고려

각 후보는 `fetch_stock_price_history_sync(pages=3)` 1회를 유발한다. limit을 무한정 올리면 스캔당 수백
회의 HTTP 호출이 발생한다. 따라서 증가는 **유계**여야 한다. ETF·ETN이 상위의 fraction f를 점유한다면,
같은 genuine 후보 수를 확보하기 위한 최소 오버페치는 ≈ `old_limit / (1 - f)`. f가 0.2~0.3이면
limit≈130~150 수준. 다만 `109610`류가 순위 훨씬 아래(예: 절대 거래량 랭크 100+)라면 modest 증가로는
못 잡을 수 있다 — 이 경우 "ETF·ETN 크라우딩" 가설이 부분적 설명임을 인정하고, 유계 증가로 개선 가능한
범위까지를 본 SPEC의 목표로 한다(추가 구조 개선은 별도 SPEC).

### 권장 방향 (plan.md에서 확정)

경로 1(오버페치 + `stocks` 교집합)을 권장한다: 071 분류 재사용 + db 보유처(build_scan_universe)에서
교집합 + `detect_volume_breakout` 거동 불변 보장 가능. 오버페치는 유계(예: limit 상향 or 소수 페이지)로
하고 정확한 값은 Run 단계 측정으로 조정한다. `_min_ratio=2.0`·`max_scan_universe=150`은 불변.

---

## 5. 범위 밖 (사용자 명시 결정)

- **Pool A / DART 공시** — SPEC-AI-073에서 처리. 본 SPEC 무관.
- **Pool C 구조적 후행성** — 별도 유예 SPEC.
- **`detect_volume_breakout`(AI-062/063/066)** — 동일 fetch를 공유하나 그 탐지기의 유니버스/임계/가중치/
  bypass는 해당 SPEC 소유. 본 SPEC은 공유 fetch를 수정하더라도 그 탐지기 거동을 바꾸지 않는다.
- **탐지기/앙상블/발신 게이팅/매매 로직**, `_min_ratio` 완화, `max_scan_universe` 상향, 코드대역 휴리스틱,
  과거 백필 — 모두 범위 밖(spec.md Exclusions).

---

## 6. 구현 방법론 (DDD: ANALYZE-PRESERVE-IMPROVE + Reproduction-First)

`quality.yaml` `development_mode` + CLAUDE.md Section 7 Rule 4(재현 우선):

1. **ANALYZE** — Pool B 후보 조립·fetch 경로·`_fetch_tracked_stock_codes` 재사용성 매핑(위 §2/§3 완료).
2. **PRESERVE / 재현 우선** — 수정 **전**에 실패 characterization 테스트 작성:
   (a) ETF·ETN 코드가 절대 거래량 순위 상위를 지배하는 픽스처에서, 200%+ 비율 genuine 종목(예 `109610`)이
   현행 Pool B에 **표면화되지 못함**(크라우딩아웃)을 포착 — 현행에서 실패.
   (b) `_fetch_tracked_stock_codes`(추출 예정 헬퍼)와 071 기존 테스트가 추출 후에도 통과하는지 기준선.
3. **IMPROVE** — 공유 헬퍼 추출 + Pool B `stocks` 교집합(비율 필터 이전) + 유계 오버페치를 최소 변경으로
   적용. (a)가 통과(genuine 종목 표면화 + ETF·ETN 배제)하고, 071 테스트 전량 통과, 전체 스위트 회귀 없음
   (`-n 4` 포함) 확인.
