---
id: SPEC-AI-069
version: 0.1.0
status: draft
created: 2026-07-02
updated: 2026-07-02
author: MoAI
priority: High
issue_number: 0
---

# SPEC-AI-069: Backtest 운영 게이트 & 자동개선 거버넌스 & z-score 회귀 격리 (Backtest Gate, Auto-Improve Governance & z-score Isolation)

## HISTORY

- 2026-07-02 (v0.1.0): 최초 작성. manager-strategy 근본원인 분석 근거. 핵심 진단: **검증(backtest)
  없는 자동개선 루프가 깨진 지표를 좇아 스스로를 마비**시켰다. 본 SPEC은 (1) backtest를 운영
  게이트로 승격, (2) 자동개선 루프를 전면 중단하고 기본값으로 리셋한 뒤 backtest 가드 +
  Scannable Recall(SPEC-AI-068) 목표로 재설계, (3) SPEC-AI-065 z-score 정규화 회귀를 config
  flag로 격리, (4) 무효 상태인 calibrator를 학습·연결 또는 명시적 제거로 정리한다.
  - **사용자 확정 결정 4건 (2026-07-02, 권장안 승인)**:
    - (D1) 분할: SPEC-AI-068 + SPEC-AI-069만 지금 작성. 탐지기 기여도 검증(구 070)은 후속 별도.
    - (D2) 위치: 루트 `.moai/specs/` (backend/.moai/specs/ 아님).
    - (D3) z-score 격리(REQ-AI069-004): config flag **기본값 DISABLED** — 즉시 절대채점(AI-065
      이전 raw score 기반)으로 폴백.
    - (D4) 자동개선 중단 범위(REQ-AI069-002): **전체 중단** — `surge_auto_improver` 스케줄러 잡
      일시 비활성화 + `surge_detection.auto.yaml`을 **기본값으로 리셋**(min_score_for_signal=0.38,
      legacy_detectors 가중치 복원 등 base yaml 기준).
  - **코드 확정 진단 (2026-07-02)**:
    - **backtest = dead code**: `compute_surge_backtest`(`surge_backtest.py:36`)의 유일한 호출처는
      수동 라우터 `fund_manager.py:560`(+tests). `scheduler.py`의 `start_scheduler()`(:1894, cron
      잡 다수)에 backtest/calibrate 정기 잡이 **0건**. 테스트 스위트 `test_surge_backtest.py`는 존재.
    - **calibrator = no-op**: `surge_calibrator.py:18`이 `data/surge_calibrator.pkl`을 로드하나 운영
      서버에 파일 부재 → **identity fallback**(보정 무효). `calibrate_confidence`는
      `fund_manager.py:1385`에서 import되나 pkl 부재로 사실상 무효.
    - **auto-improve가 깨진 recall 추종**: `surge_auto_improver.analyze_and_improve`(:355)의 min_score
      조정(:539-570)이 recall 기반. :556 주석은 "recall=0은 예측 실패 아님"을 이미 인지하나 **bypass만**
      할 뿐 지표 자체를 교정하지 않음. pendulum 진동 실증(:219), EV 가드(AI-061, :606-639) 존재.
    - **z-score 회귀**: `surge_baseline_service.zscore_to_score`=sigmoid(z)(:82-89)가 점수 분포를
      변경(SPEC-AI-065). `surge_detector.py:4038` 주석이 유니버스/z-score를 "불변(AI-065 소유)"로 명시.
      임계값·가중치는 z-score 이전 기준으로 재도출되지 않은 채 재사용됨 — 정확도 붕괴 시작과 일치.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

본 SPEC은 **거버넌스·게이트 계층**이다. 신규 탐지기·매매 로직·유니버스 구성·지표 계산 자체를
만들지 않는다. 기존 자산을 감싸고 통제한다. 각 항목은 2026-07-02 코드 재확인 결과다.

- **SPEC-AI-068 (평가지표 재정의) — [HARD] 선행 의존**: REQ-AI069-003(자동개선 목표지표
  재타게팅)은 SPEC-AI-068이 신설하는 **Scannable Recall**을 소비한다. 구현 순서 **068 → 069**.
  본 SPEC은 지표를 **소비만** 하며 지표 계산 로직은 만들지 않는다.
- **SPEC-AI-041 (자동평가·자가개선 루프) — 거버넌스로 감쌈(비충돌)**: `surge_auto_improver`의
  가중치/임계값 자동조정 로직 자체는 AI-041 소유. 본 SPEC은 그 위에 **backtest 통과 게이트 +
  목표지표 재타게팅 + 전면 중단/리셋 스위치**를 얹는다(로직 재작성 아님, 거버넌스 추가).
- **SPEC-AI-061 (자동개선 하드닝) — 확장(비충돌)**: pendulum 방지·EV 가드·트랜잭션 안전은
  AI-061 소유. 본 SPEC의 backtest 가드는 그 위에 추가되는 상위 게이트다.
- **SPEC-AI-065 (z-score 상대채점) — flag로 격리**: z-score 정규화(`surge_baseline_service`
  sigmoid, `surge_detector` 적용부)를 **재작성하지 않고** config flag로 감싸 기본 DISABLED
  (절대채점 폴백)로 전환한다. backtest 재보정 후 재활성 가능.
- **SPEC-AI-043 (예측기록 모드) — 불변**: 실매매 비활성 유지. 단, 자동개선은 운영 배치
  파이프라인을 변경하므로 롤아웃/롤백 전략(plan.md)을 수반한다.

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, APScheduler(SQLAlchemy 잡스토어), Alembic.
- numpy/scipy/sklearn 부재 — backtest/calibrator 로직은 순수 파이썬.
- config: `surge_detection.yaml`(base, 커밋됨) + `surge_detection.auto.yaml`(자동개선 산출물,
  `git reset --hard` 보호). `reload_surge_config()` 존재.
- 운영 모드: 예측기록 전용(실매매 비활성). 자금 리스크 없음. 단, 배치 파이프라인 영향 있음 →
  단계적 롤아웃 필수(plan.md).
- Deploy Guard: 15:15~15:45 KST 자동 대기.

---

## Requirements (EARS)

### REQ-AI069-001 (P0, Event-Driven) — Backtest 운영 게이트 승격 (스케줄러 편입)

**WHEN** 스케줄된 backtest 잡이 실행되면, **the system SHALL** 현재 config에 대해
`compute_surge_backtest`를 실행하여 **pass/fail 판정 + 지표를 영속화**해야 한다.

- `compute_surge_backtest`(`surge_backtest.py:36`)를 `scheduler.py` `start_scheduler()`에 정기
  cron 잡으로 편입(KST 직접 지정, 기존 래퍼 패턴 SessionLocal+asyncio.run 관례).
- 판정 기준(floor)은 config로 정의하고, 판정 결과를 신규 테이블/컬럼에 저장하여 REQ-002/003
  거버넌스가 조회할 수 있게 한다.

### REQ-AI069-002 (P0, Unwanted Behavior) — 자동개선 루프 전면 중단 + 기본값 리셋 [D4 확정]

**IF** 본 SPEC이 배포되면, **THEN the system SHALL** `surge_auto_improver` 자동조정을 **전면
중단**하고 `surge_detection.auto.yaml`을 **기본값으로 리셋**해야 한다.

- 스케줄러의 자동개선 잡(`surge_auto_improve` 계열)을 **비활성화**(등록 제외 또는 no-op flag).
- `surge_detection.auto.yaml`의 자동조정 오버라이드를 제거하고 커밋된 base `surge_detection.yaml`
  기본값으로 복원한다. **[HARD] 사용자 확정값**: `min_score_for_signal = 0.38`,
  `legacy_detectors` 가중치를 base 기본값으로 복원. (그 외 auto-improver가 드리프트시킨 가중치·
  임계값도 base 기준으로 원복. 정확한 base 수치는 RUN 단계에서 커밋된 base yaml에서 읽어 확정.)
- **[HARD]** 재활성은 REQ-003의 조건(backtest 가드 + Scannable Recall 목표)이 충족되기 전까지 금지.

### REQ-AI069-003 (P0, State-Driven) — 자동개선 재설계: backtest 가드 + Scannable Recall 재타게팅

**WHILE** 자동개선이 (REQ-002 중단 이후) 재활성된 상태이면, **the system SHALL** (a) 제안된
가중치/임계값 변경이 backtest canary(REQ-001)를 **통과한 경우에만** `surge_detection.auto.yaml`에
반영하고, (b) 최적화 목표지표로 혼재된 recall 대신 **Scannable Recall(SPEC-AI-068)** 을 사용해야 한다.

- backtest 미통과 제안은 거부하고 현재 config를 유지한다(가드).
- `analyze_and_improve`(:355)의 min_score 조정(:539-570)이 참조하는 recall을 Scannable Recall로 교체.
- AI-061의 pendulum/EV 가드와 병존(상위 게이트로 추가).
- **재활성 자체는 별도 승인/플래그**로 통제(기본 비활성 유지 — REQ-002 상태 존중).

### REQ-AI069-004 (P0, Optional/Where) — z-score 회귀 격리 (config flag 기본 DISABLED) [D3 확정]

**WHERE** z-score 상대채점 경로가 코드에 존재하더라도, **the system SHALL** 이를 config flag
뒤에 두고 **기본값 DISABLED**로 하여, 기본 동작을 **AI-065 이전 절대채점(raw score)** 으로
폴백해야 한다.

- 대상: `surge_baseline_service.zscore_to_score`(sigmoid, :82-89)를 사용하는 채점 경로.
- flag 예: `surge_detection.yaml` `relative_scoring.zscore_enabled: false`(기본).
- **[HARD]** flag=false이면 z-score 정규화를 우회하고 절대 점수로 채점(AI-065 배포 이전 동작).
- 재활성(flag=true)은 backtest(REQ-001)가 z-score 기준 임계값·가중치를 재도출·통과한 이후에만.
- **[HARD]** AI-065 소유 코드를 **재작성하지 않고** flag 게이팅만 추가한다.

### REQ-AI069-005 (P1, Unwanted Behavior) — calibrator 무효 상태 표면화 + 학습연결/명시적 제거

**IF** calibrator 아티팩트(`data/surge_calibrator.pkl`)가 부재하면, **THEN the system SHALL**
조용한 identity fallback을 **상태로 표면화**(로그/지표/리포트)해야 하며, 운영자는 다음 중
하나를 선택한다: (a) 스케줄 잡으로 학습·배포하여 보정을 유효화, 또는 (b) calibrator 연결을
명시적으로 제거하고 문서화. **조용한 identity 무효 상태를 방치하지 않는다.**

- 대상: `surge_calibrator.py`(:18 경로, :207~225 fallback), 호출부 `fund_manager.py:1385`.
- 최소 요건: 부재/무효 상태가 리포트에 명시되어 운영자가 인지 가능해야 함.

---

## Exclusions (What NOT to Build) [HARD]

1. **개별 탐지기 파라미터 미세조정** — backtest 인프라(REQ-001) 구축이 선행되어야 한다. 파라미터
   튜닝은 backtest 통과를 전제로 별도 진행(본 SPEC 범위 밖).
2. **Scannable Recall/Coverage 지표 구현** — SPEC-AI-068 소유. 본 SPEC은 소비만.
3. **스캔 유니버스 구성/Pool 로직 변경** — SPEC-AI-065 소유.
4. **z-score 정규화 알고리즘 재작성** — flag 게이팅만. AI-065 코드 로직 유지.
5. **신규 탐지기 추가**.
6. **실매매·포트폴리오 로직 변경** — 예측기록 모드(AI-043) 유지.
7. **탐지기 기여도 데이터 검증·정리** — 후속 별도 SPEC(구 070). 본 SPEC 범위 밖(D1 확정).

---

## Success Criteria

- backtest가 스케줄러 정기 잡으로 실행되고 pass/fail 판정이 영속화된다(REQ-001).
- 자동개선 잡이 비활성화되고 `surge_detection.auto.yaml`이 base 기본값(min_score=0.38 등)으로
  리셋된다(REQ-002).
- 자동개선 재활성 경로가 backtest 가드 + Scannable Recall 목표를 요구하도록 구현된다(REQ-003).
- z-score flag가 기본 DISABLED이고, 기본 실행이 절대채점으로 폴백된다(REQ-004).
- calibrator 부재/무효 상태가 리포트로 표면화되고, 학습연결 또는 명시적 제거 중 하나가 반영된다(REQ-005).
- 테스트 커버리지 85%+, `ruff`/`mypy` 무경고, 전체 급등 스위트 회귀 없음, 매수 로직 diff 0.
