---
id: SPEC-AI-002
type: plan
version: "1.0.0"
created: "2026-03-29"
updated: "2026-03-29"
---

# SPEC-AI-002 구현 계획: AI 펀드 예측력 2단계 고도화

## 구현 전략

기존 fund_manager.py(52KB)가 이미 매우 크므로, 신규 기능은 **독립 모듈로 분리**하고
fund_manager.py에서는 호출만 하는 구조를 유지한다. factor_scoring.py 패턴을 따른다.

## Phase 1: 기술적 분석 강화 (Primary Goal)

**범위**: REQ-AI-014, REQ-AI-015, REQ-AI-020

### 작업 분해

**Task 1.1: 다중 시간축 분석 (REQ-AI-014)**
- 대상 파일: `backend/app/services/factor_scoring.py`
- 작업 내용:
  - compute_technical_score() 확장: 5일/20일/60일 이동평균 기울기 계산
  - trend_alignment 판정 로직 (aligned/divergent/mixed)
  - trend_aligned 시 +15점 가산, trend_divergent 시 confidence -0.1
- 의존성: naver_finance.py의 주가 데이터 (기존)
- DB 변경: fund_signals 테이블에 trend_alignment VARCHAR(20) 추가

**Task 1.2: 거래량 이상 탐지 (REQ-AI-015)**
- 대상 파일: `backend/app/services/factor_scoring.py`
- 작업 내용:
  - compute_supply_demand_score() 확장: 20일 평균 거래량 대비 비율 계산
  - volume_spike 감지 시 +10점 가산
  - fund_signals metadata에 volume_spike 기록
- 의존성: naver_finance.py의 거래량 데이터 (기존)

**Task 1.3: 시장 변동성 기반 포지션 사이징 (REQ-AI-020)**
- 대상 파일: `backend/app/services/market_context.py` (신규)
- 작업 내용:
  - KOSPI 20일 표준편차 기반 변동성 레벨 계산 (low/normal/high/extreme)
  - 변동성에 따른 suggested_weight 조정 로직
  - high 이상 시 confidence -0.15 감산
- 의존성: naver_finance.py의 KOSPI 지수 데이터
- DB 변경: fund_signals에 volatility_level VARCHAR(10) 추가

### Alembic 마이그레이션
- fund_signals: trend_alignment, volatility_level 컬럼 추가

---

## Phase 2: 섹터 분석 (Secondary Goal)

**범위**: REQ-AI-016, REQ-AI-017, REQ-AI-019

### 작업 분해

**Task 2.1: 섹터 모멘텀 추적 (REQ-AI-016)**
- 신규 파일: `backend/app/services/sector_momentum.py`
- 작업 내용:
  - 섹터별 5일 평균 등락률/거래대금 변화율 계산
  - momentum_sector 태그 부여 로직
  - capital_inflow 알림 생성
- DB 변경: sector_momentum 테이블 생성
  - sector_id FK, date, avg_return_5d, volume_change_5d, momentum_tag, capital_inflow BOOLEAN

**Task 2.2: 섹터 로테이션 감지 (REQ-AI-017)**
- 대상 파일: `backend/app/services/sector_momentum.py`
- 작업 내용:
  - 이전 모멘텀 섹터 -> 신규 모멘텀 섹터 전환 감지
  - sector_rotation 이벤트 생성
  - 이전 섹터 시그널 confidence -0.15 자동 조정
- DB 변경: sector_rotation_events 테이블 생성
  - from_sector_id, to_sector_id, detected_at, confidence

**Task 2.3: 섹터 시그널 중복 제거 (REQ-AI-019)**
- 대상 파일: `backend/app/services/fund_manager.py`
- 작업 내용:
  - 섹터별 시그널 수 제한 (최대 2개)
  - composite_score, trend_alignment, volume_spike 기준 우선순위
  - 제외 시그널 로그 기록

---

## Phase 3: 어닝 및 외부 데이터 (Tertiary Goal)

**범위**: REQ-AI-018, REQ-AI-024

### 작업 분해

**Task 3.1: DART 어닝 프리뷰 (REQ-AI-018)**
- 대상 파일: `backend/app/services/dart_crawler.py` (확장)
- 신규 파일: `backend/app/services/earnings_analyzer.py`
- 작업 내용:
  - DART 실적 공시 필터링 (rcept_tp_nm 기반)
  - 과거 실적 서프라이즈 패턴 분석
  - 동종 섹터 실적 동향 종합
  - earnings_preview 결과 생성 및 confidence 가산
  - 실적 발표 후 예측 vs 실제 비교 로직

**Task 3.2: 원자재 크로스 검증 (REQ-AI-024)**
- 대상 파일: `backend/app/services/market_context.py`
- 작업 내용:
  - 섹터-원자재 매핑 (정유-WTI, 철강-철광석, 화학-나프타, 비철금속-구리)
  - 원자재 5일 추세 계산
  - commodity_divergence 경고 로직

---

## Phase 4: AI 프롬프트 및 리스크 관리 (Final Goal)

**범위**: REQ-AI-021, REQ-AI-022, REQ-AI-023

### 작업 분해

**Task 4.1: Chain-of-Thought 프롬프트 (REQ-AI-023)**
- 대상 파일: `backend/app/services/fund_manager.py`
- 작업 내용:
  - 5단계 CoT 프롬프트 템플릿 구현
  - AI 응답 STEP 누락 감지 파서
  - A/B 테스트 버전으로 등록 (prompt_versioner.py 연동)

**Task 4.2: Max Drawdown 제어 (REQ-AI-021)**
- 대상 파일: `backend/app/services/fund_manager.py`
- 작업 내용:
  - 페이퍼 트레이딩 포트폴리오 누적 손실 모니터링
  - 방어 모드 진입/해제 상태 관리
  - 방어 모드 시 손절 기준 강화 (-5% -> -3%)

**Task 4.3: 유사 패턴 매칭 (REQ-AI-022)**
- 대상 파일: `backend/app/services/market_context.py`
- 작업 내용:
  - 시장 상황 벡터 생성 (KOSPI 5일 수익률, 변동성, 모멘텀 섹터)
  - 과거 이력 유사도 검색 (코사인 유사도 또는 유클리드 거리)
  - 유사 시점의 시그널 적중률 계산

---

## Phase 5: ML 피처 준비 (Optional Goal)

**범위**: REQ-AI-025

### 작업 분해

**Task 5.1: 피처 엔지니어링 파이프라인**
- 신규 파일: `backend/app/services/ml_features.py`
- 신규 모델: `backend/app/models/ml_feature.py`
- 작업 내용:
  - ml_features 테이블 설계 및 마이그레이션
  - 일별 피처 스냅샷 저장 로직
  - 90일 데이터 축적 알림
- 스케줄러 연동: 일간 브리핑 후 자동 실행

---

## 신규 파일 목록

| 파일 | 용도 |
|------|------|
| backend/app/services/market_context.py | 시장 변동성, 원자재 검증, 유사 패턴 매칭 |
| backend/app/services/sector_momentum.py | 섹터 모멘텀 추적, 로테이션 감지 |
| backend/app/services/earnings_analyzer.py | DART 어닝 프리뷰 |
| backend/app/services/ml_features.py | ML 피처 엔지니어링 |
| backend/app/models/sector_momentum.py | SectorMomentum ORM 모델 |
| backend/app/models/sector_rotation_event.py | SectorRotationEvent ORM 모델 |
| backend/app/models/ml_feature.py | MLFeature ORM 모델 |

## 수정 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| backend/app/services/factor_scoring.py | 다중 시간축, 거래량 이상 탐지 통합 |
| backend/app/services/fund_manager.py | CoT 프롬프트, 섹터 중복 제거, 방어 모드, 프롬프트 확장 |
| backend/app/services/dart_crawler.py | 실적 공시 필터링 확장 |
| backend/app/services/scheduler.py | 섹터 모멘텀 일일 계산 job, ML 피처 job 추가 |
| backend/app/models/fund_signal.py | trend_alignment, volatility_level 컬럼 추가 |

## 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| fund_manager.py 추가 비대화 | 유지보수 어려움 | 신규 기능은 별도 모듈에 구현, FM은 호출만 |
| KOSPI 지수 데이터 API 제한 | 변동성 계산 불가 | naver_finance.py 캐시 활용, 장중 1시간 갱신 |
| CoT 프롬프트 토큰 증가 | AI 비용 증가 | Groq 무료 tier 내 max_tokens 4096 유지, 불필요 정보 제거 |
| 섹터 모멘텀 데이터 부족 초기 | 로테이션 오감지 | 최소 10일 데이터 축적 후 활성화 |
| DART 실적 공시 포맷 변경 | 파싱 실패 | 방어적 파싱 + 실패 시 graceful degradation |

## 기술적 접근 방향

1. **모듈 분리 원칙**: fund_manager.py의 추가 비대화 방지를 위해 market_context.py, sector_momentum.py, earnings_analyzer.py를 독립 모듈로 구현
2. **점진적 활성화**: 각 모듈은 데이터 부족 시 graceful degradation (기존 로직으로 fallback)
3. **A/B 테스트 통합**: CoT 프롬프트는 prompt_versioner.py를 통해 기존 프롬프트와 A/B 비교
4. **비동기 우선**: 모든 외부 API 호출은 async로 구현
5. **페이퍼 트레이딩 검증**: 각 Phase 완료 후 페이퍼 트레이딩으로 실효성 검증
