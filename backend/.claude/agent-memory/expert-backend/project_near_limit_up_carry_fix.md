---
name: project-near-limit-up-carry-fix
description: SPEC-AI-023 detect_near_limit_up_carries 밴드 협소 + market_cap NULL 배제 버그 수정 (2026-07-01)
metadata:
  type: project
---

`detect_near_limit_up_carries` (backend/app/services/surge_detector.py, SPEC-AI-023)에서 확인된 두 가지 구조적 커버리지 갭 수정.

**Why:** 프로덕션 DB 교차 검증으로 실제 급등 종목 다수가 이 탐지기에서 누락된 것을 확인. (1) `near_limit_up_min_pct=25.0`이 너무 좁아 15~24% 상승 종목이 배제됨. (2) `market_cap IS NOT NULL` 필터가 KOSPI 60.6%, KOSDAQ 65.3% 종목을 통째로 배제 — 남광토건, 일성건설 등 실제 미스 사례 확인.

**How to apply:**
- `NearLimitUpConfig.near_limit_up_min_pct`: 25.0 → 15.0 (near_limit_up_max_pct=29.99는 유지, 실제 상한가 30% 도달분과 분리 유지)
- `NearLimitUpConfig.max_stocks_to_check`: 500 → 1200 (NULL market_cap 종목이 nullslast()로 순위 뒤로 밀려도 도달 가능하도록 확대)
- candidate 쿼리: `.filter(Stock.market_cap.isnot(None))` 제거, `.order_by(Stock.market_cap.desc())` → `.order_by(nullslast(Stock.market_cap.desc()))`로 변경. `nullslast`는 `sqlalchemy`에서 import.
- `stocks.market_cap` NULL 자체(60%+ 미채움)는 별도의 훨씬 큰 크롤러/데이터 파이프라인 이슈로 **의도적으로 미해결 상태 유지** — 이 탐지기 한정 완화만 적용.
- [[project_surge_scoring]] SPEC-AI-014와 동일하게 이 탐지기도 `_fetch_price_change_sync`를 종목별 순차 HTTP 호출로 사용 — max_stocks_to_check 확대(500→1200)로 이 탐지기 자체 런타임이 약 2.4배 증가할 수 있음 (직렬 루프, 배치/동시성 없음). `_run_coverage_expansion` 내부에서 실행되며 전체 `run_surge_signal_generation` 잡(10:00/15:20 KST, 기존 예산 약 12-15분)의 일부. 두 스케줄 간 5시간20분 여유는 있으나, 총 잡 런타임이 20-25분을 초과할 조짐이 보이면 모니터링 필요.

## 테스트

`backend/tests/test_near_limit_up_carry.py`에 AC-013(18% 신규 포함), AC-014(NULL market_cap 후보 포함) 추가. AC-003/AC-011 기존 경계값 테스트를 완화된 15.0 기준으로 갱신. 14/14 통과.
