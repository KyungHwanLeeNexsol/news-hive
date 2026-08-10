# NewsHive — Project Structure

## Top-Level Layout

```
news-hive/
├── backend/           # FastAPI Python 백엔드 (주요 비즈니스 로직)
├── frontend/          # Next.js 16 + React 19 프론트엔드
├── monitoring/        # Prometheus + Grafana (docker-compose.monitoring.yml)
├── scripts/           # 배포·유틸리티 스크립트
├── docker-compose.yml # PostgreSQL 16 + Redis 7 로컬 개발 환경
└── CHANGELOG.md       # 릴리즈 히스토리
```

## Backend Structure

```
backend/app/
├── main.py            # FastAPI 앱 엔트리포인트, Lifespan, APScheduler 초기화
├── config.py          # Pydantic BaseSettings (API keys, DB, Redis, JWT, SMTP 등)
├── database.py        # SQLAlchemy 엔진 (풀 10+20, 재연결 1800s)
├── models/            # SQLAlchemy 데이터 모델
├── services/          # 서비스 모듈
├── routers/           # 22개 FastAPI 라우터
└── alembic/           # DB 마이그레이션
```

## Key Services (services/)

### 크롤링
| 파일 | 역할 |
|------|------|
| news_crawler.py | 메인 뉴스 크롤 오케스트레이터 (멀티소스) |
| dart_crawler.py | DART 공시 크롤러 (5일 lookback) |
| crawlers/naver.py | Naver News Search API |
| crawlers/google.py | Google News RSS |
| crawlers/korean_rss.py | 한국 금융 RSS |
| forum_crawler.py | 주식 포럼 크롤러 |

### 급등 탐지 (핵심)
| 파일 | 역할 |
|------|------|
| surge_detector.py | 6종 탐지기 앙상블, 글로벌 캐시 (_surge_rate_cache) |
| surge_trading_service.py | 자동 매매 실행, BUY_CUTOFF=11:00, max_positions=7 |
| surge_calibrator.py | 동적 임계값 캘리브레이션 |
| surge_threshold_service.py | 임계값 히스토리 추적 (SPEC-AI-029) |
| surge_auto_improver.py | 급등 파라미터 자동 개선 (YAML 패치) |
| surge_evaluation_service.py | 시그널 평가 메트릭 |
| surge_absent_attribution_service.py | 실제 급등주가 후보 표면에 없었던 이유 분류 |
| surge_gate_attribution_service.py | gate/drop 관측과 relaxed gate shadow 리포트 |
| surge_lane_metrics_service.py | same-day/next-day 급등예측 lane 지표 |
| surge_missing_trigger_detector_service.py | contract/M&A, volume spike, low-liquidity shadow detector pack |
| surge_backtest.py | 백테스트 프레임워크 |

### 공시 처리
| 파일 | 역할 |
|------|------|
| disclosure_impact_scorer.py | 공시 임팩트 스코어링 (SPEC-AI-004) |
| preday_signal_service.py | 장 마감 후 공시 → 다음날 갭업 시그널 (SPEC-AI-042) |

### 자동 개선
| 파일 | 역할 |
|------|------|
| improvement_loop.py | 30일 실패 패턴 집계, 프롬프트·팩터가중치 최적화 |
| factor_scoring.py | 다중 팩터 스코어링 (뉴스 감성, 기술적, 수급, 밸류에이션) |
| prompt_versioner.py | 프롬프트 버전 관리 |

### 시장 데이터
| 파일 | 역할 |
|------|------|
| naver_finance.py | Naver Finance HTTP 스크래핑 (현재가, 변동률) |
| technical_indicators.py | RSI, MACD, 볼린저밴드 등 기술적 지표 |
| market_regime_service.py | 시장 레짐 분류 (상승/하락/중립) |
| macro_risk.py | 뉴스 기반 거시 리스크 탐지 |

### 인프라
| 파일 | 역할 |
|------|------|
| scheduler.py | APScheduler 잡 오케스트레이터 (SQLAlchemy 잡스토어) |
| ai_classifier.py | AI 감성 분석·분류 (Gemini → Z.AI → OpenAI 폴백) |
| cache.py | 인메모리 캐시 + Redis 폴백 |
| metrics.py | Prometheus 메트릭 |

## Key Models (models/)

| 모델 | 핵심 필드 |
|------|----------|
| FundSignal | stock_id, signal_type, confidence, price_at_signal, is_correct, alpha_pct, surge_metadata |
| SurgePortfolio / SurgeTrade | initial_capital=5M, entry_price, exit_price, exit_reason |
| NewsArticle | title, url, sentiment, urgency, ai_summary |
| Disclosure | corp_code, report_name, impact_score, reflected_pct |
| SurgeThresholdHistory | threshold values over time (SPEC-AI-029) |
| SurgePredictionEvaluation | model metrics, recall, precision |
| SurgeGateDropObservation | 급등 후보가 gate에서 탈락한 이유와 shadow profile 관측 |
| SurgeMissingTriggerShadowCandidate | missing-trigger detector의 shadow-only 후보 |

## Routers (API Endpoints)

| 라우터 | 경로 | 주요 기능 |
|--------|------|-----------|
| surge_trading.py | /api/surge-trading | 급등 포트폴리오 조회, 시그널 확인 |
| fund_manager.py | /api/fund-manager | 관리자 대시보드 |
| following.py | /api/following | 관심 종목 + Telegram 알림 |
| disclosures.py | /api/disclosures | DART 공시 검색 |
| auth.py | /api/auth | JWT 로그인 + 관리자 토큰 |

## Scheduled Jobs

| 잡 | 실행 시각 | 주기 | 목적 |
|----|----------|------|------|
| _run_crawl_job | 상시 | ~10분 | 뉴스 크롤 + 감성 분석 + 매크로 리스크 |
| _run_dart_crawl | 상시 | ~30분 | DART 공시 크롤 |
| Surge signal gen | 10:00 KST | 매일 | 급등 시그널 생성 (핵심 잡) |
| _run_preday_entry | 09:05 KST | 매일 | 갭업 조기 진입 |
| collect_outcomes | 16:10 KST | 매일 | 당일 급등 결과 수집 |
| surge_verify | 18:30 KST | 매일 | 예측 정확도 검증 |
| auto_improve | 19:00 KST | 매일 | 파라미터 자동 개선 |
| improve_prompts | 22:00 KST | 매주 일요일 | AI 프롬프트 정제 |
| factor_weights | 23:00 KST | 매월 1일 | 팩터 가중치 최적화 |
