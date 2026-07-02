# SPEC-AI-070 Acceptance Criteria

Given-When-Then 시나리오와 엣지케이스. 모든 기준은 관찰 가능(테이블 행/플래그 값/리포트 문자열/
테스트 출력)해야 하며, 신호 생성 경로와 매수 로직 diff는 0이어야 한다.

---

## AC-070-001 (REQ-001/002) — 기여도 계산 정확성 & 영속화

**Given** T-1 스캔 유니버스가 영속화되어 있고(068 `surge_universe_members`), T당일 실제급등주가
scannable/non_scannable로 라벨링되어 있으며, T-1에 다음 surge_candidate 시그널이 있다:
- 종목 A: `surge_basis == ["volume_news_combo"]` (단독), A는 T당일 scannable 급등 적중
- 종목 B: `surge_basis == ["theme_cluster", "volume_news_combo"]` (조합), B는 scannable 급등 적중
- 종목 C: `surge_basis == ["momentum_continuation"]` (단독), C는 급등 실패

**When** 평가 이후 기여도 계산 잡이 실행되면

**Then**:
- `surge_detector_contribution` 테이블에 해당 run_date 기준 탐지기당 1행이 적재된다.
- `volume_news_combo`: `emission_count=2`, `solo_count=1`, `solo_tp=1`, `unique_catch>=1`(A).
- `theme_cluster`: `emission_count=1`, `solo_count=0`, `solo_tp=0` (조합으로만 참여).
- `momentum_continuation`: `emission_count=1`, `solo_count=1`, `solo_tp=0`, `unique_catch=0`.
- `coincident_hit_rate`는 해당 탐지기가 낀 시그널 중 scannable 적중 비율로 계산된다.
- 신호 생성 경로(`compute_ensemble_score`/`gather_surge_candidates`/`build_scan_universe`) diff 0.

---

## AC-070-002 (REQ-002) — dead-weight & consensus 뉘앙스 표면화

**Given** `weekend_gap_up`이 yaml 가중치 0.08을 가지나 `compute_ensemble_score` weighted_sum에
미반영(standalone bypass만)이고, `legacy_detectors`가 가중치 0.00이나 consensus 그룹 "technical"에
속한 상태

**When** 기여도 리포트가 생성되면

**Then**:
- 리포트가 각 탐지기를 **(a) 앙상블 weighted_sum 편입 / (b) standalone·bypass 발신 / (c) 0-가중치**
  로 분류 표기한다.
- `weekend_gap_up`은 "standalone (yaml weight 0.08 = weighted_sum 미반영, dead config)"로 명시된다.
- `legacy_detectors`는 "weighted_sum 가중치 0.00, consensus 그룹 technical 기여 가능"으로 명시된다.
- 리포트에 두 탐지기가 "무기여"로 단순 오분류되지 않는다.

---

## AC-070-003 (REQ-003/004) — backtest 검증된 은퇴 제안 & auto-removal 금지

**Given** 탐지기 `forum_mention_surge`가 충분한 윈도(≥N 거래일, ≥min_signals) 동안
`unique_catch == 0` AND `solo_tp == 0` 이고, 이 탐지기 solo 신호를 제외해도
`compute_surge_backtest().by_combination` 기반 directional accuracy가 하락하지 않는 상태

**When** 은퇴 제안 로직이 실행되면

**Then**:
- 해당 탐지기의 `retire_candidate` 플래그가 true로 기록된다.
- 리포트에 은퇴 제안 + backtest before/after 판정(accuracy 하락 없음)이 포함된다.
- **[HARD]** `surge_detection.yaml` / `surge_detection.auto.yaml` 파일이 **수정되지 않는다**
  (테스트가 두 파일의 mtime/내용 불변을 검증).
- 앙상블 편입 탐지기가 은퇴 대상이면 리포트에 **잔여 가중치 재정규화 예시**가 포함된다.
- `surge_auto_improver`가 탐지기를 제거/비활성화하는 코드 경로가 존재하지 않는다.

---

## AC-070-004 (REQ-005) — 학습형 앙상블 타당성 평가 리포트

**Given** 기여도·backtest 이력이 충분히 축적된 상태

**When** 타당성 평가 로직이 실행되면

**Then**:
- 학습형 앙상블(오프라인 로지스틱, 순수 파이썬) vs 현행 룰기반 고정 가중치의 예상 이득/손실
  추정 리포트가 산출된다.
- 리포트에 데이터 충분성 판단 + 다음 단계 권고(별도 후속 SPEC 필요 여부)가 포함된다.
- **모델이 운영에 연결되지 않는다** — yaml 가중치 diff 0, 신호 생성 경로 diff 0.

---

## 엣지케이스

- **EC-1 표본 부족**: 배포 초기 또는 저거래일에 특정 탐지기의 `emission_count`가 min_signals
  미만이면 `retire_candidate`는 false로 유지된다(표본 부족으로 인한 오탐 은퇴 방지). 리포트는
  "표본 부족(insufficient sample)"으로 표기한다.
- **EC-2 scannable 분모 0**: 해당 run_date에 scannable 실제급등주가 0이면 hit_rate 계열 지표는
  `null`(측정 불가)로 저장하고, 이를 실패로 간주하지 않는다.
- **EC-3 유니버스 부재(과거 날짜)**: 068 유니버스가 영속화되지 않은 과거 날짜는 scannable
  attribution이 불가하므로 해당 날짜는 롤링 윈도에서 제외한다(068 배포일 이후만 유효 윈도).
- **EC-4 weekend_gap_up dead-weight 은퇴 권고**: weekend_gap_up이 은퇴 후보로 판정되어도, 리포트는
  yaml 단순 제거 시 `validate_ensemble_weights` 합=1.0이 깨짐을 경고하고 재정규화(또는 standalone
  경로 `enabled=false`만) 방법을 제시한다.
- **EC-5 legacy_detectors 0-가중치 + consensus 기여**: legacy가 weighted_sum 기여 0이지만
  `unique_catch > 0`(consensus multiplier로 다른 신호를 임계 위로 밀어 올려 잡힌 케이스)이면
  `retire_candidate`는 false로 유지되고, 리포트는 "consensus 기여로 은퇴 부적합"을 명시한다.
- **EC-6 component score 부재로 인한 근사 한계**: 특정 시그널의 surge_basis에 여러 탐지기가 있으나
  component score를 재구성할 수 없어 정밀 한계기여를 산출할 수 없는 경우, attribution은 멤버십
  기준으로만 계산하고 이 한계를 리포트 각주로 명시한다.
- **EC-7 텔레그램 미설정**: `TELEGRAM_ADMIN_CHAT_ID`/토큰 미설정 시 `send_telegram_message`가
  graceful False를 반환하며, 리포트는 로그로만 남고 잡은 실패하지 않는다.

---

## Definition of Done

- [x] `surge_detector_contribution` 테이블 + Alembic 마이그레이션 존재(head는 RUN 단계 재확인 후 확정 — 067, down_revision=066).
- [x] 기여도 집계 서비스(순수 파이썬)가 5개 지표를 정확히 산출(AC-070-001).
- [x] 리포트가 탐지기 3분류 + dead-weight/consensus 뉘앙스를 표면화(AC-070-002).
- [x] backtest 검증된 은퇴 제안 + `retire_candidate` 플래그(AC-070-003).
- [x] 시스템이 yaml/auto.yaml을 자동 수정하지 않음이 테스트로 보장(AC-070-003 [HARD]).
- [x] 학습형 타당성 평가 리포트 산출(AC-070-004), 모델 운영 미연결.
- [x] 모든 엣지케이스(EC-1~EC-7) 테스트 커버.
- [x] 테스트 커버리지 85%+(93%), `ruff check` 무경고 / `mypy` 로컬 미설치로 스킵, 전체 급등 스위트 회귀 없음(1813 passed).
- [x] 신호 생성 경로 diff 0, 매수 로직 diff 0(예측기록 모드 불변).
