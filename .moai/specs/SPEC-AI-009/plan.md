# SPEC-AI-009 Implementation Plan

## 구현 접근 방식 (Technical Approach)

기존 `SecuritiesReport` 모델과 `fund_manager.py`의 `_gather_securities_reports()` 패턴을 재사용하여 신규 함수 `_gather_securities_consensus()`를 추가합니다. **신규 모델이나 마이그레이션은 필요하지 않습니다.** 집계는 `SQLAlchemy` 쿼리 + Python 통계 계산으로 수행하며, 결과는 `analyze_stock()` 내에서 AI 프롬프트에 삽입됩니다.

## 아키텍처 개요

```
analyze_stock(stock)
├─ _gather_market_data(stock)            # current_price 획득
├─ _gather_securities_reports(stock)     # 기존 14일 윈도우 리포트 리스트
├─ _gather_securities_consensus(stock, current_price)  # 신규 (90일 집계)
└─ build_prompt(...)
    ├─ "## 9. 증권사 리포트" (기존)
    └─ "## 9-1. 증권사 컨센서스" (신규)
```

## 파일 변경 목록 (Files to Modify)

### 수정 파일 (1개)

**`backend/app/services/fund_manager.py`**

1. 신규 함수 `_gather_securities_consensus(db, stock_id, current_price) -> dict` 추가 (현재 `_gather_securities_reports()` 이후, 약 line 408 이후)
2. `analyze_stock()` 내부에서 `_gather_securities_reports()` 호출 직후 `_gather_securities_consensus()` 호출 추가
3. AI 프롬프트 빌드 로직에 컨센서스 섹션 포맷팅 추가

### 신규 파일

없음

### 마이그레이션

없음 (기존 `SecuritiesReport` 테이블 재사용)

## 함수 시그니처 상세

### `_gather_securities_consensus()`

**Input**:
- `db: Session`
- `stock_id: int`
- `current_price: int | float` (from market_data)

**Output** (dict):

| Key | Type | Description |
|-----|------|-------------|
| `report_count` | `int` | 최근 90일 리포트 총 개수 |
| `avg_target_price` | `int \| None` | 목표주가 산술평균 (None: target_price 없음) |
| `median_target_price` | `int \| None` | 목표주가 중앙값 |
| `price_range` | `{"min": int, "max": int} \| None` | 목표주가 최소/최대 |
| `buy_ratio` | `float` | 매수 의견 비율 (0.0 ~ 1.0) |
| `hold_ratio` | `float` | 중립 의견 비율 |
| `sell_ratio` | `float` | 매도 의견 비율 |
| `premium_pct` | `float \| None` | `(avg_target - current) / current * 100` |
| `consensus_signal` | `str` | `"strong_buy" \| "buy" \| "neutral" \| "caution" \| "insufficient"` |
| `target_price_trend` | `str` | `"rising" \| "falling" \| "stable"` |
| `firms` | `list[str]` | 상위 3개 증권사 이름 |

## AI 프롬프트 통합

`analyze_stock()` 내 프롬프트 빌더에 아래 섹션을 기존 "## 9. 증권사 리포트" 바로 뒤에 삽입:

```
## 9-1. 증권사 컨센서스 (최근 90일, N개 리포트)
- 평균 목표주가: {avg_target_price:,}원 (현재가 대비 {premium_pct:+.1f}%)
- 중앙값: {median_target_price:,}원 (범위: {min:,} ~ {max:,}원)
- 의견 분포: 매수 {buy_ratio:.0%} / 중립 {hold_ratio:.0%} / 매도 {sell_ratio:.0%}
- 컨센서스 신호: {consensus_signal}
- 목표주가 추세: {target_price_trend}
- 주요 증권사: {firms[0]}, {firms[1]}, {firms[2]}
```

- `report_count < 3`인 경우: `"컨센서스 신호: 표본 부족 (N개 리포트)"`만 출력
- `avg_target_price is None`인 경우: 가격 관련 라인 생략, 의견 분포만 출력

## Signal 결정 로직 (우선순위 순)

1. `report_count < 3` → `"insufficient"`
2. `sell_ratio >= 0.5` **또는** `premium_pct < 0` → `"caution"`
3. `report_count >= 3` **및** `buy_ratio >= 0.7` **및** `premium_pct >= 15` → `"strong_buy"`
4. `buy_ratio >= 0.5` → `"buy"`
5. 그 외 → `"neutral"`

## Trend 결정 로직

- `recent_30d_avg = avg(target_price for reports in last 30 days)`
- `older_60d_avg = avg(target_price for reports in 31-90 days ago)`
- 두 구간 중 하나라도 샘플 < 2 → `"stable"`
- `(recent_30d_avg - older_60d_avg) / older_60d_avg >= 0.03` → `"rising"`
- `(recent_30d_avg - older_60d_avg) / older_60d_avg <= -0.03` → `"falling"`
- 그 외 → `"stable"`

## 마일스톤 (Priority-based)

### Priority High

- M1: `_gather_securities_consensus()` 함수 구현 (집계 쿼리 + dict 반환)
- M2: Signal / Trend 결정 로직 구현 및 단위 테스트
- M3: `analyze_stock()` 프롬프트에 컨센서스 섹션 삽입

### Priority Medium

- M4: Edge case 처리 (report_count=0, target_price 전부 None, 동점 신호)
- M5: 단위 테스트 작성 (acceptance.md의 5개 시나리오)

### Priority Low

- M6: MX 태그 부착 및 문서 업데이트
- M7: 로깅/모니터링 (컨센서스 계산 소요 시간)

## MX 태그 대상

- `_gather_securities_consensus()`: **@MX:ANCHOR** (`analyze_stock`에서 호출되며 fan_in 증가 예상)
  - REASON: 컨센서스 집계는 AI 프롬프트의 불변 계약(invariant contract)에 해당
- Signal 결정 로직 섹션: **@MX:NOTE** (우선순위 기반 분기 로직 설명)
- `_gather_securities_reports()`의 14일 윈도우: **@MX:NOTE** (Consensus와의 역할 분리 명시)

## 리스크 (Risks)

| 리스크 | 영향도 | 완화 방안 |
|--------|--------|-----------|
| Opinion 한국어 매핑 누락 (증권사별 표기 차이) | Medium | 정규화 dict + 미매핑 값 로깅, neutral로 fallback |
| `target_price=None`이 많아 샘플 부족 | Medium | `consensus_signal="insufficient"` + 의견 비율만 출력 |
| 90일 쿼리 성능 저하 | Low | `stock_id + published_at` 인덱스 확인 (이미 존재 예상) |
| 프롬프트 토큰 증가로 AI 비용 상승 | Low | 섹션당 200 토큰 이하 유지, `report_count=0` 시 섹션 생략 |

## 성능 고려사항

- 쿼리: `WHERE stock_id = ? AND published_at >= now() - 90 days` - 기존 인덱스 활용
- 집계: Python 레벨 통계 계산 (statistics 표준 모듈 또는 수동 계산) - 종목당 < 10ms
- 호출 빈도: `analyze_stock()`당 1회, 일일 분석 종목 수 × 1
