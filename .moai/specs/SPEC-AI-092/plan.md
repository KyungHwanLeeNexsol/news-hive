# SPEC-AI-092 Plan

## A. 구현 전략

본 SPEC은 Tier M으로 진행한다. P0 기록 안정화는 이미 작은 코드 변경으로 수행했으며, 이후 단계는
feature flag 기본 OFF로 배포한다.

핵심 판단:

- bridge 후보화는 `SPEC-AI-089`의 측정 결과를 실제 후보 생성으로 연결하는 첫 구현이다.
- 비용 예산이 가장 큰 리스크이므로, 신규 외부 fetch 없이 기존 DB/인메모리 자료로만 시작한다.
- 평가 스냅샷은 API 표시 안정성과 디버깅 재현성을 위해 bridge 후보화보다 먼저 설계한다.

## B. 작업 분해

### TASK-001: prediction-history stored metric 고정

- 대상: `backend/app/routers/surge_trading.py`
- 평가 완료 행의 `predicted_count`를 `ev.predicted_count`로 반환한다.
- 상세 목록 길이는 공식 카운트로 사용하지 않는다.
- 회귀 테스트를 추가한다.

추적 REQ/AC:

- REQ-AI092-001
- AC-092-001

### TASK-002: 평가 스냅샷 설계 및 구현

- 대상: `backend/app/models`, `backend/alembic`, `backend/app/services/surge_evaluation_service.py`
- JSON 컬럼 또는 별도 snapshot 테이블 중 하나를 선택한다.
- `evaluate_surge_predictions()`가 공식 predicted set을 저장한다.
- `/evaluation/{date}`와 `/prediction-history`는 snapshot이 있으면 snapshot을 우선 사용한다.

추적 REQ/AC:

- REQ-AI092-002
- AC-092-002

### TASK-003: bridge config 추가

- 대상: `backend/app/surge_config/surge_settings.py`
- `scan_universe_bridge_candidates_enabled: bool = False`
- `scan_universe_bridge_max_candidates: int`
- `scan_universe_bridge_pool_limits: dict[str, int]`
- flag OFF 무회귀 테스트를 추가한다.

추적 REQ/AC:

- REQ-AI092-003
- AC-092-003

### TASK-004: bridge 후보 생성 함수

- 대상: `backend/app/services/surge_detector.py` 또는 신규 service
- 입력:
  - `universe_codes`
  - `entry_pool_map`
  - `merged`
  - 이미 조회된 pool/source 자료
- 출력:
  - `SurgeCandidate` 목록
- 원칙:
  - 신규 네트워크 호출 없음
  - `merged` 직접 변경은 한 곳에서만 수행
  - bridge 후보 metadata에 source pool과 scoring 근거 기록

추적 REQ/AC:

- REQ-AI092-003
- REQ-AI092-004
- AC-092-004
- AC-092-008 (bridge 후보 생성 시 same-day horizon 후보를 표준 predicted set에서 배제)

### TASK-005: adaptive threshold 연결 테스트

- 대상: `backend/app/services/fund_manager.py`, `backend/app/services/surge_detector.py`
- 현재 threshold 계산값이 예측 생성 gate에 쓰이는지 확인한다.
- 쓰지 않는 정책이면 "execution threshold only"로 명명/로그를 분리한다.
- 생성 gate에 연결하기로 결정하면 threshold fixture 테스트를 추가한다.

추적 REQ/AC:

- REQ-AI092-005
- AC-092-006

### TASK-006: 운영 누락 감시

- 대상: `backend/app/services` 또는 scheduler health helper
- 장마감 이후 actual/evaluation 존재 여부를 확인하는 idempotent check를 추가한다.
- 알림 연동은 기존 Telegram admin 채널이 있으면 사용하고, 없으면 warning log로 fail-open한다.

추적 REQ/AC:

- REQ-AI092-006
- AC-092-007

## C. 검증 계획

타겟 테스트:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_surge_eval_endpoints.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_088.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_089.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_surge_evaluation_service.py -q
```

전체 회귀 후보:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q -m "not slow"
```

정적 검사:

```powershell
.\backend\.venv\Scripts\ruff.exe check .\backend
```

## D. 배포/롤백

bridge 후보화 flag ON 이후 다음 중 하나가 발생하면 즉시 OFF로 되돌린다.

- 일별 예측 수가 기존 14일 평균 대비 3배 이상 증가
- precision이 5거래일 연속 0%
- 외부 fetch 호출 수가 기존 대비 증가
- scheduler runtime이 기존 대비 30% 이상 증가
- same-day 후보가 표준 T-1 -> T predicted set에 섞임

## E. 이번 sync에서 이미 완료된 항목

- TASK-001 코드 변경 완료.
- TASK-001 회귀 테스트 추가.
- 2026-07-28 운영 actual/evaluation 수동 복구 완료.
- 구현 전 분석 문서 작성: `backend/docs/spec-ai-092-surge-prediction-recall-recovery.md`.

## F. 리스크

- bridge scoring이 약하면 예측 수만 늘고 precision이 더 내려갈 수 있다.
- JSON snapshot은 빠르지만 상세 신호 분석/조인에는 한계가 있다.
- 별도 snapshot 테이블은 더 정확하지만 migration과 API 변경 범위가 커진다.
- actual outcome 수집 범위를 마스터 종목으로 제한하면 전체 시장 coverage 관점의 진단 정보가 줄어든다.
