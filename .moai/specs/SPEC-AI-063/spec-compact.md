# SPEC-AI-063 (Compact): volume_breakout 소형주 독립 시그널 우회 경로

- id: SPEC-AI-063 | status: draft | priority: P1 | created: 2026-06-24
- 선행: SPEC-AI-062 (탐지기+컬럼) | 참조패턴: SPEC-AI-018 (bypass)
- 문제: weight(0.12)×max_score(0.50)=0.06 < min_score(0.43) → 단독 시그널 불가

## Requirements

- **REQ-063-001** (Event): When `volume_breakout_score >= bypass_threshold`(default 0.30) AND 앙상블 임계 미통과 → `FundSignal`(surge_basis=["volume_breakout"]) 저장.
- **REQ-063-002** (Ubiquitous): `volume_breakout_bypass_threshold`는 `surge_detection.yaml`의 `volume_breakout` 블록에서 설정 가능 (default 0.30).
- **REQ-063-003** (Event): When 우회 자격 획득 → `composite_score = volume_breakout_score` (앙상블 점수 아님).
- **REQ-063-004** (Unwanted): If 이미 앙상블 경로로 자격 획득 → 우회 경로 중복추가/점수인플레 금지.
- **REQ-063-005** (Optional): Where auto_improver 동작 → `volume_breakout_bypass_threshold` 자동추적, 범위 [0.20, 0.45].
- **REQ-063-006** (State): While precision/recall 평가 → 우회 시그널을 predicted 분모에 포함.
- **REQ-063-007** (Unwanted, 도출): `volume_breakout.enabled=false` → 우회 경로 미실행.
- **REQ-063-008** (Unwanted, 도출): 이미 다른 우회 경로로 `qualified_codes` 등록된 후보 재처리 금지.

## Files

1. `surge_settings.py` — `[NEW]` `VolumeBreakoutConfig.volume_breakout_bypass_threshold: float = 0.30`
2. `surge_detection.yaml` — `[NEW]` `volume_breakout.volume_breakout_bypass_threshold: 0.30`
3. `surge_detector.py` — `[NEW]` 우회 경로 3 (strong_single 직후 ~line 1529, sort 직전) + composite_score 주입
4. `surge_auto_improver.py` — `[NEW]` 우회 임계값 자동추적 (clamp [0.20,0.45], dot-path `volume_breakout.volume_breakout_bypass_threshold`)

## Acceptance (Given-When-Then)

- **S1** REQ-063-001: Given score=0.35 단독 / bypass=0.30 → When 루프 → Then qualified 포함 + surge_basis=["volume_breakout"].
- **S2** 경계: Given score=0.25 단독 → When 루프 → Then qualified 미포함.
- **S3** REQ-063-003: Given score=0.40 우회 → When FundSignal 변환 → Then composite_score=0.40 (≠앙상블 0.06).
- **S4** REQ-063-004: Given theme=0.80+breakout=0.35 앙상블 통과 → When 우회 루프 → Then 재추가 없음 + 점수 불변.
- **S5** REQ-063-008: Given immediate=0.90 이미 등록+breakout=0.35 → When 우회 루프 → Then 재처리 없음.
- **S6** REQ-063-006: Given 우회 시그널 1건(T-1) → When 평가(T) → Then predicted 분모 포함.
- **S7** REQ-063-005: Given bypass=0.30 + 조정 트리거 → When auto 분석 → Then [0.20,0.45] clamp + auto.yaml 기록 + 로그.
- **S8** REQ-063-007: Given enabled=false → When 탐지 → Then 우회 시그널 0건.

## Edge Cases

- EC1: score==bypass(0.30==0.30) → `>=` 포함.
- EC2: breakout+legacy 동반 → surge_basis 둘 다 포함 (의도됨).
- EC3: 우회 후보도 sector_contagion 게이트 적용.
- EC4: 우회 후보 다수 → sort 하위 위치(낮은 앙상블 점수).

## Exclusions

- detect_volume_breakout() 탐지 로직 / 앙상블 가중치(0.12) / 다른 탐지기 우회 임계값 / 실매수 활성화 / DB 마이그레이션 / composite_score 스케일·isotonic(AI-036) / validate_ensemble_weights — 모두 변경 없음.
