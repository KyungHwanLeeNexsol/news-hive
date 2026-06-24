# 인수 기준 (Acceptance Criteria): SPEC-AI-064

코스피 대폭락 조기 경보 텔레그램 알림 시스템. 모든 외부 의존(yfinance, Naver Finance, 텔레그램)은 테스트에서 모킹한다. 위험도 산출 핵심 로직(`compute_crash_risk_score`)은 순수 함수로 모킹 없이 직접 검증한다.

---

## 시나리오 1: 장전 스캔 — 신호 2개 트리거 시 WARNING 경보 발송 (REQ-AI-064-003, 005, 006)

**Given** 08:30 KST 장전 스캔이 실행되고
**And** yfinance가 S&P 500 야간 -1.8%(임계 -1.5%), VIX 28.3(임계 25), Nasdaq -0.5%(미트리거), USD/KRW +0.3%(미트리거)를 반환할 때
**When** `run_premarket_crash_scan(db)`가 호출되면
**Then** 위험도는 WARNING으로 분류되고(트리거 신호 2개)
**And** `send_telegram_message`가 트리거된 신호 목록(S&P 500, VIX)을 포함한 메시지로 1회 호출되며
**And** `crash_risk_alerts`에 `scan_type="premarket"`, `risk_level="WARNING"`, `telegram_sent=True` 행이 1건 기록된다.

---

## 시나리오 2: 위험도 분류 경계값 (순수 함수, 위험도 산출 규칙)

`compute_crash_risk_score`를 모킹 없이 직접 호출하여 검증(parametrize):

| 트리거 신호 수 | 코스피 낙폭 | 기대 위험도 |
|----------------|-------------|-------------|
| 0 | None | SAFE |
| 1 | None | CAUTION |
| 2 | None | WARNING |
| 3 | None | DANGER |
| 1 | -2.1% | DANGER (코스피 <= -2% 강제) |
| 2 | -1.0% | WARNING |
| 0 | -2.5% | DANGER (코스피 단독으로 -2% 이하) |

**Given** 다양한 신호 조합과 코스피 낙폭이 주어질 때
**When** `compute_crash_risk_score(signals, kospi_change, basis, config)`가 호출되면
**Then** 위 표대로 위험도가 분류되고 트리거된 신호 목록이 정확히 산출된다.

---

## 시나리오 3: 장중 코스피 -2% 낙폭 시 DANGER 긴급 경보 (REQ-AI-064-004)

**Given** 09:05 KST 장중 스캔이 실행되고
**And** Naver Finance가 코스피 전일 대비 -2.1%를 반환할 때
**When** `run_intraday_crash_check(db)`가 호출되면
**Then** 위험도는 DANGER로 강제 분류되고
**And** 긴급 경보 텔레그램이 발송되며 메시지에 "코스피 현재: ... → 전일 대비 -2.1%"가 포함되고
**And** `crash_risk_alerts`에 `scan_type="intraday"`, `risk_level="DANGER"`, `kospi_change_pct=-2.1` 행이 기록된다.

---

## 시나리오 4: yfinance 부분 실패 시 graceful degradation (REQ-AI-064-007)

**Given** 장전 스캔에서 VIX 조회는 성공(28.3)하나 S&P 500/Nasdaq/USD-KRW 조회가 예외 또는 빈 DataFrame을 반환할 때
**When** `fetch_global_premarket_signals()`가 호출되면
**Then** 실패한 신호는 `None`(unavailable)으로 채워지고 경고 로그가 남으며
**And** 스캔은 중단되지 않고 가용 신호(VIX)만으로 위험도가 산출되며(VIX 단독 트리거 → CAUTION)
**And** 예외가 상위로 전파되지 않는다.

---

## 시나리오 5: 2시간 쿨다운 — 동일 위험도 중복 발송 차단 (REQ-AI-064-008)

**Given** 직전 1시간 전에 `risk_level="WARNING"`, `telegram_sent=True` 경보가 `crash_risk_alerts`에 기록되어 있고
**When** 다시 WARNING 위험도가 산출되어 `run_premarket_crash_scan(db)`가 발송을 시도하면
**Then** `_should_send_alert(db, "WARNING")`은 `False`를 반환하고
**And** `send_telegram_message`는 호출되지 않으며
**And** 새 `crash_risk_alerts` 행은 `telegram_sent=False`로 기록된다(위험도 산출·기록은 유지).

---

## 시나리오 6: 위험도 상승(escalation) 시 쿨다운 무시 발송 (REQ-AI-064-008)

**Given** 직전 30분 전에 `risk_level="WARNING"` 경보가 발송된 상태에서
**When** 새 스캔의 위험도가 DANGER로 **상승**하면
**Then** 쿨다운(2시간)이 아직 유효함에도 `_should_send_alert(db, "DANGER")`는 `True`를 반환하고
**And** DANGER 긴급 경보가 발송된다.

---

## 시나리오 7: 텔레그램 미설정 환경 graceful 처리 (REQ-AI-064-010)

**Given** `TELEGRAM_BOT_TOKEN` 또는 `TELEGRAM_ADMIN_CHAT_ID`가 미설정인 환경에서
**And** WARNING 위험도가 산출될 때
**When** `run_premarket_crash_scan(db)`가 호출되면
**Then** 예외가 발생하지 않고
**And** 발송은 스킵되며(`telegram_sent=False`)
**And** `crash_risk_alerts` 행은 정상 기록된다(위험도 산출·DB 기록은 발송 여부와 무관).

---

## 시나리오 8: 매수 로직 미호출 불변식 (REQ-AI-064-009) — 핵심 안전 게이트

**Given** DANGER 위험도가 감지된 상황에서
**When** `run_premarket_crash_scan(db)`와 `run_intraday_crash_check(db)`가 실행되면
**Then** `execute_buy_orders`, `surge_trading_service`, `fund_manager`의 매수/매도/포트폴리오 함수가 **한 번도 호출되지 않는다**
**And** (정적 검증) `crash_guard_service.py`는 매수 실행 모듈을 import하지 않는다.

---

## 시나리오 9: 알림 이력 API (REQ-AI-064-013)

**Given** `crash_risk_alerts`에 최근 7일 내 5건, 8일 전 2건의 경보가 존재할 때
**When** `GET /api/crash-guard/alerts?days=7&limit=50`이 호출되면
**Then** 최근 7일 5건만 최신순으로 반환되고
**And** 각 항목의 `triggered_signals`가 파싱된 JSON 배열로 포함되며
**And** `risk_level`/`scan_type`/`kospi_change_pct`/`telegram_sent`/`created_at` 필드가 응답에 포함된다.

---

## 시나리오 11: 미국 시장 마감 후 스캔 — 06:30 KST 2.5시간 선행 경보 (REQ-AI-064-014)

**Given** 06:30 KST 미국 마감 스캔이 실행되고
**And** yfinance가 S&P 500 전일 종가 -1.8%(임계 -1.5%)를 반환할 때
**When** `run_us_close_crash_scan(db)`가 호출되면
**Then** 위험도는 WARNING으로 분류되고
**And** "내일 코스피 하락 주의" 맥락을 포함한 텔레그램 경보가 1회 발송되며
**And** `crash_risk_alerts`에 `scan_type="us_close"`, `risk_level="WARNING"`, `telegram_sent=True` 행이 기록된다.

---

## 시나리오 12: 08:30 장전 스캔 — 코스피200 야간 선물 신호 추가 (REQ-AI-064-015)

**Given** 08:30 KST 장전 스캔이 실행되고
**And** 글로벌 신호(그룹 A): S&P 500 선물 -0.5%(미트리거), VIX 22(미트리거) — 단독으로는 CAUTION
**And** 코스피200 야간 선물(그룹 E): 전일 종가 대비 -1.8%(임계 -1.5% 트리거) 일 때
**When** `run_premarket_crash_scan(db)`가 호출되면
**Then** 야간 선물 신호가 신호 목록에 추가되어 트리거 신호 2개(VIX 제외, sp500 미트리거+야간선물) → WARNING
**And** 텔레그램 경보가 발송되며 `triggered_signals`에 야간 선물 항목이 포함된다.

**별도 검증 (graceful fallback)**: `fetch_kospi200_night_futures()`가 Naver 파싱 실패로 `None`을 반환할 때, `run_premarket_crash_scan`은 예외 없이 그룹 A 신호만으로 위험도를 산출한다.

---

## 시나리오 10: 스케줄러 잡 등록 검증 (스케줄러 잡 명세)

**Given** `start_scheduler()`가 호출되어 스케줄러가 시작될 때
**When** 등록된 잡 목록을 조회하면
**Then** 아래 3개 잡이 모두 존재한다:
- `id="crash_us_close_scan"` (06:30 KST, mon-fri) — 미국 마감 후 스캔
- `id="crash_premarket_scan"` (08:30 KST, mon-fri) — 장전 글로벌 스캔
- `id="crash_intraday_check"` (09:05 KST, mon-fri) — 장중 코스피 체크
**And** 세 잡 모두 `timezone="Asia/Seoul"`, `max_instances=1`, `coalesce=True`로 등록되며
**And** 09:05의 기존 잡(`fund_morning_execute`, `surge_preday_early_entry`)이 `crash_intraday_check` 등록으로 덮어써지지 않는다(distinct id).

---

## 엣지 케이스 (Edge Cases)

- **모든 신호 미수집**: yfinance 전량 실패 + Naver 코스피 조회 실패 → 위험도 SAFE(트리거 0), 경보 미발송, 기록은 SAFE 또는 미기록 결정(구현 단계 — 권장: 산출 불가 시 기록 스킵 + 경고 로그).
- **VIX 일일 변동만 트리거**: VIX 수준은 24(미트리거)이나 전일 대비 +18%(임계 +15% 트리거) → 1개 트리거 → CAUTION.
- **음의 베이시스 그룹 C 포함 시**: 그룹 C 구현·활성 시 베이시스 -0.7%가 추가 트리거로 집계되어 신호 수 +1.
- **코스피 낙폭 정확히 -2.0%**: 경계값 포함(`<= -2.0%`) → DANGER.
- **쿨다운 정확히 2시간 경계**: 직전 발송이 정확히 2시간 0분 전이면 발송 허용(`>` 비교, 2시간 초과 시 쿨다운 해제).
- **장 휴장일**: cron이 `day_of_week="mon-fri"`만 막으므로 KRX 임시공휴일(평일 휴장)에는 잡이 실행됨 → Naver 코스피 조회가 전일값/빈값 반환 가능. 구현 단계에서 휴장일 가드(예: `is_market_hours`/`KRX_EXTRA_HOLIDAYS` 재사용) 적용 여부 결정(선택).

---

## 품질 게이트 (Quality Gate Criteria)

- 테스트 커버리지 85% 이상(`crash_guard_service.py`, `crash_risk_alert.py`, `crash_guard.py` 라우터).
- 기존 전체 테스트 스위트 전량 통과(`pytest tests/ -m "not slow"`), 회귀 0건.
- `ruff check .` 0 errors, `mypy app/` 통과.
- `python -c "from app.main import app; print('OK')"` 임포트 정상.
- `alembic upgrade head` → `alembic downgrade -1` 왕복 무손상.

## 완료 정의 (Definition of Done)

- [ ] `CrashRiskAlert` 모델 + 마이그레이션 062 생성, `__init__.py` 등록.
- [ ] `crash_guard_service.py`: `fetch_global_premarket_signals`, `fetch_us_close_signal`, `fetch_kospi200_night_futures`, `check_intraday_kospi_drop`, `compute_crash_risk_score`, `_should_send_alert`, `_send_crash_alert`, `run_us_close_crash_scan`, `run_premarket_crash_scan`, `run_intraday_crash_check` 구현.
- [ ] `scheduler.py`: 래퍼 **3개** + add_job **3건**(06:30, 08:30, 09:05 KST) 등록.
- [ ] `GET /api/crash-guard/alerts` 라우터 구현 + main 등록.
- [ ] 위 시나리오 1~12 전부 테스트로 검증(시나리오 8 매수 미호출 불변식, 시나리오 11/12 신규 스캔 포함).
- [ ] graceful fallback(시나리오 4), 쿨다운(5/6), 텔레그램 미설정(7) 검증.
- [ ] yfinance/Naver/텔레그램 모킹 — 외부 네트워크 호출 없는 테스트.
- [ ] 그룹 C(선물 베이시스)는 안정 시 구현, 불안정 시 제외 사항으로 명시하고 그룹 A/B만으로 완료 인정.
- [ ] 품질 게이트 전 항목 통과.
- [ ] 매수/포트폴리오/기존 서비스(market_regime, macro_risk) 무변경 확인.
