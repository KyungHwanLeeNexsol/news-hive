# SPEC-AI-051 (Compact): 급등주 탐지 커버리지 확장 3종

id: SPEC-AI-051 | version: 1.0.0 | status: draft | priority: high

## 한 줄 요약

3개 독립 기능으로 급등 탐지 공백 보완: (1) 볼린저 밴드 스퀴즈 탐지기 — 트리거 없는 기술적 압축 급등 포착, (2) 공시 키워드 Tier 배수 — 고가치 공시 과소평가 교정, (3) 14:30 KST 갭상승 런너 — 당일 리더의 섹터 2/3등 종목을 익일 갭상승 후보로 등록. DB 마이그레이션 불요, 기존 탐지기 가중치 무변경.

## 요구사항 (EARS)

### M1: 볼린저 밴드 스퀴즈 (Feature 1)
- **REQ-AI051-001**: `SurgeCandidate`에 `squeeze_score: float = 0.0` 필드 추가(기존 필드·기본값 무변경).
- **REQ-AI051-002**: When `detect_bollinger_squeeze_signals(db, config)` 호출 시, 각 활성 종목 60+ 거래일 종가(`fetch_stock_price_history_sync(pages≥6)`)로 BandWidth=(BB상단−BB하단)/BB중심(period=20, `_bollinger_bands` 재사용) 계산 → 당일 BandWidth가 직전 60거래일 최저 이하인 종목을 스퀴즈 후보로 판정, `squeeze_score`(0.0~1.0 정규화) 채운 `SurgeCandidate` 반환. 데이터<60일 또는 `None` 반환 종목 제외.
- **REQ-AI051-003**: When 15:10 KST 신규 잡 트리거 시, `detect_bollinger_squeeze_signals` 실행. 15:20 `surge_signal_generate`보다 먼저 완료. 고유 잡 id.

### M2: 공시 키워드 Tier 배수 (Feature 2)
- **REQ-AI051-004**: 3개 Tier 사전 정의 — Tier1(×2.0): FDA 승인/세계 최초/독점 공급/최대주주 변경/국가전략기술/국책사업 선정. Tier2(×1.5): 공급계약 체결/지분 인수/합병/MOU 체결/수주(단독)/자사주 소각(50억+). Tier3(×1.2): 신제품 출시/신규 수주/매출 급증/계열사 지원.
- **REQ-AI051-005**: When `score_disclosure_impact()` base 산정 후, `report_name`+`ai_summary`에서 매칭 최고 Tier 1개 배수만 곱함(누적 금지) → 100 캡(기존 동작 보존).
- **REQ-AI051-006**: If 루틴 거버넌스 캡(5.0 고정 반환, `disclosure_impact_scorer.py:154`) 경로, then Tier 배수 미적용 → 5.0 반환.

### M3: 14:30 갭상승 런너 (Feature 3)
- **REQ-AI051-007**: When `detect_gap_up_runners(db, config)` 호출 시, 당일 FundSignal 중 `signal_type IN ('surge_candidate','immediate_disclosure')` AND `confidence>=0.75` 리더 조회 → 동일 `sector_id` 종목을 `market_cap` 내림차순 → 2/3등 피어(런너) 선정.
- **REQ-AI051-008**: While 런너 선정 중, `get_open_position(db, stock_code)`(`SurgeTrade.is_open`) 보유 종목 제외, `_fetch_price_change_sync()`로 현재가 주입.
- **REQ-AI051-009**: When 런너 확정 시, `signal="buy"`, `signal_type="gap_up_runners"`, `confidence=leader.confidence*0.7`, `reasoning="오늘 [리더명] +X% 급등 테마 2/3등 종목, 익일 갭상승 저격"`, `surge_metadata.surge_basis=["gap_up_runners"]`, `price_at_signal=<현재가>`로 FundSignal 생성(`stock_id` 기준). DB 마이그레이션 불요.
- **REQ-AI051-010**: When 14:30 KST 신규 잡(Mon-Fri) 트리거 시, `detect_gap_up_runners` 실행. 익일 09:05 픽업 위해 `early_entry_check()`(`preday_signal_service.py`) signal_type 필터를 `gap_up_runners` 포함하도록 확장 또는 전용 소비자 추가(현행 필터는 `preday_disclosure`만 → 자동 픽업 불가). 14:30 시그널은 익일 전용 → BUY_CUTOFF 무충돌.

## 인수 기준 (요약)

- AC-051-01: 60일 최저 BandWidth 종목 → squeeze_score ≥ 0.5
- AC-051-02: 밴드 확장 종목 → 결과 미포함
- AC-051-03: <60일 데이터 종목 → 예외 없이 스킵
- AC-051-04: "FDA 승인" → ×2.0 적용
- AC-051-05: "공급계약 체결" → ×1.5 적용(Tier1 미적용)
- AC-051-06: Tier1+Tier3 동시 → ×2.0만(누적 금지) + ≤100
- AC-051-07: 루틴 거버넌스 → 5.0 그대로(배수 면제)
- AC-051-08: 리더 confidence 0.80 → 섹터 2/3등 gap_up_runners conf≈0.56
- AC-051-09: 2등 이미 오픈 SurgeTrade → 미생성, 3등 대체
- AC-051-10: 익일 09:05 early_entry_check가 gap_up_runners 픽업
- AC-051-11: 14:30 당일 신규 SurgeTrade 0건(BUY_CUTOFF 무충돌)
- 회귀: `cd backend && uv run pytest tests/ -m "not slow"`

## Delta Markers

- [MODIFY] `surge_detector.py` — `SurgeCandidate.squeeze_score` 추가, `detect_bollinger_squeeze_signals()` 신규, `detect_gap_up_runners()` 신규.
- [MODIFY] `technical_indicators.py` — `calculate_bollinger_bandwidth_squeeze()` 신규(`_bollinger_bands` 무변경 재사용).
- [MODIFY] `disclosure_impact_scorer.py` — Tier1/2/3 사전 + `score_disclosure_impact()` 배수 로직.
- [MODIFY] `scheduler.py` — 15:10 스퀴즈 잡 + 14:30 런너 잡(고유 id).
- [MODIFY] `preday_signal_service.py` — `early_entry_check()` signal_type 필터 확장.
- [NEW] `backend/tests/` — 스퀴즈/Tier/런너 단위 테스트.

## 제외 범위 (What NOT to Build)

- 실시간 틱/WebSocket(KIS OpenAPI) 미도입
- 14:30 당일 체결용 BUY_CUTOFF 변경 금지
- Tier 4/5 키워드 미추가
- 기존 탐지기 가중치 변경 금지(스퀴즈 가산만)
- DB 마이그레이션 미추가(`gap_up_runners`는 기존 `signal_type`, `squeeze_score`는 비영속)
- `SurgeTrade` P&L 컬럼 미추가
