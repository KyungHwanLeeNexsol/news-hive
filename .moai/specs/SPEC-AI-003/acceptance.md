---
id: SPEC-AI-003
version: 1.0.0
status: Planned
created: 2026-03-31
updated: 2026-03-31
author: manager-spec
priority: High
tags: [leading-indicator, acceptance-criteria, test-scenarios]
---

# SPEC-AI-003 수락 기준: 선행 매수 신호 탐지

## 1. 핵심 원칙 검증

### TC-001: 이미 상승한 종목 제외 (REQ-AI-030)

```gherkin
Scenario: 당일 등락률 +3% 초과 종목은 선행 후보에서 제외
  Given 종목 A의 change_rate가 +4.5%
  And 종목 A의 foreign_net_5d > 0 AND institution_net_5d > 0
  When _gather_leading_candidates()가 실행되면
  Then 종목 A는 결과 리스트에 포함되지 않아야 한다

Scenario: 당일 등락률 +3% 이하 종목은 후보 유지
  Given 종목 B의 change_rate가 +2.5%
  And 종목 B가 조용한 수급 축적 조건을 충족
  When _gather_leading_candidates()가 실행되면
  Then 종목 B는 결과 리스트에 포함되어야 한다

Scenario: 당일 등락률 -5% 미만 종목도 제외
  Given 종목 C의 change_rate가 -6.2%
  When _scan_market_stocks()가 실행되면
  Then 종목 C는 1차 필터에서 제외되어야 한다
```

### TC-002: 기존 검증 기준 적용 (REQ-AI-031)

```gherkin
Scenario: 선행 후보도 기존 4가지 검증 기준을 통과해야 함
  Given 종목 D가 조용한 수급 축적 후보로 감지됨
  And 종목 D의 change_rate가 -4% (기존 기준: > -3% 필요)
  When 최종 검증 단계가 실행되면
  Then 종목 D는 최종 후보에서 제외되어야 한다

Scenario: 기존 4가지 중 3가지 이상 충족 시 통과
  Given 종목 E가 선행 후보로 감지됨
  And 종목 E가 등락률(> -3%), 5일 양의 추세, 수급 양호를 충족
  And 종목 E의 밸류에이션은 미충족 (PER > 업종 평균)
  When 최종 검증 단계가 실행되면
  Then 종목 E는 최종 후보에 포함되어야 한다 (3/4 충족)
```

---

## 2. 선행 지표 1: 조용한 수급 축적

### TC-003: 조용한 수급 축적 감지 (REQ-AI-032, REQ-AI-033)

```gherkin
Scenario: 외국인+기관 동시 순매수 + 가격 미반영 = 감지
  Given 종목 F의 foreign_net_5d가 5,000주
  And 종목 F의 institution_net_5d가 3,000주
  And 종목 F의 change_rate가 +0.5%
  When _detect_quiet_accumulation()이 실행되면
  Then 종목 F가 결과에 포함되어야 한다
  And leading_signals에 type "quiet_accumulation"이 포함되어야 한다

Scenario: 외국인 순매수이나 기관 순매도 = 미감지
  Given 종목 G의 foreign_net_5d가 10,000주
  And 종목 G의 institution_net_5d가 -2,000주
  When _detect_quiet_accumulation()이 실행되면
  Then 종목 G는 결과에 포함되지 않아야 한다

Scenario: 강한 신호 판정 - 순매수량이 일평균 거래량의 10% 이상
  Given 종목 H의 foreign_net_5d + institution_net_5d가 15,000주
  And 종목 H의 일평균 거래량이 100,000주
  And 순매수 비율이 15% (>= 10%)
  When _detect_quiet_accumulation()이 실행되면
  Then 종목 H의 신호 강도가 "strong"이어야 한다

Scenario: 보통 신호 판정 - 순매수량이 일평균 거래량의 10% 미만
  Given 종목 I의 foreign_net_5d + institution_net_5d가 5,000주
  And 종목 I의 일평균 거래량이 200,000주
  And 순매수 비율이 2.5% (< 10%)
  When _detect_quiet_accumulation()이 실행되면
  Then 종목 I의 신호 강도가 "moderate"이어야 한다

Scenario: 가격이 이미 반영된 경우 미감지 (change_rate > +2%)
  Given 종목 J의 foreign_net_5d > 0 AND institution_net_5d > 0
  And 종목 J의 change_rate가 +2.8%
  When _detect_quiet_accumulation()이 실행되면
  Then 종목 J는 결과에 포함되지 않아야 한다
```

---

## 3. 선행 지표 2: 뉴스-가격 괴리

### TC-004: 뉴스-가격 괴리 감지 (REQ-AI-034, REQ-AI-035)

```gherkin
Scenario: 긍정 뉴스 발행 후 가격 미반영 = 감지
  Given 종목 K에 2시간 전 긍정 감성 뉴스 1건 발행
  And 종목 K의 change_rate가 +0.3%
  When _detect_news_price_divergence()가 실행되면
  Then 종목 K가 결과에 포함되어야 한다
  And leading_signals에 type "news_divergence"가 포함되어야 한다

Scenario: 긍정 뉴스 발행 후 이미 가격 반영 = 미감지
  Given 종목 L에 1시간 전 긍정 감성 뉴스 1건 발행
  And 종목 L의 change_rate가 +3.5%
  When _detect_news_price_divergence()가 실행되면
  Then 종목 L은 결과에 포함되지 않아야 한다

Scenario: 부정 뉴스는 괴리 탐지 대상이 아님
  Given 종목 M에 1시간 전 부정 감성 뉴스 1건 발행
  And 종목 M의 change_rate가 +0.1%
  When _detect_news_price_divergence()가 실행되면
  Then 종목 M은 결과에 포함되지 않아야 한다

Scenario: 복수 긍정 뉴스 = 강한 신호
  Given 종목 N에 2시간 이내 긍정 감성 뉴스 3건 발행
  And 종목 N의 change_rate가 +0.5%
  When _detect_news_price_divergence()가 실행되면
  Then 종목 N의 신호 강도가 "strong"이어야 한다

Scenario: 3시간 초과 뉴스는 대상에서 제외
  Given 종목 O에 4시간 전 긍정 감성 뉴스 1건 발행
  And 종목 O의 change_rate가 +0.2%
  When _detect_news_price_divergence()가 실행되면
  Then 종목 O는 결과에 포함되지 않아야 한다
```

---

## 4. 선행 지표 3: 볼린저밴드 수축

### TC-005: 밴드 수축 감지 (REQ-AI-036, REQ-AI-037)

```gherkin
Scenario: 밴드 폭 수축 + 거래량 감소 = 감지
  Given 종목 P의 현재 bb_width가 3.2%
  And 종목 P의 20일 평균 bb_width가 8.0%
  And 현재 bb_width / 평균 bb_width = 40% (< 50%)
  And 종목 P의 volume_ratio가 0.5 (< 0.7)
  And 종목 P의 sma_20_slope >= 0
  When _detect_bb_compression()이 실행되면
  Then 종목 P가 결과에 포함되어야 한다
  And leading_signals에 type "bb_compression"이 포함되어야 한다

Scenario: 밴드 수축이나 거래량이 정상 수준 = 미감지
  Given 종목 Q의 현재 bb_width가 20일 평균의 45% (< 50%)
  And 종목 Q의 volume_ratio가 0.9 (>= 0.7)
  When _detect_bb_compression()이 실행되면
  Then 종목 Q는 결과에 포함되지 않아야 한다

Scenario: 하향 추세 종목 제외 (REQ-AI-037)
  Given 종목 R의 bb_width가 20일 평균의 40% (< 50%)
  And 종목 R의 volume_ratio가 0.5 (< 0.7)
  And 종목 R의 sma_20_slope가 -1.5% (< 0)
  When _detect_bb_compression()이 실행되면
  Then 종목 R은 결과에 포함되지 않아야 한다

Scenario: 주가 히스토리 부족 시 건너뛰기
  Given 종목 S의 상장일이 10일 전 (히스토리 < 20일)
  When _detect_bb_compression()이 실행되면
  Then 종목 S는 에러 없이 건너뛰어야 한다
```

---

## 5. 선행 지표 4: 섹터 로테이션 낙오자

### TC-006: 섹터 낙오자 감지 (REQ-AI-038, REQ-AI-039)

```gherkin
Scenario: 모멘텀 섹터 내 낙오 종목 = 감지
  Given "반도체" 섹터가 momentum_sector로 태그됨
  And "반도체" 섹터 평균 5일 수익률이 +5.2%
  And 종목 T(반도체)의 5일 수익률이 +1.8% (섹터 평균 미만)
  When _detect_sector_laggards()가 실행되면
  Then 종목 T가 결과에 포함되어야 한다
  And leading_signals에 type "sector_laggard"가 포함되어야 한다

Scenario: 섹터 평균 이상 수익률 = 미감지
  Given "반도체" 섹터가 momentum_sector로 태그됨
  And 섹터 평균 5일 수익률이 +5.2%
  And 종목 U(반도체)의 5일 수익률이 +6.0% (섹터 평균 이상)
  When _detect_sector_laggards()가 실행되면
  Then 종목 U는 결과에 포함되지 않아야 한다

Scenario: 강한 신호 - 섹터 평균 대비 -3%p 이상 괴리
  Given "2차전지" 섹터가 momentum_sector로 태그됨
  And 섹터 평균 5일 수익률이 +4.0%
  And 종목 V(2차전지)의 5일 수익률이 +0.5% (괴리: -3.5%p)
  When _detect_sector_laggards()가 실행되면
  Then 종목 V의 신호 강도가 "strong"이어야 한다

Scenario: 비모멘텀 섹터 종목은 대상 아님
  Given "건설" 섹터가 momentum_sector가 아님
  And 종목 W(건설)의 5일 수익률이 섹터 평균 미만
  When _detect_sector_laggards()가 실행되면
  Then 종목 W는 결과에 포함되지 않아야 한다
```

---

## 6. 통합 및 랭킹

### TC-007: 복수 지표 가중 합산 (REQ-AI-040)

```gherkin
Scenario: 2개 지표에 동시 감지된 종목은 높은 점수
  Given 종목 X가 "quiet_accumulation" (점수 30)으로 감지됨
  And 종목 X가 "news_divergence" (점수 25)로도 감지됨
  And 복수 지표 가산점 +10
  When 통합 랭킹이 실행되면
  Then 종목 X의 총점은 65 (30 + 25 + 10)이어야 한다
  And 종목 X의 leading_signals에 2개 지표가 모두 포함되어야 한다

Scenario: 강한 신호 보너스 적용
  Given 종목 Y가 "quiet_accumulation" (점수 30, 강함: +15)으로 감지됨
  When 통합 랭킹이 실행되면
  Then 종목 Y의 총점은 45 (30 + 15)이어야 한다
```

### TC-008: 선행+뉴스 후보 병합 (REQ-AI-042)

```gherkin
Scenario: 선행 후보와 뉴스 기반 후보 병합
  Given 선행 후보 7개, 뉴스 기반 후보 5개 (중복 2개)
  When 후보 병합이 실행되면
  Then 최종 후보는 최대 10개여야 한다
  And 선행 후보가 상위에 배치되어야 한다
  And 중복 종목은 선행 후보의 leading_signals를 유지하되 한 번만 포함

Scenario: 선행 후보만 존재 (뉴스 후보 0개)
  Given 선행 후보 8개, 뉴스 기반 후보 0개
  When 후보 병합이 실행되면
  Then 최종 후보는 8개여야 한다

Scenario: 선행 후보 0개 (폴백)
  Given 선행 후보 0개, 뉴스 기반 후보 6개
  When 후보 병합이 실행되면
  Then 최종 후보는 뉴스 기반 6개여야 한다
```

---

## 7. 브리핑 프롬프트 통합

### TC-009: leading_signals 메타데이터 전달 (REQ-AI-043, REQ-AI-044)

```gherkin
Scenario: AI 프롬프트에 선행 지표 정보 포함
  Given 종목 Z가 leading_signals를 가진 선행 후보
  And leading_signals가 [{"type": "quiet_accumulation", "strength": "strong", "detail": "외국인+기관 5일 순매수 12,000주"}]
  When AI 브리핑 프롬프트가 생성되면
  Then 종목 Z 데이터에 leading_signals 필드가 포함되어야 한다
  And 프롬프트에 "선행 신호 기반 종목은 아직 가격이 움직이지 않은 종목" 설명이 포함되어야 한다

Scenario: 뉴스 기반 후보에는 leading_signals가 없음
  Given 종목 AA가 뉴스 기반 후보 (선행 신호 없음)
  When AI 브리핑 프롬프트가 생성되면
  Then 종목 AA 데이터에 leading_signals 필드가 없어야 한다
```

---

## 8. 에러 처리

### TC-010: 부분 실패 시 graceful degradation (REQ-AI-045)

```gherkin
Scenario: 조용한 수급 탐지 실패, 나머지 성공
  Given _detect_quiet_accumulation()이 네트워크 오류로 실패
  And 나머지 3개 지표는 정상 감지
  When _gather_leading_candidates()가 실행되면
  Then 3개 지표 결과만으로 후보가 구성되어야 한다
  And 에러 로그가 기록되어야 한다

Scenario: 전체 선행 지표 실패
  Given 4개 선행 지표 모두 예외 발생
  When _gather_leading_candidates()가 실행되면
  Then 빈 리스트를 반환해야 한다
  And _gather_pick_candidates() 결과만으로 브리핑이 생성되어야 한다

Scenario: 전종목 스캔 실패
  Given fetch_naver_stock_list()가 네트워크 오류로 실패
  When _gather_leading_candidates()가 실행되면
  Then 빈 리스트를 반환해야 한다
  And 에러 로그에 "전종목 스캔 실패" 메시지가 포함되어야 한다
```

---

## 9. 성능 기준

### TC-011: 실행 시간 제한

```gherkin
Scenario: 전체 선행 신호 탐지가 60초 이내 완료
  Given KOSPI+KOSDAQ 250종목 대상
  When _gather_leading_candidates()가 실행되면
  Then 실행 시간이 60초를 초과하지 않아야 한다

Scenario: 타임아웃 시 확보된 결과만 반환
  Given 일부 API 호출이 지연되어 45초 타임아웃 도달
  When 타임아웃이 발생하면
  Then 그때까지 확보된 결과만으로 후보를 구성해야 한다
  And 타임아웃 경고 로그가 기록되어야 한다
```

### TC-012: API 호출 제한

```gherkin
Scenario: 동시 API 호출이 5개를 초과하지 않음
  Given asyncio.Semaphore(5) 설정
  When 100개 종목에 대해 시세 데이터 수집 시
  Then 동시 실행 API 호출이 5개를 초과하지 않아야 한다
```

---

## 10. Definition of Done

- [ ] `_gather_leading_candidates()` 함수가 구현되어 4개 선행 지표를 병렬 탐지
- [ ] 당일 등락률 +3% 초과 종목이 선행 후보에서 제외됨
- [ ] 각 선행 후보에 `leading_signals` 메타데이터가 포함됨
- [ ] 기존 `_gather_pick_candidates()`의 4가지 검증 기준이 최종 단계에서 적용됨
- [ ] 선행 후보와 뉴스 기반 후보가 올바르게 병합됨 (선행 우선, 최대 10개)
- [ ] AI 브리핑 프롬프트에 선행 지표 정보가 포함됨
- [ ] 부분 실패 시 graceful degradation 동작 확인
- [ ] 전체 탐지 소요 시간 60초 이내
- [ ] 모든 TC(TC-001 ~ TC-012) 테스트 시나리오 통과
- [ ] 로깅: 지표별 감지 수, 소요 시간, 병합 비율이 기록됨
