# NewsHive - Project Structure Documentation

## Directory Tree (Top 2 Levels)

```
news-hive/
├── backend/                    # FastAPI Python backend
│   ├── app/
│   │   ├── main.py            # FastAPI app, lifespan, migrations
│   │   ├── database.py        # SQLAlchemy async setup
│   │   ├── models/            # 30+ ORM models
│   │   ├── routers/           # 20 REST API modules
│   │   ├── schemas/           # Pydantic validators
│   │   ├── services/          # 50+ business logic services
│   │   └── seed/              # Database seed data
│   ├── alembic/               # 50+ database migrations
│   ├── tests/                 # 888 pytest tests
│   ├── pyproject.toml         # uv/Poetry, pytest config
│   └── .env.example           # Environment template
│
├── frontend/                   # Next.js 16 React frontend
│   ├── src/app/               # 20+ route pages
│   ├── src/components/        # React components
│   ├── src/store/             # Zustand state
│   ├── src/utils/             # Utilities
│   ├── package.json           # npm dependencies
│   └── tailwind.config.ts     # Tailwind CSS
│
├── scripts/                    # Deployment utilities
│   ├── deploy.sh              # Production deploy
│   └── setup.sh               # Infrastructure setup
│
├── docker-compose.yml         # Local: PostgreSQL + Redis
├── .moai/                     # MoAI config
├── .claude/                   # Claude Code rules
├── README.md                  # Korean overview
└── CHANGELOG.md               # Version history
```

---

## Architecture Pattern

**Layered Monolith**: Separation of concerns with clear boundaries.

```
Frontend (Next.js, port 3000)
    ↓ HTTP/JSON
REST API (FastAPI, port 8000)
    ↓
Service Layer (Crawlers, AI, scoring)
    ↓
Data Access (SQLAlchemy ORM)
    ↓
Task Scheduler (APScheduler)
    ↓
PostgreSQL 16 + Redis 7
```

---

## Key File Locations

### Backend Entry Points
- **App**: `backend/app/main.py` (FastAPI instance + lifespan)
- **Database**: `backend/app/database.py` (AsyncEngine setup)
- **Scheduler**: `backend/app/services/scheduler.py` (APScheduler jobs)

### API Routers (20 modules)
| Router | Purpose |
|--------|---------|
| `news.py` | News CRUD, search |
| `stocks.py` | Stock data, relations |
| `sectors.py` | Sector momentum |
| `fund_manager.py` | Stock candidates |
| `following.py` | User watch lists |
| `disclosures.py` | DART data |
| `vip_trading.py` | VIP signals |
| `ks200_trading.py` | Index signals |
| `paper_trading.py` | Paper trades |
| `push.py` | Push notifications |
| `auth.py` | Authentication |
| `chat.py` | AI chat |
| Plus 8 more (commodities, alerts, macro, etc.) |

### Business Services (50+ modules)
- `ai_classifier.py` - Sentiment/urgency classification
- `ai_client.py` - Gemini/OpenAI wrapper
- `fund_manager.py` - Stock selection
- `factor_scoring.py` - 4-factor scoring
- `relation_propagator.py` - Indirect impacts
- `keyword_generator.py` - AI keywords
- `keyword_matcher.py` - Notifications
- `news_crawler.py` - Collection orchestration
- `naver_finance.py` - Stock price API
- `technical_indicators.py` - RSI, MACD, Bands
- `disclosure_impact_scorer.py` - DART analysis
- `ks200_signal.py` - Index signals
- Plus 38+ additional services

### ORM Models (30+ classes)
Located in `backend/app/models/`:
- News, Stock, Sector, Commodity
- FundSignal, KS200Signal, VIPTrade, PaperTrade
- StockFollowing, Disclosure, MacroAlert
- User, DailyBriefing, EconomicEvent
- Plus 15+ additional models

### Database Migrations
`backend/alembic/versions/` - 50+ numbered files
- Example: `036_spec_ai_004_disclosure_impact.py`
- Run auto on app startup
- Manual: `alembic upgrade head`

### Test Suite
`backend/tests/` - 888 passing tests
- Run: `cd backend && uv run pytest tests/ -q -m "not slow"`
- Target: 85%+ coverage

### Frontend Pages (Next.js App Router)
```
frontend/src/app/
├── page.tsx               # Home
├── news/[id]/page.tsx    # News detail
├── stocks/page.tsx       # Stock list
├── sectors/page.tsx      # Sector analysis
├── following/[code]/     # Watch list detail
├── disclosures/page.tsx  # DART list
├── ks200_trading/        # Index signals
├── vip_trading/          # VIP portfolio
├── paper_trading/        # Paper trading
├── chat/page.tsx         # AI chat
├── auth/login            # Login/register
├── ... (20+ total)
```

---

## Module Organization

### Backend Layers

**Routes** - HTTP handling, validation, serialization
**Services** - Business logic, external APIs, orchestration
**Models** - ORM definitions, relationships, queries
**Infrastructure** - Database, scheduler, logging setup

### Frontend Structure

**Pages** - Route-based components
**Components** - Reusable React elements
**State** - Zustand stores
**Utils** - Helpers, API client, constants

---

## Data Flow Examples

### News Pipeline
Crawlers → NewsArticle DB → AI classification → Stock relation matching → Indirect propagation → Notifications

### Fund Manager Selection
Recent news → 4-factor scoring → Ranking → FundSignal DB

### Briefing Generation
Macro alerts → Sector momentum → Candidate analysis → KS200 signals → Disclosure impact → Gemini briefing → Push

### Stock Following
User follows → AI keywords (4 categories) → Periodic matching → Telegram notifications

---

## Environment & Deployment

### Local Development
```bash
docker-compose up -d
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

### Required Environment Variables
- GEMINI_API_KEY - Google GenAI
- NAVER_CLIENT_ID, NAVER_CLIENT_SECRET - Naver
- TELEGRAM_BOT_TOKEN - Telegram Bot
- DATABASE_URL - PostgreSQL asyncpg
- REDIS_URL - Redis
- OPENROUTER_API_KEY - Fallback AI

### Production
- Backend: OCI VM (140.245.76.242:8000), systemd
- Frontend: Vercel (auto-deploy from main)
- Database: PostgreSQL 16 on OCI

### Migrations
- Auto on startup
- Manual: `alembic upgrade head`
- New: `alembic revision --autogenerate -m "desc"`

---

## Performance & Constraints

### Bottlenecks
- Gemini free tier: 20 requests/day (rate limiting critical)
- Single VM: No horizontal scaling
- News collection: 30-minute intervals (batch-based)

### Optimization
- AsyncIO/await throughout
- Redis caching for hot data
- Database indices on frequent columns
- Connection pooling
- Background job distribution

### Monitoring
- JSON logging to stdout
- APScheduler job tracking
- Database query logging
- API latency tracking

---

## Commands

| Task | Command |
|------|---------|
| Install deps | `cd backend && uv pip install` |
| Dev server | `cd backend && uv run uvicorn app.main:app --reload` |
| Tests | `cd backend && uv run pytest tests/ -q -m "not slow"` |
| Type check | `cd backend && uv run mypy app/` |
| Lint | `cd backend && uv run ruff check .` |
| Format | `cd backend && uv run ruff format .` |
| Migration | `cd backend && alembic revision --autogenerate -m "desc"` |
| Migrate | `cd backend && alembic upgrade head` |
| Frontend dev | `cd frontend && npm run dev` |
| Frontend build | `cd frontend && npm run build` |

---

## Quality Standards

- Linting: ruff
- Type checking: mypy
- Testing: pytest 85%+ coverage
- Formatting: ruff format
- Standards: SQLAlchemy 2.0, FastAPI, Pydantic v2, async/await
