---
engine: _TBD_
orm: _TBD_
last_synced_at: _TBD_
manifest_hash: _TBD_
---

# Database Schema

_TBD — Run `/moai db init` to configure the database engine and ORM, then edit this file or let
the auto-sync hook populate it from your migration files._

---

## Tables

<!-- For NoSQL databases, replace this section with ## Collections -->

| Table | Description |
|-------|-------------|
| `surge_gate_drop_observations` | SPEC-AI-115 append-only observation table for candidates dropped by detection/evaluation gates and relaxed gate shadow profiles. |
| `surge_missing_trigger_shadow_candidates` | SPEC-AI-116 shadow-only candidates produced by contract/M&A, volume spike, and low-liquidity detector families. |

<!--
Example:
| users | Core user account table — authentication identity |
| posts | User-authored content items |
| comments | Threaded comment entries linked to posts |
-->

---

## Relationships

<!-- Cardinality notation: 1:1, 1:N, N:M -->

| From | To | Cardinality | FK Column | Notes |
|------|----|-------------|-----------|-------|
| _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

<!--
Example:
| users | posts    | 1:N | posts.user_id    | A user owns many posts |
| posts | comments | 1:N | comments.post_id | A post has many comments |
| users | roles    | N:M | user_roles table | Via junction table |
-->

---

## Indexes

<!-- List standalone and composite indexes -->

| Table | Columns | Type | Purpose |
|-------|---------|------|---------|
| `surge_gate_drop_observations` | `trading_date` | INDEX | Query daily gate/drop attribution reports. |
| `surge_gate_drop_observations` | `stock_code` | INDEX | Inspect a single stock's gate/drop history. |
| `surge_gate_drop_observations` | `gate_name` | INDEX | Aggregate dropped candidates by gate. |
| `surge_gate_drop_observations` | `shadow_profile` | INDEX | Compare relaxed gate shadow profiles. |
| `surge_gate_drop_observations` | `observed_at` | INDEX | Operational recency filtering. |
| `surge_missing_trigger_shadow_candidates` | `(trading_date, detector_family)` | COMPOSITE INDEX | Per-family shadow readiness reports. |

<!--
Example:
| users | email          | UNIQUE  | Enforce unique emails for login |
| posts | (user_id, created_at) | COMPOSITE | Paginated user post queries |
| posts | title          | GIN/FTS | Full-text search on post titles |
-->

---

## Constraints

<!-- UNIQUE, CHECK, EXCLUSION, NOT NULL (non-obvious cases) -->

| Table | Constraint | Type | Definition |
|-------|-----------|------|-----------|
| `surge_missing_trigger_shadow_candidates` | primary key | PRIMARY KEY | `(trading_date, stock_code, detector_family, horizon)` |

<!--
Example:
| users | users_email_unique | UNIQUE | email must be unique |
| posts | posts_status_check | CHECK  | status IN ('draft', 'published', 'archived') |
| bookings | no_overlap        | EXCLUSION | daterange(start_at, end_at) with &&  |
-->
