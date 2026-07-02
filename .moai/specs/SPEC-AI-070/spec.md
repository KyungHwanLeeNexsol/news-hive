---
id: SPEC-AI-070
version: 0.1.0
status: draft
created: 2026-07-02
updated: 2026-07-02
author: MoAI
priority: Medium
issue_number: 0
---

# SPEC-AI-070: 탐지기 기여도 검증 & 은퇴 제안 (Detector Contribution Validation & Retirement Proposal)

## HISTORY

- 2026-07-02 (v0.1.0): 최초 작성. 급등예측 근본원인 분석(2026-07-02, 최근 17개 평가일 중
  15일 TP=0)의 "Priority Low — 중장기 아키텍처" 액션 아이템을 SPEC화. 핵심 목표: **14개+
  탐지기 중 실제로 scannable 급등을 잡는 데 기여하는 탐지기와 신호만 희석시키는 탐지기를
  데이터로 구분**하고, 기여 없는 탐지기의 **은퇴 제안(사람 승인 게이트)** 을 생성한다.
  본 SPEC은 SPEC-AI-068(평가지표 재정의)의 scannable 라벨과 SPEC-AI-069(backtest 운영
  게이트)의 by_combination 통계 위에서 동작하는 **측정·리포트 전용 계층**이다.
  - **사용자 확정 결정 2건 (2026-07-02, 권장안 승인)**:
    - (D1) 기여도 스냅샷 저장 = **신규 테이블 `surge_detector_contribution`**
      `{run_date, detector, emission_count, solo_count, solo_tp, coincident_hit_rate,
      unique_catch, retire_candidate}`.
    - (D2) REQ-AI070-005(룰기반→학습형 앙상블 타당성 평가) = **포함** — 리포트/문서 생성까지만,
      모델 학습·배포·온라인 가중치 변경 없음.
  - **코드 확정 진단 (2026-07-02)**:
    - **by_combination은 이미 존재**: `compute_surge_backtest`(`surge_backtest.py:82-118`)가
      `surge_basis` 조합별 `{count, accuracy, avg_return}`를 산출하고, SPEC-AI-069가 이를
      `surge_backtest_result.by_combination_json`(`surge_backtest_result.py:47`)로 이미 영속화.
      단, 이는 **조합(combination) 단위 + 방향성 5일 정확도**(`price_after_5d > price_at_signal`,
      `surge_backtest.py:90`)이지 **단일 탐지기 한계기여도**도, **scannable 모집단 기준**도 아니다.
      → 070은 068 scannable 라벨 위에 단일 탐지기 기여도를 NEW로 얹고, by_combination은
      은퇴 backtest 시뮬레이션의 입력으로 재사용한다.
    - **앙상블 weighted_sum 편입 탐지기는 7개**(`compute_ensemble_score`
      `surge_detector.py:1553-1564`): theme_cluster(0.19), volume_news_combo(0.25),
      disclosure_pattern(0.14, =max(pattern, immediate)), legacy_detectors(**0.00**),
      news_delayed(0.11), volume_breakout(0.11), momentum_continuation(0.12).
    - **`weekend_gap_up` 가중치(0.08, `surge_detection.yaml:72`)는 죽은 config**: weighted_sum에
      항이 없고(`surge_detector.py:1553-1564`), 오직 standalone bypass로만 발신
      (`detect_weekend_gap_up_signals` `surge_detector.py:3439`, surge_basis=["weekend_gap_up"]
      `:3535`). 그러나 `validate_ensemble_weights` 합=1.0에는 계속 포함되므로 yaml에서 단순
      제거하면 검증자가 깨진다.
    - **`legacy_detectors`는 가중치 0.00이라 weighted_sum 기여가 0이지만**, `active_detectors`에
      여전히 추가되고(`:2004-2005`) `detector_groups["technical"]`(`:1574`)에 속해 nonzero
      legacy_score가 **consensus multiplier(×1.30/×1.55, `:1579-1591`)를 밀어올릴 수 있다** —
      즉 "기여도"는 가중치만이 아니라 consensus 그룹 멤버십 + standalone 발신의 합이다.
    - **탐지기별 component score는 영속화되지 않음**: FundSignal은 최종 `surge_probability_score`
      + `surge_basis` 리스트만 `surge_metadata` JSON에 저장 → "탐지기 D를 빼고 재채점"하는 정밀
      counterfactual은 사후 재구성 불가. 기여도는 `surge_basis` 멤버십 × 결과 attribution으로
      한정한다.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

본 SPEC은 **측정·리포트·제안 전용**이다. 신규 탐지기·매매 로직·유니버스 구성·신호 생성 경로를
만들지 않으며, 사람 승인 없이 어떤 탐지기도 자동으로 제거/비활성화하지 않는다. 각 항목은
2026-07-02 코드 재확인 결과다.

- **SPEC-AI-068 (평가지표 재정의 & 유니버스 진단) — [HARD] 선행 의존**: 본 SPEC의 기여도는
  068이 신설한 `SurgeActualOutcome.surge_type=="scannable"` 라벨과 `surge_universe_members`
  테이블(`get_universe_members_for_date`, `surge_universe_pool_service.py:170`) 위에서만
  계산된다. 구현 순서 **068 → 070**.
- **SPEC-AI-069 (backtest 운영 게이트 & 자동개선 거버넌스) — [HARD] 선행 의존**: 은퇴 제안의
  backtest 검증(REQ-003)은 069가 스케줄러에 편입한 `compute_surge_backtest`/`run_backtest_gate`
  결과와 `surge_backtest_result.by_combination_json`을 재사용한다. auto-removal 금지(REQ-004)는
  069의 auto-improve 전면 중단 + HITL 거버넌스 패턴과 일관된다. 구현 순서 **069 → 070**.
- **SPEC-AI-041 (자동평가·자가개선 루프) — 확장(비충돌)**: 평가 잡
  `evaluate_surge_predictions`(`surge_evaluation_service.py:482`, 18:30 KST)를 재사용하되, 본
  SPEC은 **기여도 지표를 추가 산출·리포트**할 뿐 가중치/임계값 자동조정 로직은 건드리지 않는다.
  auto-improver에 탐지기 추가/제거 능력을 부여하지 않는다.
- **SPEC-AI-065 (z-score 상대채점 + 유니버스 확장) — 불변**: 오프라인 로지스틱 회귀 시드가
  이미 존재(prior art). REQ-005의 학습형 타당성 평가는 이 prior art를 참조하되 **평가 리포트
  까지만** 산출하고 모델을 학습·배포하지 않는다.
- **SPEC-AI-043 (예측기록 모드) — 불변**: 실매매 비활성·예측 기록 패러다임을 그대로 유지한다.
  본 SPEC은 측정·리포트만 다루므로 자금·매수 로직과 무관하다(매수 로직 diff 0).

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, APScheduler(KST 직접 지정), Alembic
  (앱 시작 시 자동 마이그레이션).
- DB: PostgreSQL 16. numpy/scipy/sklearn 부재 — 기여도 계산 및 학습형 타당성 평가는 **순수
  파이썬**으로만 구현.
- 스케줄러: 평가 잡은 18:30 KST `_run_surge_verify_predictions`, backtest 게이트 잡(069)은
  18:45 KST `surge_backtest_gate`. 기여도 계산 잡은 평가 이후 시점에 편입(래퍼 관례
  SessionLocal+asyncio.run).
- 운영 모드: 예측기록 전용(실매매 비활성). 자금 리스크 없음. 순수 알고리즘 품질 과제.
- 마이그레이션 head: SPEC-AI-068이 065를, SPEC-AI-069가 066을 각각 down_revision으로 사용했을
  가능성이 높아 **067이 다음 head가 될 것으로 추정**되나, 하드코딩하지 않는다. 신규 마이그레이션
  번호와 `down_revision`은 **RUN 단계에서 실제 head를 재확인 후 확정**한다.

---

## Requirements (EARS)

### REQ-AI070-001 (P0, Event-Driven) — 탐지기별 기여도 계산 (scannable 모집단 기준)

**WHEN** 일별 평가(18:30 KST)가 완료되면, **the system SHALL** 각 탐지기 D에 대해 롤링 윈도(W
거래일) 기준 아래 기여도 지표를 계산해야 한다:

- **emission_count(D)** = `surge_basis`에 D가 포함된 시그널 수.
- **solo_count(D)** = `surge_basis == [D]` (D 단독) 시그널 수.
- **solo_tp(D)** = 그 solo 시그널 중 T당일 **scannable 실제급등주**(068 라벨)에 적중한 수.
- **coincident_hit_rate(D)** = D가 낀 모든 시그널 중 scannable 적중 비율.
- **unique_catch(D)** = D 단독으로만 잡힌 scannable 실제급등 종목 수(= "D 은퇴 시 잃는 TP").

계산 기반:
- `FundSignal.surge_metadata.surge_basis`(= `candidate.active_detectors`,
  `surge_detector.py:2299`) → 어떤 탐지기가 발동했는지.
- `SurgeActualOutcome.surge_type=="scannable"` + `get_universe_members_for_date`(068) 교집합
  → 정답 집합(scannable 모집단).
- FundSignal→Stock.stock_code 조인으로 종목 매칭(FundSignal에 stock_code 컬럼 없음).
- **[HARD]** 신호 생성 경로(`compute_ensemble_score`/`gather_surge_candidates`/
  `build_scan_universe`)는 변경하지 않는다 — 확정된 결과만 사후 집계.

### REQ-AI070-002 (P0, Event-Driven) — 기여도 롤링 스냅샷 영속화 + 리포트

**WHEN** REQ-001의 기여도가 계산되면, **the system SHALL** 이를 신규 테이블
`surge_detector_contribution` `{run_date, detector, emission_count, solo_count, solo_tp,
coincident_hit_rate, unique_catch, retire_candidate}`에 탐지기당 1행씩 영속화하고, 리포트
(텔레그램/로그, 선택적 조회 엔드포인트)로 노출해야 한다.

- 대상은 앙상블 weighted_sum 편입 탐지기(7개)뿐 아니라 **standalone/bypass 탐지기 및 0-가중치
  탐지기 전부**를 포함한다.
- 리포트는 각 탐지기를 **(a) 앙상블 weighted_sum 편입, (b) standalone/bypass 발신, (c) 0-가중치**
  로 분류하여 표기해야 한다 — 특히 `weekend_gap_up`의 죽은 가중치(0.08이나 weighted_sum 미반영)와
  `legacy_detectors`(0.00 가중치이나 consensus 그룹 기여)의 뉘앙스를 명시적으로 표면화한다.

### REQ-AI070-003 (P1, State-Driven) — backtest 검증된 은퇴 제안 생성

**WHILE** 한 탐지기의 롤링 기여도가 설정된 floor 미만인 상태이면(예: `unique_catch == 0`
AND `solo_tp == 0` 이 충분한 윈도 ≥N 거래일 AND ≥min_signals 동안 지속), **the system SHALL**
해당 탐지기의 **은퇴 제안(retirement proposal)** 을 생성해야 하며, 그 제안은 SPEC-AI-069식
backtest 시뮬레이션으로 검증된 before/after 판정을 포함해야 한다.

- 검증 방법: `compute_surge_backtest().by_combination`에서 해당 탐지기가 포함된 조합을 식별하고,
  그 탐지기 solo 신호를 제외한 잔여 신호 집합의 directional accuracy(및 scannable 지표)를
  재계산하여 **은퇴가 정확도를 하락시키지 않음**을 검증한다.
- `retire_candidate` 플래그(REQ-002 테이블)는 floor 미달 + backtest 검증 통과를 함께 만족할
  때만 true로 기록한다.
- **[HARD]** 제안 생성까지만 — 어떤 config도 자동으로 쓰지 않는다(REQ-004로 이어짐).

### REQ-AI070-004 (P0, Unwanted Behavior) — auto-removal 금지 + 사람 승인 게이트

**IF** 은퇴 제안이 생성되면, **THEN the system SHALL NOT** `surge_detection.yaml`,
`surge_detection.auto.yaml`을 자동으로 수정하거나 어떤 탐지기도 자동으로 비활성화해서는 안 된다.

- 가중치 0 처리(앙상블 편입 탐지기) 또는 `enabled=false`(standalone 탐지기)는 제안 리포트를
  검토한 **운영자가 커밋된 base `surge_detection.yaml`을 수동 편집**해야만 적용된다.
- **[HARD]** `surge_auto_improver`에 탐지기 추가/제거 능력을 부여하지 않는다(가중치 수치 미세조정은
  SPEC-AI-069 backtest 가드가, 탐지기 add/remove는 어떤 자동 경로도 소유하지 않음).
- **[HARD]** 앙상블 편입 탐지기를 가중치 0 처리하거나 yaml에서 제거할 경우 잔여 가중치 합이
  1.0을 벗어나 `validate_ensemble_weights`가 깨지므로, 리포트는 **"제거 시 잔여 가중치 재정규화
  필요"** 경고와 재정규화 예시를 반드시 포함해야 한다.

### REQ-AI070-005 (P1, Optional/Where) — 룰기반→학습형 앙상블 타당성 평가 (리포트 전용)

**WHERE** 충분한 기여도·backtest 이력이 축적된 상태이면, **the system SHALL** 학습형 앙상블
(영속화된 탐지기-발화 피처 위 오프라인 로지스틱 가중)이 현행 룰기반 고정 가중치 대비 scannable
정확도를 능가할지에 대한 **타당성 평가 리포트/문서**를 산출해야 한다.

- 평가 전용: **모델 학습·배포·온라인 가중치 변경 없음**. AI-065의 1회성 오프라인 로지스틱 시드가
  prior art로 참조되나, 본 SPEC은 실제 모델을 운영에 연결하지 않는다.
- 리포트는 최소한 (a) 현행 룰기반 대비 예상 이득/손실 추정, (b) 데이터 충분성 판단, (c) 다음
  단계(별도 후속 SPEC 필요 여부) 권고를 포함한다.

---

## Exclusions (What NOT to Build) [HARD]

1. **신규 탐지기 추가 금지** — 본 SPEC은 기존 탐지기의 기여도를 측정할 뿐 새 탐지기를 만들지 않는다.
2. **승인 없는 자동 탐지기 제거/비활성화 금지** — `surge_detection.yaml`/`surge_detection.auto.yaml`
   자동 수정 금지. 가중치 0/`enabled=false`는 사람의 수동 base yaml 편집으로만 적용.
3. **파라미터/가중치 미세조정 금지** — 그건 SPEC-AI-069 backtest 가드 영역. 070은 기여도 측정 +
   은퇴 제안 리포트만.
4. **룰기반→학습형 전환은 타당성 평가(REQ-005)까지만** — 실제 모델 학습·배포·온라인 가중치 변경은
   범위 밖(필요 시 별도 후속 SPEC).
5. **신호 생성 경로 무변경** — `compute_ensemble_score`, `gather_surge_candidates`,
   `build_scan_universe`는 불변(068과 동일한 측정 전용 철학).
6. **SPEC-AI-065/068/069 재작성 금지** — 유니버스 구성(065), Scannable Recall/Coverage 지표
   계산(068), backtest 게이트·자동개선 거버넌스(069)는 **소비만** 하고 재구현하지 않는다.
7. **실매매·포트폴리오 로직 변경 금지** — SPEC-AI-043 예측기록 모드 유지(매수 로직 diff 0).
8. **component-score 영속화 범위 밖** — 탐지기별 세부 점수 저장은 신호 생성 경로 write 변경을
   유발하므로 제외. 기여도는 `surge_basis` 멤버십 attribution으로 한정하며, 정밀 재채점
   counterfactual 불가를 명시적 한계로 수용한다.

---

## Success Criteria

- 신규 테이블 `surge_detector_contribution`이 존재하고, 평가 이후 잡이 탐지기당 1행씩 롤링
  기여도(emission/solo/solo_tp/coincident_hit_rate/unique_catch/retire_candidate)를 채운다(REQ-001/002).
- 리포트가 모든 탐지기를 (weighted_sum 편입 / standalone / 0-가중치)로 분류 표기하고,
  `weekend_gap_up` dead-weight와 `legacy_detectors` consensus 기여 뉘앙스를 표면화한다(REQ-002).
- floor 미달 탐지기에 대해 069 backtest로 검증된 은퇴 제안이 생성되고, before/after 판정이
  리포트에 포함된다(REQ-003).
- 어떤 경우에도 시스템이 yaml/auto.yaml을 자동 수정하지 않으며, 은퇴는 사람 수동 편집으로만
  적용됨이 테스트로 보장된다(REQ-004).
- 학습형 앙상블 타당성 평가 리포트가 산출된다(REQ-005).
- 신규/변경 로직 테스트 커버리지 85%+, `ruff`/`mypy` 무경고, 전체 급등 스위트 회귀 없음.
- 예측기록 모드 불변(매수 로직 diff 0), 신호 생성 경로 diff 0.
