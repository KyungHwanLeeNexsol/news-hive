---
id: SPEC-AI-098
title: "테마 클러스터 뉴스-종목 매칭 일원화, 종목명 별칭 확장, theme_news_carry 재활성화 관측성"
version: "0.1.0"
status: completed
created: 2026-08-03
updated: 2026-08-04
author: Nexsol
priority: Medium
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, theme-cluster, keyword-matching, name-alias, observability, backend"
tier: M
related_specs: [SPEC-AI-012, SPEC-AI-014, SPEC-AI-038, SPEC-AI-084, SPEC-AI-090, SPEC-AI-091]
---

# SPEC-AI-098: 테마 클러스터 뉴스-종목 매칭 일원화, 종목명 별칭 확장, theme_news_carry 재활성화 관측성

## HISTORY

- 2026-08-03 v0.1.0 (draft): 뉴스-종목 매칭이 단순 substring 매칭과 11개 대형주 전용
  별칭 표에 의존해 자회사/제품명 언급을 놓치거나 섹터 전체를 과대 포함하는 문제, 그리고
  오늘 재활성화된 `theme_news_carry` 플래그의 재활성화 후 관측 공백을 범위로 정의한다.
  research.md에서 위임 프롬프트의 두 가지 전제(SPEC-AI-091이 두 매칭 경로 모두에 동일
  경계 가드를 추가했다는 서술, `stocks.keywords`/`NewsStockRelation`이 별칭 파생에
  쓸 수 있는 독립 소스라는 서술)가 부정확함을 코드 대조로 확인해 §Decisions에 반영했다.

## 선행 SPEC

- **SPEC-AI-012/014**: `detect_theme_news_cluster()` 원 설계 및 종목 전용 기사
  블렌딩(60/40)·섹터 페널티(0.5×) 공식의 소유 SPEC. 본 SPEC은 그 공식 자체를 대체하지
  않고 구성 값을 설정 가능하게 만든다(§Decisions D3).
- **SPEC-AI-038**: 테마 클러스터의 시총 필터 및 NULL 시총 종목의 "뉴스 언급 시에만 포함"
  성능 패치. 본 SPEC의 섹터 전용 스코어링 개선과 인접하나 겹치지 않는다(포함 여부 vs
  포함 이후 점수).
- **SPEC-AI-084/090/091**: `theme_news_carry`(그룹 A) + `stocks.keywords` 태깅(그룹 C)
  파이프라인의 소유 SPEC. SPEC-AI-091이 무경계 substring 매칭 결함과 자기강화 순환
  고리를 수정하고 프로덕션 정화를 실행했다. 본 SPEC은 그 수정된 로직을 **재구현하지
  않고**, 재활성화(오늘 커밋 `63de7f6`) 이후의 관측성만 추가한다.

### amendment 여부

본 SPEC은 SPEC-AI-091의 amendment가 아니다. SPEC-AI-091의 본문(무경계 매칭 수정,
자기강화 순환 차단, 프로덕션 정화)은 그 시점의 결정 기록으로서 여전히 정확하며 수정
대상이 아니다. 여기서는 `amendment_of:` 없이 `related_specs`로만 참조하는 통상적
신규 SPEC이다.

## Context / Problem

### 문제 1 — 테마 클러스터의 종목별 기사 매칭이 무경계 substring이다

`backend/app/services/surge_detector.py:434-438`(`detect_theme_news_cluster()` 내부):

```python
_name_variants = _get_name_variants(stock.name)
stock_articles = [
    a for a in window_news
    if any(v in (a.title or "") + " " + (a.content or "") for v in _name_variants)
    or stock.stock_code in (a.title or "") + " " + (a.content or "")
]
```

`v in text`, `stock.stock_code in text` 모두 경계 검사가 없는 순수 substring 매칭이다.
이 프로젝트에는 이미 두 개의 경계 가드 구현이 존재하지만(research.md §1), 이 경로는
그중 어느 것도 재사용하지 않는다 — 세 번째 "가드 없음" 경로다.

### 문제 2 — `_STOCK_NAME_ALIASES`(surge_detector.py:32-44)가 11개 대형주 전용
하드코딩 딕셔너리다

자회사명, 제품명만 언급되는 기사, 축약 표기가 이 표에 없으면 `stock_articles`가 항상
0건으로 집계되어, 실제로 테마와 강하게 연관된 종목이 "섹터 전용" 취급을 받고 §문제 3의
0.5× flat penalty만 적용받는다.

### 문제 3 — 직접 언급 종목과 섹터 전용 종목의 점수 분기(surge_detector.py:444-449)가
섹터 크기를 반영하지 않는다

```python
if stock_specific_count >= 1:
    theme_cluster_score = (best_theme_base * 0.6) + (stock_article_score * 0.4)
else:
    theme_cluster_score = best_theme_base * 0.5
```

섹터 전용 분기는 섹터 소속 종목 수와 무관하게 동일한 0.5배를 적용한다. 섹터가 클수록
(예: 반도체 50+ 종목) 테마 활성화 시 그 섹터 전체가 균등하게 후보로 편입될 수 있다 —
개별 종목의 실제 연관성 증거 없이 과대 포함되는 구조적 원인이다.

### 문제 4 — `theme_news_carry`가 오늘 재활성화되었고 재활성화 이후 관측 데이터가 없다

`backend/app/surge_config/surge_settings.py:762`(`ThemeNewsCarryConfig.enabled: bool =
True`)는 commit `63de7f6`(2026-08-03 09:45:31 +0900)로 재활성화되었다. 2026-07-28
자기강화 오염 사건(당일 신호 69건 중 53건=77%가 오염된 keywords 기반) 이후 SPEC-AI-091
수정 + 프로덕션 정화 + AC-AI091-009/010 재측정으로 재활성화를 결정했으나, 그 재측정은
1회성 수동 확인이었다(`backend/scripts/remediate_keyword_tagging.py`, 스케줄러 미등록).
재발을 조기에 감지할 반복 가능한(recurring) 자동 체크가 없다(research.md §5).

## Goals

1. 테마 클러스터의 종목별 기사 매칭(`surge_detector.py:434-438`)이 이 코드베이스에
   이미 확립된 경계 가드 매칭 방식을 재사용하도록 교정한다 — 종목명 별칭 뿐 아니라
   종목코드 매칭에도 동일하게 적용한다.
2. 종목명 별칭 확장을 하드코딩 1회성 나열이 아닌, 근거를 동반한 반복 가능한 검토
   프로세스로 전환한다 — 자동 확정이 아닌 사람 검토 후보 제안 방식이다.
3. 섹터 전용 스코어링 상수(0.5× 페널티)를 설정 가능하게 만들어, 기본값에서는 완전히
   현행과 동일하게 동작하되(바이트 동등), 필요 시 섹터 규모 기반 완화를 튜닝할 수 있게
   한다.
4. `theme_news_carry` 재활성화 이후의 재발 감지 관측성을 추가한다 — AC-AI091-009가
   정의한 지표(10개 보유 비율, 중앙값)를 반복 측정하고, 일일 `surge_basis` 구성에서
   `theme_news_carry`가 차지하는 비율을 로깅한다.

## Non-Goals

### Out of Scope — 범위 제한

- **스캔 유니버스/후보 풀(Pool A/B/C/D) 변경**: 이번 배치의 형제 SPEC(SPEC-AI-096/097)
  대상이다. 본 SPEC은 건드리지 않는다.
- **`detect_theme_news_carry()`의 전파 로직 자체 수정**: SPEC-AI-091이 이미 커밋한
  수정(무경계 매칭 교정, 자기강화 순환 차단)을 재구현하지 않는다. 본 SPEC은 그 위에
  관측성만 **추가**한다 — 새로운 증거 없이 그 로직을 변경하지 않는다.
- **`keyword_tagging_service.py::extract_theme_keywords()`의 기존 경계 가드(선행문자
  전용, `ai_classifier.py::_count_keyword_matches` 재사용) 강도 변경**: 이미 프로덕션
  정화·재측정을 거친 검증된 상태다. 본 SPEC이 다른 목적(테마 클러스터 종목-기사 매칭)을
  위해 도입하는 가드는 이 경로와 완전히 분리된 신규 소비처이며, 기존 경로는 무수정으로
  둔다.
- **`stocks.keywords` 데이터 자체의 재백필/재정화**: SPEC-AI-091이 이미 실행했다. 본
  SPEC은 그 결과를 재검증하는 관측 체크만 추가한다.
- **전체 NLP/임베딩 기반 개체 연결(entity linking) 시스템 신규 구축**: research.md에서
  `stocks.keywords`/`NewsStockRelation`을 별칭 파생의 독립 소스로 쓸 수 없음을 확인했다.
  본 SPEC은 기존 substring/경계 가드 접근을 점진 개선하는 데 그친다.
- **`ThemeGroupCarryConfig`/`detect_theme_group_carry_forward()`(SPEC-AI-025, 계열/
  지분 그룹 전용 탐지기) 변경**: `theme_news_carry`(그룹 A)와 이름이 유사하나 별개
  탐지기이며 본 SPEC의 대상이 아니다.
- **`min_market_cap_krw` 시총 필터·NULL 시총 뉴스 언급 필터(SPEC-AI-038) 변경**: 포함
  여부를 결정하는 기존 필터는 무수정이다. 본 SPEC은 포함된 이후의 점수 산정만 다룬다.

## Decisions

### D1 — 경계 가드는 `keyword_matcher.py::_keyword_in_text`(완전 양방향 가드)를
재사용한다, `ai_classifier.py::_count_keyword_matches`(선행문자 전용)가 아니다

research.md 정정 사항 1이 확인했듯 이 코드베이스에는 강도가 다른 두 개의 경계 가드가
있다. 종목명(한글 조사 활용형 대응 필요)과 종목코드(숫자, 양방향 경계 필요) 양쪽을
매칭해야 하는 이 소비처에는 완전 양방향 가드가 더 적합하다 — 후행 경계 미검사(선행문자
전용 가드의 한계)는 숫자 종목코드 매칭에서 특히 위험하다(예: 6자리 코드가 더 긴 숫자
문자열의 일부로 우연히 일치). `keyword_matcher.py::_keyword_in_text`는 한글/영문/숫자
분기를 이미 모두 처리하므로 신규 로직 발명 없이 그대로 재사용 가능하다.

기각한 대안 — `ai_classifier.py::_count_keyword_matches` 재사용. `keyword_tagging_service.py`가
이미 이 함수를 쓰고 있어 일관성은 있으나, 후행 경계 미검사로 인해 숫자 종목코드
매칭에서 오탐 위험이 더 크고, SPEC-AI-091이 검증한 것은 "테마 어휘 vs 텍스트" 매칭이지
"종목코드 vs 텍스트" 매칭이 아니다.

`keyword_tagging_service.py`의 기존 가드는 무수정으로 둔다(§Out of Scope) — 이미
검증된 프로덕션 상태를 근거 없이 바꾸지 않는다.

### D2 — 별칭 확장은 규칙 기반 후보 제안 도구 + 사람 검토로 한다, DB 마이그레이션 없음

research.md 정정 사항 2가 확인했듯 `stocks.keywords`/`NewsStockRelation` 모두 별칭
파생의 독립 소스가 아니다. 기존 11개 별칭에서 관찰되는 유일하게 신뢰 가능한 패턴은
"한글 음역된 영문 법인 접미어"(에스=S, 케이=K, 엘지=LG, 디=D 등)다. 이 패턴에 대해서만
후보를 자동 생성하고, 그 외(자회사명·제품명)는 계속 사람이 큐레이션한다.

- 별칭 표 자체는 계속 Python 딕셔너리로 둔다(Simplicity Ladder 1단계 — DB 컬럼이
  필요한 근거가 없다).
- 후보 생성기는 `backend/scripts/remediate_keyword_tagging.py`의 기존 관례(기본
  dry-run, `--execute` 없이는 아무것도 변경하지 않음)를 따르되, 별칭 표 자체는
  자동으로 **절대 수정하지 않는다** — 후보 목록만 출력한다.

### D3 — 섹터 전용 페널티는 설정 필드로 추출하고 기본값은 현행 상수와 동일하게
유지한다(바이트 동등)

SPEC-AI-094/084/085/086/092가 일관되게 사용해 온 "기본값 비활성/현행 유지 → 관측 →
사용자 판단으로 튜닝" 패턴을 그대로 따른다. `0.5` flat 배수를
`ThemeClusterConfig.sector_only_penalty: float = 0.5`로 추출하고, 섹터 규모 기반 완화가
필요할 때를 대비해 `sector_only_max_candidates: int | None = None`(기본값 `None` =
현행처럼 상한 없음)을 추가한다. 두 필드 모두 기본값에서는 현재 코드와 완전히 동일하게
동작해야 한다 — 이것이 검증 가능한 계약이다.

기각한 대안 — 즉시 0.5를 더 낮은 값(예: 0.3)이나 섹터 크기 반비례 공식으로 교체.
근거가 될 실측 데이터(섹터 크기별 실제 과대포함 빈도)가 아직 없다. 근거 없는 새 매직
넘버로 교체하는 것은 기존 문제를 다른 형태로 재현할 뿐이다.

### D4 — 관측성은 로깅 우선이다, 신규 DB 테이블 없음. Telegram 경보 임계값은 Open
Question으로 남긴다

D3와 동일한 근거로 신규 영속 계층을 만들지 않는다. AC-AI091-009가 정의한 지표(10개
보유 종목 비율, 키워드 개수 중앙값)를 일 1회 재계산해 로그로 남기고,
`surge_backtest.py::_extract_combo_key()`를 재사용해 일일 `surge_basis` 구성에서
`theme_news_carry`가 차지하는 비율을 로깅한다. Telegram 경보(기존
`TELEGRAM_ADMIN_CHAT_ID` 채널, SPEC-AI-064 선례)는 Should-Pass로 다루되, 임계값은
2026-07-28 사건(77%)이라는 이상치 1개 데이터포인트만 있고 "정상" 기준선 관측이 없으므로
정밀한 숫자를 이 문서에서 확정하지 않는다(Open Question 2).

## Requirements

### REQ-AI098-001: 테마 클러스터 종목-기사 매칭 경계 가드 적용

**When** 테마 클러스터 탐지기가 종목별 연관 기사를 집계하면, the system **shall**
종목명 변형(공식명 + 별칭)과 종목코드 매칭 모두에 이 코드베이스에 이미 확립된
경계 가드 매칭 규칙(한글 조사 경계 인식, 영문/숫자 앞뒤 경계 인식)을 동일하게
적용해야 하며, 가드 없는 순수 부분 문자열 포함 검사를 사용해서는 **shall not**.

필수 조건:

- 적용 범위는 테마 클러스터 탐지기의 종목별 기사 귀속(attribution) 단계에
  한정한다. 정확한 코드 위치는 plan.md §A.1에 정의한다.
- 어떤 테마가 오늘 활성인지 판정하는 단계는 변경하지 않는다 — 이 REQ는 종목
  귀속 단계에만 적용된다.
- 별도로 관리 중인 기존 키워드 태깅 매칭 로직은 변경하지 않는다(REQ-AI098-006).

### REQ-AI098-002: 별칭 후보 제안 도구

**When** 별칭 후보 검토가 실행되면, the system **shall** 기존 11개 별칭에서 관찰되는
"한글 음역 영문 접미어" 패턴에 해당하는 미등록 종목명을 후보로 나열하고 근거(매칭된
음역 세그먼트)를 함께 제시해야 하며, 별칭 표를 자동으로 수정해서는 **shall not**.

필수 조건:

- 실행은 기존 `remediate_keyword_tagging.py`와 동일하게 수동 트리거(스케줄러 미등록)다.
- 출력은 사람이 읽고 판단할 수 있는 후보 목록이며, 파일 쓰기가 필요하다면 검토용
  초안 파일에 한정하고 `_STOCK_NAME_ALIASES` 딕셔너리 자체는 건드리지 않는다.

### REQ-AI098-003: 섹터 전용 스코어링 설정화 및 기본값 바이트 동등

**While** 섹터 전용 스코어링 설정(페널티 배수, 후보 수 상한)이 각각 기본값
(현행 페널티 배수, 상한 없음)이면, the system **shall** 본 SPEC 적용 이전과
완전히 동일한 섹터 전용 후보 점수를 반환해야 한다. **Where** 그 설정값이
기본값과 다르게 지정되면, the system **shall** 직접 언급이 없는 섹터 전용
종목에 그 설정값을 적용해야 한다.

필수 조건:

- 섹터 전용 후보 수 상한이 설정되면, 후보 점수 기준 상위 N개만 유지하고
  나머지는 후보에서 제외한다(직접 언급이 있는 종목은 이 상한의 영향을 받지
  않는다).
- 기존 시총 필터(SPEC-AI-038)와 이 상한은 서로 독립적으로 적용된다 — 순서는 시총
  필터가 먼저, 상한 절단이 그 이후다.
- 설정 필드의 정확한 이름/기본값/타입은 plan.md §A.1에 정의한다.

### REQ-AI098-004: `theme_news_carry` 키워드 분포 재발 감지 체크

**When** 관측 체크가 실행되면, the system **shall** AC-AI091-009와 동일한 정의로
"태깅된 종목 중 `keywords` 배열 길이가 `max_keywords_per_stock`(10)인 종목의 비율"과
"`keywords` 배열 길이의 중앙값"을 계산하고 로그로 남겨야 한다.

필수 조건:

- 신규 DB 테이블/컬럼을 추가하지 않는다(§Decisions D4) — 로그 라인으로만 노출한다.
- 계산 실패가 다른 스케줄 잡을 방해해서는 안 된다(기존 `@retry_with_backoff` +
  `try/except` 관례를 따른다).
- 실행 주기(일 1회 vs 스캔 사이클마다)는 아직 확정되지 않았다 — §Open Questions 1
  참고. 구현 착수 전 확정한다.

### REQ-AI098-005: `theme_news_carry` 시그널 기여 비율 로깅

**When** 관측 체크가 실행되면, the system **shall** 기존에 확립된 조합-키
추출 로직을 재사용해 직전 관측 주기 동안 생성된 급등 후보 시그널 중 그 근거에
`theme_news_carry`가 포함된 비율을 계산하고 로그로 남겨야 한다.

**Should** 그 비율이 설정된 임계값을 초과하면, the system SHOULD 기존 Telegram
경보 채널(관리자 채팅방)로 경보를 발송한다(임계값 자체는 Open Question 2 —
미확정).

실행 주기(일 1회 vs 스캔 사이클마다)는 아직 확정되지 않았다 — §Open Questions 1
참고. 재사용 대상 로직/채널의 정확한 함수명·설정 키는 plan.md §A.1에 정의한다.

### REQ-AI098-006: 기존 검증된 경로 무변경 보존

**While** 본 SPEC이 적용되는 동안, the system **shall not** 이미 프로덕션에서
검증된 키워드 태깅 매칭 로직, `theme_news_carry` 탐지기의 전파 로직(테마 활성
게이트, 앵커 자기제외, 바스켓당 최대 시그널 수 제한 등), 또는 기존 종목 키워드
데이터 자체를 변경해서는 안 된다. 이 REQ가 보호하는 정확한 함수/파일 목록은
plan.md §A.5 PRESERVE 목록에 정의한다.

## Open Questions

정책 판단(가드 선택 D1 / 별칭 자동수정 금지 D2 / 설정 기본값 바이트 동등 D3 / 관측성
로깅 우선·DB 없음 D4)은 §Decisions에서 이미 확정했다. 남은 항목은 구현 시 또는 관측
데이터 축적 후 확정할 사항이다.

1. 관측 체크(REQ-AI098-004/005)의 실행 주기 확정 — REQ 본문은 의도적으로 주기
   비종속(cadence-agnostic) 트리거("관측 체크가 실행되면")로 작성했다. plan.md
   TASK-005는 일 1회(24시간 주기) 스케줄러 잡 등록을 잠정 설계로 제안하나,
   스캔 사이클마다 실행하는 대안과 비교해 아직 최종 확정되지 않았다. 구현 착수
   (Implementation Kickoff) 전 이 결정을 확정한다.
2. Telegram 경보 임계값(REQ-AI098-005 Should절) — 2026-07-28 사건(77%)은 이상치 1개
   데이터포인트뿐이며 정상 기준선이 관측된 적이 없다. 재활성화 이후 며칠간 로깅값을
   관측한 뒤 별도로 확정한다. 본 SPEC은 로깅까지만 Must-Pass로 다루고 경보 발송은
   Should-Pass로 남긴다.
3. `sector_only_max_candidates` 활성화 여부와 구체적 값 — 본 SPEC은 설정 필드 배선까지만
   하고 기본값(`None`, 상한 없음)에서 활성화하지 않는다. 활성화는 REQ-AI098-004 관측
   데이터를 근거로 별도 판단한다.
