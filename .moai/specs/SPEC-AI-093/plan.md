# SPEC-AI-093 Plan

## A. 구현 전략

본 SPEC은 Tier M으로 진행한다. 범위는 "라벨 수집 정확도" 한 축에 한정하며, 예측 로직·유니버스·탐지기
어느 것도 건드리지 않는다.

핵심 판단:

- 이 SPEC의 위험은 신규 기능이 아니라 **기존 지표의 조용한 이동**에 있다. 따라서 `change_rate` 산출
  경로와 `was_surge` 산출식을 물리적으로 무수정으로 유지하는 것이 최우선 제약이다.
- 고가 데이터는 이미 `PriceRecord.high`로 파싱되고 있으므로 파서 변경이 필요 없다. 필요한 것은
  호출과 계산, 그리고 실패 경로의 관측이다.
- 새 컬럼과 마이그레이션이 없다 — `high_change_rate`는 이미 존재하고, 고가 기반 판정은 파생값이다.
  SPEC-AI-073이 겪은 프로덕션 전용 마이그레이션 위험(락 데드락, `alembic_version` 길이 초과)에
  해당하지 않는다.

### A.5 PRESERVE 목록 (수정 금지)

| 대상 | 사유 |
|------|------|
| `naver_finance.py`의 `fetch_current_price_with_change` | `change_rate` 산출 경로 — D1에 의해 불변 |
| `naver_finance.py`의 `_parse_sise_day_html` / `PriceRecord` | 고가는 이미 파싱됨. 파서 변경 불필요 |
| `surge_actual_outcome_service.py`의 `was_surge` 산출식 | REQ-AI093-004 동결 |
| `surge_evaluation_service.py` 전체 | `was_surge` 소비자 — 무회귀 대상 |
| `surge_universe_gap_service.py` / `surge_auto_improver.py` | `was_surge` 소비자 — 무회귀 대상 |
| `surge_detector.py:3922` 주변 테마캐리 쿼리 | `was_surge` 소비자이자 탐지기 입력 — 절대 무수정 |
| `scheduler.py:952`, `:998` | `was_surge` 소비자 (텔레그램 알림) |
| `alembic/versions/058_surge_actual_outcome.py` | 기존 마이그레이션 — 신규 마이그레이션 없음 |

## B. 작업 분해

### TASK-001: 고가 기준 등락률 계산 헬퍼

- 대상: `backend/app/services/surge_actual_outcome_service.py` (신규 모듈 레벨 헬퍼)
- 순수 함수로 분리한다 — 입력은 `list[PriceRecord]` + `trading_date` + `prev_business_day` +
  `change_rate`, 출력은 `(high_change_rate | None, fallback_reason | None)`.
- `date` 매칭으로 T / T-1 레코드를 특정한다. 인덱스 접근 금지.
- Naver 일봉 날짜 형식(`YYYY.MM.DD`) 변환을 헬퍼 내부에서 수행한다.
- REQ-AI093-001 불변식(`high_change_rate >= change_rate`) 위반 시 `invariant_violation` 반환.
- 직전 영업일 산출은 기존 `surge_trading_service._get_prev_business_day`를 재사용한다
  (`collect_daily_surge_outcomes`가 이미 import하는 함수).

추적 REQ/AC:

- REQ-AI093-001, REQ-AI093-002
- AC-093-001, AC-093-002, AC-093-006

### TASK-002: 수집 배치에 고가 조회 배선

- 대상: `backend/app/services/surge_actual_outcome_service.py` — `collect_daily_surge_outcomes`
- 기존 `_fetch_with_semaphore` 팬아웃과 동일한 세마포어(`_PRICE_CONCURRENCY`) 아래에서
  `fetch_stock_price_history(code, pages=N)`를 조회한다.
- `pages` 값은 T와 T-1이 항상 포함되도록 실측으로 확정한다 (연휴 직후 고려 — Open Question 4).
- 개별 종목 고가 조회 실패는 해당 종목의 `high_change_rate`만 NULL로 만들고 배치를 중단하지 않는다.
- `"high_change_rate": None` 하드코딩(현재 `:174`)을 계산 결과로 교체한다.
- `change_rate` 대입부(`:172`)와 `was_surge` 대입부(`:173`)는 **문자 단위로 무수정**.

추적 REQ/AC:

- REQ-AI093-001, REQ-AI093-004
- AC-093-001, AC-093-004, AC-093-005

### TASK-003: fallback 사유별 로깅과 배치 요약

- 대상: `backend/app/services/surge_actual_outcome_service.py`
- 5개 사유 코드(`no_candle_t` / `no_candle_t1` / `invalid_high` / `invalid_prev_close` /
  `invariant_violation`)별 카운터를 배치 내에서 집계한다.
- 배치 종료 시 기존 `"SurgeActualOutcome upsert 완료: ..."` 로그 옆에 사유별 건수 + 비율 요약 로그를
  1건 추가한다.
- 로그 문구는 한국어(`code_comments: ko` 정책), 사유 코드는 영문 식별자.

추적 REQ/AC:

- REQ-AI093-003
- AC-093-003

### TASK-004: 고가 기반 파생 지표 + coverage guard

- 대상: `backend/app/services/surge_actual_outcome_service.py` 또는 평가 지표 계층 (구현 시 결정)
- 파생 판정: `COALESCE(high_change_rate, change_rate) >= 10.0`.
- 거래일별 coverage 계산: `high_change_rate IS NOT NULL` 비율.
- coverage < 임계값이면 반환 구조에 "부분 수집" 플래그를 부착한다.
- 임계값은 `surge_settings`에 노출하고 기본값을 명시한다 (초안 제안 0.90 — Open Question 1).
- **기존 `was_surge` 기반 지표는 그대로 두고 병렬로 추가**한다. 대체 금지.

추적 REQ/AC:

- REQ-AI093-005
- AC-093-007, AC-093-008

### TASK-005: 비용 계측

- 대상: `backend/app/services/surge_actual_outcome_service.py`
- 고가 조회 시도 수 / 캐시 적중 추정 수 / 실제 외부 호출 수를 배치 요약 로그에 포함한다.
- 기존 `_record_job_duration("surge_collect_outcomes", ...)` 경로는 그대로 유지한다.
- 목적은 spec.md D1의 "캐시 덕분에 증가분이 작을 것"이라는 **예상을 실측으로 대체**하는 것이다.

추적 REQ/AC:

- REQ-AI093-006
- AC-093-009

### TASK-006: 무회귀 검증

- 대상: `backend/tests/test_surge_actual_outcome_service.py` (기존 파일 확장)
- 기존 테스트 14개(그중 10개가 `collect_daily_surge_outcomes`를 직접 호출, 3개는 `was_surge`
  임계값 테스트, 1개는 `_fetch_tracked_stock_codes` 단위 테스트)가 무수정으로 통과하는지 확인한다.
  고가 조회가 추가되므로 `collect_daily_surge_outcomes` 호출 테스트 10개는 mock 범위 확장이 필요할
  수 있다 — 그 경우 **기존 단언은 유지한 채 mock만 확장**한다.
- `was_surge` 소비자 5개 서비스의 기존 테스트를 회귀 대상으로 실행한다.

추적 REQ/AC:

- REQ-AI093-004
- AC-093-004, AC-093-010

## C. 검증 계획

타겟 테스트:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_surge_actual_outcome_service.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_surge_evaluation_service.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_090.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_089.py -q
```

전체 회귀:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q -m "not slow"
```

정적 검사:

```powershell
.\backend\.venv\Scripts\ruff.exe check .\backend
.\backend\.venv\Scripts\python.exe -m mypy .\backend\app
```

임포트 sanity:

```powershell
cd backend; uv run python -c "from app.main import app; print('OK')"
```

> CI 주의: `pytest-xdist -n 4` 환경에서만 재현되는 레이스 사례가 과거에 있었다(2026-07-03).
> 배치 카운터를 모듈 전역이 아닌 함수 지역 상태로 유지하면 해당 위험을 회피한다.

## D. 배포/롤백

본 SPEC은 feature flag 없이 배포 가능하다 — `high_change_rate`는 현재 무조건 NULL이므로, 값이
채워지는 것은 **기존 소비자에게 관측되지 않는 순수 추가**다 (어떤 코드도 이 컬럼을 읽지 않는다).

다만 다음 중 하나가 발생하면 TASK-002 배선을 되돌린다.

- `surge_collect_outcomes` 잡 소요 시간이 기존 대비 50% 이상 증가
- 기존 `was_surge` 일별 건수가 배포 전후로 변동 (REQ-AI093-004 위반 신호)
- fallback 비율이 50%를 초과 (일봉 미게시 등 데이터 가용성 문제 — 잡 실행 시각 재검토 필요)
- 외부 호출 실패로 배치가 완주하지 못함

롤백 단위: TASK-002의 배선만 되돌리면 `high_change_rate`가 다시 NULL로 돌아가며 나머지 지표는
영향받지 않는다.

## E. 리스크

- **일봉 미게시**: 16:10 KST에 당일 일봉이 아직 게시되지 않으면 `no_candle_t` fallback이 대량
  발생한다. REQ-AI093-003의 계측이 이를 즉시 드러내며, 대응은 잡 시각 조정(별도 판단)이다.
- **호출량 증가**: 종목당 최대 +1 호출. 캐시 적중률이 예상보다 낮으면 배치 시간이 늘어난다.
  TASK-005의 실측이 판단 근거가 된다.
- **연휴 경계**: `pages=1`이 T-1을 포함하지 못하는 경우 `no_candle_t1`이 발생한다. TASK-002에서
  `pages` 값을 보수적으로 확정해 완화한다.
- **coverage 오독**: 부분 수집된 초기 며칠의 고가 기반 recall이 실제보다 낮게 보일 수 있다.
  REQ-AI093-005의 guard가 이를 방어하나, 운영자가 플래그를 무시하면 여전히 오독 가능하다.
- **백필 부재의 대가**: 배포 이후 표본이 쌓이기 전까지 "종가 기준 라벨 대비 고가 기준 라벨이 얼마나
  다른가"를 정량 비교할 수 없다. 이는 D3에서 의도적으로 수용한 트레이드오프다.
