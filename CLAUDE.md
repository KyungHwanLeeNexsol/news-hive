# Stock News Tracker - 섹터 기반 투자 뉴스 추적 앱

## 프로젝트 목적
투자자가 특정 종목만 보면 놓치기 쉬운 **산업 섹터 내 중요 뉴스**를 자동으로 추적하는 앱.

### 핵심 사용 시나리오
- 대창단조(포크레인 하부 구조물)에 투자 중
- 같은 섹터: 대창단조, 진성이엔씨, 현대제철이 과점
- "현대제철 중기사업부 매각" 뉴스가 뜸 → 대창단조만 보고 있으면 이 뉴스를 놓침
- **섹터 단위로 종목을 묶고, 각 종목별 뉴스를 모아서** 간접적이지만 중요한 뉴스를 포착

### 뉴스 수집 2가지 유형
1. **개별 종목 뉴스**: 해당 종목명이 기사에 언급되면 무조건 팔로우업
2. **산업 뉴스**: 업종 전체에 해당될 것 같으면 무조건 팔로우업

---

## 기술 스택
- **Frontend**: Next.js (App Router) + TypeScript + Tailwind CSS v4
- **Backend**: Python FastAPI + SQLAlchemy + Alembic
- **Database**: PostgreSQL (docker-compose로 실행)
- **스케줄러**: APScheduler (30분 간격 백그라운드 뉴스 수집)
- **AI 분류**: Anthropic Claude API (뉴스 → 섹터/종목 자동 매핑)
- **뉴스 소스**: Naver 검색 API, Google News RSS, NewsAPI.org

---

## 프로젝트 구조
```
stock-news-tracker/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 앱 진입점 + 스케줄러 시작
│   │   ├── config.py                # 환경변수 (pydantic-settings)
│   │   ├── database.py              # SQLAlchemy 엔진 + 세션
│   │   ├── models/                  # SQLAlchemy ORM 모델
│   │   │   ├── sector.py            # Sector (섹터)
│   │   │   ├── stock.py             # Stock (종목)
│   │   │   ├── news.py              # NewsArticle (뉴스 기사)
│   │   │   └── news_relation.py     # NewsStockRelation (뉴스-종목/섹터 매핑)
│   │   ├── schemas/                 # Pydantic 요청/응답 스키마
│   │   ├── routers/                 # API 라우터
│   │   │   ├── sectors.py           # 섹터 CRUD + 뉴스 조회
│   │   │   ├── stocks.py            # 종목 CRUD + 뉴스 조회
│   │   │   └── news.py              # 전체 뉴스 조회 + 수동 새로고침
│   │   ├── services/
│   │   │   ├── news_crawler.py      # 크롤러 통합 관리자 (orchestrator)
│   │   │   ├── crawlers/
│   │   │   │   ├── naver.py         # 네이버 뉴스 검색 API
│   │   │   │   ├── google.py        # Google News RSS 파싱
│   │   │   │   └── newsapi.py       # NewsAPI.org
│   │   │   ├── ai_classifier.py     # Claude API로 뉴스→섹터/종목 분류
│   │   │   └── scheduler.py         # APScheduler 설정
│   │   └── seed/
│   │       └── sectors.py           # 한국 증시 업종 초기 데이터
│   ├── alembic/                     # DB 마이그레이션
│   ├── requirements.txt
│   └── .env                         # (gitignore됨) .env.example 참고
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx             # 대시보드: 섹터 카드 목록
│   │   │   ├── sectors/[id]/page.tsx # 섹터 상세: 종목 목록 + 섹터 뉴스 피드
│   │   │   ├── stocks/[id]/page.tsx  # 종목 상세: 개별 종목 뉴스 피드
│   │   │   └── manage/page.tsx      # 관리: 섹터/종목 추가·삭제
│   │   ├── components/              # UI 컴포넌트
│   │   └── lib/api.ts               # Backend API 호출 함수
│   ├── next.config.ts               # /api/* → FastAPI 프록시 rewrite 설정됨
│   └── package.json
└── docker-compose.yml               # PostgreSQL 16
```

---

## DB 스키마

### sectors
- `id` SERIAL PK
- `name` VARCHAR(100) — 섹터명 (건설기계, 반도체 등)
- `is_custom` BOOLEAN — 사용자가 직접 만든 섹터 여부
- `created_at` TIMESTAMP

### stocks
- `id` SERIAL PK
- `sector_id` FK → sectors
- `name` VARCHAR(100) — 종목명 (대창단조 등)
- `stock_code` VARCHAR(20) — 종목코드 (015230 등)
- `keywords` TEXT[] — 뉴스 검색용 추가 키워드 배열
- `created_at` TIMESTAMP

### news_articles
- `id` SERIAL PK
- `title` VARCHAR(500)
- `summary` TEXT — AI 생성 요약
- `url` VARCHAR(1000) UNIQUE — 중복 방지 기준
- `source` VARCHAR(50) — naver / google / newsapi
- `published_at` TIMESTAMP
- `collected_at` TIMESTAMP

### news_stock_relations
- `id` SERIAL PK
- `news_id` FK → news_articles
- `stock_id` FK → stocks (nullable)
- `sector_id` FK → sectors (nullable)
- `match_type` ENUM('keyword', 'ai_classified')
- `relevance` VARCHAR(20) — 'direct' / 'indirect'

---

## API 엔드포인트

### 섹터
- `GET /api/sectors` — 전체 섹터 목록 (종목 수 포함)
- `POST /api/sectors` — 커스텀 섹터 생성
- `GET /api/sectors/{id}` — 섹터 상세 (종목 목록 포함)
- `DELETE /api/sectors/{id}` — 커스텀 섹터 삭제
- `GET /api/sectors/{id}/news` — 해당 섹터 관련 뉴스

### 종목
- `POST /api/sectors/{id}/stocks` — 섹터에 종목 추가
- `DELETE /api/stocks/{id}` — 종목 삭제
- `GET /api/stocks/{id}/news` — 해당 종목 뉴스

### 뉴스
- `GET /api/news` — 전체 최신 뉴스
- `POST /api/news/refresh` — 수동 뉴스 수집 트리거

---

## 뉴스 수집 파이프라인
```
스케줄러(30분) 또는 수동 트리거
  ↓
각 크롤러 병렬 실행 (Naver/Google/NewsAPI)
  ↓
URL 기반 중복 제거
  ↓
Claude API로 AI 분류 (관련 섹터/종목 태깅 + 요약)
  ↓
DB 저장 (news_articles + news_stock_relations)
```

### AI 분류 프롬프트 설계
```
뉴스 기사: "{title}"
등록된 섹터/종목:
- 건설기계: [대창단조, 진성이엔씨, 현대제철]
- 반도체: [삼성전자, SK하이닉스]
...

이 뉴스가 관련된 섹터와 종목을 JSON으로 응답해.
직접 언급된 종목은 "direct", 간접 영향은 "indirect"로 표시.
```

---

## 구현 순서 (Phase별)

### Phase 1: 핵심 백엔드 ✅ 셋업 완료 → 구현 필요
1. `backend/app/config.py` — pydantic-settings로 환경변수 로드
2. `backend/app/database.py` — SQLAlchemy 엔진 + 세션 팩토리
3. `backend/app/models/` — 4개 테이블 ORM 모델
4. Alembic 초기화 + 마이그레이션 생성
5. `backend/app/main.py` — FastAPI 앱 + 라우터 등록
6. `backend/app/seed/sectors.py` — 한국 증시 업종 초기 데이터

### Phase 2: 섹터/종목 CRUD API
7. `backend/app/schemas/` — Pydantic 스키마
8. `backend/app/routers/sectors.py` — 섹터 CRUD
9. `backend/app/routers/stocks.py` — 종목 CRUD

### Phase 3: 뉴스 수집 시스템
10. `backend/app/services/crawlers/naver.py` — 네이버 뉴스 API
11. `backend/app/services/crawlers/google.py` — Google News RSS
12. `backend/app/services/crawlers/newsapi.py` — NewsAPI.org (선택)
13. `backend/app/services/news_crawler.py` — 크롤러 통합 오케스트레이터
14. `backend/app/services/scheduler.py` — APScheduler 30분 주기

### Phase 4: AI 뉴스 분류
15. `backend/app/services/ai_classifier.py` — Claude API 연동
16. 수집→분류→저장 파이프라인 통합

### Phase 5: 프론트엔드 UI
17. 대시보드 (섹터 카드 목록)
18. 섹터 상세 (종목 리스트 + 뉴스 피드)
19. 종목 상세 (개별 뉴스 피드)
20. 관리 페이지 (섹터/종목 CRUD)
21. 새로고침 버튼

---

## 실행 방법

### DB 실행
```bash
docker-compose up -d
```

### Backend 실행
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env      # .env 파일 편집하여 API 키 입력
alembic upgrade head      # DB 마이그레이션
uvicorn app.main:app --reload --port 8000
```

### Frontend 실행
```bash
cd frontend
npm install
npm run dev               # http://localhost:3000
```

---

## 필요한 API 키
- **Naver**: https://developers.naver.com → 애플리케이션 등록 → 검색 API
- **NewsAPI**: https://newsapi.org → 무료 플랜 (일 100건)
- **Anthropic**: https://console.anthropic.com → API 키 발급

---

## 개발 규칙
- Backend: Python 3.11+, FastAPI, async 함수 사용
- Frontend: TypeScript 필수, Tailwind CSS v4 사용
- DB 변경 시 반드시 Alembic 마이그레이션 생성
- 뉴스 크롤러는 `crawlers/` 하위에 개별 파일로 분리 (새 소스 추가 용이)
- AI 분류 결과는 news_stock_relations 테이블에 저장
- 프론트엔드 → 백엔드 호출은 `/api/*` 프록시로 (next.config.ts에 설정됨)
