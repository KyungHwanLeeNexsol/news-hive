# SPEC-AI-069 구현 계획 (plan.md)

## 목표

검증 없는 자동개선 루프가 깨진 recall을 좇아 필터를 스스로 조이던 구조를 끊는다. backtest를
운영 게이트로 승격하고, 자동개선을 전면 중단·기본값 리셋한 뒤 backtest 가드 + Scannable
Recall(SPEC-AI-068) 목표로 재설계하며, SPEC-AI-065 z-score 회귀를 flag로 격리하고 무효
calibrator를 정리한다.

## 사용자 확정 결정 반영 (2026-07-02) [HARD]

| # | 결정 | SPEC 반영 |
|---|------|----------|
| D1 | SPEC-AI-068 + 069만 지금 작성, 탐지기 기여도 검증(구 070)은 후속 별도 | Exclusions #7, 본 SPEC 범위 한정 |
| D2 | 문서 위치 = 루트 `.moai/specs/` | `.moai/specs/SPEC-AI-069/`에 작성됨 |
| D3 | z-score 격리 = config flag **기본값 false** → 즉시 절대채점(AI-065 이전 raw) 폴백 | REQ-AI069-004 |
| D4 | 자동개선 **전체 중단** — 스케줄러 잡 비활성 + `auto.yaml` 기본값 리셋(min_score=0.38, legacy 가중치 복원) | REQ-AI069-002 |

## 기술 접근 (Technical Approach)

### 1. Backtest 운영 게이트 (REQ-001)
- `compute_surge_backtest`(`surge_backtest.py:36`)를 `scheduler.py` `start_scheduler()`(:1894)에
  cron 잡으로 편입. 기존 래퍼 관례(SessionLocal()+asyncio.run+try/except/finally, KST 직접 지정)
  준수. 실행 시각은 평가(18:30) 이후 슬롯 권장(RUN 단계에서 충돌 없는 KST 확정).
- 판정 결과 저장: 신규 컬럼/소형 테이블(`surge_backtest_result`)에 pass/fail + 지표 + config
  스냅샷(파라미터 해시)을 기록 → REQ-002/003 거버넌스가 조회.
- floor 기준은 `surge_detection.yaml`에 config화(예: 최소 precision/Scannable Recall/EV).

### 2. 자동개선 전면 중단 + 기본값 리셋 (REQ-002, D4)
- 스케줄러: 자동개선 잡(`surge_auto_improve` 계열 등록부)을 **비활성화**. 방식은 (A) 등록 자체
  제외 vs (B) `auto_improve_enabled: false` flag로 no-op — 롤백 용이성 위해 **(B) flag 권장**.
- `surge_detection.auto.yaml` 리셋: 자동조정 오버라이드 제거 → base `surge_detection.yaml`
  기본값 복원. **확정값 min_score_for_signal=0.38**, `legacy_detectors` 가중치를 base 기본값으로
  복원. 그 외 auto-improver 드리프트 항목(가중치 0으로 무력화된 탐지기, 상향된 임계값)도 base
  기준 원복. **정확한 base 수치는 커밋된 `surge_detection.yaml`에서 읽어 확정**(코드에 상수
  하드코딩 금지 — base yaml이 authoritative). 리셋 후 `reload_surge_config()` 호출로 캐시 반영.

### 3. 자동개선 재설계: backtest 가드 + Scannable Recall (REQ-003)
- `analyze_and_improve`(`surge_auto_improver.py:355`)의 min_score 조정(:539-570)이 참조하는
  recall을 **Scannable Recall(SPEC-AI-068)** 로 교체.
- 제안 반영 전 backtest canary(REQ-001) 통과 확인 → 미통과 시 `_write_auto_yaml` 미호출(가드).
- AI-061 pendulum/EV 가드와 병존. **재활성은 기본 비활성**(REQ-002 존중) — 명시적 flag로만 on.

### 4. z-score 회귀 격리 (REQ-004, D3)
- `surge_detection.yaml`에 `relative_scoring.zscore_enabled: false`(기본) 추가.
- `zscore_to_score`(`surge_baseline_service.py:82-89`) 사용 채점 경로에 분기: flag=false이면
  z-score 우회, AI-065 이전 절대 점수로 채점. **AI-065 코드 재작성 없이 게이팅만.**
- 재활성(true)은 backtest가 z-score 기준 임계값·가중치를 재도출·통과한 뒤에만.

### 5. calibrator 정리 (REQ-005)
- 부재/identity 상태를 일별 리포트/로그에 명시(`surge_calibrator.py:207-225` fallback 경로).
- 결정: (a) 학습 스케줄 잡 추가로 pkl 생성·배포 vs (b) `fund_manager.py:1385` 연결 제거+문서화.
  RUN 단계에서 데이터 충분성(최소 학습 샘플) 확인 후 (a)/(b) 택1. 조용한 무효 방치 금지.

## 파일 영향 범위 (예상)

| 파일 | 변경 유형 | 근거 |
|------|----------|------|
| `backend/app/services/scheduler.py` (start_scheduler :1894~) | 잡 편입/비활성 | REQ-001/002 |
| `backend/app/services/surge_backtest.py` | 판정/저장 보강 | REQ-001 |
| `backend/app/services/surge_auto_improver.py` (:355, :539-570) | 가드+재타게팅+중단 flag | REQ-002/003 |
| `backend/app/services/surge_baseline_service.py` (:82-89) 및 채점 호출부 | flag 분기 | REQ-004 |
| `backend/app/services/surge_calibrator.py` / `fund_manager.py:1385` | 표면화/연결정리 | REQ-005 |
| `backend/surge_detection.yaml` / `surge_detection.auto.yaml` | flag/기본값 리셋 | REQ-002/003/004 |
| `backend/alembic/versions/0XX_*.py` | backtest 결과 저장 스키마 | REQ-001 |
| `backend/tests/test_surge_backtest.py` 외 | 테스트 | 전 REQ |

## 마일스톤 (우선순위 기반)

- **M1 (P0, 즉시 출혈 차단)**: REQ-002 — 자동개선 잡 비활성 + `auto.yaml` 기본값 리셋 +
  REQ-004 z-score flag=false. **가장 안전하고 즉효**. 잘못된 자동 필터 조임과 z-score 회귀를 즉시 중단.
- **M2 (P0)**: REQ-001 — backtest 스케줄러 편입 + 판정 영속화. 검증 신호 축적 시작.
- **M3 (P0)**: REQ-003 — 자동개선 재설계(backtest 가드 + Scannable Recall). **SPEC-AI-068 완료 후.**
- **M4 (P1)**: REQ-005 — calibrator 표면화 + 학습연결/제거.
- **M5 (P0)**: 테스트 + 전체 급등 스위트 회귀 + 린트/타입.

## 롤아웃 / 롤백 전략 [HARD]

예측기록 모드라 자금 리스크는 없으나 자동개선·채점은 **운영 배치 파이프라인**을 바꾸므로 단계적.

**롤아웃 (순서)**
1. **Phase 1 (즉시)**: M1 배포 — 자동개선 SUSPEND(`auto_improve_enabled=false`) + `auto.yaml`
   기본값 리셋 + z-score flag=false. 파이프라인이 base yaml 기본값으로 결정론적 동작하게 됨.
2. **Phase 2 (축적)**: M2 배포 — backtest 정기 잡 가동, pass/fail 판정 누적(신호 생성엔 미개입).
3. **Phase 3 (재활성, 068 완료 후)**: M3 배포 — 자동개선을 backtest 가드 + Scannable Recall
   목표로 재활성(명시적 flag on). z-score는 backtest 재보정 통과 시에만 flag=true 고려.

**롤백 (각 REQ 독립 flag)**
- 자동개선: `auto_improve_enabled` flag로 즉시 재중단.
- z-score: `relative_scoring.zscore_enabled` flag로 절대채점 복귀(기본 false이므로 롤백=기본상태).
- backtest 잡: 잡 등록 제거/비활성으로 신호 경로 무영향(잡은 판정만 생성).
- 모든 config는 `surge_detection.auto.yaml` 경유(`git reset --hard` 보호). base yaml 변경은 커밋 추적.
- **Deploy Guard 15:15~15:45 KST 준수** — 신호 생성 중 배포 금지.

## 리스크 & 완화

- **기본값 리셋 오판**: `legacy_detectors` 등 "복원" 대상 base 수치를 코드 상수로 하드코딩하면
  stale 위험. 완화: base `surge_detection.yaml`을 authoritative 소스로 읽어 리셋(하드코딩 금지).
- **backtest floor 과/부족 설정**: 초기 floor를 보수적으로 두고 Phase 2 축적 데이터로 조정.
- **068 미완 시 REQ-003 차단**: Scannable Recall 의존 → 068 완료 전 M3 착수 금지(M1/M2는 독립 진행 가능).
- **z-score 재활성 유혹**: flag=true 전환은 반드시 backtest 재보정 통과를 전제(REQ-004 [HARD]).

## 검증 방법

- M1 후: `surge_detection.auto.yaml`이 base 기본값과 일치(min_score=0.38), 자동개선 잡 미등록/no-op
  로그 확인. z-score flag=false에서 채점이 절대 점수 경로를 타는지 로그로 확인.
- M2 후: backtest 잡 실행 로그 + 판정 레코드 생성 확인.
- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과, 매수 로직 diff 0.
