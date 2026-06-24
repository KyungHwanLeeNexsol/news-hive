# 구현 계획 (Implementation Plan): SPEC-AI-063

## 개요 (Overview)

`volume_breakout` 탐지기에 독립 시그널 우회 경로를 추가한다. 기존 `immediate_disclosure_bypass` / `strong_single_bypass` 우회 경로와 동일한 구조를 따른다(brownfield 패턴 재사용).

핵심 통찰: 이미 검증된 우회 경로 2종이 `compute ensemble score + threshold filter` 루프 직후에 존재한다. 본 SPEC은 세 번째 우회 경로를 동일한 위치에 동일한 패턴으로 삽입한다.

## 델타 마커 범례 (Delta Marker Legend)

- `[EXISTING]` — 변경하지 않는 기존 코드 컨텍스트
- `[MODIFY]` — 변경 대상 기존 코드
- `[NEW]` — 신규 설정 키 / 신규 함수 파라미터 / 신규 코드 경로

---

## 변경 대상 파일 (Files to Modify)

### 파일 1: `backend/app/surge_config/surge_settings.py`

Pydantic 설정 모델에 신규 필드를 추가한다. (YAML 로딩의 source of truth)

`[EXISTING]` `class VolumeBreakoutConfig(BaseModel)` (line ~111-126) — `enabled`, `max_candidates`, `volume_ratio_threshold`, `baseline_days`, `min_history_days`, `confidence_denominator`, `max_score` 보유.

`[NEW]` `VolumeBreakoutConfig`에 `volume_breakout_bypass_threshold: float = 0.30` 필드 추가.
- **WHERE**: `max_score: float = 0.50` 라인 직후.
- **WHAT**: 우회 경로 발동 임계값. 후보의 `volume_breakout_score`가 이 값 이상이면 앙상블 임계 우회.
- **WHY**: REQ-063-002는 이 키가 `ensemble` 블록이 아니라 `volume_breakout` 블록에 위치하도록 명시한다. 이는 기존 두 우회 임계값(`EnsembleConfig` 소유)과 다른 위치이며, **의도적 설계 결정**이다 — 탐지기 전용 튜닝 파라미터를 탐지기 설정과 co-locate한다.

`[EXISTING]` `class EnsembleConfig(BaseModel)` (line ~146-163) — `strong_single_bypass_threshold`, `immediate_disclosure_bypass_threshold` 보유. **변경하지 않음** (참조 패턴으로만 사용).

**설계 주의 (Design Note)**: 우회 임계값의 위치 불일치를 plan에 명시한다. 향후 일관성 검토 시 세 우회 임계값을 한 곳으로 모으는 리팩토링을 고려할 수 있으나, 본 SPEC 범위 밖이다.

---

### 파일 2: `backend/app/surge_config/surge_detection.yaml`

`[EXISTING]` `volume_breakout` 블록 (line ~187-194):
- `enabled: true`, `max_candidates: 100`, `volume_ratio_threshold: 3.0`, `baseline_days: 20`, `min_history_days: 10`, `confidence_denominator: 8.0`, `max_score: 0.50`

`[NEW]` `volume_breakout` 블록에 `volume_breakout_bypass_threshold: 0.30` 키 추가.
- **WHERE**: `max_score: 0.50` 라인 직후, `volume_breakout` 블록 내부.
- **WHAT**: 단독 시그널 우회 임계값 기본 0.30.
- **주석**: 우회 경로의 의미와 기본값 근거(0.06 앙상블 기여 vs 0.43 임계값 격차 해소)를 한글 주석으로 부기.

`[EXISTING]` `ensemble:` 블록의 `strong_single_bypass_threshold: 0.85`, `immediate_disclosure_bypass_threshold: 0.85` (line ~83/86) — **변경하지 않음**.

`[EXISTING]` `ensemble.weights.volume_breakout: 0.12` (line ~68) — **변경하지 않음**. 우회 경로는 가중치와 무관.

---

### 파일 3: `backend/app/services/surge_detector.py`

앙상블 스코어링 + 우회 경로 루프 다음에 신규 우회 경로를 삽입한다.

`[EXISTING]` 병합 루프 (line ~1373-1382) — `breakout_results = detect_volume_breakout(db, config)`로 단독 후보가 `merged` 딕셔너리에 진입 (`else: merged[candidate.stock_code] = candidate`). **변경하지 않음**.

`[EXISTING]` 앙상블 스코어링 + 임계 필터 (line ~1463-1482) — `for candidate in merged.values(): score = compute_ensemble_score(...)`; `if score >= effective_threshold: qualified.append(...)`. **변경하지 않음**.

`[EXISTING]` 우회 경로 1 — immediate_disclosure (line ~1484-1503): `for candidate in merged.values(): if candidate.stock_code not in qualified_codes and candidate.immediate_disclosure_score >= _immediate_bypass_threshold: ... qualified.append(...)`.

`[EXISTING]` 우회 경로 2 — strong_single (line ~1505-1529): theme/combo 강한 단일 신호 우회. 동일 패턴.

`[NEW]` 우회 경로 3 — volume_breakout 우회 경로 삽입.
- **WHERE**: 우회 경로 2(strong_single, line ~1529) 직후, `qualified.sort(...)` (line ~1531) 직전.
- **WHAT (로직 서술 — 코드 아님)**:
  1. `volume_breakout` 우회 임계값을 설정에서 읽음: `config.volume_breakout.volume_breakout_bypass_threshold`.
  2. `merged.values()` 순회하며 다음 조건을 만족하는 후보 선별:
     - `candidate.stock_code not in qualified_codes` (REQ-063-004, REQ-063-008: 이미 자격 획득한 후보 제외 → 중복/인플레이션 방지)
     - `candidate.volume_breakout_score >= bypass_threshold` (REQ-063-001)
  3. 조건 충족 시 `qualified`에 추가하고 `qualified_codes`에 등록.
  4. 우회 발동 로그 기록 (기존 우회 경로와 동일한 `logger.info` 스타일).
- **WHY**: REQ-063-001. `qualified_codes` 가드로 REQ-063-004/008(중복 금지)을 구조적으로 보장한다 — 기존 두 우회 경로와 동일한 안전장치.

`[NEW]` composite_score 주입 (REQ-063-003).
- **DESIGN DECISION 필요 (구현 단계에서 확정)**: 현재 surge_candidate 경로는 `composite_score`를 설정하지 않는다(메모리 검증: surge path는 confidence/surge_metadata만 설정, composite_score는 항상 NULL). REQ-063-003은 우회 후보의 `composite_score`를 `volume_breakout_score`로 설정하도록 요구한다.
- **WHERE**: 우회 경로에서 자격 획득한 후보가 `FundSignal`로 변환되는 지점. 두 가지 선택지를 구현 단계에서 평가:
  - (A) `SurgeCandidate`에 우회 출처 플래그를 표기하고, FundSignal 생성 시점에 해당 플래그 기반으로 `composite_score = volume_breakout_score` 주입.
  - (B) 우회 경로에서 즉시 후보의 composite 관련 필드를 세팅.
- **WHAT**: 우회 후보만 `composite_score = volume_breakout_score`. 메인 앙상블 통과 후보는 영향 없음.
- **WHY**: 매수 실행 시점 신뢰도를 정확히 반영. 앙상블 점수(0.06 수준)는 우회 후보의 실제 신뢰도를 과소표현하므로 사용 금지.

`[EXISTING]` `surge_candidate_to_signal_metadata()` (line ~1597-1612) — `surge_basis`를 `candidate.active_detectors`에서 파생. **변경 불필요**.
- **KEY INSIGHT (REQ-063-001 자동 충족)**: `detect_volume_breakout()`가 `active_detectors=["volume_breakout"]`를 부여하므로, 단독 우회 후보는 자동으로 `surge_basis=["volume_breakout"]`를 획득한다. 명시적 surge_basis 설정 코드는 불필요.
- **주의**: 단독 breakout 후보가 legacy 점수 부여 루프(line ~1399-1403)에서 `legacy`를 획득하면 `active_detectors=["volume_breakout", "legacy"]`가 될 수 있다. 이 경우 `surge_basis`에 `legacy`가 포함되나, 이는 의도된 동작(실제로 legacy 탐지기도 발동한 것)이며 REQ-063-001의 "MUST have surge_basis=['volume_breakout']" 해석상 허용 범위인지 구현 단계에서 확인. 순수 단독(legacy 미발동) 후보는 `["volume_breakout"]` 단일이다.

`[EXISTING]` `qualified.sort(...)` (line ~1531) 및 sector_contagion 게이트 (line ~1545-1592) — **변경하지 않음**. 우회 후보도 동일하게 sector_contagion 게이트를 거친다(일관성).

---

### 파일 4: `backend/app/services/surge_auto_improver.py`

`volume_breakout_bypass_threshold`를 자동 개선 파라미터로 추적한다 (REQ-063-005).

`[EXISTING]` Step 4 — `min_score_for_signal` 조정 (line ~532-558): `recall`/`precision` 기반 `delta` 계산 후 `new_min_score = max(0.35, min(0.65, current + delta))` 클램핑. **참조 패턴**.

`[EXISTING]` `_write_auto_yaml({...})` (line ~587) + `reload_surge_config()` (line ~588) — auto.yaml에 dot-path로 값 기록. **참조 패턴**.

`[EXISTING]` `SurgeAutoImprovementLog` 기록 패턴 (line ~590-600) — `parameter_path`, `old_value`, `new_value`, `rationale`. **참조 패턴**.

`[NEW]` `volume_breakout_bypass_threshold` 자동 조정 블록 추가.
- **WHERE**: Step 4(min_score 조정) 인근, 또는 별도 Step으로 분리. 구현 단계에서 응집도 판단.
- **WHAT (로직 서술 — 코드 아님)**:
  1. 현재 `volume_breakout_bypass_threshold`를 설정에서 읽음.
  2. 평가 지표 기반 delta 결정 — `min_score_for_signal` 조정과 유사한 신호 사용(예: volume_breakout 우회 시그널의 적중률/recall). 정확한 트리거 지표는 구현 단계에서 확정하되, 본 SPEC은 "추적 가능(trackable) + 범위 제한" 만을 요구.
  3. **클램핑 범위 `[0.20, 0.45]`** — `max(0.20, min(0.45, current + delta))`. (REQ-063-005, 기존 min_score의 [0.35, 0.65]와 다른 범위임에 유의)
  4. 변경 시 `_write_auto_yaml({"volume_breakout.volume_breakout_bypass_threshold": new_value})` + `SurgeAutoImprovementLog` 기록.
- **WHY**: REQ-063-005. 우회 임계값이 과도하게 낮으면 노이즈 시그널 폭증, 과도하게 높으면 SPEC-AI-062 도입 목적 무력화. 자동 개선 루프가 적응적으로 균형을 찾는다.
- **dot-path 주의**: 기존 자동 개선 키는 `ensemble.min_score_for_signal`(ensemble 하위). 신규 키는 `volume_breakout.volume_breakout_bypass_threshold`(volume_breakout 하위). `_patch_yaml_values` / `_write_auto_yaml`의 dot-path 탐색이 `volume_breakout.*` 경로를 정확히 패치하는지 구현 단계에서 검증.

`[EXISTING]` `_ALL_WEIGHT_KEYS = [*_DETECTORS, "weekend_gap_up", "volume_breakout"]` (line ~48) 및 가중치 합산 검증 — **변경하지 않음**. 우회 임계값은 가중치가 아니므로 합산 검증과 무관.

---

## 작업 순서 (Task Decomposition — 우선순위 기반)

### Priority High (핵심 우회 경로)

1. **파일 1** — `VolumeBreakoutConfig`에 `volume_breakout_bypass_threshold` 필드 추가. (다른 모든 작업의 선행 조건: 설정 모델이 먼저 존재해야 함)
2. **파일 2** — YAML에 `volume_breakout_bypass_threshold: 0.30` 추가. (파일 1과 짝)
3. **파일 3** — `surge_detector.py`에 우회 경로 3 삽입 (REQ-063-001, 004, 008) + composite_score 주입 (REQ-063-003).

### Priority Medium (평가 정합성)

4. **파일 3 검증** — REQ-063-006: 우회 시그널이 `SurgePredictionEvaluation` 분모에 포함되는지 확인. surge_basis 기반 집계 로직이 `volume_breakout`를 누락하지 않는지 검토. (코드 변경이 필요할 수도, 자동 포함될 수도 있음 — 구현 단계에서 확인)

### Priority Low (자동 개선)

5. **파일 4** — `surge_auto_improver.py`에 `volume_breakout_bypass_threshold` 자동 추적 추가 (REQ-063-005, 범위 [0.20, 0.45]).

---

## 기술적 접근 (Technical Approach)

- **패턴 재사용 우선**: 신규 코드는 최소화하고 기존 두 우회 경로의 구조를 미러링한다. `qualified_codes` 가드는 그대로 REQ-063-004/008의 중복 방지를 보장한다.
- **YAML-우선 변경**: 파일 1/2(설정)는 코드 로직 변경이 아니므로 위험도 최저. 파일 3(detector)가 핵심 로직 변경.
- **auto.yaml 보호**: 자동 개선 값은 `surge_detection.auto.yaml`에 기록되어 `git reset --hard`로부터 보호됨(기존 패턴 준수).

## 위험 (Risks)

- **R1 (composite_score 스케일 혼선)**: surge 경로의 composite_score는 SPEC-AI-036에서 0~1 스케일로 도입 예정/진행 중. `volume_breakout_score`(0~0.50)를 composite_score로 주입할 때 스케일 일관성 확인 필요. → 우회 후보는 `volume_breakout_score`를 그대로 사용(0~0.50)하되, 다운스트림 소비자가 동일 스케일을 기대하는지 검증.
- **R2 (노이즈 시그널 증가)**: 우회 임계 0.30은 `volume_ratio ≈ 2.4배`(0.30 × 8.0 denominator)에서 발동. 과다 시그널 가능성 → 자동 개선 루프(REQ-063-005)가 [0.20, 0.45] 범위에서 균형 조정. 초기 배포 후 우회 시그널 적중률 모니터링.
- **R3 (legacy 동반 발동)**: 단독 breakout 후보가 legacy 점수를 획득하면 `surge_basis`가 단일이 아님. REQ-063-001 해석 범위 내인지 구현 시 확정.
- **R4 (dot-path 패치 실패)**: `volume_breakout.*` 경로가 기존 `ensemble.*` 패턴과 다르므로 `_write_auto_yaml` dot-path 탐색이 정확히 동작하는지 테스트 필수.

## 검증 명령 (Verification — CLAUDE.local.md 기준)

```bash
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"
cd backend && uv run ruff check . && uv run mypy app/
cd backend && uv run python -c "from app.main import app; print('OK')"
```

## @MX 태그 대상 (MX Tag Targets)

- `surge_detector.py` 신규 우회 경로 블록 → `@MX:NOTE` (우회 경로 의도 + REQ-063-001/004 참조).
- `surge_detector.py` composite_score 주입 → `@MX:WARN` + `@MX:REASON` (스케일 혼선 위험 R1).
- `surge_auto_improver.py` 신규 자동 추적 블록 → `@MX:NOTE` (범위 [0.20, 0.45] 근거).
