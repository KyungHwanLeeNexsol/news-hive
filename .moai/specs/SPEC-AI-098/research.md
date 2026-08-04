# SPEC-AI-098 Research — 테마 클러스터 뉴스-종목 매칭 및 별칭/관측성 개선

## 목적

이 문서는 spec.md 작성 전 라이브 코드를 직접 읽어 확인한 사실을 기록한다. 위임 프롬프트에
포함된 5개 "검증된 현황" 항목을 모두 코드 대조로 재확인했고, 그중 2건은 **부정확하거나
과대해석된 부분이 있어 정정**했다(§정정 사항 참고). manager-spec은 검증 도구 없이 방어 주장을
하지 않는다는 원칙(verification-claim-integrity)에 따라 정정 내용을 숨기지 않고 명시한다.

## 0. SPEC ID 배정 경위

원 위임은 "다음 자유 번호는 SPEC-AI-096 근처, 동일 배치의 형제 SPEC과 충돌 가능성이 있으니
098 부근으로 착지할 수 있다"고 예고했다. 실제로 작업 중 `.moai/specs/` 재확인 결과
**SPEC-AI-096**(스캔 유니버스 파이프라인 주제, 다른 형제 세션이 이미 research.md/spec.md
작성 중)과 **SPEC-AI-097**(이미 4개 파일 완성)이 모두 선점되어 있어, 096으로의 최초
Write 시도가 파일 충돌 안전장치(Read-before-Write)에 의해 차단되었다. 손상 없이
**SPEC-AI-098**로 재배정했다(098/099/1xx 전체 재확인 결과 미점유 확인).

## 1. 뉴스-종목 매칭 3개 경로의 실제 구현 확인

이 프로젝트에는 "뉴스/공시 텍스트에 특정 문자열이 포함되는가"를 판정하는 서로 다른
**3개의 독립 구현**이 존재한다. 위임 프롬프트는 이를 2개(가드 있음 vs 가드 없음)로
단순화했으나, 실제로는 가드 강도가 다른 2개의 가드 + 가드 없는 1개로 3분된다.

| 경로 | 위치 | 가드 방식 | 소비 도메인 |
|------|------|-----------|-------------|
| A. 사용자 팔로잉 키워드 알림 | `keyword_matcher.py::_keyword_in_text`(43-79행) | **완전 양방향 경계 가드** — 한글 조사 인식 정규식(64-76행) + 영문/숫자 `(?<![a-zA-Z0-9\-])...(?![a-zA-Z0-9\-])`(78행) | `match_keywords_and_notify()` — SPEC-FOLLOW-001 |
| B. 테마 키워드 → 종목 태깅 | `keyword_tagging_service.py::extract_theme_keywords()`(101-136행) → `ai_classifier.py::_count_keyword_matches()`(398-418행) | **선행문자 전용 가드** — 매칭 문자열 직전 글자가 한글 음절(`가`~`힣`)이면 거부, **후행 경계는 검사하지 않음** | `stocks.keywords` 백필/갱신 — SPEC-AI-084/091 |
| C. 테마 클러스터 종목별 기사 카운트 | `surge_detector.py:434-438`(`_get_name_variants` + `stock_articles` 리스트 컴프리헨션) | **가드 없음** — `v in text`, `stock.stock_code in text` 순수 substring | `detect_theme_news_cluster()` 스코어링 — SPEC-AI-012/014 |

### 정정 사항 1 — "SPEC-AI-091이 `keyword_matcher.py`와 `keyword_tagging_service.py` 양쪽에
경계 가드를 추가했다"는 위임 프롬프트의 서술은 부정확하다

SPEC-AI-091(`spec.md:212-215` REQ-AI091-003)은 "기존 코드베이스에 이미 확립된 경계 가드
패턴을 재사용"하라고 명시했고, 실제 구현은 **`ai_classifier.py::_count_keyword_matches`를
재사용**했다(경로 B) — `keyword_matcher.py::_keyword_in_text`(경로 A, 더 강한 완전
양방향 가드)를 호출하지 않는다. `grep "_keyword_in_text" keyword_tagging_service.py` →
0건(직접 확인). 두 가드는 **강도가 다르다**: 경로 A는 선행+후행 경계를 모두 검사하고
한글 조사 활용형까지 인식하지만, 경로 B는 선행 문자만 검사한다(후행 경계 미검사 — 예:
"현대"가 "현대차그룹"의 앞부분에 매칭되는 것은 경로 B 기준으로는 막히지 않는다, 후행
검사가 없으므로). 이 차이는 두 경로가 서로 다른 SPEC(FOLLOW-001 vs AI-084/091)이 서로
다른 시점에 독립적으로 발전시킨 결과이며, 본 SPEC이 새로 만든 문제가 아니다.

**결론**: 경로 C(본 SPEC의 실제 대상)가 재사용해야 할 "기존에 확립된 경계 가드"는 두 개
중 하나를 선택해야 하는 상황이며, 위임 프롬프트가 전제한 "이미 하나로 통일되어 있다"는
가정은 사실이 아니다. §Decisions D1에서 어느 쪽을 재사용할지 근거와 함께 결정한다.

### 정정 사항 2 — `NewsStockRelation`은 별칭 검증에 쓸 수 있는 독립적 정답 소스가 아니다

위임 프롬프트는 별칭 확장을 "semi-automated alias derivation from stocks.keywords or
similar"로 제안했다. 두 후보를 직접 확인했다.

- **`stocks.keywords`**: `ThemeClusterConfig.keywords`(고정 20개 테마 어휘, 예: "반도체",
  "2차전지")를 뉴스/공시 텍스트에서 감지해 채우는 **주제 태그**다(`keyword_tagging_service.py`
  모듈 docstring 1-17행). 종목명의 별칭/약칭(예: "삼성SDS")과는 **범주가 다른 데이터**이며,
  이름 별칭을 파생시킬 수 있는 원천이 아니다.
- **`NewsStockRelation`**: `news_crawler.py::_resolve_query_relations()`(251-303행)가
  생성하며, `relevance="direct"`는 크롤러가 **검색 쿼리로 사용한 종목 공식명**(`index.stock_names`,
  DB `stock.name` 자체)이 정확히 일치할 때만 부여된다(261-268행). 즉 이 관계 테이블도
  결국 DB 공식명 매칭에서 파생되므로, 별칭 매칭이 놓친 종목을 교차검증할 **독립적** 정답
  집합이 아니다 — 같은 맹점(별칭 미보유)을 공유한다.

**결론**: "기존 데이터에서 자동 파생"이라는 손쉬운 경로는 존재하지 않는다. 별칭 확장은
(a) 사람이 검토하는 후보 제안 도구, 또는 (b) 순수 수동 큐레이션 중 하나로 좁혀야 한다.
§Decisions D2에서 실제 관측된 별칭 패턴(한글 음역 vs 영문 약칭)에 기반한 규칙 기반 후보
생성기를 제안한다.

## 2. `_STOCK_NAME_ALIASES` 현황 (surge_detector.py:30-44)

11개 항목 전부 대형주다. 관찰된 패턴: DB 공식명이 영문 법인 접미어의 **한글 음역**이고
(예: "에스케이"=SK, "엘지"=LG, "에스디에스"=SDS), 뉴스에서는 **영문/혼용 약칭**이 더 흔히
쓰인다.

```python
_STOCK_NAME_ALIASES: dict[str, list[str]] = {
    "삼성에스디에스": ["삼성SDS"],
    "에스케이텔레콤": ["SKT", "SK텔레콤"],
    "에스케이하이닉스": ["SK하이닉스"],
    "에스케이이노베이션": ["SK이노베이션"],
    "엘지에너지솔루션": ["LG에너지솔루션"],
    "엘지전자": ["LG전자"],
    "엘지화학": ["LG화학"],
    "엘지디스플레이": ["LG디스플레이"],
    "현대모비스": ["MOBIS"],
    "카카오뱅크": ["카카오 뱅크"],
    "카카오페이": ["카카오 페이"],
}
```

이 패턴(한글 음역된 영문 음절 — "에스"=S, "케이"=K, "엘"=L, "지"=G, "디"=D 등)은 규칙
기반으로 후보를 생성할 수 있는 유일하게 신뢰 가능한 하위 집합이다. 그 외(자회사명,
제품명만 언급되는 경우)는 규칙화가 어려워 사람 큐레이션이 필요하다.

## 3. 직접 언급 vs 섹터 전용 스코어링 분기 (surge_detector.py:432-452)

```python
_name_variants = _get_name_variants(stock.name)             # 434
stock_articles = [                                            # 435-439
    a for a in window_news
    if any(v in (a.title or "") + " " + (a.content or "") for v in _name_variants)
    or stock.stock_code in (a.title or "") + " " + (a.content or "")
]
stock_specific_count = len(stock_articles)                    # 440
...
if stock_specific_count >= 1:                                 # 444
    theme_cluster_score = (best_theme_base * 0.6) + (stock_article_score * 0.4)  # 446
else:
    theme_cluster_score = best_theme_base * 0.5               # 449 — 섹터 전용 flat penalty
theme_cluster_score *= best_sector_relevance                  # 452
```

직접 언급 종목은 60/40 블렌딩, 섹터 전용(직접 언급 0건)은 `best_theme_base`(활성 테마
기사 수 기반, `min(1.0, cnt/10)`)에 **고정 0.5배**만 적용한다. 섹터 소속 종목 수와
무관하게 동일한 0.5 배수가 적용되므로, 섹터 규모가 클수록(예: 반도체 섹터 50+ 종목) "그
섹터 전체가 테마 활성화 시 균등하게 0.5×theme_base 점수를 받는" 과대 포함이 구조적으로
발생한다. 이는 스코어 산식 자체의 결함이 아니라 **섹터 크기를 전혀 반영하지 않는다는
설계 공백**이다.

시총 필터(`min_market_cap_krw` 환산, 378-392행)와 뉴스 언급 종목 우선 포함(NULL 시총
한정, SPEC-AI-038)이 이미 존재하나, 이는 "포함 여부"만 다루고 "포함된 이후의 점수 크기"는
다루지 않는다.

## 4. `detect_theme_news_cluster()`의 뉴스 스캔 범위 (surge_detector.py:308-317)

```python
window_news = (
    db.query(NewsArticle)
    .filter(NewsArticle.published_at >= cutoff_naive)
    .order_by(NewsArticle.published_at.desc())
    .limit(1000)
    .all()
)
```

`cluster_window_hours`(설정값) 내 뉴스를 최대 1000건까지 조회한다 — 위임 프롬프트의
"최근 뉴스 최대 1000건 스캔"은 정확하다.

## 5. `theme_news_carry` 재활성화 확인 (surge_settings.py:741-762)

```python
enabled: bool = True   # 762행
```

`git log -1 63de7f6` → `2026-08-03 09:45:31 +0900 feat(SPEC-AI-084): theme_news_carry
플래그 재활성화 (그룹 A)` — **오늘 날짜**(currentDate=2026-08-03)에 재활성화되었으며,
프로덕션 재활성화 이후 관측 데이터가 존재하지 않는다는 위임 프롬프트의 전제는 정확하다.

751-761행 주석은 2026-07-28 오염 사건(720개 종목 중 144개, 20%가 10개 테마 전부 보유,
당일 신호 69건 중 53건=77%가 오염된 keywords 기반)과 SPEC-AI-091 배포 + `--execute`
정화 실행 후 AC-AI091-009(10개 보유 비율 ≤5%, 중앙값 ≤4)/AC-AI091-010(지정 3종목
≤3개) 재측정 통과를 근거로 재활성화했다고 기록한다.

### 관측성 공백 확인 — `detect_theme_news_carry()`(surge_detector.py:3261-3419)

완료 시 로그는 집계 2개 값뿐이다(3409-3413행):

```python
logger.info(
    "[theme_news_carry] 평가 %d개 바스켓, 시그널 %d건 생성",
    baskets_evaluated,
    len(signals),
)
```

바스켓별/키워드별 세부 로그, 또는 AC-AI091-009/010이 정의한 "10개 보유 비율·중앙값"
지표를 재측정하는 **반복 가능한(recurring) 자동 체크는 존재하지 않는다** —
`backend/scripts/remediate_keyword_tagging.py`는 1회성 정화/측정 스크립트이며 스케줄러에
등록되어 있지 않다(`grep -rn "remediate_keyword_tagging" backend/app/services/scheduler.py`
→ 0건, 직접 확인). 유사하게, 일일 시그널 중 `surge_basis`에 `theme_news_carry`가 차지하는
비율을 추적하는 체크도 없다 — 2026-07-28 사건 자체가 이 비율(77%)로 발견되었음에도,
그 발견은 수동 조사였다(project memory 확인).

기존에 재사용 가능한 유틸리티: `surge_backtest.py::_extract_combo_key()`(228-243행)가
`FundSignal.surge_metadata`에서 `surge_basis` 리스트를 정렬된 `"+"` 조합 키로 추출하는
로직을 이미 제공한다 — 신규 파싱 로직을 발명할 필요 없이 이를 재사용할 수 있다.

`keyword_backfill` 잡(scheduler.py:2165-2171, 24시간 주기, `backfill_stock_keywords()`
호출)은 NULL/빈 keywords만 백필하는 idempotent 잡이다 — 기존에 채워진 keywords를 재검사하지
않으므로 이 잡을 관측성 체크의 숙주로 그대로 재사용할 수는 없다(신규 함수가 필요하나 같은
잡 등록 패턴은 재사용 가능). `refresh_stock_keywords()`는 뉴스 크롤 사이클마다 실시간
트리거된다(`news_crawler.py:895-897`, `_should_touch_stock_for_tagging()` direct-relevance
게이트 경유) — keywords 오염이 다시 누적된다면 이 경로를 통해서일 가능성이 높다.

## 6. Non-Goals 경계 확인

- `evaluate_high_based_outcomes()`, `build_scan_universe()`, `SurgePredictionEvaluation`
  등 다른 세션/형제 SPEC(SPEC-AI-094/095, 그리고 이번 배치의 SPEC-AI-096/097) 대상 파일은
  본 조사에서 전혀 건드리지 않았다.
- `ThemeGroupCarryConfig`/`detect_theme_group_carry_forward()`(SPEC-AI-025, 계열/지분
  그룹 전용)는 `theme_news_carry`와 이름이 유사하나 별개 탐지기다 — 본 SPEC은 후자만
  다룬다.

## 7. Open Question 후보 (spec.md로 이월)

1. 관측성 체크의 실행 주기 — 매 15:20/10:00 스캔 사이클마다인지, 일 1회 집계인지.
   AC-AI091-009 지표 자체가 DB 스냅샷 집계라 일 1회가 자연스러우나, 최종 확정은
   plan.md TASK 단계에서.
2. Telegram 경보 임계값 — 2026-07-28 사건의 77%는 이상치 1개 데이터포인트일 뿐, "정상"
   구간의 기준선이 관측된 적이 없다. 근거 없는 정밀한 숫자를 제시하지 않고 Open Question으로
   유지한다(§Decisions D4).
