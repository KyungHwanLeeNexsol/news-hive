# SPEC-AI-076 Implementation Plan — 스캔 유니버스 풀 절단 크라우딩아웃 교정

개발 방식: **DDD (ANALYZE → PRESERVE → IMPROVE)** — `.moai/config/sections/quality.yaml` `development_mode: ddd`.
`/moai run SPEC-AI-076`는 manager-ddd가 characterization test 선행으로 수행.

## 기술 접근 (Technical Approach)

### 핵심 변경: 배분 메커니즘 교체 (`build_scan_universe` `:4288-4303`)

AS-IS(엄격 concat-then-slice):
```
universe_ordered = pool_a + pool_b + pool_c + existing
final_universe   = dedup(universe_ordered)[:max_universe]
```

TO-BE(풀별 최소 슬롯 예약 quota + 우선순위 잔여):
1. `reserved_b = min(len(pool_b_codes), cfg.pool_b_min_slots)`
   `reserved_c = min(len(pool_c_codes), cfg.pool_c_min_slots)`
2. `sum_reserved = reserved_b + reserved_c`; `sum_reserved > max_universe`면 비율 축소 + 경고 로그(REQ-007).
3. 예약분 확보: `pool_b_codes[:reserved_b]`, `pool_c_codes[:reserved_c]`.
4. `remaining = max_universe - sum_reserved`; 잔여를 A > B(나머지) > C(나머지) > existing 순으로 채움.
5. 전체를 dedup(순서 보존)하고 `[:max_universe]`로 최종 안전 절단(항상 <= cap 보장).

**백워드 호환**: `pool_b_min_slots==0 and pool_c_min_slots==0`이면 1~4가 엄격 concat-then-slice와 동일 결과
(reserved 0 → 전부 우선순위 잔여로 감). REQ-004 회귀 탈출구.

**Pool A**: floor 불필요(우선순위 1, 잔여에서 최우선 충당). 굶주림 대상은 B/C뿐.

### 관측성 (REQ-005) — 스키마 0

- `final_universe` 확정 후 `entry_pool_map`으로 풀별 실제 스캔 수 집계:
  `scanned = Counter(entry_pool_map[c] for c in final_universe)`.
- 반환 `pool_counts`에 신규 키 추가: `pool_a_scanned`/`pool_b_scanned`/`pool_c_scanned`(+ 원한다면
  `existing_scanned`). **기존 `pool_a`/`pool_b`/`pool_c`(raw) 키는 그대로 유지**.
- 최종 로그(`:4304-4312`)에 raw 대비 scanned를 함께 출력(굶주림 발생 시 눈에 보이게).
- `persist_pool_counts` 호출부(`surge_detector.py:1953-1962`)는 **기존 raw 키만** 계속 전달 →
  `SurgeUniversePoolHistory` 쓰기 의미 불변(REQ-005 [HARD]). scanned 키는 로깅·테스트 전용.

### 설정 (REQ-007)

- `SurgeDetectionConfig`(`app/surge_config/surge_settings.py`)에 `pool_b_min_slots: int = 20`,
  `pool_c_min_slots: int = 30` 필드 추가(Pydantic 기본값). 값 검증은 배분 시점 clamp로 처리(모델 검증은 개별
  필드 범위만).
- `surge_detection.yaml` scan_universe 관련 섹션에 두 키 추가(기존 `max_scan_universe` 인접). `auto.yaml`
  자동개선 대상 아님(배분 정책은 자가개선 루프가 건드리지 않음).

## 변경 파일 (파일 단위 분해)

| # | 파일 | 변경 | 비고 |
|---|------|------|------|
| 1 | `backend/app/services/surge_detector.py` | `build_scan_universe` 배분 로직(`:4288-4303`) quota화 + scanned 카운트 반환/로깅 + `:4183`/`:4217` 불변 주석 갱신 + `@MX:ANCHOR/NOTE` | 핵심 |
| 2 | `backend/app/surge_config/surge_settings.py` | `SurgeDetectionConfig`에 `pool_b_min_slots`/`pool_c_min_slots` 필드 | 설정 |
| 3 | `backend/app/surge_config/surge_detection.yaml` | 두 floor 키 추가 | 설정 |
| 4 | `backend/app/models/surge_universe_pool_history.py` | `pool_a/b/c_count` = pre-truncation 의미 주석 명확화(선택, 컬럼/스키마 불변) | 문서성 |
| 5 | `backend/tests/test_spec_ai_065.py` | quota 배분 characterization 테스트 추가(재현 우선) | 테스트 |

**주의**: 파일 5개지만 실질 로직 변경은 #1 한 곳에 집중. #2/#3은 설정 추가, #4는 주석, #5는 테스트. Multi-File
Decomposition(3+) 규칙에 따라 #1 → #2/#3(설정) → #5(테스트) → #4(주석) 순으로 논리 단위 진행.

## DDD 사이클

**ANALYZE**: `build_scan_universe` 배분/반환 계약, fan_in 3 호출부(특히 `:1953` persist 경로), `pool_counts`
소비처(`evaluate_surge_predictions`, `get_pool_counts_for_date`), `SurgeUniverseMember` entry_pool 영속 확인.
기존 065/074 테스트가 고정한 거동 파악.

**PRESERVE**: 재현 우선(REQ-006) — 07-08형 시나리오(A=232 mock, B=0, C=52, cap=150)에서 현행 Pool C 대표=0을
포착하는 실패 characterization 작성·확인. 기존 065/074/유니버스 테스트로 배분·소싱·영속 거동 스냅샷.

**IMPROVE**: 배분 로직 quota화(#1) → 실패 테스트 통과 확인 → 설정 필드(#2/#3) → scanned 관측성 → floors=0
레거시 동등성 테스트 → 전체 스위트(`-n 4`) 회귀 확인.

## 마일스톤 (우선순위 기반, 시간 추정 없음)

- **M1 (P0)**: quota 배분 메커니즘 + 비굶주림 보장 + 비용 상한 보존(REQ-001/002/003) + 재현 우선 실패 테스트
  선행(REQ-006). 07-08형 replay에서 Pool C >= floor 통과.
- **M2 (P0)**: 레거시 동등성 — 절단 압력 없음 시 전 후보 포함, floors=0 시 엄격 슬라이스와 동일(REQ-004).
- **M3 (P1)**: 설정 floor + 안전 clamp(REQ-007), scanned 관측성 반환/로깅(REQ-005), 불변 주석 갱신 + MX 태그.

## 리스크 및 완화

- **R1 순서 변경으로 인한 다운스트림 영향**: 예약분이 앞당겨져 `final_universe` 순서가 달라질 수 있음. 완화 —
  다운스트림은 유니버스를 **집합**으로 소비(entry_pool_map=dict, persist_universe_members=code dedup). 절단
  압력 없을 때 **집합 동등성**을 REQ-004로 명시 검증.
- **R2 raw 카운트 의미 오염 회귀**: scanned를 실수로 `persist_pool_counts`에 전달하면 이력 테이블/평가가 깨짐.
  완화 — REQ-005 [HARD]로 raw 키만 persist, scanned는 신규 키로 분리. 테스트로 persist 인자 고정.
- **R3 floor 오설정으로 Pool A 과다 압박**: `sum(floors)`가 크면 A 잔여 축소. 완화 — REQ-007 clamp + 작은
  기본값(20/30, 합 50 << 150) + Run 단계 라이브 튜닝.
- **R4 프로덕션 전용 위험**: 순수 in-memory 배분 로직 + 설정 추가라 SPEC-AI-073류 프로덕션 전용 위험(락
  데드락, VARCHAR 초과)은 해당 없음. 마이그레이션 없음.

## 검증

```
cd backend && uv run pytest tests/test_spec_ai_065.py tests/test_spec_ai_074.py \
  tests/test_surge_universe_members.py tests/test_surge_universe_pool_bugfix.py --tb=short -q
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"   # 전체(개발)
cd backend && uv run pytest tests/ --tb=short -q -n 4            # xdist 회귀 확인(커밋 전)
cd backend && uv run ruff check . && uv run mypy app/
```
