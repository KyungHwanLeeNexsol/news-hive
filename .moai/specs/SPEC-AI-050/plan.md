---
id: SPEC-AI-050
version: 0.1.0
status: draft
created: 2026-06-17
updated: 2026-06-17
---

# SPEC-AI-050 구현 계획 (Plan)

## 기술 접근 (Technical Approach)

본 SPEC은 신규 코드보다 **기존 탐지 경로의 파라미터·게이트 개선**을 중심으로
한다. 우선순위는 (1) YAML-only 변경, (2) 설정 모델 확장, (3) 코드 로직 추가
순이며, 위험이 낮은 변경부터 적용한다.

### 핵심 설계 결정

1. **요일 판정 위치 (REQ-1)**: `detect_volume_surge_news_combo` 가 cfg 를
   재구성하는 지점(surge_detector.py:455-464)에서 요일 가드를 적용한다.
   별도 헬퍼 `_resolve_dynamic_news_window(base_hours, run_dt)` 를 추가해
   `min(72, base_hours * 4)` 확장 로직을 캡슐화하고, weekend_gap_up(REQ-5)도
   동일 헬퍼로 활성화 여부를 판정한다 (단일 진실 공급원).

2. **직전 거래일 판정**: `is_market_hours()`/`KRX_EXTRA_HOLIDAYS`
   (surge_trading_service.py) 의 거래일 판정을 재사용한다. "직전 거래일이
   2 역일 이상 이전" = 토/일/공휴일 건너뛴 직전 영업일과의 역일 차 >= 2.
   월요일이면 금요일과의 차 = 3 역일 → 트리거.

3. **YAML 자동 패치 확장 (REQ-3)**: `_patch_yaml_values` 는 이미 임의 dot-path
   를 지원하므로 코드 변경 없이 `regime_detector_params.BEAR.news_window_hours`
   패치가 가능하다. 단, `_replace_yaml_value` 가 정수(`24`)를 `24.0000` 으로
   포맷하면 YAML int 가 float 으로 바뀌는 부작용이 있으므로, 정수 파라미터용
   포맷 분기를 추가한다 (news_window_hours 는 int 필드).

4. **group_cascade companion 가드 (REQ-4)**: `existing_today` 맵(이미 수집됨,
   surge_detector.py:2333-2343)을 cascade 종목 발행 직전에 조회하여
   group_cascade 외 signal_type 존재 여부를 판정한다. 유효 신뢰도는
   `flagship_prob * config.decay_factor` 로 계산.

5. **weekend_gap_up 배선 (REQ-5)**: `_run_coverage_expansion_signals`
   (fund_manager.py:3804+)에 다른 커버리지 탐지기들과 동일한 try/except 블록으로
   추가하여 실패해도 surge_candidate 파이프라인에 영향을 주지 않도록 격리한다.

6. **앙상블 가중치 재배분 결정 (REQ-5)**: 기본안은 legacy_detectors 0.10 → 0.00,
   weekend_gap_up 0.10. legacy_detectors 가 여전히 유효 신호를 내는지
   확인 후, 무효하면 0.00, 유효하면 분할안(0.05/0.05)으로 운영자 승인. 이
   설계 결정은 구현 시작 시 확정한다.

---

## 마일스톤 (Milestones, 우선순위 기반)

### M1 (Priority High): YAML-only 즉시 완화 — REQ-2

- BEAR.news_window_hours 12 → 24 변경.
- 배포 후 다음 BEAR 레짐 신호 생성에서 윈도우 확장 효과 확인.
- 위험 최저. 코드 변경 없음.

### M2 (Priority High): 요일 동적 윈도우 — REQ-1

- `_resolve_dynamic_news_window` 헬퍼 추가.
- 직전 거래일 판정 로직(거래일 가드 재사용).
- `detect_volume_surge_news_combo` cfg 재구성에 주입.
- 로깅 추가.

### M3 (Priority High): group_cascade companion 가드 — REQ-4

- GroupCascadeConfig 에 `require_companion_detector`,
  `companion_required_below_prob` 추가.
- detect_group_cascade_signals 발행 단계에 가드 삽입.
- YAML group_cascade 섹션 추가.

### M4 (Priority Medium): 자가개선 윈도우 확장 — REQ-3

- recall=0 3일 연속 + detector contribution=0 판정 로직 추가.
- `regime_detector_params.{regime}.news_window_hours` 패치 + 상한 48h.
- `_replace_yaml_value` 정수 포맷 분기.
- SurgeAutoImprovementLog 기록(R12 롤백 호환).
- M1 이후에 진행 (BEAR 윈도우 24 가 baseline 이 된 뒤 자동 조정 검증).

### M5 (Priority Medium): weekend_gap_up 탐지기 — REQ-5

- `detect_weekend_gap_up_signals()` 신규.
- surge_actual_outcome 최근 10거래일 was_surge=True 조회.
- 섹터-활성테마 매칭.
- 앙상블 가중치 재배분(설계 결정 확정 후).
- fund_manager 후처리 파이프라인 배선.
- M2 의 요일 가드 헬퍼에 의존.

---

## 마이그레이션 / 롤백 노트

### DB 마이그레이션

- **DB 스키마 변경 없음**. weekend_gap_up 은 기존
  signal_type="surge_candidate" + surge_metadata.surge_basis 를 사용한다
  (FundSignal 에 신규 컬럼 불필요). REQ-3 윈도우 로그는 기존
  SurgeAutoImprovementLog 모델 재사용.

### YAML 변경 롤백

surge_detection.yaml 변경 항목:
- `regime_detector_params.BEAR.news_window_hours`: 12 → 24 (REQ-2)
- `ensemble.weights.legacy_detectors` / 신규 `weekend_gap_up` (REQ-5)
- 신규 `group_cascade.require_companion_detector` /
  `companion_required_below_prob` (REQ-4)

롤백 절차: 위 키들을 이전 값으로 되돌리고 `reload_surge_config()` 호출(또는
서비스 재시작). 가중치 롤백 시 합산 1.0 재검증 필수.

### [중요] 배포 시 YAML 리셋 위험

- **`git pull` 이 자가개선된 YAML 을 덮어쓴다.** 자가개선 루프(SPEC-AI-041)와
  본 SPEC REQ-3 는 surge_detection.yaml 을 런타임에 직접 패치한다. 배포
  (`scripts/deploy.sh` git pull)는 커밋된 버전으로 파일을 되돌려, 누적된 자동
  조정값(min_score, 가중치, 윈도우)이 소실된다.
- **완화책 (구현 시 고려, 본 SPEC 범위 밖일 수 있음)**:
  - 배포 전 현행 surge_detection.yaml 의 자동조정 키 값을 백업/머지하거나,
  - 자동조정 대상 키를 별도 런타임 오버라이드 파일(예: 미추적
    `surge_overrides.yaml`)로 분리하여 git pull 영향을 받지 않게 하는 방안.
  - 최소한 배포 후 R12 롤백/재조정이 정상화될 때까지 recall 모니터링.
- 본 SPEC은 이 위험을 **명시적으로 기록**하되 구조적 해결(오버라이드 파일
  분리)은 별도 SPEC 후보로 남긴다.

### YAML 정수 포맷 회귀 위험

- `_replace_yaml_value` 의 `f"{new_val:.4f}"` 포맷은 int 파라미터를 float 으로
  바꾼다. news_window_hours(int)에 적용 시 `24.0000` 이 되어 Pydantic int
  파싱은 통과하나 YAML 가독성 저하. M4 에서 정수 분기 추가로 해결.

---

## 위험 (Risks)

| 위험 | 영향 | 완화 |
|------|------|------|
| 동적 윈도우가 노이즈 뉴스 과다 유입 → precision 저하 | recall↑ but precision↓ | 72h 상한 + min_news_sentiment 게이트 유지, 자가개선이 min_score 로 보정 |
| companion 가드가 정상 cascade 까지 과도 차단 | recall 추가 하락 | 임계 0.4 는 유효 신뢰도 기준 — flagship_prob 0.57 이상이면 통과(0.57×0.7=0.4) |
| weekend_gap_up 가중치 재배분으로 기존 신호 약화 | 기존 탐지기 신호 점수 변동 | legacy_detectors 유효성 사전 검증, 분할안 fallback |
| YAML 자동패치 + 배포 충돌로 조정값 소실 | 자가개선 효과 무력화 | 위 "배포 시 YAML 리셋 위험" 모니터링/백업 |
| 요일 판정 공휴일 누락 | 연휴 후 윈도우 미확장 | KRX_EXTRA_HOLIDAYS 동기화 확인, 역일 차 기반 판정으로 공휴일도 포착 |

## 검증 (Verification)

각 REQ 의 구체적·테스트 가능한 합격 기준은 acceptance.md 참조.
- 백엔드 변경 검증: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`
- 임포트 정합성: `cd backend && uv run python -c "from app.main import app; print('OK')"`
- 가중치 합산: `validate_ensemble_weights` 가 1.0 통과 확인.
