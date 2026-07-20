# Plan: SPEC-AI-082 — 급등 후보 수집 글로벌 타임아웃 오폐기 교정

## 목표

`_gather_surge_candidates()`(`backend/app/services/fund_manager.py:1259-1319`)의 글로벌 타임아웃
상수 `_GATHER_TIMEOUT_S = 300`(5분)을, 코드베이스가 문서화한 정상 실행 시간(12~15분, `:3106`)을
여유 있게 상회하는 값으로 교정한다. 동시에 (1) 가드는 유계로 유지(무한 대기 금지), (2) 값을 테스트
주입 가능한 형태로 승격, (3) DDD 재현-우선으로 오폐기 거동을 특성화한 뒤 수정한다. 탐지 본체·앙상블·
유니버스·매매 로직은 diff 0.

## 기술 접근 (Technical Approach)

### 1. 타임아웃 값 승격 + 상향 (REQ-001/004, OQ-1/OQ-2)

**현행**(`fund_manager.py:1293-1295`):

```python
# 성능 패치: sync HTTP 루프를 스레드로 분리 + 5분 글로벌 타임아웃
# gather_surge_candidates는 종목당 다중 sync HTTP 호출 — 직접 await 시 event loop 블로킹
_GATHER_TIMEOUT_S = 300
```

문제: `_GATHER_TIMEOUT_S`가 **함수-로컬 리터럴**이라 (a) 값이 정상 실행 시간의 1/3이고, (b)
테스트에서 monkeypatch가 불가능하다(spec.md §2 [E-1]).

**권장 해법 (단순성 우선, CLAUDE.md Agent Core Behavior #4)**: 값을 **모듈 상수**로 승격하고 상향한다.

```python
# fund_manager.py 최상단(모듈 상수 영역)
# @MX:NOTE: [AUTO] SPEC-AI-082 — gather_surge_candidates 글로벌 타임아웃(초).
#   문서화된 정상 실행 시간 12~15분(:3106, SPEC-AI-022)을 여유 있게 상회해야 함.
#   유계 유지(무한 대기 금지, REQ-003). 테스트는 이 상수를 monkeypatch 하여 주입.
# @MX:SPEC: SPEC-AI-082 REQ-AI082-001
_GATHER_TIMEOUT_S = 1200  # 20분 (15분 상단 대비 ≈+33% 헤드룸)
```

`_gather_surge_candidates()` 내부의 함수-로컬 선언(`:1295`)은 제거하고, `asyncio.wait_for(...,
timeout=_GATHER_TIMEOUT_S)`가 모듈 상수를 참조하도록 한다. `run_in_executor`/`wait_for` 구조 자체는
그대로 유지(REQ-006).

**대안 (OQ-1)**: `SurgeDetectionConfig`(`surge_config/surge_settings.py`)에 필드로 승격(SPEC-AI-076/078
설정 필드 관례). 중앙화 이점은 있으나 배선이 늘고 최소 수정 원칙과 상충 — 본 plan은 모듈 상수를
권장한다. 어느 쪽이든 REQ-004(테스트 주입 가능)를 충족하면 된다.

**값 선정 근거(REQ-001, AC-082-001 하한)**: 문서화된 정상 상단 15분(900s)을 그대로 쓰면 헤드룸이
0이다. 20분(1200s)은 ≈+33% 헤드룸을 주며, 다음 스케줄 잡까지 수 시간 간격 대비 충분히 작은 유계
값이라 REQ-003(무한 대기 금지)도 만족한다. AC 하한은 `>= 1200s`로 고정한다.

### 2. 안전망 거동 보존 (REQ-003/007)

`except asyncio.TimeoutError:` 핸들러(`:1311-1316`)의 로그 메시지(`"...타임아웃 %ds 초과 — 빈 리스트
반환"`, 숫자 초 값 `%ds` 포함)와 `return []`는 **그대로 유지**한다. 값만 올릴 뿐 안전망 형태는
불변이므로, 상향 후에도 병리적 초과 시 동일하게 경고+빈 리스트로 폴백한다(REQ-007). `%ds` 포맷을
유지하면 journalctl에서 ASCII `1200s` 부분 문자열 검색이 계속 가능하다(REQ-008).

### 3. 재현-우선 특성화 테스트 (REQ-005, DDD ANALYZE-PRESERVE)

**핵심 제약**: 실제 12~15분 HTTP 지연을 단위 테스트에서 재현할 수 없다. 대신 §1에서 모듈 상수로
승격된 `_GATHER_TIMEOUT_S`를 소형 값으로 monkeypatch 하고, 감싼 `gather_surge_candidates`를
**해당 소형 값보다 오래 블로킹**하는 mock으로 대체해 래퍼의 타임아웃 거동을 결정적으로 구동한다.

- **RED (수정 전 특성화)**: `_GATHER_TIMEOUT_S`를 아주 작은 값(예: 0.05초)으로 monkeypatch,
  `app.services.fund_manager.gather_surge_candidates`를 그보다 오래 블로킹하는 mock(예: 내부에서
  `time.sleep(0.2)` 후 `[mock_candidate]` 반환 — executor 스레드에서 도는 sync 함수이므로 블로킹
  sleep이 실제 소요를 모사)으로 대체. `await _gather_surge_candidates(...)` 결과가 `[]`임을 단언 →
  **실제 후보가 있는데도 오폐기됨**을 재현. (이 테스트는 승격 전이라면 monkeypatch 지점이 없어
  작성 불가 → 승격이 재현의 전제임을 문서화.)
- **GREEN (수정 후 목표)**: `_GATHER_TIMEOUT_S`를 mock 소요보다 크게(예: 5초) monkeypatch, 동일
  mock으로 호출 시 결과가 `[mock_candidate]`(실제 후보 보존, 비어있지 않음)임을 단언 → **적용
  타임아웃 이내 완료 시 오폐기 없음**(REQ-002).
- **경계 명확화 테스트(선택)**: 상수의 프로덕션 값이 `>= 1200`임을 단언(AC-082-001) — 값 회귀 가드.

테스트 위치: `tests/test_surge_ai080_fund_manager.py`가 이미 `_gather_surge_candidates`를 mock 하는
패턴을 보유하므로 재사용 가능(spec.md §2 [E-5]). 단, 관심사 분리를 위해 신규 전용 파일
`tests/test_surge_ai082_gather_timeout.py`를 두는 것을 권장(기존 AI-080 테스트 오염 방지).

### 4. 범위·불변 회귀 가드 (REQ-006)

- `surge_detector.py::gather_surge_candidates`(탐지 본체) diff 0 — 코드 리뷰로 확인.
- 앙상블/가중치/임계/유니버스/매매 경로 diff 0.
- 스케줄러 크론 diff 0.
- 기존 `test_surge_ai080_fund_manager.py` 전량 무회귀(즉시 반환 mock이라 타임아웃 값 무관, §2 [E-5]).
- 전체 백엔드 회귀 스위트(기본 + `-n 4` xdist).

## 변경 대상 파일 (예상)

| 파일 | 변경 내용 | 규모 |
|------|-----------|------|
| `backend/app/services/fund_manager.py` | `_GATHER_TIMEOUT_S` 함수-로컬 → 모듈 상수 승격 + 300→1200, MX 태그 | 소 |
| `backend/tests/test_surge_ai082_gather_timeout.py` (신규) | RED(오폐기 재현) + GREEN(오폐기 없음) + 값 회귀 가드 테스트 | 소~중 |

**신규 테이블/마이그레이션 없음. 탐지 본체·설정 YAML·매매 로직 무변경.** (OQ-1에서 설정 필드 승격을
택하면 `surge_settings.py`/`surge_detection.yaml`가 변경 대상에 추가되나, 본 plan 권장안은 모듈 상수로
파일 변경을 fund_manager.py + 신규 테스트로 최소화.)

## 마일스톤 (우선순위 기반, 시간 추정 없음)

1. **Priority High — 재현(특성화) 테스트 선행 (ANALYZE-PRESERVE)**: 소형 주입 타임아웃 + 블로킹 mock으로
   RED(오폐기 `[]` 재현)을 먼저 작성·실패 확인. (REQ-005)
2. **Priority High — 타임아웃 값 승격 + 상향 (IMPROVE)**: `_GATHER_TIMEOUT_S`를 모듈 상수로 승격하고
   300→1200. GREEN(적용 타임아웃 이내 완료 시 후보 보존) 통과 확인. (REQ-001/002/004)
3. **Priority High — 안전망 보존 검증**: 병리적 초과(mock 소요 > 주입 타임아웃) 시 경고 로그 + 빈
   리스트 반환이 유지됨을 테스트로 고정. (REQ-003/007)
4. **Priority High — 범위·불변 회귀 가드**: 탐지 본체/앙상블/유니버스/매매/크론 diff 0, 기존
   `test_surge_ai080_fund_manager.py` 무회귀, 전체 스위트(기본 + `-n 4`). (REQ-006)
5. **Priority Medium — 값 회귀 가드**: 프로덕션 상수 `>= 1200s` 단언 테스트. (AC-082-001)
6. **Priority Low — 관측성 연속성**: 타임아웃 로그의 `%ds` 숫자 포맷 유지 확인(ASCII 부분 문자열
   검색 가능성), MX NOTE 보강. (REQ-008)

## 리스크 및 완화

| 리스크 | 영향 | 완화 |
|--------|------|------|
| 브리핑 병렬 gather 블로킹 5분→20분 증가([R-1]) | 브리핑 생성 지연 | Run 단계에서 브리핑 스케줄 여유 확인, 필요 시 경로별 타임아웃 분리 검토(기본은 단일 값) |
| 20분마저 초과하는 병리적 날([R-2]) | 그날 여전히 오폐기 | REQ-007 안전망(경고+빈 리스트)로 기존 거동 유지, 근본 해소는 §8 (b) 후속 SPEC |
| 고아 스레드 세션 경쟁([R-3], 본 SPEC 미해결) | 뒤늦은 쓰기 유실/경쟁 | 값 상향으로 발생 빈도 감소, 근본 수정은 §8 (c) 후속 SPEC으로 명시 유예(오케스트레이터 고지) |
| 상수 승격이 다른 거동을 건드릴 위험([R-4]) | 회귀 | 승격은 값 위치만 이동, 기존 mock 테스트 무회귀로 확인 |

## 검증 명령 (CLAUDE.local.md)

```bash
cd backend && uv run pytest tests/test_surge_ai082_gather_timeout.py \
  tests/test_surge_ai080_fund_manager.py --tb=short -q
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"          # 전체 회귀
cd backend && uv run pytest tests/ --tb=short -q -m "not slow" -n 4     # 전체 회귀(xdist 병렬)
cd backend && uv run ruff check . && uv run mypy app/
```

**프로덕션 로그 검증 주석 (유니코드 정규화 함정):** journalctl에서 이 타임아웃을 검색할 때는
한국어 단어 `타임아웃`으로 grep 하면 유니코드 정규화(NFC/NFD) 불일치로 거짓 음성이 발생할 수 있다.
반드시 ASCII 숫자 부분 문자열(예: `300s`, 수정 후 `1200s`)로 검색할 것. 배포 후 검증: 다음 10:00/
15:20 KST 잡 로그에서 타임아웃 메시지 소멸 + `surge_universe_members`/`surge_detector_contribution`
당일 비-0행 확인.

## 선행/관계 SPEC

- **SPEC-AI-012(선행)**: `_gather_surge_candidates`/`gather_surge_candidates` 원 소유. 본 SPEC은 async
  래퍼 타임아웃 값만 교정.
- **SPEC-AI-022(근거)**: "12~15분 실행" 주석이 정상 실행 시간 근거. 커버리지 확장 로직 무변경.
- **SPEC-AI-043(계승)**: 예측 기록 모드 유지(매매 무변경).
- **SPEC-AI-080/081(무관)**: 본 버그는 선재·독립(07-09 최초 발생이 07-16 배포보다 앞섬).
