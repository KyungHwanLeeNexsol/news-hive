# SPEC-AI-086 (compact)

> spec.md에서 자동 추출: REQ + Given/When/Then + 변경 파일 + Exclusions. 정본은 spec.md/acceptance.md/plan.md.

## Scope

스캔 유니버스 커버리지 확장 — 측정 계층 한정(진단 우선 + 상한/소스풀 설정 유연화). **탐지·발신·매매 diff 0.**
핵심 전제 [F-1]: `build_scan_universe`는 측정 전용 그림자 유니버스(탐지 입력 아님) → 상한↑는 coverage 분모만
이동, recall 불변. Option A 확정(사용자 승인).

## Requirements

- **REQ-AI086-001 (State, P0)**: `max_scan_universe` 설정 유연화 + 경계 [50,600] clamp, 기본값 150 유지.
- **REQ-AI086-002 (Ubiquitous, P0, HARD)**: non_scannable 원인 진단(truncated vs absent), 기존 테이블 재사용·마이그레이션 없이.
- **REQ-AI086-003 (Where/Optional, P1)**: 신규 소스 풀(Pool D) `pool_d_min_slots` quota 통합, 기본 OFF, 소싱 fetch 유계.
- **REQ-AI086-004 (Where/State, P1)**: 장중 시간대별 동적 상한(선택), 기본 단일 평탄 150.
- **REQ-AI086-005 (Unwanted, P0, HARD)**: 측정 전용 비용 경계 — 기존 경로 탐지기 실행/gather 시간/시세조회/LLM 발신 증가 금지, 측정 유니버스 코드 탐지 재투입 금지. [D5] 범위=기존 Pool A/B/C·gather 경로 한정; REQ-003 신규 풀의 유계·기본-OFF 소싱 조회는 별개 허용 비용.
- **REQ-AI086-006 (Unwanted, P0, HARD)**: 커버리지 지표 정합성 — scannable_recall 산술 하락을 탐지 회귀로 오기록 금지, 분모 의미 보존, 명명 필드/토큰으로 "회귀 아님" 표식.
- **REQ-AI086-007 (State, P0)**: 백워드 호환 — 신규 설정 전부 기본값이면 현재 출력과 바이트 동등.
- **REQ-AI086-008 (Optional, P2)**: 관측성 — 상한값/풀 raw·scanned 카운트/신규 풀/진단 요약 로그 1줄, 스키마 0.

> [D4] REQ 정규 "shall" 문장은 서술적 용어 유지, 리터럴 식별자(`max_scan_universe`/`pool_d_min_slots`/
> `build_scan_universe`/`SurgeUniverseMember` 등)는 spec.md 각 REQ "구현 참고" 부속 라인에 위치.

## Acceptance (EARS 정본 + Given/When/Then 부속)

- **AC-086-001 (REQ-001)**: While 상한이 [50,600] 이내(예:300) 설정 → shall 그 상한 적용, 유니버스 ≤ 상한. (G/W/T: 상한=300 → 적용 300, ≤300)
- **AC-086-002 (REQ-001)**: If 상한이 경계 초과(5000) → shall 600 clamp + 경고 로그 + 예외 없음.
- **AC-086-003 (REQ-007, HARD)**: While 신규 설정 전부 기본값 → shall 현재 구현과 바이트 동등(final_universe·pool_counts).
- **AC-086-004 (REQ-002, HARD)**: When 진단 실행 → shall 각 non_scannable을 truncated/absent 분류·기록(마이그레이션 없이). (A=truncated, B=absent)
- **AC-086-005 (REQ-005, HARD)**: If 확장 유효 → shall NOT 기존 경로 탐지기/시세조회/LLM 호출 수 증가 + 측정 유니버스 코드 탐지 미투입(회귀 assert).
- **AC-086-006 (REQ-003)**: Where 신규 풀 예약=20 + 절단 압력 → shall 신규 풀 ≥20 예약 잔존 + entry_pool='pool_d' 태깅.
- **AC-086-007 (REQ-006) [D6]**: If scannable 확장 & TP 불변 → shall coverage↑·scannable_recall↓ 기록 + 명명 필드(`scannable_denominator_expanded` 등)로 "탐지 회귀 아님" 기계 검증.
- **AC-086-008 (REQ-004) [D3]**: Where 시간대 상한 설정 → shall 현재 시간대 상한 적용; Where 미설정 → shall 단일 평탄 상한(REQ-001).
- **AC-086-009 (REQ-008) [D3]**: Where 로깅 유효 → shall 상한값/풀 raw·scanned/신규 풀/원인 분류 요약 단일 로그 1줄, 스키마 0, 종목별 상세 없음.

추적성: REQ-001~008 전량 AC 커버(8/8, 미커버 0). 매핑 = 001→AC1·2 / 002→AC4 / 003→AC6 / 004→AC8 / 005→AC5 / 006→AC7 / 007→AC3 / 008→AC9.

### 엣지 케이스
- 전 풀 공백(주말/장애) → 안전 no-op. 신규 풀 예약 합계 상한 초과 → SPEC-AI-076 clamp. 신규 풀 소싱 실패 → fail-open. 동적 상한 맵 현재 시간대 키 부재 → 평탄 상한 폴백.

## 변경 예상 파일

- `backend/app/services/surge_detector.py` (build_scan_universe 배분/상한/진단)
- `backend/app/surge_config/surge_settings.py` (SurgeDetectionConfig 신규 필드)
- `backend/app/services/surge_detection.yaml` (신규 설정 키)
- `backend/app/services/surge_evaluation_service.py` 또는 신규 진단 함수 (REQ-002)
- `backend/tests/test_spec_ai_086.py` (신규 특성화 테스트)
- **마이그레이션 회피 우선 — 신규 DB 마이그레이션 0건 목표.**

## Exclusions (What NOT to Build)

1. **[HARD]** 유니버스 → 탐지 배선(실제 recall 레버) = 별도 후속 SPEC(gather wall-time/LLM 비용, SPEC-AI-082 타임아웃 위험).
2. auto_improve_enabled 재활성화 금지(별개 이슈, 2026-07-02부터 정지).
3. `existing_codes` 병합 필터 pre-existing 버그 미수정(SPEC-AI-076 Exclusion 10 보존).
4. 탐지기/앙상블 가중치/적응형 임계/발신/매매(SPEC-AI-043 예측기록모드) 무변경.
5. Pool A/B/C 후보 소싱 로직(SPEC-AI-073/074/078/065) 무변경 — 배분·상한·신규풀 통합만.
6. `_min_ratio`(2.0) 변경 금지, `gather_surge_candidates` HTTP 재구조화(SPEC-AI-082 §8) 범위 밖.
7. 과거 coverage/universe_members 백필 금지(전진 적용만).
