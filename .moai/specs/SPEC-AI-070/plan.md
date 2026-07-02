# SPEC-AI-070 Implementation Plan

## 기여도 정의 (설계 근거)

**핵심 제약**: 탐지기별 component score(theme_cluster_score 등)는 영속화되지 않는다. FundSignal은
최종 `surge_probability_score` + `surge_basis` 리스트만 `surge_metadata` JSON에 저장하므로(코드
확정 2026-07-02), "탐지기 D를 빼고 재채점"하는 정밀 counterfactual은 사후 재구성이 불가능하다.
따라서 기여도는 **`surge_basis` 멤버십(어떤 탐지기가 발동했는가) × scannable 결과(068 라벨)**
의 attribution으로 정의한다 — 이는 068과 동일한 측정 전용 철학을 따르며 신호 생성 경로를 전혀
건드리지 않는다.

탐지기 D, 롤링 윈도 W(거래일), scannable 모집단(068 `surge_type=="scannable"` ∩ T-1 유니버스) 기준:

| 지표 | 정의 | 해석 |
|---|---|---|
| `emission_count(D)` | D ∈ surge_basis 시그널 수 | 0이면 즉시 은퇴 후보(발신 자체가 없음) |
| `solo_count(D)` | surge_basis == [D] 수 | D 단독 발신 빈도 |
| `solo_tp(D)` | solo 시그널 중 scannable 적중 수 | D의 독립 예측력 |
| `coincident_hit_rate(D)` | D가 낀 전체 시그널 중 scannable 적중 비율 | D의 동반 적중 기여 |
| `unique_catch(D)` | D 단독으로만 잡힌 scannable 급등 종목 수 | "D 은퇴 시 잃는 TP" |

**은퇴 후보 판정** = `emission_count == 0` OR (`solo_tp == 0` AND `unique_catch == 0` 이 충분한
윈도 ≥N 거래일 AND ≥min_signals 동안 지속) — **그리고** 069 backtest 시뮬레이션 통과.

## 진입점 / 재사용 (신규 자산 최소화)

**재사용:**
- `evaluate_surge_predictions`(`surge_evaluation_service.py:482`, 18:30 KST) — 이미 predicted_set /
  actual_set / 유니버스 교집합 / scannable 라벨을 계산하는 지점. 기여도 attribution의 자연스러운
  위치. 여기서 hook 하거나 직후 별도 잡으로 실행.
- `get_universe_members_for_date`(`surge_universe_pool_service.py:170`) — T-1 유니버스 종목 집합.
- `SurgeActualOutcome.surge_type`(068) — scannable/non_scannable 라벨.
- `compute_surge_backtest().by_combination`(`surge_backtest.py:82-118`) — 은퇴 backtest 시뮬레이션
  입력(조합별 count/accuracy/avg_return). SPEC-AI-069가 이미 스케줄러 편입 + 영속화한 자산.
- FundSignal→Stock.stock_code 조인 패턴(FundSignal에 stock_code 컬럼 없음, 068에서 확립).

**신규 자산 (측정 계층):**
- 모델 `SurgeDetectorContribution`(테이블 `surge_detector_contribution`):
  `{id, run_date, detector, emission_count, solo_count, solo_tp, coincident_hit_rate,
  unique_catch, retire_candidate, created_at}`. run_date+detector 유니크. Alembic 마이그레이션 1건.
  **[HARD] 마이그레이션 번호와 `down_revision`은 RUN 단계에서 실제 head를 재확인 후 확정**한다
  (068→065, 069→066 사용 추정상 067이 다음 head로 보이나 하드코딩 금지).
- 서비스 `surge_contribution_service.py`(순수 파이썬, numpy/sklearn 금지):
  기여도 집계 + 은퇴 후보 판정 + backtest 검증 시뮬레이션.
- 리포터: 069 리포트 패턴 재사용(텔레그램 `send_telegram_message(chat_id, text,
  parse_mode="HTML")`, 토큰 미설정 시 graceful False; 로그). 선택적 조회 엔드포인트
  `GET /api/surge-trading/detector-contribution`.
- 학습형 타당성 평가(REQ-005): 순수 파이썬 오프라인 로지스틱(AI-065 시드 prior art 참조) →
  현행 룰기반 대비 예상 이득 추정 리포트. 모델을 운영에 연결하지 않음.
- 스케줄러 잡 1건: 평가/backtest 이후 시점(예: 19:00 KST) `surge_detector_contribution` 래퍼
  (SessionLocal+asyncio.run 관례, timezone="Asia/Seoul" 직접 지정, distinct id).

## 마일스톤 (우선순위 기반)

1. **(P0) 기여도 집계 + 영속화** — `SurgeDetectorContribution` 모델 + 마이그레이션 +
   `surge_contribution_service` 집계 로직(REQ-001/002). surge_basis × scannable attribution.
2. **(P0) 리포트 + dead-weight/consensus 표면화** — 탐지기 분류(weighted_sum/standalone/0-가중치)
   + weekend_gap_up·legacy 뉘앙스 명시(REQ-002).
3. **(P1) backtest 검증 은퇴 제안** — by_combination 재사용한 은퇴 시뮬레이션 + retire_candidate
   플래그(REQ-003).
4. **(P0) auto-removal 금지 가드 + HITL 문서화** — 어떤 config write도 하지 않음을 코드/테스트로
   보장 + 재정규화 경고(REQ-004).
5. **(P1) 학습형 타당성 평가 리포트** — 오프라인 로지스틱 이득 추정 리포트(REQ-005).

## human-approval 게이트 설계

SPEC-AI-069와 동일한 **"시스템은 근거+제안만, 사람이 config를 직접 변경"** 구조:

1. 시스템: 탐지기별 기여도 표 + backtest 검증된 은퇴 시뮬레이션을 **리포트로 생성·영속화**하고
   텔레그램/로그로 운영자에게 통지한다.
2. 리포트는 "탐지기 X 가중치 0.00 처리"(앙상블 편입) 또는 "standalone 탐지기 enabled=false"를
   **권고**하되, 시스템은 yaml을 절대 만지지 않는다.
3. 앙상블 편입 탐지기 은퇴 권고 시, 리포트는 **잔여 가중치 재정규화 예시**를 함께 제시한다
   (`validate_ensemble_weights` 합=1.0 보존).
4. 실제 적용: 운영자가 커밋된 base `surge_detection.yaml`을 **수동 편집** → SPEC-AI-069
   REQ-002/003(auto-improve 중단, 재활성은 사람 승인)과 정확히 일관.
5. `surge_auto_improver`는 탐지기 add/remove 능력을 절대 갖지 않는다(REQ-004 [HARD]).

## 롤아웃 전략 (측정 전용, 신호 생성 무변경)

본 SPEC은 신호 생성/매수 로직을 바꾸지 않으므로 신호 손실 위험은 없다. 단, 신규 테이블 +
신규 스케줄러 잡을 추가하므로 간단한 배포 확인 절차를 둔다:

1. **마이그레이션 head 재확인** — RUN 시작 시 실제 Alembic head 조회 후 신규 마이그레이션
   `down_revision` 확정(하드코딩 금지).
2. **백필 없이 전진(forward-only)** — 기여도는 롤링 윈도 기준이므로 배포 후 W 거래일이 축적되면
   지표가 유효해진다. 과거 날짜 재구성은 하지 않는다(068과 동일; surge_basis는 과거 시그널에도
   있으나 scannable 라벨은 068 배포 이후 날짜만 존재 → 유효 윈도는 068 배포일 이후로 한정).
3. **초기 관측 기간(shadow)** — 첫 N 거래일 동안은 은퇴 제안을 **관측/리포트만** 하고 어떤 수동
   조치도 취하지 않는다(retire_candidate가 표본 부족으로 왜곡되지 않도록 min_signals 게이트가
   방어).
4. **배포 확인** — 스케줄러 잡이 등록되었는지(잡 id 존재), 신규 테이블에 첫 run_date 행이 적재
   되는지, 리포트가 텔레그램/로그로 도달하는지 확인. 실패 시 잡은 예외를 삼키지 않고 로그로
   표면화(래퍼 try/except→raise/finally 관례).
5. **Deploy Guard** — 15:15~15:45 KST 자동 대기 창을 준수(기존 배포 파이프라인 관례).

## 리스크

- **component score 미영속화** → 기여도가 조합 attribution 근사에 그쳐 "D가 발동했으나 실제로는
  0.01만 기여" 같은 미세 기여를 구분하지 못한다. REQ-005 학습형 평가가 일부 보완하나, 정밀
  counterfactual을 원하면 별도 후속 SPEC에서 신호 생성 write(component 저장)를 논의해야 함 —
  070 범위 밖(Exclusion 8).
- **weekend_gap_up 죽은 가중치** — 리포트가 "기여 0"으로 표기 시, 운영자가 yaml에서 단순 제거하면
  `validate_ensemble_weights` 합이 깨진다 → REQ-004 [HARD]의 재정규화 경고로 방어.
- **069 선행 의존** — 은퇴 backtest 시뮬레이션은 069가 backtest를 스케줄러에 편입하고
  by_combination을 영속화한 뒤라야 신뢰 가능 → 구현 순서 068 → 069 → 070 엄수.
- **표본 부족 왜곡** — 배포 초기 또는 저거래일에 emission/solo가 극소수면 hit_rate가 불안정 →
  min_signals + ≥N 거래일 게이트로 retire_candidate 판정을 보수화.
- **legacy 0-가중치의 consensus 기여 은닉** — 리포트가 weighted_sum share만 보면 legacy를 "무기여"로
  오판할 수 있음 → consensus 그룹 멤버십을 별도 표기(REQ-002).
