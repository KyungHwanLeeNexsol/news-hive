# NewsHive

섹터 기반 투자 뉴스 추적 앱 - 특정 종목만 보면 놓치기 쉬운 산업 섹터 내 중요 뉴스를 자동으로 추적합니다.

## 주요 기능

- **섹터 단위 뉴스 추적**: 동일 섹터의 종목 뉴스를 모아 간접적이지만 중요한 뉴스 포착
- **뉴스 자동 수집**: 네이버 뉴스, Google News RSS를 30분 주기로 자동 수집
- **AI 뉴스 분류**: Claude/Gemini AI가 뉴스를 관련 섹터/종목에 자동 태깅
- **간접 영향 뉴스 전파**: AI가 추론한 종목 관계 그래프(공급망/경쟁사)를 기반으로 간접 호재/악재 뉴스 자동 전파
- **뉴스-가격 반응 추적**: 뉴스 발행 시점 주가 스냅샷 및 T+1D/T+5D 가격 변화율 추적
- **기업 팔로잉 시스템**: 관심 종목을 팔로잉하면 AI가 핵심 키워드를 자동 생성하고, 매칭되는 뉴스/공시를 텔레그램으로 실시간 알림

## 기술 스택

- **Frontend**: Next.js (App Router) + TypeScript + Tailwind CSS v4
- **Backend**: Python FastAPI + SQLAlchemy + Alembic
- **Database**: PostgreSQL 16 (docker-compose)
- **스케줄러**: APScheduler (30분 간격 백그라운드 뉴스 수집)
- **AI**: Gemini / OpenRouter API

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

## 배포

- **Backend**: OCI VM (`140.245.76.242:8000`) + systemd
- **Frontend**: Vercel (main 브랜치 자동 배포)
- **배포 스크립트**: `scripts/deploy.sh`

## 필요한 API 키

- **Naver**: https://developers.naver.com (검색 API)
- **Anthropic/Gemini**: AI 분류 및 뉴스 전파 추론용
- **Telegram Bot Token**: 팔로잉 시스템 알림용 (BotFather에서 발급)

## 팔로잉 기능 (Following System)

### 기능 설명

사용자가 관심 종목을 팔로잉하면:

1. AI가 4가지 카테고리(제품, 경쟁사, 전방산업, 시장키워드)에서 핵심 키워드를 자동 생성
2. 스케줄러가 주기적으로 신규 뉴스/공시를 사용자 키워드와 매칭
3. 매칭되는 콘텐츠를 텔레그램으로 실시간 알림 발송

### 환경변수 설정

```bash
# .env 파일에 추가
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

### 텔레그램 봇 설정

1. Telegram에서 `@BotFather`와 대화하여 봇 생성
2. 봇의 토큰을 `TELEGRAM_BOT_TOKEN` 환경변수에 설정
3. 앱 시작 시 webhook URL이 자동으로 등록됨

### 데이터베이스 마이그레이션

```bash
# 팔로잉 테이블 생성 (revision 040)
alembic upgrade head
```

### API 엔드포인트

#### 종목 팔로잉

```bash
# 종목 팔로잉 등록
POST /api/following/stocks
Content-Type: application/json

{
  "stock_code": "298020"
}

# 팔로잉 목록 조회
GET /api/following/stocks

# 팔로잉 해제
DELETE /api/following/stocks/{stock_code}
```

#### 키워드 관리

```bash
# 키워드 목록 조회
GET /api/following/stocks/{stock_code}/keywords

# 수동 키워드 추가
POST /api/following/stocks/{stock_code}/keywords
Content-Type: application/json

{
  "keyword": "스판덱스",
  "category": "custom"
}

# AI 키워드 자동 생성
POST /api/following/stocks/{stock_code}/keywords/ai-generate

# 키워드 삭제
DELETE /api/following/stocks/{stock_code}/keywords/{keyword_id}
```

#### 텔레그램 연동

```bash
# 텔레그램 연동 코드 생성
POST /api/following/telegram/link

# 텔레그램 연동 상태 확인
GET /api/following/telegram/status

# 텔레그램 연동 해제
DELETE /api/following/telegram/link
```

#### 알림 히스토리

```bash
# 알림 히스토리 조회
GET /api/following/notifications
```

### 사용 예시

1. 프론트엔드에서 `/following` 페이지 접속
2. 관심 종목 코드(예: 298020) 입력 후 팔로잉
3. AI가 자동 생성한 키워드 확인/수정
4. 텔레그램 연동: "텔레그램 연동" 버튼 클릭 후 봇에 코드 전송
5. 이후 매칭되는 뉴스/공시가 텔레그램으로 실시간 알림

### 기술 구현

- **모델**: `backend/app/models/following.py` - StockFollowing, StockKeyword, KeywordNotification
- **라우터**: `backend/app/routers/following.py` - 12개 엔드포인트
- **서비스**:
  - `keyword_generator.py` - AI 키워드 생성
  - `keyword_matcher.py` - 키워드 매칭 및 알림 발송
  - `telegram_service.py` - Telegram Bot API 통합
- **스케줄러**: APScheduler 10분 간격 키워드 매칭 작업
- **프론트엔드**: `/following` 및 `/following/[stock_code]` 페이지
