# Changelog

NewsHive의 주요 변경 사항을 기록합니다.

## [Unreleased]

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
