# SPEC-AI-110 Plan

## Scope

`backend/app/routers/surge_trading.py`의 응답 직렬화만 수정한다. DB 모델과 평가 저장
로직은 변경하지 않는다.

## Design

- `_compute_market_recall()`
- `_compute_market_f1()`
- `_evaluation_metric_fields()`
- `_evaluation_list_item()`

위 헬퍼로 목록/상세/history 응답에서 같은 지표 정의를 재사용한다.

## Verification

- `backend/tests/test_surge_eval_endpoints.py`
- `ruff check backend/app/routers/surge_trading.py backend/tests/test_surge_eval_endpoints.py`
