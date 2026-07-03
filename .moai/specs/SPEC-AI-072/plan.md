# SPEC-AI-072 Implementation Plan

## 설계 근거 (데이터 소스와 선택 기준)

**핵심 문제**: 탐지기 이름·docstring(`surge_detector.py:2618-2621`)은 "전일(T-1) 상한가 근접 →
익일 이월"을 주장하나, 구현(`:2685` `_fetch_price_change_sync`)은 잡 실행 시점의 **라이브 등락률**을
읽는다. 탐지기가 장중(10:00/15:20 KST, 개장 09:00 이후)에 돌기 때문에, 라이브 값은 "이미 당일 오른
종목"을 가리키고 이를 "전일 급등"으로 오라벨한다. 상한가 부근까지 확장된 종목은 연속보다 되돌림
경향이 커, precision이 구조적으로 낮을 개연성이 있다.

**교정**: change_rate 소스를 `fetch_stock_price_history_sync` 일봉의 **T-1 종가-대-종가**
`(close[T-1] - close[T-2]) / close[T-2] * 100` 로 대체. 이렇게 하면 임계·confidence·reasoning·
`yesterday_change_pct`가 모두 이름이 주장하는 값을 실제로 측정한다.

**T-1 선택 = 날짜 매칭(인덱스 아님)**: 이력은 최신순이고 장중 `records[0]`이 당일 partial일 수
있으나(SPEC-AI-067 REQ-004/006 규약), 그 존재는 Naver 서버측 타이밍에 의존한다. 당일 행이 아직
없으면 인덱스가 한 칸 밀린다. 따라서 `PriceRecord.date`("YYYY.MM.DD")를 `_get_prev_business_day`로
산출한 예상 T-1 KST 거래일과 매칭해 T-1을 찾고, 그 바로 이전(더 오래된) 레코드를 T-2로 삼는다.
예상 T-1 날짜가 없으면 그 종목만 조용히 스킵.

## 진입점 / 재사용 (신규 자산 최소화)

**재사용:**
- `detect_near_limit_up_carries`(`surge_detector.py:2614`) — 유일한 변경 대상 함수.
- `fetch_stock_price_history_sync`(`naver_finance.py:808`) + `PriceRecord`(`:656-663`) — 이미 다수
  탐지기가 쓰는 동기/캐시 일봉 조회. 캐시가 공유되므로 같은 실행 내 다른 탐지기가 데운 종목은 재요청
  없이 히트.
- `_get_prev_business_day`(`surge_trading_service.py:161`) — T-1 KST 거래일 산출.
- 최신순 정렬 규약 + 종가 추출 패턴(`_get_peer_price_5d_trend` `:2313-2330`, bollinger `:3598`).

**신규 자산:** 없음(신규 테이블·모델·마이그레이션·스케줄러 잡 없음). 함수 내부의 데이터 소스 교체
+ 소규모 헬퍼(예: T-1 종가-대-종가 계산 내부 함수)만.

## 마일스톤 (우선순위 기반)

1. **(ANALYZE) 미해결 질문 실증 해소** — research §7: (a) 10:00/15:20 KST 잡 시점에
   `fetch_stock_price_history_sync`가 당일 partial 행을 `records[0]`으로 포함하는지 실제 응답 관측,
   (b) T-1 종가 확정성 스팟 확인, (c) `price_at_signal` 소스안(A/B) 결정, (d) `pages` 값 결정.
   결과와 무관하게 날짜 매칭이 옳음을 확인.
2. **(PRESERVE) characterization test 작성** — 현행(라이브 기반, 버그) 동작 스냅샷: `_fetch_price_
   change_sync`의 라이브 change_rate가 임계/confidence/reasoning/`yesterday_change_pct`로 그대로
   흘러가던 동작을 고정(버그 재현). `test_near_limit_up_carry.py`의 기존 mock 구조 활용.
3. **(P0, IMPROVE) T-1 종가-대-종가 소스 교체** — `_fetch_price_change_sync` 호출 지점을
   `fetch_stock_price_history_sync` + 날짜 매칭 T-1/T-2 계산으로 교체(REQ-001/002). 임계·confidence·
   reasoning·metadata는 새 change_rate를 그대로 소비.
4. **(P0) 종목별 조용한 스킵** — 예상 T-1 날짜 부재/T-2 부재/조회 실패 시 `continue`로 종목만 스킵,
   배치 미중단(REQ-002).
5. **(P1) price_at_signal 소스 확정** — ANALYZE 결정에 따라 (A) T-1 종가 또는 (B) 라이브 스냅샷.
   NULL 회귀/오라벨 없음(REQ-005).
6. **(P0) 회귀 보호 검증** — 임계(15.0~29.99)·`change_rate/30*0.5` confidence·`paper_executed=True`
   생성·중복 방지·`max_signals_per_day`가 무변경임을 테스트로 확정(REQ-004).
7. **(IMPROVE 검증) 테스트 갱신** — `test_near_limit_up_carry.py`를 `fetch_stock_price_history_sync`
   OHLCV mock 기반으로 갱신, 신규 T-1 동작 확정. `yesterday_change_pct` 값 정확성 단언 추가.

## 실패/엣지 처리 설계

- **T-1 날짜 이력에 없음**: 데이터 공백/휴장 불일치/`pages` 부족 → `continue`(그 종목만 스킵). 근거:
  코드베이스의 per-stock 실패 격리(인접 탐지기 try/except, `surge_actual_outcome_service.py` per-code).
- **`fetch_stock_price_history_sync` 조회 실패/빈 리스트**: 예외 억제 후 스킵(기존 `:829-830` debug
  로그 관례와 일관).
- **`close[T-2] <= 0`**: 0 나눗셈 방지 → 스킵(`_get_peer_price_5d_trend`의 `oldest > 0` 가드와 동형).
- **당일 partial 행이 T-1로 오인될 위험**: 날짜 매칭이 당일 날짜를 T-1로 뽑지 않도록, 예상 T-1
  날짜(과거 거래일)와 정확히 일치하는 레코드만 T-1으로 채택(당일 행은 T-1 날짜와 불일치하므로 자연
  배제).
- **함수 최상위 예외**: 기존 `try/except`(`:2729-2731`)가 빈 리스트 반환으로 파이프라인 보호 —
  유지.

## 롤아웃 전략 (전진 전용, 신호 생성 경로 국소 변경)

본 SPEC은 단일 탐지기의 change_rate 입력만 바꾸므로 앙상블/매수 로직 위험이 없다.

1. **백필 없이 전진(forward-only)** — 다음 `run_surge_signal_generation`(10:00/15:20 KST) 실행부터
   적용. 구 로직으로 생성된 과거 near_limit_up_carry 시그널은 손대지 않는다(Exclusion 4).
2. **배포 확인** — 배포 후 첫 실행에서 (a) near_limit_up_carry 시그널의 `yesterday_change_pct`가
   당일 라이브가 아니라 T-1 종가-대-종가와 일치하는지, (b) T-1 이력 부재로 스킵된 종목이 배치를
   중단시키지 않는지, (c) 발행 건수가 합리적 범위인지 로그로 확인.
3. **precision 재해석 유의** — 교정 전후로 이 탐지기의 시그널 성격이 "추격"→"전일 이월 예측"으로
   바뀌므로, 041 평가에서 near_limit_up_carry 조합의 시계열 비교 시 배포일을 경계로 인지.
4. **Deploy Guard** — 15:15~16:10 KST 자동 대기 창 준수(기존 배포 파이프라인 관례).

## 리스크

- **T-1 이력 부재로 인한 과도 스킵** — `pages`가 너무 작거나 연휴로 T-1/T-2가 이력에 없으면 정상
  종목이 스킵될 수 있음. `pages`를 연휴 대비 여유 있게(예: 2~3) 잡고, REQ-004/AC로 정상 케이스가
  스킵되지 않음을 보장. 캐시 공유로 런타임 부담은 낮음.
- **당일 partial 행 취급 오류** — ANALYZE에서 당일 행 존재/타이밍을 오판하면 T-1/T-2가 밀릴 수 있음.
  날짜 매칭(예상 T-1 날짜와 정확 일치)으로 인덱스 의존을 제거해 이 위험을 구조적으로 차단.
- **price_at_signal 의미 변화(안 A 선택 시)** — T-1 종가를 price_at_signal로 쓰면 당일 진입가와
  괴리가 생겨 041의 return_pct 계산에 영향 가능. 이는 예측기록 모드(실집행 아님)에서 참조값일 뿐이나,
  ANALYZE에서 041 소비 방식을 확인해 안 A/B를 선택(REQ-005). 오라벨만 아니면 둘 다 허용.
- **런타임** — 라이브 호출 1건이 이력 호출 1건으로 대체되며, 캐시 공유로 오히려 감소 가능.
  `max_stocks_to_check`가 크므로(SPEC-AI-023 후속에서 1200으로 확대) `pages`는 작게 유지.
