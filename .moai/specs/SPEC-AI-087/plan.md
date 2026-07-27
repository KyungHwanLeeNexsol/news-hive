# SPEC-AI-087 구현 계획

## 접근 개요

행동보존(behavior-preserving) 원칙의 데이터 완전성 확장. DDD ANALYZE-PRESERVE-IMPROVE +
Reproduction-First(특성화 테스트 선행). 세 근본원인(시총 업데이트 페이지 상한 / 3개 탐지기 NULL 시총
하드 필터 / 키워드 백필 미스케줄링)에 대해 각각 독립적으로 안전하게 개입하며, 탐지기 본체·앙상블·매매
로직은 diff 0을 유지한다.

## 신규 설정 필드 설계 결정 (결정 가역성 우선 검토 — 가장 변경 가능성 높은 결정)

세 탐지기 경로의 후보 쿼리 구조가 서로 다르므로(무제한 조회 vs 이미 상한이 걸린 소규모 조회, 네트워크
fetch 유무), SPEC-AI-077의 `null_cap_min_slots`(int, floor-quota+로테이션) 패턴을 기계적으로 3곳에
동일 복제하지 않고 경로별로 다르게 설계했다. 이 설계 선택이 본 SPEC에서 가장 변경 가능성이 높은 결정이므로
구현에 앞서 명시한다.

| 경로 | 기존 후보풀 규모/상한 | 네트워크 fetch | NULL 편입 메커니즘 | 신규 필드 |
|------|----------------------|----------------|---------------------|-----------|
| **volume_anomaly** | 무제한(상한 없음, `Stock.market_cap >= min_market_cap` 조회 후 전량 순회) | 종목당 1회 (`fetch_stock_price_history_sync`) | **floor-quota + 날짜 로테이션**(SPEC-AI-077 패턴 이식) — 신규 fetch 비용을 명시적으로 상한 | `VolumeAnomalyConfig.null_cap_min_slots: int = 0` |
| **group_cascade** | 계열사 접두사 매칭(소규모) + `max_cascade_per_flagship`(기본 3) 상한 | 없음(순수 DB/인메모리, 검증됨) | **boolean 토글**(비용 0, 굶주림 위험 낮음) | `GroupCascadeConfig.cascade_include_null_market_cap: bool = False` |
| **gap_up_runners** | 섹터 피어 `.limit(5)` + 런너 `[:2]` 슬라이스 | `[:2]`로 이미 상한(검증됨) | **boolean 토글**(비용 0) | `GapUpRunnersConfig.runner_include_null_market_cap: bool = False` |

**결정 근거**: floor-quota+로테이션은 "많은 후보가 적은 슬롯을 두고 경쟁하며 non-null이 null을
구조적으로 밀어내는" 문제를 푸는 메커니즘이다(SPEC-AI-077의 원 문제). cascade/gap_up_runners는 후보풀
자체가 이미 작고 상한이 걸려 있어 이 경쟁 문제가 near_limit_up만큼 심각하지 않으므로, 단순화 사다리
(Enforce Simplicity)에 따라 boolean 토글로 충분하다고 판단했다. 세 경로 모두 기본값은 기존 거동과
바이트 동등(REQ-008).

## 세 근본원인 대응 요약

| 근본원인 | 대상 REQ | 실제 효과 | 비용 | 권고 |
|----------|----------|-----------|------|------|
| ① 시총 업데이트 500종목 상한 | REQ-001/002 | 커버리지 964→최대 2,605건까지 확대 가능(Naver API 자체 제한 없음, 확인됨) | 배포당 Naver fetch 페이지 수 증가(시장당 최대 10→60페이지, 안전 상한) | 기계적 저위험 변경 — 우선 적용 |
| ② 3개 탐지기 NULL 시총 하드 배제 | REQ-003~006 | volume_anomaly/cascade/gap_up_runners가 NULL 시총 종목을 후보로 고려 가능(opt-in) | volume_anomaly만 신규 fetch 비용(floor-quota로 상한); 나머지 2곳은 비용 0 | REQ-003~005 opt-in, REQ-006 경계 고정 |
| ③ 키워드 백필 미스케줄링 | REQ-007/008 | `keywords` NULL 종목(75.1%)이 정기적으로 태깅 시도됨 → SPEC-AI-084 뉴스기반 테마전파 입력 완전성 개선(084는 여전히 플래그 OFF, 별개 논의) | 외부 API/LLM 호출 없음(기존 저장 레코드만 읽음), 저비용 | 낮은 위험 — 신규 잡 등록만 |

## 마일스톤 (우선순위 기반, 시간 추정 없음 — 결정 가역성 순서로 배열: 신규 설정면 설계 → 기계적 변경 → 검증)

- **M1 (P0)**: 특성화 테스트 선행 — 5개 대상 지점(volume_anomaly 후보 쿼리, group_cascade 계열사
  필터 + flagship 배제, gap_up_runners 섹터 피어 필터, bollinger_squeeze 상위 N 쿼리, 시총 업데이트
  페이지 루프)의 현재 출력을 고정. NULL 시총 종목이 각 경로에서 배제됨을 RED로 재현.
- **M2 (P0, 신규 설정면 — 가장 변경 가능성 높은 결정)**: REQ-003(volume_anomaly floor-quota) +
  REQ-004/005(cascade/gap_up_runners boolean 토글) 구현. 기본값 OFF 검증(REQ-008 일부).
- **M3 (P0, 기계적 변경)**: REQ-001/002 시총 업데이트 페이지 상한 확장 + 안전 상한 상수 도입 +
  백워드 호환(기존 top-500 값 불변) 검증.
- **M4 (P0, 경계 검증)**: REQ-006 회귀 assert — flagship 배제 로직(AC-007) 및 bollinger_squeeze
  상위 N 쿼리가 M2 적용 후에도 무변경임을 고정.
- **M5 (P1, 기계적 변경)**: REQ-007 키워드 백필 스케줄러 등록(`register_jobs()`).
- **M6 (P0, 최종 검증)**: REQ-008 전체 백워드 호환 검증 + 전체 스위트 무회귀 확인 + lint/mypy.

## 기술적 접근

- **REQ-001**: `_update_market_caps()`(`scheduler.py:423`)의 `for page in range(1, 11):`를
  안전 상한 상수(예: `_MARKET_CAP_UPDATE_MAX_PAGES = 60`, 시장당)로 교체한다. 기존
  `if not items: break`(`:437-438`) 자연 종료 로직은 그대로 유지 — 안전 상한은 API 이상 동작(무한
  페이지네이션 등) 방어선일 뿐, 정상 경로에서는 KOSPI(~50페이지)/KOSDAQ(~37페이지) 도달 전에 자연
  종료된다(이번 세션 실측 `totalCount` 기준 추정치). `Stock.stock_code.in_(cap_map.keys())`
  (`:449`) 배치 갱신 경계는 무변경.
- **REQ-003**: `_detect_volume_anomaly_internal`(`surge_detector.py:2489`)의 후보 조회를
  SPEC-AI-077 패턴(`:2704-2769` 참고)과 동일 구조로 분리한다 — non-null 쿼리(기존
  `market_cap >= min_market_cap`, 무제한 유지) + NULL 전용 쿼리(`Stock.market_cap.is_(None)`,
  `order_by(Stock.id.asc())`, 날짜 서수 기반 `offset`, `limit(null_cap_min_slots)`, wrap-around
  포함). `null_cap_min_slots=0`이면 NULL 쿼리 자체를 스킵(레거시 완전 동일).
- **REQ-004**: `detect_group_cascade_signals`(`:3529`)의 계열사 후보 필터(`:3630-3639`)를
  `cascade_include_null_market_cap=True`일 때 `or_(Stock.market_cap >= config.cascade_min_market_cap,
  Stock.market_cap.is_(None))` + `order_by(Stock.market_cap.desc().nullslast())`로 교체한다(기존
  `max_cascade_per_flagship` LIMIT 불변). Flagship 판정 블록(`:3598-3619`)은 건드리지 않는다.
- **REQ-005**: `detect_gap_up_runners`(`:3945`)의 섹터 피어 필터(`:4006-4014`)를
  `runner_include_null_market_cap=True`일 때 `Stock.market_cap.isnot(None)` 조건을 제거하고
  `order_by(Stock.market_cap.desc().nullslast())`로 교체한다(기존 `.limit(5)`, `[:2]` 불변).
- **REQ-006**: 회귀 테스트로 (a) flagship 배제(`:3598-3600, 3609, 3613`) 무변경, (b)
  `detect_bollinger_squeeze`(`:3894-3900`) 무변경을 고정한다. 코드 수정 없음 — 테스트만 추가.
- **REQ-007**: `keyword_tagging_service.backfill_stock_keywords`를 `scheduler.py`
  `register_jobs()`에 `_update_market_caps`와 동일한 `scheduler.add_job(..., "interval", ...)`
  패턴으로 등록한다(주기는 시총 업데이트보다 낮은 빈도로 설정 — 예: 1일 1회, 외부 API 호출이 없어
  DART/네이버 rate limit과 무관).

## 리스크

- **R-1 (volume_anomaly 신규 fetch 비용)**: `null_cap_min_slots` 활성화 시 종목당 1회
  `fetch_stock_price_history_sync` 호출이 추가된다. → 기본값 0(OFF)로 배포, 활성화 시 소규모
  값(예: 50~100)부터 관찰.
- **R-2 (cascade/gap_up_runners 신규 시그널 볼륨)**: NULL 시총 편입 시 이전에 생성되지 않던
  `FundSignal` 행이 생성될 수 있다(계산 비용은 0이지만 시그널 볼륨은 증가). → 두 필드 모두 기본
  OFF, opt-in.
- **R-3 (시총 업데이트 배포당 페이지 수 증가)**: 안전 상한 60페이지×2시장=최대 120회 Naver 호출
  (기존 20회 대비 증가). → `MARKET_CAP_UPDATE_HOURS` 주기 자체는 무변경(기존 설정 간격 유지),
  1회 실행 소요시간만 증가(재시도 데코레이터 `retry_with_backoff(max_attempts=3)` 기존 유지).
- **R-4 (라인 인용 오류로 인한 오적용 위험)**: Context 절에서 정정한 대로, 사전 조사 메모의
  "3894-3898" 인용은 실제로 `detect_bollinger_squeeze`였다. → REQ-006에서 두 경계(flagship,
  bollinger_squeeze)를 명시적으로 고정해 M4에서 회귀 assert로 재확인한다.

## 변경 예상 파일

`backend/app/services/scheduler.py`(REQ-001/007), `backend/app/services/surge_detector.py`
(REQ-003/004/005/006 — `_detect_volume_anomaly_internal`, `detect_group_cascade_signals`,
`detect_gap_up_runners`), `backend/app/surge_config/surge_settings.py`(신규 설정 필드 3개),
`backend/tests/test_spec_ai_087.py`(신규 — 특성화 + 회귀 테스트). `surge_detection.yaml` 신규 키는
불필요(모든 필드가 Pydantic 기본값으로 backward-compat 충족, near_limit_up의
`NearLimitUpConfig.null_cap_min_slots`가 이미 이 패턴을 사용 중 — `surge_settings.py:637-638` 주석
"yaml 비구동" 참고). **마이그레이션 없음.**
