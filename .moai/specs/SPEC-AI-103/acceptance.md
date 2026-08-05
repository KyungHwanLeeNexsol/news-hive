# Acceptance Criteria — SPEC-AI-103 테마 클러스터 뉴스 신선도/중복(dedup) 가드

> **iteration 2 개정 안내**: plan-auditor 1차 심사(FAIL, 0.67, MP-2 위반)를 반영해
> 모든 AC의 1차 진술을 GEARS 패턴으로 재작성했다. 기존 Given/When/Then 내용은
> 구현자 참고용 "테스트 시나리오" 하위 항목으로 보존한다. REQ-AI103-005/007에
> 대한 전용 AC(AC-AI103-006/007)를 신규 추가했다.

## §A GEARS 패턴 Acceptance Criteria

### AC-AI103-001 (REQ-AI103-001 대응) — 근접 중복 기사의 단일 집계

**Where** 신선도/중복 가드가 활성화되어 있고, **When** 테마 클러스터 탐지기가
제목 유사도 임계 이상이면서 발행 시각이 근접한(근접 중복) 기사를 포함하는
기사 부분집합에서 테마 활성 판정 카운트 또는 종목별 기사 귀속 카운트를
계산하면, the system **shall** 그 근접 중복 기사들을 단일 건으로 집계하고
그중 가장 이른 발행 기사를 대표 건으로 사용해야 한다.

테스트 시나리오(예시):

- **Given** 특정 테마 키워드에 매칭되는 기사가 3건이며 그중 2건이 근접 중복
  판정 조건(제목 유사도 임계 이상 + 발행 시각 근접)을 만족하고,
  `min_article_count=2`이다.
- **When** `detect_theme_news_cluster()`가 실행된다.
- **Then** 중복 제거 후 유효 기사 수는 2건(고유 사건 2건)으로 집계되고,
  테마 활성 여부 판정은 raw count(3)이 아닌 중복 제거된 count(2) 기준으로
  이루어진다. raw count 기준이면 통과했을 시나리오와 달리, 실제 고유 사건이
  1건뿐이라 `min_article_count` 미달로 귀결되는 경계 사례도 함께 검증한다.

### AC-AI103-002 (REQ-AI103-002 대응) — 기본값 바이트 동등

**While** 신선도/중복 가드 설정이 기본값(`enabled=false`)이면, the system
**shall** 본 SPEC 적용 이전과 완전히 동일한 테마 활성 판정 결과와
`theme_cluster_score`를 산출해야 한다.

테스트 시나리오(예시):

- **Given** `theme_freshness_guard`가 스키마 기본값이고, AC-AI103-001과 동일한
  (중복 포함) 픽스처가 주어진다.
- **When** `detect_theme_news_cluster()`가 실행된다.
- **Then** 반환된 `SurgeCandidate` 목록이 본 SPEC 적용 이전 코드로 동일 픽스처를
  실행한 특성화 테스트 스냅샷과 완전히 동일하다.

### AC-AI103-003 (REQ-AI103-003 대응, 진부화 분기) — 진부화된 테마의 점수 감쇠

**Where** 신선도/중복 가드가 활성화되어 있고 `min_theme_freshness_ratio`가
0보다 크게 설정되어 있으며, **When** 활성 테마의 (중복 제거된) 기사 활동이
신선 구간 밖에 집중되어 있으면, the system **shall** 해당 테마 후보의
`theme_base` 점수에 `freshness_discount_factor` 감쇠를 적용해야 하며, 후보
자체를 완전히 배제해서는 안 된다.

테스트 시나리오(예시):

- **Given** 위 활성화 조건이 성립하고, 활성 테마의 모든(중복 제거된) 기사가
  `fresh_window_hours` 밖(예: 창 초반 40시간 전)에만 존재한다.
- **When** `detect_theme_news_cluster()`가 실행된다.
- **Then** 감쇠가 적용되어 가드 비활성 시보다 낮은 `theme_cluster_score`를
  산출하되, 후보 자체는 결과 목록에서 사라지지 않는다.

### AC-AI103-004 (REQ-AI103-003 대응, 신선 분기 — 대칭 케이스) — 신선한 테마는
감쇠되지 않는다

**Where** 신선도/중복 가드가 활성화되어 있고, **When** 활성 테마의 (중복
제거된) 모든 기사가 신선 구간 이내에 발행되었으면, the system **shall**
해당 테마의 `theme_base`에 어떤 감쇠도 적용하지 않고 가드 비활성 시와 동일한
`theme_cluster_score`를 산출해야 한다.

테스트 시나리오(예시):

- **Given** AC-AI103-003과 동일한 활성화 설정이나, 활성 테마의 모든 기사가
  `fresh_window_hours` 이내에 발행되었다.
- **When** `detect_theme_news_cluster()`가 실행된다.
- **Then** 감쇠 미적용, `theme_cluster_score`가 가드 비활성 시와 동일하다.

### AC-AI103-005 (REQ-AI103-004 대응, **SHOULD-PASS**) — 유계된 가격 과열 방어

**Where** 신선도/중복 가드의 가격 과열 서브기능이 활성화되어 있고
`sector_only_max_candidates`가 설정되어 있으면, **When** 테마 클러스터
탐지기가 섹터 전용 후보 목록을 확정하면, the system **shall** 절단 이후의
(이미 상한이 걸린) 후보 중 테마 활동 시작 시점 이후 가격이 과열 임계 이상
이미 움직인 후보를 감쇠하거나 제외해야 하며, 이 과정에서 배치 가격 조회
함수를 정확히 1회만 호출해야 한다.

> SHOULD-PASS 라벨은 REQ-AI103-004와 동일한 우선순위 표기이며, 위 문장
> 자체는 정규 GEARS "shall" 어휘를 사용한다(plan-audit D2 조치 반영).

테스트 시나리오(예시):

- **Given** 위 활성화 조건이 성립하고, 절단 이후 남은 섹터 전용 후보 중 1개가
  테마 활동 시작 이후 가격이 `price_overheat_change_pct` 이상 이미 상승했다.
- **When** `detect_theme_news_cluster()`가 실행된다.
- **Then** 해당 후보 점수가 감쇠/제외되고, `fetch_stock_price_history_batch_sync`
  mock 호출 카운트가 정확히 1(종목별 개별 호출이 아님)임이 검증된다.

### AC-AI103-006 (REQ-AI103-005 대응, **Must-Pass — SPEC-AI-038 회귀 방지
불변식**) — 종목 순회 루프 내 동기 가격 호출 금지

**While** 테마 클러스터 탐지기가 섹터 소속 종목을 순회하며 점수를 계산하는
동안, **어떤** 가드 활성/비활성 조합(가드 비활성 / 가드 활성+가격과열
비활성 / 가드 활성+가격과열 활성)에서도, the system **shall not** 그 순회의
종목 1건마다 개별 동기 가격 API 호출을 수행해서는 안 된다.

테스트 시나리오(예시, mock/spy 기반 — 수동 확인 아님):

- **Given** `_fetch_price_change_sync`(및 그 하위 `fetch_current_price_with_change`
  경로)에 spy를 설치하고, 위 3가지 가드 설정 조합 각각에 대해 섹터 소속
  종목이 다수(예: 10개 이상)인 활성 테마 픽스처를 준비한다.
- **When** `detect_theme_news_cluster()`가 각 설정 조합으로 실행된다.
- **Then** 세 조합 모두에서 `_fetch_price_change_sync`류 개별-종목 동기 호출
  카운트가 0이다(가격과열 활성 조합에서는 대신
  `fetch_stock_price_history_batch_sync` 배치 호출만 최대 1회 관측됨 —
  AC-AI103-005와 상호 정합).

### AC-AI103-007 (REQ-AI103-007 대응, **Must-Pass**) — 관측성 로깅

**While** 신선도/중복 가드가 활성화되어 있으면, **When** 테마 클러스터
탐지기가 활성 테마를 처리하면, the system **shall** 그 테마에 대해 중복
제거로 축소된 기사 수와 계산된 신선 비율 값을 포함하는 디버그 레벨 로그
레코드를 남겨야 한다.

테스트 시나리오(예시, pytest `caplog` 자동 검증 — 수동 확인 아님):

- **Given** 가드가 활성화되어 있고 `caplog`가 DEBUG 레벨로 설정되어 있으며,
  중복 2건을 포함하는 활성 테마 픽스처가 주어진다.
- **When** `detect_theme_news_cluster()`가 실행된다.
- **Then** `caplog.records`에 축소된 기사 수와 신선 비율 수치를 모두 포함하는
  로그 레코드가 최소 1건 존재함을 자동 단언(assert)한다.

### REQ-AI103-006 커버리지에 대한 명시적 결정 (특성화 테스트 선행 순서 요건)

REQ-AI103-006("구현이 시작되면 특성화 테스트를 먼저 작성한다")은 런타임
동작이 아닌 **작업 순서(프로세스) 제약**이므로, 별도의 런타임 AC-AI103-XXX
항목을 두지 않기로 **명시적으로 결정**한다. 대신 이 요건은 다음 두 프로세스
게이트로 추적한다:

- plan.md §F 마일스톤 순서 — M5(특성화 테스트 작성)가 M6(구현)보다 명시적으로
  선행한다.
- 아래 §D Definition of Done의 첫 항목 — "특성화 테스트가 구현 변경 이전
  커밋에서 먼저 통과 확인됨"을 커밋 이력(`git log`)으로 검증한다.

이는 코드 동작을 검증하는 AC와는 성격이 다른, 작업 순서를 검증하는 프로세스
게이트임을 밝힌다.

## §B Edge Cases

- **빈 뉴스 창**: `window_news`가 0건일 때 신규 헬퍼 호출 없이 기존과 동일하게
  빈 후보 목록을 반환한다(가드 활성/비활성 무관).
- **전량 동일 제목**: 창 내 모든 기사가 완전히 동일한 제목일 때 중복 제거가
  1건으로 수렴하고 `ZeroDivisionError` 없이 신선 비율이 계산된다.
- **경계값 발행 시각 차이**: 두 기사의 발행 시각 차이가
  `duplicate_dedup_window_hours` 경계값(정확히 일치)일 때의 포함/배제 방향을
  명시적으로 테스트한다.
- **다중 테마 교차 오염 방지**: 서로 다른 두 키워드에 매칭되는 기사 집합이
  겹치는 경우(한 기사가 두 테마 모두에 매칭), 한 테마의 중복 제거가 다른
  테마의 부분집합 카운트에 영향을 주지 않는다.
- **가격 과열 서브기능 비활성 시 스킵**: `sector_only_max_candidates=None`
  상태에서 `price_overheat_enabled=true`로 설정해도 배치 가격 호출이 전혀
  발생하지 않는다(AC-AI103-006과 함께 가드 조합 검증).
- **성능 경계(하드 캡 검증, D6 조치)**: 단일 키워드에 매칭되는 기사 수가
  정확히 `dedup_max_comparison_batch`(기본 200) 캡에 도달한 픽스처에서, 중복
  제거를 포함한 실행 시간이 캡 미적용 베이스라인(가드 비활성) 대비 **20%
  이내 증가**함을 확인한다. 이어서 캡을 초과하는 픽스처(예: 500건 매칭)에서도
  dedup 비교 비용이 캡 크기(200)로 유계됨을 확인한다 — 캡이 없었다면
  발생했을 O(N²) 방향의 초과 증가가 발생하지 않음을 구조적으로 증명하는
  것이며, "관측 사례상 작다"는 경험적 주장이 아니라 코드가 강제하는 상한임을
  검증한다(spec.md §Decisions D4, plan.md §C 하드 캡 참고).

## §C 품질 게이트 기준

- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 전체 통과
  (`CLAUDE.local.md` 검증 명령).
- `cd backend && uv run ruff check .` 클린.
- `cd backend && uv run mypy app/` — 신규 코드에 대해 기존 대비 신규 에러 0건.
- 신규/수정 함수(`_dedup_near_duplicate_articles`,
  `_compute_theme_freshness_ratio`, 및 `detect_theme_news_cluster()` 수정
  구간)에 대한 커버리지 85% 이상(TRUST 5 Tested 원칙).
- **신설 게이트 블록의 `enabled` 값 자체를 단언**(블록 존재 여부만 확인하는
  대신 값을 직접 검사 — plan-audit D4 조치; range-awk 오프바이원 수정 — D9 조치):
  ```bash
  awk '/theme_freshness_guard:/{flag=1; next} flag && /^[a-zA-Z_]/{exit} flag' \
    backend/app/surge_config/surge_detection.yaml \
    | grep -qE '^[[:space:]]*enabled:[[:space:]]*false' \
    && echo PASS || echo FAIL
  ```
  기대 출력: `PASS` (신설 블록이 `enabled: false`로 명시 배포됨). 이전(D4 조치)
  버전은 `awk '/theme_freshness_guard:/,/^[a-zA-Z_]/'` range 패턴을 썼는데,
  헤더 라인이 동시에 시작·종료 패턴을 만족하면 범위가 그 자리에서 닫혀 이후
  라인을 전혀 캡처하지 못하는 오프바이원 결함이 있었다(iteration 2
  plan-audit D9). 수정된 형태는 헤더 라인을 `next`로 건너뛴 뒤 캡처를
  시작하고, 이후 첫 비들여쓰기(column-0) 라인에서 `exit`한다. 이 커맨드는
  구현 착수 전 확인용 문서 도구다 — 본 SPEC은 아직 plan-phase이므로 실제
  `surge_detection.yaml`에는 `theme_freshness_guard:` 블록이 아직 없다.
  이 자리에서 검증한 것: (1) 헤더 바로 아래에 `enabled: false`가 있는
  합성(synthetic) 픽스처(실제 `combo_chase_guard:` 블록과 동일한 2-space/
  4-space 들여쓰기 구조 복제) 대상으로 새 커맨드가 `PASS`를 출력함, (2)
  블록이 아직 없는 현재 `surge_detection.yaml` 원본 대상으로는 새 커맨드가
  올바르게 `FAIL`을 출력함(거짓 PASS 없음). 구현 시점에 블록이 실제로
  추가되면 이 커맨드를 실제 파일에 재실행해 `PASS`를 재확인한다.

## §D Definition of Done

- [ ] 특성화 테스트(REQ-AI103-006)가 구현 변경 이전 커밋에서 먼저 통과
      확인됨(§A "REQ-AI103-006 커버리지에 대한 명시적 결정" 프로세스 게이트)
- [ ] AC-AI103-001, -002, -003, -004, -006, -007(Must-Pass) 전부 PASS
- [ ] AC-AI103-005(Should-Pass)가 M4 포함 결정 시 PASS, 미포함 결정 시 spec.md
      Open Question 2에 후속 SPEC 위임으로 명시 기록
- [ ] 기본 설정 바이트 동등 회귀 스위트 그린 (AC-AI103-002)
- [ ] `theme_freshness_guard.enabled=false`가 `surge_detection.yaml` 배포본에
      §C의 값-단언(awk+grep) 명령으로 확인됨
- [ ] REQ-AI103-007 디버그 로그가 `caplog` 자동 검증으로 확인됨(수동 확인
      아님, AC-AI103-007)
- [ ] `dedup_max_comparison_batch` 하드 캡 경계(200건)와 캡 초과(500건) 성능
      엣지 케이스 모두 20% 이내 증가로 통과함(§B 성능 경계)
- [ ] plan-auditor PASS
- [ ] PRESERVE 목록(plan.md §G) 대상 파일에 diff 0 (git diff로 확인)
