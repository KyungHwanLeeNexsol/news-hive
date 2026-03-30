# 기술 스택

## 전체 기술 스택 개요

| 레이어 | 기술 | 버전 | 역할 |
|--------|------|------|------|
| 프론트엔드 프레임워크 | Next.js | 15 (App Router) | SSR/SSG + API 프록시 |
| UI 라이브러리 | React | 19 | 컴포넌트 기반 UI |
| 스타일링 | Tailwind CSS | v4 | 유틸리티 퍼스트 CSS |
| 언어 (프론트) | TypeScript | 5.x | 타입 안전성 |
| 백엔드 프레임워크 | FastAPI | 0.115.6 | 비동기 REST API |
| ORM | SQLAlchemy | 2.0 | 데이터베이스 추상화 |
| DB 마이그레이션 | Alembic | - | 스키마 버전 관리 |
| 언어 (백엔드) | Python | 3.13+ | 비동기 서비스 |
| 데이터베이스 | PostgreSQL | 16 | 메인 데이터 저장소 |
| 스케줄러 | APScheduler | - | 백그라운드 예약 작업 |
| AI (주) | Google Gemini | 1.5 Flash | 뉴스 분류, 브리핑 생성 |
| AI (폴백1) | Groq | - | 고속 추론 폴백 |
| AI (폴백2) | OpenRouter | - | 다양한 모델 폴백 |
| 주가 데이터 | Naver Finance | - | 실시간 시세 크롤링 |
| 주가 데이터 | KIS Open API | - | 한국투자증권 API |
| 원자재 가격 | yfinance | - | 글로벌 원자재 선물/ETF 가격 수집 |
| 공시 | DART API | - | 금융감독원 공시 |
| 컨테이너 | Docker / Compose | - | 로컬 DB 실행 |
| 배포 (백엔드) | Oracle Cloud VM | - | Ubuntu + systemd |
| 배포 (프론트) | Vercel | - | 자동 배포 |
| CI/CD | GitHub Webhook | - | 원클릭 배포 |

---

## 프레임워크 선택 근거

### FastAPI (백엔드)

- **비동기 지원**: 뉴스 크롤러가 다수의 외부 HTTP 요청을 병렬 실행해야 하므로 `async/await` 기반 프레임워크가 필수
- **자동 OpenAPI 문서**: `/docs`와 `/redoc`에서 자동 생성되는 Swagger UI로 API 테스트 편의성 확보
- **Pydantic 통합**: 요청/응답 스키마 자동 검증, 환경변수 관리(`pydantic-settings`)
- **성능**: Starlette 기반으로 Flask/Django보다 처리량이 높음

### SQLAlchemy 2.0 (ORM)

- **비동기 세션**: `AsyncSession`으로 FastAPI의 비동기 컨텍스트에서 DB 쿼리 가능
- **Alembic 연동**: 모델 변경 시 `alembic revision --autogenerate`로 마이그레이션 자동 생성
- **선언적 매핑**: Python 클래스로 테이블 구조를 명확하게 표현

### asyncio.to_thread() 패턴 (CPU-bound 오프로딩)

- **용도**: 동기 함수(특히 DB 집합 연산, 번역 배치 등)를 FastAPI 비동기 엔드포인트 내에서 실행할 때 이벤트 루프 블로킹 방지
- **적용 위치**: `backend/app/routers/news.py`의 `_run_full_refresh` — `_deduplicate_existing`, `_backfill_sentiment` 호출 시 사용
- **원칙**: I/O bound 작업은 `await` 비동기 함수를 직접 사용하고, CPU/메모리 집약적인 동기 함수는 `asyncio.to_thread(fn, *args)`로 스레드풀에 오프로딩

### Next.js App Router (프론트엔드)

- **API 프록시**: `next.config.ts`의 `rewrites`로 `/api/*`를 FastAPI로 투명하게 프록시하여 CORS 문제 없이 운영
- **서버 컴포넌트**: 초기 렌더링 성능 최적화
- **파일 기반 라우팅**: 페이지 추가 시 디렉토리 생성만으로 처리

### Next.js Middleware (Edge Runtime)

- **위치**: `frontend/src/middleware.ts`
- **역할**: 모든 페이지 네비게이션 시 백엔드 헬스체크(`/api/health`) 수행, 응답 없음 또는 오류 시 `/maintenance`로 리디렉션
- **Edge Runtime 호환**: `AbortController` + `setTimeout` 조합으로 타임아웃 구현 (Node.js API 미사용)
- **적용 범위**: `/maintenance` 및 `/_next/*`, `/favicon.ico` 등 정적 경로 제외한 모든 경로

### Tailwind CSS v4

- **CSS Variables 기반**: v4의 새로운 방식으로 빌드 시간 단축, 런타임 테마 전환 용이
- **유틸리티 퍼스트**: 반응형 디자인을 클래스 조합만으로 구현

---

## AI 프로바이더 전략 (멀티 프로바이더 폴백)

### 설계 원칙

단일 AI 프로바이더에 의존할 경우 API 장애, 요청 한도 초과, 서비스 중단 시 전체 기능이 마비됩니다. NewsHive는 3개 프로바이더를 계층적으로 구성하여 가용성을 확보합니다.

### 폴백 체인

```
요청
  └─> Gemini (주, 무료 20회/일)
        ├─> 성공: 결과 반환
        └─> 한도 초과 / 오류
              └─> Groq (폴백1, 고속 추론)
                    ├─> 성공: 결과 반환
                    └─> 오류
                          └─> OpenRouter (폴백2, 다양한 모델)
                                └─> 성공 / 최종 오류 반환
```

### 프로바이더별 특성

| 프로바이더 | 강점 | 제한 | 용도 |
|-----------|------|------|------|
| Google Gemini | 무료 쿼터, 한국어 성능 | 20회/일 (무료 플랜) | 주 프로바이더 |
| Groq | 초고속 추론 (LLaMA 기반) | 분당 요청 제한 | 속도 중요 작업 폴백 |
| OpenRouter | 다양한 모델 선택 | 유료 | 최후 폴백 |

### 구현 위치

`backend/app/services/ai_client.py`에 폴백 로직이 집중되어 있습니다. 각 크롤러와 분류기는 `ai_client.py`를 통해 AI를 호출하므로 프로바이더 변경 시 이 파일만 수정합니다.

---

## 데이터베이스 설계

### 스키마 설계 결정사항

**뉴스-종목 관계 분리 (news_stock_relations)**

뉴스와 종목/섹터 매핑을 별도 테이블로 분리했습니다. 하나의 뉴스가 여러 종목에 동시에 관련될 수 있고, 관계 유형(direct/indirect)과 매핑 방법(keyword/ai_classified)을 기록해야 하기 때문입니다.

**URL 기반 중복 제거**

`news_articles.url`에 UNIQUE 제약을 걸어 DB 레벨에서 중복을 방지합니다. 크롤러에서는 추가적으로 Fuzzy 매칭으로 제목이 유사한 기사를 사전 필터링합니다.

**keywords 배열 컬럼 (stocks.keywords)**

PostgreSQL의 TEXT[] 배열 타입을 활용하여 종목별 검색 키워드를 유연하게 관리합니다. 종목명 외에 부서명, 브랜드명 등 추가 검색어를 지정할 수 있습니다.

### 원자재 가격 수집 전략 (yfinance)

원자재 가격 수집은 yfinance를 사용하며 심볼 유형과 시장 상황에 따라 두 가지 방법을 사용합니다.

**심볼 전략: 선물 vs ETF 프록시**

| 유형 | 예시 심볼 | 설명 |
|------|-----------|------|
| 선물 (=F suffix) | CL=F, GC=F, SI=F | yfinance 지원 원자재 선물 (WTI, 금, 은 등) |
| ETF 프록시 | COAL, LIT, REMX | 선물 미지원 품목 대용 (석탄, 리튬, 희토류) |

ETF 프록시를 사용하는 이유: Newcastle Coal 선물(MTF=F)은 yfinance에서 데이터가 반환되지 않아 Range Global Coal ETF(COAL)를 대용합니다. 리튬(LIT)·희토류(REMX)도 선물 시장이 없어 ETF로 추적합니다.

**가격 수집 로직 (`_download_with_fallback`)**

1. 1차 시도 — 1분봉 당일 데이터 (`period="1d", interval="1m"`): 장 중에는 15분 지연된 실시간 가격 반환
2. 2차 시도 (fallback) — 5일 일봉 데이터 (`period="5d"`): 장 외 시간이나 1차가 비어있으면 최근 거래일 종가 사용

이 방식으로 단일 코드에서 장 중/장 외 모두 최신 가격을 제공합니다.

**경합 조건 방지**: 앱 시작(lifespan) 시 시드 완료 직후 `fetch_commodity_prices()`를 즉시 실행하여, 스케줄러 첫 실행 전에 새 심볼의 가격이 DB에 적재됩니다.

---

### 테이블 목록 (24개 Alembic 마이그레이션)

| 테이블 | 용도 |
|--------|------|
| sectors | 투자 섹터 (건설기계, 반도체 등) |
| stocks | 개별 종목 |
| news_articles | 수집된 뉴스 기사 |
| news_stock_relations | 뉴스-종목/섹터 매핑 |
| disclosures | DART 공시 |
| macro_alerts | 매크로 경제 리스크 알림 |
| economic_events | 경제 일정 이벤트 |
| fund_signals | 종목별 투자 시그널 |
| daily_briefings | 일일 AI 브리핑 |
| portfolio_reports | 포트폴리오 보고서 |
| news_price_impact | 뉴스-가격 반응 추적 (SPEC-NEWS-001) |
| commodities | 원자재 마스터 (심볼, 카테고리) |
| commodity_prices | 원자재 가격 히스토리 |
| sector_commodity_relations | 섹터-원자재 상관관계 매핑 |
| news_commodity_relations | 뉴스-원자재 연관 매핑 |
| stock_relations | 종목 간 관계 그래프 (SPEC-RELATION-001) |

#### news_price_impact 테이블 (migration 016)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | SERIAL PK | 고유 ID |
| news_id | INTEGER (FK, SET NULL) | 뉴스 기사 ID (삭제 시 null 유지) |
| stock_id | INTEGER (FK, CASCADE) | 종목 ID |
| relation_id | INTEGER (FK, SET NULL) | 뉴스-종목 관계 ID |
| price_at_news | FLOAT NOT NULL | 뉴스 발생 시점 주가 |
| price_after_1d | FLOAT NULL | 1일 후 주가 |
| price_after_5d | FLOAT NULL | 5일 후 주가 |
| return_1d_pct | FLOAT NULL | 1일 수익률 (%) |
| return_5d_pct | FLOAT NULL | 5일 수익률 (%) |
| captured_at | TIMESTAMP NOT NULL | 스냅샷 캡처 시각 |
| backfill_1d_at | TIMESTAMP NULL | 1D 백필 완료 시각 |
| backfill_5d_at | TIMESTAMP NULL | 5D 백필 완료 시각 |
| created_at | TIMESTAMP NOT NULL | 레코드 생성 시각 |

인덱스: stock_id, news_id, captured_at (3개)

---

## 배포 아키텍처

### 프로덕션 환경

```
인터넷
  ├─> Vercel CDN
  │     └─> Next.js 프론트엔드 (자동 배포, main 브랜치)
  │           └─> /api/* 프록시 → Oracle Cloud VM
  │
  └─> Oracle Cloud VM (140.245.76.242)
        ├─> FastAPI 백엔드 (포트 8000, systemd 서비스: newshive)
        │     └─> APScheduler (9개 백그라운드 작업)
        └─> PostgreSQL 16 (내부 포트 5432)
```

### 배포 프로세스

**백엔드 배포 (GitHub Webhook)**

`/api/deploy` 엔드포인트가 GitHub push 이벤트를 수신하면 다음 명령을 실행합니다.

```bash
cd /home/ubuntu/news-hive
git fetch origin
git reset --hard origin/main
sudo systemctl restart newshive
```

**프론트엔드 배포**

Vercel이 `main` 브랜치 push를 감지하면 자동으로 빌드 및 배포합니다.

**수동 배포 명령**

```bash
ssh -i /path/to/ssh-key.key ubuntu@140.245.76.242
cd /home/ubuntu/news-hive
git fetch origin && git reset --hard origin/main
sudo systemctl restart newshive
journalctl -u newshive -n 50 --no-pager
```

### 서비스 관리

```bash
sudo systemctl status newshive    # 서비스 상태 확인
sudo systemctl restart newshive   # 재시작
journalctl -u newshive -f         # 실시간 로그 확인
```

---

## 개발 환경 요구사항

### 백엔드

- Python 3.13 이상
- PostgreSQL 16 (Docker Compose로 실행 가능)
- 가상환경 (venv 또는 conda)

```bash
# 환경 설정
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # API 키 입력 후 저장

# DB 마이그레이션
docker-compose up -d              # PostgreSQL 시작
alembic upgrade head              # 마이그레이션 적용

# 서버 실행
uvicorn app.main:app --reload --port 8000
```

### 프론트엔드

- Node.js 20 이상 (LTS 권장)
- npm 또는 pnpm

```bash
cd frontend
npm install
npm run dev                       # http://localhost:3000
npm run build                     # 프로덕션 빌드
```

### 환경변수 목록

| 변수명 | 필수 | 설명 |
|--------|------|------|
| DATABASE_URL | 필수 | PostgreSQL 연결 URL |
| NAVER_CLIENT_ID | 필수 | Naver 검색 API Client ID |
| NAVER_CLIENT_SECRET | 필수 | Naver 검색 API Secret |
| GEMINI_API_KEY | 필수 | Google Gemini API 키 |
| OPENROUTER_API_KEY | 권장 | OpenRouter 폴백 AI |
| GROQ_API_KEY | 권장 | Groq 폴백 AI |
| KIS_APP_KEY | 선택 | 한국투자증권 API 키 |
| KIS_APP_SECRET | 선택 | 한국투자증권 API Secret |
| DART_API_KEY | 선택 | DART 공시 API 키 |
| ADMIN_PASSWORD | 필수 | 관리자 포털 비밀번호 |

---

## 주요 Python 패키지

| 패키지 | 용도 |
|--------|------|
| fastapi | 웹 프레임워크 |
| sqlalchemy | ORM |
| alembic | DB 마이그레이션 |
| pydantic-settings | 환경변수 관리 |
| apscheduler | 백그라운드 스케줄러 |
| httpx | 비동기 HTTP 클라이언트 |
| feedparser | RSS 피드 파싱 |
| google-generativeai | Gemini AI SDK |
| groq | Groq AI SDK |
| psycopg2-binary | PostgreSQL 드라이버 |
| python-jose | JWT 인증 |
| yfinance | 원자재/주식 시세 수집 |

## 주요 npm 패키지

| 패키지 | 용도 |
|--------|------|
| next | 프레임워크 |
| react | UI 라이브러리 |
| typescript | 타입 시스템 |
| tailwindcss | CSS 유틸리티 |
| recharts | 차트 시각화 |
| date-fns | 날짜 처리 |
| swr | 데이터 페칭 및 캐싱 |
