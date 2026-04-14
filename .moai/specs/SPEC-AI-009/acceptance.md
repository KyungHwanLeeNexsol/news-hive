# SPEC-AI-009 Acceptance Criteria

## 시나리오 (Given-When-Then)

### Scenario 1: 평균/프리미엄 정상 계산

**Given**:
- 특정 종목의 최근 90일 SecuritiesReport 5건 존재
- 각 리포트의 `target_price = [85000, 90000, 92000, 88000, 95000]`
- `current_price = 80000`
- Opinion 분포: 매수 3건, 중립 1건, 매도 1건

**When**:
- `_gather_securities_consensus(db, stock_id, 80000)` 호출

**Then**:
- `report_count == 5`
- `avg_target_price == 90000` (합계 450000 / 5)
- `median_target_price == 90000`
- `price_range == {"min": 85000, "max": 95000}`
- `premium_pct == 12.5` ((90000 - 80000) / 80000 * 100)
- `buy_ratio == 0.6`, `hold_ratio == 0.2`, `sell_ratio == 0.2`

### Scenario 2: Strong Buy 신호 발생

**Given**:
- 최근 90일 리포트 5건
- Opinion: 매수 4건, 중립 0건, 매도 1건 (buy_ratio = 0.8)
- `avg_target_price = 118000`, `current_price = 100000` (premium = 18.0%)

**When**:
- `_gather_securities_consensus(db, stock_id, 100000)` 호출

**Then**:
- `buy_ratio == 0.8` (>= 0.7 충족)
- `premium_pct == 18.0` (>= 15 충족)
- `report_count == 5` (>= 3 충족)
- `consensus_signal == "strong_buy"`

### Scenario 3: target_price 전부 None (Insufficient 신호)

**Given**:
- 최근 90일 리포트 4건 존재
- 모든 리포트의 `target_price IS NULL`
- Opinion: 매수 2건, 중립 2건

**When**:
- `_gather_securities_consensus(db, stock_id, 50000)` 호출

**Then**:
- `report_count == 4` (opinion은 집계됨)
- `avg_target_price is None`
- `median_target_price is None`
- `price_range is None`
- `premium_pct is None`
- `buy_ratio == 0.5`, `hold_ratio == 0.5`, `sell_ratio == 0.0`
- `consensus_signal == "insufficient"` (target_price 샘플 부족)

### Scenario 4: Target Price 상승 추세

**Given**:
- 최근 30일 내 리포트 3건의 `avg_target_price = 90000`
- 31~90일 구간 리포트 3건의 `avg_target_price = 80000`

**When**:
- Trend 계산 수행

**Then**:
- 변화율 = (90000 - 80000) / 80000 = 0.125 (12.5%, >= 3%)
- `target_price_trend == "rising"`

### Scenario 5: Caution 신호 (매도 우세)

**Given**:
- 최근 90일 리포트 5건
- Opinion: 매수 1건, 중립 1건, 매도 3건 (sell_ratio = 0.6)
- `avg_target_price = 110000`, `current_price = 100000` (premium = 10%, 양수)

**When**:
- `_gather_securities_consensus(db, stock_id, 100000)` 호출

**Then**:
- `sell_ratio == 0.6` (>= 0.5 충족)
- `consensus_signal == "caution"` (premium_pct와 무관하게 sell_ratio 우선)

## Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| `report_count == 0` (90일 내 리포트 없음) | 모든 값 None/0, `consensus_signal == "insufficient"`, AI 프롬프트 섹션 완전 생략 |
| `report_count == 1` | `consensus_signal == "insufficient"` (최소 3건 미달) |
| `report_count == 2` | `consensus_signal == "insufficient"` |
| `current_price == 0` 또는 None | `premium_pct = None`, division by zero 방지 |
| Opinion 한국어 미매핑 값 (예: "지켜봄") | 해당 리포트는 buy/hold/sell 집계에서 제외 + 경고 로그 |
| 최근 30일 샘플 0건 | `target_price_trend == "stable"` |
| 31-90일 샘플 0건 | `target_price_trend == "stable"` |
| `target_price` 있는 리포트 1건만 | avg = 단일값, median = 단일값, trend = "stable" |
| 동일 증권사 중복 리포트 | 모두 개별 집계 (중복 제거 없음) |
| 매우 큰 `target_price` (outlier) | 평균과 중앙값 모두 계산, 이상치 제거 로직 없음 |

## Quality Gate Criteria

- `_gather_securities_consensus()` 함수는 pytest 단위 테스트에서 5개 시나리오 전부 통과
- `analyze_stock()` 통합 테스트: 신규 섹션이 프롬프트 문자열에 포함됨을 검증
- 기존 `_gather_securities_reports()` 테스트는 회귀 없음 (14일 윈도우 동작 불변)
- 함수 실행 시간 < 50ms (로컬 DB 기준, 종목당)
- Opinion 매핑 미매핑 비율이 5% 이하로 로그 모니터링 가능
- AI 프롬프트 토큰 증가량 종목당 평균 < 200 토큰 (BPE 기준)

## Definition of Done

- [ ] `_gather_securities_consensus()` 함수 구현 완료
- [ ] Signal 결정 로직 5단계 우선순위 구현
- [ ] Trend 결정 로직 구현 (30일 vs 31-90일 비교)
- [ ] Opinion 한국어 매핑 정규화 딕셔너리 정의
- [ ] `analyze_stock()` 프롬프트에 "## 9-1. 증권사 컨센서스" 섹션 통합
- [ ] 5개 acceptance 시나리오 모두 통과하는 pytest 단위 테스트 작성
- [ ] Edge case 10개 중 최소 7개 커버
- [ ] `report_count == 0` 시 프롬프트 섹션 완전 생략 검증
- [ ] @MX:ANCHOR 태그 부착 (`_gather_securities_consensus`)
- [ ] 기존 `_gather_securities_reports()` 회귀 없음 확인
- [ ] 실제 운영 종목 대상 통합 테스트 1회 실행 및 프롬프트 샘플 검토
- [ ] 코드 리뷰 통과 (TRUST 5: Tested, Readable, Unified, Secured, Trackable)
