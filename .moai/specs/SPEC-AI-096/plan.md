# SPEC-AI-096 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `quality.yaml` `constitution.development_mode:
ddd`). 4개 축(캡 상향/절단 면제/Pool D 관측/bridge 관측)을 각각 독립적으로 검증 가능한
Milestone으로 나누되, **데이터 모델 변경(Pool D 컬럼 추가)이 가장 되돌리기 어려운 결정이므로
M1로 가장 먼저 다룬다** — 계산 로직·설정값·문서화는 이후 얼마든지 조정 가능하지만, 마이그레이션이
배포된 뒤에는 컬럼 스키마를 되돌리는 비용이 더 크다. 그다음으로 **프로덕션 즉시 관측 가능한
동작을 바꾸는 결정**(캡 150→250, REQ-AI096-001)을 M2로 배치한다 — 이는 플래그 뒤에 있지 않아
배포 즉시 평가지표 분모에 영향을 준다는 점에서 Pool D/bridge의 "기본값 유지" 결정보다 리스크가
높다. 절단 면제 정책(M3)과 활성화 기준 문서화(M4)는 상대적으로 기계적/문서 작업이므로 뒤에
배치한다.

핵심 판단:

- 이 SPEC의 진짜 위험은 새 로직 버그가 아니라 **"관측 배선"과 "실제 활성화"를 혼동하는 것**이다.
  Pool D/bridge 관련 모든 TASK는 명시적으로 "값 자체는 바꾸지 않는다"를 완료 조건에 포함한다.
- Pool D 컬럼 추가는 SPEC-AI-068/095가 확립한 "nullable 신규 컬럼, 백필 없음, 기존 컬럼
  무수정" 패턴을 그대로 재사용한다 — 새 패턴을 발명하지 않는다.
- 절단 면제(M3)는 `entry_pool` 필드가 이미 절단 블록 이전에 채워져 있다는 사실(research.md
  §C.3)에 의존한다 — 코드 재배치나 파이프라인 순서 변경이 필요 없다.

### A.5 PRESERVE 목록 (수정 금지)

| 대상 | 사유 |
|------|------|
| `build_scan_universe()`의 quota 배분 로직(`reserved_b/c/d`, A>B>C>D>existing 우선순위) | SPEC-AI-076/086 소유 — 배분 알고리즘 자체는 REQ-AI096 범위 밖 |
| `_clamp_scan_universe_cap()` / `_resolve_scan_universe_cap()` 로직 | SPEC-AI-086 소유 — clamp 경계값/동적 시간대 상한 로직 무수정, 값만 통과 |
| `pool_d_min_slots`(0) / `scan_universe_bridge_candidates_enabled`(False) 실제 값 | §Out of Scope — 이 SPEC은 활성화하지 않는다 |
| `existing_codes` 병합 필터(`scan_universe_include_existing`, SPEC-AI-094) | 완전히 무관 — 재론하지 않음 |
| `generate_scan_universe_bridge_candidates()` 내부 로직 | SPEC-AI-092 소유 — attribution 재사용만 하고 함수 자체는 무수정 |
| 7개 핵심 탐지기(theme_cluster, volume_news_combo, disclosure_pattern, news_delayed, volume_breakout, momentum_continuation, immediate_disclosure) | 완전히 무관 |
| `_pre_score()` 가중합 산출식 자체 | REQ-AI096-005는 절단 **대상 집합**만 바꾼다 — 점수 산출식은 무변경 |
| `evaluate_surge_predictions()`의 pool_counts 소비 로직 | REQ-AI096-002는 저장/조회 계층만 확장 — 평가 함수 자체는 무수정 |

## B. 작업 분해

### M1: `SurgeUniversePoolHistory.pool_d_count` 마이그레이션 + 영속화 배선

- 대상: 신규 `backend/alembic/versions/071_surge_universe_pool_history_pool_d.py`
  (down_revision = `"070_surge_pred_eval_high_based"`),
  `backend/app/models/surge_universe_pool_history.py`,
  `backend/app/services/surge_universe_pool_service.py`(`persist_pool_counts`,
  `get_pool_counts_for_date`), `backend/app/services/surge_detector.py`
  (`:1961-1970` 호출부 dict에 `"pool_d"` 키 추가).
- `pool_d_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)` —
  기존 3개 컬럼과 동일 타입/제약(§Decisions D5).
- 백필 없음(기존 행은 0).

추적 REQ/AC: REQ-AI096-002 / AC-096-001, AC-096-002

### M2: `max_scan_universe` 기본값 150→250

- 대상: `backend/app/surge_config/surge_settings.py`(`SurgeDetectionConfig.max_scan_universe`
  필드 기본값), `backend/app/surge_config/surge_detection.yaml`(`max_scan_universe: 150`
  값).
- `_clamp_scan_universe_cap`/`_resolve_scan_universe_cap` 함수 본체는 무수정(PRESERVE).
- CHANGELOG 문구에 평가지표 분모 이동 경고를 포함(REQ-AI096-006 — M5에서 최종 작성,
  여기서는 값만 변경).

추적 REQ/AC: REQ-AI096-001 / AC-096-003, AC-096-004

### M3: price-fetch 사전절단 pool 소속 후보 면제

- 대상: `backend/app/services/surge_detector.py`(`:2118-2138`
  `_MAX_PRICE_FETCH_CANDIDATES` 절단 블록).
- 절단 대상 후보 집합을 `[c for c in merged.values() if c.entry_pool == "existing"]`로
  제한 — 면제된 pool 소속 후보는 그대로 `merged`에 남긴다.
- `_MAX_PRICE_FETCH_CANDIDATES`(50) 숫자와 `_pre_score()` 가중합 산출식은 무수정(PRESERVE).
- pool 소속 후보만으로 `merged`가 과도하게 커지는 경우(제안 임계값: 200개) 경고 로그
  1건 추가(REQ-AI096-005 필수 조건).

추적 REQ/AC: REQ-AI096-005 / AC-096-005, AC-096-006, AC-096-007

### M4: Pool D / bridge 후보 활성화 기준 문서화

- 대상: 코드 변경 없음 — `surge_detection.yaml`/`surge_settings.py`의 해당 필드 주석
  블록에 §Decisions D3/D4의 활성화 기준(canary 값, 관측 기간, 롤백 트리거)을 요약
  주석으로 추가한다(기존 `@MX:NOTE`/`@MX:SPEC` 관례 재사용, 값 자체는 무변경).
- `if config.pool_d_min_slots > 0:`(`:4798`) 게이트와 `if not
  config.scan_universe_bridge_candidates_enabled: return []`(`:5009`) 게이트가 코드
  변경 없이 canary 활성화를 지원함을 diff 0으로 확인(무수정 확인 = 완료 조건).

추적 REQ/AC: REQ-AI096-003, REQ-AI096-004 / AC-096-008, AC-096-009

### M5: 무회귀 확인 + CHANGELOG 경고 문구 + 검증 스위트

- 대상: `backend/tests/test_spec_ai_065.py`(또는 신규 `test_spec_ai_096.py`,
  기존 골든 fixture 재사용), `backend/tests/test_spec_ai_086.py`(clamp 상호작용 회귀),
  `backend/tests/test_spec_ai_092.py`(bridge 무수정 확인), `CHANGELOG.md`.
- 신규 테스트: (a) 캡 250 반영 후 골든 유니버스 순서/카운트, (b) `pool_d_count` 저장/조회
  왕복, (c) 절단 면제 — pool 소속 60개 + existing 60개 입력 시 pool 소속 60개 전원 생존 +
  existing 상위 50개만 생존, (d) 절단 면제 상태에서 pool_d_min_slots=0/bridge=False 조합의
  `qualified` 최종 집합이 REQ-AI096-001 적용 **전**(즉 캡 150 기준)과 일치함을 캡 파라미터를
  150으로 고정한 별도 테스트로 확인(REQ-AI096-006 무회귀 범위 명확화).
- 전체 회귀: `test_spec_ai_065.py` + `test_spec_ai_086.py` + `test_spec_ai_089.py` +
  `test_spec_ai_092.py` + `test_spec_ai_094.py`(존재 시) 무수정 통과.

추적 REQ/AC: REQ-AI096-001~006 전체 / AC-096-001~010

## C. 검증 계획

타겟 테스트:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_065.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_086.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_089.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_092.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_096.py -q
```

전체 회귀:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q -m "not slow"
```

정적 검사:

```powershell
.\backend\.venv\Scripts\ruff.exe check .\backend
```

임포트 sanity:

```powershell
cd backend; uv run python -c "from app.main import app; print('OK')"
```

마이그레이션 적용 확인:

```powershell
cd backend; uv run alembic upgrade head; uv run alembic current
```

## D. 배포/롤백

M1(마이그레이션)은 nullable 대신 `default=0, nullable=False`이지만 기존 컬럼과 동일한
안전한 ADD COLUMN이므로 배포 즉시 무해하다. M2(캡 150→250)는 **플래그가 아니므로 배포
즉시 프로덕션 동작(평가지표 분모)에 영향을 준다** — 이것이 이 SPEC에서 가장 신중하게
다뤄야 할 배포 단계다. M3(절단 면제)는 `merged`가 50개를 초과하는 날에만 관측 가능한
차이를 만든다(대부분의 날은 no-op). M4는 코드 변경이 없어 무해하다.

롤백 트리거:

- M2 배포 후 `scannable_recall`/`coverage`가 예상치 못한 방향으로 급변하고 그 원인이
  실제 탐지 성능 변화가 아니라 순수 분모 이동으로 판단되면, `max_scan_universe`를
  150으로 되돌린다(단일 값 변경, `_clamp_scan_universe_cap` 무관하게 즉시 원복 가능).
- M3 배포 후 `merged` 크기 급증으로 `price_5d_trend` HTTP 호출 소요 시간이 유의하게
  증가하거나 300초 타임아웃 재현 징후가 관측되면(§리스크), pool 소속 면제 조건을 되돌리고
  기존 절단(전체 `merged`에 대해 상위 50개)으로 복원한다.
- M1(마이그레이션)은 롤백 불필요 — 신규 컬럼은 존재해도 무해하다.

롤백 단위: M2/M3는 각각 독립적으로 되돌릴 수 있다(설정값 1건, 절단 필터 조건 1건) — M1의
컬럼 자체는 되돌릴 필요가 없다.

## E. 리스크

- **M2(캡 상향)의 평가지표 연속성 리스크**: `scannable_recall`/`coverage`가 캡 변경
  전후로 비교 불가능해진다. 완화책: REQ-AI096-006의 CHANGELOG 경고 + 배포일 명시 기록으로
  "이 날짜 이후 지표는 새 기준"임을 추적 가능하게 한다.
- **M3(절단 면제)의 HTTP 호출량 증가 리스크**: pool 소속 후보가 많은 날(예: DART 공시가
  몰리는 날) `merged` 크기가 기존 50개 상한을 크게 초과할 수 있다 — `price_5d_trend`
  HTTP 호출 수가 그만큼 늘어나 SPEC-AI-038이 해결한 300초 타임아웃 위험을 재도입할 수
  있다. 완화책: 경고 로그(제안 임계값 200개) + Open Question 4가 언급한 대로 이 리스크가
  실제로 발생하면 즉시 M3만 롤백 가능하도록 설계했다(§D).
- **Pool D/bridge "미활성화 문서화"가 실제로는 아무것도 검증하지 않는다는 오해 위험**:
  M4는 코드를 바꾸지 않으므로 자칫 "형식적 작업"으로 취급되기 쉽다 — 그러나 AC-096-008/009는
  기존 게이트가 실제로 canary 값을 코드 변경 없이 받아들이는지(회귀 테스트로) 검증하므로,
  이 M4는 "다음 세션에서 값만 바꾸면 안전하게 canary 전환 가능"이라는 보장을 산출물로
  남긴다.
- **finding 7 미검증 상태로 진행하는 리스크**: spec.md Open Questions 4에 명시한 대로,
  이 세션은 2026-07-28 실측치를 DB로 재확인하지 않았다. 캡 상향(D1)과 절단 면제(D2)는
  finding 7의 정확한 수치와 무관하게 독립적으로 타당한 개선이므로 진행하되, run-phase
  착수 전 오케스트레이터/사용자가 원하면 별도로 그 수치를 재검증할 것을 권장한다(이
  SPEC의 완료 조건에는 포함하지 않는다).
