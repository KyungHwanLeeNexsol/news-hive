# SPEC-AI-016 구현 진행 상황

## 최종 상태: 완료 (2026-05-20)

## 구현된 REQ

| REQ | 상태 | 설명 |
|---|---|---|
| REQ-AI016-001 | 완료 | `ensemble.min_score_for_signal: 0.20 → 0.45` |
| REQ-AI016-002 | 완료 | 탐지기별 분해 INFO 로그 `[SURGE] {code} {action} score=... | theme=... | reason=...` |
| REQ-AI016-003 | 완료 | 섹터 포트폴리오 비중 가드 (`MAX_SECTOR_PORTFOLIO_PCT=0.40`, 환경변수 오버라이드) |
| REQ-AI016-004 | 완료 | 배치 가격 조회 `fetch_current_prices_batch` + 캐시 통합 |

## 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `backend/app/surge_config/surge_detection.yaml` | `min_score_for_signal: 0.20 → 0.45`, `price_query` 섹션 추가 |
| `backend/app/surge_config/surge_settings.py` | `PriceQueryConfig` dataclass 추가, `SurgeDetectionConfig.price_query` 필드 추가 |
| `backend/app/services/naver_finance.py` | `fetch_current_prices_batch()` 함수 추가 (배치 비동기 조회) |
| `backend/app/services/surge_trading_service.py` | `_extract_detector_scores()`, `_get_price_with_change_batch_sync()`, `_compute_sector_portfolio_pct()`, `MAX_SECTOR_PORTFOLIO_PCT` 추가; `execute_buy_orders()` 배치조회/섹터가드/분해로그 적용 |
| `backend/tests/test_surge_trading.py` | T-016-001~016 단위 테스트 추가 (15개), 기존 3개 테스트 배치mock으로 수정 |
| `backend/tests/test_surge_detector.py` | T-016-001 YAML 임계값 0.45 검증 + 주석 업데이트 |

## 테스트 결과

```
전체 테스트: 1073개 (1070 passed + 3 xpassed)
신규 T-016 테스트: 15개 (T-016-001~016 중 16개 중 일부가 통합됨)
```

## 인수 기준 달성

### Phase A (REQ-001)
- AC-016-001-1: YAML min_score_for_signal == 0.45 ✓
- AC-016-001-2: weighted_sum=0.14 (< 0.45) 후보 제외 ✓
- AC-016-001-3: weighted_sum=0.83 (> 0.45) 후보 포함 ✓
- AC-016-001-4: 즉각 공시 우회 (회귀 테스트) ✓

### Phase B (REQ-004)
- AC-016-004-1: 30종목 → 3배치, sleep 2회 ✓
- AC-016-004-2: 일부 None 반환 시 다른 종목 정상 ✓
- AC-016-004-3: 1차 실패 → 재시도 1회 → None ✓
- AC-016-004-4: 50종목 50% 실패 → 25 통과/25 None ✓

### Phase C (REQ-002)
- AC-016-002-1: 매수 완료 시 [SURGE] executed 로그 ✓
- AC-016-002-2: 섹터 집중 스킵 시 sector_concentration 로그 ✓
- AC-016-002-3: 가격 실패 시 price_unavailable 로그 ✓
- AC-016-002-4: surge_metadata 결측 시 0.0, 예외 없음 ✓

### Phase D (REQ-003)
- AC-016-003-1: 섹터 비중 0.596 > 0.40 → sector_overweight 스킵 ✓
- AC-016-003-2: 비보유 섹터 → 통과 ✓
- AC-016-003-3: 현재가 실패 → entry_price 폴백 ✓
- AC-016-003-5: MAX_SECTOR_PORTFOLIO_PCT 환경변수 오버라이드 ✓

## @MX 태그 추가

- `naver_finance.fetch_current_prices_batch`: `@MX:ANCHOR` 추가
- `surge_trading_service._compute_sector_portfolio_pct`: `@MX:NOTE` 추가
- `surge_trading_service._extract_detector_scores`: `@MX:NOTE` 추가
- `surge_trading_service._get_price_with_change_batch_sync`: `@MX:NOTE` 추가
- `surge_trading_service.MAX_SECTOR_PORTFOLIO_PCT`: `@MX:NOTE` 추가

## 배포 주의사항

**반드시 정규장 마감 후(KST 15:30 이후) 배포** — spec.md 5.6절 참조
