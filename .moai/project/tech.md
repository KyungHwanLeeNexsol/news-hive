# NewsHive - Technology Stack Documentation

## Framework & Language Overview

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| **Backend Framework** | FastAPI | 0.115.6 | Async REST API framework |
| **Backend Language** | Python | 3.12+ | Server-side implementation |
| **Frontend Framework** | Next.js | 16.1.6 | React SSR framework |
| **Frontend Language** | TypeScript | 5.9.3 | Type-safe frontend code |
| **Frontend Runtime** | React | 19.2.4 | UI component library |

---

## Database & Caching

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Primary Database** | PostgreSQL | 16 | Relational data storage |
| **ORM** | SQLAlchemy | 2.0 | Async database abstraction |
| **Migrations** | Alembic | — | Database versioning |
| **Cache** | Redis | 7 | In-memory caching |
| **Connection Pool** | asyncpg | — | PostgreSQL async driver |

---

## Task Scheduling & Background Jobs

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Task Scheduler** | APScheduler | 3.10.4 | Background job scheduling |
| **Job Storage** | PostgreSQL | 16 | Persistent job store |
| **Execution** | APScheduler | 3.10.4 | 30-minute news collection cycles |

---

## AI & NLP Integration

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **AI - Primary** | Google GenAI | 1.14.0 | Gemini API for classification |
| **AI - Fallback** | OpenAI SDK | — | OpenRouter API integration |
| **Use Cases** | Gemini + Claude | — | Sentiment/urgency classification, briefing |

---

## Market Data & External APIs

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Korean News** | Naver Search API | News article collection |
| **Global News** | Google News RSS | Macro and international news |
| **Disclosures** | DART | Corporate disclosure tracking |
| **Stock Prices** | Naver Finance | Real-time stock data fetching |
| **Market Index** | KRX API | Korean exchange data |

---

## Frontend Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| **Styling** | Tailwind CSS | 4.2.0 | Utility-first CSS |
| **State Management** | Zustand | 5.0.12 | Global state |
| **Charting** | Recharts | 3.8.1 | React charts |
| **Technical Charts** | Lightweight-charts | 5.1.0 | Trading charts |

---

## Development Tools

| Category | Technology | Purpose |
|----------|-----------|---------|
| **Python Linting** | ruff | Fast PEP 8 linter |
| **Python Formatting** | ruff format | Code formatting |
| **Type Checking** | mypy | Static type checking |
| **Testing** | pytest | 888 tests, 85%+ coverage |
| **Async Testing** | pytest-asyncio | Async test support |
| **Package Manager** | uv | Fast Python package manager |
| **Frontend Linting** | ESLint | JavaScript/TypeScript |

---

## Deployment & Infrastructure

| Component | Technology | Details |
|-----------|-----------|---------|
| **Backend Host** | OCI VM | Standard.E2.1.Micro, Ubuntu |
| **Backend Port** | 8000 | uvicorn ASGI server |
| **Service Manager** | systemd | Linux service management |
| **Frontend Host** | Vercel | Global CDN, auto-deploy |
| **Backend IP** | 140.245.76.242 | Fixed OCI instance |

---

## Framework Choice Rationale

### FastAPI
- Async-first design with built-in validation (Pydantic)
- High performance, automatic OpenAPI docs
- Suitable for high-concurrency news processing

### SQLAlchemy 2.0
- Native async support with full ORM features
- Type safety and relationship management
- Suitable for complex stock/sector/commodity relationships

### Pydantic v2
- High-performance validation and serialization
- Type hints and JSON schema generation
- Used for request/response validation across 20 routers

### Next.js 16
- Server-side rendering with React 19 and TypeScript
- Built-in optimization and file-based routing
- Vercel deployment for global CDN

### APScheduler with PostgreSQL
- Persistent job scheduling without external service
- Survives service restarts
- Used for 30-minute news collection and 06:00 briefing

### Redis
- In-memory caching for hot data
- Sub-millisecond latency
- Cache stock prices, sector scores, rate limiting

---

## Development Environment

### Minimum Versions
- Python 3.12+ (f-strings, match statements)
- Node.js 20+ (ESM modules)
- PostgreSQL 14+ (JSON operators)
- Redis 6.0+ (stream support)

### Local Setup
```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
alembic upgrade head

# Frontend
cd frontend
npm install

# Database
docker-compose up -d
```

### Required Environment Variables
- GEMINI_API_KEY
- NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
- TELEGRAM_BOT_TOKEN
- DATABASE_URL (PostgreSQL asyncpg)
- REDIS_URL
- OPENROUTER_API_KEY (fallback)

---

## Build & Test Commands

### Backend

#### Development
```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

#### Testing
```bash
cd backend
uv run pytest tests/ --tb=short -q -m "not slow"
uv run pytest tests/ --cov=app --cov-report=html
```

#### Code Quality
```bash
cd backend
uv run ruff check .                    # Lint
uv run mypy app/                       # Type check
uv run ruff format .                   # Format
```

#### Database Migrations
```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```

### Frontend

#### Development
```bash
cd frontend
npm run dev                # http://localhost:3000
```

#### Build & Production
```bash
cd frontend
npm run build
npm run start
npm run lint
```

---

## Performance Targets

### API Response Time
- Median: < 500ms
- p95: < 2 seconds
- p99: < 5 seconds

### Database Queries
- News retrieval (10): < 100ms
- Stock lookup: < 50ms
- Relation graph (depth 3): < 500ms

### Frontend
- Page load (Lighthouse): >80 score
- Time to Interactive: < 3 seconds

### Infrastructure
- Backend uptime: >99%
- Database availability: >99.9%
- News collection: 100% success

---

## Known Constraints

### AI API
- Gemini free tier: 20 requests/day (rate limiting critical)
- Solution: Queue + OpenRouter fallback

### Infrastructure
- Single OCI VM: No horizontal scaling
- Solution: Async/await for concurrency

### Market Data
- Naver API: Periodic 401 errors
- Solution: Automatic retry with backoff

### Development
- Python 3.12: f-string dict literals cause SyntaxError
- Solution: Use single-line dicts or variables

---

## Upgrade Paths

### FastAPI 0.115 → 1.0
- Non-breaking changes
- Recommended: Test all AI classification

### SQLAlchemy 2.0 → 2.1+
- Query syntax compatible
- Recommended: Performance improvements

### PostgreSQL 16 → 17+
- All SQL compatible
- Recommended: Monitor performance

### Python 3.12 → 3.13+
- Type hints syntax compatible
- Recommended: Enables JIT compiler

### Next.js 16 → 17+
- Check App Router stability
- Recommended: Test in staging

---

## Monitoring & Observability

### Logging
- JSON structured logging via python-json-logger
- All jobs logged to stdout/systemd journal
- Key events: API start, job completion, errors

### Metrics
- APScheduler job success/failure rates
- Gemini API quota usage
- Database query latency
- API endpoint latency
- Cache hit rate

### Health Checks
- GET /health → 200 OK
- Database: Connection pool status
- Redis: PING
- API: GET /stocks/top

---

## Context7 Integration

For library documentation:
- FastAPI: tiangolo/fastapi
- SQLAlchemy: sqlalchemy/sqlalchemy
- PostgreSQL: postgres/postgres
- Redis: redis/redis
- pytest: pytest-dev/pytest
- pydantic: pydantic/pydantic
- Next.js: vercel/next.js
- React: facebook/react
