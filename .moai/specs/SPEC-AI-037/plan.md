# SPEC-AI-037 — 구현 계획 (plan.md)

> 시간 추정 없음. 우선순위 라벨(High/Medium/Low)과 단계 순서로만 표기.
> 원칙: YAML 전용 변경을 먼저 적용해 위험을 최소화하고, 코드 변경은 예외 격리하여 후속 적용한다(research.md §10).

## 기술적 접근 요약

본 SPEC의 변경은 두 부류로 나뉜다:
1. **YAML 전용** — `surge_detection.yaml` 값/리스트 수정. 코드 변경 없음, 회귀 위험 최소. (REQ-001/002a/003a/004)
2. **코드 변경** — `surge_threshold_service.py`, `surge_detector.py`의 게이트/쿼리 분기 추가. 모두 예외 격리. (REQ-002b/003b/005)

핵심 게이트 위치(research.md §5):
- `is_combo_theme_gate_passed` — `backend/app/services/surge_threshold_service.py:238~272`
- 호출부 `execute_buy_orders` — `backend/app/services/surge_trading_service.py:692~707`

---

## 구현 단위 (Implementation Units)

### Unit 1 — 테마 키워드/섹터 매핑 확장 [Priority: High] [YAML-only]

대상: `backend/app/surge_config/surge_detection.yaml`

- `theme_cluster.keywords`에 신규 테마 키워드 추가: 게임, 엔터, 조선, 해운물류, 건설부동산, 음식료, 화학소재.
- `theme_cluster.sector_theme_map`에 동일 키 추가, 매핑 섹터는 `seed/sectors.py` `_SNAPSHOT` 정본 이름만 사용(spec.md REQ-037-001 권장 매핑).
- 코드 변경 불필요: detector가 `cfg.keywords`/`cfg.sector_theme_map`를 동적 순회(surge_detector.py 216, 238).

검증: `get_surge_config()` 로드 성공(Pydantic 검증 통과), keywords 개수 >= 20.

### Unit 2 — 기존 매핑 정본 대조 및 수정 [Priority: High] [YAML-only]

대상: `backend/app/surge_config/surge_detection.yaml`

- 기존 13개 테마 + 신규 테마의 전체 섹터명을 `_SNAPSHOT` 정본과 대조.
- 정본에 없는 이름 발견 시 정본 이름으로 교체(`음식료품`→`식품`/`음료`, `운송장비`→`조선`, `미디어`→`방송과엔터테인먼트` 등).
- research.md §2 기준 기존 13개 매핑은 깨진 이름 없음 확인됨 — 신규 테마 매핑만 집중 검증.

검증: sector_theme_map 전체 섹터명 100% 정본 존재(AC-037-004).

### Unit 3 — combo_zero_theme_floor 단순 하향 [Priority: High] [YAML-only]

대상: `backend/app/surge_config/surge_detection.yaml`

- `adaptive_threshold.combo_zero_theme_floor`: 0.7 → 0.55(또는 0.60).
- 코드 변경 불필요: `AdaptiveThresholdConfig.combo_zero_theme_floor` 필드가 YAML 값을 읽음(surge_settings.py 188).

검증: combo=0 & 0.55 <= theme < 0.7 종목이 매수 게이트 통과(AC-037-002 part a).

### Unit 4 — 시총 필터 조정 [Priority: Medium] [YAML-only 또는 코드]

대상: `backend/app/surge_config/surge_detection.yaml` (+ 옵션 b 선택 시 `backend/app/services/surge_detector.py`)

- 옵션 (a) YAML-only: `min_market_cap_krw`: 100000000000 → 50000000000(500억).
- 옵션 (b) 코드: 1000억 유지 + `surge_detector.py:261~269` 시총 쿼리에 `immediate_disclosure_score >= 0.80` 우회 분기.
- 운영 판단으로 (a)를 우선 권장(YAML-only, 위험 최소). (b)는 별도 결정 시 적용.

검증: 선택 옵션에 따른 소형주 포함 동작 확인(AC-037-003).

### Unit 5 — combo_zero_theme_floor 조건부 적용 [Priority: Medium] [코드]

대상: `backend/app/services/surge_threshold_service.py` (`is_combo_theme_gate_passed`)

- `surge_metadata`에서 `volume_z_score`(또는 동등 지표) 읽기.
- `volume_z_score >= 3.0`이면 완화 floor 대신 기존 0.7 유지(과열 추격 억제).
- 신규 로직 예외 격리: 메타데이터 누락/파싱 실패 시 기존 floor 비교로 폴백.

검증: 과열 종목(z>=3.0)은 완화 floor 미적용 확인(AC-037-002 part b).

### Unit 6 — 비테마 fast path [Priority: Medium] [코드]

대상: `backend/app/services/surge_threshold_service.py` (`is_combo_theme_gate_passed`)

- `theme_cluster_score == 0.0`이고 `combo_score == 0.0`인 경우에도, `disclosure_pattern_score >= 0.70` 또는 (`combo_score >= 0.80` & 비과열) 조건 만족 시 `True` 반환(게이트 통과).
- 명시적 bypass 분기로 추가, 기존 `return theme_score >= floor` 이전에 평가.
- 예외 격리: 점수 키 누락 시 fast path 미적용, 기존 동작 유지.

검증: theme=0 & disclosure_pattern_score >= 0.70 종목 통과(AC-037-005).

### Unit 7 — 회귀 검증 [Priority: High] [테스트]

대상: `backend/tests/` (surge 관련 테스트), `surge_detection.yaml` 로드 검증

- 기존 SPEC-AI-029/030/036 테스트 전부 실행 후 통과 확인.
- 신규 분기 단위 테스트 추가(완화 floor, 조건부 적용, fast path).
- `CLAUDE.local.md` 검증 명령: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`.

검증: 회귀 0건(AC-037-006).

---

## 파일 수정 목록

| 파일 | 변경 유형 | 관련 Unit |
|------|-----------|-----------|
| `backend/app/surge_config/surge_detection.yaml` | keywords/sector_theme_map/combo_zero_theme_floor/min_market_cap_krw | Unit 1,2,3,4a |
| `backend/app/services/surge_threshold_service.py` | is_combo_theme_gate_passed 분기 추가 | Unit 5,6 |
| `backend/app/services/surge_detector.py` | 시총 쿼리 우회 분기(옵션 b 선택 시만) | Unit 4b |
| `backend/tests/test_services/*surge*` | 신규/회귀 테스트 | Unit 7 |

읽기 전용 참조(변경 없음): `backend/app/seed/sectors.py`(정본 대조), `backend/app/surge_config/surge_settings.py`(필드 정의).

---

## 우선순위 실행 순서

1. **High / YAML-only 먼저**: Unit 1 → Unit 2 → Unit 3 (테마 확장 + 정본 대조 + floor 하향). 이 단계만으로 가장 큰 커버리지 개선 + 최소 위험.
2. **Medium / 코드 변경**: Unit 4(시총) → Unit 5(조건부 floor) → Unit 6(fast path). 예외 격리 적용.
3. **High / 검증**: Unit 7. 단, YAML-only 단계(1~3) 완료 후에도 즉시 회귀 일부 실행 권장.

---

## 리스크 평가

| 리스크 | 영향 | 완화책 |
|--------|------|--------|
| 신규 테마 섹터명 오타로 0건 매칭 | 신규 테마 무력화(조용한 실패) | Unit 2 정본 대조 필수, AC-037-004로 100% 검증 |
| floor 하향으로 약신호 비테마 종목 과다 진입 | 승률 하락 | 0.55~0.60 보수적 설정, 적응형 임계값(AI-029) + chase guard(AI-030)가 상위에서 추가 필터 |
| SPEC-AI-036 품질 floor와 동일 함수 영역 충돌 | merge 충돌/로직 중복 | 작업 전 SPEC-AI-036 변경분 확인, 더 엄격한 floor 우선 적용 원칙 |
| fast path가 과거 -7.7% combo 실패 패턴 재유입(AI-030 근거) | 추격매수 재발 | fast path에 "비과열(chase guard 미발동)" 조건 강제, combo 단독은 disclosure 강신호 동반 시만 |
| 시총 500억 하향으로 유동성 부족 소형주 진입 | 슬리피지/체결 실패 | 옵션 (a) 선택 시 위험 보정 confidence floor 동반(REQ-037-003) |
| 코드 분기 예외로 게이트 전체 실패 | 매수 로직 중단 | 모든 신규 분기 try/except + 기존 동작 폴백(SP-007) |

---

## Definition of Done (요약)

- SP-001~SP-007 전부 충족.
- YAML-only 변경(Unit 1~3, 4a)이 적용되고 `get_surge_config()` 로드 성공.
- 코드 변경(Unit 5,6, 선택적 4b)이 예외 격리됨.
- 기존 SPEC-AI-029/030/036 테스트 + 신규 테스트 전부 통과.
- 상세 기준은 acceptance.md 참조.
