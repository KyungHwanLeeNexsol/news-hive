# SPEC-AI-096 Research — 급등예측 스캔 유니버스 파이프라인 구조 조사

> 이 문서는 spec.md §Context가 인용하는 "정확한 사실"의 1차 출처다. 모든 라인 번호는
> 2026-08-03 기준 `backend/app/services/surge_detector.py` HEAD를 직접 Read/Grep으로
> 확인한 값이다(추정치 아님). 사용자가 위임 프롬프트에서 인용한 라인 번호와 실제 라인
> 번호가 일부 다른 경우 실제 값으로 정정했다(§검증 결과 참고).

## §A. 조사 방법

- `Grep` + `Read`로 `backend/app/services/surge_detector.py`, `backend/app/surge_config/surge_settings.py`,
  `backend/app/surge_config/surge_detection.yaml`, `backend/app/models/surge_universe_pool_history.py`,
  `backend/app/services/surge_universe_pool_service.py`를 직접 읽고 인용된 사실을 재검증했다.
- DB 접근이나 실제 배치 실행은 하지 않았다(plan-phase, 프로덕션 코드 무수정 원칙). 2026-07-28
  실측 수치(23개 중 4개만 scannable)는 위임 프롬프트에 인용된 값으로, 이 세션에서 DB로
  재검증하지 않았다 — §검증 결과에 이 사실을 명시한다.

## §B. 검증 결과 (원본 인용 vs 실제 코드)

| # | 원본 위임 프롬프트 인용 | 실제 확인 값 | 상태 |
|---|--------------------------|--------------|------|
| 1 | `surge_detection.yaml:234`, `surge_settings.py:532` — `max_scan_universe: 150` | 정확히 일치 (yaml :234, settings.py :532) | ✅ 정확 |
| 2 | Pool D `pool_d_min_slots > 0` 게이트, 기본값 0 | `surge_detector.py:4798`(게이트), `surge_settings.py:557`/`surge_detection.yaml:244`(기본값 0) | ✅ 정확 |
| 3 | 호출 순서 — 탐지기 실행 → `existing_codes = set(merged.keys())` → `build_scan_universe()` | `existing_codes`는 `:1937`, `build_scan_universe()` 호출은 `:1941` (원본 "1890-1941" 범위 근사치, 정확한 라인은 1937/1941) | ✅ 정확(라인 정정) |
| 4 | `generate_scan_universe_bridge_candidates`(`:4977`, 호출 `:2021`), `scan_universe_bridge_candidates_enabled` 기본 `False`(`surge_settings.py:589`) | 라인 번호 정확히 일치 | ✅ 정확 |
| 5 | `measure_universe_detection_gap`(`:1992-2015`), `universe_gap_measurement_enabled` 기본 `False`(`:581`) | 실제 블록은 `:1992-2015`(if문 시작 1992, try 블록 끝 2015 — 정확) | ✅ 정확 |
| 6 | `_MAX_PRICE_FETCH_CANDIDATES = 50`(`:2118`), SPEC-AI-038이 30→50으로 확대(2026-06-30) | 정확히 일치. 코드 주석(`:2117`)이 "2026-06-30: 30→50으로 확대 — KOSDAQ 2페이지 추가로 후보 증가, idle_in_transaction 타임아웃 제거로 여유 생김"을 직접 확인 | ✅ 정확 |
| 7 | 2026-07-28, 실급등 23개 중 scannable 4개, 11개 미탐지원 진입, 8개 150-cap 절단 | **DB 재검증 안 함** — 위임 프롬프트 인용값을 그대로 신뢰. 이 세션은 그 수치의 원천 쿼리를 재실행하지 않았다 | ⚠️ 미검증 (§C.4 참고) |

## §C. 심화 발견 — 위임 프롬프트에 없던 추가 사실

### C.1 — `_universe_codes`(max_scan_universe cap 대상)는 기본 설정에서 탐지 경로에 영향이 없다

`build_scan_universe()`가 반환하는 `_universe_codes`(및 `max_scan_universe` 절단 결과)는
다음 4곳에서만 소비된다(`surge_detector.py:1944-2027` 전수 확인):

1. `:1944-1948` entry_pool 태깅 — `merged`(탐지기 결과)의 각 candidate에 `entry_pool` 필드를
   갱신. **`merged`의 멤버십 자체는 바꾸지 않는다.**
2. `:1961-1983` `persist_pool_counts`/`persist_universe_members` — 순수 관측/DB 기록.
3. `:1992-2015` `measure_universe_detection_gap` — `universe_gap_measurement_enabled=False`
   (기본값)이면 스킵.
4. `:2021` `generate_scan_universe_bridge_candidates` — `scan_universe_bridge_candidates_enabled=False`
   (기본값)이면 즉시 빈 리스트 반환(`:5009-5010`).

**결론**: 기본 설정(Pool D 비활성 + bridge 비활성)에서 `max_scan_universe`(150) 상한은
**실제 후보/시그널 생성에 전혀 영향을 주지 않는다** — `scannable_recall`/`coverage`/
`surge_type`(SPEC-AI-068) 평가지표의 **분모**에만 영향을 준다. 이는 SPEC-AI-094가
`existing_codes` 병합 필터에 대해 확인한 것과 정확히 동일한 구조다.

**이 발견이 본 SPEC의 스코프에 미치는 영향**: "8개가 150-cap에 절단됐다"(finding 7)는 주장이
성립하려면, 그 8개 종목이 (a) `_universe_codes`에서 잘렸을 뿐 아니라 (b) 어느 7개 핵심
탐지기에도 걸리지 않아 `merged`에 없었어야 한다. 즉 이 8개를 실제로 "구제"하려면
**`max_scan_universe` 상향과 `scan_universe_bridge_candidates_enabled` 활성화가 함께
필요하다** — 캡만 올리는 것은 관측 지표(scannable_recall/coverage)만 개선하고 실제 매매
후보에는 영향이 없다(bridge가 꺼져 있는 한). 이 사실을 spec.md §Decisions에 명시했다.

### C.2 — Pool D는 count는 계산하지만 이력 테이블에 저장하지 않는다 (신규 발견 — 관측 갭)

`build_scan_universe()`는 `pool_counts["pool_d"]`를 계산한다(`:4861`, 반환값에 포함).
그러나 호출부(`surge_detector.py:1961-1970`)의 `persist_pool_counts()` 호출은:

```python
persist_pool_counts(
    db, date.today(),
    {
        "pool_a": _pool_counts.get("pool_a", 0),
        "pool_b": _pool_counts.get("pool_b", 0),
        "pool_c": _pool_counts.get("pool_c", 0),
        "scan_universe_size": len(_universe_codes),
    },
)
```

`pool_d` 키를 **명시적으로 누락**한다. 그리고 `SurgeUniversePoolHistory` 모델
(`backend/app/models/surge_universe_pool_history.py:15-47`)에는 애초에 `pool_d_count`
컬럼이 **존재하지 않는다** — `pool_a_count`/`pool_b_count`/`pool_c_count`/`scan_universe_size`
4개 컬럼뿐이다.

**결론**: Pool D를 "안전하게, 관측 가능하게" 단계적으로 활성화하려면 — 사용자가 요청한
"활성화 전 모니터링/롤백 기준" — 우선 **일자별 이력 테이블에 pool_d 수치를 저장할 컬럼이
있어야 한다.** 현재는 매 실행 로그 라인(`:4824` "[스캔유니버스] Pool D(뉴스언급): %d개")에만
찍히고 휘발된다 — 여러 거래일에 걸친 추세를 판단할 영속 데이터가 없다. 이것이 본 SPEC이
새 마이그레이션 컬럼을 필요로 하는 근본 이유다(REQ-AI096-002).

`get_pool_counts_for_date()`(`surge_universe_pool_service.py:77-98`)도 동일하게 `pool_d`
키를 반환하지 않는다(반환 dict가 `pool_a`/`pool_b`/`pool_c`/`scan_universe_size` 4키 고정).

### C.3 — `entry_pool` 태깅이 이미 `_MAX_PRICE_FETCH_CANDIDATES` 절단보다 먼저 실행된다

절단 관련 재설계(REQ-AI096-005)가 안전하게 구현 가능한 이유: `candidate.entry_pool` 필드
(기본값 `"existing"`, `SurgeCandidate` 클래스 `:95`)는 `:1944-1948`에서 Pool A/B/C/D
소속 여부로 갱신되며, 이는 `_MAX_PRICE_FETCH_CANDIDATES` 절단 블록(`:2118-2138`)보다
**먼저** 실행된다. 즉 절단 시점에 이미 각 candidate가 "외부 독립 공급 신호(Pool A/B/C/D)"를
가졌는지 여부를 별도 조회 없이 알 수 있다 — 이는 SPEC-AI-063가 `volume_breakout_score`
단독 bypass에 사용한 것과 동일한 "이미 계산된 필드 재사용" 패턴이다(`:2260-2278`).

### C.4 — Bridge 후보는 이미 attribution을 갖고 있다 (관측 인프라 재사용 가능)

`generate_scan_universe_bridge_candidates()`가 생성하는 각 `SurgeCandidate`는
`active_detectors=["scan_universe_bridge", pool]`(`:5132`)로 태깅된다. 이 필드는
`FundSignal.surge_metadata.surge_basis`로 흘러간다(에이전트 메모리
`project_surge_data_model.md` 확인 — "Detector attribution goes through
FundSignal.surge_metadata"). `backend/app/services/surge_backtest.py`의
`_extract_combo_key()`가 이 값을 기존에 파싱하는 유틸리티다.

**결론**: bridge 후보를 활성화 후 "잘 작동하는지" 평가하려면 **새 계측을 만들 필요가 없다**
— 기존 `_extract_combo_key`/`surge_basis` 파이프라인이 `"scan_universe_bridge+pool_a"`
같은 조합 키를 이미 자연스럽게 산출한다. 본 SPEC은 이 사실을 활용해 "활성화 기준"을
새 코드가 아닌 **기존 분석 도구로 관측하는 절차**로 정의한다(REQ-AI096-004).

### C.5 — `_MAX_PRICE_FETCH_CANDIDATES`를 무작정 올리는 것은 과거에 실제로 사고를 낸 값이다

코드 주석(`surge_detector.py:2115-2117`)이 직접 진술한다: "테마클러스터가 수백 개 후보
반환 시 모든 종목 HTTP 호출 → 300s 타임아웃 초과"가 SPEC-AI-038이 이 상수를 도입한
근본 이유였고, 30→50 확대도 "KOSDAQ 2페이지 추가로 후보 증가"라는 **원인 제공** 변경과
함께 "idle_in_transaction 타임아웃 제거로 여유 생김"이라는 **별도의 인프라 개선**을
전제로 한 것이었다. 즉 이 숫자를 올리는 것은 단순 설정값 변경이 아니라 **HTTP 호출량 ×
타임아웃 여유**의 함수다. 본 SPEC은 이 상수를 무작정 재상향하지 않고(§Decisions D2에서
근거 서술), 배치 HTTP 인프라(SPEC B, out of scope)가 나오기 전까지는 절단 **면제 정책**
(entry_pool 소속 후보 보호)만 도입한다.

## §D. 관련 SPEC 요약 (선행 인프라 소유권)

| SPEC | 소유 대상 | 본 SPEC과의 관계 |
|------|-----------|-------------------|
| SPEC-AI-065 (completed) | `build_scan_universe()` 최초 구조, Pool A/B/C, `max_scan_universe` | 본 SPEC이 값만 조정(구조 무변경) |
| SPEC-AI-076 (completed) | quota 배분(`pool_b/c_min_slots`), existing 우선순위 최하 원칙 | 무변경 — 신규 quota 도입 안 함 |
| SPEC-AI-086 (completed) | Pool D 도입(비활성 기본), `max_scan_universe` clamp [50,600], 동적 시간대 상한 | 본 SPEC은 이 clamp를 그대로 사용하며 절대 초과하지 않는다 |
| SPEC-AI-089 (completed) | `measure_universe_detection_gap`(관측 전용, 기본 비활성) | 무변경 — 활성화 여부는 본 SPEC의 관측 절차가 권장할 수 있음 |
| SPEC-AI-092 (completed) | bridge 후보 생성 로직, attribution 태깅 | 본 SPEC은 이 로직을 재사용하며 코드 변경 없음(활성화 기준만 정의) |
| SPEC-AI-063 (completed) | `volume_breakout_score` 단독 bypass 패턴 | REQ-AI096-005가 이 패턴을 재사용 |
| SPEC-AI-038 | `_MAX_PRICE_FETCH_CANDIDATES` 30→50 조정, 타임아웃 회귀 이력 | REQ-AI096-005 설계의 안전 제약 근거 |
| SPEC-AI-094 (completed) | `existing_codes` 병합 필터 교정(별도 플래그) | 명시적 제외 대상(§Out of Scope) — 재론하지 않음 |

## §E. 미해결 항목 (spec.md §Open Questions로 승계)

1. `max_scan_universe` 신규 기본값의 정확한 숫자 — 이 세션은 250을 제안하되, 실측
   근거(pool_d_count 영속화 이후 관측되는 실제 Pool A/B/C/D 원시 합산치)가 아직 없다.
2. Pool D/bridge 활성화 관측 기간(거래일 수)의 정확한 값 — 제안값은 있으나(§Decisions),
   최종 확정은 운영 판단.
