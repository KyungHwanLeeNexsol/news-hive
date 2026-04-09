---
id: SPEC-VIP-001
title: VIP투자자문 지분 추종 자동매매
status: Planned
priority: High
created: 2026-04-08
lifecycle: spec-anchored
---

# SPEC-VIP-001: VIP투자자문 지분 추종 자동매매

## Overview

**전략명**: VIP투자자문 지분 추종 자동매매 (VIP Investment Advisory Copycat Trading)

**목표**: 한국 VIP투자자문이 DART에 제출하는 5% 이상 대량보유 공시(주식등의대량보유상황보고서)를 실시간 추적하여, 동일 종목을 자동으로 분할 매수/매도하는 카피캣 트레이딩 시스템 구축.

**범위**:
- 기존 AI 페이퍼 트레이딩 시스템과 완전히 분리된 신규 포트폴리오
- DART 크롤러 확장 (VIP투자자문 공시자 필터링 + 보고서 본문 파싱)
- 신규 매매 서비스 (분할 매수, 부분 익절, 전량 매도 로직)
- 신규 스케줄러 작업 (공시 폴링, 청산 조건 체크)
- 신규 API 라우터 및 단위 테스트

**비범위 (Out of Scope)**:
- 기존 `paper_trading.py`, `fund_manager.py`, `virtual_portfolio.py` 변경 없음
- 기존 AI 시그널 생성 로직 변경 없음
- 프론트엔드 UI 작업은 별도 SPEC에서 다룸

---

## Environment

- **Backend**: FastAPI + SQLAlchemy + APScheduler (기존 인프라 재사용)
- **DB**: PostgreSQL (Alembic 마이그레이션 043으로 신규 테이블 추가)
- **외부 API**:
  - DART Open API 목록: `https://opendart.fss.or.kr/api/list.json`
  - DART 보고서 본문: `https://opendart.fss.or.kr/api/document.json` (XML)
  - 시세 조회: `app/services/naver_finance.fetch_current_price` (기존 함수 재사용)
- **타임존**: Asia/Seoul (KST), 거래일 기준 영업일 계산

---

## Assumptions

1. VIP투자자문은 DART 공시자명(`flr_nm`)에 "VIP투자자문" 문자열을 포함하여 등록한다.
2. DART 보고서 본문 XML에는 `보유주식수`, `주식등의수`, `보유비율`, `평균단가` 필드가 존재하며 정규식 또는 XML 파싱으로 추출 가능하다.
3. DART API 키는 환경변수 `DART_API_KEY`로 이미 설정되어 있다 (기존 `dart_crawler.py` 참조).
4. 한국 거래일(영업일) 계산을 위해 주말과 공휴일을 제외한 단순 영업일 카운트를 사용한다 (별도 공휴일 캘린더 라이브러리 도입 없음).
5. 기존 종목 마스터 테이블(`stocks`)에 매수 대상 종목이 등록되어 있거나, 미등록 시 자동 등록한다.
6. VIP 포트폴리오는 단일 인스턴스로 운영한다 (멀티 포트폴리오 미지원).

---

## Requirements (EARS Format)

### REQ-VIP-001: VIP 대량보유 공시 수집 (Event-Driven)

**WHEN** DART API에서 `report_nm`에 "주식등의대량보유"를 포함하는 신규 공시가 발견되고 **AND** 공시자(`flr_nm`)에 "VIP투자자문"이 포함되는 경우, **THEN** 시스템은 해당 공시를 다음 정보와 함께 `vip_disclosures` 테이블에 저장해야 한다:

- `rcept_no` (DART 접수번호, unique)
- `corp_name` (대상 회사명)
- `stock_code` (대상 종목 코드)
- `stake_pct` (보유비율, 보고서 본문에서 파싱)
- `avg_price` (평균단가, 보고서 본문에서 파싱)
- `disclosure_type` (분류: `accumulate` / `reduce` / `below5` / `unknown`)
- `rcept_dt` (공시 접수일)
- `flr_nm` (공시자명)
- `raw_xml` (원본 XML, nullable)
- `processed` (처리 여부, 기본값 False)

**WHY**: 공시 원문을 보존해 추후 디버깅 및 백테스트에 활용한다.
**IMPACT**: 누락 시 매매 시그널이 발생하지 않아 전략 자체가 동작하지 않는다.

### REQ-VIP-002: 5% 이상 공시 시 분할 매수 (Event-Driven)

**WHEN** VIP 공시가 탐지되고 **AND** `stake_pct >= 5.0`이며 **AND** `disclosure_type`이 `accumulate`인 경우, **THEN** 시스템은 즉시 1차 매수를 실행해야 한다.

**WHEN** 1차 매수 실행 후 3 거래일이 경과한 경우, **THEN** 시스템은 동일 종목에 대해 2차 매수를 실행해야 한다.

**규칙**:
- 종목당 총 포지션 크기 = VIP 포트폴리오 가용 현금 × 10%
- 각 분할 매수 = 총 포지션 크기 / 2 (50%씩)
- 1차 매수가는 현재가 기준 시장가
- 2차 매수가는 3 거래일 후 시장가
- 1차 매수 시 `VIPTrade(split_sequence=1)` 생성
- 2차 매수 시 `VIPTrade(split_sequence=2)` 생성
- 가용 현금 부족 시 가능한 만큼만 매수하고 로그 기록

### REQ-VIP-003: 지분 5% 미만 공시 시 전량 매도 (Event-Driven)

**WHEN** VIP 공시가 탐지되고 **AND** `stake_pct < 5.0`이거나 `disclosure_type`이 `below5` 또는 `reduce`(전량 처분)인 경우, **THEN** 시스템은 해당 종목의 모든 `is_open=True`인 `VIPTrade`를 시장가로 전량 청산해야 한다 (`exit_reason="vip_sell"`).

### REQ-VIP-004: 수익률 50% 이상 시 30% 부분 익절 (State-Driven)

**IF** 어느 VIP 포지션의 `unrealized_return_pct >= 50.0` **AND** `partial_sold == False`인 경우, **THEN** 시스템은 현재 보유 수량의 30%를 시장가로 매도하고 `partial_sold = True`로 설정해야 한다 (`exit_reason="profit_lock"`).

**제약**: 포지션당 1회만 트리거된다. 나머지 70%는 VIP가 5% 미만으로 떨어질 때까지 보유한다.

### REQ-VIP-005: 별도 VIP 포트폴리오 (Ubiquitous)

시스템은 항상 기존 AI 펀드 포트폴리오와 완전히 독립된 다음 테이블을 유지해야 한다:

- `vip_portfolios`: 단일 포트폴리오, 초기 자본 50,000,000 KRW
- `vip_trades`: VIP 매매 내역
- `vip_disclosures`: VIP 공시 원문

기존 `virtual_portfolios`, `virtual_trades`, `portfolio_snapshots` 테이블은 변경하지 않는다.

### REQ-VIP-006: 스케줄러 연동 (Event-Driven)

**WHEN** 한국 거래시간(평일 09:00–18:00 KST) 중 매 30분마다, **THEN** 시스템은 DART API를 폴링하여 신규 VIP 공시를 수집하고 REQ-VIP-001 ~ REQ-VIP-003을 처리해야 한다.

**WHEN** 한국 거래시간 중 매 60분마다, **THEN** 시스템은 모든 오픈 VIP 포지션의 청산 조건(REQ-VIP-004)과 2차 매수 대기 포지션의 영업일 경과 여부(REQ-VIP-002)를 체크해야 한다.

### REQ-VIP-007: API 엔드포인트 제공 (Ubiquitous)

시스템은 다음 REST API를 항상 제공해야 한다:

- `GET /api/vip-trading/portfolio` — VIP 포트폴리오 현황 (현금, 평가금액, 총 손익)
- `GET /api/vip-trading/positions` — 현재 오픈 포지션 목록
- `GET /api/vip-trading/trades` — 전체 매매 내역 (페이지네이션)
- `GET /api/vip-trading/disclosures` — 수집된 VIP 공시 내역
- `POST /api/vip-trading/trigger-check` — 수동 트리거 (관리자용)

### REQ-VIP-008: 보안 및 데이터 보호 (Unwanted)

시스템은 DART API 키를 코드에 하드코딩해서는 안 되며 (`os.getenv("DART_API_KEY")` 사용), 매매 트리거 엔드포인트는 인증 없이 호출되어서는 안 된다.

---

## Specifications

### 데이터 모델

#### `vip_disclosures`

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | Integer | PK | |
| rcept_no | String(20) | unique, not null | DART 접수번호 |
| corp_name | String(100) | not null | 대상 회사명 |
| stock_code | String(10) | not null, indexed | 종목 코드 |
| stock_id | Integer | FK(stocks.id), nullable | 종목 마스터 참조 |
| stake_pct | Float | nullable | 보유비율(%) |
| avg_price | Float | nullable | 평균단가(KRW) |
| disclosure_type | Enum | not null | accumulate/reduce/below5/unknown |
| rcept_dt | Date | not null | 공시 접수일 |
| flr_nm | String(100) | not null | 공시자명 |
| raw_xml | Text | nullable | 원본 XML |
| processed | Boolean | default False | 처리 여부 |
| created_at | DateTime | default now | |

#### `vip_portfolios`

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | Integer | PK | |
| name | String(50) | not null | 포트폴리오 이름 |
| initial_capital | Float | not null | 초기 자본 (50,000,000) |
| current_cash | Float | not null | 현재 현금 |
| is_active | Boolean | default True | |
| created_at | DateTime | default now | |

#### `vip_trades`

| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| id | Integer | PK | |
| portfolio_id | Integer | FK(vip_portfolios.id), not null | |
| stock_id | Integer | FK(stocks.id), not null | |
| vip_disclosure_id | Integer | FK(vip_disclosures.id), not null | 진입 트리거 공시 |
| split_sequence | Integer | not null | 1 또는 2 |
| entry_price | Float | not null | 진입가 |
| quantity | Integer | not null | 현재 보유 수량 |
| entry_date | DateTime | not null | |
| exit_price | Float | nullable | 청산가 (전량 매도 시) |
| exit_date | DateTime | nullable | |
| exit_reason | String(50) | nullable | vip_sell / profit_lock / manual |
| pnl | Float | nullable | 실현 손익 |
| return_pct | Float | nullable | 수익률(%) |
| partial_sold | Boolean | default False | 50% 익절 트리거 사용 여부 |
| is_open | Boolean | default True | |
| created_at | DateTime | default now | |

### API 엔드포인트

```
GET  /api/vip-trading/portfolio
GET  /api/vip-trading/positions
GET  /api/vip-trading/trades?limit=50&offset=0
GET  /api/vip-trading/disclosures?limit=50&offset=0
POST /api/vip-trading/trigger-check    (관리자 전용)
```

### 신규 파일

```
backend/app/models/vip_trading.py
backend/app/services/vip_disclosure_crawler.py
backend/app/services/vip_follow_trading.py
backend/app/routers/vip_trading.py
backend/alembic/versions/043_spec_vip_001_vip_trading.py
backend/tests/test_vip_follow_trading.py
```

### 서비스 책임 분리

- `vip_disclosure_crawler.py`:
  - DART `list.json` 폴링 (`bgn_de`, `end_de`, `pblntf_detail_ty=A001` 또는 지분공시 분류)
  - `flr_nm`에 "VIP투자자문" 포함 필터링
  - `document.json`으로 보고서 본문 XML 다운로드 후 정규식/lxml로 `보유비율`, `평균단가`, `보유주식수` 추출
  - `disclosure_type` 분류: 직전 공시와 비교하여 accumulate/reduce/below5 결정
  - `vip_disclosures` 저장 후 `vip_follow_trading.process_disclosure()` 호출

- `vip_follow_trading.py`:
  - `process_disclosure(disclosure)`: REQ-VIP-002 / REQ-VIP-003 라우팅
  - `execute_first_buy(disclosure)`: 1차 매수
  - `execute_second_buy(trade)`: 영업일 카운트 체크 후 2차 매수
  - `check_exit_conditions()`: 모든 오픈 포지션 순회, REQ-VIP-004 처리
  - `close_positions_for_stock(stock_code, reason)`: REQ-VIP-003 전량 매도
  - `_calculate_position_size(cash)`: 가용 현금 × 10%
  - `_business_days_between(start, end)`: 주말 제외 영업일 카운트

- `scheduler.py` (기존 파일에 작업 추가):
  - `vip_disclosure_polling_job` (cron: */30분, mon-fri 09:00-18:00 KST)
  - `vip_exit_check_job` (cron: 0 * * * *, mon-fri 09:00-18:00 KST)

---

## Exclusions (What NOT to Build)

- Shall NOT modify any file under `backend/app/services/paper_trading.py`, `backend/app/services/fund_manager.py`, or `backend/app/models/virtual_portfolio.py` (이유: 기존 AI 페이퍼 트레이딩과 완전 분리)
- Shall NOT support multiple VIP portfolios in single deployment (이유: 단일 카피캣 전략으로 충분)
- Shall NOT implement frontend UI in this SPEC (이유: 백엔드 우선, UI는 별도 SPEC)
- Shall NOT use external Korean holiday calendar library (이유: 단순 주말 제외 영업일로 충분)
- Will NOT support partial sell triggers other than the 50% profit lock (이유: 전략 단순성 유지)
- Shall NOT auto-register new VIP filers other than "VIP투자자문" (이유: 본 SPEC은 VIP투자자문 추종에 한정)
- Shall NOT trigger trades outside Korean market hours (이유: 현실적 체결 가정 유지)

---

## Acceptance Criteria

상세 acceptance 시나리오는 `acceptance.md` 참조. 핵심 기준:

- **AC-VIP-001**: VIP 공시 수집 스케줄러가 30분마다 DART를 폴링하고, "VIP투자자문"이 `flr_nm`에 포함된 신규 공시를 `vip_disclosures`에 저장한다.
- **AC-VIP-002**: `stake_pct >= 5.0` 공시 탐지 즉시 `VIPTrade(split_sequence=1)`이 생성되고 `vip_portfolios.current_cash`가 차감된다.
- **AC-VIP-003**: 1차 매수로부터 3 영업일 경과 시 `VIPTrade(split_sequence=2)`가 생성된다.
- **AC-VIP-004**: VIP 5% 미만 공시 시 해당 종목의 모든 `is_open=True` `VIPTrade`가 `exit_reason="vip_sell"`로 청산된다.
- **AC-VIP-005**: 수익률 50% 이상 포지션에서 정확히 30% 수량이 매도되며 `partial_sold=True`가 되고, 이후 동일 트리거가 재발동하지 않는다.
- **AC-VIP-006**: VIP 포트폴리오의 매매가 기존 `virtual_portfolios` / `virtual_trades` 테이블에 어떤 영향도 주지 않음을 통합 테스트로 검증한다.
- **AC-VIP-007**: 5개 API 엔드포인트가 200 OK와 정상 페이로드를 반환한다.
- **AC-VIP-008**: `pytest backend/tests/test_vip_follow_trading.py` 5개 이상 단위 테스트 모두 통과 (분할 매수, 전량 매도, 50% 익절, 영업일 카운트, 가용 현금 부족 케이스).

---

## Traceability

- **SPEC ID**: SPEC-VIP-001
- **관련 인프라**: `backend/app/services/dart_crawler.py`, `backend/app/models/disclosure.py`, `backend/app/services/naver_finance.py`
- **마이그레이션**: `043_spec_vip_001_vip_trading.py` (down_revision=`042`)
- **테스트**: `backend/tests/test_vip_follow_trading.py`
- **상위 도메인**: 자동매매 / 공시 추종 전략
