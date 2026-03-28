---
spec_id: SPEC-AI-001
type: implementation-plan
---

# SPEC-AI-001 구현 계획: AI 펀드 예측 시스템 고도화

## Phase A: 즉시 개선 (최우선)

### A1. 매수 필터링 임계값 완화 (REQ-AI-001)

**목표:** 매수 후보 종목 풀 확대

**기술 접근:**
- fund_manager.py 프롬프트 규칙 섹션(lines 921-938) 수정
  - change_rate 임계값: 0%/-1% -> -3%
  - 4-of-4 조건 -> 3-of-4 조건으로 완화
  - "조건부 매수 후보" 카테고리 추가
- AI 프롬프트에 조건 충족 현황 명시 (예: "3/4 조건 충족: [등락률 O, 추세 O, 수급 O, 밸류 X]")

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/services/fund_manager.py` | 프롬프트 규칙 수정 (lines 921-938) |

**리스크:** 낮음 - 프롬프트 텍스트 변경만 필요, AI가 최종 판단

---

### A2. 시간 가중 뉴스 스코어링 (REQ-AI-002)

**목표:** 최신 뉴스에 적절한 가중치 부여

**기술 접근:**
- `_gather_stock_news()` 함수에서 뉴스별 시간 가중치 계산
- 가중치 공식: `max(0.1, 1.0 - (hours_since_publish / 72) * 0.6)`
  - 0h: 1.0, 24h: 0.8, 48h: 0.6, 72h: 0.4
- 프롬프트에 뉴스 항목별 "[가중치: 0.8]" 표시
- 가중치순 정렬 후 AI에 전달

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/services/fund_manager.py` | `_gather_stock_news()` 가중치 로직, 프롬프트 정렬 |

**리스크:** 낮음 - 기존 뉴스 수집 로직에 가중치 필드 추가

---

### A3. 오류 패턴 분류 (REQ-AI-003)

**목표:** 시그널 실패 원인 체계적 분석

**기술 접근:**
- FundSignal 모델에 `error_category` 컬럼 추가 (Alembic migration)
- signal_verifier.py에서 검증 실패 시 AI 호출로 원인 분류
  - 입력: 시그널 당시 데이터 + 5일간 시장 데이터
  - 출력: 5개 카테고리 중 1개 선택
- `get_accuracy_stats()`에 error_category 분포 통계 추가
- daily_briefing 프롬프트에 "최근 오류 패턴 분포" 섹션 추가

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/models/fund_signal.py` | error_category 컬럼 추가 |
| `backend/app/services/signal_verifier.py` | 오류 분류 로직 추가 |
| `backend/app/services/fund_manager.py` | 프롬프트에 오류 패턴 피드백 주입 |
| `alembic/versions/` | 마이그레이션 파일 생성 |

**리스크:** 중간 - AI 분류의 정확도가 불확실, 수동 검증 기간 필요

---

### A4. 베이지안 신뢰도 보정 (REQ-AI-004)

**목표:** confidence 값의 통계적 의미 부여

**기술 접근:**
- FundSignal 모델에 `calibrated_confidence` 컬럼 추가
- signal_verifier.py에 보정 함수 추가:
  ```
  calibrate(raw_confidence):
    bucket = round(raw_confidence, 1)  # 0.1 단위 구간
    historical_accuracy = get_bucket_accuracy(bucket, days=90)
    return historical_accuracy if sample >= 10 else raw_confidence
  ```
- analyze_stock() 결과에 calibrated_confidence 적용
- API 응답에 양쪽 confidence 모두 포함

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/models/fund_signal.py` | calibrated_confidence 컬럼 추가 |
| `backend/app/services/signal_verifier.py` | 보정 함수 + 통계 산출 |
| `backend/app/services/fund_manager.py` | analyze_stock()에 보정 적용 |
| `backend/app/schemas/fund.py` | 응답 스키마에 calibrated_confidence 추가 |
| `alembic/versions/` | 마이그레이션 파일 생성 |

**리스크:** 낮음 - 데이터 충분 시 통계적으로 견고, 부족 시 원본 유지

---

## Phase B: 구조적 개선 (중간 우선)

### B1. 다중 팩터 스코어링 엔진 (REQ-AI-006, REQ-AI-007)

**목표:** AI 블랙박스를 투명한 팩터 기반 시스템으로 전환

**기술 접근:**
- 새 모듈 `factor_scoring.py` 생성
  - `compute_news_sentiment_score(news_data) -> int` (0-100)
  - `compute_technical_score(indicators) -> int` (0-100)
  - `compute_supply_demand_score(investor_data) -> int` (0-100)
  - `compute_valuation_score(financials, sector_avg) -> int` (0-100)
- `factor_weights` 테이블: sector_id, factor_name, weight (기본 0.25)
- FundSignal.factor_scores (JSONB): 4개 팩터 점수 + composite_score 저장
- 검증 시 팩터별 적중 여부 분석

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/services/factor_scoring.py` | 신규 - 팩터 점수 계산 엔진 |
| `backend/app/models/fund_signal.py` | factor_scores (JSONB) 컬럼 추가 |
| `backend/app/models/factor_weight.py` | 신규 - 섹터별 가중치 모델 |
| `backend/app/services/fund_manager.py` | analyze_stock()에 팩터 점수 통합 |
| `backend/app/services/signal_verifier.py` | 팩터별 적중 분석 추가 |
| `alembic/versions/` | 마이그레이션 파일 생성 |

**기술 스택:** SQLAlchemy JSONB, 기존 데이터 파이프라인 활용

---

### B2. 빠른 검증 루프 (REQ-AI-005)

**목표:** 5일 -> 6시간으로 피드백 속도 단축

**기술 접근:**
- FundSignal에 price_after_6h, price_after_12h 컬럼 추가
- signal_verifier.py에 `fast_verify()` 함수 추가
  - 장중(09:00-15:30 KST)에만 동작
  - 6h/12h 경과 시그널 가격 기록
  - stop_loss 이탈 감지 -> early_warning 플래그
- APScheduler에 장중 1시간 간격 fast_verify job 추가

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/models/fund_signal.py` | price_after_6h, price_after_12h 추가 |
| `backend/app/services/signal_verifier.py` | fast_verify() 함수 추가 |
| `backend/app/services/scheduler.py` | 장중 fast_verify job 등록 |
| `alembic/versions/` | 마이그레이션 파일 생성 |

---

### B3. A/B 테스트 프레임워크 (REQ-AI-008)

**목표:** 프롬프트 개선의 체계적 검증

**기술 접근:**
- `prompt_versions` 테이블: id, version_name, template_text, is_active, created_at
- `prompt_ab_results` 테이블: version_a, version_b, trials, winner, p_value
- FundSignal.prompt_version 컬럼 추가
- 새 모듈 `prompt_versioner.py`:
  - `get_active_versions()` -> (control, treatment)
  - `record_result(version, signal_id, outcome)`
  - `evaluate_ab_test()` -> paired t-test 결과
  - `promote_winner(version)` -> 자동 승격

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/models/prompt_version.py` | 신규 - 프롬프트 버전 모델 |
| `backend/app/models/prompt_ab_result.py` | 신규 - A/B 결과 모델 |
| `backend/app/services/prompt_versioner.py` | 신규 - A/B 테스트 서비스 |
| `backend/app/models/fund_signal.py` | prompt_version 컬럼 추가 |
| `backend/app/services/fund_manager.py` | 프롬프트 버전 시스템 연동 |

**기술 스택:** scipy.stats (t-test), 기존 AI 파이프라인

---

### B4. 뉴스 임팩트 통계 학습 (REQ-AI-009)

**목표:** news_price_impact 데이터를 시그널 생성에 체계적 활용

**기술 접근:**
- news_price_impact_service.py 확장:
  - `get_sector_impact_stats(sector_id, days=30)` 함수 추가
  - 섹터별/뉴스 유형별 평균 수익률, 승률 산출
- 팩터 스코어링의 news_sentiment_score에 역사적 임팩트 가산
- AI 프롬프트에 섹터별 뉴스 반응 통계 명시

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/services/news_price_impact_service.py` | 섹터별 통계 함수 추가 |
| `backend/app/services/factor_scoring.py` | 뉴스 임팩트 가산 로직 |
| `backend/app/services/fund_manager.py` | 프롬프트에 섹터별 통계 주입 |

---

### B5. 매크로 리스크 NLP 분류기 (REQ-AI-010)

**목표:** 키워드 기반 거짓 양성 감소

**기술 접근:**
- 매크로 뉴스 감지 시 AI 호출로 문맥 분석
  - 입력: 뉴스 제목 + 본문 일부
  - 출력: severity (none/low/medium/high/critical), context_summary
- MacroAlert 모델에 ai_severity, context_summary 컬럼 추가
- 기존 키워드 감지는 1차 필터로 유지, AI 분류는 2차 검증

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/models/macro_alert.py` | ai_severity, context_summary 추가 |
| `backend/app/services/macro_alert_service.py` | NLP 분류 로직 추가 |
| `backend/app/services/fund_manager.py` | AI 분류 결과 프롬프트 반영 |
| `alembic/versions/` | 마이그레이션 파일 생성 |

---

## Phase C: 고급 예측 (최종)

### C1. ML 앙상블 모델 (REQ-AI-011)

**목표:** AI + ML 결합으로 예측 정확도 극대화

**기술 접근:**
- 새 모듈 `ml_ensemble.py`:
  - Feature: 4개 팩터 점수 + AI confidence + 시장 지표
  - Label: is_correct (binary), return_pct (regression)
  - Model: XGBoost classifier + regressor
  - Training: 주간 재학습 (Sunday night batch)
  - Inference: analyze_stock()에서 AI 시그널과 병행
- 모델 저장: `backend/ml_models/` 디렉토리 (pickle/joblib)

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/services/ml_ensemble.py` | 신규 - XGBoost 학습/추론 |
| `backend/app/services/fund_manager.py` | ML 점수 통합 |
| `backend/app/services/scheduler.py` | 주간 재학습 job |

**기술 스택 추가:** xgboost, scikit-learn, joblib

**전제:** Phase B의 factor_scores 데이터가 90일 이상 축적

---

### C2. 섹터 전파 모델 (REQ-AI-012)

**목표:** 섹터 내 간접 뉴스 영향 정량화

**기술 접근:**
- 새 모듈 `sector_propagation.py`:
  - 섹터 내 종목 간 30일 가격 상관 행렬 계산
  - 뉴스 발생 종목에서 타 종목으로의 propagation_score 산출
  - propagation_score = news_impact * correlation_coefficient
- AI 프롬프트에 전파 점수 주입
- 프론트엔드 섹터 상세 페이지에 상관관계 시각화

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/services/sector_propagation.py` | 신규 - 상관/전파 계산 |
| `backend/app/services/fund_manager.py` | 전파 점수 프롬프트 반영 |
| `frontend/src/components/` | 상관관계 시각화 컴포넌트 |

**기술 스택 추가:** numpy (correlation matrix), 프론트엔드 차트 라이브러리

---

### C3. 페이퍼 트레이딩 시뮬레이션 (REQ-AI-013)

**목표:** 전략 성과의 객관적 측정

**기술 접근:**
- 새 테이블:
  - `virtual_portfolios`: id, name, initial_capital, current_value, created_at
  - `virtual_trades`: id, portfolio_id, stock_id, signal_id, action, price, shares, created_at, closed_at, close_price, pnl
- 새 모듈 `paper_trading.py`:
  - 시그널 생성 시 자동 가상 매매 기록
  - target_price/stop_loss 도달 시 자동 청산 (스케줄러)
  - 일일 성과 계산: 수익률, 누적, Sharpe ratio, MDD
  - KOSPI 벤치마크 비교
- API 엔드포인트:
  - GET /api/fund/paper-trading/performance
  - GET /api/fund/paper-trading/trades

**수정 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/models/virtual_portfolio.py` | 신규 - 가상 포트폴리오 모델 |
| `backend/app/models/virtual_trade.py` | 신규 - 가상 거래 모델 |
| `backend/app/services/paper_trading.py` | 신규 - 시뮬레이션 서비스 |
| `backend/app/routers/fund.py` | 페이퍼 트레이딩 API 엔드포인트 |
| `backend/app/services/scheduler.py` | 일일 성과 계산 + 청산 체크 job |
| `alembic/versions/` | 마이그레이션 파일 생성 |

**기술 스택 추가:** numpy (Sharpe ratio, MDD 계산)

---

## Phase 간 의존성

```
Phase A (독립)
  A1 필터링 완화     ─ 독립 실행 가능
  A2 시간 가중 뉴스   ─ 독립 실행 가능
  A3 오류 패턴 분류   ─ 독립 실행 가능
  A4 신뢰도 보정      ─ A3 이후 권장 (오류 패턴 데이터 활용)

Phase B (A 완료 후)
  B1 팩터 스코어링    ─ A3, A4 데이터 활용
  B2 빠른 검증 루프   ─ 독립 실행 가능
  B3 A/B 테스트       ─ 독립 실행 가능
  B4 뉴스 임팩트 학습  ─ B1 팩터 엔진 필요
  B5 매크로 NLP       ─ 독립 실행 가능

Phase C (B 완료 후)
  C1 ML 앙상블        ─ B1 팩터 데이터 90일 축적 필요
  C2 섹터 전파        ─ 독립 실행 가능 (B4와 시너지)
  C3 페이퍼 트레이딩   ─ 독립 실행 가능 (B1 팩터와 시너지)
```

---

## 리스크 분석 및 대응

| 리스크 | 영향 | 확률 | 대응 |
|--------|------|------|------|
| AI API 비용 증가 (A/B 병렬 생성) | 중간 | 높음 | A/B 테스트 대상을 일일 2-3종목으로 제한 |
| 오류 패턴 AI 분류 정확도 낮음 | 중간 | 중간 | 수동 검증 기간(30일) 설정, 정확도 70% 미달 시 규칙 기반으로 전환 |
| XGBoost 데이터 부족 (Phase C) | 높음 | 중간 | Phase B 팩터 데이터 90일 축적 후 시작 |
| KIS API 장중 부하 증가 (빠른 검증) | 낮음 | 중간 | 가격 캐시(5분 TTL) 적용, batch 조회 |
| Alembic 마이그레이션 충돌 | 낮음 | 낮음 | Phase별 마이그레이션 분리, 순차 적용 |

---

## 마일스톤 정의

### Primary Goal: Phase A 완료
- A1 필터링 완화 + A2 시간 가중 뉴스 적용
- A3 오류 패턴 분류 + A4 베이지안 보정
- 매수 후보 종목 수 40% 증가 검증

### Secondary Goal: Phase B 핵심 완료
- B1 다중 팩터 스코어링 엔진 동작
- B2 빠른 검증 루프 장중 운영
- B3 A/B 테스트 첫 번째 라운드 완료

### Tertiary Goal: Phase B 나머지 + Phase C 착수
- B4 뉴스 임팩트 학습 + B5 매크로 NLP
- C3 페이퍼 트레이딩 시작 (독립 가능)

### Final Goal: Phase C 완성
- C1 ML 앙상블 모델 첫 학습 및 검증
- C2 섹터 전파 모델 동작
- Sharpe ratio > 1.0 달성 여부 평가
