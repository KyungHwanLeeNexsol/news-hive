# SPEC-AI-074 Implementation Plan

## 설계 근거 (후보 오염 제거 + 크라우딩아웃 보상, 발신 로직 무변경)

Pool B의 급등 미탐지는 두 층위를 갖는다: (1) **오염** — 레버리지/인버스 ETF·ETN이 절대 거래량 순위
후보 슬롯을 점유, (2) **소스 협소** — 후보 fetch가 사실상 시장당 ≈50행 단일 페이지에 막혀 밀려난
중·소형주가 애초에 검사되지 않음. 두 층위를 함께 다뤄야 실제 개선이 난다.

### 축 1 — 오염 제거: `stocks` 교집합 (REQ-001)

Pool B 후보를 비율 필터링 **이전에** 앱 `stocks` 테이블과 교집합하여 비-`stocks` 상품(레버리지/인버스
ETF·ETN + 미추적)을 배제한다. 분류는 SPEC-AI-071의 `_fetch_tracked_stock_codes` 규칙을 재사용한다
(코드대역 휴리스틱 아님 — research.md §3).

- **왜 `stocks` 교집합인가**: ETF·ETN은 `stocks`에 부재하며(권위적 배제), Pool B는 결국 `stocks` 기반
  탐지기에 후보를 공급하므로 비-`stocks`는 영구 false negative다. 미추적 실제 기업도 동일 논리로 자연
  제외되어 코드대역 휴리스틱보다 견고하다. 071과 같은 규칙을 쓰면 분류가 한 곳에서 관리된다.
- **fail-open**: `stocks` 조회 실패 시 `None` 반환 → Pool B 미필터 진행 + `db.rollback()`(REQ-004,
  071 EC-1 계승).

### 축 2 — 크라우딩아웃 보상: 유계 오버페치 (REQ-002/003)

교집합을 top-N 절단 **이후**에만 적용하면 밀려난 중·소형주는 복구되지 않는다. 따라서 후보 소스가
genuine 종목을 더 공급하도록 원본 fetch를 유계로 확장한다. **권장 경로 = 오버페치 후 교집합**
(research.md §4 경로 1):

- `build_scan_universe`가 `fetch_volume_leaders_sync`로부터 더 많은 원본 후보를 받아(limit 상향 또는
  소수 페이지네이션), `stocks` 교집합으로 ETF·ETN·미추적을 떨군 뒤, 기존 ratio 루프를 genuine 후보 위에서
  돈다.
- **limit 트레이드오프 (명시적 판단)**: 각 후보는 `fetch_stock_price_history_sync(pages=3)` 1회를
  유발하므로 증가는 유계여야 한다. ETF·ETN 점유율 f에 대해 동일 genuine 후보 확보 최소 오버페치 ≈
  `old_limit / (1 - f)`. 라이브 관측상 상위 상당수가 ETF·ETN이므로 f≈0.2~0.3 가정 시 limit≈130~150이
  1차 후보. **정확한 값은 Run 단계에서 (a) 배제 후 순 genuine 후보 수가 배제 전 이상, (b) `109610`류
  표면화, (c) 스캔당 HTTP 호출/지연이 수용 범위 — 3조건으로 측정·조정**한다. SPEC 계약은 결과(순
  genuine 후보 비감소 + genuine 표면화)이지 특정 limit 값이 아니다.
- **왜 스크레이프-단계 스킵(경로 2)이 아닌가**: `fetch_volume_leaders_sync`는 db 없는 순수 스크레이퍼라
  거기서 `stocks` 교집합을 하려면 db 주입(성격 훼손) 또는 코드대역 회귀(원칙 위배)가 필요하다. 오버페치
  경로가 071 분류 재사용 + `detect_volume_breakout` 거동 보존과 양립한다.

## 진입점 / 재사용 (신규 자산 최소화)

**변경 대상 파일:**
- `backend/app/services/surge_detector.py` — `build_scan_universe` Pool B 블록(`:4174-4212`): fetch
  호출부(`:4179`)와 ratio 루프(`:4183-4208`) 사이에 `stocks` 교집합 삽입 + 유계 오버페치. 우선순위
  (A>B>C)·`max_scan_universe`·`_min_ratio`는 불변.
- 공유 헬퍼 추출: `_fetch_tracked_stock_codes`(`surge_actual_outcome_service.py:40`)를 **중립 공유
  공개 헬퍼**로 추출(권장). 두 호출부(071 정답 경로 + 074 Pool B)가 함께 import. 071 거동 불변,
  기존 테스트가 가드.
- (경로 1이 페이지네이션을 택할 경우) `backend/app/services/naver_finance.py` —
  `fetch_volume_leaders_sync`에 유계 페이지네이션/limit 확장(하위 호환, `detect_volume_breakout`
  거동 불변). limit 상향만으로 충분하면 이 파일 무변경 가능.

**재사용:** `_fetch_tracked_stock_codes`(분류), 기존 Pool B ratio 루프/`_resolve_today_volume`
(AI-067)/`fetch_stock_price_history_sync`, `[스캔유니버스]` 로깅 관례, 071 EC-1 fail-open 패턴.

**신규 자산:** 공유 헬퍼 1개(기존 함수 추출) 외 신규 테이블/모델/스케줄러 잡/마이그레이션 **없음**.

## 공유 헬퍼 추출 계획 (규칙 단일 출처)

- 목표: "앱 추적 `stocks` 종목만 유효 후보" 분류 규칙이 **한 곳**에만 존재.
- 권장: `_fetch_tracked_stock_codes`를 중립 공개 함수로 이동/승격(예: 공유 util 모듈 또는 공개 심볼),
  `collect_daily_surge_outcomes`(071)와 `build_scan_universe`(074)가 동일 헬퍼 import.
- **[HARD]** 추출은 리팩터(거동 불변)다 — 071 로직/반환 계약(`None` = fail-open)을 바꾸지 않는다.
  `test_surge_actual_outcome_service.py`가 회귀 가드. 최소 대안(현 위치 공개 승격 후 import)도 규칙
  단일 출처를 만족하면 허용하되, 교차-모듈 결합 최소화를 위해 중립 위치를 우선한다.

## 마일스톤 (우선순위 기반, 재현 우선)

1. **(ANALYZE)** Pool B 후보 조립·fetch 경로·헬퍼 재사용성 확정(research.md 완료).
2. **(재현 우선 · RED)** 수정 **전** 실패 characterization 테스트 작성 후 실패 확인(CLAUDE.md Rule 4):
   - (a) ETF·ETN 코드가 절대 거래량 순위 상위를 지배하는 픽스처에서, 200%+ 비율 genuine 종목
     (예 `109610` 6.86x)이 현행 Pool B(`pool_b_codes`)에 **표면화되지 못함**을 포착 — 현행에서 실패.
   - (b) 071 기존 테스트가 헬퍼 추출 후에도 통과하는지 기준선 확인.
3. **(P0)** 공유 헬퍼 추출(거동 불변) — 071/074 단일 출처. 071 테스트 전량 통과 확인.
4. **(P0)** Pool B `stocks` 교집합(REQ-001) — 비율 필터 이전 삽입 + fail-open(REQ-004).
5. **(P0)** 유계 오버페치(REQ-002) — 배제 후 순 genuine 후보 비감소하도록 후보 소스 확장(값은 측정 조정).
6. **(P0)** genuine 표면화 검증(REQ-003) — (a) 테스트가 수정 후 통과(genuine 종목 Pool B 포함 + ETF·ETN
   배제).
7. **(P1)** 배제 관측 로깅(REQ-005) — 배제 종목 수/예시 로깅(071 REQ-004 형식 일관).
8. **(GREEN/IMPROVE 검증)** 재현 테스트 통과, 071 테스트 무회귀, 전체 스위트 회귀 없음(`-n 4` 포함).
   `detect_volume_breakout` 거동 diff 0 확인.

## 실패/엣지 처리 설계

- **`stocks` 조회 실패**: `_fetch_tracked_stock_codes`가 `None` → Pool B 미필터 진행 + `db.rollback()`
  (REQ-004). Pool B가 비지 않는다.
- **교집합 후 후보 0**: 정제 후 genuine 후보가 없으면 Pool B는 빈 채로 진행(현행에서도 가능한 정상 상태).
  A>B>C 우선순위·`max_scan_universe` 절단은 그대로 동작.
- **오버페치 비용 폭증 방지**: limit/페이지 증가는 유계. 각 후보의 history fetch 비용을 상한으로 관리하고,
  Run 단계에서 스캔당 HTTP 호출/지연을 측정해 값 조정.
- **`detect_volume_breakout` 영향**: 공유 fetch를 수정할 경우 후보 수만 늘 뿐(그 탐지기 자체 3.0x 임계로
  필터), 임계/가중치/bypass diff 0이어야 한다. 테스트로 거동 불변 확인.
- **entry_pool_map 중복**: Pool A가 이미 claim한 코드는 Pool B에서 스킵(현행 `:4184`). 교집합/오버페치가
  이 우선순위를 깨지 않도록 삽입 위치는 기존 dedup 이전/정합.

## 롤아웃 전략

1. **재현 테스트 선행**(Rule 4) — 수정 전 실패 확인 후 최소 수정.
2. **Deploy Guard 준수** — 15:15~16:10 KST 자동 대기 창(기존 배포 파이프라인 관례).
3. **배포 후 관측** — 배포 후 스캔 로그에서 (a) `[스캔유니버스] Pool B` count가 유지/개선, (b) 배제
   로깅에 ETF·ETN 코드가 나타남, (c) 이후 급등 거래일에 200%+ 비율 중·소형주가 Pool B에 표면화되는지
   관찰. Pool B 표면화는 당일 실제 급증 종목 유무에 의존하므로 즉시성보다 전진 관측으로 확인.

## 리스크

- **크라우딩 가설의 부분성** — `109610`류가 절대 거래량 랭크 매우 하위라면 유계 오버페치로도 못 잡을 수
  있다. 완화: SPEC 목표를 "유계 오버페치 + 오염 제거로 개선 가능한 범위"로 한정하고, 절대-거래량-축
  자체의 한계(ratio-우선 소스 등 구조 개선)는 별도 SPEC로 유예. 픽스처 테스트로 개선 방향은 결정적으로
  검증.
- **오버페치 스크레이핑 비용/지연** — limit/페이지 증가가 스캔당 HTTP 호출을 늘린다. 완화: 유계 증가 +
  Run 단계 측정 조정 + history fetch 비용 상한.
- **헬퍼 추출의 071 회귀** — 리팩터가 071 거동을 바꾸면 정답 모집단 손상. 완화: 거동 불변 추출,
  `test_surge_actual_outcome_service.py` 전량 통과를 게이트로.
- **공유 fetch 수정의 파급** — `fetch_volume_leaders_sync` 변경이 `detect_volume_breakout`에 파급.
  완화: 하위 호환 확장(후보 증가만, 임계/필터 무변경) + 그 탐지기 거동 불변 테스트. limit 상향만으로
  충분하면 fetch 함수 무변경.
- **과설계 위험** — 교집합/오버페치를 위해 함수를 과도 재구조화하지 않는다(TRUST Readable). 후보 조립에
  최소 삽입 + 헬퍼 재사용을 우선.
