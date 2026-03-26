---
id: SPEC-NEWS-001
type: acceptance
version: "1.0.0"
---

# SPEC-NEWS-001: 인수 기준서

## 1. 정상 케이스: 뉴스 저장 후 스냅샷 캡처 성공

### Scenario 1.1: 단일 뉴스 기사의 연관 종목 가격 스냅샷

```gherkin
Given 섹터 "건설기계"에 종목 "대창단조"(stock_id=45)가 등록되어 있다
  And "대창단조"의 현재 주가가 15,200원이다
  And 뉴스 크롤러가 새 기사 "현대제철 중기사업부 매각 검토"를 수집했다
  And AI 분류기가 해당 뉴스를 "대창단조"(stock_id=45)에 indirect로 매핑했다
When 뉴스 기사와 news_stock_relations가 DB에 커밋된다
Then news_price_impact 테이블에 새 레코드가 생성된다
  And 해당 레코드의 stock_id는 45이다
  And 해당 레코드의 price_at_news는 15200.0이다
  And 해당 레코드의 captured_at은 현재 시각이다
  And 해당 레코드의 price_after_1d, price_after_5d는 null이다
```

### Scenario 1.2: 다수 종목에 매핑된 뉴스의 일괄 캡처

```gherkin
Given 뉴스 "반도체 수출 호조"가 "삼성전자"(stock_id=10)와 "SK하이닉스"(stock_id=11)에 매핑되었다
  And "삼성전자" 현재가 72,000원, "SK하이닉스" 현재가 185,000원이다
When 뉴스 기사와 relations가 DB에 커밋된다
Then news_price_impact 테이블에 2개의 레코드가 생성된다
  And stock_id=10 레코드의 price_at_news는 72000.0이다
  And stock_id=11 레코드의 price_at_news는 185000.0이다
```

### Scenario 1.3: sector_id만 있는 관계는 스냅샷 생성 안함

```gherkin
Given 뉴스 "건설업 전망"이 섹터 "건설기계"(sector_id=3)에만 매핑되었다
  And 해당 news_stock_relations의 stock_id는 null이다
When 뉴스 기사와 relations가 DB에 커밋된다
Then 해당 relation에 대해 news_price_impact 레코드가 생성되지 않는다
```

---

## 2. 백필 케이스: 1일 후 스케줄러가 수익률 업데이트

### Scenario 2.1: 1D 백필 정상 처리

```gherkin
Given news_price_impact 레코드가 존재한다
  And 해당 레코드의 captured_at이 어제(1일 전)이다
  And 해당 레코드의 price_at_news가 15,200원이다
  And 해당 레코드의 price_after_1d가 null이다
  And 해당 종목의 현재가가 15,800원이다
When 18:30 KST 백필 스케줄러가 실행된다
Then 해당 레코드의 price_after_1d가 15800.0으로 업데이트된다
  And 해당 레코드의 return_1d_pct가 3.95로 업데이트된다 ((15800-15200)/15200*100)
  And 해당 레코드의 backfill_1d_at이 현재 시각으로 설정된다
```

### Scenario 2.2: 5D 백필 정상 처리

```gherkin
Given news_price_impact 레코드가 존재한다
  And 해당 레코드의 captured_at이 5일 전이다
  And 해당 레코드의 price_at_news가 15,200원이다
  And 해당 레코드의 price_after_1d가 이미 채워져 있다
  And 해당 레코드의 price_after_5d가 null이다
  And 해당 종목의 현재가가 16,100원이다
When 18:30 KST 백필 스케줄러가 실행된다
Then 해당 레코드의 price_after_5d가 16100.0으로 업데이트된다
  And 해당 레코드의 return_5d_pct가 5.92로 업데이트된다
  And 해당 레코드의 backfill_5d_at이 현재 시각으로 설정된다
```

### Scenario 2.3: 이미 백필 완료된 레코드는 건너뛰기

```gherkin
Given news_price_impact 레코드의 backfill_1d_at이 이미 설정되어 있다
When 18:30 KST 백필 스케줄러가 실행된다
Then 해당 레코드의 price_after_1d는 변경되지 않는다
  And 해당 레코드의 backfill_1d_at도 변경되지 않는다
```

---

## 3. API 실패 케이스: 가격 API 실패 시 나머지 계속 처리

### Scenario 3.1: 스냅샷 캡처 중 일부 종목 API 실패

```gherkin
Given 뉴스가 "삼성전자"(stock_id=10)와 "SK하이닉스"(stock_id=11)에 매핑되었다
  And "삼성전자"의 가격 API 호출이 실패한다
  And "SK하이닉스"의 현재가는 185,000원이다
When 가격 스냅샷 캡처가 실행된다
Then stock_id=10에 대한 news_price_impact 레코드는 생성되지 않는다
  And stock_id=11에 대한 news_price_impact 레코드는 정상 생성된다
  And price_at_news는 185000.0이다
  And 실패한 종목에 대한 경고 로그가 기록된다
```

### Scenario 3.2: 백필 중 API 실패 시 3회 재시도 후 null 유지

```gherkin
Given news_price_impact 레코드의 price_after_1d가 null이다
  And 해당 종목의 가격 API 호출이 계속 실패한다
When 18:30 KST 백필 스케줄러가 실행된다
Then 시스템은 해당 종목에 대해 최대 3회 재시도한다
  And 3회 모두 실패 시 price_after_1d는 null로 유지된다
  And backfill_1d_at은 null로 유지된다 (다음 스케줄에서 재시도 가능)
  And 다른 레코드의 백필 처리는 정상적으로 계속된다
```

---

## 4. 7일 삭제 케이스: 뉴스 삭제 후에도 impact 레코드 보존

### Scenario 4.1: 뉴스 기사 삭제 시 impact 레코드 유지

```gherkin
Given news_price_impact 레코드가 존재한다 (news_id=100, stock_id=45)
  And 해당 레코드의 모든 백필이 완료되었다
  And 7일이 경과하여 news_articles에서 id=100 기사가 삭제된다
When 뉴스 기사 삭제 처리가 실행된다
Then news_price_impact 레코드는 삭제되지 않고 유지된다
  And 해당 레코드의 news_id는 null로 변경된다
  And 해당 레코드의 stock_id, price_at_news, return_1d_pct, return_5d_pct는 그대로 유지된다
```

### Scenario 4.2: 90일 경과 후 impact 레코드 삭제

```gherkin
Given news_price_impact 레코드의 created_at이 91일 전이다
When 03:00 KST 정리 스케줄러가 실행된다
Then 해당 레코드는 news_price_impact 테이블에서 삭제된다
```

### Scenario 4.3: 89일 경과 레코드는 보존

```gherkin
Given news_price_impact 레코드의 created_at이 89일 전이다
When 03:00 KST 정리 스케줄러가 실행된다
Then 해당 레코드는 news_price_impact 테이블에서 삭제되지 않는다
```

---

## 5. 통계 API 케이스: 30일 뉴스 패턴 통계 정확히 반환

### Scenario 5.1: 완료된 데이터로 통계 계산

```gherkin
Given stock_id=45에 대한 최근 30일 내 news_price_impact 레코드가 8건이다
  And 8건 모두 backfill_1d_at이 설정되어 있다 (1D 백필 완료)
  And return_1d_pct 값이 [3.95, -1.2, 2.1, 0.5, -0.8, 4.2, 1.5, -2.1]이다
  And 양수 수익률(승) 5건, 음수 수익률(패) 3건이다
When GET /api/stocks/45/news-impact-stats를 호출한다
Then 응답의 stats_1d.avg_return_pct는 1.01이다 (8건 평균)
  And stats_1d.win_rate_pct는 62.5이다 (5/8 * 100)
  And stats_1d.max_return_pct는 4.2이다
  And stats_1d.min_return_pct는 -2.1이다
  And total_news_count는 8이다
  And completed_count는 8이다
```

### Scenario 5.2: 데이터가 없는 종목의 통계

```gherkin
Given stock_id=99에 대한 news_price_impact 레코드가 0건이다
When GET /api/stocks/99/news-impact-stats를 호출한다
Then 응답의 total_news_count는 0이다
  And completed_count는 0이다
  And stats_1d, stats_5d는 null이다
  And 응답 HTTP 상태 코드는 200이다
```

### Scenario 5.3: 뉴스별 impact 조회

```gherkin
Given news_id=100에 연관된 news_price_impact 레코드가 2건이다
  And stock_id=45 (대창단조), stock_id=46 (진성이엔씨)
When GET /api/news/100/impact를 호출한다
Then 응답의 impacts 배열 길이는 2이다
  And 각 항목에 stock_name, price_at_news, return_1d_pct, return_5d_pct가 포함된다
```

---

## 6. 브리핑 강화 케이스: 통계가 있을 때 AI 프롬프트에 포함

### Scenario 6.1: 통계 데이터가 있는 종목의 브리핑 강화

```gherkin
Given 데일리 브리핑 대상 종목 "대창단조"(stock_id=45)가 있다
  And stock_id=45의 최근 30일 뉴스 패턴 통계가 존재한다
  And stats_1d.avg_return_pct=1.23, stats_1d.win_rate_pct=62.5이다
When 08:30 KST 브리핑 생성이 실행된다
Then AI 프롬프트에 "대창단조: 최근 30일 뉴스 후 1일 평균 수익률 1.23%, 승률 62.5%" 형식의 통계가 포함된다
```

### Scenario 6.2: 통계 데이터가 없는 종목은 생략

```gherkin
Given 데일리 브리핑 대상 종목 "신규종목"(stock_id=99)가 있다
  And stock_id=99의 news_price_impact 레코드가 0건이다
When 08:30 KST 브리핑 생성이 실행된다
Then AI 프롬프트에 stock_id=99의 뉴스 패턴 통계 섹션은 포함되지 않는다
  And 브리핑 생성은 정상적으로 완료된다
```

---

## 7. Quality Gate 기준

### 7.1 기능 완료 기준 (Definition of Done)

- [ ] 모든 6개 시나리오 그룹의 테스트가 통과한다
- [ ] `NewsPriceImpact` 모델이 Alembic 마이그레이션으로 적용된다
- [ ] 기존 뉴스 수집 파이프라인이 깨지지 않는다 (회귀 없음)
- [ ] 가격 API 실패 시 전체 프로세스가 중단되지 않는다
- [ ] 7일 뉴스 삭제 후에도 impact 레코드가 보존된다
- [ ] 90일 경과 레코드가 자동 삭제된다

### 7.2 성능 기준

- [ ] 스냅샷 캡처: 50종목 기준 10초 이내 완료
- [ ] 백필 스케줄러: 1000건 기준 60초 이내 완료
- [ ] 통계 API 응답: P95 500ms 이내
- [ ] 90일 정리 작업: 10000건 기준 30초 이내 완료

### 7.3 코드 품질 기준

- [ ] 테스트 커버리지 85% 이상 (신규 코드)
- [ ] ruff/black 포맷팅 통과
- [ ] 타입 힌트 100% (신규 함수)
- [ ] @MX 태그 적용 완료

### 7.4 검증 방법

| 검증 항목              | 방법                                           |
| ---------------------- | ---------------------------------------------- |
| 스냅샷 캡처            | pytest + mock 가격 API                         |
| 백필 로직              | pytest + 시간 조작 (freezegun)                 |
| API 실패 격리          | pytest + 가격 API 예외 주입                    |
| FK SET NULL            | pytest + 실제 DB 레코드 삭제                   |
| 통계 API 정확도        | pytest + 사전 정의 데이터셋                    |
| 브리핑 프롬프트 통합   | pytest + AI 프롬프트 문자열 검증               |
| 90일 정리              | pytest + 날짜 조작                             |
