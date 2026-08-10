# SPEC-AI-109 Plan

## A. Scope

P0만 구현한다. 이번 변경은 평가 누락을 복구 가능하게 만드는 운영 안정성 작업이며,
예측력 자체를 높이는 유니버스/모델 변경은 다음 우선순위로 분리한다.

수정 파일:

- `backend/app/services/surge_evaluation_service.py`
- `backend/app/services/scheduler.py`
- `backend/app/routers/surge_trading.py`
- `backend/tests/test_spec_ai_092.py`
- `backend/tests/test_surge_eval_endpoints.py`

## B. Design

1. `repair_missing_surge_evaluation()`을 평가 서비스에 추가한다.
2. 기존 감시 잡은 `check_and_alert_missing_evaluation()` 이후 누락이면 복구 함수를
   호출한다.
3. 관리자 API `POST /api/surge-trading/evaluation-backfill`을 추가한다.
4. 수집 후에도 actual outcome row가 없으면 평가를 만들지 않는다. 이는 잘못된
   `actual_surge_count=0` row가 공식 평가로 남는 것을 막기 위한 안전장치다.
5. 과거 날짜 actual outcome은 기존 current-top-movers 수집 함수로 안전하게 재구성할
   수 없으므로 기본 차단한다. 운영 백필은 actual row가 이미 있는 과거 날짜의
   evaluation 생성/갱신에 사용한다.

## C. Verification

집중 테스트:

- `backend/tests/test_spec_ai_092.py::TestMissingEvaluationMonitor`
- `backend/tests/test_surge_eval_endpoints.py::TestEvaluationBackfill`

운영 백필 예시:

```bash
curl -X POST \
  'http://140.245.76.242:8000/api/surge-trading/evaluation-backfill?start_date=2026-08-04&end_date=2026-08-07' \
  -H 'Authorization: Bearer <admin-token>'
```

과거 날짜에 actual outcome row가 없으면 응답은
`skipped_historical_actual_collection_unavailable`이며, 이 경우 별도 historical
actual 재구성 SPEC가 필요하다.
