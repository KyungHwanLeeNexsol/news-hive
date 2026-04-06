# Changelog

NewsHive의 주요 변경 사항을 기록합니다.

## [Unreleased]

### Added — SPEC-FOLLOW-002: 증권사 리포트 수집 및 키워드 알림 확장

- `SecuritiesReport` 모델 추가: 네이버 리서치 종목분석 리포트 저장 테이블
- Alembic 마이그레이션 041: `securities_reports` 테이블 생성 (url UNIQUE, stock_id FK)
- `securities_report_crawler.py`: 네이버 리서치 크롤러 (서킷 브레이커 "naver_research", 30분 간격)
- `keyword_matcher.py` 확장: 리포트 키워드 매칭 루프 추가, type_label 3원 분기
- `scheduler.py` 확장: `_run_securities_report_crawl` 잡 등록
- 테스트 2종 추가: `test_securities_report_crawler.py`, `test_keyword_matcher_report.py`

### 구현 비고 (SPEC-FOLLOW-002)

- PDF 본문 수집 제외 (REQ-FOLLOW-002-N3 준수)
- 서킷 브레이커 "naver_research" 키 — 동적 생성으로 circuit_breaker.py 수정 불필요
- `company_name` 컬럼: String(200) — SPEC 7.1 정합

### Added (SPEC-FOLLOW-001: 기업 팔로잉 시스템 - 완료)

- **팔로잉 기능**: `backend/app/models/following.py` - StockFollowing, StockKeyword, KeywordNotification 모델 추가
  - StockFollowing: 사용자-종목 팔로잉 관계
  - StockKeyword: 카테고리별 키워드 (product, competitor, upstream, market, custom)
  - KeywordNotification: 알림 히스토리
- **키워드 생성 서비스**: `backend/app/services/keyword_generator.py` - AI 기반 자동 키워드 생성
  - 4가지 카테고리에서 핵심 키워드 추출
  - Gemini + Z.AI 다중 프로바이더 지원
  - 생성된 키워드의 수동 편집 가능
- **키워드 매칭 및 알림**: `backend/app/services/keyword_matcher.py`
  - 뉴스/공시 제목+본문에서 사용자 키워드 매칭
  - 중복 알림 방지
  - 매칭 결과 DB 기록
- **텔레그램 통합**: `backend/app/services/telegram_service.py`
  - Telegram Bot API를 통한 실시간 알림 발송
  - 채팅 ID 기반 사용자 연동
  - HTML 포맷 메시지 지원
- **팔로잉 라우터**: `backend/app/routers/following.py` - 12개 엔드포인트
  - 종목 팔로잉 CRUD: POST/DELETE/GET `/api/following/stocks`
  - 키워드 관리: GET/POST/DELETE `/api/following/stocks/{code}/keywords`
  - AI 키워드 생성: POST `/api/following/stocks/{code}/keywords/ai-generate`
  - 텔레그램 연동: POST/GET/DELETE `/api/following/telegram/*`
  - 알림 히스토리: GET `/api/following/notifications`
- **사용자 모델 확장**: `backend/app/models/user.py`
  - telegram_chat_id 컬럼 추가 - 텔레그램 연동 시 저장
- **DB 마이그레이션**: `backend/alembic/versions/040_spec_follow_001_following.py`
  - stock_followings 테이블 (user_id, stock_id, UNIQUE 제약)
  - stock_keywords 테이블 (카테고리, 소스 추적)
  - keyword_notifications 테이블 (알림 히스토리, 중복 방지)
  - users.telegram_chat_id 컬럼
- **스케줄러 통합**: `backend/app/services/scheduler.py`
  - 10분 간격 키워드 매칭 작업 추가
  - 신규 뉴스/공시 수집 직후 실행
- **설정**: `backend/app/config.py`
  - TELEGRAM_BOT_TOKEN 환경변수 추가
- **프론트엔드 페이지**:
  - `/following` - 팔로잉 종목 목록 및 텔레그램 연동 상태
  - `/following/[stock_code]` - 키워드 관리 및 알림 히스토리
  - 네비게이션 메뉴에 "팔로잉" 항목 추가
- **테스트 커버리지**:
  - `backend/tests/test_following.py` - 13개 엔드포인트 테스트
  - `backend/tests/test_keyword_generator.py` - AI 키워드 생성 테스트
  - `backend/tests/test_keyword_matcher.py` - 키워드 매칭 로직 테스트
  - `backend/tests/test_telegram_service.py` - 텔레그램 서비스 테스트

### 구현 비고 (SPEC-FOLLOW-001)

- 텔레그램 연동 코드는 Redis가 아닌 in-memory dict 사용 (MVP 범위, 재시작 시 초기화됨)
- Telegram webhook X-Telegram-Bot-Api-Secret-Token 검증 미구현 (단계적 개선 예정)
- 키워드 매칭 로깅 개선 필요 (현재 except 블록에 로깅 누락)

### Deployment Notes (SPEC-FOLLOW-001)

- DB 마이그레이션 필요: `alembic upgrade head` (revision 040)
- 신규 환경변수: `TELEGRAM_BOT_TOKEN` (BotFather에서 발급)
- 하위 호환성: 기존 API 엔드포인트 변경 없음 (신규 라우터 추가만)
- 스케줄러 자동 등록: 앱 시작 시 keyword_matching 작업 자동으로 시작됨

### Added (SPEC-AI-004: 공시 기반 미반영 호재 탐지 - 진행 중)

- **공시 충격 스코어러**: `disclosure_impact_scorer.py` - 공시 유형/규모별 예상 시장 충격 자동 계산
- **DB 마이그레이션**: `036_spec_ai_004_disclosure_impact.py` - Disclosure 모델에 충격 스코어, 반영도, 미반영 갭 필드 추가
- **AI 모델 추적**: `035_add_ai_model_to_briefing_signal.py` - BriefingSignal에 사용된 AI 모델명 기록

### Added (사용자 인증 시스템)

- **User 모델**: `backend/app/models/user.py` - 이메일 인증 기반 회원 관리
- **인증 라우터**: `backend/app/routers/auth.py` - 회원가입, 로그인, 토큰 갱신 엔드포인트
- **사용자 라우터**: `backend/app/routers/user.py` - 프로필 조회/수정, 관심종목 관리
- **이메일 서비스**: `backend/app/services/email_service.py` - 인증 토큰 발송
- **DB 마이그레이션**: `033_add_user_auth_tables.py`, `034_change_verification_code_to_token.py`
- **Frontend 인증**: 로그인/회원가입/이메일 인증 페이지 + AuthProvider 컴포넌트

### Added (푸시 알림)

- **푸시 서비스**: `backend/app/services/push_service.py` - Web Push 알림 발송
- **푸시 라우터**: `backend/app/routers/push.py` - 구독 관리 엔드포인트
- **Service Worker**: `frontend/public/sw.js` - 브라우저 푸시 수신

### Changed (기존 기능 개선)

- **AI 클라이언트**: `ai_client.py` 리팩토링 - 모델 선택 로직 개선
- **채팅 페이지**: 대화형 분석 UI 대폭 개선 (`frontend/src/app/chat/page.tsx`)
- **메인 페이지/워치리스트/펀드/뉴스 페이지**: 인증 연동 및 UI 개선
- **네이버 파이낸스**: `naver_finance.py` 크롤링 안정성 강화

### Infrastructure

- **MoAI ADK**: v2.8.0 -> v2.9.1 업데이트 (hook 스크립트, skill, rule 갱신)

### Added (SPEC-AI-003: 선행 매수 신호 탐지)

- **선행 지표 탐지 엔진**: 4개 독립 신호 탐지 함수로 가격 상승 이전 시점 포착
  - `_detect_quiet_accumulation()`: 외국인+기관 동시 순매수 + 낮은 가격 변동률 감지
  - `_detect_news_price_divergence()`: 긍정 뉴스 발행 후 미반영 가격 괴리 감지
  - `_detect_bb_compression()`: 볼린저 밴드 수축 + 저거래량 에너지 축적 감지
  - `_detect_sector_laggards()`: 모멘텀 섹터 내 낙오 종목 평균 회귀 기회 감지
- **통합 랭킹 시스템**: 4개 지표 복합 신호 가중 점수 산정, 중복 감지된 종목 우선 배치
- **AI 프롬프트 통합**: `leading_signals` 메타데이터 필드로 신호 타입과 강도 전달
- **asyncio.Semaphore(5)** 동시성 제어: API 호출 병렬화로 60초 이내 처리 완료
- **24개 특성 테스트**: 각 신호 탐지 함수별 단위 테스트, 통합 테스트, 에러 처리 시나리오 검증

### Added (배포/점검 중 시스템 점검 페이지 및 미들웨어)

- 시스템 점검 페이지 (`/maintenance`): "시스템 점검 중" 안내, 10초 자동 재시도, 백엔드 복구 시 자동 홈 이동 (`frontend/src/app/maintenance/page.tsx`)
- Next.js 미들웨어 (`frontend/src/middleware.ts`): 페이지 접근 시 헬스체크 수행, 백엔드 다운 감지 시 `/maintenance`로 리디렉션, Edge Runtime 호환 AbortController 적용
- `fetchWithRetry` 강화 (`frontend/src/lib/api.ts`): 최종 502/503 또는 네트워크 오류 발생 시 `/maintenance`로 자동 이동

### Fixed (뉴스 새로고침 안정성)

- 뉴스 새로고침 후 서버 응답 없음 수정 (`backend/app/routers/news.py`): `_deduplicate_existing` 및 `_backfill_sentiment`을 `asyncio.to_thread()`로 실행하여 이벤트 루프 블로킹 해소, `_backfill_translate`를 최근 200건 / 회당 최대 20건으로 제한
- 뉴스 갱신 안 됨 수정 (`backend/app/services/news_crawler.py`): `del` 이후 참조된 변수(`all_raw_articles`, `existing_urls`)에 의한 NameError 수정

### Deployment Notes (점검 페이지 / 뉴스 새로고침 수정)

- DB 마이그레이션 없음
- 신규 환경변수 없음
- 하위 호환성: 기존 API 엔드포인트 변경 없음

---

### Fixed (원자재 시세 + 뉴스 정확도)

#### 원자재 실시간 가격 수집 (`commodity_service.py`)
- `_download_with_fallback()` 추가: 장 중에는 1분봉(`period="1d", interval="1m"`) 15분 지연 실시간 가격, 장 외 또는 데이터 없을 때는 5일 일봉(`period="5d"`) 종가로 자동 fallback
- 앱 시작 시(lifespan) 시드 완료 직후 `fetch_commodity_prices()` 즉시 실행 — 스케줄러 첫 실행 전 경합 조건 방지 (`main.py`)

#### 석탄 심볼 표준화 (`seed/commodities.py`, `migration 024`)
- 석탄 심볼 `MTF=F` / `BTU` → `COAL` (Range Global Coal ETF 프록시)로 표준화
- `024_ensure_coal_symbol.py` 마이그레이션: BTU와 COAL이 동시 존재하는 unique violation 방지 — BTU 관련 레코드 삭제 후 COAL 보장
- ETF 프록시 사용 이유: Newcastle Coal 선물(MTF=F)은 yfinance 미지원, BTU도 거래 중단으로 `COAL` ETF를 대용

#### 원자재 뉴스 오탐 수정 (`commodity_news_service.py`)
- 키워드 매칭 범위를 기사 **제목만**으로 제한 (기존: 제목 + 본문 500자)
- `귀금속` 키워드를 은(SI=F)의 extra keywords에서 제거 — 금 기사에 은 뱃지가 함께 붙는 오탐 방지

### Deployment Notes

- DB 마이그레이션 필요: `alembic upgrade head` (024_ensure_coal_symbol)
- 신규 환경변수 없음
- 하위 호환성: 기존 API 엔드포인트 변경 없음

---

### Added (SPEC-RELATION-001: 종목 간 관계 기반 간접 영향 뉴스 전파)

- **stock_relations 테이블**: AI 추론 종목/섹터 간 방향성 관계 저장 (공급망, 경쟁사, 장비, 소재, 고객사)
- **stock_relation_service.py**: Gemini AI 기반 섹터 간/섹터 내 관계 자동 추론 (하드코딩 없음)
- **relation_propagator.py**: 관계 그래프 탐색 기반 간접 영향 뉴스 전파 엔진 (감성 역전 포함)
- **간접 뉴스 배지**: "↗ 간접호재" / "↘ 간접악재" 프론트엔드 배지 표시
- **관계 API**: GET/POST/DELETE /api/stocks/relations 엔드포인트
- **DB 마이그레이션**: migration 019 (stock_relations 신규), 020 (news_stock_relations 컬럼 3개 추가)

### Deployment Notes (SPEC-RELATION-001)

- DB 마이그레이션 필요: `alembic upgrade head` (019, 020)
- 앱 재시작 시 AI 관계 추론 자동 실행 (stock_relations 비어있을 때)
- 하위 호환성: 기존 뉴스 크롤링 파이프라인 변경 없음

---

### Added (SPEC-NEWS-001: 뉴스-가격 반응 추적 시스템)

- **NewsPriceImpact 모델**: 뉴스 발행 시점의 주가 스냅샷 및 T+1D/T+5D 가격 변화율 추적
- **가격 스냅샷 자동 캡처**: 뉴스 수집 완료 직후 관련 종목의 현재가를 자동으로 저장
- **자동 백필 스케줄러**: 매일 18:30 KST에 1일/5일 경과 레코드의 수익률 자동 계산
- **뉴스 반응 통계 API**: `GET /api/stocks/{id}/news-impact-stats` — 30일 평균 수익률, 승률 제공
- **뉴스 impact API**: `GET /api/news/{id}/impact` — 특정 뉴스의 가격 반응 데이터 조회
- **AI 브리핑 강화**: 데일리 브리핑 프롬프트에 종목별 뉴스-가격 반응 통계 데이터 통합
- **종목 상세 UI**: 뉴스 반응 통계 카드 (평균 1일/5일 수익률, 승률, 데이터 건수) 추가
- **DB 마이그레이션**: migration 016 — news_price_impact 테이블 (3개 인덱스 포함)
- **90일 자동 정리**: 매일 03:00 KST에 90일 초과 impact 레코드 자동 삭제

### 구현 비고

- `relation_id`는 현재 None으로 전달됨 (대량 삽입 후 ID 역추적은 향후 개선 예정)
- FK 전략: `news_id`는 ON DELETE SET NULL, `stock_id`는 ON DELETE CASCADE
- 신규 환경변수 없음 (기존 `naver_finance.fetch_stock_fundamentals_batch()` 재사용)

### Deployment Notes

- DB 마이그레이션 필요: `alembic upgrade head` (016_add_news_price_impact_table)
- 신규 환경변수 없음
- 하위 호환성: 기존 API 엔드포인트 변경 없음 (신규 엔드포인트 추가만)
