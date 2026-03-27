# Changelog

NewsHive의 주요 변경 사항을 기록합니다.

## [Unreleased]

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
