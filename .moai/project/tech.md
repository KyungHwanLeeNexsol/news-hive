# NewsHive — Tech Stack

## Backend

| 항목 | 버전 / 내용 |
|------|------------|
| Language | Python 3.12+ |
| Framework | FastAPI 0.115.6 |
| ASGI Server | Uvicorn 0.34.0 |
| ORM | SQLAlchemy 2.0.36 |
| Migration | Alembic 1.14.1 (앱 시작 시 자동 실행) |
| Scheduler | APScheduler 3.10.4 (SQLAlchemy 잡스토어, misfire_grace=3600s) |
| Package Manager | uv (pip fallback) |
| DB | PostgreSQL 16 (로컬 설치, Docker 없음) |
| Cache | Redis 7 (선택, 인메모리 폴백) |

## AI / ML

| 항목 | 내용 |
|------|------|
| Primary LLM | Google Gemini (free tier, 20req/day 제한) |
| Fallback LLM | Z.AI (GLM) → OpenAI |
| 용도 | 감성 분석, 종목 분류, 프롬프트 자동 개선, 키워드 생성 |

## External APIs

| API | 용도 | 주의사항 |
|-----|------|----------|
| Naver Finance | 주가 스크래핑 (현재가, 일봉) | HTML 구조 변경 시 선택자 수정 필요 |
| Naver News | 뉴스 검색 | 401 주기적 발생 (키 만료) |
| DART | 공시 크롤링 | API 키 필요, 30분 주기 |
| KIS (한국투자증권) | 실시간 주가 (미래 확장) | WebSocket 기반 |

## Frontend

| 항목 | 버전 |
|------|------|
| Framework | Next.js 16.1.6 (App Router) |
| UI Library | React 19.2.4 |
| Language | TypeScript 5.9.3 |
| Styling | Tailwind CSS 4.2.0 |
| State | Zustand 5.0.12 |
| Charts | Recharts 3.8.1, Lightweight-charts 5.1.0 |
| Deploy | Vercel (main 브랜치 자동 배포) |

## Infrastructure

| 항목 | 내용 |
|------|------|
| Server | OCI VM.Standard.E2.1.Micro (Ubuntu, 140.245.76.242) |
| Process | systemd (newshive.service) |
| Deploy | scripts/deploy.sh (git pull + pip + alembic + systemctl) |
| Monitoring | Prometheus + Grafana (monitoring/ 디렉토리) |
| Deploy Guard | 15:15~15:45 KST 자동 대기 (급등 시그널 생성 중 배포 차단) |

## Testing

| 항목 | 내용 |
|------|------|
| Framework | pytest 8.3.4 + pytest-asyncio 0.25.0 |
| Coverage | pytest-cov 6.0.0 |
| Time mocking | freezegun 1.4.0 |
| 실행 | uv run pytest tests/ --tb=short -q -m "not slow" |
| 총 테스트 수 | 1511개+ (SPEC-AI-050 기준) |

## Linting

```bash
uv run ruff check .      # 린팅
uv run mypy app/         # 타입 체크
```

## Key Constants (Business Logic)

| 상수 | 값 | 위치 |
|------|-----|------|
| BUY_CUTOFF | time(11, 0) | surge_trading_service.py |
| max_open_positions | 7 | surge_trading_service.py |
| position_pct | 0.14 (14%) | surge_trading_service.py |
| max_daily_entries | 5 | surge_trading_service.py |
| 손절 | -8% | surge_trading_service.py |
| 익절 | +15% | surge_trading_service.py |
| 최대 보유 | 5거래일 | surge_trading_service.py |

## SPEC Implementation History

| SPEC | 내용 | 상태 |
|------|------|------|
| SPEC-AI-003 | 4종 선행 기술 탐지기 | 완료 |
| SPEC-AI-004 | 공시 기반 선제 시그널 | 완료 |
| SPEC-AI-006 | 자동 개선 루프 | 완료 |
| SPEC-AI-012 | 4종 앙상블 급등 탐지 | 완료 |
| SPEC-AI-013 | 자동 매매 포트폴리오 | 완료 |
| SPEC-AI-027 | 그룹 계열사 테마캐리 탐지 | 완료 |
| SPEC-AI-028 | 공시 역신호 필터링 | 완료 |
| SPEC-AI-029 | 적응형 급등 확률 임계값 | 완료 |
| SPEC-AI-030 | volume_news_combo 추격매수 방지 | 완료 |
| SPEC-AI-041 | 급등예측 자동평가·자가개선 루프 | 완료 |
| SPEC-AI-042 | Preday 공시 갭업 조기 진입 | 완료 |
| SPEC-AI-050 | 주말갭업탐지 + 동적뉴스윈도우 + BEAR방어 | 완료 (2026-06-17) |
