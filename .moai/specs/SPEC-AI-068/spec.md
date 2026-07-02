---
id: SPEC-AI-068
version: 0.1.0
status: draft
created: 2026-07-02
updated: 2026-07-02
author: MoAI
priority: High
issue_number: 0
---

# SPEC-AI-068: 급등예측 평가지표 재정의 & 스캔 유니버스 진단 인프라 (Surge Metric Redefinition & Scan Universe Diagnostics)

## HISTORY

- 2026-07-02 (v0.1.0): 최초 작성. manager-strategy의 근본원인 분석(최근 17개 평가일 중 15일
  TP=0)을 근거로 함. 핵심 진단: 실패는 탐지기 파라미터가 아니라 **평가지표 구조**의 문제다.
  현재 recall이 "알고리즘 품질"과 "유니버스 설계 품질"을 하나로 뒤섞어(conflate) 진단
  불가능한 상태이며, 스캔 유니버스에 애초에 없던 종목까지 recall 분모에 포함되어 **구조적
  recall 상한(~22%)** 이 형성된다. 본 SPEC은 이 둘을 분리 측정하는 진단 인프라를 구축한다.
  - **깨진 recall 전제 (코드 확정, 2026-07-02)**: `surge_evaluation_service.py:531-535`의
    주석이 "surge_actual_outcome이 이미 스캔 유니버스임"이라고 단언하나 이는 **거짓**이다.
    실제 정답 집합은 `surge_actual_outcome_service.py:44-47`에서 **KOSPI/KOSDAQ 각 상위
    100개 무버(change_rate>=10%) + T-1 예측종목 보완**으로 수집된다 — 즉 시장 전체 상위
    상승주이지 우리가 스캔한 유니버스가 아니다. 따라서 `fn = actual_set - predicted_set`에는
    애초에 스캔조차 안 된 종목이 대량 포함되어 recall이 구조적으로 눌린다.
  - **실측 증거 (2026-07-01)**: 당일 실제 급등 123종목 중 **78%(96종목)** 가 전일 스캔
    유니버스에 부재. 완벽한 탐지기라도 recall 상한 ≈ 22%.
  - **유니버스 코드 미영속화 (코드 확정)**: `SurgeUniversePoolHistory`
    (`surge_universe_pool_history.py:15-42`)는 `pool_a/b/c_count` + `scan_universe_size`
    **개수만** 저장하고 종목코드 리스트가 없어 사후 Coverage 진단이 원천 불가능하다.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

본 SPEC은 **측정·진단 인프라 전용**이다. 신규 탐지기·매매 로직·유니버스 구성 로직을 만들지
않는다. 각 항목은 2026-07-02 코드 재확인 결과다.

- **SPEC-AI-065 (z-score 상대채점 + 유니버스 확장 Pool A/B/C) — 확장(비충돌)**: 유니버스
  구성 로직 `build_scan_universe`(`surge_detector.py:3960`), Pool A>B>C 우선순위,
  `max_scan_universe` 상한은 SPEC-AI-065 소유이며 **본 SPEC은 이를 일절 변경하지 않는다.**
  본 SPEC은 065가 만든 유니버스의 **결과(종목코드 리스트)를 영속화하고, 그 위에서 진단
  지표를 계산**할 뿐이다. `SurgeUniversePoolHistory`(AI-065 REQ-5 소유) 확장,
  `SurgePredictionEvaluation.scan_universe_size/pool_a/b/c_count`(`surge_prediction_evaluation.py:53-59`,
  AI-065 REQ-5) 옆에 진단 지표 컬럼을 추가한다.
- **SPEC-AI-041 (급등예측 자동평가·자가개선 루프) — 확장(비충돌)**: 평가 루프
  `evaluate_surge_predictions`(`surge_evaluation_service.py`)와 18:30 KST 스케줄 잡을 재사용한다.
  본 SPEC은 **새 지표를 추가 산출·저장**할 뿐 가중치/임계값 자동조정 로직은 건드리지 않는다
  (그 거버넌스는 SPEC-AI-069 소유).
- **SPEC-AI-043 (예측기록 모드) — 불변**: 실매매 비활성·예측 기록 패러다임을 그대로 유지한다.
  본 SPEC은 지표만 다루므로 자금·매수 로직과 무관하다.
- **SPEC-AI-069 (backtest 게이트·자동개선 거버넌스·z-score 격리) — 후속 의존**: SPEC-AI-069
  REQ-AI069-003(자동개선 목표지표 재타게팅)은 본 SPEC이 신설하는 **Scannable Recall**을
  소비한다. 따라서 구현 순서는 **068 → 069**다.

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic (앱 시작 시 자동 마이그레이션)
- DB: PostgreSQL 16. numpy/scipy/sklearn 부재 — 순수 파이썬으로만 지표 계산.
- 스케줄러: APScheduler, KST 직접 지정. 평가 잡은 18:30 KST `_run_surge_verify_predictions`.
- 운영 모드: 예측기록 전용(실매매 비활성). 자금 리스크 없음, 순수 알고리즘 품질 과제.
- 마이그레이션 head: 현재 최신(AI-065가 063 추가) — 신규 마이그레이션은 실제 head를 RUN
  단계에서 재확인 후 `down_revision`을 설정한다.

---

## Requirements (EARS)

### REQ-AI068-001 (P0, Event-Driven) — 스캔 유니버스 종목 코드 영속화

**WHEN** 일별 스캔 유니버스가 `build_scan_universe`로 구성되면(신호 생성 10:00/15:20 KST),
**the system SHALL** 해당 거래일에 유니버스로 확정된 **종목코드 리스트를 진입 풀 태그(A/B/C)와
함께** 거래일 키로 영속화해야 한다.

- 저장 대상: `{trading_date, stock_code, entry_pool}` 튜플의 집합(일자당 upsert).
- 구현 방향: `SurgeUniversePoolHistory`(현재 개수만) 확장 또는 신규 자식 테이블
  `surge_universe_members` 추가 + Alembic 마이그레이션. (개수 컬럼은 하위호환 유지)
- **[HARD]** 유니버스 구성 로직(우선순위·상한·풀 판정)은 변경하지 않는다 — 확정된 결과만 기록.

### REQ-AI068-002 (P0, Event-Driven) — Scannable Recall 지표 신설

**WHEN** 일별 평가가 실행되면(18:30 KST), **the system SHALL** **Scannable Recall**을 다음으로
계산·저장해야 한다:

```
Scannable Recall = |스캔 유니버스 ∩ 실제급등주 ∩ 발신(predicted) 종목|
                 / |스캔 유니버스 ∩ 실제급등주|
```

- 분모: 해당 T-1 영속화 유니버스(REQ-001)에 포함된 실제급등주만.
- 의미: "스캔 가능했던 종목에 한해, 우리 알고리즘이 실제로 잡았는가" = **알고리즘 품질 지표**.
- 분모가 0이면 값은 `null`(측정 불가)로 저장하며 실패로 간주하지 않는다.

### REQ-AI068-003 (P0, Event-Driven) — Coverage 지표 신설

**WHEN** 일별 평가가 실행되면, **the system SHALL** **Coverage**를 다음으로 계산하고
Scannable Recall과 **분리된 컬럼**에 저장해야 한다:

```
Coverage = |스캔 유니버스 ∩ 실제급등주| / |전체 실제급등주|
```

- 의미: "실제로 급등한 종목 중 몇 %가 애초에 스캔 대상이었는가" = **유니버스 설계 품질 지표**.
- 저장 위치: `SurgePredictionEvaluation`에 `scannable_recall`, `coverage`,
  `scannable_actual_count`, `total_actual_count` 컬럼 추가(마이그레이션).

### REQ-AI068-004 (P0, Unwanted Behavior) — 깨진 recall 전제 교정

**IF** 해당 거래일의 영속화된 스캔 유니버스(REQ-001)가 존재하면, **THEN the system SHALL NOT**
시장 전체 top-movers 집합을 recall 분모로 사용해서는 안 된다.

- `surge_evaluation_service.py:531-535`의 "surge_actual_outcome == 스캔 유니버스" 거짓 전제
  주석과 그에 기반한 계산을 제거한다.
- 기존 시장전체 기준 수치는 **폐기하지 않고** `coverage`(REQ-003)로 명확히 재라벨하여
  보존한다(설계 품질 추적용). 두 지표는 항상 분리 표기된다.
- 유니버스가 부재한 과거 날짜(백필 불가)는 Scannable Recall을 `null`로 두고 레거시 수치를
  "coverage-미상"으로 표시한다.

### REQ-AI068-005 (P1, Ubiquitous + 경계정의) — 급등 유형 라벨링 & 트랙 경계 정의

**The system SHALL** 각 실제급등주를 T-1 스캔 유니버스 포함 여부로 **scannable(선행형) /
non-scannable(당일 촉매형)** 으로 라벨링하고, 급등예측의 **공식 정확도 목표는 scannable
모집단 기준으로만** 측정해야 한다.

- scannable: T-1 유니버스에 존재 → 모멘텀/연속형, 선행 신호 가능(공식 예측 목표, ~22%).
- non-scannable: T-1 유니버스에 부재 → 당일 뉴스/공시 촉매형(T-1 예측 원리적 불가, ~78%).
- **[경계 정의만]** non-scannable 집단은 향후 별도의 **장중 실시간 조기탐지 트랙**에 귀속됨을
  명문화한다. 본 SPEC은 그 트랙의 **경계·라벨 정의까지만** 포함하며, 실시간 파이프라인 자체는
  구현하지 않는다(→ Exclusions, 별도 후속 SPEC).

---

## Exclusions (What NOT to Build) [HARD]

1. **당일 뉴스/공시형(~78%) 실시간 장중 조기탐지 파이프라인 구현** — 본 SPEC은 유형 라벨링과
   트랙 경계 정의까지만. 실시간 스트리밍/장중 재스캔 파이프라인은 별도 후속 SPEC 범위 밖.
2. **스캔 유니버스 구성 로직 변경** — `build_scan_universe`, Pool A/B/C 우선순위,
   `max_scan_universe` 상한은 SPEC-AI-065 소유. 본 SPEC은 결과 영속화 + 진단 지표만 ADD.
3. **탐지기 파라미터·가중치·앙상블·임계값 변경** — 측정 인프라 전용. 어떤 신호 생성 경로도
   바꾸지 않는다.
4. **자동개선 루프 로직 변경** — 가중치/임계값 자동조정 및 목표지표 재타게팅은 SPEC-AI-069 소유.
5. **backtest·calibrator 관련 변경** — SPEC-AI-069 소유.
6. **과거 날짜 유니버스 백필** — 코드가 없어 재구성 불가한 과거는 Scannable Recall `null`로 둔다.

---

## Success Criteria

- `SurgePredictionEvaluation`에 `scannable_recall`/`coverage`/`scannable_actual_count`/
  `total_actual_count` 컬럼이 존재하고 18:30 평가 잡이 이를 채운다.
- 유니버스 종목코드가 거래일별로 조회 가능(신규 테이블/컬럼 + 조회 경로).
- `surge_evaluation_service.py:531-535`의 거짓 전제 주석/로직 제거, recall 분모가 유니버스
  교집합 기반으로 전환.
- 실제급등주가 scannable/non-scannable로 라벨링되어 저장.
- 신규/변경 로직 테스트 커버리지 85%+, `ruff`/`mypy` 무경고, 전체 급등 테스트 회귀 없음.
- 예측기록 모드 불변(매수 로직 diff 0).
