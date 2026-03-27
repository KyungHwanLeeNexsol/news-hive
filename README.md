# NewsHive

섹터 기반 투자 뉴스 추적 앱 - 특정 종목만 보면 놓치기 쉬운 산업 섹터 내 중요 뉴스를 자동으로 추적합니다.

## 주요 기능

- **섹터 단위 뉴스 추적**: 동일 섹터의 종목 뉴스를 모아 간접적이지만 중요한 뉴스 포착
- **뉴스 자동 수집**: 네이버 뉴스, Google News RSS를 30분 주기로 자동 수집
- **AI 뉴스 분류**: Claude/Gemini AI가 뉴스를 관련 섹터/종목에 자동 태깅
- **간접 영향 뉴스 전파**: AI가 추론한 종목 관계 그래프(공급망/경쟁사)를 기반으로 간접 호재/악재 뉴스 자동 전파
- **뉴스-가격 반응 추적**: 뉴스 발행 시점 주가 스냅샷 및 T+1D/T+5D 가격 변화율 추적

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
