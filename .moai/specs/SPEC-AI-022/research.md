# SPEC-AI-022 Research: Signal Coverage Expansion

## 1. Current Signal Generation Architecture

### 1.1 Service Topology

The surge_candidate signal generation pipeline lives entirely in `backend/app/services/` and is orchestrated by `scheduler.py` (08:30 KST batch and intraday triggers). The end-to-end chain consumed today (2026-05-29) is:

```
scheduler.py
  └─► fund_manager.run_surge_signal_generation()
        └─► surge_detector.gather_surge_candidates(db, recent_news, config, legacy_candidates, market_regime)
              ├─► detect_theme_news_cluster()        # tag: "theme_cluster"
              ├─► detect_volume_surge_news_combo()   # tag: "volume_news_combo"
              ├─► detect_disclosure_surge_pattern()  # tag: "disclosure_pattern"
              ├─► detect_immediate_disclosure_signal() # tag: "immediate_disclosure"
              └─► [merge → compute_ensemble_score → recent_surge_penalty → threshold/bypass filter]
        └─► persist FundSignal(signal_type="surge_candidate", surge_metadata=JSON{...})
```

Downstream consumers:
- `surge_trading_service.get_today_signals(db, min_probability=Decimal("0.30"))` — buy candidate filter (SPEC-AI-021 boosts confidence here)
- `surge_trading_service.execute_buy_orders(db)` — 09:05 KST batch
- `paper_executed` boolean on `fund_signals` — marks signals that crossed the execution gate

### 1.2 surge_metadata JSON Schema (de-facto, from `surge_candidate_to_signal_metadata`)

```json
{
  "surge_probability_score": 0.0..1.0,
  "surge_basis": ["theme_cluster", "volume_news_combo", "disclosure_pattern", "immediate_disclosure", "legacy", "carry_over"],
  "theme_cluster_score": 0.0..1.0,
  "combo_score": 0.0..1.0,
  "pattern_score": 0.0..1.0,
  "immediate_disclosure_score": 0.0..1.0,
  "legacy_score": 0.0..1.0
}
```

SPEC-AI-022 must extend this schema with two new values:
- `surge_basis += ["theme_propagation"]` (REQ-AI022-001)
- new `signal_type` value `"volume_anomaly"` at the FundSignal level (REQ-AI022-002) — NOT a new `surge_basis` value, because volume_anomaly signals are NOT surge_candidate.

### 1.3 Existing `signal_type` Values in `fund_signals` Table

| signal_type | Producer | Comment |
|---|---|---|
| `buy` / `sell` / `hold` | `fund_manager` legacy AI signals | Older path, still active |
| `surge_candidate` | `surge_detector` + `fund_manager.run_surge_signal_generation` | Today's 68/day output |
| `disclosure_impact` | `disclosure_impact_scorer` (SPEC-AI-004) | Disclosure-driven |
| `sector_ripple` | `disclosure_impact_scorer.generate_sector_ripple_signals` | Sector contagion |
| `gap_pullback_candidate` | `disclosure_impact_scorer` | Gap-down recovery |

SPEC-AI-022 will introduce two new `signal_type` values:
- `theme_propagation` (REQ-AI022-001) — a new low-confidence sibling of `surge_candidate`. Separate `signal_type` is preferable to `surge_candidate + surge_basis=["theme_propagation"]` so that the BUY pipeline can exclude them by default (`paper_executed=False`) without modifying the existing `get_today_signals` query.
- `volume_anomaly` (REQ-AI022-002) — fully orthogonal to the surge_candidate scoring system.

## 2. Stock / Sector / Theme Grouping Data

### 2.1 `stocks` Table (from `app/models/stock.py`)

```python
class Stock(Base):
    __tablename__ = "stocks"
    id: int (PK)
    sector_id: int (FK → sectors.id)  ← Primary grouping vector available today
    name: str
    stock_code: str
    market: str | None              # KOSPI / KOSDAQ
    market_cap: int | None          # 시가총액 (억원)
    keywords: list[str] | None
    created_at: datetime
```

Key observation: There is no `theme_group_id`, no `conglomerate`, no `parent_corp` field. The only grouping available is `sector_id`.

### 2.2 `sectors` Table (from `app/models/sector.py`)

```python
class Sector(Base):
    id: int (PK)
    name: str            # e.g. "반도체", "2차전지", "전기·전자"
    naver_code: str | None
    is_custom: bool      # ← Custom sectors are allowed
```

Sectors are largely Naver Finance industry groups. They do **not** correspond to conglomerate themes. LG씨엔에스 (IT 서비스), LG전자 (전기·전자), LG화학 (화학), LG에너지솔루션 (2차전지) all sit in different sectors today. Pure `sector_id` propagation will NOT capture conglomerate cascades.

### 2.3 Why a new `theme_groups` mapping is required (REQ-AI022-003)

Today's live evidence shows the cascade `LG씨엔에스 → LG전자 → LG이노텍 → 솔루스첨단소재` crosses 4 different `sector_id` values. To propagate signals across the group, we need an explicit many-to-many mapping that is independent of sector.

The lowest-risk approach is a new table (or a JSON list on Stock) that lets a stock belong to zero-or-more theme groups, where each theme group has a name and an optional `anchor_stock_id` (the bellwether like LG전자 for LG group).

Proposed minimal schema:

```python
class ThemeGroup(Base):
    __tablename__ = "theme_groups"
    id: int (PK)
    name: str (unique)              # e.g. "LG그룹", "삼성그룹", "2차전지 밸류체인"
    anchor_stock_id: int | None     # bellwether stock for the group
    description: str | None
    created_at: datetime

class StockThemeGroup(Base):
    __tablename__ = "stock_theme_groups"
    id: int (PK)
    stock_id: int (FK)
    theme_group_id: int (FK)
    weight: float                   # 1.0 for core member, 0.5 for tangential
    UniqueConstraint(stock_id, theme_group_id)
```

Alternative considered and rejected: storing theme groups in `Stock.keywords` (TEXT[]). Rejected because it offers no anchor-stock concept and no weight, and querying by theme requires array scans.

### 2.4 Initial Theme Group Seed Data (REQ-AI022-003)

Based on today's live cascade and historical patterns, the migration must seed at minimum:

| theme_group | anchor | members |
|---|---|---|
| LG그룹 | LG전자 (066570) | LG (003550), LG전자 (066570), LG이노텍 (011070), LG씨엔에스 (064400), LG화학 (051910), LG에너지솔루션 (373220), LG디스플레이 (034220), LG유플러스 (032640), 솔루스첨단소재 (336370) |
| 삼성그룹 | 삼성전자 (005930) | 삼성전자 (005930), 삼성SDI (006400), 삼성SDS / 삼성에스디에스 (018260), 삼성전기 (009150), 삼성바이오로직스 (207940), 삼성물산 (028260), 삼성생명 (032830) |
| 현대차그룹 | 현대차 (005380) | 현대차 (005380), 기아 (000270), 현대모비스 (012330), 현대오토에버 (307950), 현대글로비스 (086280), 현대건설 (000720) |
| SK그룹 | SK하이닉스 (000660) | SK하이닉스 (000660), SK텔레콤 (017670), SK이노베이션 (096770), SK스퀘어 (402340), SK (034730), SKC (011790) |

These are stored as Alembic data-only inserts and are extensible by manual SQL after the fact.

## 3. Volume Data Availability (for REQ-AI022-002)

### 3.1 No persistent `price_history` / `volume_history` table

A grep for `class PriceHistory|class StockHistory|daily_price|volume_history` returned no model file. Daily volume data is **not** persisted in PostgreSQL today. The system fetches it on-demand from Naver Finance via:

- `naver_finance.fetch_stock_price_history(stock_code, pages=5)` — async, returns `list[PriceRecord]` with `.volume` field
- `naver_finance.fetch_stock_price_history_sync(stock_code, pages=3)` — sync wrapper, used by `_get_volume_history` in surge_detector

### 3.2 PriceRecord schema (from `naver_finance.py` L249-251, L390, L636, L852, L1003)

```python
@dataclass
class PriceRecord:
    date: str
    close_price: int
    volume: int = 0
    prev_volume: int = 0
    ...
```

`fetch_stock_price_history_sync(code, pages=3)` returns approximately 30 trading days (pages * 10), which is sufficient for a 60-day rolling baseline only if pages is increased to `pages=6` (60 days = 6 pages of 10).

### 3.3 In-memory `_price_cache` in `naver_finance.py`

The module maintains a global `_price_cache.data: dict[stock_code, list[PriceRecord]]` with a 1-hour TTL. The surge_detector volume_news_combo path already relies on this cache.

### 3.4 Implication for REQ-AI022-002

For REQ-AI022-002 (volume anomaly: today vs. 60-day average × 5):
- We MUST call `fetch_stock_price_history_sync(code, pages=6)` per evaluated stock to obtain 60+ days
- For 2,605 tracked stocks × 6 pages × ~500ms = unacceptable latency in one batch
- Mitigation: limit REQ-AI022-002 to a candidate pool — stocks that today (`PriceRecord[0]`) show price change ≥ +3% AND have not been signaled in the past 90 days (dormancy filter from the requirement)
- Realistic batch size: ~100-200 stocks per day, ~10-30 seconds total

REQ-AI022-002 must run AFTER the main surge_detector pass to avoid blocking the existing pipeline.

## 4. Existing Theme Cluster Detection Mechanism

### 4.1 `detect_theme_news_cluster()` (surge_detector.py L174-386)

This function is the source of `theme_cluster_score`. It does NOT use the `theme_groups` table at all today; it uses `cfg.sector_theme_map: dict[theme_keyword, list[sector_name]]` to map news themes (e.g. "2차전지") to Naver sector names. The output is per-stock based on the stock's `sector_id`.

### 4.2 Where the propagation gap is today

When LG전자 receives a signal with `theme_cluster_score >= 0.80` (i.e. multiple LG-related news clustered with positive sentiment), the current code:
1. Generates a signal ONLY for stocks whose `sector_id` is in `theme_to_sectors[theme]`.
2. Does NOT consult conglomerate group membership.
3. So LG씨엔에스 (sector_id = IT 서비스) and 현대오토에버 (sector_id = IT 서비스) do not receive propagation even though their anchor stocks are surging.

### 4.3 Required hook for REQ-AI022-001

The propagation step is best done AFTER `gather_surge_candidates` returns and BEFORE persistence, in a new `propagate_theme_group_signals(db, qualified_candidates, config)` function inside surge_detector. The function:
1. Filters `qualified_candidates` to those with `theme_cluster_score >= 0.80`.
2. For each, looks up the candidate's `ThemeGroup` memberships via `StockThemeGroup`.
3. For each peer stock in the same theme group, checks if a signal exists today (`FundSignal.created_at >= today_start AND stock_id = peer_id`). If not, generates a new `signal_type="theme_propagation"` row with confidence `propagation_base_score` (default 0.25), `paper_executed=False`, and metadata recording source.

## 5. Surge Trading Consumer Behavior — Compatibility Notes

### 5.1 `get_today_signals` filter (SPEC-AI-013, modified by SPEC-AI-021)

```python
def get_today_signals(db, min_probability: Decimal):
    # Queries FundSignal WHERE signal_type='surge_candidate' AND created_at >= today
    # ...
```

The query filters by `signal_type='surge_candidate'`. SPEC-AI-022 new signals have `signal_type='theme_propagation'` or `signal_type='volume_anomaly'` — so they are **invisible to the buy pipeline by construction**. No SQL change is needed in `get_today_signals` to maintain "paper_executed=False excluded from execution" guarantee.

### 5.2 `paper_executed` semantics

Today's invariant: `paper_executed=True` means the 09:05 batch evaluated the signal and either bought or rejected. For SPEC-AI-022 new signals, `paper_executed=False` is the permanent state because they are never evaluated by the batch (different signal_type).

### 5.3 Routers affected

- `app/routers/surge_trading.py` (prefix `/api/surge-trading`) — REQ-AI022-004 adds `GET /coverage` here.
- `app/routers/fund_manager.py` already filters by `signal_type` via Query parameter (L251, L406, L422). It will naturally accept the new signal_type values without code change — but UI should be informed (out of scope, see Exclusions).

## 6. Database Migration Strategy

### 6.1 Current Alembic state

Latest known migration: `036_spec_ai_004_disclosure_impact.py` (down_revision=035). No surge-related schema migration has been applied since.

### 6.2 New migration for SPEC-AI-022

A single new migration `037_spec_ai_022_theme_groups.py` (down_revision=036) is sufficient:

```python
def upgrade():
    # 1. Create theme_groups table
    # 2. Create stock_theme_groups join table with unique (stock_id, theme_group_id)
    # 3. Seed initial groups (LG, 삼성, 현대차, SK) via op.bulk_insert
    # 4. Seed initial stock memberships (NULL-safe — INSERT ... WHERE EXISTS)
    pass

def downgrade():
    # Drop stock_theme_groups, then theme_groups
    pass
```

### 6.3 No new column on `fund_signals`

The existing columns (`signal_type`, `confidence`, `surge_metadata` TEXT, `paper_executed`) are sufficient for both new signal types. No `ALTER TABLE fund_signals` needed.

## 7. Coverage Dashboard (REQ-AI022-004) Data Sources

The `GET /api/surge-trading/coverage` endpoint must return:

| Field | Source |
|---|---|
| `total_stocks_tracked` | `SELECT COUNT(*) FROM stocks` |
| `signals_generated_today` | `SELECT COUNT(*) FROM fund_signals WHERE signal_type='surge_candidate' AND created_at >= today_kst_start` |
| `coverage_pct` | computed: `signals_generated_today / total_stocks_tracked * 100` |
| `top_missed` | For stocks with today's price change ≥ +15% (configurable threshold), JOIN with fund_signals filtered to today's surge_candidate; LEFT JOIN to detect missing. Requires per-stock price fetch, capped at top 30 by change_pct. |
| `theme_propagation_triggered` | `SELECT COUNT(*) FROM fund_signals WHERE signal_type='theme_propagation' AND created_at >= today_kst_start` |
| `volume_anomaly_triggered` | (added for completeness) `SELECT COUNT(*) FROM fund_signals WHERE signal_type='volume_anomaly' AND created_at >= today_kst_start` |

`top_missed` is the most expensive — it requires fetching current price/change for stocks not in today's signals. Mitigation: limit to stocks with `market_cap >= 1000억` (top ~600 stocks) and cache result with 5-minute TTL. If even this is too slow, defer `top_missed` calculation to a background job and surface via a separate `/api/surge-trading/coverage/missed` endpoint.

## 8. Test Strategy Summary

- New module `backend/tests/test_theme_propagation.py` — REQ-AI022-001 with mocked `ThemeGroup`/`StockThemeGroup` fixtures and synthetic `qualified_candidates`.
- New module `backend/tests/test_volume_anomaly.py` — REQ-AI022-002 with mocked `_get_volume_history` provider returning a 60-day series.
- New module `backend/tests/test_theme_groups_migration.py` — assertions on Alembic upgrade/downgrade reversibility (using SQLite in-memory).
- New module `backend/tests/test_coverage_endpoint.py` — REQ-AI022-004 with mocked DB and price fetch.
- Reuse helpers from `tests/test_surge_trading.py` and `tests/test_surge_detector.py`.

Target coverage: 90%+ on the new files (propagator, anomaly detector, ThemeGroup models, coverage endpoint), 85%+ on modified files (surge_detector.py).

## 9. Open Questions Surfaced During Research

These are flagged for review during the Plan annotation cycle and have been resolved within this SPEC by adopting the listed default:

1. Should `theme_propagation` signals contribute to `surge_metadata.surge_basis` of the source candidate? → **Default: No.** They are emitted as separate FundSignal rows; the source candidate is untouched.
2. Should `volume_anomaly` signals be visible in the fund_manager UI? → **Default: Yes, but read-only.** They appear in `/api/fund/signals` lists because the schema already supports arbitrary `signal_type` filter. UI label changes are out of scope.
3. What `confidence` semantic does `volume_anomaly` carry? → **Default:** Linear ramp `min(volume_ratio / 10, 0.40)`. A 5× volume gives `confidence=0.50` raw, capped at `0.40` per the requirement. A 10× volume hits the cap.
4. Should propagation respect the `recent_surge_penalty` (5-day return > 20%)? → **Default: Yes.** Propagated signals inherit the penalty multiplier from the source candidate's `price_5d_trend` if the peer's own trend is unknown. If the peer has its own `price_5d_trend > 20%`, the propagation is suppressed (no signal generated).
5. How many theme groups can a stock belong to? → **Default: Unlimited.** A stock may appear in multiple groups (e.g. 삼성SDI in 삼성그룹 and 2차전지 밸류체인). Propagation runs once per (source, group) pair; if multiple sources in different groups target the same peer, the highest confidence wins (no duplicate row).
