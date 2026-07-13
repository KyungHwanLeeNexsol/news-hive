# SPEC-AI-079 (compact)

**volume_breakout 상대임계(z-score) 확장 기능 활성화** — status: draft, priority: Medium, 2026-07-13

## 한 줄 요약
SPEC-AI-066에서 구현·테스트 완료됐으나 `relative_threshold_enabled: false`로 프로덕션에서 한 번도
가동 안 된 catalyst-universe + z-score 확장 경로를, **YAML 값 1줄 flip**으로 활성화. 로직 변경 없음.

## 변경
- `backend/app/surge_config/surge_detection.yaml:217` `relative_threshold_enabled: false` → `true`.
- (P2 optional) `surge_detector.py:4059` 부근 z-score-vs-flat 집계 INFO 1줄.

## 핵심 검증 사실 (2026-07-13 read-only 확인)
- 설정 키 경로 O (`:217`), 로직 O (`surge_detector.py:3983-3990`/`4027-4033`, z임계 `_VB_RELATIVE_Z_THRESHOLD=2.0`), 테스트 O (`tests/test_surge_ai066.py::TestVolumeBreakoutRelative`).
- **Pydantic 모델 기본값(`surge_settings.py:142` `=False`)은 유지** — `test_surge_ai066.py:223`이 모델 기본값=False 단언. YAML 런타임 값만 flip.
- 테스트는 `vb_overrides`로 플래그를 명시 주입 → YAML flip이 기존 테스트 결과를 바꾸지 않음.
- [research 정정] 리더 유니버스는 `limit=max_candidates//2`=상위 50, 촉매 확장 후 `max_candidates`=100 상한 ("100~173" 아님).

## EARS (4 core + 1 optional)
- **001 (Ubiq, P0)**: yaml `relative_threshold_enabled=true`.
- **002 (Event, P0)**: `detect_volume_breakout()`이 촉매 종목 유니버스 합류 + z>=2.0 상대 임계 인정; cold-start는 flat 3.0x 폴백.
- **003 (Unwanted, P0)**: Pydantic 기본값(False)/기타 임계(ratio 3.0/max_cand 100/baseline 20/min_hist 10/denom 8.0/max_score 0.50/bypass 0.30)/AI-062 가중치(0.11)/AI-063 bypass/타 탐지기/AI-078 diff 0.
- **004 (State, P0)**: `test_surge_ai066.py` + 전체 회귀 통과.
- **005 (Optional, P2)**: z-score(rel=True) vs flat 구분 INFO 집계 1줄 (스키마 0, 종목별 로그 금지).

## Exclusions
신규 탐지기 로직 / 기타 임계값 / z임계(2.0) / Pydantic 모델 기본값 / AI-078 Pool A 정렬 / 타 탐지기·앙상블·bypass·발신·매매(AI-043) / 신규 테이블·마이그레이션·백필 — 전부 금지.

## 리스크
- R-1 후보 확대 → surge_candidate 증가 → precision 일시 저하 가능(자금 리스크 0, 예측기록 모드 AI-043). 완화=REQ-005 관측 후 필요 시 후속 SPEC.
- R-2 촉매 조회 부하 = AI-066 설계 기반, 낮음. R-3 회귀 = 기존 테스트 양경로 커버, 낮음.
- Rollback: yaml `false` 복귀 = 즉시 완전 레거시(플래그가 유일 게이트).

## Related
SPEC-AI-066(선행/소유, 기능 본체) · AI-062(가중치) · AI-063(bypass) · AI-065(z-score 인프라) · AI-078(별개, Pool A 정렬) · AI-043(예측기록 모드).

## Acceptance (요지)
S1 활성화 시 촉매/z-score 확장 실행(011090형) · S2 비활성 시 제외(rollback 완전성) · S3 cold-start flat 폴백 · S4 모델기본값/소유경계 불변 · S5(P2) 관측성.
검증: `cd backend && uv run pytest tests/test_surge_ai066.py -q` + 전체 회귀(`-m "not slow"`, CI는 `-n 4`).
