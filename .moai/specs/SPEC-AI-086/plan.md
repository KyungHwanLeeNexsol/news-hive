# SPEC-AI-086 구현 계획

## 접근 개요

측정 계층 한정 변경. `build_scan_universe`의 배분/상한을 설정 기반으로 유연화하고, non_scannable 원인을
진단 가능하게 만든다. **탐지·발신·매매 경로는 diff 0.** DDD ANALYZE-PRESERVE-IMPROVE + Reproduction-First
(characterization test 선행).

## 세 변경 후보 트레이드오프 분석 (작업 지시 요청)

| 후보 | 실제 효과 (F-1 그림자 유니버스 전제) | 비용 | non_scannable 유형 대응 | 권고 |
|------|--------------------------------------|------|-------------------------|------|
| **① 상한 상향 (150→N)** | 측정 전용. coverage 분모↑, recall 불변, scannable_recall↓ | ≈0 (F-3) | 절단-바운드(a)에만 유효 | REQ-001로 **설정 유연화만** — 진단(REQ-002)이 절단 압력 확인 후에만 의미 |
| **② 신규 소스 풀 (quota 통합)** | 측정 전용. absent(b) 종목을 scannable로 편입 | 신규 풀 소싱 fetch 시 유계 필요 | 소스-부재(b) — 지배적 87% | REQ-003 **권장 핵심**, 단 탐지 배선(Exclusion 1) 없이는 coverage 지표만 상승 |
| **③ 동적 상한 (시간대별)** | 측정 전용. 시간대별 분모 조정 | ≈0 | 한계적 | REQ-004 **선택/저우선**, 탐지 배선 전엔 효용 미미 |

**핵심 결론**: 세 후보 모두 F-1(측정 전용) 하에서는 coverage 지표를 이동시킬 뿐 recall을 올리지 못한다.
coverage 상향이 실제 recall로 전환되려면 **유니버스→탐지 배선(별도 SPEC)이 필수**다. 본 SPEC은 그 배선의
선결 인프라(설정 유연화 + 신규 풀 + 진단)를 정직하게 깔고, 배선 자체는 분리한다.

## 마일스톤 (우선순위 기반, 시간 추정 없음)

- **M1 (P0)**: characterization test 선행 — 현재 `build_scan_universe` 출력(150 절단, 풀 배분)을 고정.
  진단 대상 지점(non_scannable 분류) RED 재현.
- **M2 (P0)**: REQ-001 상한 설정 유연화 + clamp. REQ-007 백워드 호환(기본값 150 = 바이트 동등) 검증.
- **M3 (P0)**: REQ-002 non_scannable 원인 진단(절단 vs 부재) — 로그 + 기존 테이블 재사용, 마이그레이션 회피.
- **M4 (P1)**: REQ-003 신규 소스 풀 + `pool_d_min_slots` quota 통합, 기본 OFF. REQ-005 비용 경계 검증.
- **M5 (P1)**: REQ-004 동적 상한(선택) + REQ-006 지표 정합성 문서화 + REQ-008 관측성.

## 기술적 접근

- `SurgeDetectionConfig`(surge_settings.py:532~550)에 신규 필드: `max_scan_universe` clamp 경계 상수,
  `pool_d_min_slots:int=0`(기본 OFF), 동적 상한 맵(선택). SPEC-AI-076 `reserved_*` 패턴을 pool_d로 확장.
- REQ-002 진단: `SurgeActualOutcome`(actual surgers) ⟕ `SurgeUniverseMember`(entry_pool) 좌외부조인으로
  non_scannable 집합 도출 → 각 종목에 대해 Pool A/B/C raw 멤버십 재판정(절단 vs 부재). 평가 잡
  (`evaluate_surge_predictions`, 18:30 KST) 확장 또는 신규 진단 함수. 계산식·기존 컬럼 불변.
- REQ-005 비용 경계: `_universe_codes`가 탐지기에 재투입되지 않음을 회귀 테스트로 고정(grep/호출그래프 assert).

## 리스크

- **R-1 (측정 착시)**: coverage 상승이 recall 개선으로 오독될 위험. → REQ-006 지표 해석 문서화로 완화.
- **R-2 (신규 풀 fetch 비용)**: Pool D가 Naver를 치면 gather 외 비용 발생. → 유계(bounded) + 기본 OFF.
- **R-3 (범위 오해)**: 사용자가 recall 상향을 기대할 수 있음. → Exclusion 1 + 승인 게이트에서 A/B 분기 확정.
- **R-4 (SPEC-AI-076/078과 인접)**: 배분 로직 공유 함수 변경. → characterization 선행 + floors/OFF 기본값.

## 변경 예상 파일

`surge_detector.py`(build_scan_universe 배분/진단), `surge_settings.py`(설정 필드),
`surge_detection.yaml`(신규 키), 평가/진단 함수(surge_evaluation_service.py 또는 신규), 신규 테스트
`test_spec_ai_086.py`. **마이그레이션 회피 우선.**
