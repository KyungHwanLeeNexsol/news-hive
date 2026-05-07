# Changelog

NewsHive의 주요 변경 사항을 기록합니다.

## [Unreleased]

### Fixed — Alembic 마이그레이션 053 프로덕션 배포 오류 수정 (2026-05-07)

- **근본 원인**: `sa.Enum._on_table_create()` 내부에서 `_resolve_for_literal(dialect)` 호출 시 새 PostgreSQL ENUM 객체가 생성되며 `create_type=False` 플래그가 소실 → `CREATE TYPE` 재시도 → `DuplicateObject` 오류
- **수정** (`backend/alembic/versions/053_spec_ai_015_market_regime.py`):
  - `sa.Enum.create(checkfirst=True)` → PL/pgSQL DO 블록 (`EXCEPTION WHEN duplicate_object THEN NULL`) — PostgreSQL 표준 idempotent 패턴
  - 컬럼 타입 `sa.Enum(..., create_type=False)` → `postgresql.ENUM(..., create_type=False)` — dialect 변환 없이 플래그 직접 적용
- **코드 품질** (`backend/app/services/surge_trading_service.py`): ruff F401 — `sqlalchemy.func` 미사용 import 제거

### Added — SPEC-AI-015: 시장 레짐 적응형 전략 (Market Regime Adaptive Strategy) (2026-05-07)

**배경**: AI 펀드매니저가 상승장/하락장/횡보장에서 동일한 정적 파라미터를 사용하여 상승장 기회 손실과 하락장 과다 노출 문제 발생. 즉시 적용 fix(168e4cb) 후속으로 레짐 분류를 DB 영속화하고 모든 파라미터를 동적으로 관리.

- **MarketRegime DB 모델** (`backend/app/models/market_regime.py`, 마이그레이션 053):
  - `market_regimes` 테이블 — date(UNIQUE), regime(ENUM: BULL/SIDEWAYS/BEAR), kospi_5d_return, kospi_20d_ma_position, confidence_score
- **레짐 분류 서비스** (`backend/app/services/market_regime_service.py`):
  - BULL: KOSPI 5일 수익률 ≥ +1.5% AND 20일 MA 위 / BEAR: ≤ -1.5% OR 20일 MA -2% 미만 / SIDEWAYS: 나머지
  - 레짐별 파라미터 — BULL(0.48/20%/30%/7%/7건) · SIDEWAYS(0.55/15%/25%/5%/5건) · BEAR(0.65/10%/15%/4%/2건)
  - 멱등성: UNIQUE constraint + IntegrityError catch + re-SELECT
  - 데이터 부재 시 in-memory SIDEWAYS 기본값 반환 (시스템 무중단)
- **AI 펀드매니저 통합** (`backend/app/services/fund_manager.py`): `analyze_stock()` / `generate_daily_briefing()` 동적 레짐 파라미터 주입
- **모의투자 통합** (`backend/app/services/paper_trading.py`): `_position_pct_by_confidence(conf, db=None)` — 레짐별 포지션 사이징, db=None 시 기존 정적 사다리 역호환 유지
- **스케줄러** (`backend/app/services/scheduler.py`): 매 평일 08:55 KST 레짐 갱신 잡 신설
- **REST API** (`backend/app/routers/fund_manager.py`): `GET /api/fund/market-regime` — 오늘 레짐 + 최근 7일 이력 (데이터 부재 시 SIDEWAYS 기본값 200 OK)
- **테스트**: 56개 신규 (서비스 30 + 특성화 26 + API 6), 전체 1022개 통과, 회귀 zero

### Changed — AI 펀드매니저 수익률 개선 (알파 생성 전략 적용) (2026-05-07)

- **신뢰도 임계값 완화** (`backend/app/services/fund_manager.py`): `MIN_ACTION_CONFIDENCE` 0.55 → 0.50 — 상승장에서 과도한 hold 편향 및 현금 드래그 해소
- **목표가 상한 확대** (`fund_manager.py`): 시그널/브리핑 프롬프트 목표가 범위 +5~20% → +5~30%, 검증 범위 0.30 → 0.35 — 모멘텀 종목에서 조기 익절 방지
- **고확신 포지션 사이즈 확대** (`backend/app/services/paper_trading.py`): conf≥0.80 구간 신설(20%), conf≥0.70(15%), conf≥0.60(10%) 3단계로 재편 — 최고 확신 시그널에 알파 집중
- **시장 레짐 바이어스 주입** (`fund_manager.py`): KOSPI 5일 수익률 기반 상승/하락/횡보 레짐을 `analyze_stock` 및 `generate_daily_briefing` 프롬프트에 실시간 주입 — AI가 시장 추세를 인식하여 buy/hold 결정에 반영

### Changed — 급등 예측 탭 숨김 및 독립 URL 분리 (2026-05-07)

- **탭 UI 제거** (`frontend/src/app/trading/page.tsx`): `/trading` 탭 목록에서 '급등 예측' 버튼 완전 제거 — 일반 사용자에게 비노출
- **독립 URL 신설** (`frontend/src/app/trading/surge/page.tsx`): `/trading/surge` 직접 입력 시에만 접근 가능한 전용 페이지 생성

### Added — SPEC-AI-013: 급등예측 모의투자 포트폴리오 (2026-05-07)

**배경**: SPEC-AI-012에서 생성되는 `FundSignal(signal_type="surge_candidate")` 시그널을 추적·검증할 독립 모의투자 모델이 없어 시그널 수익성 측정이 불가능한 상황. 기존 3개 모델(AI Fund/VIP/KS200)과 완전 분리된 4번째 모의투자 포트폴리오(급등예측 모델) 신설.

- **급등예측 포트폴리오 데이터 모델** (`surge_portfolios`, `surge_trades` 테이블):
  - 초기 자본 5,000,000 KRW, 기존 3개 모델과 자본·포지션·종료조건 완전 분리
  - `FundSignal.paper_executed` 미수정 — `SurgeTrade` 조회 기반 중복 진입 차단(Option B)
  - `surge_probability_score` 스냅샷 저장으로 진입 시점 시그널 정확도 역분석 지원
- **자동 매수 로직** (`backend/app/services/surge_trading_service.py`):
  - KST 평일 09:00~15:30 정규장 내에서만 매수 실행 — 장외 시간은 즉시 no-op
  - `surge_probability_score ≥ 0.6` 시그널만 선택 (설정 가능)
  - 포지션당 초기 자본의 20% (기본 1,000,000원), 일 최대 5 포지션 (설정 가능)
  - async `fetch_current_price` 어댑터(`_get_current_price_sync`)로 sync 서비스에서 안전 호출
- **자동 매도 로직** (`backend/app/services/surge_trading_service.py`):
  - 손절: -8%, 익절: +15%, 최대 보유: 5 거래일 (주말 제외, 공휴일 1차 무시)
  - 가격 조회 실패 시 매도 강제 실행 없음 — 다음 체크 사이클로 안전하게 연기
  - 매도 시 `current_cash` 가산과 `SurgeTrade` 업데이트를 단일 트랜잭션으로 처리
- **APScheduler 잡 2개** (`backend/app/services/scheduler.py`):
  - `surge_execute_buys`: cron, 평일 09:00~15:30, 매 30분 간격
  - `surge_check_exits`: cron, 평일 09:00~15:30, 매 5분 간격
  - 두 잡 모두 `is_market_hours()` 내부 가드 추가로 오차 트리거(15:35 등) 안전 처리
- **REST API** (`backend/app/routers/surge_trading.py`):
  - `GET /api/surge-trading/portfolio` — 현재 평가액·현금·수익률·거래수 통계
  - `GET /api/surge-trading/positions` — 보유 포지션 목록 (현재가·PnL% 포함)
  - `GET /api/surge-trading/trades` — 종료 거래 이력 (페이징, exit_reason/pnl_pct/holding_days)
  - `GET /api/surge-trading/performance` — 누적 수익률 시계열 (days 파라미터)
  - `POST /api/surge-trading/execute` — 관리자 수동 매수 트리거 (X-Admin-Token 인증)
- **DB 마이그레이션**: `052_spec_ai_013_surge_portfolio.py` — `surge_portfolios`·`surge_trades` 테이블, 3개 인덱스, 초기 포트폴리오 레코드(id=1) 자동 생성
- **테스트 40개 추가** (`backend/tests/test_surge_trading.py`): 전체 960/960 PASS
  - AC-SURGE-TRADE-001~031 전체 충족 (매수/매도/API/격리 시나리오 포함)
- **프론트엔드** (`frontend/src/app/trading/page.tsx`): '급등 예측' 탭 추가, `SurgeTab` 인라인 컴포넌트, `frontend/src/lib/api.ts`·`types.ts` Surge 타입 5종·API 함수 4개 통합

### Added — SPEC-AI-012: 급등 징후 탐지 시스템 (2026-05-07)

**배경**: 기존 4개 사전 탐지기(조용한 매집·뉴스-주가 괴리·볼린저밴드 압축·섹터 후행)와 SPEC-AI-004(공시 미반영 갭)만으로는 단기 급등 가능성이 높은 3개 신호 영역(테마 뉴스 클러스터링·거래량-뉴스 복합·공시 유형별 역사적 급등 패턴)이 미포착 상태였음. 룰 기반 앙상블 스코어로 신호 우선순위화 시스템을 구현.

- **테마 뉴스 클러스터 탐지기** (`backend/app/services/surge_detector.py`):
  - 48시간 이내 동일 테마 키워드가 N건 이상 출현한 종목군을 자동 발굴 (`min_news_count` 설정값 경유)
  - 시총 필터·섹터-테마 매핑 적용, 중복 발굴 방지
- **거래량 z-score + 뉴스 복합 신호 탐지기** (`backend/app/services/surge_detector.py`):
  - 24시간 이내 거래량 z-score ≥ 임계값 AND 관련 뉴스 감성 점수 동시 충족 종목 포착
  - z-score 기준값(`volume_zscore_threshold`)과 히스토리 기간(`lookback_days`) 모두 설정 파일 경유
- **공시 유형별 역사적 급등률 탐지기** (`backend/app/services/surge_detector.py`):
  - SPEC-AI-004 FundSignal 데이터를 재활용해 공시 유형별 5일 후 상승 비율(historical surge rate) 산출
  - 24h 인메모리 캐시(`_surge_rate_cache`) 적용으로 DB 쿼리 최소화
  - `min_sample_size`(최소 표본) · `min_surge_rate`(최소 비율) 설정 기반 필터링
- **가중 앙상블 스코어링** (`backend/app/services/surge_detector.py`):
  - `surge_probability_score = 0.25×테마 + 0.30×거래량_뉴스 + 0.25×공시패턴 + 0.20×레거시`
  - 레거시 점수: 기존 4개 탐지기 트리거 수 / 4 (`min(1.0, n/4)`)
  - `min_score_for_signal` 임계값 미달 시 `FundSignal` 생성 미실행
- **surge_candidate 시그널 통합** (`backend/app/services/fund_manager.py`):
  - `_gather_surge_candidates()` — `generate_daily_briefing`의 `asyncio.gather`에서 병렬 호출
  - 5 거래일 이내 동일 종목 중복 시그널 방지 (UPDATE vs INSERT 분기)
  - `FundSignal.surge_metadata` (Text, nullable) 컬럼에 탐지기 조합 JSON 저장
- **신규 API 엔드포인트** (`backend/app/routers/fund_manager.py`):
  - `GET /fund/surge-backtest?days=30` — 방향성 적중률·평균 5일 수익률·탐지기 조합별 통계 반환
- **설정 외부화** (`backend/app/surge_config/surge_detection.yaml`):
  - 모든 임계값(z-score, 테마 키워드 수, 공시 급등률, 앙상블 가중치 등) YAML 설정 경유
  - `SurgeDetectionConfig` Pydantic v2 모델로 타입 안전 로딩 (`model_validator` 가중치 합 검증)
- **DB 마이그레이션**: `051_spec_ai_012_surge_signal.py` — `fund_signals.surge_metadata` Text nullable 컬럼 추가
- **테스트 22개 추가** (`test_surge_detector.py`, `test_surge_backtest.py`): 전체 920/920 PASS
  - AC-SURGE-001 ~ 007 모두 충족
  - 5-day 중복 방지 UPDATE/INSERT 분기 테스트(AC-SURGE-005) 포함

### Fixed — AI 펀드매니저 상승장 과매수 차단 완화 및 프롬프트 개선 (2026-05-06)

**배경**: 한국증시 상승장에서 Stochastic >80 + 이격도 >103% 종목(과매수 상태)이 기술적 승수 0.5를 적용받아 AI confidence가 절반으로 낮아지고 실행 임계값(0.50)에 미달 처리됨. 상승장에서 과매수는 정상 상태임에도 매수 신호가 전혀 생성되지 않는 문제 해결.

- **`_get_technical_multiplier()` 승수 조정** (`backend/app/services/fund_manager.py`):
  - 이중 과매수(Stochastic >80 AND 이격도 >103%): `0.5` → `0.75` (50% 억제 → 25% 억제)
  - 단일 과매수(둘 중 하나): `0.7` → `0.88` (30% 억제 → 12% 억제)
  - 변경 후 AI confidence ≥ 0.67부터 과매수 상태에서도 매수 가능 (기존: 사실상 불가)
- **AI 프롬프트 과매수 판단 기준 개선** (`backend/app/services/fund_manager.py`):
  - 기존: "RSI 과매수 + 볼린저 상단 돌파 = 조정 임박 가능성" → 강한 상승 추세에서도 보수적 판단 유도
  - 변경: 추세 지속 여부 중심 판단, 수급·뉴스 뒷받침 시 과매수 상태도 buy 가능
  - `0.55 미만이면 반드시 hold` 강제 지시 제거 (코드 임계값과 이중 필터링 방지)
- **효과**: 서버 메모리 MemoryMax=700M 적용(systemd OOM kill 방지)과 함께 상승장 대응력 개선

### Added — SPEC-VIP-REBAL-001: VIP 포트폴리오 비중 미러링 리밸런싱 (2026-04-30)

**배경**: VIP 추종 매매에서 2차 매수 시 가용 현금 부족으로 매수를 단순 포기하던 문제 해결. VIP가 이미 종료한 종목이 포트폴리오에 남아 자본이 묶이는 상황을 해소.

- **`_exit_vip_closed_positions()` 신규 함수** (`vip_follow_trading.py`):
  - 가장 최근 공시가 `reduce`/`below5`인 종목의 오픈 포지션 전량 청산
  - `exit_reason="vip_rebalance_exit"`, 종목 단위 그룹 청산, `stock_id` 오름차순 처리
- **`_get_vip_target_weights()` 신규 함수** (`vip_follow_trading.py`):
  - VIP `stake_pct` 비율 기반 목표 비중 산출 (`Σ ≈ 1.0`)
  - `None` stake_pct → 다른 종목 평균값 대체; 전부 None → 1/N 균등 배분
- **`_rebalance_to_vip_weights()` 신규 함수** (`vip_follow_trading.py`):
  - `|current_weight - target_weight| > 0.03` 초과 시만 리밸런싱 실행
  - 매도(trim) 우선 처리 후 매수, 단일 포지션 보호(1개 이하 시 스킵)
- **`_try_rebalance_for_second_buy()` 신규 함수** (`vip_follow_trading.py`):
  - `asyncio.Lock` 동시 실행 방지, 종료포지션청산 → 비중조정 → 현금 충족 여부 반환
- **`check_second_buy_pending()` 확장** (`vip_follow_trading.py`):
  - 현금 부족 시 `VIP_REBALANCE_ENABLED` 확인 후 리밸런싱 재시도
  - 성공 시 `_execute_vip_buy()` 재호출로 2차 매수 실현
- **신규 환경변수**: `VIP_REBALANCE_ENABLED` (기본값 `true`), `VIP_REBALANCE_THRESHOLD` (기본값 `0.03`)
- **테스트 10개 추가** (`test_vip_follow_trading.py`): 전체 23/23 PASS

### Improved — 거래 페이지 UI 용어 및 표시 개선 (2026-04-27)

- **"잔여 현금" → "예수금" 레이블 변경** (`trading/page.tsx`):
  - VIPTab, KS200Tab, PaperTradingTab 세 탭 모두 반영
  - 증권 업계 표준 용어 "예수금"으로 통일
- **현금 카드에 주식평가금액 서브라인 추가**:
  - 예수금 카드 하단에 `주식평가금액 {금액}원` 표시
  - "투자 중" 카드: 포지션 수 → 포지션 평가금액으로 변경

### Fixed — APScheduler DB JobStore 적용 및 yfinance 로그 스팸 억제 (2026-04-27)

- **APScheduler SQLAlchemyJobStore 적용** (`scheduler.py`):
  - 기존 MemoryJobStore는 OOM SIGKILL 재시작 시 스케줄러 상태 소멸 → 당일 브리핑 누락
  - `apscheduler_jobs` PostgreSQL 테이블에 잡 상태 영속화 (37개 잡 등록 확인)
  - OOM 재시작 후 `misfire_grace_time(30s)` 내 누락 잡 자동 재실행
  - 근본 원인: OCI E2.1.Micro 1GB VM 메모리 402MB 도달 → SIGKILL (Apr 24, Apr 25 각 1회)
- **yfinance 로그 스팸 완전 차단** (`main.py`):
  - `ZC=F, ALI=F, ZS=F, ZW=F` 등 미상장 선물 티커 "Failed downloads" 오류가 10분마다 10건씩 출력
  - 하루 144회 ERROR 로그가 journald를 덮어써 OOM 발생 시각 추적 불가
  - `logging.getLogger("yfinance").setLevel(logging.CRITICAL)` 적용으로 완전 차단
  - 검증: 서버 배포 후 10분 경과, yfinance 로그 0건 확인

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
