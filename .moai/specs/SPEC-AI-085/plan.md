# SPEC-AI-085 — Implementation Plan (구현 계획)

> Plan 단계 산출물. 구현은 `/moai run SPEC-AI-085`에서 수행한다. 시간 추정 없음(우선순위 라벨).

## Tier 판정: M (3 files)

- **분류**: Tier M — spec.md + plan.md + acceptance.md.
- **근거**: 변경 규모는 작으나(~2-4 files, < 300 LOC 예상) **공유 고fan-in 관계 계산 경로**
  (`crawl_all_news`)를 건드리며 오탐 통제·순환 고리 차단 검증에 전용 인수 기준이 필요하다.
  직접 상위 SPEC-AI-084도 Tier M(3 files)이며, 사용자가 spec+plan+acceptance 3종을 명시 요청.
- **plan-auditor PASS 임계**: 0.80 (Tier M).

## 단일 SPEC 결정

- 하나의 메커니즘(설명 기반 관계 생성) + 하나의 삽입 지점(`news_crawler.py` 관계 루프)에 집중한다.
  방향 b(라운드로빈)·본문 매칭은 명시적 후속(§Follow-up)으로 분리 → Enforce Simplicity 준수,
  "가장 단순한 순환 고리 차단 변경"이라는 사용자 지시 정합.

## 기술 접근 (Technical Approach)

### 핵심 삽입 지점

`crawl_all_news`의 관계 계산 루프(`news_crawler.py:531-543`)의 `classify_news(ad["title"], index)`
(`:542`) **직후**, 설정 플래그가 ON일 때 기사 설명(`ad.get("description")`)에 대한 종목명 매칭
결과를 `ad["_relations"]`에 병합한다. 이 지점은:

- 무-관계 폐기 필터(`:554-558`) **이전**이라 설명 매칭이 무-관계 기사를 구제할 수 있다([E-4]).
- 설명(`ad.get("description")`)이 이미 메모리에 있어 추가 비용 0([E-3]/[E-4]).
- 신규 관계가 기존 삽입 루프(`:690-761`) → `_touched_stock_ids`(`:747`) →
  `refresh_stock_keywords` 훅(`:812`)을 그대로 타 키워드 승격까지 자동 연결([E-6]).

### 재사용 자산 (신규 인프라 최소화)

- **매칭**: `classify_news`(`ai_classifier.py:332`)의 종목명 최장일치 + 한글 선행문자 배제 가드를
  재사용. 후보 방식(OQ-1): (i) `classify_news(ad.get("description",""), index)` 재호출 후 제목
  관계와 dedup, 또는 (ii) 제목 매칭과 동형의 경량 설명 전용 헬퍼. plan 권고 = (i)(코드 재사용
  최대, 신규 표면 최소) — 단 설명 매칭 결과에 기사당 상한(REQ-003)과 dedup을 적용.
- **점수**: 기존 `calculate_relevance_score`(`ai_classifier.py:268`) + 최소 점수 필터
  (`news_crawler.py:619`/`:741`)를 그대로 사용. 설명에 종목명 포함 시 +20이 이미 존재하므로
  설명-only 매칭의 점수 통과 여부를 Run에서 검증(OQ-2). 통과 미달 시 relevance/match_type 라벨
  또는 점수 취급을 Run 결정점 DP-2에서 확정.
- **인덱스**: `get_or_build_index(db)`로 얻는 기존 `KeywordIndex`(`:314`) 재사용 — 재빌드 없음.

### 설정 게이팅 (REQ-006)

- SPEC-AI-084 그룹 B의 `NewsUrgencyRecalibrationConfig`(surge_settings.py) 선례를 따라 신규 경량
  설정(예: `ContentRelationMatchingConfig` 또는 `app.config.settings` 플래그, DP-3)로 게이팅.
  기본값 보수(예: `enabled=False` 또는 staged). 롤백 = 플래그 복귀 = 완전 레거시.

### 오탐 통제 (REQ-003)

- 이름 경계 가드는 `classify_news` 재사용으로 자동 계승(최장일치 + 한글 선행문자 배제).
- 기사당 설명 기반 관계 수 상한(예: N개, DP-1) — 시황/묶음 기사 남발 차단. 값은 07-22 로봇 랠리
  묶음 기사 replay로 캘리브레이션.

## Milestones (우선순위 기반, 시간 추정 없음)

- **M1 (P0) — 재현 우선 특성화 (DDD ANALYZE-PRESERVE)**: 현재 관계 계산 거동을 캡처하는 특성화
  테스트 선행 — (a) 제목에 종목명 있는 기사 → 관계 생성(기존 거동), (b) 설명에만 종목명 있고
  제목엔 없는 기사 → **현재 관계 미생성**(결손 RED 재현), (c) `_query=None` RSS 기사 제목 매칭
  회귀 보호. 테스트홈: `tests/test_news_crawler_*.py`(기존 크롤러 테스트 확장) 또는 신규
  `tests/test_spec_ai_085_content_relations.py`.
- **M2 (P0) — 설명 기반 관계 생성 (IMPROVE)**: `:542` 직후 게이팅된 설명 매칭 병합 구현
  (REQ-001/002). 이름 가드 + 기사당 상한(REQ-003) + 기존 점수 필터 라우팅(REQ-004). 기존 제목/
  쿼리 관계 불변(REQ-005) 검증. M1의 (b) RED → GREEN.
- **M3 (P1) — 설정 게이팅 + 무오염 (IMPROVE)**: 설정 플래그(REQ-006) + following/수동 키워드
  무변경(REQ-007) 정적 확인. 플래그 OFF = 완전 레거시 회귀 테스트.
- **M4 (P1) — 회귀 안전 + 관측성 (IMPROVE)**: 전체 스위트 무회귀(REQ-008) + 크롤당 설명 관계 수
  유계 로그(REQ-009). 린트 clean.

## Decision Points (Run 착수 시 확정)

- **DP-1 (기사당 관계 상한)**: N 값 — 07-22 로봇 랠리 묶음 기사 replay로 오탐/커버리지 균형점.
- **DP-2 (설명-only 점수 취급)**: 설명 매칭 관계의 relevance(`direct`/`indirect`)·match_type
  라벨 및 점수 통과 보정 — OQ-2 검증 결과에 따라.
- **DP-3 (설정 플래그 위치·기본값)**: `NewsUrgencyRecalibrationConfig` 형태(surge_settings.py) vs
  `app.config.settings` 플래그. 기본값 보수.
- **DP-4 (dedup 방식)**: 설명 매칭이 제목 매칭과 같은 종목을 중복 산출할 때의 병합(제목 관계 우선
  보존 + 설명-only 신규분만 추가).

## 변경 예상 파일

- `backend/app/services/news_crawler.py` — 관계 루프(`:542` 직후) 설명 매칭 병합 + 게이팅 + 관측 로그.
- `backend/app/services/ai_classifier.py` — (OQ-1 (ii) 채택 시에만) 경량 설명 매칭 헬퍼. (i) 채택 시
  변경 없음(`classify_news` 재호출).
- `backend/app/surge_config/surge_settings.py` **또는** `backend/app/config.py` — 설정 플래그(DP-3).
- `backend/tests/test_spec_ai_085_content_relations.py`(신규) 또는 기존 크롤러 테스트 확장 — 특성화 +
  회귀 테스트.

## 검증 명령

- 백엔드 테스트: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`
- 린트: `cd backend && uv run ruff check .`
- 임포트 sanity: `cd backend && uv run python -c "from app.main import app; print('OK')"`

## Risks (요약 — 상세 spec.md §5)

- R-1 오탐 precision(핵심) → 이름 가드 + 기사당 상한 + 점수 필터 + 게이팅.
- R-2 설명 풍부도 한계 → 구조적 차단 목표 + 특정 6종은 관측 지표(본문 매칭은 §8(a) 후속).
- R-3 공유 코드 회귀 → 재현 우선 특성화 + 플래그 OFF 완전 레거시.
- R-4 삽입 볼륨 증가 → 기사당 상한 + 최소 점수 필터 + 관측 로그.

## OWNERSHIP

- 084 = 키워드 태깅/전파 인프라 소유(불변; 085는 관계 유입으로 그 훅을 자동 트리거).
- 079 = 게이팅/단계적 롤아웃 관례(계승).
- 043 = 예측 기록 모드(계승, 매매 무변경).
- 085 = 설명 기반 관계 생성 메커니즘 소유(제목/쿼리 관계 경로는 불변, additive only).
