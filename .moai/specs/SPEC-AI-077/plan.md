# SPEC-AI-077 Implementation Plan — near_limit_up NULL 시총 굶주림 교정

개발 방식: **DDD (ANALYZE → PRESERVE → IMPROVE)** — `.moai/config/sections/quality.yaml` `development_mode: ddd`.
`/moai run SPEC-AI-077`은 manager-ddd가 characterization test 선행으로 수행.

## 기술 접근 (Technical Approach)

### 핵심 변경: 후보 쿼리 분리 + NULL floor quota + 날짜 로테이션 (`detect_near_limit_up_carries` `:2705-2716`)

AS-IS(단일 nullslast 쿼리):
```python
candidates = (
    db.query(Stock)
    .filter(or_(Stock.market_cap.is_(None), Stock.market_cap >= config.min_market_cap_eok))
    .order_by(nullslast(Stock.market_cap.desc()))
    .limit(config.max_stocks_to_check)   # non-null 전부 먼저 → NULL 굶주림
    .all()
)
```

TO-BE(non-null 우선 쿼리 + NULL floor quota 쿼리, 날짜 로테이션):
1. `null_count = db.query(func.count(Stock.id)).filter(Stock.market_cap.is_(None)).scalar()` (값싼 COUNT).
2. `reserved_null = min(null_count, cfg.null_cap_min_slots)`; `reserved_null > max_stocks`면 clamp + 경고(REQ-006).
3. `non_null_limit = max_stocks_to_check − reserved_null`.
4. non-null 쿼리: `filter(market_cap >= min_market_cap_eok).order_by(market_cap.desc()).limit(non_null_limit)` → `nn`.
5. `null_limit = max_stocks_to_check − len(nn)` (미달 non-null 슬롯을 NULL에 환원; 항상 >= `reserved_null`).
6. `rot_offset` = 스캔 날짜 유도 결정적 offset(무상태); NULL 쿼리:
   `filter(market_cap IS NULL).order_by(<안정키: Stock.id 또는 stock_code>).limit(null_limit).offset(rot_offset)`.
   `null_count`보다 offset이 크면 wrap-around(모듈러) — `us_news.py` 라운드로빈과 동형.
7. `candidates = nn + null_rows` (필요 시 dedup; 두 쿼리는 상호배타적 필터라 원천 중복 없음). 총 <= `max_stocks_to_check`.

**백워드 호환**: `null_cap_min_slots == 0` → `reserved_null=0`, `non_null_limit=max_stocks` → non-null이 우선
전량, 남은 슬롯을 NULL이 채움 = 레거시 nullslast **집합**과 동일(REQ-005 탈출구). 로테이션도 이 경우 무효화 옵션 고려.

**로테이션 offset 유도(권장, 무상태·결정적)**: `rot_offset = (scan_date.toordinal() * null_limit) % max(null_count, 1)`.
- 날짜별로 offset이 `null_limit`씩 전진 → `ceil(null_count / null_limit)` 스캔일 내 전 NULL 커버(라운드로빈).
- 스캔 날짜는 함수 내 이미 계산되는 `today_kst_start.date()`(`:2681-2683`) 재사용 → 테스트에서 시간 mock으로 재현.
- `null_limit`이 날마다 달라질 수 있으나(non-null 수 변동) even-coverage 근사는 유지. 정확 재현이 필요하면 offset을
  `null_cap_min_slots` 기준으로 고정하는 변형도 가능(Run 판단).

**대안(고려·비권장)**: (a) `func.random()` NULL 정렬 — 매 실행 다른 서브셋이나 커버리지 보장 없음 + 테스트
비결정성; (b) `us_news.py`식 모듈 전역 커서 — 재배포 시 0 리셋되어 head 재굶주림. → 날짜 유도 offset이 무상태·
결정적·재배포 무관으로 우세.

### 설정 (REQ-006) — yaml 비구동 [핵심]

- `NearLimitUpConfig`(`surge_settings.py:557-571`)에 `null_cap_min_slots: int = 300` 필드 추가(Pydantic 기본값).
- **[HARD] `surge_detection.yaml` 무변경.** `NearLimitUpConfig()`는 `fund_manager.py:3919`에서 bare 생성 →
  yaml 키는 소비되지 않는 dead config. AI-076과 정반대(AI-076은 `SurgeDetectionConfig` yaml 구동이라 yaml 추가함).
- 값 검증: 배분 시점 clamp(`null_cap_min_slots > max_stocks_to_check`면 축소 + 경고). 모델 검증은 개별 필드 범위만.
- 명명: `SurgeDetectionConfig`의 `pool_b_min_slots`/`pool_c_min_slots`(:495/:499) 관례 계승 → `null_cap_min_slots`.

### 관측성 (REQ-008) — 스키마 0

- 후보 확정 후 `[near_limit_up]` 로그에 `non_null=len(nn)`, `null=len(null_rows)`, `rot_offset`, `총=len(candidates)`
  출력(기존 `:2775-2778` 완료 로그 인접 또는 후보 확정 직후). 신규 테이블/컬럼 없음.

## 변경 파일 (파일 단위 분해)

| # | 파일 | 변경 | 비고 |
|---|------|------|------|
| 1 | `backend/app/services/surge_detector.py` | 후보 쿼리(`:2705-2716`) 분리+floor quota+로테이션, non-null/NULL 평가 수+offset 로깅, `:2701-2704` 증상-처치 주석 갱신 + `@MX:ANCHOR/NOTE` | 핵심 |
| 2 | `backend/app/surge_config/surge_settings.py` | `NearLimitUpConfig`에 `null_cap_min_slots: int = 300` 필드 | 설정(yaml 아님) |
| 3 | `backend/tests/test_near_limit_up_carry.py` | 굶주림 재현 characterization + floor/로테이션/레거시 동등성 테스트(재현 우선) | 테스트 |

**주의**: 실질 로직 변경은 #1 한 곳. #2는 기본값 필드 추가(yaml 배선 없음), #3은 테스트. `surge_detection.yaml`은
**변경 대상 아님**(Exclusion 3). Multi-File Decomposition: #1 → #2(설정) → #3(테스트) 순으로 논리 단위 진행.

## DDD 사이클

**ANALYZE**: `detect_near_limit_up_carries` 후보 쿼리·루프·metadata 생성 계약, 호출부(`fund_manager.py:3919` bare
생성 → yaml 비구동 확정), `max_signals_per_day=None`이 루프를 truncate하지 않음 확인(연구 §4), `min_market_cap_eok`
필터 의미. 기존 테스트(AC-001~015/072/EC)가 고정한 거동 파악.

**PRESERVE**: 재현 우선(REQ-007) — 굶주림 시나리오(`max_stocks_to_check=3`, non-null 3 + NULL 2, 모두 near-limit-up
mock)에서 현행 NULL 후보 도달=0(NULL 종목 code로 `fetch_stock_price_history_sync` 미호출)을 포착하는 실패 테스트
작성·확인. 기존 AC/EC로 임계·공식·소형주 배제·metadata 스냅샷.

**IMPROVE**: 후보 쿼리 분리+floor quota+로테이션(#1) → 실패 테스트 통과 확인 → 설정 필드(#2) → 로테이션/레거시
동등성/관측성 테스트 → 전체 스위트(`-n 4`) 회귀 확인.

## 마일스톤 (우선순위 기반, 시간 추정 없음)

- **M1 (P0)**: 후보 쿼리 분리 + NULL floor quota + 비용 상한 보존(REQ-001/002/003) + 재현 우선 실패 테스트 선행
  (REQ-007). 라이브형 replay에서 NULL 후보 >= floor 통과.
- **M2 (P0)**: 날짜 로테이션(REQ-004) — 날짜별 다른 NULL 서브셋, 시간 커버리지. 레거시 동등성(REQ-005) — 절단 압력
  없음 시 전 후보 포함, `null_cap_min_slots=0` 시 레거시 집합 동일.
- **M3 (P1)**: 설정 필드 + clamp(REQ-006, yaml 아님), 관측성 로깅(REQ-008), 증상-처치 주석 갱신 + MX 태그.

## 리스크 및 완화

- **R1 로테이션 결정성 vs 커버리지**: 날짜 유도 offset은 `null_limit` 변동 시 정확 라운드로빈이 깨질 수 있음. 완화 —
  REQ-004는 "유계 스캔일 내 전 NULL 1회 이상"의 근사 보장만 요구; 정확 재현이 필요한 테스트는 시간 mock + 고정
  `null_cap_min_slots`로 offset 결정.
- **R2 non-null 드롭(floor가 non-null 압박)**: `null_cap_min_slots`가 크면 `non_null_limit`가 줄어 최소 시총 non-null
  일부 배제. 완화 — 현행 도달 NULL(243)보다 약간 큰 기본값(300)으로 시작, `sum` clamp + Run 라이브 튜닝. non-null이
  cap 미만인 동안(957<1200)은 실질 드롭 없음(non-null 957 < non_null_limit 900? → 이 경우 57 드롭 가능 → Run에서
  floor 값으로 조절; 300이면 non_null_limit=900<957이라 57 드롭. floor 200이면 1000>957 무드롭). Run에서 결정.
- **R3 yaml 오배선**: floor를 실수로 yaml에 넣으면 dead config(소비 안 됨). 완화 — REQ-006 [HARD] + Exclusion 3로
  yaml 무변경 명시. 코드 리뷰로 `surge_detection.yaml` diff 0 확인.
- **R4 프로덕션 전용 위험**: 순수 in-memory 쿼리 분리 + Pydantic 기본값 + 로깅이라 SPEC-AI-073류 프로덕션 전용
  위험(락 데드락, VARCHAR 초과) 해당 없음. 마이그레이션·yaml 변경 없음.

## 검증

```
cd backend && uv run pytest tests/test_near_limit_up_carry.py --tb=short -q
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"   # 전체(개발)
cd backend && uv run pytest tests/ --tb=short -q -n 4            # xdist 회귀 확인(커밋 전)
cd backend && uv run ruff check . && uv run mypy app/
```
