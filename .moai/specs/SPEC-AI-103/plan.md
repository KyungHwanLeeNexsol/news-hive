# Plan — SPEC-AI-103 테마 클러스터 뉴스 신선도/중복(dedup) 가드

## §A 기술적 접근 개요

DDD(ANALYZE-PRESERVE-IMPROVE) 모드로 진행한다(`.moai/config/sections/quality.yaml`
`development_mode: ddd`). 대상은 단일 함수 `detect_theme_news_cluster()`
(`backend/app/services/surge_detector.py:286-527`)이며, 신규 헬퍼 함수 2개
(중복 제거, 신선 비율 계산)와 신규 설정 클래스 1개를 추가한다. 신규 DB
테이블/마이그레이션은 없다(§Constraints 참고).

마일스톤은 **변경 가능성(decision-reversibility)이 높은 결정부터** 배치한다 —
설정 스키마(필드명·기본값·타입)가 가장 되돌리기 어렵고(다른 SPEC이 곧 이 필드를
참조할 수 있음), 기계적인 테스트 작성/설정 배선이 가장 나중이다.

## §B 설정 스키마 결정 (M1에서 확정 — 가장 높은 변경 가능성)

`ThemeClusterConfig`(`surge_settings.py:38-53`)에 신규 필드를 직접 추가하는 대신,
`ComboChaseGuardConfig`(`surge_settings.py:295`, `combo_chase_guard` yaml 블록)와
동일한 전례를 따라 **독립 중첩 설정 클래스**를 신설한다 — 이 가드는
`combo_chase_guard`처럼 명확한 게이트 정체성을 가지며, 향후 확장(예:
REQ-AI103-004 활성화) 여지를 남긴다.

제안 스키마(구현 시 최종 확정, spec.md Open Question 1과 연동):

```
class ThemeFreshnessGuardConfig(BaseModel):
    enabled: bool = False
    duplicate_title_similarity_threshold: float = 0.85
    duplicate_dedup_window_hours: float = 6.0
    dedup_max_comparison_batch: int = 200      # D6 하드 캡 — 부분집합 비교 비용을 O(캡²)로 유계(구조적 보장, 관측 아님)
    min_theme_freshness_ratio: float = 0.0
    fresh_window_hours: float | None = None  # None → cluster_window_hours/2로 파생
    freshness_discount_factor: float = 0.5
    price_overheat_enabled: bool = False       # REQ-AI103-004 서브기능 스위치
    price_overheat_change_pct: float = 15.0    # combo_chase_guard.overheat_change_pct_high_conviction와 정합
```

- `SurgeDetectionConfig`(`surge_settings.py:493` 인근)에
  `theme_freshness_guard: ThemeFreshnessGuardConfig = Field(default_factory=...)`로
  등록한다 — `combo_chase_guard` 필드 등록 패턴과 동일.
- yaml 블록 `theme_freshness_guard:`를 `surge_detection.yaml`의 `theme_cluster:`
  블록 근처(또는 `combo_chase_guard:` 옆, 게이트류 블록 그룹핑)에 신설한다.
  `enabled: false`로 명시 배포 — REQ-AI103-002 바이트 동등 계약의 1차 증거.
- `min_theme_freshness_ratio: float = 0.0` 기본값은 "감쇠 조건이 항상 거짓"이
  되도록 선택했다 — `freshness_ratio >= 0.0`은 항상 참이므로 `enabled=True`로
  전환해도 이 임계값이 0.0으로 남아 있는 한 감쇠가 발동하지 않는다. 이는
  "활성화"와 "감쇠 발동"을 분리하는 2단 스위치로, SPEC-AI-066/079 등 이
  코드베이스의 반복 관례(플래그 on → 관측 → 임계값 별도 튜닝)와 일치한다.

## §C 중복 제거 알고리즘 설계 (M2)

신규 헬퍼(예: `_dedup_near_duplicate_articles(articles: list[NewsArticle], cfg:
ThemeFreshnessGuardConfig) -> list[NewsArticle]`)를 `surge_detector.py`에 추가한다.

- 신규 표준 라이브러리 import: `import difflib`(research.md §3 — 신규 서드파티
  의존성 없음).
- 제목 정규화: 공백 축약 + 소문자화(영문 부분) 정도의 경량 정규화만 수행한다
  (형태소 분석 등 무거운 NLP 도입 금지 — Simplicity Ladder).
- 판정 조건(AND): `difflib.SequenceMatcher(None, norm_a, norm_b).ratio() >=
  cfg.duplicate_title_similarity_threshold` **그리고** 두 기사의 `published_at`
  차이가 `cfg.duplicate_dedup_window_hours` 이내.
- **비교 범위 제한(성능, research.md §4)**: 이 헬퍼는 전체 `window_news`(최대
  1,000건)에 대해 호출하지 않는다. 대신:
  - 테마 활성 판정 경로(`:324-340`): 키워드별 매칭 기사 부분집합을 먼저
    materialize(현재는 카운트만 증가시키는 인라인 루프 — 이를
    `keyword_to_articles: dict[str, list[NewsArticle]]`로 바꾸는 최소 리팩터
    필요)한 뒤, 그 부분집합 내부에서만 중복 제거 → `keyword_counts[kw] =
    len(dedup(...))`.
  - 종목별 기사 귀속 경로(`:442-450`): 이미 materialize된 `stock_articles`
    리스트(종목당 소수)에 그대로 적용.
  - 두 경로 모두 O(부분집합²)이며 부분집합 크기가 유계이므로 전체 비용도 유계.
  - **하드 캡(D6, plan-audit D6 조치)**: 위 두 부분집합 모두, 크기가
    `cfg.dedup_max_comparison_batch`(기본 200)를 초과하면 `published_at`
    내림차순으로 정렬해 최신 200건만 dedup 비교 대상으로 삼고, 그 이후(더
    오래된) 기사는 비교 없이 원본 그대로 개별 집계에 포함한다. 이로써
    "관측 사례상 부분집합이 작다"는 경험적 가정이 깨지더라도(예: 범용
    키워드가 창 내 500건에 매칭) dedup 비교 연산량은 항상 O(200²) 이내로
    유계됨이 코드로 보장된다 — 관측적 안정성이 아닌 구조적 상한.
- `enabled=False`(기본값)일 때는 이 헬퍼를 호출하지 않고 기존 raw count 경로를
  그대로 유지한다(REQ-AI103-002).

## §D 신선 비율 알고리즘 설계 (M3)

신규 헬퍼(예: `_compute_theme_freshness_ratio(deduped_articles: list[NewsArticle],
cfg: ThemeFreshnessGuardConfig) -> float`)를 추가한다.

- `fresh_cutoff = now - timedelta(hours=cfg.fresh_window_hours or
  cfg.cluster_window_hours/2)`.
- `freshness_ratio = len([a for a in deduped_articles if a.published_at >=
  fresh_cutoff]) / len(deduped_articles)` — 분모 0 방어(중복 제거 후에도
  `min_article_count` 게이트를 이미 통과했으므로 이론상 0이 될 수 없으나,
  방어적으로 `max(1, len(...))` 또는 조기 반환 처리한다(REQ-AI103-003 필수 조건).
- 적용 지점: `theme_base = min(1.0, cnt/10)` 산출 직후(`:426`) — 신선 비율이
  `cfg.min_theme_freshness_ratio` 미만이면 `theme_base *=
  cfg.freshness_discount_factor`. 이 위치는 `combo_chase_guard`가 `combo_score`
  계산 이후 최종 append 직전에 게이트를 거는 것과 동일한 "사후 조정" 철학을
  따른다.

## §E 가격 과열 서브기능 설계 (M4, SHOULD-PASS — 후속 분리 가능)

REQ-AI103-004 구현 여부는 plan-audit/Implementation Kickoff Approval 단계에서
사용자와 함께 재확인한다(spec.md Open Question 2). 구현할 경우:

- 적용 지점: `:515-532`(SPEC-AI-098 `sector_only_max_candidates` 절단) **직후**,
  절단된 `_keep_indices`에 해당하는 종목 코드만 대상으로.
- 가격 조회: `fetch_stock_price_history_batch_sync`(`naver_finance.py:863`,
  Pool B/build_scan_universe와 동일 헬퍼 재사용) 1회 배치 호출 — 종목별 개별
  `_fetch_price_change_sync` 호출 금지(REQ-AI103-005).
- 과열 판정: 배치로 얻은 일봉 이력에서 테마 활동 시작(창의 첫 활성 기사 발행
  시각에 가장 가까운 거래일) 종가 대비 최신 종가 변화율이
  `cfg.price_overheat_change_pct`(기본 15.0) 이상이면 감쇠/제외.
- `price_overheat_enabled=False`(기본) 또는 `sector_only_max_candidates is None`
  이면 이 서브기능은 완전히 스킵된다.

## §F 마일스톤

1. **M1 — 설정 스키마 확정**: `ThemeFreshnessGuardConfig` 필드 세트/기본값/yaml
   블록 위치 확정(§B). 가장 되돌리기 어려운 결정이므로 최우선 확정.
2. **M2 — 중복 제거 함수 설계 확정**: 알고리즘·비교 범위 한정·헬퍼 시그니처
   확정(§C). 신규 타입 인터페이스 결정.
3. **M3 — 신선 비율 함수 설계 확정 + 적용 지점 확정**: 헬퍼 시그니처·
   `theme_base` 감쇠 적용 위치 확정(§D).
4. **M4 — 가격 과열 서브기능 범위 확정(선택)**: 포함/제외 여부를 Implementation
   Kickoff Approval에서 재확인 후 확정(§E). 가장 추측적이므로 뒤에 배치.
5. **M5 — 특성화 테스트 작성(DDD PRESERVE, REQ-AI103-006)**: 가드 도입 이전
   `detect_theme_news_cluster()`의 대표 픽스처 출력을 캡처하는 테스트를 먼저
   작성·통과 확인. 테스트 홈: `backend/tests/test_spec_ai_103.py`(SPEC-AI-098
   전례의 `test_spec_ai_098.py` 명명 관례 계승).
6. **M6 — 구현 + 신규 동작 테스트 + 설정 배선 + 관측성 로깅**: M1-M4에서 확정한
   설계를 `surge_detector.py`/`surge_settings.py`/`surge_detection.yaml`에
   반영, 신규 동작 테스트 작성, REQ-AI103-007 디버그 로그 추가, 전체 회귀
   스위트 실행.

## §G PRESERVE 목록 (변경 금지 대상)

- `compute_ensemble_score()`, 5개 탐지기 그룹핑, 앙상블 가중치 값 일체.
- `sector_only_penalty`/`sector_only_max_candidates` 값 및 그 절단
  메커니즘(SPEC-AI-098) — 본 SPEC의 가격 과열 서브기능은 그 절단 **결과**를
  소비만 하고, 절단 순서나 값을 바꾸지 않는다.
- `combo_chase_guard`(`ComboChaseGuardConfig`) 임계값/로직 — 참고 모델일 뿐
  원본은 무수정.
- `_comention_supplement`/`_derive_comention_theme_candidates`(SPEC-AI-066
  REQ-004) — co-mention 보강 경로는 본 SPEC의 신선도/중복 가드 적용 대상에서
  제외한다.
- `detect_theme_group_carry_forward`(SPEC-AI-025/027), `detect_theme_news_carry`
  (SPEC-AI-084/090/091) — 이름 유사 별개 탐지기, 무수정.
- `_keyword_in_text`(`keyword_matcher.py`) 자체 로직 — 재사용만, 수정 없음.

## §H 리스크

| 리스크 | 완화 |
|---|---|
| 중복 제거 비교가 예상보다 넓은 범위에서 호출되어 O(N²) 재발 | §C의 부분집합 한정 설계 + `dedup_max_comparison_batch`(기본 200) 하드 캡으로 dedup 비교 비용을 O(200²)로 구조적 유계화(경험적 관측이 아닌 코드 보장). 성능 테스트가 캡 경계(200건)와 캡 초과(500건) 양쪽에서 실행 시간이 베이스라인 대비 20% 이내임을 검증(acceptance.md §B) |
| `theme_base` 감쇠가 장기 활성 테마를 부당하게 억제 | REQ-AI103-003이 완전 배제가 아닌 감쇠만 요구, `min_theme_freshness_ratio` 기본값 0.0으로 초기 무영향 보장 |
| 가격 과열 서브기능이 SPEC-AI-038 제약을 재위반 | §E에서 배치 호출 + 유계 후보 집합(사전 절단 필수) 강제, `sector_only_max_candidates is None`이면 무조건 스킵 |
| 신규 설정 필드명이 향후 SPEC과 충돌 | `ThemeFreshnessGuardConfig`를 독립 클래스로 분리해 네임스페이스 격리(SPEC-AI-077의 "필드 충돌 없음" 관례 계승) |

## §I Cross-References

- `.moai/specs/SPEC-AI-103/research.md` — 코드 위치 재검증, 성능/제약 근거.
- `.moai/specs/SPEC-AI-098/spec.md` §Decisions D3/D4 — 설정화·관측성 우선
  패턴의 직접 전례.
- `backend/tests/test_spec_ai_098.py` — 인접 테스트 파일 명명/구조 관례.
- `.claude/rules/moai/development/manager-develop-prompt-template.md` — run-phase
  위임 시 Section B(Known Issues) B9/B10 준수(직접 커밋+PRESERVE 목록 엄수).
