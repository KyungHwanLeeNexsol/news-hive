# 프로젝트 구조

## 전체 디렉토리 트리

```
news-hive/
├── backend/                          # FastAPI 백엔드 애플리케이션
│   ├── app/
│   │   ├── main.py                   # FastAPI 앱 진입점, 라이프사이클, 웹훅 배포
│   │   ├── config.py                 # pydantic-settings 환경변수 관리
│   │   ├── database.py               # SQLAlchemy 엔진 및 세션 팩토리
│   │   ├── models/                   # SQLAlchemy ORM 모델
│   │   │   ├── sector.py             # Sector (섹터)
│   │   │   ├── stock.py              # Stock (종목)
│   │   │   ├── news.py               # NewsArticle (뉴스 기사)
│   │   │   ├── news_relation.py      # NewsStockRelation (뉴스-종목 매핑)
│   │   │   ├── disclosure.py         # Disclosure (DART 공시)
│   │   │   ├── macro_alert.py        # MacroAlert (매크로 리스크 알림)
│   │   │   ├── economic_event.py     # EconomicEvent (경제 이벤트)
│   │   │   ├── fund_signal.py        # FundSignal (투자 시그널)
│   │   │   ├── daily_briefing.py     # DailyBriefing (일일 브리핑)
│   │   │   ├── portfolio_report.py   # PortfolioReport (포트폴리오 보고서)
│   │   │   └── news_price_impact.py  # NewsPriceImpact (뉴스-가격 반응 추적)
│   │   ├── schemas/                  # Pydantic 요청/응답 스키마
│   │   ├── routers/                  # API 라우터 (엔드포인트 정의)
│   │   │   ├── sectors.py            # 섹터 CRUD + 뉴스 조회
│   │   │   ├── stocks.py             # 종목 CRUD + 뉴스 조회
│   │   │   ├── news.py               # 전체 뉴스 조회 + 수동 새로고침
│   │   │   ├── disclosures.py        # DART 공시 조회
│   │   │   ├── alerts.py             # 매크로 알림
│   │   │   ├── events.py             # 경제 이벤트
│   │   │   ├── fund_manager.py       # 투자 시그널, 브리핑, TP/SL 통계
│   │   │   ├── paper_trading.py      # 페이퍼 트레이딩 (시뮬레이션 거래, TP/SL 백테스트)
│   │   │   ├── auth.py               # 관리자 인증
│   │   │   ├── health.py             # 헬스체크
│   │   │   ├── market_status.py      # 시장 상태
│   │   │   └── deploy.py             # GitHub 웹훅 배포
│   │   └── services/                 # 비즈니스 로직 서비스
│   │       ├── scheduler.py          # APScheduler 16개 예약 작업
│   │       ├── fund_manager.py       # 투자 시그널 + 브리핑 (52KB, 핵심)
│   │       ├── ai_client.py          # 멀티 프로바이더 AI 폴백 클라이언트
│   │       ├── news_crawler.py       # 뉴스 수집 오케스트레이터 (Fuzzy 중복 제거)
│   │       ├── ai_classifier.py      # AI 기반 뉴스 분류
│   │       ├── dart_crawler.py       # DART 공시 크롤러
│   │       ├── naver_finance.py      # Naver Finance 실시간 주가
│   │       ├── technical_indicators.py # RSI, MACD, 볼린저 밴드, ATR 계산
│   │       ├── dynamic_tp_sl.py      # 동적 익절/손절 (ATR 기반) (SPEC-AI-005)
│   │       ├── news_price_impact_service.py  # 뉴스-가격 반응 추적 (스냅샷/백필/통계)
│   │       ├── commodity_service.py  # 원자재 가격 수집 (yfinance, 장 중/장 외 fallback)
│   │       └── commodity_news_service.py # 원자재 뉴스 매칭 (제목 기반 키워드 매칭)
│   │       └── crawlers/             # 개별 뉴스 소스 크롤러
│   │           ├── naver.py          # Naver 뉴스 검색 API
│   │           ├── google.py         # Google News RSS 파싱
│   │           ├── yahoo.py          # Yahoo Finance RSS
│   │           ├── korean_rss.py     # 한국 경제 미디어 RSS
│   │           ├── us_news.py        # 미국 뉴스 소스
│   │           └── content_scraper.py # 기사 본문 스크래핑
│   ├── tests/                        # 백엔드 단위 테스트
│   │   ├── test_disclosure_impact_scorer.py  # 공시 충격 점수 계산 테스트 (40개 케이스)
│   │   └── test_dynamic_tp_sl.py     # 동적 TP/SL 테스트 (37개 케이스)
│   ├── alembic/                      # DB 마이그레이션 (38개 버전)
│   │   ├── versions/                 # 마이그레이션 파일들
│   │   │   └── 038_add_dynamic_tp_sl.py # 동적 TP/SL 컬럼 추가
│   │   └── env.py                    # Alembic 환경 설정
│   ├── seed/
│   │   ├── sectors.py               # 한국 증시 업종 초기 데이터
│   │   └── commodities.py           # 원자재 마스터 + 섹터-원자재 관계 초기 데이터
│   ├── requirements.txt              # Python 패키지 의존성
│   └── .env.example                  # 환경변수 템플릿
├── frontend/                         # Next.js 프론트엔드
│   ├── src/
│   │   ├── middleware.ts              # Next.js Edge 미들웨어: 헬스체크 기반 점검 페이지 리디렉션
│   │   ├── app/                      # Next.js App Router 페이지
│   │   │   ├── page.tsx              # 대시보드 (섹터 카드 목록)
│   │   │   ├── layout.tsx            # 루트 레이아웃
│   │   │   ├── maintenance/
│   │   │   │   └── page.tsx          # 시스템 점검 페이지 (10초 자동 재시도, 복구 시 홈 이동)
│   │   │   ├── stocks/
│   │   │   │   ├── page.tsx          # 전체 종목 목록
│   │   │   │   └── [id]/page.tsx     # 종목 상세 (뉴스 피드 + 시그널)
│   │   │   ├── sectors/
│   │   │   │   └── [id]/page.tsx     # 섹터 상세 (종목 목록 + 섹터 뉴스)
│   │   │   ├── news/
│   │   │   │   ├── page.tsx          # 전체 뉴스 피드
│   │   │   │   └── [id]/page.tsx     # 뉴스 상세
│   │   │   ├── disclosures/
│   │   │   │   └── page.tsx          # DART 공시 목록
│   │   │   ├── fund/
│   │   │   │   └── page.tsx          # 펀드 매니저 (투자 시그널 대시보드)
│   │   │   ├── calendar/
│   │   │   │   └── page.tsx          # 경제 이벤트 캘린더
│   │   │   ├── watchlist/
│   │   │   │   └── page.tsx          # 관심 종목 (localStorage 기반)
│   │   │   └── manage/
│   │   │       └── page.tsx          # 관리 페이지 (섹터/종목 CRUD)
│   │   ├── components/               # 재사용 UI 컴포넌트
│   │   └── lib/
│   │       └── api.ts                # Backend API 호출 함수 모음
│   ├── next.config.ts                # /api/* → FastAPI 프록시 rewrite
│   ├── tailwind.config.ts            # Tailwind CSS v4 설정
│   └── package.json
├── docker-compose.yml                # PostgreSQL 16 컨테이너
└── .env                              # (gitignore) 실제 환경변수
```

---

## 주요 디렉토리별 역할

### backend/app/models/

SQLAlchemy ORM 모델 10개. 각 파일은 단일 테이블을 담당합니다. 관계 정의는 `relationship()`으로 명시적으로 선언하며, Alembic이 스키마 변경을 추적합니다.

### backend/app/routers/

FastAPI 라우터 12개. 각 라우터는 단일 도메인의 엔드포인트를 담당합니다. `APIRouter`를 사용하고 `main.py`에서 prefix와 함께 등록됩니다.

### backend/app/services/

비즈니스 로직의 핵심. 크롤러, AI 클라이언트, 스케줄러 등 외부 시스템과의 연동을 담당합니다.

### backend/app/services/crawlers/

개별 뉴스 소스별 크롤러. 새 소스 추가 시 이 디렉토리에 파일을 추가하고 `news_crawler.py` 오케스트레이터에 등록합니다.

### frontend/src/app/

Next.js 15 App Router 기반 페이지. 각 폴더가 URL 경로에 대응합니다. `[id]` 형태의 폴더는 동적 라우트입니다.

### frontend/src/lib/api.ts

모든 Backend API 호출을 단일 파일에 집중. `/api/*` 경로는 `next.config.ts`의 rewrite 설정으로 FastAPI 서버로 프록시됩니다.

---

## 모듈 조직 원칙

1. **단일 책임**: 각 서비스 파일은 하나의 외부 시스템 또는 도메인을 담당
2. **오케스트레이터 패턴**: `news_crawler.py`가 개별 크롤러를 조율, `scheduler.py`가 서비스들을 조율
3. **의존성 방향**: Router → Service → Model (단방향)
4. **프록시 패턴**: 프론트엔드는 직접 FastAPI를 호출하지 않고 Next.js API 프록시를 통함

---

## 데이터 흐름

### 뉴스 수집 파이프라인

```
APScheduler (30분 주기)
  └─> news_crawler.py (오케스트레이터)
        ├─> naver.py     (Naver 검색 API)
        ├─> google.py    (Google News RSS)
        ├─> yahoo.py     (Yahoo Finance RSS)
        └─> korean_rss.py (한국 미디어 RSS)
              │
              ▼
        URL 기반 중복 제거 (Fuzzy 매칭)
              │
              ▼
        ai_classifier.py (Claude/Gemini/Groq)
              │
              ▼
        DB 저장 (news_articles + news_stock_relations)
```

### 투자 시그널 파이프라인

```
APScheduler (일 1회)
  └─> fund_manager.py
        ├─> naver_finance.py (실시간 주가 조회)
        ├─> technical_indicators.py (RSI, MACD, BB 계산)
        ├─> ai_client.py (시그널 해석)
        └─> DB 저장 (fund_signals + daily_briefings)
```

### 일일 브리핑 파이프라인

```
APScheduler (08:30 KST)
  └─> fund_manager.py (브리핑 생성)
        ├─> DB 조회 (전일 뉴스 + 시그널)
        ├─> ai_client.py (브리핑 텍스트 생성)
        └─> DB 저장 (daily_briefings)
```

### API 요청 흐름

```
사용자 브라우저
  └─> Next.js 프론트엔드 (Vercel)
        └─> /api/* rewrite (next.config.ts)
              └─> FastAPI 백엔드 (Oracle Cloud VM :8000)
                    └─> PostgreSQL DB (Oracle Cloud VM)
```

---

## 스케줄러 작업 목록 (16개)

| 작업 | 주기 | 담당 서비스 |
|------|------|------------|
| 뉴스 수집 | 30분 | news_crawler.py |
| DART 공시 수집 | 1시간 | dart_crawler.py |
| 기술적 지표 계산 | 1시간 | technical_indicators.py |
| 투자 시그널 생성 | 1일 | fund_manager.py |
| 일일 브리핑 생성 | 08:30 KST | fund_manager.py |
| 매크로 리스크 확인 | 6시간 | fund_manager.py |
| 포트폴리오 보고서 | 1주 | fund_manager.py |
| 뉴스-가격 반응 백필 | 18:30 KST | news_price_impact_service.py |
| 90일 초과 impact 정리 | 03:00 KST | news_price_impact_service.py |
| 갭업 풀백 감지 (월) | 10:00~11:30 KST | disclosure_impact_scorer.py |
| 갭업 풀백 감지 (화) | 10:00~11:30 KST | disclosure_impact_scorer.py |
| 갭업 풀백 감지 (수) | 10:00~11:30 KST | disclosure_impact_scorer.py |
| 갭업 풀백 감지 (목) | 10:00~11:30 KST | disclosure_impact_scorer.py |
| 갭업 풀백 감지 (금) | 10:00~11:30 KST | disclosure_impact_scorer.py |
| 갭업 풀백 감지 (토) | 10:00~11:30 KST | disclosure_impact_scorer.py |
| 갭업 풀백 감지 (일) | 10:00~11:30 KST | disclosure_impact_scorer.py |
| 페이퍼 트레이딩 리스크 업데이트 | 15분 | paper_trading.py |

---

## 데이터베이스 테이블 (38개 마이그레이션)

| 테이블 | 용도 |
|--------|------|
| sectors | 투자 섹터 (건설기계, 반도체 등) |
| stocks | 개별 종목 |
| news_articles | 수집된 뉴스 기사 |
| news_stock_relations | 뉴스-종목/섹터 매핑 |
| disclosures | DART 공시 |
| macro_alerts | 매크로 경제 리스크 알림 |
| economic_events | 경제 일정 이벤트 |
| fund_signals | 종목별 투자 시그널 (tp_sl_method 컬럼 추가 in migration 038) |
| daily_briefings | 일일 AI 브리핑 |
| portfolio_reports | 포트폴리오 보고서 |
| news_price_impact | 뉴스-가격 반응 추적 (SPEC-NEWS-001) |
| commodities | 원자재 마스터 (심볼, 카테고리) |
| commodity_prices | 원자재 가격 히스토리 |
| sector_commodity_relations | 섹터-원자재 상관관계 매핑 |
| news_commodity_relations | 뉴스-원자재 연관 매핑 |
| stock_relations | 종목 간 관계 그래프 (SPEC-RELATION-001) |
| virtual_trades | 페이퍼 트레이딩 시뮬레이션 거래 (SPEC-AI-005) |

### virtual_trades 테이블 (migration 038)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | SERIAL PK | 고유 ID |
| stock_id | INTEGER (FK) | 종목 ID |
| signal_id | INTEGER (FK, SET NULL) | 투자 시그널 ID |
| entry_price | FLOAT NOT NULL | 진입 가격 |
| entry_at | TIMESTAMP NOT NULL | 진입 시각 |
| exit_price | FLOAT NULL | 청산 가격 |
| exit_at | TIMESTAMP NULL | 청산 시각 |
| tp_price | FLOAT NULL | 익절가 |
| sl_price | FLOAT NULL | 손절가 |
| tp_sl_method | VARCHAR(20) NOT NULL | TP/SL 방법 (ATR, fixed, trailing) |
| trailing_stop_activated | BOOLEAN DEFAULT FALSE | 트레일링 스탑 활성화 여부 |
| trailing_stop_pct | FLOAT NULL | 트레일링 스탑 퍼센트 |
| trailing_stop_price | FLOAT NULL | 현재 트레일링 스탑 가격 |
| max_profit_pct | FLOAT NULL | 최대 수익률 (%) |
| status | VARCHAR(20) NOT NULL | 상태 (pending, active, closed, tp_hit, sl_hit) |
| reason | TEXT NULL | 종료 이유 |
| created_at | TIMESTAMP NOT NULL | 생성 시각 |
| updated_at | TIMESTAMP NOT NULL | 업데이트 시각 |

인덱스: stock_id, signal_id, status (3개)
