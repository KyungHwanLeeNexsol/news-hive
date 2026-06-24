---
id: SPEC-AI-064
version: "1.0.0"
status: completed
created: "2026-06-24"
updated: "2026-06-24"
author: Nexsol
priority: P1
issue_number: 0
---

# SPEC-AI-064: 코스피 대폭락 조기 경보 텔레그램 알림 시스템

## HISTORY

- 2026-06-24 (v1.0.0): 최초 작성. 2026-06-23 코스피 대폭락 대응. 선행지표(글로벌 야간 선물·VIX·환율 + 장중 코스피 낙폭)를 사전에 읽어 폭락 위험을 **사전에** 감지하고 텔레그램 경보를 발송하는 순수 모니터링 시스템 정의. 매수 중단/포트폴리오 변경은 하지 않는다(경보 전용).

## 배경 (Background)

2026-06-23 코스피 대폭락이 발생했다. 기존 시스템은 폭락 위험을 **사전에 경고하지 못한다**:

- **`market_regime_service.py`** (SPEC-AI-015): 08:55 KST에 BULL/SIDEWAYS/BEAR를 분류하나, 전일 데이터 기반(후행적, backward-looking)이라 **당일 폭락을 예측할 수 없다.**
- **`macro_risk.py`** (SPEC-AI-010): 뉴스 키워드("전쟁", "폭락", "계엄")를 감시하나, 폭락이 **이미 발생한 후** 뉴스에서 "폭락" 키워드를 잡는 반응적(reactive) 구조다.

두 시스템 모두 폭락을 **사후에** 인지한다. 본 SPEC은 폭락 1~6시간 전에 신호를 보내는 **선행지표(leading indicators)** 를 읽어 사전 경보를 발송한다.

## 해결 전략 (Solution Strategy)

신규 `crash_guard_service.py`를 추가하여, 폭락 위험을 알리는 선행지표를 우선순위 순으로 스캔하고 복합 위험도(CrashRiskScore)를 산출한다. 위험도가 WARNING 이상이면 텔레그램 경보를 발송한다. 본 시스템은 **읽기·알림 전용**이며, 매수 로직·포트폴리오·기존 서비스를 일절 변경하지 않는다(additive only).

선행지표 출처(우선순위 순):

- **신호 그룹 A — 글로벌 장전 (08:00~08:30 KST 스캔, yfinance)**: S&P 500 야간 선물 % 변동, VIX 공포지수 수준 + 일일 변동, Nasdaq 선물, USD/KRW 환율 변동.
- **신호 그룹 B — 장중 코스피 낙폭 모니터 (09:05 KST 스캔, Naver Finance)**: 코스피 지수 현재값 vs 전일 종가 → 장 초반 -1.5% 이상 하락 시 경고.
- **신호 그룹 C — 코스피200 선물 베이시스 (선택/향상, Naver Finance)**: 코스피200 선물 vs 현물 스프레드. 큰 음(-)의 베이시스 = 기관 매도 압력 신호.
- **신호 그룹 D — 미국 시장 마감 후 스캔 (06:30 KST, yfinance)**: 미국 실제 종가(S&P 500 전일 종가 % 변동)를 코스피 개장 **2.5시간 전**에 조회. 하락 임계 초과 시 "내일 코스피 하락 주의" 사전 경보 발송. 이 신호가 **본 SPEC에서 가장 선행적인 경보**다.
- **신호 그룹 E — 코스피200 야간 선물 체결가 (08:30 KST 스캔 포함, Naver Finance)**: KRX 야간 선물 세션(03:30~08:55 KST) 체결가 vs 전일 종가 괴리율. 장 시작 30분 전에 시장이 몇 %로 시작할지를 직접 읽는다. 이것이 사용자가 요청한 "선물시장을 읽는" 방법이다.

## 환경 및 가정 (Environment & Assumptions)

- 대상 시스템: news-hive 백엔드 (`backend/app/services/`). bare-metal 배포(Docker 없음), PostgreSQL + uvicorn + systemd, APScheduler 크론.
- **yfinance는 이미 의존성에 존재한다** (`requirements.txt:28` `yfinance>=1.2.0`). `commodity_service.py`(L57, L150, L171)와 `macro_rates.py`(L99~L140)에서 `import yfinance as yf` → `yf.download(symbol, period=..., interval=..., progress=False, auto_adjust=True)` 및 `yf.Ticker(symbol)` 패턴으로 실사용 중. **신규 의존성 추가 불필요** — 기존 사용 패턴을 재사용한다.
- 텔레그램 발송 함수는 이미 존재한다: `telegram_service.send_telegram_message(chat_id: str, text: str, parse_mode="HTML", reply_markup=None) -> bool`. `TELEGRAM_BOT_TOKEN` 미설정 시 `False` 반환(graceful). 발송 대상 채팅 ID는 `os.environ.get("TELEGRAM_ADMIN_CHAT_ID")` (scheduler.py:157에서 DART 알림에 동일 패턴 사용). 미설정 시 발송 스킵.
- APScheduler 크론은 KST 시각을 직접 전달한다: `scheduler.add_job(func, "cron", day_of_week="mon-fri", hour=H, minute=M, timezone="Asia/Seoul", id=..., max_instances=1, coalesce=True, ...)` (scheduler.py 등록 블록). 래퍼 함수는 `SessionLocal()` 생성 후 `asyncio.run(...)` 호출, `try/except/finally`로 DB close + `_record_job_duration(...)`.
- 한국 시장 지수 데이터는 Naver Finance를 통해 조회한다. `data.krx.co.kr` 직접 호출은 세션 인증(400 LOGOUT) 문제로 금지(SPEC-KS200-001 경험).
- DB 모델은 `app/database.Base` + SQLAlchemy 2.0 `Mapped`/`mapped_column` 컨벤션을 따른다(`app/models/macro_alert.py` 참조). 신규 마이그레이션 head는 `061_surge_per_stock_analysis.py` 다음(`062`).
- yfinance는 Yahoo 측 사정으로 간헐적 실패가 발생할 수 있다(레이트리밋, 빈 DataFrame). 실패 시 graceful fallback(경고 로그 + 해당 신호 스킵)이 필수다.

## 요구사항 (Requirements — EARS 형식)

### Ubiquitous Requirements (상시 활성)

**REQ-AI-064-001**: 시스템은 모든 폭락 위험 임계값(S&P 500 야간 변동, VIX 수준/변동, Nasdaq 선물 변동, USD/KRW 변동, 장중 코스피 낙폭, 코스피200 선물 베이시스)을 코드 하드코딩이 아닌 **설정 파일에서 shall** 노출하여 운영 중 조정 가능하게 한다.

**REQ-AI-064-002**: 시스템은 폭락 경보 발송 이력을 `crash_risk_alerts` 테이블에 **shall** 영속 저장하여, 사후 검증과 임계값 튜닝의 근거를 남긴다.

### Event-Driven Requirements (트리거-응답)

**REQ-AI-064-003**: **When** 장전 스캔(`run_premarket_crash_scan`, 08:30 KST)이 실행될 **때**, 시스템은 yfinance로 신호 그룹 A(S&P 500 선물, VIX, Nasdaq 선물, USD/KRW)를 수집하고 복합 위험도를 산출 **shall** 한다.

**REQ-AI-064-004**: **When** 장중 스캔(`run_intraday_crash_check`, 09:05 KST)이 실행될 **때**, 시스템은 Naver Finance로 코스피 지수의 전일 종가 대비 변동률을 조회하고 복합 위험도를 산출 **shall** 한다.

**REQ-AI-064-005**: **When** 산출된 복합 위험도가 WARNING 이상일 **때**, 시스템은 트리거된 신호 목록과 위험도를 포함한 텔레그램 메시지를 `TELEGRAM_ADMIN_CHAT_ID`로 **shall** 발송한다.

**REQ-AI-064-006**: **When** 경보가 발송되거나 위험도가 산출될 **때**, 시스템은 해당 위험도·트리거된 신호·발송 여부를 `crash_risk_alerts` 행으로 **shall** 기록한다.

### State-Driven Requirements (조건부 동작)

**REQ-AI-064-007**: **While** yfinance 데이터 수집이 실패하는 동안(레이트리밋, 빈 DataFrame, 예외), 시스템은 해당 신호를 "미수집(unavailable)"으로 처리하고 **나머지 가용 신호만으로 위험도를 산출**하며 스캔 전체를 중단하지 않고 경고 로그를 남긴 채 **shall** 계속 진행한다.

**REQ-AI-064-008**: **While** 직전 2시간 이내에 동일 위험도(또는 그 이상) 경보가 이미 발송된 상태일 동안, 시스템은 중복 경보를 **shall not** 발송한다(쿨다운). 단, 위험도가 직전보다 **상승(escalation)** 한 경우는 쿨다운을 무시하고 발송 **shall** 한다.

### Unwanted Behavior Requirements (금지 동작)

**REQ-AI-064-009**: **If** 폭락 위험이 감지되더라도, **then** 시스템은 `execute_buy_orders()` 또는 어떤 매수/매도/포트폴리오 로직도 **shall not** 호출하거나 변경한다(순수 모니터링).

**REQ-AI-064-010**: **If** `TELEGRAM_BOT_TOKEN` 또는 `TELEGRAM_ADMIN_CHAT_ID`가 미설정이라면, **then** 시스템은 예외를 발생시키지 않고 발송을 스킵하며 위험도 산출·DB 기록은 **shall** 정상 수행한다.

**REQ-AI-064-011**: **If** `data.krx.co.kr` KRX 직접 API라면, **then** 시스템은 이를 데이터 출처로 **shall not** 사용한다(세션 인증 문제). 한국 시장 데이터는 Naver Finance를 통해서만 조회한다.

### Optional Requirements (선택적 향상)

**REQ-AI-064-012**: **Where** 코스피200 선물 베이시스 데이터를 Naver Finance에서 신뢰성 있게 조회 가능한 환경에서, 시스템은 신호 그룹 C(음의 베이시스 = 기관 매도 압력)를 복합 위험도 산출에 **shall** 추가 신호로 포함한다. 조회 불가 시 본 신호는 생략하고 그룹 A/B만으로 동작한다.

**REQ-AI-064-013**: **Where** 알림 이력 조회 API가 필요한 환경에서, 시스템은 `GET /api/crash-guard/alerts` 엔드포인트로 최근 경보 이력을 **shall** 제공한다.

**REQ-AI-064-014**: **When** 미국 장마감 후 스캔(`run_us_close_crash_scan`, 06:30 KST)이 실행될 **때**, 시스템은 yfinance로 S&P 500 전일 실제 종가 % 변동을 조회하고 임계값(-1.5% 이하) 초과 시 WARNING 이상 위험도를 **shall** 산출하여 텔레그램 경보를 발송한다. 이 스캔은 코스피 개장 약 2.5시간 전에 실행되며, 신호 그룹 A(08:30 KST 선물 체크)와 **독립적**으로 동작한다.

**REQ-AI-064-015**: **When** 08:30 KST 장전 스캔(`run_premarket_crash_scan`)이 실행될 **때**, 시스템은 신호 그룹 A(글로벌 선물)에 추가하여 Naver Finance에서 **코스피200 야간 선물 체결가**(KRX 야간 세션 03:30~08:55 KST)를 조회하고, 전일 종가 대비 괴리율이 -1.5% 이하이면 신호 1개를 **shall** 트리거한다. 조회 실패 시 REQ-AI-064-007(graceful fallback)을 따른다.

## 위험도 산출 규칙 (Crash Risk Score Calculation)

복합 CrashRiskScore는 트리거된 신호 개수와 장중 코스피 낙폭에 따라 4단계로 분류한다(설정 가능 임계값 기반):

| 위험도 | 조건 | 알림 |
|--------|------|------|
| **SAFE** | 트리거된 신호 0개 | 알림 없음 |
| **CAUTION** | 트리거된 신호 1개 | 정보성(알림 안 함 — 기록만) |
| **WARNING** | 트리거된 신호 2개 이상 | 강한 경보(텔레그램 발송) |
| **DANGER** | 트리거된 신호 3개 이상 **또는** 장중 코스피 낙폭 >= -2% | 긴급 경보(텔레그램 발송) |

개별 신호 트리거 기본 임계값(설정 가능, REQ-AI-064-001):

- S&P 500 야간 선물: <= -1.5%
- VIX 수준: >= 25, 또는 VIX 일일 변동: >= +15%
- Nasdaq 선물: <= -1.8%
- USD/KRW 환율 변동: >= +1.0% (원화 약세)
- 장중 코스피 낙폭(09:05 스캔): <= -1.5% (WARNING 기여), <= -2.0% (DANGER 강제)
- 코스피200 선물 베이시스(선택): <= -0.5% (음의 베이시스)
- **[신규] 미국 실제 종가 변동(그룹 D, 06:30 스캔)**: <= -1.5% (S&P 500 전일 종가 % 변동)
- **[신규] 코스피200 야간 선물 괴리율(그룹 E, 08:30 스캔)**: <= -1.5% (야간 체결가 vs 전일 종가)

## 데이터 모델 (Data Model — `crash_risk_alerts` 테이블)

`app/models/crash_risk_alert.py` (신규). `macro_alert.py` 컨벤션 미러링.

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | Integer | PK, autoincrement | 기본키 |
| `scan_type` | String(20) | NOT NULL | `"us_close"` \| `"premarket"` \| `"intraday"` |
| `risk_level` | String(10) | NOT NULL | `"SAFE"` \| `"CAUTION"` \| `"WARNING"` \| `"DANGER"` |
| `triggered_signals` | Text(JSON) | nullable | 트리거된 신호 목록 JSON (예: `[{"name":"sp500_overnight","value":-1.8,"threshold":-1.5}]`) |
| `kospi_change_pct` | Float | nullable | 장중 스캔 시 코스피 전일 대비 변동률(%) |
| `telegram_sent` | Boolean | default False | 텔레그램 발송 성공 여부 |
| `created_at` | DateTime(tz=True) | server_default=now() | 생성 시각 |

신규 alembic 마이그레이션 `062_crash_risk_alerts.py` (down_revision="061").

## 텔레그램 알림 형식 (Telegram Alert Format)

위험도 WARNING 이상일 때 발송(HTML parse_mode):

```
[코스피 폭락 경보] ⚠️
위험도: WARNING

트리거된 신호:
- S&P 500 야간: -1.8% (임계 -1.5%)
- VIX: 28.3 (임계 25)
- USD/KRW: +1.2% (임계 +1.0%)

코스피 현재: 2,580p → 전일 대비 -2.1%
```

## 스케줄러 잡 명세 (Scheduler Job Specifications)

`scheduler.py`에 신규 래퍼 + `add_job` 등록 2건 추가:

| 잡 ID | 래퍼 함수 | 트리거 | 시각(KST) | 요일 | 호출 | 선행 시간 |
|-------|-----------|--------|-----------|------|------|-----------|
| `crash_us_close_scan` | `_run_us_close_crash_scan` | cron | 06:30 | mon-fri | `crash_guard_service.run_us_close_crash_scan(db)` | **+2.5시간** |
| `crash_premarket_scan` | `_run_premarket_crash_scan` | cron | 08:30 | mon-fri | `crash_guard_service.run_premarket_crash_scan(db)` | +30분 |
| `crash_intraday_check` | `_run_intraday_crash_check` | cron | 09:05 | mon-fri | `crash_guard_service.run_intraday_crash_check(db)` | (반응적) |

기존 `add_job` 패턴 준수: `timezone="Asia/Seoul"`, `max_instances=1`, `coalesce=True`, `replace_existing=True`. 래퍼는 `SessionLocal()` + try/except(raise)/finally(db.close + `_record_job_duration`).

**충돌 확인**: 09:05 KST에는 이미 `fund_morning_execute`(scheduler.py:1650)와 SPEC-AI-042 `surge_preday_early_entry`가 등록되어 있다. 신규 `crash_intraday_check`는 **distinct id**를 사용하여 `replace_existing` 클로버를 방지한다(09:05는 동일 시각 다중 잡 공존 가능).

## API 엔드포인트 (API Endpoint)

`GET /api/crash-guard/alerts` (REQ-AI-064-013)
- 쿼리 파라미터: `limit`(기본 50), `days`(기본 7, 최근 N일 필터)
- 응답: `crash_risk_alerts` 행 목록(최신순), `id`/`scan_type`/`risk_level`/`triggered_signals`(파싱된 JSON)/`kospi_change_pct`/`telegram_sent`/`created_at`.

## 제외 사항 (Exclusions — What NOT to Build)

- **매수/매도/포트폴리오 로직 변경 금지** (REQ-AI-064-009). `execute_buy_orders()`, `surge_trading_service`, `fund_manager` 일절 미변경.
- **기존 서비스 중단/대체 금지**. `market_regime_service.py`(SPEC-AI-015), `macro_risk.py`(SPEC-AI-010)는 그대로 동작하며 본 SPEC은 additive only.
- **자동 매매 중단 트리거 금지**. 폭락 감지 시에도 자동으로 거래를 멈추거나 BEAR 레짐을 강제 전환하지 않는다(경보 전용).
- **신규 의존성 추가 금지**. yfinance는 이미 `requirements.txt`에 존재(L28). 새 라이브러리를 추가하지 않는다.
- **KRX 직접 API(`data.krx.co.kr`) 사용 금지** (REQ-AI-064-011). Naver Finance만 사용.
- **선물 베이시스(그룹 C)는 선택 사항** — Naver Finance 선물 페이지 파싱이 불안정하면 구현하지 않고 그룹 A/B만으로 출시한다. 그룹 C 미구현이 SPEC 미완료를 의미하지 않는다.
- **실시간(틱) 모니터링 금지**. 스캔은 06:30·08:30·09:05 세 시점 크론으로 한정. 장중 분 단위 폴링은 본 SPEC 범위 밖.
- **프론트엔드 UI 신규 화면 금지**. 본 SPEC은 백엔드 API + 텔레그램만 제공. 대시보드 시각화는 별도 SPEC.
- **VIX/선물 데이터의 캐싱·DB 시계열 저장 금지**. 스캔 시점에 yfinance에서 즉시 조회하고 경보 결과만 저장한다.

## 의존성 및 영역 분리 (Dependencies & Ownership Boundaries)

- **선행 의존**: 없음. 기존 인프라(telegram_service, scheduler, yfinance, Naver Finance) 위에 독립 신규 서비스로 추가.
- **참조 패턴**:
  - yfinance 사용: `commodity_service.py`(L34/L43/L57/L150/L171), `macro_rates.py`(L99~L140).
  - 텔레그램 발송: `telegram_service.send_telegram_message`.
  - 크론 등록: `scheduler.py` `add_job` 블록(예: `fund_morning_execute` L1650, `surge_signal_generate` L1946).
  - DB 모델: `app/models/macro_alert.py`.
- **영역 분리(비충돌)**:
  - `market_regime_service.py`(SPEC-AI-015)는 **후행적 레짐 분류(전일 데이터)** 를 소유. 본 SPEC은 **선행적 폭락 경보**를 소유. 두 시스템은 입력·출력·실행 시각이 다르며 상호 미변경.
  - `macro_risk.py`(SPEC-AI-010)는 **뉴스 키워드 사후 감지**를 소유. 본 SPEC은 **시장 선행지표 사전 감지**를 소유. 키워드 vs 가격지표로 신호원이 다름.
  - surge 예측 SPEC 계열(AI-012/018/029/030/041/043/050/051/060/061/062/063)과 **완전 분리** — 본 SPEC은 surge_detector/surge_settings/surge_detection.yaml/surge_auto_improver를 **일절 건드리지 않는다.**

## 성공 기준 (Success Criteria)

- 장전 스캔이 yfinance로 S&P 500/VIX/Nasdaq/USD-KRW를 조회하고 위험도를 산출함이 확인된다(일부 신호 실패 시에도 나머지로 산출 — REQ-AI-064-007).
- 트리거된 신호 2개 이상(WARNING) 시 텔레그램 메시지가 발송되고 `crash_risk_alerts.telegram_sent=True`로 기록됨이 확인된다.
- 장중 코스피 낙폭 -2% 이상 시 DANGER로 분류되고 긴급 경보가 발송됨이 확인된다.
- 직전 2시간 이내 동일 위험도 경보가 있으면 중복 발송이 차단되고, 위험도 상승 시에는 발송됨이 확인된다(REQ-AI-064-008).
- `TELEGRAM_*` 미설정 환경에서 예외 없이 위험도 산출·DB 기록이 정상 동작함이 확인된다(REQ-AI-064-010).
- `execute_buy_orders()` 및 매수 로직이 본 SPEC 코드 경로에서 호출되지 않음이 정적/테스트로 확인된다(REQ-AI-064-009).
- `GET /api/crash-guard/alerts`가 최근 경보 이력을 반환함이 확인된다.
- **[신규] 미국 마감 스캔(06:30 KST)이 S&P 500 전일 종가 -1.5% 이하 시 WARNING 이상 위험도를 산출하고 텔레그램을 발송함이 확인된다(REQ-AI-064-014).**
- **[신규] 08:30 KST 스캔에 코스피200 야간 선물 괴리율이 포함되고, -1.5% 이하 시 신호 1개가 트리거됨이 확인된다(REQ-AI-064-015).**
- 세 스캔(06:30·08:30·09:05) 간 쿨다운이 정상 동작하며(동일 위험도 2시간 내 중복 차단, 상승 시 즉시 발송) REQ-AI-064-008 준수가 확인된다.
- 테스트 커버리지 85% 이상, 기존 전체 테스트 스위트 전량 통과(yfinance/Naver는 모킹).
