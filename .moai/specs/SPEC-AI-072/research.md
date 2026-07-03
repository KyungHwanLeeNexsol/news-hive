# SPEC-AI-072 Research — near_limit_up carry-forward 데이터 소스 교정 (T-1 종가 기준)

조사 완료일: 2026-07-03. 본 문서는 오케스트레이터가 이미 확정한 진단을 구조화한 것으로, 재탐색을
목적으로 하지 않는다. 라인 번호는 2026-07-03 기준 코드 재확인 결과다. 단, §7의 "미해결 기술 질문"은
IMPROVE 이전에 ANALYZE에서 반드시 실증 확인해야 하는 항목이다.

---

## 1. 문제 요약

상한가 근접 carry-forward 탐지기 `detect_near_limit_up_carries`(SPEC-AI-023)는 이름과 docstring상
**전일(T-1) 등락률**로 상한가 근접 종목을 판별해, 그 모멘텀이 **다음 세션으로 이월**될 것이라
예측하는 선행 탐지기다. 그러나 실제 구현은 T-1 종가-대-종가 변화가 아니라 **잡 실행 시점의 현재
등락률(live change_rate)** 을 읽어, 이미 당일 상한가에 근접해 대부분 실현된 종목을 "전일 급등"으로
오분류해 시그널을 발행한다. 탐지기가 장 시작(09:00 KST)이 아니라 **장중(10:00/15:20 KST)** 에
실행되기 때문에, 구조적으로 "이미 오른 종목을 추격"하는 동작이 되어 목적과 정반대다.

---

## 2. 코드 위치 / 함수 / 라인

- **대상 함수**: `detect_near_limit_up_carries(db, config)` —
  `backend/app/services/surge_detector.py:2614`. docstring(`:2618-2621`)이 의도를 명시:
  "전일 near_limit_up_min_pct 이상 near_limit_up_max_pct 이하 등락률 종목 탐지 / 어제 상한가 근접
  종목에 익일 surge_candidate 시그널 발행".
- **버그 지점 — live 가격 조회**: 후보 루프 안에서 `_fetch_price_change_sync(stock.stock_code)`
  (`:2685`) 호출. 이 헬퍼(`:655`)는 `naver_finance.fetch_current_price_with_change`의 동기 래퍼로,
  반환 `change_rate`는 **"현재 시점 대비 전일 종가"** 변화율 — 즉 잡이 도는 그 순간의 **당일 라이브
  등락률**이다. T-1 종가-대-종가 변화가 아니다.
- **오라벨(mislabel) 지점**:
  - 임계 비교 `config.near_limit_up_min_pct <= change_rate <= config.near_limit_up_max_pct`(`:2691-2696`).
  - `confidence = round(change_rate / 30.0 * 0.5, 4)`(`:2698`).
  - reasoning 텍스트 `f"상한가 근접 종목 — 전일 {change_rate:.2f}% 상승, 미체결 모멘텀 이월"`(`:2699-2701`)
    — 라이브 값을 "**전일**"로 서술.
  - metadata `"yesterday_change_pct": round(change_rate, 2)`(`:2704`) — 라이브 값을 필드명
    `yesterday_change_pct`로 저장.
  - `surge_metadata["surge_probability_score"]`(`:2705`), `surge_basis=["near_limit_up_carry"]`(`:2703`).
- **시그널 생성(보존 대상)**: `signal_type="surge_candidate"`(`:2712`), `paper_executed=True`(`:2716`),
  `price_at_signal=price_data.get("current_price")`(`:2717`), `db.commit()`(`:2723`).
- **설정**: `NearLimitUpConfig` — `backend/app/surge_config/surge_settings.py:538`.
  `near_limit_up_min_pct=15.0`(`:543`), `near_limit_up_max_pct=29.99`(`:545`). SPEC-AI-023 익일
  carry-forward. (밴드 15.0/max 29.99는 SPEC-AI-023 후속 수정에서 확정 — 본 SPEC은 값 무변경.)

---

## 3. 호출 체인 / 실행 시점 (장중 실행이 구조적 원인)

- `run_surge_signal_generation`(`fund_manager.py:2982`) → `_run_coverage_expansion`(`:3052` 호출,
  정의 `:3855`) → `detect_near_limit_up_carries`(`:3921`, cfg `:3917`).
- 스케줄러: `_run_surge_signal_generate`(`scheduler.py:1154`)가 동일 `run_surge_signal_generation`을
  재사용하며 **두 시점**에 등록된다:
  - **10:00 KST** — `id="surge_signal_generate_intraday"`(`scheduler.py:2385-2391`, hour=10).
  - **15:20 KST** — `id="surge_signal_generate"`(`scheduler.py:2370-2376`, hour=15/minute=20).
- 장 시작은 09:00 KST. 두 실행 모두 **장중(mid-session)** 이므로, 당일 이미 상한가에 근접한 종목이
  `_fetch_price_change_sync`의 라이브 change_rate로 잡힌다. "전일 상한가 근접 → 익일 이월"이 아니라
  "당일 이미 실현된 상승을 추격"하는 동작이 된다.

---

## 4. 실증 발견 (2026-07-03 라이브)

- 종목 `034940`(조아제약)이 **09:58 KST에 이미 +29.9% 라이브 등락률**(독립 Naver 직접 조회로 확인).
- **10:05 KST**에 10:00 KST 잡(`surge_signal_generate_intraday`)이 돌며 `034940`에 near_limit_up_carry
  시그널 발행. `reasoning = "상한가 근접 종목 — 전일 29.90% 상승, 미체결 모멘텀 이월"`,
  `surge_metadata = {"surge_basis": ["near_limit_up_carry"], "yesterday_change_pct": 29.9, ...}`.
- 그 29.9%는 우리의 독립 확인(09:58) 7분 뒤의 **당일 라이브** 값이지 T-1 종가-대-종가 변화가 아니다.
  즉 "전일 29.90% 상승"·`yesterday_change_pct=29.9`는 둘 다 오라벨.
- 함의: 이미 당일 상한가 부근까지 확장된 종목은 연속보다 **되돌림(reversal)** 확률이 높아, 이
  탐지기가 지금 발행하는 시그널의 precision은 구조적으로 낮을 개연성이 크다.

---

## 5. 결정된 접근 (사용자 확정, 재논의 금지)

라이브 `_fetch_price_change_sync` 호출을, **일봉 이력에서 계산한 T-1 종가-대-종가 change_rate** 로
대체해, 탐지기가 이름·docstring이 주장하는 값을 실제로 측정하게 한다.

**재사용 인프라(코드베이스 확립 패턴):**
- `fetch_stock_price_history_sync(stock_code, pages=3) -> list[PriceRecord]`
  (`naver_finance.py:808`) — 동기, 캐시됨, Naver `sise_day.naver` 일봉 스크레이프. 이미
  `detect_bollinger_squeeze_signals`(`:3594`), `fetch_gap_up_runners`(`:3879`), Pool B 유니버스
  (`:4136`), `detect_volume_anomaly...`(`:2549`) 등 다수 탐지기가 사용.
- `PriceRecord` dataclass(`naver_finance.py:656-663`): `date: str`("YYYY.MM.DD"), `close/open/high/
  low/volume: int`. **`change_rate` 필드 없음 — `(close[T-1] - close[T-2]) / close[T-2] * 100` 로
  계산해야 한다.**
- `_get_prev_business_day(ref: date) -> date`(`surge_trading_service.py:161`) — KST 영업일 산술.
  이미 `surge_actual_outcome_service.py:112`, `surge_evaluation_service.py:87`가 T-1 계산에 사용.

**이력 정렬 규약(코드베이스 확립 사실):** 반환 리스트는 **최신순(newest-first)**.
- 근거 1: `_get_peer_price_5d_trend`(`surge_detector.py:2323`) 주석 "Naver 데이터는 최신순 정렬:
  index 0=최신, index -1=가장 오래된".
- 근거 2: SPEC-AI-067 REQ-004/006(`surge_detector.py:4139-4146`)은 장중에 `history[0]`을
  **당일(today, 진행 중 partial candle)**, `history[1:]`을 **완결된 이전 거래일**로 취급한다.
  단 REQ-006 주석은 "이전 행(history[1:]) 정확성 미검증"이라 **명시적으로 가정**임을 표기한다.

---

## 6. 선택 근거 — 왜 배열 인덱스가 아니라 날짜 매칭인가

§5의 규약대로면 장중에 `records[0]=당일`, `records[1]=T-1`, `records[2]=T-2` 이므로 인덱스
`records[1]/records[2]`로 T-1/T-2를 뽑고 싶어진다. 그러나 그 규약은 **"장중에 Naver가 당일 partial
행을 이미 채웠다"** 는 타이밍 가정에 의존한다. Naver 서버측 캐시/트래픽 사정으로 당일 행이 아직
없으면 `records[0]`이 T-1이 되어 **모든 인덱스가 한 칸 밀린다**. 따라서 인덱스 위치가 아니라
**`date` 필드 매칭**으로 T-1 레코드를 선택하고, 그 바로 뒤(더 오래된) 레코드를 T-2로 삼아
종가-대-종가 change_rate를 계산해야 한다. 예상 T-1 KST 거래일이 반환 이력에 **없으면(데이터 공백/
휴장 불일치/`pages` 부족) 그 종목은 조용히 스킵**한다 — "종목별 실패가 배치를 중단하지 않는다"는
본 코드베이스의 확립된 관례(`surge_detector.py`의 인접 탐지기 per-stock try/except,
`surge_actual_outcome_service.py`의 per-code 처리)와 일관.

---

## 7. 미해결 기술 질문 (ANALYZE에서 실증 확인 필수, 가정 금지)

1. **당일 partial 행의 존재 여부/타이밍**: 10:00 및 15:20 KST 잡 실행 시점에
   `fetch_stock_price_history_sync`가 (a) 당일 진행 중 행을 `records[0]`으로 포함하는지, (b) 항상
   완결된 과거 거래일만 반환(즉 `records[0]=T-1`)하는지. → 이 답이 무엇이든 §6의 날짜 매칭으로
   견고해야 하므로, 인덱스 기반 선택은 채택하지 않는다. 다만 ANALYZE는 실제 응답을 관측해
   `date` 매칭 로직이 두 경우 모두에서 옳게 동작함을 확인해야 한다.
2. **이전 거래일 행 정확성**: SPEC-AI-067 REQ-006이 "history[1:] 완결 가정, 미검증"으로 남겨둔
   부분 — T-1 종가가 확정 종가인지(장중에 T-1 행이 재조정되지 않는지) 스팟 확인.
3. **`price_at_signal` 소스**: 라이브 호출을 완전히 제거하면 `price_at_signal`(`:2717`,
   현재 `current_price`)의 소스가 사라진다. 두 허용안 중 택1(REQ-AI072-005): (A) T-1 종가를
   `price_at_signal`로 사용(완전 이력 기반, `_fetch_price_change_sync` 제거), (B)
   `price_at_signal` 전용으로만 라이브 현재가 스냅샷을 유지(당일 값이 "전일"로 오라벨되지 않는 한
   허용). 어느 쪽도 change_rate/임계/confidence/reasoning/metadata는 반드시 T-1 기반이어야 한다.
4. **`pages` 값**: T-1·T-2 두 완결일만 있으면 되므로 `pages=1`(약 10거래일)로 충분하나, 연휴/공백
   대비 여유가 필요하면 상향. 캐시가 다른 탐지기와 공유되므로 값 선택은 런타임에 큰 영향 없음.

---

## 8. 기존 테스트 자산 (DDD PRESERVE 출발점)

- `backend/tests/test_near_limit_up_carry.py` — AC-001~015 + bugfix 테스트가 존재하며, **전부
  `app.services.surge_detector._fetch_price_change_sync`를 patch** 해 `{"current_price":..,
  "change_rate":..}`를 주입한다(예: `_mock_price(27.0)`). 필터 소스가 이력으로 바뀌면 이 테스트들은
  `fetch_stock_price_history_sync`를 OHLCV 픽스처로 mock 하도록 갱신되어야 한다.
- `:546-547`은 `"yesterday_change_pct" in metadata` 를 단언 — 키는 유지되되(값이 이제 정확한 T-1
  값), 회귀로 오판하지 않도록 갱신.

---

## 9. 구현 방법론 (DDD: ANALYZE-PRESERVE-IMPROVE)

`quality.yaml` `development_mode: ddd` 이므로:
1. **ANALYZE** — §7의 미해결 질문(당일 행 존재/타이밍, T-1 정확성, price_at_signal, pages)을 실제
   Naver 응답 관측으로 해소. 현행 호출 체인·의존성 매핑(위 §2/§3 완료).
2. **PRESERVE** — 필터 교체 전 현행(라이브 기반, 버그) 동작을 포착하는 **characterization test**
   작성: `_fetch_price_change_sync`의 라이브 change_rate가 임계/confidence/reasoning/
   yesterday_change_pct에 그대로 흘러가던 현재 동작 스냅샷(버그 재현).
3. **IMPROVE** — change_rate 소스를 T-1 종가-대-종가(날짜 매칭)로 교체, per-stock 스킵 도입. 테스트를
   `fetch_stock_price_history_sync` mock으로 갱신해 신규 동작 확정. 임계 비교식·`change_rate/30*0.5`
   confidence·`paper_executed=True` surge_candidate 생성은 change_rate 소스 외 무변경.
