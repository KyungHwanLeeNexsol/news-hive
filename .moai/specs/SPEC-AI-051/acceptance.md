# SPEC-AI-051 인수 기준 (Acceptance Criteria)

id: SPEC-AI-051 | version: 1.0.0 | status: completed | priority: high

각 시나리오는 Given-When-Then 형식이며, 마지막 열은 pytest 검증 방법을 나타낸다.

---

## Feature 1 — 볼린저 밴드 스퀴즈

### AC-051-01: 스퀴즈 탐지 (양성)

- **Given**: 직전 60거래일 BandWidth 시계열에서 당일 BandWidth가 60일 최저값 이하인 종목의 일봉 데이터(60+ 거래일, 최신순)
- **When**: `detect_bollinger_squeeze_signals(db, config)`를 실행한다
- **Then**: 해당 종목이 결과에 포함되고, 반환된 `SurgeCandidate.squeeze_score >= 0.5`이다
- **검증**: 60거래일 합성 일봉(말미 변동성 수축)을 고정한 단위 테스트. `naver_finance.fetch_stock_price_history_sync` mock

### AC-051-02: 스퀴즈 비탐지 (음성)

- **Given**: 당일 BandWidth가 60일 최저값보다 큰(밴드 확장 상태) 종목의 일봉 데이터
- **When**: `detect_bollinger_squeeze_signals(db, config)`를 실행한다
- **Then**: 해당 종목은 결과에 포함되지 않는다
- **검증**: 변동성 확장 합성 일봉 단위 테스트. 결과 리스트에 stock_code 부재 assert

### AC-051-03: 데이터 부족 종목 제외

- **Given**: 60거래일 미만 일봉만 보유한 종목(신규 상장/거래정지) — `_bollinger_bands`가 `None` 반환
- **When**: `detect_bollinger_squeeze_signals(db, config)`를 실행한다
- **Then**: 해당 종목은 예외 없이 스킵되고 결과에 포함되지 않으며, 다른 종목 처리는 계속된다
- **검증**: 30거래일 일봉 mock + 정상 종목 혼합. 정상 종목만 결과 포함 assert

---

## Feature 2 — 공시 키워드 Tier 배수

### AC-051-04: Tier 1 키워드 (×2.0)

- **Given**: `report_name`에 "FDA 승인"을 포함하는 공시(base 점수 산정 가능)
- **When**: `score_disclosure_impact(disclosure, market_cap_億)`로 점수를 계산한다
- **Then**: 최종 점수 = min(base × 2.0, 100). Tier 1 배수가 적용된다
- **검증**: 동일 base의 키워드 무/유 공시 2건 비교. 유 점수 == min(무 점수 × 2.0, 100) assert

### AC-051-05: Tier 2 키워드 (×1.5)

- **Given**: `report_name`에 "공급계약 체결"을 포함하고 Tier 1 키워드는 없는 공시
- **When**: `score_disclosure_impact(disclosure, market_cap_億)`로 점수를 계산한다
- **Then**: 최종 점수 = min(base × 1.5, 100). Tier 2 배수만 적용(Tier 1 미적용)
- **검증**: Tier 2 단독 키워드 공시 단위 테스트. 배수 1.5 assert

### AC-051-06: 최고 Tier 우선 + 100 캡 (누적 금지)

- **Given**: Tier 1("세계 최초")과 Tier 3("신제품 출시")을 모두 포함하는 공시
- **When**: `score_disclosure_impact(disclosure, market_cap_億)`로 점수를 계산한다
- **Then**: 최고 Tier(×2.0)만 적용되고 ×1.2는 누적되지 않으며, 최종 점수는 100을 초과하지 않는다
- **검증**: 다중 Tier 키워드 공시. 배수 == 2.0 (2.0×1.2 아님) + ≤ 100 assert

### AC-051-07: 루틴 거버넌스 배수 면제

- **Given**: "정기주주총회결과" 등 루틴 거버넌스 공시(5.0 고정 반환 경로)이면서 Tier 키워드도 우연히 포함
- **When**: `score_disclosure_impact(disclosure, market_cap_億)`로 점수를 계산한다
- **Then**: 최종 점수는 5.0 그대로이며 Tier 배수가 적용되지 않는다
- **검증**: 루틴 키워드 공시 단위 테스트. 반환 == 5.0 assert

---

## Feature 3 — 14:30 갭상승 런너

### AC-051-08: 런너 시그널 생성

- **Given**: 당일 생성된 리더 FundSignal(`signal_type="surge_candidate"`, `confidence=0.80`)과 동일 `sector_id`의 `market_cap` 내림차순 정렬 종목들(1~4등)
- **When**: 14:30 KST `detect_gap_up_runners(db, config)`를 실행한다
- **Then**: 섹터 2등·3등 종목에 `signal_type="gap_up_runners"`, `confidence = 0.80 * 0.7 = 0.56`, `surge_metadata.surge_basis=["gap_up_runners"]`, `price_at_signal` 채워진 FundSignal이 생성된다(익일 실행용)
- **검증**: 리더 시그널 + 섹터 종목 seed. 2/3등 stock_id에 대해 gap_up_runners 시그널 존재 + confidence ≈ 0.56 assert

### AC-051-09: 중복 런너 제외

- **Given**: 섹터 2등 런너 종목이 이미 오픈된 `SurgeTrade`(`is_open=True`)에 존재
- **When**: 14:30 KST `detect_gap_up_runners(db, config)`를 실행한다
- **Then**: 해당 종목에는 `gap_up_runners` 시그널이 생성되지 않고, 다음 순위(3등 등) 종목이 대신 선정된다
- **검증**: `get_open_position` mock/seed로 2등 보유. 2등 미생성 assert

### AC-051-10: 익일 09:05 소비자 픽업

- **Given**: 전일 14:30에 생성된 `gap_up_runners` FundSignal
- **When**: 익일 09:05 KST `early_entry_check(db)`(필터 확장됨)를 실행한다
- **Then**: `gap_up_runners` 시그널이 조기 진입 후보로 조회된다(`preday_disclosure` 외 signal_type 픽업 확인)
- **검증**: `early_entry_check` signal_type 필터에 `gap_up_runners` 포함 후, gap_up_runners 시그널이 후보 집합에 포함 assert

### AC-051-11: BUY_CUTOFF 비충돌

- **Given**: 14:30(BUY_CUTOFF 11:00 이후) 실행 컨텍스트
- **When**: `detect_gap_up_runners(db, config)`를 실행한다
- **Then**: 시그널은 당일 체결되지 않고 익일(target_date=tomorrow) 대상으로만 기록되며, BUY_CUTOFF 위반 매수가 발생하지 않는다
- **검증**: 당일 SurgeTrade 신규 진입 0건 assert(예측 기록 모드 정합)

---

## 품질 게이트 (Quality Gate) / Definition of Done

- [ ] AC-051-01 ~ AC-051-11 전체 통과
- [ ] `SurgeCandidate.squeeze_score` 필드 추가, 기존 필드 무변경
- [ ] Tier 배수는 공시당 최고 1개만 적용 + 100 캡 + 루틴 면제
- [ ] `gap_up_runners` 시그널이 익일 09:05 소비자에서 픽업됨(필터 확장 확인)
- [ ] 기존 `EnsembleWeightsConfig` 4개 가중치 무변경(스퀴즈 가산만)
- [ ] DB 마이그레이션 미추가 확인
- [ ] 신규 스케줄러 잡 id가 기존과 충돌하지 않음
- [ ] 기존 회귀 테스트 전체 통과: `cd backend && uv run pytest tests/ -m "not slow"`
