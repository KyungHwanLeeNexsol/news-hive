# Research — SPEC-AI-024: 임원 자사주 직접 매수 공시 강화 탐지

## Codebase Discovery (read-only)

본 SPEC 작성 전 다음 파일을 직접 확인하여 실제 데이터 모델과 코드 패턴에 정합하도록 요구사항을 도출했다.

### 1. `backend/app/models/disclosure.py` — Disclosure 모델 (line 1-39)

확인된 필드 (실제 코드 기준):

| 필드 | 타입 | 비고 |
|------|------|------|
| `id` | `int (PK)` | autoincrement |
| `corp_code` | `str(8)` | DART corp code |
| `corp_name` | `str(100)` | 기업명 |
| `stock_code` | `str(6) | None` | 종목코드 |
| `stock_id` | `int | None (FK stocks.id)` | Stock 모델 연결 |
| `report_name` | `str(500)` | **공시 제목 — 본 SPEC 매칭 대상** |
| `report_type` | `str(50) | None` | 보고서 유형 (실제 값은 DB 확인 필요, 항상 채워져 있지는 않음) |
| `rcept_no` | `str(20) UNIQUE` | DART 접수번호 |
| `rcept_dt` | `str(10) "YYYYMMDD"` | 접수일자 (문자열) |
| `url` | `str(500)` | DART 원문 URL |
| `created_at` | `DateTime(tz)` | 레코드 생성시각 (UTC server_default=now) |
| `disclosed_at` | `DateTime(tz) | None` | SPEC-AI-004 추가 — DART 공시 시각 |
| `impact_score` | `float | None` | SPEC-AI-004 |
| `baseline_price`, `reflected_pct`, `unreflected_gap`, `ripple_checked` | — | SPEC-AI-004 |

핵심 관찰:
- **`report_type`은 nullable**. 따라서 매칭 로직은 `report_name` 키워드 기반 매칭을 1차로 하고, `report_type`이 있으면 보조 신호로 사용해야 한다.
- `rcept_dt`는 `YYYYMMDD` 문자열. 최근 N일 필터는 문자열 비교 가능.
- `created_at`은 UTC, 미리 조정된 timezone-aware datetime.
- DART 표준 명칭에는 **`ㆍ`(U+318D)** 가 사용된다는 점을 기존 코드(`surge_detector.py` line 766-785)가 명시하고 있다. 임원 보고서 정식 명칭도 동일 문자를 포함할 가능성이 높음.

### 2. `backend/app/services/surge_detector.py` — 기존 disclosure 탐지기 (line 760-880)

기존 `detect_immediate_disclosure_signal()` 함수의 패턴 분석:

- `_IMMEDIATE_EVENT_PATTERNS: list[tuple[str, float]]` 자료구조 사용 — (키워드, 점수) 튜플 리스트로 키워드 매칭
- DART 표기 변형(ㆍ U+318D vs · 중간점) 양쪽 등록 패턴 (line 775-776 코멘트)
- `Disclosure.rcept_dt >= cutoff_str AND Disclosure.stock_id.isnot(None)` 필터
- 종목별 최고 점수만 집계하여 `SurgeCandidate` 객체로 변환 → `immediate_disclosure_score` 부여 (signal_type 대신 ensemble 점수에 기여하는 방식)
- **본 SPEC은 위 방식과 다르게 동작해야 한다**: `_run_coverage_expansion`에서 호출되는 독립 탐지기로서 `FundSignal`을 직접 생성한다 (SPEC-AI-023 패턴과 동일).
- 기존 `_IMMEDIATE_EVENT_PATTERNS`에 이미 `"자기주식취득결정"`(score 0.70) 키워드가 등록되어 있다 — 이는 **회사가 자기주식을 사는 경우**이며, 본 SPEC 대상 **임원이 자사주를 사는 경우**는 별개의 보고서이다 (보고서 종류 자체가 다름). 따라서 본 SPEC은 기존 탐지기와 키워드 / signal type 모두 분리된다.

### 3. `backend/app/services/fund_manager.py` — `_run_coverage_expansion` (line 3654-3719)

기존 3개 try/except 블록의 패턴 확인:

```
_run_coverage_expansion(db, surge_results)
├── try: propagate_theme_group_signals (SPEC-AI-022)
├── try: detect_volume_anomaly_dormant_stocks (SPEC-AI-022)
└── try: detect_near_limit_up_carries (SPEC-AI-023)
```

각 블록 공통 패턴:
- `from app.surge_config.surge_settings import XxxConfig`
- `from app.services.surge_detector import detect_xxx`
- `config = XxxConfig()` (기본값 instantiate)
- `count = detect_xxx(db, config)` 또는 `signals = detect_xxx(db, config)`
- `logger.info("[커버리지확장] ... %d개 생성", count)`
- `except Exception as e: logger.warning("[커버리지확장] ... 실패 (... 결과 보존됨): %s", e)`

본 SPEC의 4번째 try/except 블록은 위 패턴과 동일하게 작성한다.

### 4. `backend/app/models/fund_signal.py` — FundSignal 모델

확인된 필드 (line 9-86):
- `signal_type: str | None (String(30))` — 본 SPEC은 `"surge_candidate"` 사용 (SPEC-AI-023과 동일하게 `surge_trading_service.get_today_signals` 필터 자동 통과)
- `confidence: float` — 본 SPEC은 `0.45` 고정
- `signal: str (10)` — `"buy"`
- `surge_metadata: Text | None` — JSON 문자열로 `{"surge_basis": ["insider_purchase"]}` 저장
- `paper_executed: bool` — 본 SPEC은 `True` (익일 매수 큐 진입 허용)
- `disclosure_id: int | None (FK disclosures.id)` — 본 SPEC은 트리거가 된 공시 ID 기록 가능 (SPEC-AI-004 패턴 활용)
- `reasoning: Text` — NOT NULL → 본 SPEC은 임원명/공시명 포함한 한국어 설명 채움
- `created_at: DateTime(tz) server_default=now` — UTC 자동 기록

### 5. `backend/app/services/surge_detector.py` — `detect_near_limit_up_carries` (line 1468-1577)

본 SPEC의 직접 모델로 삼는 SPEC-AI-023 구현 패턴:

핵심 패턴:
- 시그니처: `def detect_near_limit_up_carries(db: Session, config: "NearLimitUpConfig") -> list[FundSignal]`
- `if not config.enabled: return []` early return
- `KST = ZoneInfo("Asia/Seoul")` → 오늘 KST 00:00 → UTC 변환하여 중복 체크 기준 시각으로 사용
- `existing_ids: set[int]` — `FundSignal.created_at >= today_utc_start` 조건으로 **오늘 시그널이 있는 stock_id 집합** 조회 (signal_type 불문) → 중복 방지
- `db.add(signal)` 반복 후 마지막에 `db.commit()` (한 번)
- 전체를 try/except로 감싸 예외 시 빈 리스트 반환 + 로깅
- `surge_metadata`는 JSON 직렬화: `_json.dumps(metadata, ensure_ascii=False)`

본 SPEC은 위 시그니처와 패턴을 그대로 따른다.

### 6. `backend/app/surge_config/surge_settings.py` — NearLimitUpConfig (line 186-197)

`Pydantic BaseModel` 사용. 모든 필드에 기본값 부여. SurgeDetectionConfig 본체에 포함되지 **않음** (`_run_coverage_expansion`에서 직접 instantiate).

### 7. 최신 마이그레이션 — `055_spec_ai_022_theme_groups.py`

```python
revision = "055_spec_ai_022_theme_groups"
down_revision = "054_spec_ai_018_raw_regime"
```

**본 SPEC은 신규 마이그레이션을 추가하지 않는다** (기존 컬럼만 사용하며 스키마 무변경). SPEC-AI-023과 동일.

### 8. DART 임원 보고서 정식 명칭 (외부 지식 기반 — 코드 미포함)

DART 시스템상 임원의 자사주 거래 신고는 다음 보고서로 제출된다:
- 정식명: **"임원ㆍ주요주주특정증권등소유상황보고서"** (ㆍ는 U+318D)
- 변형 표기: `"임원·주요주주특정증권등소유상황보고서"` (중간점 ·) — 일부 크롤러/저장 단계에서 변환될 수 있음
- 표준 키워드: `report_name` 또는 `report_type`에 위 문자열 또는 일부가 포함됨

본 보고서 자체는 매수/매도/장내취득/장외취득 등 다양한 거래를 모두 포괄한다. 따라서 단순히 "이 보고서가 있다"는 사실만으로는 매수 신호로 판단할 수 없으며, **공시 제목에 "취득" 또는 "매수" 키워드가 추가로 포함되어 있어야 한다**. (DART는 보통 보고서 부제목에 "보통주식 N주 취득" 형태로 거래 내용을 노출한다.)

본 SPEC은 두 단계 매칭 OR 조합으로 안전하게 식별한다:
- (A) `report_name`에 "임원" AND ("취득" OR "매수") 키워드 동시 포함
- (B) `report_type` 또는 `report_name`에 "임원ㆍ주요주주특정증권등소유상황보고서" 또는 그 변형이 포함되고, 동시에 `report_name`에 "취득" 또는 "매수" 키워드 포함

## Design Decisions

### D1: signal_type은 `"surge_candidate"` 사용 — `"insider_purchase"` 신규 도입 금지

이유: SPEC-AI-023과 동일 논리. `surge_trading_service.get_today_signals`는 `signal_type='surge_candidate'`만 필터링한다 (`backend/app/services/surge_trading_service.py` 확인 시). 새 enum 값 도입은 다운스트림(트레이딩, 백테스트, UI) 모두 변경이 필요하므로 본 SPEC의 backend-only 범위를 초과한다. 식별은 `surge_metadata.surge_basis == ["insider_purchase"]`로 처리.

### D2: confidence는 고정 `0.45` — 동적 학습 미적용

이유: 요구사항이 명시하는 base_confidence=0.45 사용. 매수 임원 인원수/매수 금액/지분율 변화 같은 동적 인자는 향후 SPEC에서 학습할 항목으로 분리. 본 SPEC은 "임원이 자사주 매수했다는 사실" 자체만 신호로 인정한다.

### D3: disclosure_id 채움 — SPEC-AI-004 패턴 활용

이유: 트리거된 공시 ID를 `FundSignal.disclosure_id`에 저장하면 백테스트/적중률 추적 시 어떤 공시가 신호를 유발했는지 추적 가능. SPEC-AI-004가 동일 필드를 사용 중이며, 신규 컬럼 추가가 아니므로 안전.

### D4: lookback은 `rcept_dt` 문자열 비교 — `created_at` 사용 안 함

이유: DART 크롤러가 과거 공시를 일괄 수집하는 경우 `created_at`은 최근(크롤링 시각)이 되지만 `rcept_dt`는 실제 접수일자이다. 본 SPEC은 "**오늘 또는 어제 접수된 공시**"만 신호로 인정하므로 `rcept_dt`를 사용한다. `lookback_days=1` 기본값은 보수적인 선택.

### D5: 중복 방지 기준 — 오늘 동일 종목 surge_candidate 존재 시 스킵

이유: 본 SPEC은 SPEC-AI-023과 동일하게 `signal_type='surge_candidate'`로 발행하므로, 동일 종목에 이미 오늘 surge_candidate가 있으면 (일반 surge_candidate 또는 다른 coverage_expansion 탐지기 결과) 중복 생성하지 않는다. 이는 요구사항 AC-002의 명시적 조건.

### D6: 4번째 try/except 블록 위치 — 기존 3개 블록 이후

이유: `_run_coverage_expansion`의 try 블록은 서로 독립적이며 순서 의존성이 없다. 가독성을 위해 시간 순(SPEC-AI-022 → SPEC-AI-023 → SPEC-AI-024) 추가.

### D7: 키워드는 모듈 상수 리스트로 관리

이유: 향후 DART 표기 변경/추가 대응을 위해 `_INSIDER_PURCHASE_REPORT_TITLES`, `_INSIDER_PURCHASE_ACTION_KEYWORDS` 두 리스트 상수로 분리. `_IMMEDIATE_EVENT_PATTERNS`의 선례와 동일한 컨벤션.

### D8: enabled=False 시 즉시 빈 리스트 반환 — DB 쿼리도 실행 안 함

이유: SPEC-AI-023 AC-008과 동일. 비활성화 시 부하 0.

## Risks and Mitigations

| 리스크 | 영향 | 완화 |
|--------|------|------|
| `report_type` 표준 명칭이 DB 저장 시 변형됨 | 매칭 누락 | 키워드 매칭을 `report_name` 1차 + `report_type` 보조의 OR 조건으로 안전망 |
| 임원 매수 외에 매도/장외매도까지 포함된 보고서를 매수 신호로 오인 | False positive | `report_name`에 반드시 "취득" 또는 "매수" 키워드가 포함된 경우만 인정 ("처분"/"매도" 명시 시 스킵 — Exclusion 처리) |
| 동일 공시가 여러 임원의 매수를 동시에 보고하여 1종목에 여러 공시 매칭 | 중복 시그널 | 종목 1개당 1 시그널만 생성 (중복 방지 + 종목 단위 dedup) |
| 임원 가족(특수관계인)의 매수만 포함된 케이스도 hit | False positive | base_confidence를 0.45로 낮게 설정하여 다른 신호 부재 시 단독 결정력 제한 |
| DART 크롤러가 임원 보고서를 수집하지 않음 | 신호 0건 | 기존 `dart_crawler`가 모든 공시를 수집하는지 확인 필요 (현재 dart_crawler는 corp_code 기반 일괄 수집으로 모든 보고서 포함) |
| naver API 호출이 본 탐지기에서 발생하면 추가 부하 | 성능 저하 | 본 탐지기는 가격 조회 없음 (DB만 사용). naver API 호출 0회 |

## Related SPECs

- **SPEC-AI-004**: 공시 충격 스코어링 — `Disclosure.impact_score` 필드와 `signal_type='disclosure_impact'` 도입. 본 SPEC은 SPEC-AI-004와 직교(orthogonal)하며 동일 공시에 양쪽 시그널이 발행될 수 있다 (signal_type이 다르므로 충돌 없음, 단 본 SPEC은 surge_candidate로 발행하므로 동일 종목 중복 방지에 걸림).
- **SPEC-AI-012**: 급등 징후 탐지 — `surge_candidate`와 `surge_metadata.surge_basis` 패턴.
- **SPEC-AI-018**: 즉각 공시 이벤트 — `_IMMEDIATE_EVENT_PATTERNS`에 "자기주식취득결정"(회사가 자기주식 매수) 등록. 본 SPEC의 "임원 매수"와 다른 보고서임에 주의.
- **SPEC-AI-022**: 시그널 커버리지 확장 — `_run_coverage_expansion()` 통합 패턴. 본 SPEC은 동일 패턴으로 4번째 탐지기 추가.
- **SPEC-AI-023**: 상한가 근접 carry-forward — 시그니처/Pydantic Config/통합 위치의 직접 모델.
