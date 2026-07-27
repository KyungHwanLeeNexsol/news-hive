# SPEC-AI-088 구현 계획

## 접근 개요

DDD ANALYZE-PRESERVE-IMPROVE + Reproduction-First(특성화 테스트 선행). 3개 독립 시그널 생성
경로(fund_manager.py 장중 재스캔 / disclosure_impact_scorer.py 즉시발화 / surge_detector.py
near_limit_up_carry)에 각각 안전하게 개입하며, 탐지기 판정·신뢰도·앙상블 로직은 diff 0을
유지한다. 신규 네트워크 fetch 비용은 0(모든 계측이 기존 응답/변수 재사용).

## 데이터 모델 결정 (결정 가역성 우선 검토 — 가장 변경 가능성 높은 결정)

`surge_metadata`(Text/JSON) 신규 키 `pre_signal_change_pct`(float, optional)의 의미론이 이
SPEC에서 가장 재검토 가능성이 높은 결정이므로 구현에 앞서 명시한다.

| 항목 | 결정 | 근거 |
|------|------|------|
| **필드명** | `pre_signal_change_pct` | 사용자 원 요청 문구 그대로 채택. `yesterday_change_pct`(near_limit_up_carry 기존 필드, "전일 자체 등락률")와 의미가 다름을 이름으로 구분 — 혼동 방지가 우선 |
| **의미** | "T-1 종가 → `price_at_signal` 시점 가격"의 변화율(%) | Naver `fluctuationsRatio` 표준 정의와 정확히 일치, 신규 계산 로직 불필요 |
| **near_limit_up_carry의 0.0 값** | 계산이 아닌 **불변식**(항상 0.0)으로 명시 저장 | `price_at_signal=t1_close`이므로 수학적으로 항상 0. 저장하지 않고 생략하면 "계측 누락"과 "정말로 0"을 구분할 수 없어 리뷰 시 오독 위험 — 명시 저장이 더 정직함(§부가 전용 원칙과 상충하지 않음, fetch 비용 0 유지) |
| **미커버 경로의 부재값** | 키 자체를 생략(None이 아닌 명시 null 아님) | 기존 `horizon` 키의 "same_day일 때만 주입" 관례(SPEC-AI-083 REQ-AI083-005/[X-4])와 동일 패턴 재사용 — 새로운 관례를 만들지 않음 |

**결정 근거**: 3개 경로가 서로 다른 데이터 가용성(이미 fetch됨 / 이미 fetch됨-필드만 버려짐 /
fetch 자체가 불필요)을 가지므로 획일적 구현이 아닌 경로별 최소 개입을 택했다. 이 SPEC에서
가장 재검토 여지가 큰 것은 near_limit_up_carry의 "0.0을 명시 저장할지 생략할지" 결정이며,
위 표의 근거대로 명시 저장을 채택한다.

## 마일스톤 (우선순위 기반, 시간 추정 없음 — 결정 가역성 순서로 배열)

- **M1 (P0, 데이터 모델면 — 가장 변경 가능성 높은 결정)**: 특성화 테스트 선행 — 3개 대상
  함수(`_gather_surge_candidates`의 `_signal_current_price` 산출부, `_create_immediate_surge_signal`의
  가격 fetch부, `detect_near_limit_up_carries`의 metadata dict 구성부)의 현재 `surge_metadata`
  출력을 고정. `pre_signal_change_pct` 키가 현재 어디에도 없음을 RED로 재현.
- **M2 (P0, 신규 필드 계산 — REQ-001/002/003)**: 3개 경로에 `pre_signal_change_pct` 계산 및
  저장 로직 추가. 각 경로마다 신규 fetch가 발생하지 않음을 mock call-count assert로 고정.
- **M3 (P0, 하위 호환 회귀 — REQ-004)**: 기존 필드-부재 `surge_metadata`를 새 헬퍼로 읽을 때
  예외 없이 `None`을 반환함을 확인. `_is_same_day_event_horizon_signal`/
  `_is_near_limit_up_carry_signal`가 이 SPEC 적용 후에도 무변경임을 회귀 assert로 고정.
- **M4 (P1, API 노출 — REQ-005)**: 공유 헬퍼(`_extract_pre_signal_change_pct`)를
  `surge_trading.py`에 추가하고 `_get_signal_details_for_date()` + `/prediction-history`
  인라인 dict 2곳에 배선.
- **M5 (P0, 최종 검증)**: 전체 백엔드 스위트 무회귀 확인 + `ruff check .`.

## 기술적 접근

- **REQ-001**: `fund_manager.py:1486-1489`의
  ```python
  _price_data = fetch_current_price_with_change_sync(candidate.stock_code)
  if _price_data:
      _signal_current_price = _price_data.get("current_price")
  ```
  블록에서 `_signal_current_price_change_pct = _price_data.get("change_rate")`도 함께 추출한다.
  `metadata["horizon"] = "same_day"` 주입부(`:1417-1418`)와 동일 조건(`_intraday_horizon ==
  "same_day"`) 아래에 `metadata["pre_signal_change_pct"] = round(_signal_current_price_change_pct, 2)`를
  추가한다(값이 `None`이 아닐 때만 — fetch 실패 시 키 생략, 기존 `_signal_current_price`
  None-허용 패턴과 동일 fail-safe). `existing` 갱신 분기(`:1504-1548`)는 `metadata_json`을
  그대로 재사용하므로(`:1521`, `not _existing_is_immediate`일 때) 추가 코드 불필요.
- **REQ-002**: `disclosure_impact_scorer.py:557-560`의
  ```python
  from app.services.naver_finance import fetch_current_price
  price = await fetch_current_price(disclosure.stock_code)
  ```
  를
  ```python
  from app.services.naver_finance import fetch_current_price_with_change
  _price_data = await fetch_current_price_with_change(disclosure.stock_code)
  price = _price_data.get("current_price") if _price_data else disclosure.baseline_price
  _change_pct = _price_data.get("change_rate") if _price_data else None
  ```
  로 교체한다(예외 처리 `except Exception: price = disclosure.baseline_price` 구조는
  `_price_data=None`으로 흡수해 유지). `metadata` dict(`:573-582`)에 `horizon == "same_day"`일
  때만 `"pre_signal_change_pct": round(_change_pct, 2)`를 추가(값이 `None`이 아닐 때).
- **REQ-003**: `surge_detector.py:2860-2865`의 `metadata` dict 리터럴에
  `"pre_signal_change_pct": 0.0`을 추가한다. 계산이나 fetch 없이 상수 삽입.
- **REQ-004**: 신규 헬퍼 `_extract_pre_signal_change_pct(surge_metadata_json: str | None) -> float | None`을
  `surge_trading.py`에 추가한다. `_is_same_day_event_horizon_signal()`(`surge_evaluation_service.py:506-524`)와
  동일한 fail-safe JSON 파싱 패턴(파싱 실패/dict 아님/키 부재 → `None` 반환, 예외 없음)을 따른다.
  이 헬퍼는 순수 함수이며 기존 판별 함수를 호출하거나 변경하지 않는다.
- **REQ-005**: `surge_trading.py`의 `_get_signal_details_for_date()`(`:260-274` item dict) +
  `/prediction-history`의 두 인라인 item dict(`:455-467`, `:499-511`) 각각에
  `"pre_signal_change_pct": _extract_pre_signal_change_pct(fs.surge_metadata),` 한 줄을 추가한다.

## 리스크

- **R-1 (fund_manager.py 변수명 충돌)**: `_signal_current_price_change_pct`라는 신규 지역
  변수명이 기존 스코프와 충돌하지 않는지 M1 특성화 테스트에서 사전 확인. → 함수 스코프가
  이미 넓으므로(1270~1600+) 변수명에 접두사 `_signal_` 유지로 충돌 회피.
- **R-2 (disclosure_impact_scorer.py의 except 분기 의미 변화 + 폴백 엔드포인트 델타)**: (a) 기존
  `except Exception: price = disclosure.baseline_price` 단순 폴백을 `_price_data=None` 흡수
  패턴으로 재작성하며 `price` 값의 폴백 의미가 바뀌지 않는지(여전히 baseline_price) M1
  특성화 테스트로 고정. (b) **[plan-auditor iteration 1 D2 지적 반영]** 교체 대상
  `fetch_current_price`(구, 모바일 API 폴백 엔드포인트 `/api/stock/{code}/integration` — 문서화된
  폐기 엔드포인트, `naver_finance.py:1268`)와 `fetch_current_price_with_change`(신, 폴백
  엔드포인트 `/api/stock/{code}/price`, `:1307`)는 폴백 엔드포인트가 서로 다르다. 1차 조회
  (시가총액 상위 50위)에 잡히지 않는 종목(다수)에서는 이 폴백이 사실상 주경로이므로, 이 교체는
  해당 종목군의 `current_price` 조회 성공률을 실질적으로 바꿀 수 있다 — 이는 spec.md REQ-002가
  명시하는 계측 정확도 개선의 의도된 부수 효과이며, 탐지기 판정/신뢰도 스코어링과는 무관하다
  (§Out of Scope 원칙과 상충하지 않음). M1 특성화 테스트는 이 델타를 회귀가 아닌 의도된 개선으로
  명시 기록한다(acceptance.md AC-088-003 폴백 경로 시나리오 참고).
- **R-3 (REQ-004 회귀 범위)**: `_is_same_day_event_horizon_signal`/`_is_near_limit_up_carry_signal`
  자체는 코드 무변경이지만, 이 SPEC이 `surge_metadata`에 새 키를 추가하는 시그널이 늘어나므로
  두 판별 함수가 새 키의 존재에 영향받지 않음(오직 `horizon`/`surge_basis`/플랫
  `near_limit_up_carry` 키만 검사)을 회귀 assert로 명시 고정한다.
- **R-4 (near_limit_up_carry `0.0` 리터럴의 부동소수점 표현)**: JSON 직렬화 시 `0.0` →
  `0` 또는 `0.0`으로 표현될 수 있으나 파싱 시 Python `float`/`int` 모두 수치 비교로
  `== 0.0`이 성립하므로 실질적 문제 없음(명시 assert로 확인).

## 변경 예상 파일

`backend/app/services/fund_manager.py`(REQ-001), `backend/app/services/disclosure_impact_scorer.py`
(REQ-002), `backend/app/services/surge_detector.py`(REQ-003), `backend/app/routers/surge_trading.py`
(REQ-004/005 — 신규 헬퍼 + 3개 배선 지점), `backend/tests/test_spec_ai_088.py`(신규 — 특성화 +
신규 동작 테스트). `surge_detection.yaml`/`surge_settings.py` 신규 키 불필요(신규 설정 필드
없음 — 이 SPEC은 조건 없이 항상 계측하는 관측 필드이지 opt-in 플래그가 아님). **마이그레이션
없음.**
