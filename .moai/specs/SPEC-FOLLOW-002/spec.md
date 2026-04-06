---
id: SPEC-FOLLOW-002
title: Securities Report Collection and Keyword Notification
status: planned
priority: high
created: "2026-04-06"
depends_on: [SPEC-FOLLOW-001]
tier: 7
---

# SPEC-FOLLOW-002 — 증권사 보고서 수집 및 키워드 알림 확장

## 1. Overview (개요)

네이버 금융 리서치(`https://finance.naver.com/research/`)의 종목 분석 리포트를
주기적으로 수집하여 데이터베이스에 저장하고,
SPEC-FOLLOW-001에서 구축된 키워드 매칭 엔진이
뉴스/공시와 동일한 방식으로 **증권사 리포트**까지 매칭 및 알림 발송하도록 확장한다.

## 2. Goals (목표)

- 네이버 리서치 종목분석 리포트 자동 수집 및 저장
- 기업명 기반 Stock FK 매핑
- 기존 키워드 매처에 `content_type="report"` 경로 추가
- 뉴스/공시와 동일 UX의 텔레그램/Web Push 알림 제공
- 기존 인프라(서킷 브레이커, 스케줄러, 알림 디스패처) 100% 재사용

## 3. Non-Goals (범위 외)

- 리포트 본문(PDF/상세 HTML) 수집 및 저장
- 목표주가 상/하향 변동 감지, 증권사 컨센서스 집계
- 산업/시황/이코노미 등 비종목 리포트
- 프론트엔드 UI 변경 (기존 알림 시스템이 처리)
- AI 기반 리포트 요약 및 분석

## 4. Stakeholders

- End User: 팔로잉한 종목의 증권사 신규 리포트를 실시간으로 받고 싶은 투자자
- System: SPEC-FOLLOW-001 키워드 매처, 텔레그램 봇, Web Push

## 5. EARS Functional Requirements

### 5.1 Ubiquitous (항상 적용)

- **REQ-FOLLOW-002-U1**: 시스템은 저장된 모든 증권사 리포트에 대해 고유한 `url` 을 가져야 하며, 동일 `url` 로 중복 저장되지 않아야 한다.
- **REQ-FOLLOW-002-U2**: 시스템은 리포트 수집 시 `stock_code` 또는 `company_name` 으로 Stock 테이블과 매핑을 시도해야 한다.
- **REQ-FOLLOW-002-U3**: 시스템은 매핑 실패한 리포트도 `stock_id=NULL` 로 저장하여 유실하지 않아야 한다.

### 5.2 Event-Driven (이벤트 기반)

- **REQ-FOLLOW-002-E1**: **WHEN** 스케줄러가 `_run_securities_report_crawl` 잡을 트리거 **THEN** 시스템은 네이버 리서치 종목분석 리스트를 크롤링하여 신규 리포트를 DB에 저장해야 한다.
- **REQ-FOLLOW-002-E2**: **WHEN** `match_keywords_and_notify()` 가 실행 **THEN** 시스템은 마지막 실행 이후 새로 저장된 증권사 리포트에 대해 사용자 키워드를 매칭해야 한다.
- **REQ-FOLLOW-002-E3**: **WHEN** 리포트 키워드 매칭 성공 **AND** 동일 `(user_id, content_type='report', content_id)` 알림 이력이 없음 **THEN** 시스템은 텔레그램 또는 Web Push 알림을 발송해야 한다.
- **REQ-FOLLOW-002-E4**: **WHEN** 네이버 리서치 HTTP 요청이 실패 **THEN** 시스템은 `api_circuit_breaker.record_failure("naver_research")` 를 호출하고 다음 주기까지 재시도를 중단해야 한다.

### 5.3 State-Driven (상태 기반)

- **REQ-FOLLOW-002-S1**: **IF** `api_circuit_breaker.is_available("naver_research")` 가 `False` **THEN** 시스템은 해당 주기의 크롤링을 스킵해야 한다.
- **REQ-FOLLOW-002-S2**: **IF** 사용자가 해당 종목을 팔로잉하지 않음 **THEN** 시스템은 해당 사용자에게 리포트 알림을 보내지 않아야 한다.

### 5.4 Unwanted (금지)

- **REQ-FOLLOW-002-N1**: 시스템은 동일한 리포트 URL을 복수의 `SecuritiesReport` 레코드로 저장하지 않아야 한다.
- **REQ-FOLLOW-002-N2**: 시스템은 동일한 `(user_id, content_type='report', content_id)` 조합에 대해 두 번 이상 알림을 발송하지 않아야 한다.
- **REQ-FOLLOW-002-N3**: 시스템은 본 SPEC 범위에서 리포트 본문 파일(PDF)을 다운로드하지 않아야 한다.

### 5.5 Optional

- **REQ-FOLLOW-002-O1**: 가능하면 시스템은 리포트의 목표주가와 투자의견을 파싱하여 저장해야 하며, 파싱 실패 시 `NULL` 로 저장한다.

## 6. Acceptance Criteria

### AC-1: 신규 리포트 수집

- Given 네이버 리서치 종목분석 페이지에 신규 리포트 3건이 존재
- When `_run_securities_report_crawl()` 이 실행되면
- Then `securities_reports` 테이블에 3개 행이 생성된다
- And 각 행의 `url` 은 고유하다
- And 기업명이 Stock 테이블과 매칭되는 리포트는 `stock_id` 가 설정된다

### AC-2: 중복 수집 방지

- Given 동일한 네이버 리서치 리스트에서 방금 수집된 리포트 3건이 동일하게 노출
- When 크롤러가 재실행되면
- Then 새로 저장되는 레코드는 0건이다

### AC-3: 리포트 키워드 매칭

- Given 사용자 A 가 "삼성전자" 를 팔로잉하고 키워드 "HBM" 이 등록되어 있음
- And `securities_reports` 에 제목 "삼성전자 HBM 수요 급증 전망" 리포트가 저장됨
- When `match_keywords_and_notify()` 가 실행되면
- Then `KeywordNotification` 에 `content_type="report"`, `content_id=<report.id>` 행이 생성된다
- And 사용자 A 에게 텔레그램 또는 Web Push 알림 1건이 발송된다

### AC-4: 알림 중복 방지

- Given AC-3 후 동일 리포트가 남아있는 상태
- When `match_keywords_and_notify()` 가 다시 실행되면
- Then 동일 리포트에 대한 추가 알림은 발송되지 않는다
- And `stats["skipped_duplicates"]` 는 최소 1 증가한다

### AC-5: 서킷 브레이커 동작

- Given 네이버 리서치 HTTP 호출이 연속 실패하여 서킷이 열린 상태
- When 다음 크롤링 주기가 트리거되면
- Then 크롤러는 즉시 0건을 반환하고 HTTP 호출을 시도하지 않는다

### AC-6: 매핑 실패 허용

- Given 네이버 리스트에 Stock 테이블에 없는 "XYZ증권" 리포트가 있음
- When 크롤러가 실행되면
- Then 해당 리포트는 `stock_id=NULL` 로 저장된다 (유실 없음)

## 7. Technical Design

### 7.1 New Model: SecuritiesReport

파일: `backend/app/models/securities_report.py`

| 컬럼 | 타입 | 제약 | 비고 |
|-----|-----|-----|-----|
| id | Integer PK | autoincrement | |
| title | String(500) | NOT NULL | 리포트 제목 |
| company_name | String(200) | NOT NULL | 기업명 (원본 텍스트) |
| stock_code | String(10) | NULL | 파싱된 종목코드 (있으면) |
| stock_id | Integer FK(stocks.id) | NULL, ondelete=SET NULL, index | 매핑 실패 시 NULL |
| securities_firm | String(100) | NOT NULL | 증권사명 |
| opinion | String(50) | NULL | 투자의견 (매수/중립/매도 등) |
| target_price | Integer | NULL | 목표주가 (원 단위) |
| url | String(1000) | NOT NULL, UNIQUE | 네이버 리서치 상세 URL |
| published_at | DateTime(tz) | NULL | 리포트 등록일 |
| collected_at | DateTime(tz) | NOT NULL, server_default=now() | 수집 시각 |

인덱스:
- `ix_securities_reports_stock_id`
- `ix_securities_reports_collected_at`
- `uq_securities_reports_url` (UNIQUE)

### 7.2 New Crawler: securities_report_crawler.py

파일: `backend/app/services/securities_report_crawler.py`

주요 함수:

```
async def fetch_securities_reports(db: Session, pages: int = 3) -> int:
    """네이버 리서치 종목분석 리포트를 수집하여 저장. 신규 저장 건수 반환."""
```

설계 원칙:
- `dart_crawler.fetch_dart_disclosures` 의 구조를 그대로 모방
- `api_circuit_breaker` 키 = `"naver_research"`
- `httpx.AsyncClient` + User-Agent 헤더 설정
- BeautifulSoup 으로 `table.type_1` 또는 유사 선택자로 파싱 (구현 시점 확정)
- 기존 URL 집합 사전 로드 → 중복 스킵
- Stock `name_to_id` / `code_to_id` 매핑
- 목표주가는 `int(re.sub(r"[^0-9]", "", text))` 형태, 파싱 실패 시 `None`
- 페이지 루프는 `pages` 인자까지 순회 (기본 3페이지)

### 7.3 Keyword Matcher Extension

파일: `backend/app/services/keyword_matcher.py` (수정)

변경 요약:
- 신규 import: `from app.models.securities_report import SecuritiesReport`
- `match_keywords_and_notify()` 에 세 번째 루프 블록 추가:
  ```
  recent_reports = db.query(SecuritiesReport).filter(
      SecuritiesReport.collected_at > since
  ).all()
  for report in recent_reports:
      search_text = (report.title + " " + report.company_name + " " + (report.opinion or "")).lower()
      # ... 뉴스/공시와 동일한 사용자 키워드 루프
      # content_type = "report"
      # content_id = report.id
      # content_title = report.title
      # content_url = report.url
  ```
- `_dispatch_notification` 의 `type_label` 분기를 3원으로 확장:
  ```
  type_label = {"news": "뉴스", "disclosure": "공시", "report": "리포트"}.get(content_type, "알림")
  ```

### 7.4 Scheduler Integration

파일: `backend/app/services/scheduler.py` (수정)

- 신규 함수 `_run_securities_report_crawl()` 추가 (기존 `_run_dart_crawl` 와 동일 패턴)
- `scheduler.add_job(_run_securities_report_crawl, "interval", minutes=30, ...)` 형태로 등록
- 실행 순서: 뉴스/공시 크롤링 잡 직후 → 키워드 매칭 잡 직전

### 7.5 DB Migration

파일: `backend/alembic/versions/041_spec_follow_002_securities_reports.py`

- `revision = "041"`, `down_revision = "040"`
- `upgrade()`: `op.create_table("securities_reports", ...)` + 인덱스 3개
- `downgrade()`: 인덱스 → 테이블 drop

## 8. File Change List

신규 파일:
- `backend/app/models/securities_report.py`
- `backend/app/services/securities_report_crawler.py`
- `backend/alembic/versions/041_spec_follow_002_securities_reports.py`
- `backend/tests/services/test_securities_report_crawler.py`
- `backend/tests/services/test_keyword_matcher_report.py` (리포트 매칭 경로)

수정 파일:
- `backend/app/services/keyword_matcher.py` — 리포트 루프 + type_label 확장
- `backend/app/services/scheduler.py` — `_run_securities_report_crawl` 잡 등록
- `backend/app/models/__init__.py` — SecuritiesReport 재노출 (있는 경우)
- `backend/app/services/circuit_breaker.py` — `"naver_research"` 키 초기화 (필요 시)

변경 없음:
- `backend/app/models/following.py` — `content_type="report"` 는 이미 주석에 명시됨
- 프론트엔드 전체

## 9. DB Migration Plan

Revision: `041_spec_follow_002_securities_reports`

Upgrade:
1. `securities_reports` 테이블 생성 (모든 컬럼)
2. `ix_securities_reports_stock_id` 생성
3. `ix_securities_reports_collected_at` 생성
4. `uq_securities_reports_url` UNIQUE 제약 생성

Downgrade:
1. UNIQUE / 인덱스 3개 drop
2. `securities_reports` 테이블 drop

Deployment:
- `scripts/deploy.sh` 가 `alembic upgrade head` 를 실행하므로 배포 시 자동 적용
- 롤백은 `alembic downgrade 040` 으로 가능

## 10. Risks and Mitigation

| 위험 | 영향 | 완화 |
|-----|-----|-----|
| 네이버 HTML 구조 변경 | 크롤링 전면 실패 | 선택자 상수화, 파싱 실패 시 행 단위 skip + 경고 로그, 서킷 브레이커 |
| User-Agent 차단 | 수집 중단 | news_crawler 와 동일 헤더 전략, 주기 30분 이상 유지 |
| 동일 리포트의 title 변경 재게시 | 중복 알림 가능성 | URL 기반 중복 방지로 충분 (URL 은 리포트 ID 포함) |
| 기업명 매칭 실패율 높음 | 알림 미발송 | stock_id=NULL 허용 + 주기적 backfill 가능 (차기 SPEC) |
| 목표주가 파싱 예외 | 크롤러 크래시 | `try/except` 로 감싸고 None 저장 |

## 11. Testing Strategy

- **단위 테스트**:
  - 파싱 함수에 고정 HTML fixture 주입 → 필드 추출 검증
  - 목표주가 파싱 엣지 케이스 ("N/A", "-", "1,234,000원")
  - 종목 매핑 fallback (code → name → NULL)
- **통합 테스트**:
  - 인메모리 SQLite 로 crawler 실행 → 중복 방지 검증
  - keyword_matcher: 리포트 fixture + 사용자 키워드 → KeywordNotification 생성 검증
- **회귀 테스트**:
  - 기존 뉴스/공시 매칭 동작 변화 없음 확인

## 12. Definition of Done

- [ ] `SecuritiesReport` 모델 및 마이그레이션 041 작성 및 로컬 적용 완료
- [ ] `securities_report_crawler.py` 구현 및 단위 테스트 통과
- [ ] `keyword_matcher.py` 에 report 루프 추가, type_label 3원 확장
- [ ] `scheduler.py` 에 `_run_securities_report_crawl` 잡 등록
- [ ] 회귀 테스트: 기존 뉴스/공시 알림 동작 유지
- [ ] 서킷 브레이커 `"naver_research"` 키 초기화 확인
- [ ] `scripts/deploy.sh` 기반 OCI 배포 후 `journalctl -u newshive` 에서 정상 로그 확인
- [ ] 실제 사용자 1명 이상에게 리포트 알림 1건 이상 발송 검증
