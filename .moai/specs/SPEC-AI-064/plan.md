# 구현 계획 (Implementation Plan): SPEC-AI-064

## 개요 (Overview)

폭락 위험 선행지표를 스캔하고 텔레그램 경보를 발송하는 신규 독립 서비스 `crash_guard_service.py`를 추가한다. 기존 인프라(yfinance, telegram_service, scheduler, Naver Finance)를 재사용하며, 매수/포트폴리오/기존 서비스는 일절 변경하지 않는다(additive only).

핵심 통찰: 신규 코드가 거의 전부이며 기존 코드 변경은 최소화된다. 변경(수정)되는 기존 파일은 `scheduler.py`(크론 **3건** 등록) 1개뿐이고, 나머지는 신규 파일이다.

**2026-06-24 SPEC 개정**: 사용자 피드백 반영 — 06:30 KST 미국 시장 마감 후 스캔(그룹 D, REQ-AI-064-014) + 08:30 KST 스캔에 코스피200 야간 선물(그룹 E, REQ-AI-064-015) 추가. 스케줄러 잡 3건(06:30, 08:30, 09:05). 이 변경으로 "장 개시 후 반응" 문제를 해결하고 최대 **2.5시간 선행 경보**를 달성한다.

## 델타 마커 범례 (Delta Marker Legend)

- `[EXISTING]` — 변경하지 않는 기존 코드 컨텍스트(참조용)
- `[MODIFY]` — 변경 대상 기존 코드
- `[NEW]` — 신규 파일 / 신규 함수 / 신규 코드 경로

---

## 변경/생성 대상 파일 (Files)

### 파일 1 (신규): `backend/app/models/crash_risk_alert.py`

`[NEW]` `class CrashRiskAlert(Base)` — `macro_alert.py` 컨벤션 미러링(SQLAlchemy 2.0 `Mapped`/`mapped_column`).
- `__tablename__ = "crash_risk_alerts"`
- 컬럼: `id`(PK), `scan_type`(String(20)), `risk_level`(String(10)), `triggered_signals`(Text, nullable — JSON 직렬화 문자열), `kospi_change_pct`(Float, nullable), `telegram_sent`(Boolean, default False), `created_at`(DateTime(tz=True), server_default=func.now()).
- **WHY**: REQ-AI-064-002/006. 경보 이력 영속화로 사후 검증·임계값 튜닝 근거 확보.
- **모델 등록 주의**: `app/models/__init__.py`에 import 추가 필요 여부 확인(기존 모델 등록 패턴 확인). 메모리 노트상 일부 모델은 `__init__.py` 미포함이므로 관계 해결 시 명시적 import 필요할 수 있음 — 단, 본 모델은 FK/관계가 없어 독립적이므로 단순 등록만으로 충분.

### 파일 2 (신규): `backend/alembic/versions/062_crash_risk_alerts.py`

`[NEW]` 마이그레이션. `down_revision = "061"` (현재 head = `061_surge_per_stock_analysis.py`).
- `op.create_table("crash_risk_alerts", ...)` 위 컬럼 정의.
- `downgrade()`에서 `op.drop_table("crash_risk_alerts")`.
- **WHY**: REQ-AI-064-002. 배포 전 `alembic upgrade head` 필수.
- **검증**: `alembic history` 로 061→062 체인 단절 없는지 확인.

### 파일 3 (신규): `backend/app/services/crash_guard_service.py`

핵심 신규 서비스. 함수 단위로 분해(코드 아님 — 로직 서술):

`[NEW]` `fetch_global_premarket_signals() -> dict`
- yfinance로 신호 그룹 A 수집: `^GSPC`/`ES=F`(S&P 500 선물), `^VIX`(VIX), `NQ=F`(Nasdaq 선물), `KRW=X`(USD/KRW).
- 사용 패턴은 `macro_rates.py` L99~L140 미러링: `import yfinance as yf` → `yf.download(symbol, period="5d", progress=False, auto_adjust=True)` 로 직전 2거래일 종가 비교하여 % 변동 산출. VIX는 수준(level) + 일일 변동 둘 다.
- **graceful fallback (REQ-AI-064-007)**: 각 심볼별 try/except. 빈 DataFrame이거나 예외 시 해당 키를 `None`(unavailable)으로 채우고 `logger.warning` 후 계속. 전체 스캔 중단 금지.
- 반환: `{"sp500": float|None, "vix_level": float|None, "vix_change": float|None, "nasdaq": float|None, "usdkrw": float|None}`.

`[NEW]` `check_intraday_kospi_drop(db) -> float | None`
- Naver Finance로 코스피 지수 전일 종가 대비 변동률 조회.
- **데이터 출처 결정(구현 단계 확정)**: `benchmark.py`/`naver_finance.py`가 이미 코스피 지수 조회 경로를 보유하는지 확인하여 재사용. KRX 직접 API 금지(REQ-AI-064-011).
- 실패 시 `None` 반환(graceful).

`[NEW]` `fetch_kospi200_futures_basis() -> float | None` (선택, REQ-AI-064-012)
- Naver Finance 선물 페이지에서 코스피200 선물가 vs 현물 스프레드 산출.
- **선택 구현**: 파싱이 불안정하면 `None` 반환하고 그룹 A/B만으로 동작. 본 함수 미구현이 SPEC 미완료 아님(제외 사항 명시).

`[NEW]` `compute_crash_risk_score(signals: dict, kospi_change: float|None, basis: float|None, config) -> tuple[str, list[dict]]`
- 각 신호를 설정 임계값(REQ-AI-064-001)과 비교하여 트리거 여부 판정 → 트리거된 신호 목록(`[{"name","value","threshold"}]`) 생성.
- 위험도 분류 규칙(spec.md 표): 0개=SAFE, 1개=CAUTION, 2개+=WARNING, 3개+ 또는 코스피<=-2%=DANGER.
- 반환: `(risk_level: str, triggered: list[dict])`.
- **순수 함수**: I/O 없음 → 단위 테스트 용이. 임계값은 인자로 주입받아 모킹 가능.

`[NEW]` `_should_send_alert(db, risk_level: str) -> bool` (쿨다운, REQ-AI-064-008)
- `crash_risk_alerts`에서 직전 2시간 이내 `telegram_sent=True` 행 조회.
- 동일 위험도(또는 그 이상)가 이미 발송됐으면 `False`. 단 위험도가 직전보다 **상승**했으면 `True`(escalation은 쿨다운 무시).
- 위험도 순서 비교: SAFE<CAUTION<WARNING<DANGER (정수 매핑).

`[NEW]` `_send_crash_alert(risk_level, triggered, kospi_change) -> bool`
- `os.environ.get("TELEGRAM_ADMIN_CHAT_ID")` 조회. 미설정 시 발송 스킵, `False` 반환(REQ-AI-064-010).
- spec.md 형식대로 HTML 메시지 구성 → `asyncio.run(send_telegram_message(chat_id, text))` 호출.
- **주의**: 서비스 함수가 sync인지 async인지 구현 단계 결정. scheduler 래퍼가 `asyncio.run(...)`을 호출하는 기존 패턴(commodity_news_crawl L403)을 따르면, 서비스 진입점을 async로 두고 래퍼에서 `asyncio.run` 하는 것이 일관적. `send_telegram_message`가 async이므로 진입점 async 권장.

`[NEW]` `fetch_us_close_signal() -> dict` (그룹 D, REQ-AI-064-014)
- yfinance로 S&P 500 실제 **전일 종가** % 변동 산출: `yf.download("^GSPC", period="5d", interval="1d")` → 최근 2개 종가 비교.
- 주의: `ES=F`(선물)가 아닌 `^GSPC`(현물 종가)를 사용한다. 06:30 KST 시점에는 미국 시장이 이미 마감(05:00~06:00 KST)되어 실제 종가 데이터 가용.
- 반환: `{"sp500_close_change": float|None}`. 실패 시 `None`, graceful fallback.
- **WHY**: 미국 장마감 후 코스피 개장 2.5시간 전에 가장 강한 다음날 한국 시장 방향 신호를 제공.

`[NEW]` `fetch_kospi200_night_futures() -> float | None` (그룹 E, REQ-AI-064-015)
- Naver Finance에서 코스피200 야간 선물 체결가 조회. KRX 야간 세션 03:30~08:55 KST.
- 데이터 소스: Naver Finance `finance.naver.com/item/main.nhn?code=101S6000` (코스피 200 선물) 또는 동등한 Naver 야간 선물 페이지.
- 전일 코스피200 지수 종가와 비교하여 괴리율(%) 산출.
- 실패 시 `None` 반환(graceful). Naver 파싱 불안정 이력 주의(R4와 동일 리스크).
- **WHY**: "선물시장을 읽는다"의 직접 구현 — 장 시작 30분 전에 시장 개시 방향을 선물로 확인.

`[NEW]` `run_us_close_crash_scan(db)` (06:30 잡 진입점, REQ-AI-064-014)
- `fetch_us_close_signal()` → S&P 500 종가 변동만으로 신호 1개 판정(임계 -1.5%).
- 결과를 `compute_crash_risk_score`에 주입 → 위험도 산출.
- WARNING 이상 시 텔레그램 발송(메시지에 "내일 코스피 하락 주의" 맥락 포함).
- `crash_risk_alerts`에 `scan_type="us_close"` 기록.
- **scan_type 구분**: `"us_close"` ≠ `"premarket"` — 쿨다운 로직이 scan_type 무관하게 최근 발송 이력을 조회하므로 연속 중복 발송 방지됨.

`[NEW]` `run_premarket_crash_scan(db)` (08:30 잡 진입점, REQ-AI-064-003, 015)
- `fetch_global_premarket_signals()` + `fetch_kospi200_night_futures()` → 합산 신호를 `compute_crash_risk_score(...)` 에 주입 (kospi_change=None).
- **그룹 E 통합**: 야간 선물 괴리율 -1.5% 이하이면 신호 1개 추가. `fetch_kospi200_night_futures()` 실패 시 신호 기여 없이 진행.
- 위험도 산출 후 `crash_risk_alerts` 행 기록(REQ-AI-064-006).
- WARNING 이상이고 `_should_send_alert`면 `_send_crash_alert` 발송 후 `telegram_sent` 갱신.

`[NEW]` `run_intraday_crash_check(db)` (09:05 잡 진입점, REQ-AI-064-004)
- `check_intraday_kospi_drop(db)` → (선택) 그룹 A 재조회 또는 코스피 단독 → `compute_crash_risk_score(...)`.
- 코스피 낙폭 <= -2% 시 DANGER 강제. 이후 기록·발송은 premarket과 동일 경로.

`[NEW]` 상수/설정 로딩
- 임계값을 어디서 읽을지 구현 단계 결정(REQ-AI-064-001): (A) 신규 YAML 섹션(예: `crash_guard.yaml` 또는 기존 config 확장), (B) `app/config.py` settings 필드, (C) 모듈 상수 + 환경변수 override. 기존 surge 계열은 YAML을 쓰지만 본 SPEC은 surge YAML과 분리해야 함. **권장**: `app/config.py` 또는 전용 작은 설정 모듈 — surge_detection.yaml 오염 금지.

### 파일 4 (신규): `backend/app/routers/crash_guard.py`

`[NEW]` `GET /api/crash-guard/alerts` (REQ-AI-064-013)
- 쿼리: `limit`(기본 50), `days`(기본 7).
- `crash_risk_alerts`에서 `created_at >= now - days` 필터, 최신순, `limit` 적용.
- `triggered_signals` JSON 문자열을 파싱하여 응답.
- **라우터 등록**: `app/main.py`(또는 라우터 집계 지점)에 `include_router` 추가. 기존 라우터 등록 패턴 확인 후 동일하게.

### 파일 5 (수정): `backend/app/services/scheduler.py`

`[EXISTING]` 래퍼 함수 패턴(예: `_run_commodity_price_fetch` L375~392): `_start=_time.monotonic()` → lazy import → `SessionLocal()` → try(작업)/except(log+raise)/finally(`_record_job_duration` + `db.close()`).

`[NEW]` 래퍼 2개 추가 (기존 패턴 미러링):
- `_run_premarket_crash_scan`: `from app.services.crash_guard_service import run_premarket_crash_scan` → `asyncio.run(run_premarket_crash_scan(db))` (진입점 async인 경우).
- `_run_intraday_crash_check`: 동일 패턴, `run_intraday_crash_check`.

`[EXISTING]` `add_job` 등록 블록(예: `fund_morning_execute` L1650, `surge_signal_generate` L1946): `scheduler.add_job(func, "cron", day_of_week="mon-fri", hour=H, minute=M, timezone="Asia/Seoul", id=..., max_instances=1, coalesce=True, ...)`.

`[NEW]` 래퍼 추가 1건 더 (기존 패턴 미러링):
- `_run_us_close_crash_scan`: `from app.services.crash_guard_service import run_us_close_crash_scan` → `asyncio.run(run_us_close_crash_scan(db))`.

`[NEW]` `add_job` 등록 **3건** 추가:
- `crash_us_close_scan`: hour=6, minute=30, id="crash_us_close_scan". **선행 경보 2.5시간.**
- `crash_premarket_scan`: hour=8, minute=30, id="crash_premarket_scan".
- `crash_intraday_check`: hour=9, minute=5, id="crash_intraday_check".
- 둘 다 `timezone="Asia/Seoul"`, `day_of_week="mon-fri"`, `max_instances=1`, `coalesce=True`, `replace_existing=True`.
- **충돌 주의**: 09:05 KST에 `fund_morning_execute`(L1650), `surge_preday_early_entry`(SPEC-AI-042)가 이미 존재. **distinct id `crash_intraday_check`** 사용으로 `replace_existing` 클로버 방지(동일 시각 다중 잡 공존 정상).

---

## 작업 순서 (Task Decomposition — 우선순위 기반)

### Priority High (핵심 경보 경로)

1. **파일 1** — `CrashRiskAlert` 모델 + `app/models/__init__.py` 등록.
2. **파일 2** — 마이그레이션 062 (down_revision="061").
3. **파일 3 (핵심)** — `crash_guard_service.py`:
   - `compute_crash_risk_score`(순수 함수) 먼저 → 단위 테스트 용이.
   - `fetch_global_premarket_signals`(yfinance, graceful fallback).
   - `run_premarket_crash_scan` 진입점 + `_send_crash_alert` + `_should_send_alert`.
4. **파일 5** — `scheduler.py` 래퍼 + add_job 2건.

### Priority Medium (장중 + API)

5. **파일 3** — `check_intraday_kospi_drop`(Naver Finance) + `run_intraday_crash_check`.
6. **파일 4** — `GET /api/crash-guard/alerts` 라우터 + main 등록.

### Priority Low (선택 향상)

7. **파일 3** — `fetch_kospi200_futures_basis`(그룹 C, REQ-AI-064-012). Naver 선물 파싱 안정 시에만. 불안정하면 미구현(제외 사항).

---

## 기술적 접근 (Technical Approach)

- **순수 함수 우선 설계**: `compute_crash_risk_score`를 I/O 없는 순수 함수로 분리 → yfinance/Naver 모킹 없이 위험도 로직 단위 테스트. 데이터 수집 함수는 별도 모킹.
- **graceful degradation**: yfinance 부분 실패가 전체 스캔을 막지 않도록 신호별 try/except. 가용 신호만으로 위험도 산출(REQ-AI-064-007).
- **기존 인프라 재사용**: yfinance(commodity/macro_rates 패턴), telegram(send_telegram_message), scheduler(add_job 패턴), DB(macro_alert 모델 패턴). 신규 추상화 최소화.
- **surge 시스템과 완전 격리**: surge_detector/surge_settings/surge_detection.yaml/surge_auto_improver 미변경. 설정도 surge YAML과 분리.
- **읽기·알림 전용 불변식**: 본 서비스 코드 경로에서 `execute_buy_orders`/매수 함수 import·호출 0건(REQ-AI-064-009) — 테스트로 보증.

## 위험 (Risks)

- **R1 (yfinance 심볼·버전 불안정)**: `requirements.txt`의 `yfinance>=1.2.0` 핀이 의심스러움(yfinance 실제 버전대는 0.2.x). 운영 설치 버전 확인 필요. 야간 선물 심볼(`ES=F`/`NQ=F`)이 환경에 따라 데이터 미반환 가능 → graceful fallback로 흡수하되, 어떤 심볼 조합이 신뢰성 있는지 구현 단계에서 실측. `^GSPC`(현물 종가)와 `ES=F`(선물)의 의미 차이 주의 — 장전 시점엔 선물이 더 적절.
- **R2 (코스피 지수 Naver 출처 확정)**: 코스피 지수 변동률을 Naver에서 조회하는 정확한 경로(`benchmark.py`/`naver_finance.py` 기존 함수 유무)를 구현 전 확인. 없으면 신규 파싱 함수 필요. KRX 직접 API 금지.
- **R3 (쿨다운 위험도 비교 로직)**: "동일 이상이면 차단, 상승이면 발송" 경계 조건(예: WARNING 발송 후 다시 WARNING은 차단, WARNING→DANGER는 발송) 테스트 필수.
- **R4 (Naver 선물 파싱 취약)**: 그룹 C(선물 베이시스)와 그룹 E(야간 선물)는 Naver 선물 페이지 HTML 구조 의존. Naver CSS 변경 이력 多(메모리). 그룹 C는 선택 사항이므로 불안정 시 미구현. 그룹 E는 조회 실패 시 신호 기여 없이 graceful fallback → 08:30 스캔의 그룹 A 신호만으로 동작.
- **R6 (06:30 KST US 종가 데이터 갱신 타이밍)**: 미국 시장 마감(05:00~06:00 KST) 직후 yfinance가 최신 종가를 반영하는 데 수분 지연 가능. 06:30 KST 에는 충분히 갱신되어 있어야 하나, 서버 지역/캐시에 따라 지연 시 전일(D-2) 종가 조회 오류 발생 가능. 구현 단계에서 `yf.download` 결과 날짜 인덱스를 검증(예: 결과 최신 행의 날짜가 `today - 1` 이내인지 확인) 후 오래된 데이터는 `None` 처리.
- **R5 (async/sync 브리지)**: `send_telegram_message`가 async. 서비스 진입점-스케줄러 래퍼 간 `asyncio.run` 경계를 일관되게 설정. 이중 event loop 진입(async 함수 내부에서 또 asyncio.run) 금지 — 메모리상 sync blocking I/O를 async context에서 호출 시 event loop 블로킹 사례 있음. 본 서비스는 크론 래퍼에서만 `asyncio.run` 1회.

## 검증 명령 (Verification — CLAUDE.local.md 기준)

```bash
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"
cd backend && uv run ruff check . && uv run mypy app/
cd backend && uv run python -c "from app.main import app; print('OK')"
```

배포 전 필수:
```bash
cd backend && alembic upgrade head   # 062_crash_risk_alerts 적용
```

## @MX 태그 대상 (MX Tag Targets)

- `crash_guard_service.run_premarket_crash_scan` / `run_intraday_crash_check` → `@MX:ANCHOR` (스케줄러가 호출하는 진입점, fan_in 발생) + `@MX:REASON`.
- `crash_guard_service.fetch_global_premarket_signals` → `@MX:WARN` + `@MX:REASON` (외부 API yfinance 의존 + graceful fallback 분기 — 외부 시스템 통합 위험 지점).
- `compute_crash_risk_score` → `@MX:NOTE` (위험도 분류 비즈니스 규칙 + 임계값 근거).
- `_should_send_alert` 쿨다운 로직 → `@MX:NOTE` (escalation 예외 규칙 의도 명시).
