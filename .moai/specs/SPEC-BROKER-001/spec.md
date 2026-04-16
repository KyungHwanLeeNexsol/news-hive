---
id: SPEC-BROKER-001
version: 1.0.0
status: Planned
created: 2026-04-15
updated: 2026-04-15
author: Nexsol
priority: High
issue_number: null
---

# SPEC-BROKER-001: 한국투자증권 KIS OpenAPI 실계좌 자동매매 통합

## HISTORY

- **2026-04-15** (v1.0.0) — 초기 SPEC 작성 (Nexsol)
  - 3개 페이퍼 트레이딩 모델(AI 펀드매니저, KS200 스윙, VIP 추종)의 실계좌 연동 요구사항 정의
  - 활성화 게이트, 리스크 컨트롤, KIS API 클라이언트, 주문 로그, 알림 요구사항 수립
  - EARS 포맷 요구사항 및 Given-When-Then 수용 기준 작성

---

## 1. Overview (개요)

### 1.1 목적

NewsHive의 3개 페이퍼 트레이딩 포트폴리오 모델(AI 펀드매니저, KS200 스윙, VIP 추종)이 수익성 검증(라이브 트래킹 90일 이상, 승률 60% 이상, MDD 15% 이내, Sharpe 1.0 이상)을 통과한 이후, **한국투자증권(KIS) OpenAPI**를 통해 실계좌 자동매매를 실행하는 브로커 통합 레이어를 구축한다.

### 1.2 배경 (Context)

- **현재 상태**: 3개 모델은 모두 페이퍼 트레이딩 상태로, 시그널 생성 및 가상 포트폴리오 추적만 수행
- **목표 상태**: 검증된 모델의 시그널을 실계좌 주문으로 실행, 단 엄격한 리스크 게이트 하에서만 활성화
- **핵심 위험**: 실자금 손실 가능성이 높기 때문에 다층 안전장치(활성화 게이트, 일일 손실 한도, 비상 정지, 중복 주문 방지)가 필수

### 1.3 Scope

**IN SCOPE:**
- KIS OpenAPI OAuth 2.0 인증 및 토큰 관리
- 모의투자(mock) 및 실전투자(real) 환경 전환
- 국내주식 현금 주문(매수/매도) 실행
- 잔고 조회 및 포지션 동기화
- 신호 활성화 게이트 시스템
- 리스크 컨트롤 레이어(한도, 중복 방지, 비상 정지)
- 주문 로그 및 감사 추적
- 주문 체결 알림(푸시/카카오)
- 관리자 UI를 위한 API 엔드포인트

**OUT OF SCOPE (Exclusions - What NOT to Build):**
- 해외주식/선물/옵션 거래 (국내 현금 주문만 지원)
- WebSocket 실시간 체결 스트리밍 (Phase 2로 연기, 초기 구현은 REST 폴링)
- 자동 손절/익절 로직 (모델의 매도 시그널에만 의존)
- 다중 증권사 지원 (KIS 단일 증권사만 지원, 추상화 레이어는 준비하되 다른 브로커 구현은 제외)
- 파생상품 위험 관리 (마진, 증거금 로직)
- 세금/수수료 자동 계산 및 보고서
- 사용자 계정 별 개별 실계좌 연결 (초기에는 관리자 단일 계좌만 지원)
- 알고리즘 매매 규제 관련 법적 검토 문서 작성 (별도 SPEC에서 다룸)

### 1.4 Success Metrics

- 모의투자(mock) 환경에서 30일간 0건의 주문 오류 발생
- 실전 환경 활성화 이후 첫 주문 체결 성공률 99% 이상
- 비상 정지(kill switch) 호출 후 5초 이내 모든 활성 주문 차단
- 리스크 게이트 위반 시도에 대해 100% 차단 및 로그 기록

---

## 2. Functional Requirements (EARS Format)

### 2.1 신호 활성화 게이트 (Activation Gate)

**REQ-BROKER-001 (State-Driven)**
**While** a trading model has accumulated less than 90 days of live paper trading data, the system **shall** prevent activation of real account trading for that model.

**REQ-BROKER-002 (State-Driven)**
**While** a trading model's `win_rate < 60%` OR `max_drawdown > 15%` OR `sharpe_ratio < 1.0`, the system **shall** block real account activation and display the failing metric to the admin.

**REQ-BROKER-003 (Ubiquitous)**
The system **shall** allow each model (`ai_fund`, `ks200_swing`, `vip_follow`) to be activated and deactivated independently for real account trading.

**REQ-BROKER-004 (Event-Driven)**
**When** an admin invokes manual override via the admin API with a valid override reason, the system **shall** bypass the activation gate requirements and log the override event with timestamp, admin ID, and reason.

**REQ-BROKER-005 (Ubiquitous)**
The system **shall** re-evaluate activation gate metrics daily at 08:30 KST and auto-deactivate any model that falls below the thresholds.

### 2.2 주문 실행 (Order Execution)

**REQ-BROKER-010 (Event-Driven)**
**When** a paper trading model generates a BUY signal AND the corresponding model is activated for real trading AND the signal passes all risk gates, the system **shall** submit a cash buy order to KIS OpenAPI.

**REQ-BROKER-011 (Event-Driven)**
**When** a paper trading model generates a SELL signal for a stock that has an open real position, the system **shall** submit a cash sell order to KIS OpenAPI.

**REQ-BROKER-012 (Optional)**
**Where** the `order_type` configuration is `market`, the system **shall** submit market orders (KIS `ORD_DVSN=01`). **Where** it is `limit`, the system **shall** submit limit orders using the current ask/bid price (KIS `ORD_DVSN=00`).

**REQ-BROKER-013 (State-Driven)**
**While** the Korean stock market is closed (outside 09:00~15:30 KST on trading days), the system **shall** reject order submissions and log the attempt.

**REQ-BROKER-014 (Unwanted Behavior)**
**If** a signal arrives for a stock that already has an open position in the real account, **then** the system **shall not** submit a duplicate buy order and **shall** log the duplicate prevention event.

### 2.3 리스크 컨트롤 (Risk Controls)

**REQ-BROKER-020 (State-Driven)**
**While** processing a buy order, the system **shall** verify that `order_amount <= portfolio_value × max_per_trade_pct` (default 10%).

**REQ-BROKER-021 (State-Driven)**
**While** the daily realized + unrealized P&L is below `-portfolio_value × daily_max_loss_pct` (default -3%), the system **shall** reject all new buy orders for the remainder of the trading day.

**REQ-BROKER-022 (Event-Driven)**
**When** an admin invokes the emergency stop (kill switch) API, the system **shall** within 5 seconds: (a) disable all model activations, (b) cancel all pending KIS orders via KIS cancel API, and (c) broadcast a notification to all admins.

**REQ-BROKER-023 (Ubiquitous)**
The system **shall** persist the emergency stop state until an admin explicitly resets it via the admin API.

**REQ-BROKER-024 (Unwanted Behavior)**
**If** the KIS API returns an error indicating insufficient balance or margin, **then** the system **shall** mark the model as temporarily suspended and notify admins.

### 2.4 KIS API 클라이언트 (KIS API Client)

**REQ-BROKER-030 (Ubiquitous)**
The system **shall** manage the OAuth 2.0 access token lifecycle: request a new token when absent, refresh when the current token has less than 1 hour remaining TTL, and persist tokens in an encrypted storage.

**REQ-BROKER-031 (Ubiquitous)**
The system **shall** enforce KIS rate limits (20 requests per second per endpoint) using a token bucket rate limiter, and queue excess requests up to 100ms.

**REQ-BROKER-032 (Ubiquitous)**
The system **shall** store `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NUMBER`, and `KIS_ACCOUNT_PRODUCT_CODE` in environment variables or encrypted database columns only — **shall not** log or serialize credentials in any form.

**REQ-BROKER-033 (Event-Driven)**
**When** the configuration flag `kis_environment` is set to `mock`, the system **shall** route all requests to `openapivts.koreainvestment.com:29443` and use mock `tr_id` values (`VTTC0802U` for buy, `VTTC0801U` for sell). **When** set to `real`, the system **shall** route to `openapi.koreainvestment.com:9443` with real `tr_id` values (`TTTC0802U`, `TTTC0801U`).

**REQ-BROKER-034 (Ubiquitous)**
The system **shall** retry failed KIS API calls with exponential backoff (initial 1s, max 3 retries), treating only transient errors (5xx, network timeout) as retryable.

### 2.5 주문 로그 (Order Logging)

**REQ-BROKER-040 (Ubiquitous)**
The system **shall** persist every order attempt (successful and failed) to the `broker_orders` table with the full audit trail.

**REQ-BROKER-041 (Ubiquitous)**
Each `broker_orders` row **shall** contain a foreign key reference to the paper trading signal (`signal_id`, `signal_source`) that triggered the order.

**REQ-BROKER-042 (Ubiquitous)**
The system **shall** log every KIS API request/response pair (excluding credentials) with timestamp, endpoint, request hash, response code, and correlation ID for debugging.

### 2.6 알림 (Notifications)

**REQ-BROKER-050 (Event-Driven)**
**When** a KIS order is filled (status transitions to `filled` or `partially_filled`), the system **shall** send a push notification and a Kakao message to configured admin recipients containing: stock code, quantity, fill price, and model source.

**REQ-BROKER-051 (Event-Driven)**
**When** an order fails, a risk gate triggers, or a model is auto-deactivated, the system **shall** send an alert notification with failure reason and next-step guidance.

**REQ-BROKER-052 (Ubiquitous)**
The system **shall** send a daily summary notification at 16:00 KST comparing real account performance vs paper model performance (P&L delta, trade count, slippage).

---

## 3. Non-Functional Requirements

### 3.1 Security

**REQ-BROKER-060 (Unwanted Behavior)**
**If** any code path attempts to write `KIS_APP_SECRET` or `access_token` to logs, stdout, or error messages, **then** the logging filter **shall** redact the value to `***REDACTED***`.

**REQ-BROKER-061 (Ubiquitous)**
Credentials stored in the database **shall** be encrypted at rest using AES-256-GCM with the master key sourced from the OS environment variable `BROKER_ENCRYPTION_KEY`.

### 3.2 Reliability

**REQ-BROKER-070 (Ubiquitous)**
Order submission **shall** be idempotent: each order carries a client-generated `idempotency_key` (UUID v4); duplicate submissions within 60 seconds of the same key **shall** return the prior result without re-submission.

**REQ-BROKER-071 (Ubiquitous)**
The system **shall** reconcile real account positions with the database every 5 minutes during market hours and generate a reconciliation report on divergence.

### 3.3 Observability

**REQ-BROKER-080 (Ubiquitous)**
The system **shall** emit structured logs (JSON) for every KIS API call including: `correlation_id`, `endpoint`, `tr_id`, `response_code`, `latency_ms`.

**REQ-BROKER-081 (Ubiquitous)**
The system **shall** expose Prometheus-style metrics on `/metrics` endpoint: `broker_order_total{status,model}`, `broker_api_latency_seconds`, `broker_risk_gate_triggered_total{reason}`.

---

## 4. Data Models

### 4.1 `broker_connections` Table

Stores per-admin broker account connection configuration and credentials.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGSERIAL PK | No | Internal ID |
| `admin_id` | VARCHAR(64) | No | Owning admin identifier |
| `broker_name` | VARCHAR(32) | No | Broker name; initially only `kis` |
| `environment` | VARCHAR(16) | No | `mock` or `real` |
| `account_number` | VARCHAR(32) | No | KIS CANO (계좌번호 앞 8자리) |
| `account_product_code` | VARCHAR(8) | No | KIS ACNT_PRDT_CD (뒤 2자리) |
| `app_key_encrypted` | BYTEA | No | AES-256-GCM encrypted KIS app key |
| `app_secret_encrypted` | BYTEA | No | AES-256-GCM encrypted KIS app secret |
| `access_token_encrypted` | BYTEA | Yes | Current OAuth token (encrypted) |
| `access_token_expires_at` | TIMESTAMPTZ | Yes | Token expiry |
| `is_enabled` | BOOLEAN | No | Master enable flag |
| `emergency_stopped` | BOOLEAN | No | Kill switch state (default false) |
| `emergency_stopped_at` | TIMESTAMPTZ | Yes | Timestamp of last emergency stop |
| `created_at` | TIMESTAMPTZ | No | — |
| `updated_at` | TIMESTAMPTZ | No | — |

Indexes: `UNIQUE(admin_id, broker_name, environment)`, `INDEX(is_enabled, emergency_stopped)`.

### 4.2 `broker_model_activations` Table

Per-model activation configuration linked to a broker connection.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGSERIAL PK | No | — |
| `connection_id` | BIGINT FK | No | FK → `broker_connections.id` |
| `model_name` | VARCHAR(32) | No | `ai_fund`, `ks200_swing`, or `vip_follow` |
| `is_activated` | BOOLEAN | No | Default false |
| `activated_at` | TIMESTAMPTZ | Yes | — |
| `max_per_trade_pct` | NUMERIC(5,4) | No | Default 0.10 |
| `daily_max_loss_pct` | NUMERIC(5,4) | No | Default 0.03 |
| `order_type` | VARCHAR(16) | No | `market` or `limit`, default `market` |
| `manual_override_enabled` | BOOLEAN | No | Default false |
| `manual_override_reason` | TEXT | Yes | Required if override enabled |
| `last_gate_check_at` | TIMESTAMPTZ | Yes | — |
| `last_gate_result` | JSONB | Yes | Stores win_rate, MDD, Sharpe snapshot |

Indexes: `UNIQUE(connection_id, model_name)`.

### 4.3 `broker_orders` Table

Full audit log of every order attempt.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | BIGSERIAL PK | No | — |
| `connection_id` | BIGINT FK | No | — |
| `idempotency_key` | UUID | No | Client-generated; unique |
| `model_name` | VARCHAR(32) | No | Source model |
| `signal_source` | VARCHAR(64) | No | E.g., `fund_signal`, `ks200_signal`, `vip_follow` |
| `signal_id` | BIGINT | Yes | FK to the corresponding signal table row |
| `stock_code` | VARCHAR(8) | No | Korean stock code (6 digits) |
| `side` | VARCHAR(8) | No | `buy` or `sell` |
| `quantity` | INTEGER | No | — |
| `order_type` | VARCHAR(16) | No | `market` or `limit` |
| `limit_price` | NUMERIC(12,2) | Yes | Required if `order_type=limit` |
| `status` | VARCHAR(24) | No | `pending`, `submitted`, `filled`, `partially_filled`, `cancelled`, `rejected`, `failed` |
| `kis_order_no` | VARCHAR(32) | Yes | KIS 주문번호 (ODNO) |
| `kis_tr_id` | VARCHAR(16) | Yes | The tr_id used |
| `filled_quantity` | INTEGER | No | Default 0 |
| `filled_price_avg` | NUMERIC(12,2) | Yes | Volume-weighted average |
| `risk_gate_result` | JSONB | No | Pre-submit gate evaluation snapshot |
| `kis_response` | JSONB | Yes | Raw KIS response (credentials stripped) |
| `error_message` | TEXT | Yes | Failure reason |
| `correlation_id` | UUID | No | For log correlation |
| `submitted_at` | TIMESTAMPTZ | Yes | — |
| `filled_at` | TIMESTAMPTZ | Yes | — |
| `created_at` | TIMESTAMPTZ | No | — |
| `updated_at` | TIMESTAMPTZ | No | — |

Indexes: `UNIQUE(idempotency_key)`, `INDEX(connection_id, status, created_at DESC)`, `INDEX(signal_source, signal_id)`.

### 4.4 `broker_api_logs` Table

KIS API request/response audit log (credentials redacted).

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PK | — |
| `correlation_id` | UUID | Links to `broker_orders.correlation_id` |
| `endpoint` | VARCHAR(128) | — |
| `tr_id` | VARCHAR(16) | — |
| `request_hash` | CHAR(64) | SHA-256 of redacted request body |
| `response_code` | VARCHAR(8) | KIS rt_cd |
| `response_message` | TEXT | KIS msg1 |
| `latency_ms` | INTEGER | — |
| `created_at` | TIMESTAMPTZ | — |

Retention: 90 days rolling.

---

## 5. API Endpoints Design

All endpoints require admin authentication (existing in-memory admin token). Base path: `/broker/v1`.

### 5.1 Connection Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/broker/v1/connections` | Create broker connection (encrypt credentials on save) |
| `GET` | `/broker/v1/connections` | List admin's connections (credentials redacted) |
| `PATCH` | `/broker/v1/connections/{id}` | Update environment / enable flag |
| `POST` | `/broker/v1/connections/{id}/test` | Test OAuth + balance query |

### 5.2 Model Activation

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/broker/v1/activations` | List all model activations with gate metrics |
| `POST` | `/broker/v1/activations/{model}/activate` | Activate model (enforces gate unless override) |
| `POST` | `/broker/v1/activations/{model}/deactivate` | Deactivate model |
| `PATCH` | `/broker/v1/activations/{model}/config` | Update risk params (`max_per_trade_pct`, `daily_max_loss_pct`, `order_type`) |

### 5.3 Orders

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/broker/v1/orders` | List orders (pagination, filter by model/status/date) |
| `GET` | `/broker/v1/orders/{id}` | Order detail incl. KIS raw response |
| `POST` | `/broker/v1/orders/{id}/cancel` | Request cancellation via KIS cancel API |

### 5.4 Risk / Emergency

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/broker/v1/emergency-stop` | Activate kill switch (disables all models, cancels pending orders) |
| `POST` | `/broker/v1/emergency-stop/reset` | Reset emergency state |
| `GET` | `/broker/v1/risk/status` | Current risk state (daily P&L, active positions, gate snapshot) |

### 5.5 Reconciliation & Performance

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/broker/v1/reconcile` | Trigger manual reconciliation; returns divergence report |
| `GET` | `/broker/v1/performance/daily` | Real vs paper model delta for given date range |

---

## 6. Security Considerations

### 6.1 Credential Storage

- **Environment variables** are the preferred storage for production credentials (loaded via Pydantic `BaseSettings`).
- **Database-stored credentials** (for multi-admin future support) MUST use AES-256-GCM with the key in `BROKER_ENCRYPTION_KEY` env var, never persisted alongside ciphertext.
- **Rotation**: App key/secret rotation procedure documented in runbook; token rotation is automatic via OAuth refresh.

### 6.2 Log Redaction

A global logging filter (`BrokerCredentialRedactionFilter`) intercepts log records matching patterns for app_key, app_secret, access_token, and replaces them with `***REDACTED***`. Applied to stdlib `logging`, Uvicorn access logs, and SQLAlchemy echo.

### 6.3 Access Control

- All `/broker/v1/*` endpoints require the existing admin authentication layer.
- Emergency stop endpoint additionally requires a recent (< 5 min) admin re-authentication token ("sudo mode") to prevent accidental CSRF-style triggers.
- Manual override activation requires a free-form `reason` field (min 20 chars) stored for audit.

### 6.4 Network Security

- All KIS API calls use TLS 1.2+ with certificate pinning (pin the KIS root CA).
- Outbound connections restricted by firewall to KIS domains only on the broker-processing worker.

### 6.5 Idempotency & Replay Protection

- Every order submission requires a fresh UUID v4 `idempotency_key`.
- Replay window: 60 seconds; duplicate keys within window return the stored prior result without re-submission.

### 6.6 Audit & Compliance

- Every credential view, activation toggle, risk param change, emergency stop, and manual override is recorded in an append-only `admin_audit_log` table (separate SPEC may later formalize this).
- Log retention: broker_orders永永 (영구), broker_api_logs 90일.

---

## 7. Implementation Phases

### Phase 1 — KIS Client Foundation (Priority: High)

**Deliverables:**
- `app/integrations/kis/client.py`: OAuth 2.0, rate limiter, retry logic, mock/real switching
- `app/integrations/kis/models.py`: Pydantic request/response models for order-cash, inquire-balance
- `app/integrations/kis/credential_store.py`: AES-256-GCM encrypt/decrypt helper
- `app/integrations/kis/logging_filter.py`: Credential redaction filter
- Unit tests against KIS mock environment (`openapivts.koreainvestment.com`)

**Exit criteria:** Successful OAuth + balance query + mock buy/sell order against KIS mock env.

### Phase 2 — Data Models & Migrations (Priority: High)

**Deliverables:**
- Alembic migration creating `broker_connections`, `broker_model_activations`, `broker_orders`, `broker_api_logs`
- SQLAlchemy ORM models with encryption hooks on credential columns
- Seed script for initial admin connection (mock env)

**Exit criteria:** All tables created, encryption roundtrip verified.

### Phase 3 — Risk Gate & Order Service (Priority: High)

**Deliverables:**
- `app/services/broker/activation_gate.py`: Evaluates win_rate/MDD/Sharpe per model
- `app/services/broker/risk_guard.py`: Pre-submit validation (market hours, daily loss, position size, duplicate)
- `app/services/broker/order_service.py`: Idempotent order submission, status tracking
- `app/services/broker/emergency_stop.py`: Kill switch implementation

**Exit criteria:** End-to-end dry-run against mock env with all risk gates wired.

### Phase 4 — Signal Integration (Priority: High)

**Deliverables:**
- Hook points in `fund_manager.py`, `ks200_signal_generator.py`, `vip_follow_service.py` that invoke `order_service` when activation is enabled
- Celery/APScheduler job for daily gate re-evaluation (08:30 KST)
- 5-minute reconciliation job

**Exit criteria:** Signal from each of 3 models produces correct mock order.

### Phase 5 — API & Admin UI Backend (Priority: Medium)

**Deliverables:**
- FastAPI routers for all endpoints in Section 5
- Next.js admin pages: connection setup, activation toggle, orders list, emergency stop
- Role-based access guard

**Exit criteria:** Admin can perform full lifecycle (connect → activate → view orders → emergency stop) via UI.

### Phase 6 — Notifications & Observability (Priority: Medium)

**Deliverables:**
- Push & Kakao notification integration for order fills, failures, auto-deactivation
- Daily summary report job (16:00 KST)
- Prometheus metrics exposition
- Grafana dashboard JSON

**Exit criteria:** All notification types verified, metrics visible on dashboard.

### Phase 7 — Mock Environment Soak Test (Priority: High)

**Deliverables:**
- 30-day soak run with all 3 models active against KIS mock env
- Automated divergence detection vs paper model
- Failure mode report

**Exit criteria:** Zero unresolved errors, < 1% slippage vs paper model.

### Phase 8 — Production Rollout (Priority: High, blocked by Phase 7)

**Deliverables:**
- Switch `kis_environment` to `real` per-model gradually (canary: smallest allocation model first)
- On-call runbook
- Rollback procedure documented and rehearsed

**Exit criteria:** First real trade executed successfully, reconciliation clean.

---

## 8. Dependencies

- **Prerequisite SPECs**: SPEC-AI-003 (fund_manager signals), SPEC-AI-004 (disclosure impact), SPEC-VIP-001, SPEC-FOLLOW-001, SPEC-FOLLOW-002
- **External**: KIS OpenAPI app registration (app_key/app_secret from 한국투자증권 포털), KIS 계좌 개설, Kakao Business API key (알림)
- **Internal**: Existing Push notification system, admin auth, PostgreSQL
- **Config additions**: `.env` vars `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NUMBER`, `KIS_ACCOUNT_PRODUCT_CODE`, `BROKER_ENCRYPTION_KEY`, `KIS_ENVIRONMENT`

---

## 9. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| KIS API downtime during market hours | High | Circuit breaker + admin alert; graceful degradation to read-only |
| Activation gate metrics manipulation | High | Metrics computed server-side from immutable signal history |
| Credential leak via logs | Critical | Log filter + code review + periodic secret scan |
| Duplicate orders from retry storms | Critical | Idempotency key + 60s replay window |
| Regulatory non-compliance (algorithmic trading) | High | Out of scope for this SPEC; separate legal review SPEC required before Phase 8 |
| Token expiry mid-order | Medium | Pre-emptive refresh at 1h TTL; retry with fresh token on 401 |
| Market hour edge cases (holidays, half-days) | Medium | Use KIS-provided market calendar API; fallback to hard-coded schedule |

---

## 10. Acceptance Reference

Detailed acceptance scenarios (Given-When-Then) are defined in `acceptance.md`. Implementation plan with milestones is in `plan.md`.

---

## 11. Expert Consultation Recommendations

This SPEC spans multiple high-risk domains and benefits from specialist review before implementation:

- **expert-backend**: OAuth client design, FastAPI service layering, SQLAlchemy encryption hooks
- **expert-security**: Credential storage, log redaction, replay protection, TLS/cert pinning
- **expert-devops**: Secret management, monitoring & alerting, rollout strategy
- **expert-testing**: Mock environment integration tests, soak test framework

Recommend consulting **expert-security** first due to the criticality of credential handling and real-money implications.
