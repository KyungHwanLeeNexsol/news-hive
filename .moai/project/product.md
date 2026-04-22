# NewsHive - Product Documentation

## Project Overview

**Project Name**: NewsHive

**Description**: AI-powered Korean stock market intelligence platform that automatically tracks sector-level news, analyzes stock relationships, and generates briefings for independent investors and fund managers.

**Target Audience**: 
- Korean retail investors and independent fund managers
- Users seeking comprehensive sector-level market intelligence
- Traders using AI-driven decision support for paper trading

**Project Status**: Active development with core features implemented and additional AI-driven capabilities in progress.

---

## Core Features

### 1. Sector-Based News Tracking
Automatically collects and organizes news by sector, enabling investors to spot industry-level trends that affect multiple holdings.

### 2. Multi-Source News Collection
Aggregates news from:
- Naver News (Korean news portal)
- Google News RSS feeds
- DART corporate disclosure database
- Custom macro news crawlers

Collection runs on 30-minute intervals via APScheduler background jobs.

### 3. AI-Powered News Classification
Claude/Gemini AI automatically:
- Classifies sentiment (strong_positive, positive, mixed, neutral, negative, strong_negative)
- Assigns urgency levels (breaking, important, routine)
- Tags relevant stocks and sectors
- Generates AI summaries

### 4. Stock Relationship Propagation
AI-inferred supply chain and competitive relationships enable indirect news impact discovery.

### 5. News-to-Price Impact Tracking
Captures and analyzes price reactions to news events at T+1D and T+5D intervals.

### 6. Intelligent Stock Following System
Users can follow specific stocks and receive AI-generated keyword matching with real-time Telegram notifications.

### 7. Fund Manager Stock Selection
Automated stock candidate selection using multi-factor scoring:
- News sentiment factor (25%)
- Technical factor (25%)
- Supply-demand factor (25%)
- Valuation factor (25%)

Top 10 candidates ranked by composite score for daily consideration.

### 8. Daily AI-Generated Briefing
Scheduled briefing generation that includes macro alerts, sector momentum, candidate analysis, KS200 signals, and disclosure impacts.

### 9. KS200 Index Trading Signals
Technical indicator-based buy/sell signals for Korean 200 index with paper trading simulation.

### 10. Disclosure Impact Analysis
Monitors corporate disclosures from DART with AI impact scoring and preemptive signal generation.

---

## Key Business Logic

### News Pipeline
Multi-source collection → Article ingestion → AI classification → Stock/sector tagging → Relationship propagation → Impact scoring → User notifications

### Fund Manager Stock Selection
Daily scheduler triggers candidate gathering with recent news → Factor scoring (4 dimensions) → Composite scoring → Top 10 ranking

### Corporate Governance Enhancement (SPEC-AI-011)
Detects holding companies → Identifies subsidiaries → Applies holding company discount (-5 points) → Alerts in briefing

### Briefing Generation Pipeline
Macro alerts → Sector momentum → Candidate analysis → KS200 signals → Disclosure impact → AI briefing generation → Push notifications

### KS200 Trading System
Technical indicators (RSI, MACD, Bollinger Bands) → Signal generation → Paper trading simulation → Backtesting → Daily performance reporting

---

## Core Data Models

| Model | Purpose |
|-------|---------|
| NewsArticle | News articles with sentiment, urgency, and AI summary |
| Stock | Stock ticker, company info, sector classification |
| Sector | Sector metadata and classification |
| StockRelation | Supply chain and competitive relationships |
| NewsStockRelation | Article relevance to stocks |
| FundSignal | Fund manager candidates with factor scores |
| KS200Signal | Index trading signals |
| StockFollowing | User stock watch lists |
| StockKeyword | Following keywords (4 categories) |
| Disclosure | Corporate disclosures from DART |
| Commodity | Commodity tracking |
| MacroAlert | Economic alerts |

---

## Technology Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| Framework | FastAPI | 0.115.6 | Async web framework for REST API |
| Language | Python | 3.12 | Backend implementation |
| Database | PostgreSQL | 16 | Primary data storage |
| Cache | Redis | 7 | Caching and session storage |
| Scheduler | APScheduler | 3.10.4 | Background job scheduling |
| ORM | SQLAlchemy | 2.0 | Database abstraction with async support |
| Migrations | Alembic | — | Database version control |
| AI - Primary | Google GenAI | 1.14.0 | Gemini API for classification (free tier) |
| AI - Fallback | OpenAI SDK | — | OpenRouter API integration |
| Frontend | Next.js | 16.1.6 | React server-side rendering framework |
| Frontend | React | 19.2.4 | UI component library |
| Language | TypeScript | 5.9.3 | Type-safe frontend code |
| Styling | Tailwind CSS | 4.2.0 | Utility-first CSS framework |
| State | Zustand | 5.0.12 | Lightweight state management |
| Charts | Recharts | 3.8.1 | React charting library |
| Technical | Lightweight-charts | 5.1.0 | Professional trading charts |
| Testing | pytest | 8.3.4 | Python testing framework |
| Testing | pytest-asyncio | — | Async test support |
| Linting | ruff | — | Python linter and formatter |
| Type Check | mypy | — | Static type checking |
| Package Mgr | uv | — | Fast Python package manager |
| Deployment | systemd | — | Linux service management |
| Deployment | Vercel | — | Frontend hosting platform |

---

## Rate Limiting & Constraints

### AI API Constraints
- **Gemini**: 20 requests/day limit (free tier) - CRITICAL BOTTLENECK
- **Rate Limiting**: Essential to prevent quota exhaustion
- **Fallback**: OpenRouter API for overflow scenarios

### Infrastructure Constraints
- **Single OCI VM**: No horizontal scaling
- **Memory**: Limited concurrent operations
- **Deployment**: Bare metal (no Docker in production)

### Market Data Constraints
- **Korean Exchange (KRX)**: Trading hours only (09:00-15:30 KST)
- **News Sources**: Korean language focused
- **API Reliability**: Naver API periodically returns 401 errors

---

## Deployment

### Backend
- **Host**: OCI VM (140.245.76.242:8000)
- **Service**: systemd unit `newshive`
- **Runtime**: uvicorn ASGI server
- **Deploy**: `scripts/deploy.sh` (git pull + pip install + alembic + systemctl restart)
- **Logs**: `journalctl -u newshive -n 50 --no-pager`

### Frontend
- **Platform**: Vercel
- **Branch**: main (automatic deployment)
- **Backend URL**: BACKEND_INTERNAL_URL=http://140.245.76.242:8000

### Database
- **Local**: docker-compose.yml (PostgreSQL + Redis)
- **Production**: PostgreSQL 16 on OCI (TBD)

---

## Known Issues & Limitations

### API Reliability
- Naver News API: Periodic 401 errors (key rotation needed)
- Some stock codes don't return data from Naver polling; mobile API fallback added

### Development
- Python 3.12: f-string dict literals with bracket access cause SyntaxError

### Feature Limitations
- Paper trading only (no real order execution)
- Gemini free tier: 20 requests/day (rate limiting critical)
- Single VM: No horizontal scaling

---

## Success Metrics

- Backend uptime > 99%
- API response time < 2 seconds (p95)
- News collection 100% job completion
- AI classification accuracy > 85%
- Stock relevance precision > 80%
