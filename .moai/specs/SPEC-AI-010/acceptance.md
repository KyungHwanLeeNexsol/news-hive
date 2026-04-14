# SPEC-AI-010 Acceptance Criteria

## Given-When-Then Scenarios

### Scenario 1: 종토방 데이터 정상 통합
**Given** SPEC-AI-008이 배포되어 있고 `StockForumHourly` 테이블에 `stock_id=1`에 대한 데이터가 존재
**When** `analyze_stock(stock_id=1, ...)`가 호출됨
**Then** AI에게 전달되는 프롬프트 문자열에 `"## 1-2. 종토방 감성 (역발상 지표)"` 헤더가 포함됨
**And** 해당 섹션에 정량 지표(낙관/비관 비율 등)가 표시됨
**And** 기존 섹션 `"## 1-1."`(뉴스 센티먼트)는 변경 없이 그대로 유지됨

### Scenario 2: 과열 경고 문구 삽입
**Given** `_gather_forum_sentiment()`가 `overheating_alert=True`를 포함한 결과를 반환
**When** `analyze_stock()`이 호출되어 프롬프트가 구성됨
**Then** 프롬프트에 `"종토방이 과열 상태"` 문구가 포함됨
**And** AI에 대한 매수 신호 주의 지시 문구가 포함됨
**And** 해석 맥락(개인투자자 쏠림, 고점 가능성)이 함께 제공됨

### Scenario 3: 선행 SPEC 미배포 시 graceful fallback
**Given** `StockForumHourly` 테이블이 존재하지 않음 (SPEC-AI-008 미배포)
**When** `analyze_stock()`이 호출됨
**Then** 예외가 raise되지 않음
**And** 프롬프트에 `"## 1-2. 종토방 감성"` 섹션이 포함되지 않음
**And** 분석 결과는 정상적으로 생성되며 기존 섹션(뉴스 센티먼트 포함)은 유지됨
**And** 로그에 "forum sentiment unavailable, skipped" 등 안내 로그가 기록됨

### Scenario 4: 증권사 컨센서스 strong_buy 표시
**Given** SPEC-AI-009 배포 완료 및 `_gather_securities_consensus()`가 `consensus_signal="strong_buy"`, `avg_target_price=50000`, `premium_pct=20.5` 반환
**When** `analyze_stock()`이 호출됨
**Then** 프롬프트에 `"## 9-1. 증권사 컨센서스"` 섹션이 포함됨
**And** `avg_target_price=50000` 및 `premium_pct=20.5%` 값이 표시됨
**And** 긍정적 컨센서스를 나타내는 노트(예: "애널리스트 강한 매수 의견")가 포함됨
**And** buy/hold/sell 비율이 표시됨

### Scenario 5: 댓글 급증 단독 감지 (과열 미발생)
**Given** `_gather_forum_sentiment()`가 `volume_surge=True`, `overheating_alert=False` 반환
**When** `analyze_stock()`이 호출됨
**Then** 프롬프트에 `"종토방 댓글 급증 감지"` 문구가 포함됨
**And** 프롬프트에 `"과열 상태"` 문구는 포함되지 **않음**
**And** "공시/뉴스와 교차 확인 필요" 안내 문구가 포함됨

### Scenario 6: 성능 회귀 가드
**Given** 모든 신규 데이터 소스(뉴스/종토방/컨센서스)가 정상 제공됨
**When** `analyze_stock()`를 10회 연속 실행하여 평균 응답 시간 측정
**Then** SPEC-AI-010 배포 전 기준선 대비 평균 실행 시간 증가가 500ms 이내
**And** 95th percentile 응답 시간도 기준선 대비 500ms 이내 증가

## Additional Edge Cases

### Edge Case 1: 종토방 데이터 부분 존재
**Given** `StockForumHourly` 테이블은 존재하나 해당 `stock_id`에 대한 레코드가 없음
**When** `_gather_forum_sentiment()`가 None 또는 빈 결과 반환
**Then** 프롬프트에서 섹션 1-2가 생략되고 예외 없이 진행

### Edge Case 2: 컨센서스 caution 신호
**Given** `consensus_signal="caution"` 반환
**When** `analyze_stock()` 호출
**Then** 프롬프트 섹션 9-1에 경고 노트 포함 (예: "애널리스트 주의 의견")

### Edge Case 3: 두 신규 채널 모두 미제공
**Given** 두 함수 모두 None 반환 (데이터 없음)
**When** `analyze_stock()` 호출
**Then** 프롬프트는 기존 SPEC-AI-010 이전과 동일한 구조 유지
**And** 분석 결과는 뉴스 센티먼트 기반으로 정상 생성

### Edge Case 4: 종토방 낙관 과다 + 뉴스 긍정
**Given** 뉴스 센티먼트 긍정, 종토방 낙관 비율 90% 이상, `overheating_alert=True`
**When** `analyze_stock()` 호출
**Then** 프롬프트에 "역발상 경계" 해석 지시 포함
**And** AI가 단순 매수 신호로 판단하지 않도록 맥락 제공

## Quality Gate Criteria

- [ ] 기존 뉴스 센티먼트 섹션(1-1) 및 리포트 섹션(9)는 변경되지 않음 — diff 검증
- [ ] 두 신규 데이터 수집 호출은 try-except로 보호되어 graceful fallback 동작
- [ ] 프롬프트 내 신규 섹션 헤더는 정확히 `"## 1-2. 종토방 감성 (역발상 지표)"` 및 `"## 9-1. 증권사 컨센서스"`
- [ ] `overheating_alert` 및 `volume_surge`에 대한 조건부 경고 문구가 REQ 명세와 일치
- [ ] `consensus_signal` 값에 따른 조건부 노트가 REQ-SENTIMENT-007과 일치
- [ ] 성능 회귀 테스트 통과 (500ms 이내 증가)
- [ ] 종토방 센티먼트가 단독 매수/매도 신호로 사용되지 않음 — 코드 리뷰 확인
- [ ] `FundSignal` 모델 스키마 미변경 — migration 파일 추가 없음 확인

## Definition of Done

- [ ] 모든 REQ-SENTIMENT-001 ~ 008 요구사항 구현 완료
- [ ] Given-When-Then 시나리오 1~6 모두 통과
- [ ] Edge Case 1~4 모두 통과
- [ ] 기존 `analyze_stock` 기반 통합 테스트 전체 통과 (regression 없음)
- [ ] graceful fallback 시나리오(SPEC-AI-008/009 미배포) 단위 테스트 작성 및 통과
- [ ] `@MX:ANCHOR` (analyze_stock), `@MX:NOTE` (신규 섹션, fallback 블록) 태그 부착 완료
- [ ] 성능 벤치마크 결과가 acceptance 기준 충족 (500ms 이내)
- [ ] 코드 리뷰에서 기존 뉴스 센티먼트 로직 미변경 확인
- [ ] 로그에 각 채널 데이터 가용성 정보가 기록됨 (observability)
- [ ] Korean 주석 및 문서 작성 (language.yaml 설정 준수)
