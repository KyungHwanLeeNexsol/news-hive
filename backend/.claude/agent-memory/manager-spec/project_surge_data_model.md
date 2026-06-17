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

- **`early_entry_check()` filters strictly on one signal_type.** `preday_signal_service.early_entry_check()` (the 09:05 KST `surge_preday_early_entry` consumer) queries `FundSignal.signal_type == "preday_disclosure"` only (PREDAY_SIGNAL_TYPE constant). Any new SPEC that introduces a new signal_type and claims it will be "picked up by the existing preday/early-entry mechanism" is WRONG unless it ALSO extends this filter. Verified 2026-06-17 for SPEC-AI-051 gap_up_runners.

- **`score_disclosure_impact()` has 4 early-return paths.** `disclosure_impact_scorer.py:138-182` returns at: routine-governance cap (`5.0`, line 154), contract-ratio (line 163), 실적변동 % (line 171), or `_BASE_IMPACT_BY_TYPE` default (line 176-182). Any new post-processing (multiplier, bonus) must be placed carefully — the routine-governance `5.0` return happens FIRST and must stay exempt from later adjustments.

Related: [[project-surge-spec-conventions]]