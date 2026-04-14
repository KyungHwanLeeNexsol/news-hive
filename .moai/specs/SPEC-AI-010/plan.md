# SPEC-AI-010 Implementation Plan

## Scope Summary

`backend/app/services/fund_manager.py`의 `analyze_stock()` 함수에 두 개의 신규 데이터 채널을 통합한다. 이는 **brownfield modification**으로, 기존 로직은 보존하고 프롬프트에 신규 섹션만 추가한다.

## Delta Markers

### [DELTA] `backend/app/services/fund_manager.py`

#### [EXISTING] 유지 항목 (수정 금지)
- `_gather_sentiment_trend()` (line 138): 뉴스 기반 센티먼트 추이 반환 — 변경 없음
- `_gather_securities_reports()` (line 381): 최근 14일 5개 리포트 반환 — 변경 없음
- `analyze_stock()` 프롬프트 섹션 1-1 (~line 1739): 뉴스 센티먼트 표시 — 변경 없음
- `analyze_stock()` 프롬프트 섹션 9 (~line 1799): 리포트 표시 — 변경 없음

#### [NEW] (선행 SPEC에서 구현됨 - 본 SPEC에서는 호출만)
- `_gather_forum_sentiment(db, stock_id)`: SPEC-AI-008에서 구현 — 본 SPEC에서 호출 추가
- `_gather_securities_consensus(db, stock_id, current_price)`: SPEC-AI-009에서 구현 — 본 SPEC에서 호출 추가

#### [MODIFY] `analyze_stock()` 함수 내부 변경 (line 1623~)

**변경 지점 A: 데이터 수집부**
- 기존 `sentiment_trend = await _gather_sentiment_trend(...)` 호출 직후
  - 추가: `forum_sentiment = _gather_forum_sentiment(db, stock_id)` (예외 포착 → None)
- 기존 `securities_reports = _gather_securities_reports(...)` 호출 직후
  - 추가: `consensus = _gather_securities_consensus(db, stock_id, current_price=market_data.get("current_price"))` (예외 포착 → None)

**변경 지점 B: 프롬프트 구성부**
- 섹션 1-1 (뉴스 센티먼트) 직후에 **섹션 1-2 (종토방 감성)** 삽입
  - `forum_sentiment`가 None이면 섹션 스킵 (REQ-SENTIMENT-006)
  - `overheating_alert=True` → 과열 경고 문구 포함 (REQ-SENTIMENT-003)
  - `volume_surge=True` → 급증 주의 문구 포함 (REQ-SENTIMENT-004)
  - 헤더 고정: `"## 1-2. 종토방 감성 (역발상 지표)"` (REQ-SENTIMENT-002)
  - 역발상 해석 안내: 낙관 과다 시 고점 경계, 비관 과다 시 저점 가능성

- 섹션 9 (증권사 리포트) 직후에 **섹션 9-1 (증권사 컨센서스)** 삽입
  - `consensus`가 None이면 섹션 스킵
  - 표시 필드: `avg_target_price`, `premium_pct`, `consensus_signal`, buy/hold/sell 비율 (REQ-SENTIMENT-005)
  - `consensus_signal == "strong_buy"` → 긍정 노트 추가 (REQ-SENTIMENT-007)
  - `consensus_signal == "caution"` → 경고 노트 추가 (REQ-SENTIMENT-007)

## Technical Approach

### Graceful Fallback Pattern
선행 SPEC 미배포/데이터 부재 시 무장애 동작을 위해 try-except 래핑을 적용한다. `ProgrammingError`, `OperationalError` (테이블 없음) 및 `AttributeError`(함수 미존재)를 모두 포착하여 None 반환.

### Prompt Section Ordering
최종 프롬프트 순서:
1. `1. 종목 개요`
2. `1-1. 센티먼트 추이 (뉴스)` — 기존 유지
3. `1-2. 종토방 감성 (역발상 지표)` — **NEW**
4. ... (기존 섹션 2~8) ...
5. `9. 증권사 리포트` — 기존 유지
6. `9-1. 증권사 컨센서스` — **NEW**
7. ... (기존 섹션 10~) ...

### Contrarian Weighting
프롬프트 내 해석 지시:
- 뉴스 센티먼트 가중치: 1.0 (정방향 신호)
- 종토방 센티먼트 가중치: 0.2 (역방향 보조)
- AI에게 최종 판단 시 뉴스가 긍정 + 종토방이 극도 낙관 → **경계** 지시
- AI에게 최종 판단 시 뉴스가 중립 + 종토방이 극도 비관 → **저점 탐색 가능성** 시사

## Milestones

### Priority High
1. **M1 - Data Gathering Integration**: `analyze_stock()`에 두 신규 함수 호출 추가 및 graceful fallback 확인
2. **M2 - Prompt Section 1-2 Injection**: 종토방 감성 섹션을 프롬프트에 삽입 및 overheating/surge 조건부 경고 구현

### Priority Medium
3. **M3 - Prompt Section 9-1 Injection**: 증권사 컨센서스 섹션 삽입 및 signal 기반 조건부 노트 구현
4. **M4 - Performance Verification**: 기준선 대비 500ms 이내 증가 확인 (profiling)

### Priority Low
5. **M5 - Logging Enhancement**: 각 채널(news/forum/consensus)의 데이터 존재 여부 로깅

## MX Tag Targets

- **`analyze_stock()`** (line 1623): `@MX:ANCHOR`
  - Reason: fan_in ≥ 3 (scheduler, briefing service, API endpoint에서 호출)
  - 본 SPEC에서 시그니처는 변경되지 않으나 내부 동작이 확장됨 — 불변 계약 문서화 필요

- **신규 프롬프트 섹션 1-2 및 9-1 구성 블록**: `@MX:NOTE`
  - Reason: 각 신호 채널의 가중치/해석 규칙을 코드 주석으로 명시
  - 역발상 지표(종토방 0.2)와 주 신호(뉴스 1.0)의 의도 기록

- **Graceful fallback try-except 블록**: `@MX:NOTE`
  - Reason: 선행 SPEC 미배포 상황에서의 안전 동작 의도 기록

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| SPEC-AI-008/009 미배포 시 ImportError | High | try-except로 `_gather_forum_sentiment`/`_gather_securities_consensus` import 보호 또는 함수 존재 검사 |
| 프롬프트 길이 증가로 LLM 컨텍스트 초과 | Medium | 섹션 1-2는 최대 10줄, 9-1은 최대 8줄로 제한 |
| 종토방 과열 경고 남발로 매수 신호 억제 과다 | Medium | `overheating_alert` 기준을 SPEC-AI-008에서 보수적으로 설정 (상위 5% 등) |
| 실행 시간 증가 (500ms 초과) | Low | DB 조회는 인덱스 활용, 두 함수 모두 캐싱 또는 단일 쿼리 |
| 기존 뉴스 센티먼트 로직 회귀 | High | 기존 코드 라인 비수정 원칙 엄수, regression test 추가 |

## Technical Approach Summary

1. 기존 함수는 읽기만 수행하며, 신규 호출 2개를 기존 호출 인접 위치에 추가
2. 프롬프트 문자열 조립 시 조건부 삽입 패턴 사용 (data가 None이면 빈 문자열)
3. 모든 신규 로직은 try-except로 감싸 기존 분석 흐름에 영향 없음 보장
4. 테스트: 기존 뉴스 센티먼트 골든 테스트 추가 + 신규 섹션 포함 여부 테스트 추가
