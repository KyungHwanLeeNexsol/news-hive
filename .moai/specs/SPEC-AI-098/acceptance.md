# SPEC-AI-098 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-098-001 | REQ-AI098-001 | Must-Pass |
| AC-098-002 | REQ-AI098-001 | Must-Pass |
| AC-098-003 | REQ-AI098-003 | Must-Pass |
| AC-098-004 | REQ-AI098-003 | Must-Pass |
| AC-098-005 | REQ-AI098-003 | Should-Pass |
| AC-098-006 | REQ-AI098-002 | Must-Pass |
| AC-098-007 | REQ-AI098-004 | Must-Pass |
| AC-098-008 | REQ-AI098-005 | Must-Pass |
| AC-098-009 | REQ-AI098-005 | Should-Pass |
| AC-098-010 | REQ-AI098-006 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-098-001 — 경계 가드 적용으로 이전에 놓치던 별칭/자회사 언급이 매칭된다

**When** 종목 X의 별칭이 `_STOCK_NAME_ALIASES`에 등록되어 있고 뉴스 본문에 그 별칭이
조사가 붙은 형태(예: "LG전자가")로 언급되면, the system **shall** `stock_articles`에
그 기사를 포함해야 한다.

- 검증 방법: pytest — `keyword_matcher._keyword_in_text`와 동일한 경계 규칙을
  fixture 텍스트로 검증(조사 활용형 포함 케이스)

### AC-098-002 — 경계 가드가 오탐을 유발하지 않는다(무경계 substring 대비 회귀 없음)

**While** 경계 가드가 적용된 상태에서, the system **shall not** 종목명이 더 긴 무관
단어의 일부로 우연히 일치하는 경우(예: 짧은 별칭이 다른 고유명사에 포함된 경우)를
매칭시켜서는 안 되며, 영문 별칭(대문자, 예: "SKT")이 기사 원문 그대로(대소문자 무관)
등장하는 경우 매칭에 실패해서는 **shall not**(소문자 변환 처리 필수, plan.md A.1
경고 참고).

- 검증 방법: pytest — 오탐 유발 fixture(부분 문자열 포함 케이스) + 영문 대소문자
  혼용 fixture 양쪽 통과 확인. 본 AC는 두 fixture 케이스가 **모두** 통과해야
  PASS로 판정한다 — 어느 한쪽만 통과하는 부분 충족은 FAIL로 처리한다.

### AC-098-003 — 섹터 전용 설정 기본값에서 바이트 동등

**While** `sector_only_penalty=0.5`(기본값)이고 `sector_only_max_candidates=None`
(기본값)이면, the system **shall** 본 SPEC 적용 이전과 완전히 동일한
`theme_cluster_score` 값을 모든 섹터 전용 후보에 대해 산출해야 한다.

- 검증 방법: pytest — 적용 전/후 동일 fixture로 `theme_cluster_score` 값 diff 0 확인
  (골든 값 비교)

### AC-098-004 — `sector_only_penalty` 설정 시 섹터 전용 점수가 그 값을 반영한다

**Where** `sector_only_penalty`가 기본값과 다른 값(예: 0.3)으로 설정되면, the system
**shall** 섹터 전용 후보의 `theme_cluster_score`에 그 설정값을 적용해야 하며, 직접
언급 종목(60/40 블렌딩 경로)의 산식은 영향받지 않아야 한다.

- 검증 방법: pytest — `sector_only_penalty=0.3` fixture로 섹터 전용 점수가
  `best_theme_base * 0.3 * best_sector_relevance`와 일치함을 확인, 동일 fixture의
  직접 언급 종목 점수는 무변경임을 확인

### AC-098-005 — `sector_only_max_candidates` 절단이 직접 언급 종목에 영향을 주지 않는다

**When** `sector_only_max_candidates=N`이 설정되고 섹터 전용 후보가 N개를 초과하면,
the system **shall** `theme_cluster_score` 내림차순 상위 N개 섹터 전용 후보만 유지하고
나머지는 결과에서 제외해야 하며, 직접 언급 종목(`stock_specific_count >= 1`) 후보 수는
**shall not** 이 절단의 영향을 받아 줄어들어서는 안 된다.

- 검증 방법: pytest — 섹터 전용 후보 10개 + 직접 언급 후보 5개 fixture에
  `sector_only_max_candidates=3` 적용, 결과가 섹터 전용 3개 + 직접 언급 5개(총 8개)임을
  확인. 본 AC는 절단 결과(섹터 전용 3개)와 직접 언급 종목 수 무변경(5개 유지)이
  **모두** 확인되어야 PASS로 판정한다 — 어느 한쪽만 성립하는 부분 충족은 FAIL로
  처리한다.

### AC-098-006 — 별칭 후보 스크립트가 표를 자동 수정하지 않는다

**When** 별칭 후보 제안 스크립트를 실행하면, the system **shall** 후보 목록을 콘솔
출력(또는 검토용 초안 파일)으로만 제시해야 하며, `_STOCK_NAME_ALIASES` 딕셔너리
정의가 포함된 소스 파일을 **shall not** 수정해서는 안 된다.

- 검증 방법: 스크립트 실행 전/후 `surge_detector.py`의 `git diff` 0 매치 확인 +
  스크립트가 알려진 한글 음역 패턴 종목(픽스처)을 후보로 정확히 식별하는지 확인.
  본 AC는 두 검증(무수정 확인 + 후보 식별 정확도)이 **모두** 성립해야 PASS로
  판정한다 — 어느 한쪽만 성립하는 부분 충족은 FAIL로 처리한다.

### AC-098-007 — `theme_news_carry` 키워드 분포 지표가 일일 로깅된다

**When** 관측 잡이 실행되면, the system **shall** AC-AI091-009와 동일한 정의로
계산한 "10개 보유 종목 비율"과 "키워드 개수 중앙값"을 로그 라인에 남겨야 한다.

- 검증 방법: pytest — `caplog`로 두 지표 값이 로그에 포함됨을 확인(fixture DB로
  알려진 분포 구성 후 정확한 수치 검증)

### AC-098-008 — `theme_news_carry` 일일 시그널 기여 비율이 로깅된다

**When** 관측 잡이 실행되면, the system **shall**
`surge_backtest.py::_extract_combo_key()`를 재사용해 당일 `surge_candidate` 시그널
중 `theme_news_carry`가 `surge_basis`에 포함된 비율을 계산하고 로그 라인에 남겨야
한다.

- 검증 방법: pytest — `FundSignal` fixture(일부는 `theme_news_carry` 포함, 일부는
  다른 탐지기)로 정확한 비율 계산 확인

### AC-098-009 — 임계값 초과 시 Telegram 경보

**Where** Telegram 경보 임계값이 설정되어 있고 관측된 `theme_news_carry` 기여
비율이 그 임계값을 초과하면, the system **shall** 기존
`send_telegram_message`/`TELEGRAM_ADMIN_CHAT_ID` 채널로 경보 메시지를 발송해야
한다.

임계값이 아직 확정되지 않은 경우(spec.md Open Question 2), 본 AC는 §A AC 매트릭스
상 Should-Pass로 분류되며 미구현이 DoD를 막지 않는다(§E Definition of Done 참고).

- 검증 방법: pytest — 임계값이 config로 주입 가능한 구조인지 확인, 초과 fixture에서
  `send_telegram_message` 호출 여부 mock 검증(구현 시점에 임계값이 미확정이면 이
  검증은 "호출 지점이 존재하고 config 미설정 시 안전하게 스킵됨"으로 축소 가능)

### AC-098-010 — 기존 검증된 경로 완전 무변경

**While** 본 SPEC이 적용된 상태에서, the system **shall not**
`keyword_tagging_service.py::extract_theme_keywords()`/`refresh_stock_keywords()`,
`ai_classifier.py::_count_keyword_matches()`, `detect_theme_news_carry()`의 전파
로직(테마 활성 게이트, 앵커 자기제외, `max_signals_per_basket`)을 변경해서는 안 된다.

- 검증 방법: 코드 리뷰 — 위 4개 함수 본문에 라인 변경이 없음을 diff로 확인(plan.md
  §C 주의사항 참고, 자동 grep만으로는 불충분해 코드 리뷰를 병행) + 기존
  `test_keyword_tagging_service.py`/`test_spec_ai_091.py` 무수정 통과

```bash
git diff --name-only | grep -E 'keyword_tagging_service\.py|ai_classifier\.py'
```

## §C. Given-When-Then 시나리오 (AC 보강용, AC 정의 아님)

### 시나리오 1 — 별칭 미등록 자회사 언급이 경계 가드 적용 후 매칭된다

- **Given** 종목 Y가 `_STOCK_NAME_ALIASES`에 별칭이 없고, 뉴스 기사에 Y의 공식명이
  조사가 붙은 형태로 언급된다.
- **When** `detect_theme_news_cluster()`를 실행한다.
- **Then** 경계 가드 적용 이후에는 이 기사가 `stock_articles`에 포함되어
  `stock_specific_count >= 1`이 되고, 60/40 블렌딩 경로로 전환된다. (AC-098-001)

### 시나리오 2 — 섹터 전용 페널티 설정이 직접 언급 종목에 영향을 주지 않는다

- **Given** 섹터에 직접 언급 종목 3개, 섹터 전용 종목 7개가 있다.
- **When** `sector_only_penalty=0.2`로 설정하고 재실행한다.
- **Then** 직접 언급 3개의 점수는 변하지 않고, 섹터 전용 7개만 새 배수를 반영한
  낮은 점수로 재계산된다. (AC-098-004)

### 시나리오 3 — `theme_news_carry` 재발 조짐이 로그로 관측된다

- **Given** `stocks.keywords` 분포가 다시 악화되기 시작해(예: 10개 보유 비율이 5%를
  넘기기 시작) SPEC-AI-091 정화 직후보다 높아졌다.
- **When** 일일 관측 잡이 실행된다.
- **Then** 그 수치가 로그에 명시적으로 남아, 수동 조사 없이도 로그 스캔만으로 재발
  조짐을 확인할 수 있다. (AC-098-007)

## §D. Edge Cases

- **경계 가드 적용 후 매칭 0건인 테마**: 기존과 동일하게 `_comention_supplement()`
  폴백 경로로 이어진다 — 본 SPEC은 이 폴백 자체를 변경하지 않는다.
- **`sector_only_max_candidates`가 섹터 전용 후보 수보다 큰 경우**: 절단이 발생하지
  않고 전량 유지된다(현행과 동일) — 상한 값 자체가 no-op이 되는 정상 케이스.
- **관측 잡 실행 시점에 당일 시그널이 0건인 거래일**: `theme_news_carry` 기여
  비율은 분모 0이므로 계산 불가 — `high_based_precision` 계열(SPEC-AI-095 D-패턴)과
  동일하게 `None`/측정 불가로 로깅하고 `ZeroDivisionError`를 발생시키지 않는다.
- **별칭 후보 스크립트가 이미 등록된 별칭을 다시 후보로 제시하는 경우**: 기존
  `_STOCK_NAME_ALIASES` 키 집합과의 차집합만 출력하도록 필터링해 중복 후보를
  제거한다.
- **`_keyword_in_text` 재사용 시 모듈 프라이빗 함수 import**: Python은 언더스코어
  프라이빗 함수의 크로스모듈 import를 문법적으로 막지 않는다 — SPEC-AI-091이 동일
  패턴(`ai_classifier._count_keyword_matches`를 `keyword_tagging_service.py`에서
  import)을 이미 사용했으므로 이 프로젝트의 기존 관례를 벗어나지 않는다.

## §E. Definition of Done

- [ ] AC-098-001 통과 — 경계 가드 적용으로 별칭/자회사 매칭 개선.
- [ ] AC-098-002 통과 — 오탐 없음 + 영문 대소문자 처리.
- [ ] AC-098-003 통과 — 섹터 전용 설정 기본값 바이트 동등.
- [ ] AC-098-004 통과 — `sector_only_penalty` 설정 반영.
- [ ] AC-098-005 통과(Should) — `sector_only_max_candidates` 절단, 직접 언급 종목 무영향.
- [ ] AC-098-006 통과 — 별칭 후보 스크립트가 표를 자동 수정하지 않음.
- [ ] AC-098-007 통과 — 키워드 분포 지표 일일 로깅.
- [ ] AC-098-008 통과 — `theme_news_carry` 기여 비율 로깅.
- [ ] AC-098-009 통과(Should) — 임계값 초과 시 Telegram 경보(임계값 미확정 시
      Should-Pass로 DoD 비차단).
- [ ] AC-098-010 통과 — 기존 검증된 4개 함수/경로 완전 무변경.
- [ ] `ruff check` / `mypy` 통과.
- [ ] 기존 회귀 테스트 전체 통과: `cd backend && uv run pytest tests/ -m "not slow"`.
- [ ] spec.md §Open Questions 1(관측 체크 실행 주기)이 구현 착수 전 확정됨.
- [ ] spec.md §Open Questions 2(Telegram 임계값)와 3(`sector_only_max_candidates` 활성화
      여부)의 미확정 상태는 본 SPEC의 DoD를 막지 않는다 — 로깅/배선까지가 Must-Pass
      범위이며, 활성화·임계값 확정은 관측 데이터 축적 후 별도 판단이다.
