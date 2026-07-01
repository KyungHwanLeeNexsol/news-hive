---
id: SPEC-AI-067
version: 0.2.0
status: completed
created: 2026-07-01
updated: 2026-07-01
author: MoAI
priority: High
issue_number: null
---

# SPEC-AI-067: 장중 당일 거래량 실시간성 개선 (Intraday Today-Volume Freshness)

## HISTORY

- 2026-07-01 (v0.2.0): 열린 결정 D1~D4 사용자 확정 반영. (D1) 롤아웃 범위 —
  combo/breakout/PoolB 3개 전부 마스터 `enabled=true` + 스캔당 상한으로 **기본 활성화**
  확정(staged 단계적 옵션 미채택). (D2) `max_live_fetches_per_scan` 기본값 **80** 확정.
  (D3) 부수 버그(`_PriceHistoryCache` 평면 TTL)를 **본 SPEC 범위로 승격** — 신규
  **REQ-AI067-008** 추가, 관련 Non-Goal 제거. 단, 이는 오늘 위메이드 불일치의 실제 원인이
  아니며(신선 fetch에서도 지연) 핵심 수정은 여전히 REQ-001~005(실시간 모바일 소스 전환)
  임을 명시. (D4) 베이스라인 검증 — 경량 점검(AC-6) + 가정 명시 확정, 별도 검증 파이프라인
  미구축.
- 2026-07-01 (v0.1.0): 최초 작성. SPEC-AI-066(선행지표 확신도 게이트) 실증 검증 중
  발견된 **별개의 근본 원인** — 3개 탐지기가 "당일 거래량"으로 사용하는 데이터 소스
  (Naver `sise_day.naver` 일별시세 페이지의 "오늘" 행)가 **장중에 실시간 누적 거래량을
  신뢰성 있게 반영하지 못하고, 종목마다 예측 불가능한 폭으로 지연**된다는 사실을 다룬다.
  이는 게이트/판별 로직(SPEC-AI-066 소관)이 아니라 그 **상위의 입력 데이터 품질** 문제이며,
  합성 테스트로는 잡히지 않는 실환경 데이터 소스 신뢰성 결함이다.
  - **2026-07-01 ~14:45 KST(장중) 실측 증거** — `sise_day` "오늘" 행 거래량 대 Naver 모바일
    API `accumulatedTradingVolume`(실시간 정확) 비교:
    | 종목 | sise_day "오늘" | 모바일 accumulatedTradingVolume | 과소계상 배율 |
    |---|---|---|---|
    | 위메이드 (112040, 당일 M&A 뉴스로 상한가) | 64,418 | 258,945 | 4.0x |
    | 금호건설 (002990, 수일 연속 상한가) | 4,497,704 | 4,497,704 | 1.0x (정확) |
    | 코세스 (089890) | 343,634 | 724,368 | 2.1x |
    | SK하이닉스 (000660, 대형주 대조군) | 3,524,116 | 5,324,483 | 1.5x |
  - **패턴**: 당일 새로 급등하는 종목(위메이드, 첫 관심일)일수록 지연이 심하고, 수일 지속
    관심 종목(금호건설)은 정확하다. 이는 해당 일별시세 페이지에 대한 Naver **자체 서버측
    캐시/갱신 주기가 트래픽 의존적**(다른 Naver 사용자 요청이 많을수록 Naver측 캐시가 최신화)
    이라는 우리 통제 밖 요인과 일치한다. **우리 코드의 캐싱은 원인이 아님**(각 격리 테스트
    프로세스에서 인메모리 캐시가 비어 있어 신선한 HTTP 요청이 이루어졌음을 확인).
  - **SPEC-AI-066과의 연결**: 이 결함은 오늘 SPEC-AI-066 수정 이후에도 위메이드가 여전히
    포착되지 않은 이유의 **일부**를 설명한다. `detect_volume_surge_news_combo`의 Gate 1
    (SPEC-AI-030 z-score)이 stale `sise_day` 값 64,418을 20일 평균 182,449에 대입해
    **음(-)의 z-score(-1.63)** — 즉 "거래량 감소 중"이라는 잘못된 신호 — 을 계산했다.
    실제 실시간 값(258,945)이었다면 양(+)의 z-score(+1.05)로, 여전히 raw 임계(2.0~2.5)에는
    미달이나 **방향은 옳게** 나온다. 이는 SPEC-AI-066이 고친 게이트 로직과 **가산적(additive)
    으로 독립**된, 데이터 소스 신뢰성 갭이다.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

본 SPEC은 신규 탐지기·매매 엔진·스트리밍 인프라를 만들지 않는다. 기존 자산 위에서 동작하며,
각 항목은 코드 재확인(2026-07-01) 결과다.

- **[HARD] SPEC-AI-066 (확신도 기반 선행 급등 신호 정밀화) — 별개·독립**: 본 SPEC은
  SPEC-AI-066이 소유한 **게이트/판별 로직(과열·신선도·분산 게이트, 확신도 산출, 공시 페널티
  예외, co-mention 테마, volume_breakout 유니버스/상대임계)을 일절 변경하지 않는다.** 본
  SPEC은 그 게이트들에 **입력되는 "당일 거래량" 값의 신선도만** 교정한다. 두 SPEC은 서로
  다른 계층을 다룬다(AI-066 = 판별 로직, AI-067 = 입력 데이터 소스).
- **SPEC-AI-030 (거래량콤보 추격매수 방지)**: Gate 1(과열)·Gate 2(신선도)·Gate 3(분산)이
  모두 "당일 거래량" 또는 그로부터 계산된 z-score/신선도비에 의존한다. 본 SPEC이 당일
  거래량을 더 정확하게 만들면 이 게이트들의 판정이 실측 기반이 되지만, **게이트의 임계·구조
  자체는 변경하지 않는다.**
- **SPEC-AI-062 / AI-063 (volume_breakout 탐지기 + 단독 bypass)**: `detect_volume_breakout`
  (surge_detector.py:3629)의 `today_vol = history[0].volume`(:3677)가 본 SPEC의 교정 대상
  중 하나다. **가중치(AI-062)·bypass 임계 0.30(AI-063)은 불변.**
- **SPEC-AI-065 (z-score 상대 채점 + 유니버스 확장 Pool A/B/C)**: `build_scan_universe`
  (surge_detector.py:3851) Pool B의 `today_vol = history[0].volume`(:3928)가 교정 대상.
  Pool 우선순위·상한·z-score 베이스라인 서비스는 불변.
- **[HARD] 데이터 가용성 사실 확인 (2026-07-01 코드 재확인)**:
  - Naver 모바일 API 엔드포인트 `https://m.stock.naver.com/api/stock/{code}/price`는
    **이미 본 코드베이스에서 사용 중**이다:
    - 비동기 `_fetch_fundamentals_mobile()`(naver_finance.py:583~625)가
      `accumulatedTradingVolume` 필드를 `volume`으로 파싱(:620).
    - 동기 `fetch_current_price_with_change_sync()`(naver_finance.py:847~880)가 **동일
      엔드포인트**를 호출하나 현재는 `closePrice`/`fluctuationsRatio`만 추출하고
      `accumulatedTradingVolume`은 추출하지 않는다. 즉 이 엔드포인트로의 **동기 경로가 이미
      존재**하며, 거래량 필드 추출만 추가하면 된다.
  - `sise_day` 기반 동기 조회는 `fetch_stock_price_history_sync()`(naver_finance.py:779~807,
    `SISE_DAY_URL` :374)이며, 반환 리스트는 **최신순(newest-first)**. 따라서 "오늘"은
    `history[0]`(breakout/PoolB) 또는 `_get_volume_history`가 역순 변환 후 반환하는 리스트의
    **마지막 원소 `volumes[-1]`**(combo)이다.
  - 장중 판정에 재사용 가능한 `_is_market_open()`(naver_finance.py:36~45, 평일
    09:00~15:30 KST) 헬퍼가 이미 존재한다.
  - `PriceRecord`에는 `.volume`(int) 필드가 있다.
- **[HARD] 시가(open_price) 미가용**: 동기 경로에 시가/분봉은 없다(SPEC-AI-066에서 확인).
  본 SPEC은 시가·분봉을 도입하지 않으며, 오직 **누적 거래량 필드 하나**만 교정한다.

---

## Overview

급등 예측 시스템의 3개 지점이 "당일 거래량"을 Naver `sise_day.naver` 일별시세 페이지의
"오늘" 행에서 읽는다. 이 값은 장중에 실시간 누적 거래량을 신뢰성 있게 반영하지 못하고,
종목별로 가변적·예측 불가능한 폭(오늘 실측 최대 4.0x 과소계상)으로 지연된다. 본 SPEC은
장중(시장 개장 시간)에 한해 이 "당일 거래량" 원소를 **이미 본 코드베이스에서 사용 중인
Naver 모바일 API의 `accumulatedTradingVolume`(실시간 정확) 필드로 교체**한다.

정의하는 요구사항(우선순위 표기):

- **[P0] REQ-AI067-001 — 실시간 당일 거래량 소스(공유 메커니즘)**: 장중에 종목의 "당일
  누적 거래량"을 모바일 API `accumulatedTradingVolume`에서 취득하는 단일 공유 메커니즘을
  도입한다(세 호출부가 중복 없이 재사용).
- **[P0] REQ-AI067-002 — combo 탐지기 당일 거래량 교정**: z-score 입력의 "오늘" 원소
  (`volumes[-1]`)를 실시간 값으로 대체한다.
- **[P0] REQ-AI067-003 — volume_breakout 탐지기 당일 거래량 교정**: `today_vol =
  history[0].volume`을 실시간 값으로 대체한다.
- **[P0] REQ-AI067-004 — Pool B 당일 거래량 교정**: `build_scan_universe` Pool B의
  `today_vol = history[0].volume`을 실시간 값으로 대체한다.
- **[P0] REQ-AI067-005 — 장애 시 fail-open 폴백**: 모바일 API 실패(레이트리밋·네트워크·
  종목 미존재·필드 부재) 시 기존 `sise_day` 당일 값으로 우아하게 폴백하며, 탐지를 중단하지
  않는다.
- **[P1] REQ-AI067-006 — 과거 베이스라인 무결성(가정 명시)**: 베이스라인(어제 및 그 이전)
  거래량은 계속 `sise_day`에서 취득하며 본 SPEC이 변경하지 않는다. 완결된 과거일 행은
  정확하다는 **가정을 명시적으로 기록**하고, 이를 **점검(spot-check) 대상**으로 남긴다
  (오늘의 "오늘 행" 지연만 실측했을 뿐, 과거 행의 장 마감 직후 잔여 지연 여부는 미검증).
- **REQ-AI067-007 — 설정 추가**: `intraday_live_volume` 섹션(마스터 스위치 `enabled=true`
  기본 활성 [D1 확정]·장중 게이팅·스캔당 조회 상한 `max_live_fetches_per_scan=80` 기본값
  [D2 확정]).
- **[P2] REQ-AI067-008 — `_PriceHistoryCache` 장중 인지형 TTL(부수적 견고성 개선)** [D3 확정]:
  형제 캐시와 달리 홀로 평면 `PRICE_CACHE_TTL=3600`을 쓰는 `_PriceHistoryCache`를 장중
  인지형 `_cache_ttl()`(장중 짧은 TTL / 장외 긴 TTL)로 전환한다. **이는 오늘 위메이드
  불일치의 실제 원인이 아니며(핵심 수정은 REQ-001~005), 관련 부수 불일치를 바로잡는
  독립적 견고성 개선이다.**

이 SPEC은 **무엇을(WHAT)**과 **왜(WHY)**를 정의하며, 공유 헬퍼의 정확한 함수 시그니처·
스플라이스 지점·예산 상한의 구체 수치는 plan.md 및 Run 단계로 이연한다.

**[HARD] 핵심 수정 vs 부수 개선 구분(오해 방지)**: 본 SPEC의 **핵심 수정은
REQ-001~005**(장중 당일 거래량을 모바일 실시간 소스로 전환)이며, 이것만이 오늘 관측된 지연
문제(위메이드 4.0x 과소계상)를 실제로 해결한다. **REQ-008(캐시 TTL 전환)은 부수적
견고성 개선**으로, **그것만으로는 오늘 같은 문제의 재발을 막지 못한다** — 신선한 HTTP
fetch에서도 `sise_day` 페이지 자체가 지연되어 있었으므로, 캐시 TTL을 아무리 짧게 해도 stale
소스를 더 자주 읽을 뿐이다. 두 수정은 서로 다른 문제를 다루며 REQ-008은 REQ-001~005의
전제조건도, 대체재도 아니다.

### 문제 맥락 — 3개 호출부와 지연 소스 (Evidence)

| 호출부 | "당일 거래량" 코드 위치 | 소스 | 지연 영향 |
|---|---|---|---|
| `detect_volume_surge_news_combo` (Gate 1 z-score) | `current_vol = volumes[-1]` (surge_detector.py:911), `volumes = _get_volume_history(...)`(:903 → :1000) | `sise_day` (fetch_stock_price_history_sync) | **z-score 부호 오류** (위메이드 -1.63 vs 실측 +1.05) |
| `detect_volume_breakout` | `today_vol = history[0].volume` (surge_detector.py:3677) | `sise_day` (pages=3) | breakout 배율 과소 → 미탐지 |
| `build_scan_universe` Pool B | `today_vol = history[0].volume` (surge_detector.py:3928) | `sise_day` (pages=3) | 유니버스 편입 실패 |

**교정 가능 근거(코드 재확인)**: 모바일 `accumulatedTradingVolume`은 비동기
`_fetch_fundamentals_mobile`(:620)에서 이미 파싱되고 있고, 동기 `fetch_current_price_with_change_sync`
(:847)는 동일 엔드포인트를 이미 호출한다. 즉 **신규 데이터 소스가 아니라 기존 소스의 필드
하나를 동기 경로에서 추출·주입**하는 경량 변경이다.

### 데이터 소스 비교 (설계 근거)

| 구분 | `sise_day` "오늘" 행 | 모바일 `accumulatedTradingVolume` |
|---|---|---|
| 장중 실시간성 | 트래픽 의존, 최대 4.0x 과소(오늘 실측) | 실시간 정확(오늘 실측 대조군 1.0x) |
| 과거 완결일 | 정확(가정, REQ-006 점검 대상) | 당일치만 제공(과거 미제공) |
| 동기 경로 존재 | 예 (fetch_stock_price_history_sync) | 예 (fetch_current_price_with_change_sync, 필드 미추출) |
| 코드베이스 사용 이력 | 광범위 | `_fetch_fundamentals_mobile` 등에서 사용 |

핵심: 본 SPEC은 **당일 원소 하나**만 모바일 소스로 바꾸고, **과거 베이스라인은 sise_day를
유지**한다(모바일은 과거일을 제공하지 않으므로 애초에 대체 불가).

---

## Root Cause (근본 원인)

### Root Cause 1 — `sise_day` "오늘" 행은 장중 실시간 누적 거래량이 아니다

`fetch_stock_price_history_sync`가 파싱하는 `sise_day.naver` 일별시세 페이지의 최신 행("오늘")은
Naver 서버측 캐시/갱신 주기에 종속되어 장중에 실시간 누적 거래량보다 뒤처진다. 지연 폭은
고정 상수가 아니라 종목별 트래픽에 따라 가변적이며(오늘 실측 1.0x~4.0x), **당일 새로
급등하는 종목일수록 심하다** — 이는 곧 급등 예측이 가장 잡아야 할 종목에서 데이터가 가장
나쁘다는 뜻이다. 우리 인메모리 캐시(`_PriceHistoryCache`)는 원인이 아님이 확인되었다(신선한
HTTP 요청에서도 페이지 자체가 stale).

### Root Cause 2 — 세 탐지기가 동일한 stale 소스를 공유한다

`detect_volume_surge_news_combo`(z-score), `detect_volume_breakout`(배율), `build_scan_universe`
Pool B(유니버스 편입)가 모두 동일한 `sise_day` "오늘" 값을 "당일 거래량"으로 사용한다.
따라서 지연은 세 경로 모두에 동시에 전파되며, combo에서는 **z-score의 부호까지 뒤집어**
"거래량 감소 중"이라는 정반대 신호를 만든다(위메이드 -1.63).

### Root Cause 3 (부차, REQ-008로 in-scope) — `_PriceHistoryCache`의 TTL이 장중 인지형이 아니다

`naver_finance.py`의 형제 캐시(`_FundamentalsCache`/`_SectorCache`/`_StockPerfCache`)는
`_cache_ttl()`(:48~49, 장중 10초 / 장외 300초, config.py:49~50)로 **장중 인지형 동적 TTL**을
쓰는 반면, `_PriceHistoryCache`만 홀로 평면(flat) `PRICE_CACHE_TTL=3600`(:375, 1시간)을 쓴다
(사용처 :669, :731, :788). 장기 실행 운영 프로세스에서는 1시간 캐시가 stale `sise_day` 값을
최대 1시간 고착시켜 지연을 가중할 수 있는 **형제 캐시와의 독립적 불일치**다. 본 SPEC은
D3 결정에 따라 이 불일치를 **REQ-AI067-008로 범위에 포함**해 `_cache_ttl()`로 전환한다.

**[HARD] 그러나 이것은 핵심 원인이 아니다**: 이 평면 TTL은 오늘 실측 불일치의 원인이
**아니다**(격리 테스트에서 캐시가 비어 신선 fetch가 일어났음에도 `sise_day` 페이지 자체가
지연). 따라서 **REQ-008만으로는 오늘 같은 문제의 재발이 방지되지 않는다** — 캐시를 짧게
해도 stale 소스를 더 자주 읽을 뿐이다. 재발 방지의 실질 수정은 여전히 REQ-001~005(실시간
모바일 소스 전환)이며, REQ-008은 그 위에 얹는 부수적 견고성 개선일 뿐이다.

---

## 설계 원칙 (Design Principles)

1. **데이터 계층만 교정, 판별 로직 불변**: 본 SPEC은 게이트·임계·가중치·bypass·확신도 등
   어떤 판별 로직도 바꾸지 않는다. 오직 게이트에 입력되는 "당일 거래량" 값의 신선도만
   높인다. SPEC-AI-030/062/063/065/066의 소유 영역은 전부 보존된다.
2. **당일 원소만 교체**: 모바일 소스로 바꾸는 것은 각 호출부의 "오늘" 거래량 원소
   (`volumes[-1]` 또는 `history[0].volume`) **하나뿐**이다. 과거 베이스라인 원소는 계속
   `sise_day`에서 온다(모바일이 과거일을 제공하지 않음).
3. **장중 게이팅**: 실시간 교체는 시장 개장 시간(`_is_market_open()`)에만 적용한다. 장외
   에는 완결된 `sise_day` 당일 값이 이미 정확하므로 모바일 호출을 하지 않는다(불필요한 HTTP
   제거). 08:00 장전 스캔은 장외로 간주되어 `sise_day`(=전일 완결 데이터) 사용.
4. **Fail-open 방어**: 모바일 호출이 실패하면 반드시 기존 `sise_day` 값으로 폴백한다. 본
   SPEC은 어떤 경우에도 탐지를 중단시키지 않는다(기존 per-candidate try/except 패턴과 일관).
5. **기존 소스 재사용**: 모바일 `accumulatedTradingVolume`은 이미 사용 중인 필드·엔드포인트
   다. 신규 외부 API·스트리밍 인프라·신규 데이터 저장소를 도입하지 않는다.
6. **설정 기반·하위 호환**: 모든 스위치·상한은 `surge_detection.yaml`에서 조정 가능하며,
   섹션 부재 시 문서화된 기본값으로 동작한다. 마스터 스위치 off이면 전 호출부가 `sise_day`
   당일 값을 쓰는 레거시 동작으로 복원된다.
7. **HTTP 예산 방어**: 장중 실시간 조회는 종목당 추가 HTTP 1회다. `detect_volume_breakout`
   (유니버스 최대 ~100)과 Pool B(리더 100)는 스캔당 다수 호출을 유발할 수 있으므로, 스캔당
   조회 상한으로 레이트리밋 노출을 유계(bounded)한다.

---

## EARS Requirements

### REQ-AI067-001: 실시간 당일 거래량 소스 (공유 메커니즘)

**When** a surge detector needs the current trading day's accumulated volume for a stock
during market hours, the system **shall** obtain that value from the Naver mobile price
API's `accumulatedTradingVolume` field (the same endpoint already used by
`_fetch_fundamentals_mobile` and `fetch_current_price_with_change_sync`), rather than
from the `sise_day.naver` daily-quotes "today" row.

**The system shall** expose this as a single shared mechanism reused by all three call
sites (REQ-002/003/004) — the market-hours gate, the live fetch, the fail-open fallback,
and the value splice **shall not** be independently re-implemented at each call site.

**While** the market is closed (outside weekday 09:00–15:30 KST, per `_is_market_open()`),
the system **shall not** issue the live mobile fetch and **shall** use the existing
`sise_day` "today" value (a completed trading day's volume is already accurate, and the
08:00 pre-open scan sees the prior completed day).

**Where** the live value is obtained, the system **shall** replace only the current-day
(today) volume element and **shall not** alter any historical (baseline) volume element,
which continues to come from `sise_day`.

### REQ-AI067-002: combo 탐지기 당일 거래량 교정

**When** `detect_volume_surge_news_combo` computes its SPEC-AI-030 Gate 1 volume z-score,
the system **shall** use the live today-volume (REQ-001) as the `current_vol` term
(currently `volumes[-1]` from `_get_volume_history`, surge_detector.py:911) while keeping
the baseline term (`volumes[:-1]`) sourced from `sise_day`.

**If** the live today-volume is available and greater than the stale `sise_day` value for
a freshly-surging stock, **then** the resulting z-score **shall** reflect the true
accumulated volume (correcting the false-negative "declining volume" sign error observed
for 위메이드: stale 64,418 → z −1.63 vs live 258,945 → z +1.05).

**While** this correction is applied, the system **shall not** change the
`volume_zscore_threshold` or any other Gate 1/2/3 logic — this requirement only changes
the input value, not the gate.

### REQ-AI067-003: volume_breakout 탐지기 당일 거래량 교정

**When** `detect_volume_breakout` determines a candidate's today volume
(`today_vol = history[0].volume`, surge_detector.py:3677), the system **shall** use the
live today-volume (REQ-001) in place of the `sise_day` `history[0].volume`, while keeping
the baseline window (`history[1:baseline_days+1]`) sourced from `sise_day`.

**The system shall not** modify the SPEC-AI-062 detector weight, the SPEC-AI-063
`volume_breakout_bypass_threshold`, the flat `volume_ratio_threshold`, or the SPEC-AI-066
relative-threshold / universe-expansion logic — only the today-volume input value changes.

### REQ-AI067-004: Pool B 당일 거래량 교정

**When** `build_scan_universe` evaluates Pool B volume ratios
(`today_vol = history[0].volume`, surge_detector.py:3928), the system **shall** use the
live today-volume (REQ-001) in place of the `sise_day` `history[0].volume`, while keeping
the baseline window sourced from `sise_day`.

**The system shall not** change the Pool A/B/C priority ordering, the `max_scan_universe`
cap, or the Pool B ratio threshold (`_min_ratio = 2.0`) — only the today-volume input
value changes.

### REQ-AI067-005: 장애 시 fail-open 폴백

**If** the live mobile fetch fails for any reason (rate limit, network error, HTTP error,
stock not found, missing/zero `accumulatedTradingVolume` field), **then** the system
**shall** fall back to the existing `sise_day` today value for that stock and continue
detection without raising.

**The system shall** never let a live-fetch failure abort a detector run or a scan — the
behavior on failure **shall** be byte-equivalent to the current `sise_day`-only behavior
for that candidate (consistent with the existing per-candidate try/except in
`detect_volume_breakout` and Pool B).

**Where** the live value is obtained but is **lower** than the `sise_day` today value
(should not normally happen, but possible from transient API states), the system
**shall** use the larger of the two (accumulated intraday volume is monotonically
non-decreasing within a day; the larger value is the more-accurate accumulated figure).

### REQ-AI067-006: 과거 베이스라인 무결성 (가정 명시 + 점검 대상)

**The system shall** continue to source all historical (non-today) baseline volumes
(yesterday and earlier) from `sise_day`, unchanged by this SPEC.

**Where** the baseline is used, the system relies on the **assumption** that a completed
trading day's `sise_day` volume is accurate once the day is over. This assumption is
**explicitly flagged as a spot-check target** and **shall not** be silently taken as
proven — only the current-day "today row" lag was empirically measured on 2026-07-01;
whether historical rows carry residual lag shortly after market close (e.g., a same-day
row measured minutes after 15:30 KST) was **not** verified.

**When** a baseline spot-check is performed (see acceptance.md AC-6), the check **shall**
compare a recently-completed day's `sise_day` volume against a known-accurate reference
(e.g., the mobile API's value for that same completed day, if available, or the next-day
`sise_day` value for the same date) to confirm the assumption before relying on it for
production tuning.

### REQ-AI067-007: intraday_live_volume 설정 추가

The system **shall** add an `intraday_live_volume` section under `surge_detection:` in
`backend/app/surge_config/surge_detection.yaml`, parsed by a new Pydantic model in
`backend/app/surge_config/surge_settings.py` and attached to `SurgeDetectionConfig` via
`Field(default_factory=...)` (mirroring the existing `catalyst_conviction`/`combo_chase_guard`
wiring). The section **shall** define at minimum:

- `enabled`: bool master switch for all three live-volume corrections (REQ-002/003/004).
  **Default: `true`** — all three call sites (combo/breakout/PoolB) are active by default
  with the per-scan cap as the rate-limit safeguard (D1 확정 2026-07-01; staged per-site
  toggles are NOT adopted). When `false`, all call sites use the `sise_day` today value
  (legacy behavior).
- `market_hours_only`: bool. When `true` (default), the live fetch is issued only while
  `_is_market_open()` is true (REQ-001).
- `max_live_fetches_per_scan`: int. Upper bound on live mobile fetches per scan cycle to
  bound rate-limit exposure; beyond the cap, candidates fall back to `sise_day` (REQ-005).
  **Default: `80`** (D2 확정 2026-07-01).

**When** any of these keys is absent from the YAML, the loader **shall** apply the
documented defaults (backward compatible). All switches and bounds **shall** be adjustable
without code changes.

### REQ-AI067-008: `_PriceHistoryCache` 장중 인지형 TTL (부수적 견고성 개선)

**The system shall** change `_PriceHistoryCache`'s expiry policy from the flat
`PRICE_CACHE_TTL=3600` (naver_finance.py:375) to the market-hours-aware `_cache_ttl()`
(naver_finance.py:48~49; short TTL while market open, longer TTL while closed — reading
`PRICE_CACHE_TTL_MARKET_OPEN`/`PRICE_CACHE_TTL_MARKET_CLOSED` from config.py:49~50), so
that it is consistent with the sibling caches (`_FundamentalsCache`/`_SectorCache`/
`_StockPerfCache`) that already use `_cache_ttl()`.

**Where** `PRICE_CACHE_TTL` is currently referenced (async `fetch_stock_price_history`
:669, `evict_expired` call :731, sync `fetch_stock_price_history_sync` :788), the system
**shall** substitute the market-hours-aware TTL value, preserving all other cache behavior
(eviction, max-size, Redis recovery) unchanged.

**This requirement is a secondary robustness improvement, not the core fix.** The system
relies on REQ-001~005 (live mobile source) — not on this cache TTL change — to resolve the
intraday lag: **this requirement alone does not prevent a recurrence of the 2026-07-01
위메이드 discrepancy**, because a fresh HTTP fetch of `sise_day` was already stale (a shorter
cache TTL only re-reads the stale source more often). This requirement only removes an
independent inconsistency with sibling caches.

**Where** implementing REQ-008 would materially expand the blast radius of the async
`fetch_stock_price_history` path (broadly used) or risk regression in unrelated callers,
the system **shall** keep the change minimal (TTL value substitution only) and **shall
not** alter cache invalidation semantics, eviction thresholds, or the Redis recovery path.

---

## Implementation Scope

| 파일 | 변경 내용 | 관련 REQ |
|---|---|---|
| `backend/app/services/naver_finance.py` | (a) 모바일 `accumulatedTradingVolume`을 반환하는 동기 헬퍼 신규(또는 `fetch_current_price_with_change_sync` 반환 확장 — plan.md에서 결정), `_is_market_open()` 재사용; (b) `_PriceHistoryCache`의 `PRICE_CACHE_TTL=3600`(:375) 사용처(:669, :731, :788)를 `_cache_ttl()`(:48~49)로 전환 | REQ-001 / REQ-008 |
| `backend/app/services/surge_detector.py` | 공유 스플라이스/결정 헬퍼 신규(장중 게이트 + 실시간 fetch + fail-open + 예산 상한); combo `volumes[-1]`(:911 인근), `detect_volume_breakout` `history[0].volume`(:3677), Pool B `history[0].volume`(:3928) 세 지점에서 헬퍼 호출 | REQ-002~005 |
| `backend/app/surge_config/surge_settings.py` | `IntradayLiveVolumeConfig` 신규 모델 + `SurgeDetectionConfig` 연결 (`enabled=true`, `max_live_fetches_per_scan=80` 기본값) | REQ-007 |
| `backend/app/surge_config/surge_detection.yaml` | `intraday_live_volume` 섹션 추가 | REQ-007 |
| `backend/tests/test_surge_ai067.py` (신규) | 장중 실시간 교체(combo z-score 부호 교정/breakout 배율/Pool B 편입)·장외 폴백·fail-open 폴백·예산 상한(80) 초과 폴백·베이스라인 불변·enabled=false 레거시 동등·설정 부재 기본값·베이스라인 무결성 점검·`_PriceHistoryCache` TTL 장중/장외 전환(REQ-008) | 전체 |

---

## Non-Goals (What NOT to Build)

- **WebSocket/스트리밍 실시간 피드를 도입하지 않는다.** 본 SPEC은 기존 폴링 API의 **필드
  하나(`accumulatedTradingVolume`)를 동기 경로에서 추출·주입**하는 경량 변경이며, 실시간
  스트림·메시지 큐·상시 리스너 프로세스 등 신규 인프라를 만들지 않는다.
- **SPEC-AI-066의 게이트/판별 로직을 재검토·변경하지 않는다.** 확신도 산출, 과열·신선도·
  분산 게이트, 공시 페널티 예외, co-mention 테마, volume_breakout 유니버스/상대임계는
  이미 배포·검증되었고 본 SPEC의 범위 밖이다. 본 SPEC은 그 게이트에 **입력되는 데이터
  품질만** 다룬다.
- **과거 베이스라인 원소를 모바일로 대체하지 않는다.** 모바일 API는 당일치만 제공하므로
  과거일은 대체 불가하며, 완결된 과거일은 `sise_day`로 충분하다(REQ-006 가정, 점검 대상).
- **(D3 확정으로 범위 승격됨)** 평면 `PRICE_CACHE_TTL=3600`의 장중 인지형 전환은 더 이상
  Non-Goal이 아니라 **REQ-AI067-008**로 본 SPEC 범위에 포함된다. 단, 이는 부수적 견고성
  개선이며 핵심 수정(REQ-001~005)의 전제·대체가 아님을 REQ-008에 명시했다.
- **시가(open_price)·분봉·OHLC 실시간화를 도입하지 않는다.** 오직 누적 거래량 필드 하나만
  교정한다. 등락률 판정은 기존대로 `change_rate`.
- **탐지기 가중치·임계·bypass·앙상블·적응형 임계값을 변경하지 않는다**
  (AI-018/029/030/041/062/063/065/066 소유). 본 SPEC은 데이터 소스 계층만 소유한다.
- **매수 로직·포지션 사이징·정기 스캔 스케줄을 변경하지 않는다** (예측 기록 모드 유지,
  SPEC-AI-043).

---

## References

### 코드 위치 (수정/신규 대상, 2026-07-01 재확인)

- `backend/app/services/surge_detector.py`
  - `_get_volume_history()` (라인 1000~1028) — combo용 거래량 히스토리(마지막 원소=오늘);
    `fetch_stock_price_history_sync(pages=1)` 사용
  - `detect_volume_surge_news_combo()` — `current_vol = volumes[-1]`(:911), z-score(:917)
    (REQ-002 스플라이스 지점)
  - `detect_volume_breakout()` (라인 3629~3729) — `today_vol = history[0].volume`(:3677)
    (REQ-003); AI-066 REQ-005 유니버스/상대임계는 이미 존재, 불변
  - `build_scan_universe()` (라인 3851~) — Pool B `today_vol = history[0].volume`(:3928)
    (REQ-004)
- `backend/app/services/naver_finance.py`
  - `fetch_stock_price_history_sync()` (라인 779~807) — `sise_day` 동기 조회(최신순),
    `SISE_DAY_URL`(:374); baseline 소스로 유지
  - `_fetch_fundamentals_mobile()` (라인 583~625) — `accumulatedTradingVolume` 파싱(:620)
    선례(재사용 근거)
  - `fetch_current_price_with_change_sync()` (라인 847~880) — 동일 모바일 엔드포인트 동기
    호출(거래량 미추출); REQ-001 헬퍼의 확장/모델 대상
  - `_is_market_open()` (라인 36~45) — 장중 게이팅 재사용
  - `_PriceHistoryCache`(:642~656) + `PRICE_CACHE_TTL`(:375) 사용처(:669, :731, :788) —
    REQ-008 전환 대상; `_cache_ttl()`(:48~49)로 교체 (형제 캐시와 일관화)
- `backend/app/config.py` — `PRICE_CACHE_TTL_MARKET_OPEN=10`/`PRICE_CACHE_TTL_MARKET_CLOSED=300`
  (:49~50), `_cache_ttl()`가 읽는 값 (REQ-008이 `_PriceHistoryCache`에도 적용)
- `backend/app/surge_config/surge_settings.py` — `IntradayLiveVolumeConfig` 신규;
  `SurgeDetectionConfig`(:359~) 연결 (REQ-007)
- `backend/app/surge_config/surge_detection.yaml` — `intraday_live_volume` 섹션 (REQ-007)

### 데이터·동작 사실 확인

- 모바일 응답 `entries[0]`가 "오늘" 데이터(naver_finance.py:599 주석), `accumulatedTradingVolume`
  필드 존재(:620 파싱 선례).
- combo z-score: `mean=statistics.mean(volumes[:-1])`, `current_vol=volumes[-1]`,
  `z=(current_vol-mean)/std`(surge_detector.py:909~917). 마지막 원소가 오늘.
- breakout/PoolB: `history` 최신순 → `history[0]`이 오늘, `history[1:N+1]`이 baseline.
- 오늘 실측(2026-07-01 ~14:45 KST): sise_day 대 모바일 과소계상 1.0x~4.0x, 신규 급등
  종목일수록 심함.

### 선행 SPEC

- SPEC-AI-030: 거래량콤보 추격매수 방지 (Gate 1 z-score 입력을 본 SPEC이 신선화 — 게이트 불변)
- SPEC-AI-062 / AI-063: volume_breakout 탐지기 + bypass (today_vol 소스 교정 — 가중치/bypass 불변)
- SPEC-AI-065: Pool A/B/C 유니버스 (Pool B today_vol 소스 교정 — 우선순위/상한 불변)
- SPEC-AI-066: 확신도 기반 선행 급등 신호 정밀화 (게이트 로직 소유; 본 SPEC은 그 입력
  데이터 계층만 다룸 — 완전 독립)

---

## Implementation Notes

### 마일스톤 완료 요약 (2026-07-01)

모든 7개 마일스톤(M1-M7)을 완료하여 REQ-AI067-001~008을 구현했다.

**구현 대상 파일:**
- `backend/app/services/naver_finance.py` — 모바일 `accumulatedTradingVolume` 동기 취득, `_PriceHistoryCache` TTL 장중 인지형 전환
- `backend/app/services/surge_detector.py` — 공유 스플라이스/결정 헬퍼 `_resolve_today_volume()` 신규(REQ-001), 3개 호출부(combo/breakout/PoolB) 통합
- `backend/app/surge_config/surge_settings.py` — `IntradayLiveVolumeConfig` Pydantic 모델 신규
- `backend/app/surge_config/surge_detection.yaml` — `intraday_live_volume` 섹션 신규(`enabled=true`, `max_live_fetches_per_scan=80` 기본값)
- `backend/tests/test_surge_ai067.py` (신규) — 25개 테스트, AC-1~AC-8 및 Edge Cases 커버

### 검증 결과 (2026-07-01)

**테스트 실행:**
```bash
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"
```
**결과: 1709 passed, 4 skipped, 3 xpassed, 0 failed** (457초 소요)

**린트 검사:**
```bash
uv run ruff check .
```
**결과: 모든 검사 통과**

**테스트 파일 통계:**
- `test_surge_ai067.py`: 25개 신규 테스트, AC 기준 커버리지 100%
- 회귀: SPEC-AI-030/062/063/065/066 관련 기존 테스트 전량 통과

### 구현 편차 3건 (정직한 보고)

다음 3건의 편차는 plan.md 및 spec.md와 구현 실제 사이에 발생했으며, 모두 필요한 근거를 가짐:

#### 편차 1: REQ-002 Gate 2 신선도 체크 범위 확대
- **plan.md 의도**: REQ-002에서 z-score의 `current_vol` 입력만 교정
- **실제 구현**: Gate 2 신선도 체크(`volumes[-1]/volumes[-2]` 비율)도 **동시에** 교정된 "오늘" 값 사용
- **근거**: Gate 2를 stale 값으로 두면, 신선하게 급등 중인 종목이 신선도 체크(Gate 2)에서 stale-to-baseline 비율로 차단될 수 있음 → REQ-002의 "z-score 부호 교정" 효과를 게이트 2가 상쇄 가능
- **해결**: Gate 1(z-score)과 Gate 2(신선도) 모두 `_resolve_today_volume()` 반환값 사용 (기존 Gate 구조/임계 불변)

#### 편차 2: `naver_finance.py` Redis TTL 일관성 개선
- **spec.md**: `_PriceHistoryCache` TTL을 `_cache_ttl()`로 전환하고, 사용처 3곳 교체
- **실제 구현**: Redis write-through 경로(:669)의 `PRICE_CACHE_TTL=3600` 리터럴도 `_cache_ttl()` 호출로 통일
- **근거**: 캐시 대상 `_PriceHistoryCache`는 단기 TTL로 장중 인지화했으나, 그 Redis 백업 쓰기가 여전히 평면 1시간 TTL을 써서 캐시 무효화 의미 불일치
- **해결**: 최소 변경(`PRICE_CACHE_TTL` 리터럴 제거, `_cache_ttl()` 호출 일관화) — 캐시 무효화/eviction/Redis 복구 의미는 불변

#### 편차 3: 스캔-스코프 메모이즈 미구현
- **plan.md**: "필요 시" 고려 항목으로 표기
- **실제**: combo/breakout/PoolB가 동일 스캔 내 동일 종목의 live 거래량을 재요청하지 않음 (각 탐지기 단계별 호출이므로 중복 시점 없음)
- **근거**: 현재 아키텍처에서는 재요청이 발생하지 않아 메모이즈 불필요
- **해결**: 미구현 (필요 없음, Run 단계 결정 사항 충족)

### 핵심 메커니즘 및 기본값

**공유 헬퍼 `_resolve_today_volume(code: str, sise_day_value: int) -> int`:**
- 입력: 종목코드 + sise_day "오늘" 값
- 장중(`_is_market_open()`=true) && 설정 `enabled=true` 시: 모바일 API `accumulatedTradingVolume` fetch → fail-open 폴백(sise_day) → max(live, sise_day) 채택 → 반환
- 장외 또는 설정 비활성화: sise_day 값 그대로 반환
- 스캔당 `max_live_fetches_per_scan=80` 상한 도달 후: 이후 후보는 sise_day 폴백

**기본 설정값 (D1/D2 사용자 확정 2026-07-01):**
- `intraday_live_volume.enabled=true` — 3개 호출부(combo/breakout/PoolB) **모두 기본 활성**
- `max_live_fetches_per_scan=80` — 스캔당 실시간 조회 상한
- `market_hours_only=true` — 장중에만 모바일 호출(장외 비용 0)

### 의도적 불변성 (회귀 보호)

다음 요소는 변경되지 않았으며, 회귀 테스트로 검증:
- SPEC-AI-030 Gate 1~4 구조 (과열/신선도/분산/combo 단독) — 임계 불변, 입력값만 신선화
- SPEC-AI-062 가중치(0.12) 및 AI-063 bypass 임계(0.30)
- SPEC-AI-065 Pool 우선순위/상한/z-score 베이스라인 서비스
- SPEC-AI-066 게이트/확신도 로직 (완전 독립)
- 장외/설정 비활성화 시 레거시 동등 — sise_day-only 동작 복원

### 위메이드(112040) 회귀 시험

SPEC의 근본 동기인 2026-07-01 오전 위메이드 사례에 대해 회귀 검증:

- **시나리오**: sise_day "오늘" 64,418 → 모바일 258,945 (4.0x 과소), 20일 평균 182,449
- **구 동작**: z-score = (64,418 - 182,449) / std = **-1.63** ("거래량 감소" 오신호) → Gate 1 제외
- **신규 동작**: z-score = (258,945 - 182,449) / std = **+1.05** ("거래량 증가" 정신호) → 방향 교정, breakout/PoolB 편입 개선
- **테스트**: `TestComboZScoreSignFlip` 및 통합 시나리오로 부호 교정 검증

### 배치 및 롤백 전략

마스터 스위치 `intraday_live_volume.enabled=false` 시 즉시 레거시 복원 가능:
- 3개 호출부 모두 sise_day "오늘" 값 사용
- 모바일 API 미호출 (0 추가 비용)
- 기존 SPEC-AI-030/062/063/065/066 동작 동등성 검증됨
