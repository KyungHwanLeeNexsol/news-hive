---
id: SPEC-AI-050
version: 0.1.0
status: draft
created: 2026-06-17
updated: 2026-06-17
phase: tasks
development_mode: DDD
---

# SPEC-AI-050 태스크 분해 (Tasks)

DDD(ANALYZE-PRESERVE-IMPROVE) 사이클 기준 원자적 태스크. 각 태스크는 단일
DDD 사이클로 완료 가능하며 REQ 매핑과 의존성을 명시한다.

> [중요] `surge_detector.py`(TASK-002/004/008)와 `surge_settings.py`(TASK-003/007),
> `surge_auto_improver.py`(TASK-005/006)는 **동일 파일을 공유**하므로 병렬 실행
> 금지. 표기된 의존성 순서대로 순차 실행한다.

---

## TASK-001 — REQ-2: BEAR 레짐 news_window_hours 12 → 24 (YAML-only)

- **REQ 매핑**: REQ-2 (AC-2.1)
- **의존성**: 없음 (최우선, 위험 최저)
- **대상 파일**: `backend/app/surge_config/surge_detection.yaml`
- **변경 내용**: `regime_detector_params.BEAR.news_window_hours: 12 → 24` (line 98)
- **DDD ANALYZE 포인트**: line 96-99 의 주석은 `min_news_sentiment 0.50→0.35`
  변경 이력이고, news_window_hours 12 는 별개 값. 변경 대상은 line 98 의 12 단일.
  `RegimeDetectorParams.news_window_hours: int = 24` (settings.py:26) 기본값과
  일치시키는 방향.
- **PRESERVE**: `get_surge_config().regime_detector_params["BEAR"]` 로드가
  변경 후에도 Pydantic 검증 통과하는지 characterization (다른 BEAR 필드 불변).
- **IMPROVE**: 값 변경 + AC-2.1 테스트.
- **완료 기준**: `get_surge_config().regime_detector_params["BEAR"].news_window_hours == 24`.
  AC-2.2(클램프)는 TASK-006 으로 이관(auto-improver가 유일한 프로그램적 writer).

## TASK-002 — REQ-1: 요일 기반 동적 news_window_hours 헬퍼 + 주입

- **REQ 매핑**: REQ-1 (AC-1.1, AC-1.2, AC-1.3, AC-1.4)
- **의존성**: 없음 (TASK-008 이 이 헬퍼를 재사용 → M5 선행 조건)
- **대상 파일**: `backend/app/services/surge_detector.py`
- **변경 내용**:
  - 신규 `_resolve_dynamic_news_window(base_hours: int, run_dt: datetime) -> int`
    헬퍼: 월요일 또는 직전 거래일이 2 역일 이상 이전이면 `min(72, base_hours*4)`,
    아니면 base_hours. 확장 시 로그.
  - 직전 거래일 판정은 `surge_trading_service._get_prev_business_day` +
    `KRX_EXTRA_HOLIDAYS` 재사용 (역일 차 = `run_dt.date() - prev_bday).days >= 2`).
  - `detect_volume_surge_news_combo` cfg 재구성(455-464)에서
    `news_window_hours=_resolve_dynamic_news_window(regime_params.news_window_hours, now)`.
- **DDD ANALYZE 포인트**: surge_detector.py:455-466. 현행 흐름은
  `cfg = VolumeNewsComboConfig(news_window_hours=regime_params.news_window_hours)`
  → `news_cutoff = now - timedelta(hours=cfg.news_window_hours)`. 주입 지점은
  cfg 생성 직전. `regime_params is None`(SIDEWAYS 등) 경로도 동적 확장 적용
  여부 결정 필요 — 현재 None 경로는 기본 cfg 사용하므로 base=cfg.news_window_hours.
- **PRESERVE**: 일반 거래일(직전 1역일)에 윈도우 불변 = 기존 동작 유지
  characterization (AC-1.2). 기존 `news_cutoff` 계산식 회귀 없음.
- **IMPROVE**: 헬퍼 추가 + 주입 + 로깅. AC-1.1/1.3(확장), AC-1.4(통합 주입).
- **완료 기준**: AC-1.1~1.4 통과. 월요일 base=12 → 48 반환, 확장 로그 기록.
- **@MX**: `_resolve_dynamic_news_window` 에 @MX:NOTE (요일 가드 단일 진실 공급원).

## TASK-003 — REQ-4(설정): GroupCascadeConfig companion 필드 추가

- **REQ 매핑**: REQ-4 (필드 정의), AC-4.4 기반
- **의존성**: 없음 (surge_settings.py — TASK-007 과 순차)
- **대상 파일**: `backend/app/surge_config/surge_settings.py`
- **변경 내용**: `GroupCascadeConfig`(374-386)에
  `require_companion_detector: bool = True`,
  `companion_required_below_prob: float = 0.4` 추가.
- **DDD ANALYZE 포인트**: [정정] `GroupCascadeConfig` 는 YAML 에서 로드되지
  **않고** `fund_manager.py:3898 cascade_cfg = GroupCascadeConfig()` 로 **기본값
  인스턴스화**된다. surge_detection.yaml 에 `group_cascade:` 섹션 부재. 따라서
  Pydantic 기본값(True/0.4)만으로 가드가 활성화되며, plan.md M3 의 "YAML
  group_cascade 섹션 추가"는 fund_manager 로더 변경 없이는 무효 → **YAML 추가
  불필요, Pydantic 기본값으로 충분**.
- **PRESERVE**: 기존 7개 필드 기본값/타입 불변. `GroupCascadeConfig()` 인스턴스화
  회귀 없음.
- **IMPROVE**: 2개 필드 추가.
- **완료 기준**: `GroupCascadeConfig().require_companion_detector is True`,
  `.companion_required_below_prob == 0.4`.

## TASK-004 — REQ-4(가드): detect_group_cascade_signals companion 가드 삽입

- **REQ 매핑**: REQ-4 (AC-4.1, AC-4.2, AC-4.3, AC-4.4)
- **의존성**: TASK-003 (필드), TASK-002 (동일 파일 순차)
- **대상 파일**: `backend/app/services/surge_detector.py`
- **변경 내용**: `detect_group_cascade_signals`(2300-2488) cascade 발행 단계에
  가드 삽입. 유효 신뢰도 `confidence = flagship_prob * decay_factor`(2421)가
  `companion_required_below_prob` 미만이고 `existing_today[affiliate.id]` 에
  group_cascade 외 signal_type 이 없으면 best_cascade 등록 스킵. 차단 건수 로그.
- **DDD ANALYZE 포인트**: 2413-2429. 현행 dedup 가드는 `existing_types`(2417)가
  비어있지 않으면 무조건 skip(2418-2419). companion 가드는 이 직후, confidence
  계산(2421) 전후에 삽입. `require_companion_detector=False` 시 SPEC-AI-027 기존
  동작 우회(AC-4.4). 주의: existing_today 는 `signal_type` 단위이며 cascade 본인
  signal_type 은 "surge_candidate" — group_cascade 외 판정은 surge_basis 메타
  의존이 아니라 signal_type set 으로 근사(SPEC AC-4.1/4.2 가 existing_today set
  기준으로 명시).
- **PRESERVE**: AC-4.3(고확률 단독 통과) + AC-4.4(가드 off) 로 SPEC-AI-027
  기존 cascade 발행 동작 characterization. flagship 판정(2373-2390) 무변경.
- **IMPROVE**: 가드 + 차단 카운트 로그.
- **완료 기준**: AC-4.1(0.35 단독 차단), AC-4.2(0.35+동반 허용),
  AC-4.3(0.49 단독 허용), AC-4.4(off 시 레거시) 통과.
- **@MX**: 가드 분기에 @MX:WARN + @MX:REASON (저확률 cascade 노이즈 억제).

## TASK-005 — REQ-3(PRESERVE): _replace_yaml_value 정수 포맷 분기

- **REQ 매핑**: REQ-3 (int 포맷 회귀 방지, AC-3.1/3.2 전제)
- **의존성**: TASK-001 (BEAR=24 baseline)
- **대상 파일**: `backend/app/services/surge_auto_improver.py`
- **변경 내용**: `_replace_yaml_value`(96-144) line 134 `f"{new_val:.4f}"` 가
  `news_window_hours` 경로에 적용되면 `24.0000` 생성. dot-path 마지막 키가
  `news_window_hours` 이거나 정수형 파라미터일 때 `int(new_val)` 포맷 분기 추가.
- **DDD ANALYZE 포인트**: 이 함수는 (a) 가중치/min_score 패치(.4f 필수),
  (b) R12 롤백(389-393, old_value=Float), (c) REQ-3 윈도우 패치 3경로에서
  공유된다. 정수 분기는 **반드시 news_window_hours 경로에만** 적용해 기존
  가중치 .4f 포맷을 보존해야 한다 (fan_in 다중 호출자).
- **PRESERVE**: 기존 가중치 패치(`ensemble.weights.theme_cluster` 등)가 여전히
  `.4f` 로 기록되는 characterization 테스트. R12 롤백 시 가중치 .4f 유지.
- **IMPROVE**: 정수 경로 분기 1개.
- **완료 기준**: `news_window_hours` 패치 시 `24`(정수) 기록, 가중치 패치 시
  `0.2500` 유지.
- **@MX**: `_replace_yaml_value` 포맷 분기에 @MX:WARN + @MX:REASON (YAML 직접
  쓰기 + 다중 호출자).

## TASK-006 — REQ-3(로직) + REQ-2 클램프: 자가개선 윈도우 확장

- **REQ 매핑**: REQ-3 (AC-3.1, AC-3.2, AC-3.3, AC-3.4), REQ-2 (AC-2.2 클램프)
- **의존성**: TASK-005 (int 포맷), TASK-001 (baseline)
- **대상 파일**: `backend/app/services/surge_auto_improver.py`
- **변경 내용**: `analyze_and_improve` Step 4(318-344)와 Step 6(398-417) 사이에
  윈도우 확장 로직 추가:
  - 트리거: 최근 3일 recall=0(`recall_values[:3]` 모두 0) AND 윈도우 내 detector
    contribution 합=0(`sum(detector_total.values())==0`).
  - 활성 레짐의 `regime_detector_params.{regime}.news_window_hours += 12` (상한 48,
    하한 클램프 24 = AC-2.2).
  - dot-path `regime_detector_params.{regime}.news_window_hours` 를 `yaml_updates`
    에 추가 → 기존 `_patch_yaml_values` + `reload_surge_config()` 경유(EC-3: min_score
    와 동시 패치 시 reload 1회).
  - `SurgeAutoImprovementLog(parameter_path=dot-path, old, new)` 기록 → R12
    롤백 자동 포함(AC-3.4).
  - 48h 도달 시 미조정 + 로그만(AC-3.2).
- **DDD ANALYZE 포인트**: Step 2(176-260)에서 `detector_total`/`recall_values`
  데이터가 이미 동일 스코프에 존재 → 신규 쿼리 불필요. Step 5 R12 롤백(347-396)은
  parameter_path 무관하게 prev_logs 전체를 롤백하므로 윈도우 로그 자동 호환.
  활성 레짐 판정 방법 확인 필요(regime_detector 호출부 또는 today_eval 의 regime
  필드) — ANALYZE 시 활성 레짐 소스 확정.
- **PRESERVE**: recall>0 시 윈도우 미조정(AC-3.3) + 기존 min_score ±0.02 로직
  (333-340) 불변 characterization. 가중치 조정 경로 회귀 없음.
- **IMPROVE**: 윈도우 확장 + 클램프 + 로그.
- **완료 기준**: AC-3.1(24→36), AC-3.2(48 상한), AC-3.3(recall 회복 시 미조정),
  AC-3.4(R12 롤백), AC-2.2(<24 클램프) 통과.
- **@MX**: 윈도우 확장 분기에 @MX:WARN + @MX:REASON.

## TASK-007 — REQ-5(앙상블): weekend_gap_up 가중치 필드 + 검증 + YAML 재배분

- **REQ 매핑**: REQ-5 (AC-5.5)
- **의존성**: TASK-003 (surge_settings.py 동일 파일 순차)
- **대상 파일**: `backend/app/surge_config/surge_settings.py`,
  `backend/app/surge_config/surge_detection.yaml`
- **변경 내용**:
  - `EnsembleWeightsConfig`(109-117)에 `weekend_gap_up: float = 0.0` 추가.
  - `validate_ensemble_weights`(286-299) 합산에 `w.weekend_gap_up` 포함(6개 합 1.0).
  - YAML `ensemble.weights`: `legacy_detectors: 0.10 → 0.00`,
    `weekend_gap_up: 0.10` 신설(합 1.0 유지).
- **DDD ANALYZE 포인트**: validate_ensemble_weights 는 @MX:ANCHOR(283) — 합산
  무결성 불변 계약. [설계 결정 필요] legacy_detectors 0.00 vs 분할안 0.05/0.05
  (REQ-5 대안). **운영자 승인 사항** — plan.md 6번. 또한 `_DETECTORS`
  (auto_improver:37)에 weekend_gap_up 포함 여부는 별도 결정: weekend_gap_up 는
  coverage-expansion 탐지기(앙상블 스코어 비참여, surge_candidate 직접 발행)이므로
  _DETECTORS 자동조정 대상에 넣으면 기여도=0 으로 가중치가 0.05 floor 로
  수렴할 위험. **권고: _DETECTORS 미포함, 가중치는 합산 무결성용 nominal 필드**.
- **PRESERVE**: 기존 5개 가중치 합 1.0 검증 + ValueError 경로 characterization.
- **IMPROVE**: 필드 + 검증 + YAML 재배분.
- **완료 기준**: AC-5.5(합 1.0, weekend_gap_up 필드 존재) 통과.

## TASK-008 — REQ-5(탐지기+배선): detect_weekend_gap_up_signals + fund_manager 배선

- **REQ 매핑**: REQ-5 (AC-5.1, AC-5.2, AC-5.3, AC-5.4) + DoD 통합 테스트
- **의존성**: TASK-002 (요일 가드 헬퍼), TASK-004 (surge_detector.py 순차),
  TASK-007 (가중치 필드)
- **대상 파일**: `backend/app/services/surge_detector.py`,
  `backend/app/services/fund_manager.py`
- **변경 내용**:
  - 신규 `detect_weekend_gap_up_signals(db)`: (a) 최근 10거래일
    `SurgeActualOutcome.was_surge=True` 종목 조회, (b) 섹터-활성테마 매칭,
    (c) `_resolve_dynamic_news_window` 와 동일 요일 가드로 활성화 판정(AC-5.4),
    (d) signal_type="surge_candidate" + surge_metadata.surge_basis 에
    "weekend_gap_up" 포함.
  - `_run_coverage_expansion_signals`(fund_manager.py ~3804)에 블록 8 로 배선
    (기존 블록 1-7 과 동일 try/except 격리 패턴, 3894-3902 group_cascade 직후).
- **DDD ANALYZE 포인트**: 활성 테마 매칭 소스 확정 필요 — theme_cluster
  sector_theme_map(yaml) 역방향 매핑 또는 최근 뉴스 테마 집계. SurgeActualOutcome
  최근 10거래일 조회는 `_get_prev_business_day` 반복 또는 trading_date 정렬
  상위 N. 시가 미가용(가정 6) → 갭은 이력+테마 근사만.
- **PRESERVE**: `_run_coverage_expansion_signals` 의 기존 블록 1-7 동작 불변
  (try/except 격리로 weekend_gap_up 실패 시 기존 결과 보존, EC-2 빈 outcome).
- **IMPROVE**: 탐지기 + 배선.
- **완료 기준**: AC-5.1(이력+테마 탐지), AC-5.2(이력 없음 미탐), AC-5.3(테마
  불일치 미탐), AC-5.4(평일 비활성) + DoD: 월요일 시나리오에서 최소 1종목 포착
  통합 테스트.
- **@MX**: `detect_weekend_gap_up_signals` 공개 탐지기 → @MX:NOTE(+ fan_in 증가
  시 @MX:ANCHOR).

---

## 의존성 그래프

```
TASK-001 (REQ-2 YAML) ─────────────┐
                                   ├─→ TASK-005 (int포맷) ─→ TASK-006 (REQ-3+클램프)
TASK-002 (REQ-1 헬퍼) ──┬──────────┘
                        ├─→ TASK-008 (REQ-5 탐지기+배선)
TASK-003 (REQ-4 필드) ──┼─→ TASK-004 (REQ-4 가드) ──┘
                        └─→ TASK-007 (REQ-5 가중치) ─→ TASK-008
```

권장 실행 순서(파일 충돌 회피, 순차): TASK-001 → TASK-002 → TASK-003 →
TASK-004 → TASK-005 → TASK-006 → TASK-007 → TASK-008.

병렬 가능 묶음(파일 비중첩 시): {TASK-001(yaml), TASK-002(detector),
TASK-003(settings)} 는 서로 다른 파일이나, TASK-002·TASK-004·TASK-008 이
detector.py 를, TASK-003·TASK-007 이 settings.py 를 공유하므로 안전을 위해
순차 권장.

## 품질 게이트 (전 태스크 공통)

- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과
- `cd backend && uv run ruff check .` 통과
- `cd backend && uv run python -c "from app.main import app; print('OK')"` 통과
- `validate_ensemble_weights` 합 1.0 (TASK-007 이후)
- 신규 코드 커버리지 85%+
- 테스트 파일: `backend/tests/test_spec_ai_050_*.py`
