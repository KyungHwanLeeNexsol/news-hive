## SPEC-AI-070 Progress

- Started: 2026-07-02 (follow-up to SPEC-AI-068/069 root-cause remediation)
- Dependency: SPEC-AI-068 (scannable_recall/coverage/surge_type) + SPEC-AI-069 (backtest gate, by_combination_json) both completed and committed (2e26696, 7d642ab, a553eb8 for the AI-023~026 bugfix batch).
- Phase 0.9: Python (backend/pyproject.toml) detected -> moai-lang-python
- Phase 0.95: ~7 files (model, migration, service, scheduler hook, router endpoint, test files) single domain (backend) -> Standard Mode
- Harness level: standard. Development mode: ddd (quality.yaml)
- SPEC/plan/acceptance approved by user (2026-07-02, second resume) with 2 confirmed decisions: (D1) new table surge_detector_contribution, (D2) REQ-005 included (report-only).

### Phase 1 (manager-spec) — Plan proposed, AWAITING USER APPROVAL (no response after 60s, paused)

manager-spec verified code and found 2 non-obvious facts to surface in the SPEC:
- `weekend_gap_up` has yaml weight 0.08 but is NOT actually in `compute_ensemble_score`'s weighted_sum (`surge_detector.py:1553-1564`) — it only fires via standalone bypass (`:3535`). The yaml weight is dead config that still counts toward `validate_ensemble_weights` sum=1.0 check.
- `legacy_detectors` has weight 0.00 (truly zero contribution to weighted_sum) but still counts toward `active_detectors` and `detector_groups["technical"]` membership (`:1574`), meaning it can still push the consensus multiplier (×1.30/×1.55) even at zero weight.

Detector classification (verified against code):
- 7 detectors in ensemble weighted_sum: theme_cluster 0.19, volume_news_combo 0.25, disclosure_pattern 0.14, legacy_detectors 0.00, news_delayed 0.11, volume_breakout 0.11, momentum_continuation 0.12
- 9 standalone/bypass detectors (own surge_basis, outside weighted_sum): weekend_gap_up, near_limit_up_carry, insider_purchase, theme_group_carry, forum_mention_surge, group_cascade, gap_up_runners, bollinger_squeeze, volume_anomaly

Contribution definition (since per-detector component scores are NOT persisted — only final surge_probability_score + surge_basis list in FundSignal.surge_metadata): use surge_basis membership × scannable-outcome attribution, not precise counterfactual re-scoring:
- emission_count(D), solo_count/solo_tp(D) — independent predictive power when D fires alone
- coincident_hit_rate(D) — TP rate across all signals D participates in
- unique_catch(D) — scannable actual surges caught ONLY by D (lost if D retired)
- Retirement candidate = emission==0 OR (solo_tp==0 AND unique_catch==0 over sufficient window), further validated via SPEC-AI-069's by_combination backtest simulation (exclude D's solo signals, check directional accuracy doesn't drop)

Proposed EARS (5 requirements, single SPEC — not split, all one linear measure→report→propose→gate→evaluate concern):
- REQ-AI070-001 (P0): compute rolling per-detector contribution metrics from surge_basis × scannable label × universe intersection, at 18:30 KST eval job. Zero change to signal-generation path.
- REQ-AI070-002 (P0): persist rolling snapshots + report (telegram/log), distinguishing weighted_sum-member / standalone / zero-weight detectors, explicitly surfacing the weekend_gap_up dead-weight and legacy_detectors consensus-membership nuances found above.
- REQ-AI070-003 (P1): when a detector's rolling contribution is below floor, generate a backtest-validated retirement PROPOSAL (via by_combination re-simulation, before/after verdict) — proposal only, no config write.
- REQ-AI070-004 (P0, HARD): system SHALL NOT auto-modify surge_detection.yaml/auto.yaml or auto-disable any detector. Retirement requires human manual edit of base yaml (consistent with SPEC-AI-069's auto-improve suspension + HITL governance). auto_improver must never gain detector add/remove capability.
- REQ-AI070-005 (P1): when sufficient contribution+backtest history accumulates, produce a feasibility EVALUATION (report only) on whether a learned ensemble (offline logistic regression over persisted detector-firing features) would outperform the current fixed rule-based weights — evaluation only, no model training/deployment/online weight change (AI-065's offline logistic seed is prior art).

Exclusions (8 items): no new detectors; no unapproved auto-removal; no parameter/weight tuning (that's SPEC-AI-069's backtest-gate territory); rule→learned transition is feasibility evaluation only (REQ-005), no training/deployment; signal-generation path unchanged (compute_ensemble_score/gather_surge_candidates/build_scan_universe untouched); no rewrite of 065/068/069 (universe construction/Scannable Recall/backtest gate — consume only); no trading/portfolio logic change (AI-043 prediction-record mode preserved); component-score persistence out of scope (would require signal-generation write change — contribution is limited to surge_basis attribution, precise counterfactual is an explicit accepted limitation).

Human-approval gate design: same "system proposes with evidence, human edits config directly" pattern as SPEC-AI-069 — system generates + persists a report recommending "detector X → weight 0.00" or "standalone detector Y → disabled", but never touches yaml itself. Report must also warn about ensemble-weight renormalization needed if a nonzero-weight detector is removed (since validate_ensemble_weights requires sum=1.0).

Reference files (absolute): `backend/app/services/surge_backtest.py` (by_combination logic already exists at `:82-118`, already persisted via SPEC-AI-069's `surge_backtest_result.by_combination_json`), `surge_detector.py` (`:1532` compute_ensemble_score, `:1553-1564` weighted_sum, `:3439` weekend_gap_up bypass), `surge_evaluation_service.py:482` (natural integration point — already computes predicted_set/actual_set/universe intersection), `surge_universe_pool_service.py:170` get_universe_members_for_date, `models/surge_actual_outcome.py` (surge_type), `models/surge_prediction_evaluation.py`, `models/surge_backtest_result.py`, `surge_config/surge_detection.yaml:53-75` (ensemble.weights).

Two open decisions asked via AskUserQuestion, no response yet:
1. Contribution snapshot storage: (A) new table `surge_detector_contribution` {run_date, detector, emission_count, solo_count, solo_tp, coincident_hit_rate, unique_catch, retire_candidate} — RECOMMENDED, matches SPEC-AI-068/069 pattern of dedicated tables, easy per-detector/per-date trend queries. vs (B) JSON column on SurgePredictionEvaluation — minimal migration but hard to query per-detector trends (would need to parse JSON every time).
2. Whether to include REQ-AI070-005 (learned-ensemble feasibility evaluation) in this SPEC (RECOMMENDED — low incremental cost, it's report-only, no model training) vs split it into a separate future SPEC (e.g. SPEC-AI-071) once more contribution/backtest history has accumulated, keeping 070 scoped purely to "rule-based detector cleanup".

**Resume instruction**: Re-ask these 2 questions via AskUserQuestion at the start of the next `/moai run SPEC-AI-070` or `/moai plan` continuation before proceeding to file creation (Phase 2). The plan content above is already verified against code (agentId a9eeaa12ad37a7d69 if still resumable) and doesn't need re-derivation — just the two storage/scope decisions need a user answer, then create spec.md/plan.md/acceptance.md per the standard 3-file SPEC structure.

---

### Phase 2 (manager-ddd) — DDD 구현 완료 (2026-07-02)

SPEC/plan/acceptance 승인 완료 후 ANALYZE-PRESERVE-IMPROVE 사이클로 T-001~T-008 전체 구현.

#### ANALYZE

- Alembic head 재확인: `067_surge_detector_contribution`이 이미 유일 head(down_revision=`066_surge_backtest_result`) — plan.md의 추정이 정확했음을 확인.
- 코드 재검증으로 spec.md 대비 3건의 추가 정정 사항 발견(EC-6 각주 및 T-003 리포트에 반영):
  1. `weekend_gap_up`: `detect_weekend_gap_up_signals()`의 dict 결과가 `fund_manager.py:4013` 주석("weekend_gap_up 결과는 dict 목록으로 반환 — FundSignal 미생성")에 따라 **FundSignal로 전혀 영속화되지 않음** — spec.md는 "standalone bypass로 발신"이라 서술했으나 실제로는 구조적으로 emission_count=0.
  2. `bollinger_squeeze`: `detect_bollinger_squeeze_signals()`가 SurgeCandidate를 계산하나 `gather_surge_candidates()`의 `merged` 딕셔너리에 병합되지 않고, 스케줄러 `_run_bollinger_squeeze_detect`도 로그만 남길 뿐 FundSignal을 생성하지 않음 — 구조적 emission_count=0.
  3. `gap_up_runners`: `detect_gap_up_runners()`가 FundSignal을 생성하되 `signal_type="gap_up_runners"`이지 `"surge_candidate"`가 아니므로, 068/070이 공유하는 predicted_set 필터(`signal_type=="surge_candidate"`) 밖에 위치 — 측정 범위에서 구조적으로 emission_count=0.
  4. (기존 확정 정정 유지) component score 5종은 부분 영속화됨(`surge_metadata`에 theme_cluster_score/combo_score/pattern_score/immediate_disclosure_score/legacy_score 저장) — standalone/bypass 탐지기 개별 점수는 미저장.
- `surge_auto_improver._parse_detector_contributions`(041)가 이미 유사한 5-탐지기 기여도 근사를 자체 목적(가중치 자동조정)으로 구현 중임을 확인 — 070은 이를 재사용하지 않고 독립 구현(요구 지표 셋이 다름: solo/unique_catch/backtest 검증 등 041에 없음).
- 탐지기 레지스트리 17개 항목으로 확정: 앙상블 편입 7(disclosure_pattern/immediate_disclosure 버킷 공유 포함 8개 surge_basis 리터럴) + 0-가중치 1(legacy) + standalone 활성 5 + standalone 구조적 0발신 4.

#### PRESERVE

- 기존 스위트 베이스라인 확인: `test_surge_evaluation_service.py` + `test_spec_ai_069.py` = 61 passed (구현 전).
- 구현 완료 후 동일 두 파일 재실행: 61 passed (diff 0, git diff로 두 파일 자체가 미수정임을 확인).
- 전체 백엔드 스위트(`pytest tests/ -m "not slow"`): 1813 passed, 4 skipped, 3 xpassed — 신규 회귀 없음(스케줄러 잡 카운트 테스트는 `>= 15` 상한 검증이라 신규 잡 추가에 영향받지 않음).

#### IMPROVE

- T-001: `SurgeDetectorContribution` 모델 + 마이그레이션 067(stub 채움) + `models/__init__.py` 등록 + `tests/conftest.py`(create_all 등록).
- T-002: `evaluate_detector_contribution(db, trading_date)` — evaluate_surge_predictions와 완전 분리된 신규 함수, T-1 surge_basis 파싱 × scannable attribution, 레지스트리 전체(17개) 1행씩 upsert.
- T-003/T-005: `build_contribution_report()` — 3분류(weighted_sum/standalone/0-가중치) + weekend_gap_up dead-weight/legacy consensus 각주 + EC-6 정정 각주 + 은퇴 제안 시 재정규화 예시(yaml_weight_key 보유 탐지기는 카테고리 무관하게 재정규화 안내 — weekend_gap_up EC-4 케이스 포함).
- T-004: `verify_retirement_via_backtest()` — `compute_surge_backtest().by_combination`에서 solo 조합 통계를 역산 제외한 잔여 accuracy 재계산(재구현 아님, fresh 호출 + 사후 집계). `assess_retirement_candidates()` — 롤링 윈도(기본 10거래일) + EC-1(표본부족)/EC-3(증거없는 날 제외) 가드.
- T-006: `assess_learned_ensemble_feasibility()` — 순수 파이썬 배치 경사하강 로지스틱(numpy/sklearn 미사용), 관측 30거래일 미만 시 불충분 리포트, 충분 시 in-sample 학습 정확도 vs 룰기반 실측 정밀도 비교 리포트(모델 미배포, held-out 검증 부재를 명시적 한계로 리포트에 기재).
- T-007: `scheduler.py`에 `_run_surge_detector_contribution()` 래퍼(기존 관례: `_is_kr_market_open` 가드 → `SessionLocal()` → try/except(`logger.exception; raise`) → finally) + 19:05 KST 평일 잡 등록(`surge_backtest_gate` 18:45, `surge_auto_improve` 19:00과 독립). 텔레그램 리포트는 `asyncio.run(send_telegram_message(...))`, `TELEGRAM_ADMIN_CHAT_ID` 미설정 시 로그만 남기고 정상 종료(EC-7). **조회 엔드포인트는 시간 제약으로 생략**(T-007 명시적 선택사항, P0 우선).
- T-008: `test_spec_ai_070.py` 22개 테스트 — AC-070-001~004 전부 + EC-1/EC-2/EC-3/EC-4/EC-5/EC-6/EC-7 전체 + UniqueConstraint 강제 검증 + `surge_auto_improver`/본 서비스 모듈 소스 검사로 탐지기 add/remove·yaml 쓰기 코드 경로 부재 확인 + yaml 파일 mtime/해시 불변 검증.

#### 검증 결과

- 신규 테스트: 22 passed (test_spec_ai_070.py).
- 커버리지: `surge_contribution_service.py` 93%, `surge_detector_contribution.py` 100% (85%+ 기준 충족).
- `ruff check`: 신규/변경 5개 파일 전부 무경고.
- `mypy`: 로컬 환경에 미설치 — 스킵(프로젝트 관례상 미설치 도구는 gracefully skip).
- 매수/포트폴리오 로직 diff 0, 신호 생성 경로(`compute_ensemble_score`/`gather_surge_candidates`/`build_scan_universe`) diff 0 — 세 함수 모두 067~070 커밋에서 전혀 수정되지 않음(읽기 참조만).
- `surge_detection.yaml`/`surge_detection.auto.yaml` 자동 수정 없음 — 테스트로 mtime/해시 불변 보장.

Acceptance criteria completion this cycle: 4/4 (AC-070-001~004). Error delta: 0 new errors introduced. No stagnation — single-pass implementation.