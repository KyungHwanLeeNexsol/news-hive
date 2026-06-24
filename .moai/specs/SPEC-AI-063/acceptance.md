# 인수 기준 (Acceptance Criteria): SPEC-AI-063

## 테스트 시나리오 (Given-When-Then)

### 시나리오 1: 단독 volume_breakout 후보가 우회 경로로 시그널 생성 (REQ-063-001)

**Given** 한 종목이 `volume_breakout` 탐지기에서만 발동하여 `volume_breakout_score = 0.35`, `active_detectors = ["volume_breakout"]`를 가지며, 다른 모든 탐지기 점수(theme/combo/disclosure/legacy/news_delayed)는 0이고, 앙상블 점수는 0.06으로 `min_score_for_signal(0.43)` 미달이다.
**And** `surge_detection.yaml`의 `volume_breakout.volume_breakout_bypass_threshold = 0.30`이다.

**When** 앙상블 스코어링 + 우회 경로 루프가 실행된다.

**Then** 해당 후보는 `qualified` 목록에 포함된다.
**And** 생성된 `FundSignal`의 `surge_metadata.surge_basis`에 `"volume_breakout"`이 포함된다.
**And** 우회 발동 로그(`logger.info`)가 기록된다.

---

### 시나리오 2: 임계값 미달 단독 후보는 우회되지 않음 (REQ-063-001 경계)

**Given** 한 종목이 `volume_breakout_score = 0.25`(우회 임계 0.30 미만)를 가지며, 다른 탐지기 점수는 모두 0이고 앙상블 점수도 임계 미달이다.

**When** 우회 경로 루프가 실행된다.

**Then** 해당 후보는 `qualified` 목록에 포함되지 **않는다.**
**And** 해당 종목에 대한 우회 발동 로그가 기록되지 **않는다.**

---

### 시나리오 3: 우회 후보의 composite_score가 volume_breakout_score로 설정됨 (REQ-063-003)

**Given** 한 종목이 `volume_breakout_score = 0.40`인 단독 후보로 우회 경로를 통과한다.

**When** 해당 후보가 `FundSignal`로 변환되어 저장된다.

**Then** 저장된 `FundSignal`의 `composite_score`는 `0.40`(= `volume_breakout_score`)이다.
**And** `composite_score`는 앙상블 점수(0.06)가 **아니다.**

---

### 시나리오 4: 메인 앙상블 통과 후보는 우회 경로의 영향을 받지 않음 (REQ-063-004)

**Given** 한 종목이 `theme_cluster_score = 0.80` + `volume_breakout_score = 0.35`를 가지며, 앙상블 점수가 `effective_threshold` 이상이어서 메인 앙상블 경로로 이미 `qualified_codes`에 등록되었다.

**When** volume_breakout 우회 경로 루프가 실행된다.

**Then** 해당 후보는 우회 경로에서 `qualified`에 **재추가되지 않는다**(중복 없음).
**And** 해당 후보의 점수/시그널은 우회 경로 추가 전후로 **변동이 없다**(인플레이션 없음).
**And** 전체 `qualified` 목록의 시그널 개수가 우회 경로 도입 전과 동일하다(단독 우회 후보를 제외하고).

---

### 시나리오 5: 이미 다른 우회 경로로 등록된 후보는 재처리되지 않음 (REQ-063-008)

**Given** 한 종목이 `immediate_disclosure_score = 0.90`으로 immediate_disclosure 우회 경로를 통해 이미 `qualified_codes`에 등록되었으며, 동시에 `volume_breakout_score = 0.35`도 가진다.

**When** volume_breakout 우회 경로 루프가 실행된다.

**Then** 해당 후보는 volume_breakout 우회 경로에서 **재처리되지 않는다**(이미 `qualified_codes`에 존재).
**And** `qualified` 목록에 중복 항목이 발생하지 않는다.

---

### 시나리오 6: 우회 시그널이 precision/recall 평가 분모에 포함됨 (REQ-063-006)

**Given** `volume_breakout` 우회 경로로 생성된 시그널 1건이 특정 거래일(T-1)에 저장되어 있다.

**When** `SurgePredictionEvaluation`의 precision/recall 평가가 T일에 수행된다.

**Then** 해당 우회 시그널은 예측 후보(predicted candidates) 집계에 **포함된다.**
**And** 평가 로직이 `surge_basis=["volume_breakout"]` 시그널을 누락하거나 제외하지 않는다.

---

### 시나리오 7: 자동 개선 루프가 우회 임계값을 범위 내에서 조정 (REQ-063-005)

**Given** 자동 개선 루프(`surge_auto_improver.py`)가 동작하며, 현재 `volume_breakout_bypass_threshold = 0.30`이다.
**And** 평가 지표가 임계값 조정을 트리거하는 상태이다.

**When** 자동 개선 분석이 실행되어 `volume_breakout_bypass_threshold`를 조정한다.

**Then** 조정된 값은 `[0.20, 0.45]` 범위 내로 클램핑된다.
**And** 변경 시 `surge_detection.auto.yaml`에 `volume_breakout.volume_breakout_bypass_threshold` dot-path로 기록된다.
**And** `SurgeAutoImprovementLog`에 변경 이력(old_value, new_value, rationale)이 기록된다.

---

### 시나리오 8: 탐지기 비활성 시 우회 경로 미실행 (REQ-063-007)

**Given** `surge_detection.yaml`의 `volume_breakout.enabled = false`이다.

**When** 급등 후보 탐지가 실행된다.

**Then** `detect_volume_breakout()`는 빈 목록을 반환한다.
**And** volume_breakout 우회 경로는 처리할 후보가 없으므로 어떤 시그널도 우회 생성하지 않는다.

---

## 엣지 케이스 (Edge Cases)

- **EC1**: `volume_breakout_score`가 정확히 `volume_breakout_bypass_threshold`와 동일(0.30 == 0.30)한 경우 → `>=` 비교이므로 우회 발동(포함).
- **EC2**: 단독 breakout 후보가 legacy 점수 부여 루프에서 `legacy`를 동반 획득하여 `active_detectors=["volume_breakout", "legacy"]`가 된 경우 → `surge_basis`에 두 탐지기 모두 포함(의도된 동작). REQ-063-001은 "volume_breakout 포함"을 요구하며 충족됨.
- **EC3**: 우회 후보가 sector_contagion 게이트(섹터 하락 비율 초과)에 걸리는 경우 → 메인 경로 후보와 동일하게 게이트 적용되어 제거됨(일관성 유지).
- **EC4**: `volume_breakout` 우회 후보가 다수일 때 → 모두 `qualified`에 추가되며, `qualified.sort()`는 앙상블 점수 기준 정렬이므로 우회 후보(낮은 앙상블 점수)는 정렬 하위에 위치(정상).

## 품질 게이트 (Quality Gate Criteria)

- [ ] 시나리오 1-8 전체 통과
- [ ] 엣지 케이스 EC1-EC4 검증
- [ ] 기존 surge 테스트 스위트 전량 통과 (회귀 없음)
- [ ] `uv run ruff check .` 0 error
- [ ] `uv run mypy app/` 0 error
- [ ] 테스트 커버리지 85% 이상 (변경 모듈 기준)
- [ ] `from app.main import app` import sanity 통과

## 완료의 정의 (Definition of Done)

- 4개 파일 변경 완료: `surge_settings.py`, `surge_detection.yaml`, `surge_detector.py`, `surge_auto_improver.py`
- REQ-063-001 ~ REQ-063-008 모두 테스트로 검증됨
- 단독 `volume_breakout` 후보(score >= 0.30)가 `surge_basis=["volume_breakout"]`로 시그널 생성됨이 실증됨
- 메인 앙상블 경로 후보의 시그널 수/점수가 우회 경로 도입 전후 불변(REQ-063-004 실증)
- `@MX` 태그가 신규 우회 경로 및 composite_score 주입 지점에 부착됨
- 배포 전 `surge_detection.auto.yaml`의 가중치 합산(5탐지기 0.79 + weekend_gap_up + volume_breakout)이 깨지지 않음 확인 (본 SPEC은 가중치 미변경이나 회귀 방지 차원)
