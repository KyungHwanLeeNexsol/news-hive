# SPEC-AI-070 (compact)

- id: SPEC-AI-070 | status: draft | priority: Medium | created: 2026-07-02
- title: 탐지기 기여도 검증 & 은퇴 제안 (Detector Contribution Validation & Retirement Proposal)
- goal: 14개+ 탐지기 중 scannable 급등을 실제로 잡는 탐지기와 신호만 희석시키는 탐지기를 데이터로
  구분하고, 기여 없는 탐지기의 은퇴 제안(사람 승인 게이트)을 생성. 측정·리포트 전용, 신호생성 무변경.

## 사용자 확정 결정 (2026-07-02)
- D1: 기여도 스냅샷 = 신규 테이블 `surge_detector_contribution`
  {run_date, detector, emission_count, solo_count, solo_tp, coincident_hit_rate, unique_catch, retire_candidate}
- D2: REQ-005 학습형 타당성 평가 = 포함(리포트 전용, 모델 학습·배포 없음)

## 코드 확정 근거 (2026-07-02)
- by_combination 이미 존재·영속화: `compute_surge_backtest`(`surge_backtest.py:82-118`) → 069가
  `surge_backtest_result.by_combination_json`(:47) 저장. 단 조합단위+방향성5일정확도(:90)이지
  단일탐지기·scannable 아님 → 070은 068 라벨 위 단일탐지기 기여 NEW, by_combination은 은퇴 시뮬 입력 재사용.
- 앙상블 weighted_sum 편입 7개(`surge_detector.py:1553-1564`): theme_cluster0.19/volume_news_combo0.25/
  disclosure_pattern0.14/legacy_detectors0.00/news_delayed0.11/volume_breakout0.11/momentum_continuation0.12.
- weekend_gap_up(yaml:72 weight 0.08)는 weighted_sum 미반영=dead config, standalone bypass만(:3439/:3535);
  단 validate_ensemble_weights 합=1.0에는 포함 → yaml 단순제거시 검증자 깨짐.
- legacy_detectors weight0.00이나 active_detectors 추가(:2004-2005)+detector_groups["technical"](:1574)로
  consensus multiplier(×1.30/1.55, :1579-1591) 기여 가능 → 기여도≠가중치.
- component score 미영속화(surge_metadata=최종 score+surge_basis만) → 정밀 재채점 counterfactual 불가,
  기여도는 surge_basis 멤버십 attribution으로 한정.

## REQ (5)
- REQ-AI070-001 (P0, Event-Driven): WHEN 일별 평가(18:30) 완료 시, 탐지기별 롤링 기여도 5지표
  (emission_count/solo_count/solo_tp/coincident_hit_rate/unique_catch)를 surge_basis × 068 scannable
  라벨(surge_type=="scannable")∩T-1 유니버스 위에서 계산. [HARD] 신호생성 경로 무변경.
- REQ-AI070-002 (P0, Event-Driven): WHEN 기여도 계산 시, 신규 테이블 surge_detector_contribution에
  탐지기당 1행 영속화 + 리포트(텔레그램/로그/옵션 엔드포인트). 전 탐지기(standalone/0-가중치 포함) 대상,
  weighted_sum/standalone/0-가중치 3분류 표기 + weekend_gap_up dead-weight·legacy consensus 뉘앙스 표면화.
- REQ-AI070-003 (P1, State-Driven): WHILE 롤링 기여도 floor 미만(unique_catch==0 AND solo_tp==0이
  ≥N거래일 AND ≥min_signals 지속)이면, 069 backtest 시뮬(by_combination서 solo 신호 제외 후 accuracy
  재계산)로 검증된 은퇴 제안 생성 + retire_candidate=true. 제안만, config write 금지.
- REQ-AI070-004 (P0, Unwanted): IF 은퇴 제안 생성 시, THEN yaml/auto.yaml 자동수정·자동비활성화 금지.
  가중치0/enabled=false는 사람이 base yaml 수동편집(069 HITL 일관). auto_improver에 detector add/remove
  능력 부여 금지. 앙상블 편입 은퇴시 [HARD] 잔여 가중치 재정규화 경고 포함(validate_ensemble_weights 보존).
- REQ-AI070-005 (P1, Optional/Where): WHERE 기여도·backtest 이력 충분 시, 학습형 앙상블(오프라인 로지스틱,
  순수파이썬, AI-065 시드 prior art) vs 룰기반 고정가중치 타당성 평가 리포트 산출. 평가 전용, 모델
  학습·배포·온라인 가중치 변경 없음.

## Given/When/Then (요약)
- AC-070-001 (REQ-001/002): T-1 시그널 A[combo단독,scannable적중]/B[theme+combo,적중]/C[momentum단독,실패]
  → 계산잡 실행 → surge_detector_contribution 탐지기당 1행, combo emission=2·solo=1·solo_tp=1·unique_catch≥1,
  theme emission=1·solo=0, momentum solo_tp=0·unique_catch=0. 신호생성 diff 0.
- AC-070-002 (REQ-002): weekend_gap_up(weight0.08 미반영)+legacy(0.00,consensus) 상태 → 리포트 생성 →
  3분류 표기, weekend_gap_up="standalone dead config", legacy="0가중치 consensus 기여 가능", 무기여 오분류 없음.
- AC-070-003 (REQ-003/004): forum_mention_surge가 충분윈도 unique_catch==0&solo_tp==0 & 은퇴시 accuracy
  하락없음 → 은퇴로직 → retire_candidate=true + before/after 판정 리포트, [HARD] yaml/auto.yaml mtime·내용
  불변(테스트 검증), 앙상블 은퇴시 재정규화 예시 포함, auto_improver 제거경로 부재.
- AC-070-004 (REQ-005): 이력 충분 → 타당성 평가 로직 → 학습형 vs 룰기반 이득/손실 추정 + 데이터충분성
  + 다음단계 권고 리포트. 모델 운영 미연결, yaml/신호생성 diff 0.
- Edge: EC-1 표본부족→retire_candidate=false, EC-2 scannable분모0→hit_rate null, EC-3 유니버스부재과거
  →윈도 제외, EC-4 weekend_gap_up 재정규화 경고, EC-5 legacy 0가중치+unique_catch>0→은퇴부적합,
  EC-6 component부재 근사한계 각주, EC-7 텔레그램 미설정→로그만 graceful.

## 영향받는 파일
- NEW: `app/models/surge_detector_contribution.py`(테이블 surge_detector_contribution) +
  Alembic 마이그레이션 1건([HARD] head는 RUN서 재확인; 068→065·069→066 사용상 067 추정, 하드코딩 금지).
- NEW: `app/services/surge_contribution_service.py`(순수파이썬, 집계+은퇴판정+backtest검증시뮬).
- NEW(옵션): 조회 엔드포인트 `GET /api/surge-trading/detector-contribution`.
- MODIFY: `app/scheduler.py`(평가/backtest 이후 잡 1건, timezone="Asia/Seoul", distinct id) — 잡 등록만.
- REUSE(불변): `surge_evaluation_service.py:482` evaluate_surge_predictions(18:30), `surge_backtest.py:82-118`
  compute_surge_backtest.by_combination, `surge_universe_pool_service.py:170` get_universe_members_for_date,
  `surge_actual_outcome.py` surge_type. FundSignal→Stock.stock_code 조인.
- [HARD] 무변경: `surge_detector.py`(compute_ensemble_score/gather_surge_candidates/build_scan_universe),
  surge_detection.yaml, surge_detection.auto.yaml, 매수 로직.

## Exclusions (8)
1. 신규 탐지기 추가 금지.
2. 승인 없는 자동 탐지기 제거/비활성화 금지(yaml/auto.yaml 자동수정 금지, 사람 수동편집만).
3. 파라미터/가중치 미세조정 금지(SPEC-AI-069 backtest 가드 영역).
4. 룰기반→학습형 전환은 타당성 평가(REQ-005)까지만(모델 학습·배포·온라인 가중치 변경 범위 밖).
5. 신호생성 경로 무변경(compute_ensemble_score/gather_surge_candidates/build_scan_universe).
6. SPEC-AI-065/068/069 재작성 금지(소비만).
7. 실매매·포트폴리오 로직 변경 금지(AI-043 예측기록 모드 유지, 매수 diff 0).
8. component-score 영속화 범위 밖(신호생성 write 유발) → surge_basis attribution으로 한정.

## Deps / Rollout
- [HARD] 068 선행(scannable 라벨 소비) + 069 선행(by_combination backtest 검증). 순서 068→069→070.
- Rollout(측정전용, 신호손실 위험 없음): M1 마이그레이션 head 재확인 → M2 forward-only(068 배포일 이후만
  유효 윈도, 백필 없음) → M3 초기 shadow 관측(min_signals 게이트로 표본부족 방어) → M4 배포확인(잡 등록/
  첫 run_date 행 적재/리포트 도달) → Deploy Guard 15:15~15:45 KST 준수.
