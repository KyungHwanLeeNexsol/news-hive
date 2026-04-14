# SPEC-AI-010 Compact

## Requirements

- REQ-SENTIMENT-001: WHEN analyze_stock() called AND StockForumHourly data available THEN system SHALL call `_gather_forum_sentiment()`
- REQ-SENTIMENT-002: System SHALL include forum sentiment under header "## 1-2. 종토방 감성 (역발상 지표)" separate from news sentiment
- REQ-SENTIMENT-003: WHEN overheating_alert is True THEN system SHALL include "※ 종토방이 과열 상태입니다. 개인투자자 쏠림에 의한 고점 가능성을 고려하세요"
- REQ-SENTIMENT-004: WHEN volume_surge is True THEN system SHALL include "※ 종토방 댓글 급증 감지: 시장 관심도 급등. 공시/뉴스와 교차 확인 필요"
- REQ-SENTIMENT-005: System SHALL include consensus result under "## 9-1. 증권사 컨센서스" with avg_target_price, premium_pct, consensus_signal, buy/hold/sell ratios
- REQ-SENTIMENT-006: WHEN forum data unavailable THEN system SHALL skip forum section gracefully without exception
- REQ-SENTIMENT-007: WHEN consensus_signal="strong_buy" THEN positive note; WHEN "caution" THEN warning note
- REQ-SENTIMENT-008: System SHALL NOT use forum sentiment as standalone buy/sell signal; MUST be supporting context only

## Delta Markers

- [EXISTING] `_gather_sentiment_trend()` — unchanged
- [EXISTING] `_gather_securities_reports()` — unchanged
- [EXISTING] Prompt section 1-1 and 9 — unchanged
- [MODIFY] `analyze_stock()` — add 2 function calls + 2 prompt sections
- [NEW-FROM-DEP] `_gather_forum_sentiment()` call (impl: SPEC-AI-008)
- [NEW-FROM-DEP] `_gather_securities_consensus()` call (impl: SPEC-AI-009)

## MX Tags

- `analyze_stock()`: @MX:ANCHOR (high fan_in: scheduler, briefing, API)
- New prompt sections 1-2 and 9-1: @MX:NOTE (document weight/significance)
- Graceful fallback try-except blocks: @MX:NOTE

## Given-When-Then

1. Given SPEC-AI-008 deployed + data, When analyze_stock(), Then prompt contains "1-2. 종토방 감성"
2. Given overheating_alert=True, When analyze_stock(), Then prompt contains "종토방이 과열 상태"
3. Given StockForumHourly missing, When analyze_stock(), Then no exception, no forum section
4. Given consensus_signal="strong_buy", When analyze_stock(), Then section 9-1 shows positive note + avg_target_price + premium_pct
5. Given volume_surge=True AND overheating_alert=False, When analyze_stock(), Then surge notice but NO overheating warning
6. Given all sources available, When analyze_stock() 10x, Then avg exec time increase < 500ms vs baseline

## Exclusions

- No modification of existing news sentiment logic
- No new DB tables (consumes SPEC-AI-008/009 outputs only)
- No FundSignal schema changes
- No frontend/API changes
- No promoting forum sentiment to standalone signal
- No externalized config for weights (hardcoded constants OK)

## Dependencies

- SPEC-AI-008: StockForumHourly model + `_gather_forum_sentiment()` required
- SPEC-AI-009: `_gather_securities_consensus()` required
- Both must support graceful fallback if not deployed
