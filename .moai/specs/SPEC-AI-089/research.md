# SPEC-AI-089 Research — 스캔 유니버스→탐지 배선 사전조사

조사 방법: read-only 코드 읽기(Grep + Read, line-range 매핑) + 이전 세션의 직접 DB 쿼리 결과
인용(project memory `project_surge_architectural_root_cause_2026_07_21.md`,
`project_13stock_miss_analysis_2026_07_09.md`). 코드 라인 번호는 2026-07-27 기준(SPEC-AI-086/087
반영 이후)이며, 향후 커밋으로 드리프트할 수 있으므로 구현 시점에 재확인 필요.

## 재검증 대상: SPEC-AI-086 F-1 (여전히 유효)

`build_scan_universe()`(`backend/app/services/surge_detector.py:4514-4883`)의 유일한 실질
호출부는 `gather_surge_candidates()` 내부 `:1934`이며, 호출 시점이 **8개 1차 탐지기 실행 완료
이후**(`existing_codes=set(merged.keys())`, `:1932`)임을 재확인했다. 반환값
(`_universe_codes`/`_entry_pool_map`/`_pool_counts`)은:

1. 이미 병합된 `merged` 딕셔너리의 `entry_pool` 필드 태깅(`:1937-1941`)
2. `persist_pool_counts`/`persist_universe_members`(SPEC-AI-068) 영속화(`:1954-1969`)

두 곳에만 소비되고, `merged` 자체(탐지 후보 목록)에는 재투입되지 않는다. 스케줄러 호출부
(`scheduler.py:1301`/`:1318`)도 별도 16:00 KST 사전 빌드 잡으로, 결과가 평가용으로 쓰이지 않고
폐기된다(SPEC-086 F-4 재확인, 무변경).

**결론**: SPEC-086의 핵심 주장은 2026-07-27 시점에도 그대로 유효하다. SPEC-087은 이 구조를
전혀 건드리지 않았다(SPEC-087의 3개 탐지기 변경은 각 탐지기의 자체 후보 쿼리 필터이지,
`build_scan_universe`와의 배선이 아니다).

## 신규 발견: 탐지기 유형 분류 (사용자 최초 프레이밍의 부분적 부정확성)

사용자의 최초 작업 지시는 "각 탐지기가 `build_scan_universe`의 유니버스를 후보로 소비하도록
배선하라"는 단일 패턴을 가정했다. 코드를 직접 읽은 결과, 탐지기들은 후보 소싱 방식이 근본적으로
다른 최소 3개 카테고리로 나뉘며, 각 카테고리에 대해 "유니버스 배선"이 의미하는 바와 그 가치가
다르다.

### 카테고리 1 — 블랭킷 시총 스캔형 (SPEC-087이 이미 다룸)

| 탐지기 | 후보 소스 | LIMIT? | 유니버스와의 관계 |
|---|---|---|---|
| `_detect_volume_anomaly_internal` (`:2489-2644`) | `Stock.market_cap >= 300억` 전체 조회 (`:2502-2506`) | **없음** ("무제한 유지" 주석) | 유니버스(150~600 cap)보다 **이미 훨씬 넓다**. 배제 축은 시총 floor/NULL이지 유니버스 밖 여부가 아니다. |
| `detect_group_cascade_signals` 계열사 필터 (`:3630-3658`) | 접두사 매칭 + `market_cap >= 1000억` | `max_cascade_per_flagship`(3) | **2차 확장**(1차 시드는 이미 탐지된 대장주) — 카테고리 3 참고 |
| `detect_gap_up_runners` 섹터 피어 필터 (`:4005-4152`) | 섹터 피어 + `.limit(5)` → `[:2]` | 이미 상한 있음 | **2차 확장**(1차 시드는 이미 탐지된 리더) — 카테고리 3 참고 |
| `detect_bollinger_squeeze_signals` (`:3926-4005`) | `max_stocks_to_check=200`, 시총 상위 N | 있음(200) | 유니버스보다 좁게 이미 제한됨 — 시총 상위 200이라는 별도 축 |

**핵심**: `volume_anomaly`는 이미 유니버스보다 넓은 범위를 스캔하므로, "유니버스를 배선"해도
커버리지가 늘지 않는다(오히려 무의미한 no-op 위험). SPEC-087이 이미 이 탐지기의 진짜 배제 축
(NULL 시총)을 opt-in으로 다뤘다 — 이것이 카테고리 1의 올바른 개입 지점이었다.

### 카테고리 2 — 이벤트 소싱형 (공시/뉴스 테이블 직접 조회, Pool A와 사실상 중복)

| 탐지기 | 후보 소스 |
|---|---|
| `detect_disclosure_surge_pattern` (`:1221-1349`) | 오늘 `Disclosure` 레코드 |
| `detect_immediate_disclosure_signal` (`:1406-1533`) | 오늘 `Disclosure` 레코드 |
| `detect_theme_news_cluster` (`:279-514`) | 최근 N시간 `NewsArticle` + 섹터 매칭 (가격 API 호출 완전 제거됨, SPEC-AI-038) |
| `detect_volume_surge_news_combo` (`:730-1007`) | 뉴스 + 거래량 결합 |

이 카테고리의 후보 소스는 `build_scan_universe`의 **Pool A(오늘 DART 공시)** 소스(`Disclosure`
테이블, `rcept_dt == today`)와 사실상 동일한 원천 테이블을 직접 조회한다. 즉 Pool A가 커버하는
종목은 이미 `disclosure_surge_pattern`/`immediate_disclosure_signal`이 독립적으로 재발견하고
있을 가능성이 높다 — Pool A를 이 탐지기들에 "배선"해도 순증 커버리지는 제한적일 수 있다(정량
검증은 M1 REQ-001의 대상).

### 카테고리 3 — 캐스케이드/캐리형 (이미 탐지된 시그널로부터 파생)

| 탐지기 | 1차 시드 입력 |
|---|---|
| `detect_group_cascade_signals` (`:3568-3812`) | `surge_results` 파라미터 = `gather_surge_candidates()`의 **병합 결과 그 자체** (`:3620` 루프) |
| `detect_theme_group_carry_forward` (`:3052-3195`) | 어제 앵커 종목의 급등 확정 여부 |
| `detect_theme_news_carry` (`:3195-3356`, SPEC-AI-084, 기본 OFF) | 앵커 멤버 동반 이동 |
| `detect_near_limit_up_carries` (`:2691-2917`) | 전일 상한가 근접 종목(`SurgeActualOutcome`/가격 히스토리) |

이 카테고리는 "블랭킷 스캔"이 아니라 "이미 확정된 신호로부터의 2차 파생"이다.
`build_scan_universe`의 코드를 이들의 후보 필터에 배선해도, **1차 시드(대장주/앵커)가 애초에
탐지되지 못하면** 2차 확장은 트리거되지 않는다. F-1(build_scan_universe가 사후 계산)이 진짜
병목이라면, 카테고리 3에 개입하는 것은 근본 원인이 아니라 증상에 개입하는 것이다.

### 카테고리 4 — 유니버스와 병렬·중복 계산형 (신규 발견, 가장 중요)

`detect_volume_breakout`(`:4225-4337`)의 후보 소싱은:

```
leader_codes = fetch_volume_leaders_sync(limit=cfg.max_candidates // 2)   # :4245
history = fetch_stock_price_history_sync(code, pages=3)                    # :4269 (종목당)
today_vol = _resolve_today_volume(code, history[0].volume, config)         # :4275
```

이는 `build_scan_universe`의 **Pool B 계산 로직**(`:4617-4687`, `fetch_volume_leaders_sync(limit=140,
max_pages=3)` + 종목당 `fetch_stock_price_history_sync(pages=3)` + 200% 비율 필터)과 **구조적으로
거의 동일**하다 — 같은 Naver API, 같은 "거래량 배수" 개념, 유사한 파라미터. 두 계산은 서로
독립적으로 실행되며 교차 검증되지 않는다.

**함의**: "Pool B를 탐지에 배선한다"는 표현은 실제로는 이미 존재하는 `volume_breakout` 탐지기와의
**통합/중복제거 문제**일 가능성이 높다 — 전혀 새로운 배선 경로를 만드는 것보다, 두 계산의 차이
(임계값·페이지 수·필터 순서)를 먼저 측정하는 편이 저비용·저위험이다.

## 앙상블 스코어링의 구조적 제약

`compute_ensemble_score()`(`:1533-1604`)는 다음 7개 필드의 순수 가중합이다:
`theme_cluster_score` / `combo_score` / `best_disclosure_score`(pattern·immediate 중 최대) /
`legacy_score` / `news_delayed_score` / `volume_breakout_score` / `momentum_continuation_score`.
"범용 모멘텀" 같은 별도 점수 항목은 존재하지 않는다.

**함의**: Pool B/C 코드를 단순히 스코어링 파이프라인에 "주입"하는 것만으로는 이 종목들의
앙상블 점수가 0이 된다 — 최소 한 개의 실제 탐지기가 그 종목에 대해 점수를 계산해야 신호가 발행될
수 있다. 따라서 배선의 실질 구현은 다음 중 하나를 선택해야 한다(design.md §Options):

- **옵션 A**: Pool B/C 코드를 카테고리 1/2 탐지기의 **입력 후보 집합에 합집합으로 추가**하여, 그
  탐지기들이 이 종목들에 대해서도 실제 점수를 계산하도록 한다(예: theme_cluster의 섹터 필터,
  disclosure_pattern의 Disclosure 필터와 무관하게 Pool B/C 종목은 별도 서브셋으로 통과).
- **옵션 B**: `volume_breakout`과 Pool B의 중복을 통합 — Pool B 계산 결과를 `volume_breakout`
  탐지기의 후보 소스로 재사용(별도 재계산 제거), 카테고리 4의 중복 비용을 없애면서 자연스럽게
  일원화.
- **옵션 C**: 신규 "raw momentum" 앙상블 컴포넌트를 추가 — Pool B/C 소속 자체를 낮은 가중치의
  8번째(실질적으로는 앙상블 재구성이 필요한) 점수 소스로 편입. 앙상블 가중치 합=1.0 불변식
  (`validate_ensemble_weights`, `:567-588`)을 건드리므로 회귀 위험이 가장 크다.

## 비용/스케줄 제약 (재확인)

- `_GATHER_TIMEOUT_S = 1200`(20분) 안전 상한, 정상 소요 12~15분 (`scheduler.py:2500` 주석,
  SPEC-AI-082).
- `gather_surge_candidates()` 호출 스케줄: 평일 09:10 / 09:35 / 10:00 / 10:30 / 10:55 / 15:20 KST
  (`scheduler.py:2470-2520`, SPEC-AI-083 인트라데이 재스캔 4개 + 기존 10:00 + 15:20). **하루 6회**
  — 탐지 경로에 종목당 네트워크 조회를 추가하는 배선은 이 예산을 최대 6배 곱한다.
- `_MAX_SCAN_UNIVERSE_FLOOR=50`, `_MAX_SCAN_UNIVERSE_CEILING=600` (`surge_detector.py:4454-4455`).
- Pool B 소싱 자체가 이미 `fetch_volume_leaders_sync(limit=140, max_pages=3)` + 종목당
  `fetch_stock_price_history_sync(pages=3)`를 수행한다(`:4630/:4658`) — 즉 `build_scan_universe`
  호출 자체도 무료가 아니며, 이미 이 비용을 매 스캔 사이클마다 지불하고 있다(SPEC-086 F-3
  "근사 0"이라는 서술은 상한 조정 비용에 한정된 것이며, Pool B 소싱 자체의 네트워크 비용과는
  별개임 — 본 SPEC에서 이 구분을 명확히 한다).

## 측정 가능성 검증 (REQ-001/002가 신규 스키마 없이 가능한가)

- `SurgeUniverseMember`(SPEC-AI-068, `app/models/surge_universe_member.py`)는 일자별
  `stock_code` + `entry_pool` 태그를 저장 — REQ-001의 유니버스측 데이터는 이미 존재.
- `FundSignal`(`signal_type`, `created_at`, `surge_metadata`)로 그날 어떤 탐지기가 어떤 종목에
  대해 시그널을 냈는지 복원 가능 — REQ-001의 탐지망측 데이터도 이미 존재.
- `SurgeActualOutcome`(`trading_date`, `stock_code`, `change_rate`)로 실제 급등 종목 판정 —
  REQ-002의 정답 데이터도 이미 존재.

세 테이블의 조인만으로 REQ-001/002 모두 신규 마이그레이션 없이 산출 가능하다고 판단한다(spec.md
Out of Scope 항목과 일치).

## 열린 질문 (M1에서 실측으로 해소, 본 SPEC 작성 시점에서는 답을 모름)

1. **카테고리 2(Pool A) 중복도**: 실제로 Pool A 코드 중 몇 %가 `disclosure_pattern`/
   `immediate_disclosure_signal`에 의해 이미 독립적으로 재발견되는가? 간극이 작다면 Pool A 배선의
   가치는 낮다.
2. **카테고리 4(Pool B) 중복도**: Pool B와 `volume_breakout`의 후보 집합이 실제로 얼마나 겹치는가
   (파라미터 차이 — 임계값 2.0배 vs `volume_breakout`의 자체 임계값, 조회 페이지 수 등)?
3. **69% 무시그널 종목의 실제 풀 귀속**: 이 종목들이 Pool A/B/C 어디에도 속하지 않았다면(소스
   부재형), 유니버스 배선 자체로는 해결되지 않고 SPEC-086 REQ-003(Pool D, 뉴스 언급 기반)의
   확장이 더 유효한 레버일 수 있다.
4. **옵션 A/B/C 중 어느 것이 M2에서 승인될지**: 이는 M1 측정 결과에 의존하며 사용자 결정이
   필요하다 — 본 문서는 답을 내리지 않는다.

## 참고 코드 위치 요약

| 대상 | 파일:라인 (2026-07-27 기준) |
|---|---|
| `build_scan_universe` | `surge_detector.py:4514-4883` |
| `gather_surge_candidates` (호출부 `:1934`) | `surge_detector.py:1830-2292` |
| `compute_ensemble_score` | `surge_detector.py:1533-1604` |
| `_detect_volume_anomaly_internal` | `surge_detector.py:2489-2644` |
| `detect_group_cascade_signals` | `surge_detector.py:3568-3812` |
| `detect_gap_up_runners` | `surge_detector.py:4005-4152` |
| `detect_volume_breakout` | `surge_detector.py:4225-4337` |
| `detect_bollinger_squeeze_signals` | `surge_detector.py:3926-4005` |
| `_MAX_SCAN_UNIVERSE_FLOOR/CEILING` | `surge_detector.py:4454-4455` |
| 스캔 스케줄(6회/일) | `scheduler.py:2470-2520` |
| gather 타임아웃 주석 | `scheduler.py:2500` |
| `SurgeDetectionConfig.max_scan_universe` 등 | `surge_config/surge_settings.py:527-563` |
| `VolumeAnomalyConfig.min_market_cap`/`null_cap_min_slots` | `surge_config/surge_settings.py:602-625` |
