# Research — SPEC-AI-103 테마 클러스터 신선도/중복 가드

## 조사 범위

`detect_theme_news_cluster()`(`backend/app/services/surge_detector.py:286-527`, `theme_cluster` 탐지기,
앙상블 가중치 0.19 — `surge_detection.yaml:67`)에 신선도/중복(dedup) 가드가 없는 문제와,
같은 파일의 형제 탐지기 `detect_volume_surge_news_combo`(`volume_news_combo`)가 이미 갖춘
`combo_chase_guard` 게이트 패턴(`surge_detector.py:984-1030`)을 모델로 한 재사용/적응
가능성을 조사한다. 미션 위임 프롬프트가 이미 검증했다고 명시한 라인 번호·설정 이름을
이 세션에서 다시 대조해 여전히 유효함을 확인했다 — 코드 이동 없음.

## 1. 대상 코드 재확인 (2026-08-05 read-only 재검증)

- `detect_theme_news_cluster()`: `surge_detector.py:286-555`(co-mention 보강 포함).
  - 뉴스 창 조회 `:312-318` — `cluster_window_hours`(기본 48h, `surge_detection.yaml:27`)
    이내 뉴스를 `published_at` 내림차순 `.limit(1000)`으로 DB 직접 조회. 신선도/기사 반복
    검사가 전혀 없다 — raw row count만 본다.
  - 키워드별 활성 테마 판정 `:324-340` — `keyword_counts[kw]`를 `window_news` 전수 순회로
    증가시키고 `min_article_count`(기본 2, `surge_detection.yaml:28`) 이상이면 활성 테마로
    채택. 동일 기사가 여러 매체에 재보도(syndication)되면 `keyword_counts`가 그만큼
    부풀어 실제 매체 수·독립 취재 여부와 무관하게 활성화 임계를 쉽게 통과한다.
  - 종목별 기사 귀속 `:442-450` — `stock_articles`는 `_keyword_in_text`(SPEC-AI-098
    REQ-AI098-001, `keyword_matcher.py:43`)로 양방향 경계 가드까지는 확보했으나, 여기도
    "몇 건의 서로 다른 기사가 이 종목을 언급했는가"만 세고 "그 기사들이 서로 다른
    사건/취재인가"는 검사하지 않는다.
  - 블렌딩 공식 `:453-460` — `theme_cluster_score = theme_base*0.6 + stock_article_score*0.4`
    (직접 언급) 또는 `theme_base * cfg.sector_only_penalty`(섹터 전용, 기본 0.5). 둘 다
    `theme_base = min(1.0, cnt/10)`에서 파생되므로, 중복/재보도로 부풀려진 `cnt`는 두
    분기 모두를 오염시킨다.
  - 섹터 전용 절단 `:515-532` — SPEC-AI-098이 추가한 `sector_only_max_candidates`
    (기본 `None`=무제한)로 `theme_cluster_score` 내림차순 상위 N개만 유지. 이 절단은
    이미 계산된 점수를 정렬할 뿐, 그 점수 자체의 진부화/중복 오염은 건드리지 않는다.
  - Co-mention 보강 경로(`:538-552`, `_comention_supplement` `:563-`, SPEC-AI-066 REQ-004)는
    이번 SPEC의 대상이 아니다 — 별도 임시 테마 파생 로직이며 신선도/중복 문제의 발생
    지점이 다르다(§Non-Goals 참고).

- `detect_volume_surge_news_combo()`의 `combo_chase_guard` 게이트(모델 삼을 패턴):
  `surge_detector.py:984-1030`, 설정 클래스 `ComboChaseGuardConfig`
  (`surge_settings.py:295`), yaml 블록 `combo_chase_guard:`(`surge_detection.yaml:202-212`).
  - **Gate 1 — 과열 필터**(`:993-1011`): `_fetch_price_change_sync`로 얻은 당일
    `change_rate`가 `overheat_change_pct`(기본 5.0, 확신도 HIGH는 15.0) 이상이면 제외.
    "가격이 이미 움직였다"는 즉, **가격 기반** 신선도 신호.
  - **Gate 2 — 거래량 신선도**(`:1013-1021`): `volumes[-1]/volumes[-2]`(당일/전일 거래량
    비율)이 `min_freshness_ratio`(기본 1.5) 미만이면 "stale"로 제외. **시간축 기반**
    신선도 신호 — 거래량 대신 "본 SPEC은 기사 활동"을 같은 방식으로 볼 수 있다.
  - **Gate 3 — 분산 패턴 거부**(`:1024-1030`): `change_rate < distribution_change_pct`
    (기본 0.0)면 제외(거래량은 느는데 가격은 빠지는 분산 패턴).
  - 게이트 전체는 `cfg_guard.enabled`(기본 `true`, 프로덕션 활성) 단일 스위치로 켜지며,
    `combo_score` 계산 이후 최종 `results.append` 직전에 적용된다(사후 필터, 사전 배제
    아님) — theme_cluster에 이식할 때도 "점수 계산 후 필터/디스카운트" 위치가 자연스럽다.

## 2. 핵심 제약 — SPEC-AI-038이 의도적으로 제거한 가격 API 호출

`surge_detector.py:465-471`(theme_cluster 내부, 주석 원문 보존):

> "SPEC-AI-038 성능 패치 최종판: detect_theme_news_cluster에서 가격 API 호출 완전 제거...
> 921종목 × 0.6s/call = 550초 → timeout 직접 원인... 효과: O(N×API_latency) → O(N)
> 순수 메모리 연산".

이는 이번 SPEC이 반드시 지켜야 할 하드 제약이다: `combo_chase_guard`의 Gate 1(과열
필터)을 **그대로** theme_cluster의 메인 종목 순회 루프(`:407-527`, 모든 섹터 소속
종목을 순회)에 이식하면 SPEC-AI-038이 고친 정확히 그 회귀를 재현한다. 볼륨콤보는
후보가 이미 거래량 이상치로 사전 필터링된 소수 종목이라 종목당 1회 가격 호출이
감당 가능하지만, theme_cluster는 활성 섹터의 **전체** 종목(예: 반도체 50+종목)을
순회하므로 조건이 다르다.

- 배치 대안 존재: `fetch_stock_price_history_batch_sync`(`naver_finance.py:863`)는
  이미 이 파일의 다른 지점(`:4722-4745` Pool B, `:5142-5186` build_scan_universe)에서
  종목 리스트를 **한 번에** 배치 조회하는 데 쓰이고 있다 — per-stock synchronous
  호출이 아니라 per-scan 1회 배치 호출이다. 이 패턴은 theme_cluster에도 재사용
  가능하지만, 반드시 **이미 상한이 걸린 소수 후보 집합**(예: SPEC-AI-098
  `sector_only_max_candidates` 절단 이후)에만 적용해야 SPEC-AI-038 제약을 재위반하지
  않는다.
- `NewsArticle`/`Stock` 모델에는 시가(open_price) 개념이 없으므로(에이전트 메모리
  `project-surge-detector-constraints` 재확인: `change_rate`만 가용, 전일 종가 대비),
  "과열"은 볼륨콤보와 동일하게 `change_rate` 기준으로만 판단 가능하다.

## 3. 중복/재보도(syndication) 탐지 — 재사용 가능 자산 조사

- 코드베이스 전체에서 `rapidfuzz`/`thefuzz`/`Levenshtein`/`difflib` 사용처를 검색한 결과
  **0건** — 유사도 기반 중복 탐지 라이브러리·유틸이 이 프로젝트에 존재하지 않는다.
  `pyproject.toml`에도 해당 의존성 없음(에이전트 메모리 "backend has NO numpy/scipy/
  sklearn" 재확인 패턴과 일관).
- `keyword_matcher.py::_keyword_in_text`(`:43`)는 경계 가드 매칭이지 기사 간 유사도
  비교가 아니다 — 재사용 대상이 아니다.
- `NewsArticle`(`models/news.py:9-29`) 필드: `title`(500자), `summary`, `url`(고유,
  `unique=True`), `source`(50자, 매체명), `published_at`, `content`. `url`이 UNIQUE라
  동일 URL 재수집은 애초에 불가능하지만, 서로 다른 매체가 같은 통신사 기사를 각자
  URL로 재게시하는 경우(전형적 syndication)는 `url`/`source` 모두 다르므로 URL 기반
  중복 제거로는 잡히지 않는다.
- **Simplicity Ladder 적용 결과**: 신규 서드파티 의존성 없이, Python 표준 라이브러리
  `difflib.SequenceMatcher`(현재 `surge_detector.py`에 미import, 추가는 표준 라이브러리
  범위 내)로 제목 유사도를 계산할 수 있다 — Ladder 3단계("표준 라이브러리가 이를
  하는가? 사용하라")를 충족하는 유일한 실질 후보.
- 소스(`source`) 다양성만으로 중복을 판정하는 대안은 기각한다: 동일 매체가 같은
  기사를 재게시하는 경우와, 서로 다른 매체가 독립적으로 같은 사건을 취재하는 경우를
  `source` 필드만으로는 구분할 수 없고, 오히려 "여러 매체가 동시 보도" 자체가
  통신사발 syndication의 전형적 signature이므로 소스 다양성 요건은 중복탐지 목적에
  역행할 수 있다(§Decisions D2에서 기각 사유 재정리).

## 4. 성능 경계 조건 — O(N²) 회피 필요

`window_news`는 최대 1000건(`:316` `.limit(1000)`)이다. 제목 유사도를 전수 쌍대 비교로
계산하면 최악 O(1000²)=최대 100만 쌍의 `SequenceMatcher.ratio()` 호출이 발생할 수 있어,
SPEC-AI-082가 이미 문제 삼은 "정상 실행 12~15분" 지연 예산을 다시 압박할 위험이 있다.
그러나 실제 필요한 비교 범위는 훨씬 좁다:

- 테마 활성 판정(`keyword_counts`)은 이미 **키워드별로 분리된 부분집합**을 순회하는
  구조다(`:326-330`) — 한 키워드에 매칭되는 기사 수는 전체 창(최대 1000)보다 훨씬
  작다(관측 사례: 활성 테마당 2~수십 건). 중복 판정을 "키워드 매칭 기사 부분집합
  내부"로 한정하면 쌍대 비교 비용이 자연히 유계(bounded)가 된다.
- 종목별 기사 귀속(`stock_articles`, `:443-450`)도 이미 종목당 소수(단자리~10건대)
  리스트로 materialize되어 있어 그 안에서의 쌍대 비교는 무시할 수준이다.
- 따라서 "전체 window_news 쌍대 비교"가 아니라 "이미 코드가 만들어 둔 좁은 부분집합
  내부에서만 비교"로 범위를 좁히는 것이 이 SPEC의 성능 설계 핵심이다(plan.md M2에서
  구체화).

**plan-audit iteration 1 조치(D6) — 경험적 관측을 구조적 상한으로 승격**: 위
"관측 사례: 활성 테마당 2~수십 건"은 어디까지나 관측이며, 범용/고빈도 키워드가
비정상적으로 넓은 부분집합에 매칭될 가능성 자체를 배제하지 않는다. 이에 따라
spec.md §Decisions D4와 plan.md §C에 **하드 캡**(`dedup_max_comparison_batch`,
기본 200)을 명시적으로 추가했다 — 부분집합이 캡을 초과하면 캡 이후(오래된)
기사는 비교 없이 원본 그대로 개별 집계로 안전하게 열화하므로, dedup 비교
비용은 관측치와 무관하게 항상 O(200²)로 코드가 강제하는 유계 상태가 된다.

## 5. 결정 요약 (§Decisions로 spec.md에 반영됨)

1. **신선도**: 볼륨콤보 Gate 2(거래량 신선도 비율)를 시간축(기사 발행 시각)으로
   재해석 — 신규 가격 API 호출 없이 `window_news`에 이미 있는 `published_at`만
   사용. Gate 1(가격 과열)의 직접 이식은 SPEC-AI-038 제약과 충돌하므로 기각.
2. **가격 과열(Gate 1 유사 기능)**: SHOULD-PASS 옵션으로만, SPEC-AI-098
   `sector_only_max_candidates` 절단 **이후**의 이미 상한 걸린 소수 후보에 한해
   기존 배치 헬퍼(`fetch_stock_price_history_batch_sync`)를 재사용 — 기본값 비활성.
3. **중복/재보도**: `difflib.SequenceMatcher`(표준 라이브러리) 기반 제목 유사도 +
   발행 시각 근접도 조합, 이미 좁혀진 부분집합(키워드별/종목별) 내부에서만 비교해
   O(N²) 위험을 구조적으로 차단.
4. **기본값**: 이 코드베이스의 최근 SPEC 전반(AI-066/079/091 등)이 반복 채택한
   "기본 비활성 → 관측 → 별도 판단으로 활성화" 단계적 롤아웃 패턴을 따른다 — 최초
   배포는 회귀 위험 0(바이트 동등)을 최우선한다.
5. **하드 캡(D6, iteration 1 조치)**: 중복 비교 부분집합 크기 자체에
   `dedup_max_comparison_batch`(기본 200) 상한을 두어, "부분집합이 작다"는
   경험적 관측이 깨지는 경우에도 dedup 비교 비용이 항상 O(200²)로 유계됨을
   코드로 강제한다.

## Cross-references

- `.moai/specs/SPEC-AI-098/spec.md` — 이 함수의 가장 최근 완료 변경(경계 가드,
  섹터 전용 스코어링 설정화). 본 SPEC은 그 위에 얹는다.
- `.moai/specs/SPEC-AI-030/spec.md` — `combo_chase_guard` 원 설계(모델 소스).
- `.moai/specs/SPEC-AI-038` — 가격 API 제거 성능 패치(제약 근거, 별도 SPEC 디렉터리
  미확인 시 `surge_detector.py:465-471` 인라인 주석이 1차 증거).
- `.claude/agent-memory/manager-spec/project_surge_detector_constraints.md` —
  `change_rate`-only 제약, 일봉 전용 거래량 제약 재확인.
