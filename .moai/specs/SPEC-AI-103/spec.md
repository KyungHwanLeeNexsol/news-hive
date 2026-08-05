---
id: SPEC-AI-103
title: "테마 클러스터 뉴스 신선도/중복(dedup) 가드"
version: "0.1.0"
status: completed
created: 2026-08-05
updated: 2026-08-05
author: Nexsol
priority: Medium
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, theme-cluster, freshness-guard, deduplication, backend"
tier: M
related_specs: [SPEC-AI-012, SPEC-AI-014, SPEC-AI-030, SPEC-AI-038, SPEC-AI-098]
---

# SPEC-AI-103: 테마 클러스터 뉴스 신선도/중복(dedup) 가드

## HISTORY

- 2026-08-05 v0.1.0 (draft): `detect_theme_news_cluster()`(`theme_cluster` 탐지기)가
  최근 1,000건 뉴스를 48시간 창에서 raw article count로만 세고, 기사 발행 시각의
  신선도나 재보도(syndication) 여부를 전혀 검사하지 않는 문제를 범위로 정의한다.
  형제 탐지기 `volume_news_combo`의 `combo_chase_guard`(과열/신선도/분산 3게이트,
  SPEC-AI-030)를 모델로 삼되, SPEC-AI-038이 이 함수에서 의도적으로 제거한 가격 API
  호출 제약을 재위반하지 않는 시간축 기반 설계로 조정했다(research.md §2).

## 선행 SPEC

- **SPEC-AI-012/014**: `detect_theme_news_cluster()` 원 설계 및 종목 전용 기사
  블렌딩(60/40)·섹터 페널티 공식의 소유 SPEC. 본 SPEC은 그 공식을 대체하지 않고,
  그 공식에 들어가는 입력(기사 카운트)의 신뢰도만 개선한다.
- **SPEC-AI-030**: `volume_news_combo`의 `combo_chase_guard`(과열/신선도/분산 게이트)
  원 설계 — 본 SPEC이 모델로 삼는 패턴의 소유 SPEC. `combo_chase_guard` 자체는
  무수정으로 둔다.
- **SPEC-AI-038**: `detect_theme_news_cluster()`에서 가격 API 호출을 성능상 이유로
  완전히 제거한 패치(921종목 × 0.6s/call = 550초 → timeout). 본 SPEC의 신선도 설계는
  이 제약을 재위반하지 않도록 시간축(기사 발행 시각) 기반으로 한정한다
  (research.md §2, §Decisions D1).
- **SPEC-AI-098**: 본 함수의 가장 최근 완료 변경 — 종목-기사 매칭 경계 가드 적용,
  `sector_only_penalty`/`sector_only_max_candidates` 설정화. 본 SPEC은 그 위에
  가산적으로 얹으며, 그 두 설정값이나 절단 순서 자체는 변경하지 않는다.

## Context / Problem

`detect_theme_news_cluster()`(`backend/app/services/surge_detector.py:286-527`,
앙상블 가중치 0.19)는 `cluster_window_hours`(기본 48시간) 이내 뉴스 최대 1,000건을
DB에서 직접 조회해(`:312-318`) 테마 키워드별 raw article count(`keyword_counts`)로
활성 테마를 판정하고(`:332-340`, `min_article_count` 기본 2), 그 테마가 매핑된
섹터의 모든 종목에 점수를 부여한다(`:400-527`, 직접 언급 없는 섹터 전용 종목 포함).

이 경로에는 기사 신선도·반복(재보도) 여부를 검사하는 로직이 전혀 없다. 형제
탐지기 `volume_news_combo`는 동일한 종류의 문제(신호 생성 시점에 이미 오래되었거나
가짜로 부풀려진 신호)를 `combo_chase_guard`(`surge_detector.py:984-1030`,
SPEC-AI-030)의 3게이트(과열/신선도/분산)로 방어하지만, `theme_cluster`에는 그에
상응하는 방어가 없다. 결과적으로 두 가지 실패 모드가 가능하다:

1. **재보도 인플레이션**: 이미 시장에 반영된(price-in) 기사가 여러 매체에 재게시되며
   `keyword_counts`를 부풀려, 실제로는 새롭지 않은 촉매가 계속 활성 테마로 재판정될
   수 있다.
2. **진부화된 테마의 지속 트리거**: `cluster_window_hours`(48h) 창 안에만 있으면
   기사 발행 시각이 창의 초반(예: 40시간 전)에 몰려 있어도 동일하게 취급되어, 이미
   가격에 반영되고 관심이 식은 테마가 창이 만료될 때까지 계속 후보를 발생시킬 수
   있다.

## Goals

1. 테마 활성 판정(`keyword_counts`)과 종목별 기사 귀속(`stock_articles`) 양쪽에서,
   동일한 근본 사건을 다루는 근접 중복(near-duplicate) 기사가 여러 건으로 중복
   집계되지 않도록 한다.
2. 테마의 기사 활동이 신선도 가드가 정의하는 최근 구간에 집중되지 않은 경우
   (진부화된 촉매) 그 테마의 점수를 낮출 수 있는 메커니즘을 추가한다.
3. 위 두 메커니즘 모두 **기본값에서는 현재와 완전히 동일하게 동작**해야 한다
   (이 코드베이스의 확립된 단계적 롤아웃 관례 — 활성화는 별도 관측·판단으로 결정).
4. SPEC-AI-038이 제거한 가격 API 호출 패턴을 재도입하지 않는다 — 메인 종목 순회
   루프 내부에서의 종목별 동기 가격 호출은 어떤 경우에도 추가하지 않는다.

## Decisions

### D1 — 신선도는 시간축(기사 발행 시각) 기반으로 설계한다, 가격 기반이 아니다

`combo_chase_guard`의 Gate 2(`volumes[-1]/volumes[-2]` 거래량 신선도 비율,
`min_freshness_ratio`)를 모델 삼되, 대상 축을 거래량에서 "테마의 근거 기사가 신선
구간 내에 있는 비율"로 치환한다. 이는 `window_news`에 이미 존재하는
`published_at`만 사용하므로 신규 I/O가 없다. Gate 1(가격 과열 필터)의 직접 이식은
SPEC-AI-038 제약(§선행 SPEC)과 정면으로 충돌하므로 **기각**한다 — 메인 종목 순회
루프에서 섹터 소속 전 종목에 대해 가격을 조회하면 921종목×0.6s 규모의 회귀가
재현된다.

기각한 대안 — Gate 1을 그대로 이식(종목별 `change_rate` 조회 후 과열 시 제외).
근거: research.md §2가 확인한 SPEC-AI-038의 명시적 제거 사유(타임아웃)가 여전히
유효하며, theme_cluster는 볼륨콤보와 달리 사전 필터링되지 않은 섹터 전체 종목을
순회한다.

### D2 — 가격 과열 방어는 SHOULD-PASS 옵션으로, 이미 절단된 소수 후보에만 적용한다

Gate 1이 방어하려는 "이미 가격이 크게 움직인 후보"라는 관심사 자체는 유효하므로
완전히 버리지 않는다. 대신, SPEC-AI-098이 이미 도입한 `sector_only_max_candidates`
절단(`:515-532`) **이후**의 소수 후보 집합에 한해, 이 코드베이스의 다른 지점
(Pool B, build_scan_universe)에서 이미 검증된 배치 헬퍼
(`fetch_stock_price_history_batch_sync`)를 1회 배치 호출로 재사용하는 것을
SHOULD-PASS(선택) 요구사항으로 둔다. `sector_only_max_candidates`가 설정되지
않은(기본 `None`, 무제한) 상태에서는 이 서브기능이 활성화되지 않는다 — 유계
후보 집합이 없으면 SPEC-AI-038 제약이 재발할 수 있기 때문이다.

### D3 — 중복(재보도) 탐지는 표준 라이브러리 `difflib` 기반 제목 유사도로 한다

research.md §3의 Simplicity Ladder 조사 결과, 이 코드베이스에는 유사도 기반 중복
탐지 라이브러리가 전혀 없다(rapidfuzz/thefuzz/Levenshtein 0건). 신규 서드파티
의존성을 추가하지 않고 Python 표준 라이브러리 `difflib.SequenceMatcher`로 제목
유사도 + 발행 시각 근접도를 조합해 "동일 근본 사건의 근접 중복"을 판정한다. 판정된
중복 기사 중 가장 이른 발행 기사만 카운트에 반영한다(뒤의 중복은 집계에서 제외,
DB 삭제 아님).

기각한 대안 — 매체(`source`) 다양성을 중복 판정 기준으로 사용. 근거: 동일 매체의
재게시와 서로 다른 매체의 독립 취재를 `source` 필드만으로 구분할 수 없고, 통신사발
재보도는 오히려 여러 매체에서 동시에 나타나는 것이 전형적 특징이라 매체 다양성
요건이 목적에 역행할 수 있다.

### D4 — 중복 비교는 이미 좁혀진 부분집합 내부로 한정하고, 그 부분집합에도
명시적 상한(하드 캡)을 둔다(O(N²) 회피)

`window_news` 전체(최대 1,000건)에 대한 전수 쌍대 비교는 하지 않는다. 테마 활성
판정용 중복 제거는 키워드별로 이미 분리된 매칭 기사 부분집합 내부에서만, 종목별
기사 귀속용 중복 제거는 이미 종목별로 좁혀진 `stock_articles` 리스트 내부에서만
수행한다(research.md §4). 이는 SPEC-AI-082가 이미 문제 삼은 스캔 지연 예산을 다시
압박하지 않기 위한 구조적 제약이다.

부분집합 크기 자체가 예상보다 커지는 경우(예: 범용 고빈도 키워드가 비정상적으로
넓은 기사 부분집합에 매칭)에 대비해, 관측적 안정성이 아닌 **구조적 상한**을
추가한다: 부분집합 크기가 설정된 캡(`dedup_max_comparison_batch`, 기본 200)을
초과하면, 캡을 초과하는 나머지(발행 시각 기준 더 오래된 기사부터)는 중복 비교
대상에서 제외하고 원본과 동일하게 개별 건으로 그대로 집계한다 — 즉 캡 초과분은
가드 도입 이전의 raw-count 방향으로 안전하게 열화(degrade)할 뿐, 캡 유무와
무관하게 dedup 비교 연산량은 항상 O(캡²)로 유계된다.

### D5 — 신규 설정은 기본 비활성(단계적 롤아웃), 기본값에서 바이트 동등

이 코드베이스의 최근 SPEC 전반(SPEC-AI-066 event_rescan/SPEC-AI-079
relative_threshold/SPEC-AI-091 등)이 반복 채택한 패턴을 그대로 따른다 — 신규
게이트는 마스터 스위치로 묶어 기본 비활성으로 배포하고, 활성화는 관측 데이터
축적 이후 별도 판단(후속 SPEC 또는 설정 변경)으로 결정한다. 기본값에서는 본 SPEC
적용 이전과 완전히 동일한 `theme_cluster_score`를 산출해야 한다 — 이것이 검증
가능한 계약이다.

**활성화 판단 기준(참고용, 확정 임계값 아님 — Open Question 1과 연동)**: 활성화
여부 결정 자체는 이 SPEC의 범위 밖으로 남기지만, 그 판단이 근거로 삼을 관측
신호는 명시한다. REQ-AI103-007이 남기는 로그를 최소 5거래일 이상 축적한 뒤,
(a) 활성 테마 중 중복 제거로 인해 카운트가 실제로 변경된 비율이 관측 가능한
수준(예: 10% 이상)으로 나타나는지, (b) 신선 비율이 낮게 계산된(진부화) 활성
테마 발생 빈도가 사후 오탐 사례(실제로는 이미 가격 반영된 테마였던 사례)와
상관관계를 보이는지를 근거로 판단한다. 이는 SPEC-AI-066
`event_rescan_enabled`/SPEC-AI-079 `relative_threshold_enabled`/SPEC-AI-091이
따른 것과 동일한 '기본 비활성 → 관측 → 후속 판단' 절차이며, 정확한 수치
임계값 확정은 이 SPEC의 범위 밖이다(§Non-Goals 아님, 단지 후속 판단 항목).

## Requirements

### REQ-AI103-001: 근접 중복 기사의 단일 집계 (Event-driven)

**When** 신선도/중복 가드가 활성화된 상태에서 테마 클러스터 탐지기가 테마 활성
판정 또는 종목별 기사 귀속을 위해 기사를 집계하면, the system **shall** 동일한
근본 사건을 다루는 것으로 판정된 근접 중복 기사들을 단일 건으로 집계해야 하며,
가장 이른 발행 기사를 대표 건으로 사용해야 한다.

필수 조건:

- 중복 판정 범위는 이미 코드가 형성한 부분집합(키워드별 매칭 기사, 또는 종목별
  귀속 기사) 내부로 한정한다 — 전체 뉴스 창에 대한 전수 비교는 수행하지 않는다.
- 중복 판정에는 제목 유사도와 발행 시각 근접도 두 조건이 모두 사용되어야 한다.
- 원본 `NewsArticle` 레코드나 DB 상태는 변경하지 않는다 — 집계 시점의 카운팅
  필터일 뿐이다.
- 부분집합 크기가 설정된 비교 상한(`dedup_max_comparison_batch`)을 초과하면,
  상한을 초과하는 기사는 중복 비교 없이 개별 집계로 안전하게 열화해야 한다
  (§Decisions D4) — 이 상한은 dedup 비교 비용을 구조적으로 O(상한²)까지만
  허용하는 하드 캡이다.

### REQ-AI103-002: 기본값 바이트 동등 (State-driven)

**While** 신선도/중복 가드 설정이 기본값이면, the system **shall** 본 SPEC 적용
이전과 완전히 동일한 테마 활성 판정 결과와 `theme_cluster_score`를 산출해야 한다.

필수 조건:

- 마스터 활성화 스위치의 기본값은 비활성이다.
- 활성화 스위치가 비활성일 때, 본 SPEC이 추가하는 어떤 계산 경로도 최종 점수나
  후보 목록에 영향을 주어서는 안 된다.

### REQ-AI103-003: 진부화된 테마의 점수 감쇠 (Event-driven, 조건부)

**Where** 신선도/중복 가드가 활성화되어 있고, **When** 한 테마의 (중복 제거된)
기사 활동이 그 가드가 정의하는 최근 신선 구간 밖에 집중되어 있으면, the system
**shall** 해당 테마 후보의 테마 기본 점수(theme_base)에 감쇠를 적용해야 한다.

필수 조건:

- 감쇠 여부·강도를 결정하는 임계값(신선 비율 임계)은 설정 가능해야 하며, 기본값은
  REQ-AI103-002의 바이트 동등 계약을 위반하지 않는 값이어야 한다.
- 감쇠는 완전 배제가 아니라 점수 조정이어야 한다 — 여전히 활성인 장기 테마를
  false negative로 만들지 않기 위함이다.
- 중복 제거 후 기사 수가 0이 되는 방어적 경계(0으로 나누기 등)를 안전하게
  처리해야 한다.

### REQ-AI103-004: 유계된 가격 과열 방어 (Where, SHOULD-PASS)

**Where** 신선도/중복 가드의 가격 과열 서브기능이 활성화되어 있고 섹터 전용
후보 수 상한(`sector_only_max_candidates`)이 설정되어 있으면, **When** 테마
클러스터 탐지기가 섹터 전용 후보 목록을 확정하면, the system **shall** 그
절단 이후의(이미 상한이 걸린) 소수 후보 집합에 한해, 테마 활동 시작 시점 이후
가격이 이미 설정된 과열 임계 이상 움직인 후보를 감쇠하거나 제외해야 하며, 이때
단일 배치 가격 조회만 사용해야 한다.

> SHOULD-PASS 우선순위는 REQ 제목의 외부 라벨로만 표기하며, 문장 본문은
> 정규 GEARS 어휘 "shall"을 사용한다(plan-audit D2 조치).

필수 조건:

- 섹터 전용 후보 수 상한이 설정되지 않은 경우 이 서브기능은 활성화되지 않는다.
- 가격 조회는 이미 이 코드베이스의 다른 지점에서 검증된 배치 헬퍼를 재사용해야
  하며, 종목별 개별 동기 호출을 새로 추가해서는 안 된다.

### REQ-AI103-005: 종목 순회 루프 내 동기 가격 호출 금지 (Unwanted)

**While** 테마 클러스터 탐지기가 섹터 소속 종목을 순회하며 점수를 계산하는 동안,
the system **shall not** 그 순회의 종목 1건마다 개별 동기 가격 API 호출을
수행해서는 안 된다.

### REQ-AI103-006: 특성화 테스트 선행 (Event-driven, 프로세스)

**When** 본 SPEC의 구현이 시작되면, the system **shall** 신선도/중복 가드 도입
이전의 `detect_theme_news_cluster()` 출력을 대표 픽스처들에 대해 캡처하는
특성화(characterization) 테스트를 먼저 작성한 뒤에 탐지기 동작을 수정해야 한다.

### REQ-AI103-007: 관측성 로깅 (State-driven)

**While** 신선도/중복 가드가 활성화되어 있으면, the system **shall** 활성
테마별로 중복 제거로 축소된 기사 수와 계산된 신선 비율을 디버그 레벨 로그로
남겨야 한다.

## Non-Goals

이 절은 본 SPEC의 범위 밖(out of scope)인 항목을 정의한다.

### Out of Scope — 다른 탐지기 및 앙상블

- `compute_ensemble_score()`, 앙상블 가중치(`theme_cluster: 0.19` 등), 다른 7개
  탐지기(`volume_news_combo`, `disclosure_pattern`, `theme_news_carry`,
  `group_cascade` 등)의 로직·설정값 변경.
- `combo_chase_guard`(`ComboChaseGuardConfig`) 자체의 임계값이나 게이트 로직
  변경 — 본 SPEC은 그 패턴을 참고만 하며 원본은 무수정으로 둔다.
- `detect_theme_group_carry_forward`(SPEC-AI-025/027, 계열/지분 그룹 전파)와
  `detect_theme_news_carry`(SPEC-AI-084/090/091, 키워드 바스켓 전파) — 이름이
  유사하나 별개 탐지기이며 본 SPEC의 대상이 아니다.
- `_comention_supplement`/`_derive_comention_theme_candidates`(SPEC-AI-066
  REQ-004, 임시 테마 co-mention 보강 경로) — `detect_theme_news_cluster()` 내부의
  별도 조기 종료 분기이며, 본 SPEC의 신선도/중복 가드는 이 보강 경로에는
  적용하지 않는다.

### Out of Scope — 스캔 유니버스 및 평가

- 스캔 유니버스/후보 풀(Pool A/B/C/D) 구성이나 `build_scan_universe()` 변경
  (SPEC-AI-102 대상).
- 지평(horizon) 인식 임계값이나 결과 라벨링(`evaluate_surge_predictions()`,
  `surge_actual_outcome_service.py`) 변경 (SPEC-AI-101 대상).

### Out of Scope — 뉴스-종목 연결 로직

- 뉴스-종목 매칭/별칭(alias) 로직 자체의 확장 — SPEC-AI-098이 이미 경계 가드
  적용과 별칭 확대 프로세스를 다뤘다. 본 SPEC은 중복 판정에 필요한 최소 범위
  (기사 간 유사도 비교)만 다루며, `NewsStockRelation`이나 `_STOCK_NAME_ALIASES`
  구조 자체는 건드리지 않는다.

### Out of Scope — 데이터 백필 및 마이그레이션

- 과거 저장된 `FundSignal`/`surge_metadata` 재계산 또는 백필. 본 SPEC은 전진
  적용만 한다.
- 신규 DB 테이블/컬럼 마이그레이션 — 신선도/중복 판정은 요청 시점 메모리 연산만
  사용하며 영속 상태를 추가하지 않는다.

## Open Questions

정책 판단(신선도=시간축 D1 / 가격 과열=SHOULD-PASS+유계 D2 / 중복탐지=difflib D3 /
비교 범위=부분집합 한정+하드 캡 D4 / 기본 비활성 D5)은 §Decisions에서 이미
확정했다. 남은 항목은 구현 시 또는 관측 데이터 축적 후 확정할 사항이다.

1. `duplicate_title_similarity_threshold`, `duplicate_dedup_window_hours`,
   `min_theme_freshness_ratio`의 구체적 기본 임계값(감쇠는 적용하되 REQ-AI103-002
   바이트 동등을 만족하는 값) — plan.md에서 후보값을 제시하고 구현 착수 전 확정한다.
2. REQ-AI103-004(가격 과열 서브기능)를 본 SPEC의 M4 마일스톤으로 포함할지, 아니면
   범위를 줄여 후속 SPEC으로 분리할지 — plan-auditor 검토 및 구현 착수 승인
   시점에 판단한다.
