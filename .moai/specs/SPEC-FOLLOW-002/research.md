# SPEC-FOLLOW-002 Research — 증권사 보고서 수집 및 키워드 알림 확장

## 목적

SPEC-FOLLOW-001로 구축된 기업 팔로잉 + 키워드 알림 시스템을
"증권사 애널리스트 리포트(증권사 보고서)" 컨텐츠 타입까지 확장한다.
뉴스/공시에 이어 세 번째 알림 소스로 "report"를 추가하며, 기존 패턴을 최대한 재사용한다.

## 기존 시스템 분석

### 1. KeywordNotification 모델 (backend/app/models/following.py)

- `content_type` 컬럼은 이미 `news|disclosure|report` 세 가지 값을 주석으로 명시하고 있음
- `UniqueConstraint("user_id", "content_type", "content_id", ...)` 로 중복 알림 방지
- 즉, `content_type="report"` 값만 추가하면 스키마 변경 없이 신규 타입 수용 가능
- 단, `content_id` 는 새로 만들 `securities_reports.id` 를 참조하게 된다 (FK 아님, 단순 정수)

결론: following.py 의 스키마 수정은 불필요.

### 2. DART 크롤러 패턴 (backend/app/services/dart_crawler.py)

재사용 가능한 설계 요소:

- **서킷 브레이커**: `api_circuit_breaker.is_available("dart")` / `record_failure` / `record_success`
  → 증권사 리포트 크롤링에도 "naver_research" 또는 "securities_report" 키로 동일 적용.
- **종목 매핑 전략**:
  `stocks = db.query(Stock).filter(Stock.stock_code.isnot(None)).all()` 로
  `name_to_id` + `code_to_id` 이중 맵을 구축 후, 종목코드 우선/회사명 폴백.
  → 네이버 리서치는 보통 기업명 + 종목코드가 함께 노출되므로 동일 전략이 적용된다.
- **중복 방지**: 기존 식별자 집합을 사전 로드 (DART는 `rcept_no`, 우리는 `url`).
- **페이지네이션 루프**: `page_no` 증가, `total_page` 도달 시 종료.
- **에러 격리**: HTTP 예외 → 서킷 기록 + 로그 + break.
- **후처리 훅**: DART는 저장 후 `_score_new_disclosures()` 호출 → 증권사 리포트는 후처리 불필요(초기 버전).

### 3. 키워드 매처 패턴 (backend/app/services/keyword_matcher.py)

재사용 가능한 설계 요소:

- `_last_run` 모듈 전역 상태로 증분 처리(마지막 실행 이후만 조회)
- `user_keywords: dict[int, list[tuple[keyword_id, keyword, stock_id]]]` 로 사용자별 키워드 그룹핑
- 뉴스와 공시는 완전히 동일한 루프 구조:
  1) 최근 항목 조회 (created_at/collected_at > since)
  2) 검색 텍스트 합성 (제목 + 요약 등 최대 500자)
  3) 사용자 키워드 순회 매칭 (길이 2자 이상)
  4) 중복 알림 체크 (KeywordNotification where user_id/content_type/content_id)
  5) `_dispatch_notification(...)` 호출 → 텔레그램 우선, Web Push 폴백
  6) 첫 매칭 키워드 사용 후 break
- `_dispatch_notification` 는 `content_type` 파라미터에 의존하여 메시지 본문을 구성.
  현재 본문은 `type_label = "뉴스" if content_type == "news" else "공시"` 로 단순 분기 → 3원 분기로 확장 필요.

증권사 리포트 매칭은 뉴스/공시와 동일 패턴을 그대로 복제하며,
`content_type="report"`, 검색 텍스트 = `title + company_name + (opinion or "")` 로 구성한다.

### 4. Alembic 마이그레이션 패턴 (040_spec_follow_001_following.py)

- `revision` = 숫자 문자열 (`"040"`), `down_revision` = 이전 revision
- `op.create_table(...)` + `op.create_index(...)` 패턴
- downgrade 는 의존성 역순
- 현재 latest revision = 040 (SPEC-FOLLOW-001). 신규는 **041**로 생성.

### 5. 스케줄러 통합 지점

`backend/app/services/scheduler.py` 에 `_run_keyword_matching()` 잡이 이미 존재.
신규로 `_run_securities_report_crawl()` 잡을 추가하고,
실행 순서는 `DART/News 크롤링 → 증권사 리포트 크롤링 → 키워드 매칭` 이 자연스럽다.
크롤링 주기는 뉴스/공시와 유사하게 약 30~60분 간격 제안.

## 데이터 소스 분석: Naver Finance Research

### URL 구조

- 메인: `https://finance.naver.com/research/`
- 종목분석 리포트 목록: `https://finance.naver.com/research/company_list.naver`
- 산업/시황 등 다른 탭은 초기 범위 제외 (종목 단위 매칭이 불가능하기 때문).

### 추출 필드 (종목분석 리스트 기준)

| 필드 | HTML 소스 | 필수 |
|-----|---------|-----|
| 기업명 | `td.type01 a` 텍스트 | Y |
| 보고서 제목 | `td.title a` 텍스트 | Y |
| 증권사 | 행 내부 텍스트 | Y |
| 투자의견 | 행 내부 텍스트 (예: "매수", "Buy") | N |
| 목표주가 | 행 내부 텍스트 (숫자 + "원") | N |
| 등록일 | 행 내부 날짜 컬럼 | Y |
| 상세 URL | `td.title a[href]` → 절대경로 변환 | Y (중복 방지 키) |

### 종목코드 매핑

네이버 리서치 목록 페이지에는 종목코드가 노출되지 않는 경우가 있으므로,
1차: 기업명 → `name_to_id` 조회
2차: 기업명이 매칭되지 않으면 stock_id = NULL 로 저장 (공시와 동일 전략)

### 위험 요소

- 네이버 HTML 구조 변경 시 파싱 실패 → BeautifulSoup 선택자를 상수로 분리하고, 파싱 실패 시 행 단위 skip + 경고 로그.
- 페이지네이션 offset/page 파라미터 확인 필요 (네이버 `&page=N`).
- Naver가 User-Agent 검사/빈도 제한을 할 수 있으므로 기존 news_crawler 와 동일한 헤더 전략 사용.
- 목표주가 파싱 시 "N/A", "-", 쉼표 포함 숫자 등 예외 케이스 처리.

## 재사용 요약

| 자산 | 재사용 여부 | 비고 |
|-----|-----|-----|
| KeywordNotification 스키마 | 재사용 | content_type="report" 값만 추가 |
| api_circuit_breaker | 재사용 | "naver_research" 키 신규 등록 |
| Stock 이름/코드 매핑 패턴 | 재사용 | dart_crawler 와 동일 구조 복제 |
| _dispatch_notification | 확장 | type_label 3원 분기 |
| _last_run 증분 로직 | 재사용 | 추가 컨텐츠 루프 한 벌 더 |
| Alembic 패턴 | 재사용 | 041 신규 마이그레이션 |
| 스케줄러 잡 | 확장 | _run_securities_report_crawl 신규 추가 |

## 오픈 이슈

- 상세 페이지 본문(PDF/HTML) 수집 여부 → **범위 외**. 제목/의견/기업명만 키워드 매칭에 사용.
- 목표주가 변경 감지(상향/하향) 알림 → **범위 외**. 차기 SPEC 후보(SPEC-FOLLOW-003).
- 산업/시황/이코노미 리포트 → 종목 비연관성으로 **범위 외**.
