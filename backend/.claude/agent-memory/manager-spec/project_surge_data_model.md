---
name: project-surge-data-model
description: Non-obvious facts about the surge-trading data model that SPEC writers keep getting wrong (field names, derived metrics, reuse points)
metadata:
  type: project
---

Facts about the news-hive surge-trading subsystem that are easy to misstate in SPECs. Verify against current code before relying on these — they were true as of 2026-06-02.

- **Ensemble weight field name is `legacy_detectors`, not `legacy`.** `EnsembleWeightsConfig` (`backend/app/surge_config/surge_settings.py`) has exactly four fields: `theme_cluster`, `volume_news_combo`, `disclosure_pattern`, `legacy_detectors`. User-facing prose often abbreviates it to `legacy`. SPEC suggested-weight keys must use the canonical name.

- **`SurgeTrade` has NO `profit` or `return_pct` column.** Win/return are derived: closed trade = `exit_date IS NOT NULL` (= `is_open False`); win = `exit_reason == "take_profit"` OR `exit_price > entry_price`; return = `(exit_price - entry_price) / entry_price`. `exit_reason` values: `stop_loss` / `take_profit` / `max_holding_period` / `manual`. Do not propose adding denormalized P&L columns in SPECs.

- **Detector attribution goes through `FundSignal.surge_metadata`.** `SurgeTrade.signal_id` (nullable FK → `fund_signals.id`) joins to `FundSignal`, whose `surge_metadata` (Text/JSON) holds `surge_basis` (list of detector names). Observed names: `theme_cluster`, `volume_news_combo`, `disclosure_pattern`, `immediate_disclosure`, `sector_momentum`, `carry_over`.

- **Reuse `_extract_combo_key` instead of reinventing combo extraction.** `backend/app/services/surge_backtest.py` already extracts a sorted detector-combination key from `surge_metadata` (`"+".join(sorted(basis))`, returns `"unknown"` on missing/parse-fail). New analysis SPECs should reuse this, not re-parse surge_metadata.

- **Surge-trading router prefix is `/api/surge-trading`** (`backend/app/routers/surge_trading.py` line 15), admin auth helper is `_verify_admin_token` (from `app.routers.auth`).

Related: [[project-surge-spec-conventions]]