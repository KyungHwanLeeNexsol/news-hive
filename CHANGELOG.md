# Changelog

NewsHive의 주요 변경 사항을 기록합니다.

## [Unreleased]

### Added — SPEC-AI-011: 지배구조 인식 기반 종목선택 개선 (2026-04-22)

**배경**: AI 펀드매니저가 HD조선 관련 뉴스를 처리할 때 실제 수혜 종목(HD한국조선해양)이 아닌 지주사(HD현대)를 선택하는 문제 발생. 지주사는 운영 실체가 없어 뉴스 수혜가 자회사로 귀속됨.

- **`StockRelation` 지배구조 타입 추가** (`stock_relation.py`):
  - `holding_company` / `subsidiary` relation_type 지원
  - 방향 규약: `target_stock_id = 지주사`, `source_stock_id = 자회사`
- **Alembic 마이그레이션 050** (`050_spec_ai_011_holding_company.py`):
  - `idx_stock_relations_source_type` 복합 인덱스 생성 `(source_stock_id, relation_type)`
  - HD현대(267250) → 4개 자회사 시드 데이터: HD한국조선해양(009540), HD현대오일뱅크(329180), 현대일렉트릭(010620), HD현대미포(010140)
- **`relation_propagator.py` 지배구조 관계 전파 차단**:
  - `holding_company` / `subsidiary` 타입은 뉴스 감성 전파 대상에서 제외
  - 자회사 확장은 `fund_manager.py`에서 별도 처리
- **`fund_manager.py` 자회사 후보 확장 로직** (3개 헬퍼 함수 추가):
  - `_is_holding_company(db, stock_id)`: 지주사 여부 판별 (인메모리 캐시 지원)
  - `_get_subsidiaries(db, holding_ids)`: 지주사 → 자회사 ID 매핑
  - `_expand_candidates_with_subsidiaries(db, candidates)`: 지주사 후보 발견 시 자회사를 후보 풀에 자동 추가
  - `generate_daily_briefing` 파이프라인에서 `[:10]` cap 이전에 확장 수행
- **브리핑 프롬프트 지주사 경고 주입** (`fund_manager.py`):
  - 지주사 후보 존재 시 `## 지배구조 주의사항` 섹션을 프롬프트에 주입
  - "지주사는 운영 자회사 대신 검토하세요" 맥락 제공
- **`factor_scoring.py` 지주사 할인 팩터** (`build_factor_scores_json`):
  - 지주사 종목의 `composite_score`에 -5 할인 적용 (floor 0)
  - `factor_scores` JSON에 `holding_company_discount: -5` 필드 추가
  - `stock_id` / `db` 파라미터 추가 (기본값 `None`, 하위 호환성 유지)
- **단위 테스트 20개 추가** (`test_spec_ai_011_holding_company.py`):
  - `TestIsHoldingCompany` (5), `TestGetSubsidiaries` (4), `TestExpandCandidatesWithSubsidiaries` (5), `TestBuildFactorScoresJsonHoldingDiscount` (5), `TestRelationPropagatorGuard` (1)
  - 전체 테스트 888개 통과

### Fixed — APScheduler misfire_grace_time 및 종토방 PendingRollbackError 수정 (2026-04-21)

- **APScheduler `misfire_grace_time` 1초 → 30초로 증가** (`scheduler.py`):
  - `vip_follow_trading` 2차 매수 체크가 KST 09:00(UTC 00:00) 장 시작 시 ~1.1초 동기 블로킹 발생
  - 기본값(1초) 초과로 동시 등록된 5개 잡이 매일 자정 skip되던 문제 해결
- **종토방 `save_forum_posts` TOCTOU 경쟁 조건 제거** (`forum_crawler.py`):
  - SELECT-then-INSERT 패턴 → `INSERT ON CONFLICT DO NOTHING` (PostgreSQL dialect) 로 교체
  - `uq_forum_post` 제약조건 기반 원자적 삽입으로 `UniqueViolation` → `PendingRollbackError` 서비스 장애 완전 차단

### Improved — 모의투자 비교 대시보드 개선 (2026-04-15)

- **AI 펀드매니저 총 수익 계산 개선**: `get_portfolio_stats` async 전환, 오픈 포지션 실시간 현재가 반영
  - `_fetch_prices_batch` 배치 조회로 오픈 포지션 평가금액 산출 (현재가 없으면 매수가 fallback)
  - `GET /api/paper-trading/stats` 응답의 `total_return_pct`, `total_pnl`이 미실현 손익 포함
- **모의투자 개요 API 병렬 최적화**: `GET /api/trading/overview` — 3개 모델 stats를 `asyncio.gather`로 동시 조회
- **비교탭 경쟁 대시보드 UI**: 순위(🥇🥈🥉) + 상대 비율 바 + 컬럼 칸반 포지션 카드 + 트레이드 피드 레이아웃
  - 포지션 카드 색상: 수익률에 따라 red(이익)/blue(손실) 강도 자동 적용 (한국 주식 색상 관례)

### Added — SPEC-AI-008: 네이버 종토방 크롤러 및 이상 활성화 탐지 (2026-04-14)

- `StockForumPost`, `StockForumHourly` 모델 추가: 종토방 게시글 및 시간별 집계 데이터
- Alembic 마이그레이션 048: `stock_forum_posts`, `stock_forum_hourly` 테이블 생성
- `backend/app/services/forum_crawler.py`: httpx + BeautifulSoup 기반 종토방 크롤러 (30분 간격)
  - 감성 키워드 기반 bullish/bearish/neutral 분류 (AI 비용 절감)
  - `overheating_alert`: bullish_ratio > 80% 연속 2회 플래그
  - `volume_surge`: comment_volume이 7일 평균 3배 초과 플래그
- 스케줄러 `forum_crawl` 잡 등록 (30분 주기)
- 관련 버그 수정: circuit_breaker 임포트 오류, 네이버 HTML 컬럼 순서 오류

### Added — SPEC-AI-009: 증권사 컨센서스 목표주가 집계 및 fund_manager 통합 (2026-04-14)

- `_gather_securities_consensus()` 함수 추가: 90일 윈도우 목표주가 집계
  - 평균/중앙값 목표가, 최저/최고가, 프리미엄 비율 계산
  - 매수/보유/매도 의견 비율 통계
  - `consensus_signal` 생성: strong_buy / buy / neutral / caution / insufficient
  - 목표주가 추세: 최근 30일 vs 31~90일 비교
- `analyze_stock()` AI 프롬프트에 "## 9-1. 증권사 컨센서스" 섹션 추가
- 기존 `SecuritiesReport` 테이블만 활용 (신규 DB 테이블 불필요)

### Added — SPEC-AI-010: fund_manager 감성 분석 통합 (종토방 + 증권사 컨센서스) (2026-04-14)

- `_gather_forum_sentiment()` 함수 추가: 종토방 역발상 지표 lazy import로 미배포 시 graceful 처리
- `analyze_stock()` 프롬프트 확장
  - "## 1-2. 종토방 감성 (역발상 지표)" 섹션 추가
  - overheating_alert 발생 시: "※ 종토방이 과열 상태입니다. 개인투자자 쏠림에 의한 고점 가능성을 고려하세요"
  - volume_surge 발생 시: "※ 종토방 댓글 급증 감지: 시장 관심도 급등. 공시/뉴스와 교차 확인 필요"
  - "## 9-1. 증권사 컨센서스" 섹션 통합 (SPEC-AI-009)
- `macro_news_crawler.py`: 7개 거시경제 카테고리 RSS 크롤러 추가
  - 주요 카테고리: Fed 정책, 인플레이션, 반도체, 한국 수출, 유가, 환율, 금리 추이

### Fixed — SPEC-AI-007 사후 수정: CONFIDENCE_FLOOR 버그 및 신뢰도 구간 경계값 정렬 (2026-04-13)

- `fund_manager.py` `_CONFIDENCE_FLOOR` 오설정 수정: `MIN_ACTION_CONFIDENCE`(0.55)와 동일하게 설정되어 market_context 패널티(-0.10/-0.15) 및 CoT 패널티(-0.10)가 무력화되던 버그 해결
  - 변경: floor = `MIN_ACTION_CONFIDENCE` → `MIN_ACTION_CONFIDENCE - 0.05` (0.50)
  - 효과: 시장 리스크 시그널이 실제로 거래를 막을 수 있게 됨
- `signal_verifier.py` 신뢰도 구간(confidence_buckets) medium 하한선 조정: 0.40 → 0.55
  - 기존: 0.40~0.70 범위로 설정 → 0.40~0.54 무효 시그널이 "medium" 버킷에 혼재
  - 개선: `MIN_ACTION_CONFIDENCE`(0.55)를 기준으로 통일 → `get_accuracy_stats`와 `calibrate_confidence` 구간 일치
- `test_signal_verifier.py` medium 구간 테스트 데이터 갱신: confidence 0.5 → 0.65

### Added — SPEC-AI-007: Confidence 임계값 통일 및 모델별 적중률 분리 (2026-04-13)

**배경**: gemini 모델이 실제보다 낮은 적중률을 참조하여 과도한 hold 시그널을 생성하는 자기강화 루프 발생. confidence 임계값이 프롬프트(0.7), 코드 가드(0.45), 거래 실행(0.40) 3개 레이어에 걸쳐 불일치.

- `signal_verifier.py` `get_accuracy_stats()` 모델 필터 추가
  - `ai_model: str | None = None` 파라미터 신설
  - ai_model 지정 시 해당 모델의 시그널만 집계 → 타 모델 데이터 오염 차단
  - 최소 샘플 가드 추가: 검증 데이터가 5건 미만이면 `low_sample_warning` 반환
- `fund_manager.py` 임계값 상수 통일
  - 모듈 레벨 상수 `MIN_ACTION_CONFIDENCE: float = 0.55` 선언
  - 기존 로컬 상수 `_MIN_ACTION_CONFIDENCE = 0.45` 제거 및 통합
  - AI 프롬프트 임계값 지시문 수정: "0.7 이상" → "0.55 이상"
  - `get_accuracy_stats()` 호출 시 `ai_model=settings.GEMINI_MODEL` 전달
  - `low_sample_warning` 수신 시 accuracy_text에 데이터 부족 경고 포함
- `paper_trading.py` 거래 실행 임계값 통일
  - `MIN_ACTION_CONFIDENCE` import 추가
  - 하드코딩된 `0.4` → `MIN_ACTION_CONFIDENCE - 0.05` (0.50)으로 변경

### Performance — 모의투자 포트폴리오 조회 속도 개선 (2026-04-09)

- `_fetch_prices_batch()` 추가: Naver 배치 API(`SERVICE_ITEM`) 사용 — 종목 N개를 1회 요청으로 조회
  - 기존: N개 종목 → `Semaphore(5)` 제약으로 `ceil(N/5)` 순차 배치 (최대 10~20초)
  - 개선: N개 종목 → 배치 API 1회 호출 (1~2초), 배치 실패 시 개별 조회 폴백
- `_fetch_price()` 개선: 30초 인메모리 캐시 추가, timeout 10s → 3s 단축
- `get_vip_portfolio_stats`: Stock N+1 쿼리 → `IN` 쿼리 1회로 통합
- `GET /api/vip-trading/positions`: Stock + VIPDisclosure N+1 → `IN` 쿼리 2회로 통합
- `GET /api/paper-trading/positions`: Stock N+1 → `IN` 쿼리 1회로 통합

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
