# SPEC-AI-091 — Implementation Plan (구현 계획)

> Plan 단계 산출물. 구현은 `/moai run SPEC-AI-091`에서 수행한다. 시간 추정 없음(우선순위
> 라벨 P0/P1/P2만 사용). 아래 마일스톤은 변경 가능성(decision-reversibility)이 높은 결정
> 순으로 배치했다 — 순환 고리 차단 아키텍처 결정을 최우선으로, 기계적 테스트/관측성 정비를
> 최후순으로 둔다.

## Tier 판정: M (3 files)

- **분류**: Tier M — spec.md + plan.md + acceptance.md.
- **근거**: 3개 핵심 서비스 파일(`keyword_tagging_service.py`, `news_crawler.py`,
  `ai_classifier.py` 확인만/무변경 가능성)에 걸친 로직 변경 + 1개 신규 정화 스크립트 +
  다중 테스트 파일 확장 → 예상 5-8 files, ~350-650 LOC. 300-1000 LOC / 5-15 files 범위에
  해당(단일 파일 < 300 LOC Tier S 기준 초과).
- **plan-auditor PASS 임계**: 0.80 (Tier M).

## 단일 SPEC 결정 범위

- 하나의 근본원인(무경계 substring 매칭) + 하나의 순환 고리 차단 개입점(지속 태깅 트리거의
  relevance 게이트) + 하나의 정화 전략(리셋 후 재백필)에 집중한다. `ThemeNewsCarryConfig`
  재활성화, `theme_cluster` 변경, 크롤 예산 재설계, provenance 컬럼 신설은 명시적 후속
  범위 밖(§4 spec.md Out of Scope)이다.

---

## M1 (P0) — 순환 고리 차단 아키텍처 결정: 지속 태깅 트리거 단일 relevance 게이트

**결정 재현성: 높음** — 이 마일스톤은 REQ-AI091-004/005/006의 아키텍처 개입점을 확정한다.
잘못 선택하면 이후 모든 마일스톤이 재작업된다.

### 개입점

`news_crawler.py`의 `_touched_stock_ids` 구성 로직(관계 삽입 루프 내부, 현재 806-827행
근방)을 단일 개입점으로 삼는다 — 관계를 생성한 3개 경로(`_resolve_query_relations`,
`classify_news`, `_resolve_description_relations`) 중 어느 것이든, 삽입되는 각
`NewsStockRelation`의 `relevance` 필드가 이미 관계 dict(`rel.get("relevance", "indirect")`)에
존재하므로(§2 [E-8] spec.md), `_touched_stock_ids.add(rel["stock_id"])` 호출을
`if rel.get("relevance") == "direct":` 조건으로 감싸는 것만으로 3개 경로 전체에 동시
적용된다.

### 왜 3곳 개별 패치가 아니라 1곳인가 (Enforce Simplicity)

- `_resolve_query_relations`/`classify_news`/`_resolve_description_relations` 각각을
  수정하는 대안은 (a) 3배의 회귀 위험 표면, (b) 신규 관계 생성 경로가 미래에 추가될 때마다
  누락 위험을 안는다.
- `_touched_stock_ids` 게이트는 "관계가 어떻게 만들어졌는지"가 아니라 "관계가 얼마나
  신뢰할 만한지"(`relevance`)에 근거하므로, 신규 경로가 추가되어도 `relevance` 필드만
  올바르게 설정하면 자동으로 게이트가 적용된다 — 구조적으로 더 견고하다.

### 잠재적 트레이드오프 (Run 착수 시 재검토 대상)

- 이 게이트는 `NewsStockRelation` 자체의 생성은 막지 않는다 — indirect 관계는 여전히 DB에
  기록되고 하류 탐지기(예: `immediate_disclosure`, `volume_news_combo`)가 계속 소비한다.
  본 SPEC은 오직 "그 관계가 `stocks.keywords`를 오염시키는 것"만 차단한다(스코프 최소화,
  §4 spec.md Out of Scope와 정합).
- indirect 관계만 존재하는 신규 종목은 지속 태깅으로 키워드를 얻지 못해 `_build_search_queries`의
  우선순위 승격에서 계속 배제될 수 있다 — 이는 SPEC-AI-085가 해결하려 한 "무-관계 순환
  고리"와는 다른 축(키워드 승격 순환)이며, 본 SPEC은 **오염 차단**을 우선하고 이 트레이드오프를
  §Follow-up으로 남긴다.

---

## M2 (P0) — 매칭 알고리즘 재설계: 텍스트 스코핑 + 다중 출현 임계 + 한글 경계 가드

**결정 재현성: 중-높음** — REQ-AI091-002의 "최소 2개 텍스트" 임계값은 판단값이며 조정
가능하다.

### 함수 시그니처 변경

- `_gather_stock_theme_texts(db, stock_id)` → `NewsStockRelation.relevance == "direct"`
  필터 추가(REQ-AI091-001). 반환 타입은 `list[str]`로 유지하되, 개별 기사/공시 단위 텍스트를
  분리 유지(현재도 리스트이므로 blob으로 합치는 지점만 이동).
- `extract_theme_keywords(texts, theme_keywords=None)` → blob 결합(`" ".join(texts)`)을
  제거하고, 각 `text`를 개별 순회하며 키워드별 **등장 텍스트 개수**를 카운트하는 방식으로
  재작성(REQ-AI091-002). 최소 출현 텍스트 개수 임계값을 파라미터화(기본값 2, 하드코딩
  금지 — 테스트 용이성).
- 한글 선행문자 가드는 `ai_classifier.py::_count_keyword_matches`(398-418행)의 로직을
  참조하되, 순환 임포트 회피를 위해 `keyword_tagging_service.py` 내부에 동일 패턴의 경량
  헬퍼를 둔다(공유 유틸 모듈로의 추출은 Tier 확대 없이 가능하면 시도, 불가하면 국지적
  재구현 — 판단은 Run 착수 시 DP-1).

### 회귀 안전 (DDD ANALYZE-PRESERVE-IMPROVE)

- ANALYZE: 기존 `extract_theme_keywords`/`_gather_stock_theme_texts`/`refresh_stock_keywords`/
  `backfill_stock_keywords`의 현재 테스트(`tests/test_keyword_tagging_service.py`)를 읽고
  기존 계약(멱등성, 캡핑, 병합)을 파악한다.
- PRESERVE: 변경 전 거동을 캡처하는 특성화 테스트를 먼저 작성 — 특히 "단일 기사 언급만으로
  키워드가 매칭되는 현재(버그) 거동"을 RED로 재현.
- IMPROVE: REQ-AI091-001~003 반영 후 RED → GREEN 전환 확인.

---

## M3 (P0/P1) — 기존 데이터 정화 전략: 리셋 후 재백필

**결정 재현성: 중** — 리셋 범위(전체 vs 조건부)와 provenance 불명 처리(REQ-AI091-008)는
논쟁 여지가 있는 판단이다.

### 정화 스크립트 설계 (`scripts/remediate_keyword_tagging.py`, 신규)

1. **진단 단계(dry-run 기본값)**: 현재 `keywords`가 비어있지 않은 종목 수, 그중
   `created_at`이 SPEC-AI-084 최초 백필 실행일(2026-07-22 이전 §2 [E-12] spec.md 근거) 이전인
   종목 수(수동 설정 가능성이 상대적으로 높은 후보군)를 카운트해 로그로 보고한다
   (REQ-AI091-008).
2. **리셋 단계(`--execute` 플래그로만 실행)**: 진단 결과를 사람이 확인한 뒤에만
   `stocks.keywords = NULL`로 리셋한다 — 기본 대상은 비어있지 않은 `keywords`를 가진 전체
   종목(provenance 컬럼 부재로 완전한 구분 불가, REQ-AI091-008의 보수적 기본 처리를
   따름).
3. **재백필 단계**: M2에서 수정된 `backfill_stock_keywords()`를 호출한다(멱등 계약 유지,
   §2 [E-9] spec.md).
4. **실행 위치**: 이 스크립트의 실제 프로덕션 DB 실행은 **Run 단계(manager-develop)**의
   책임이며, 본 Plan 단계는 스크립트 설계·경로·플래그 계약만 확정한다(Plan 단계는 DB를
   건드리지 않는다는 사용자 지시 준수).

### DDD 특성화

- 정화 스크립트는 신규 코드이므로 TDD 우선(스크립트 자체는 `backfill_stock_keywords()`를
  호출만 하므로 소량 신규 로직에 한해 RED-GREEN 적용).

---

## M4 (P1) — 검증·관측성: 분포 상한 + 스팟체크 + 회귀 스위트

**결정 재현성: 낮음** — 이미 M1-M3에서 확정된 결정을 검증하는 기계적 단계.

- REQ-AI091-009 분포 상한 쿼리(예: `keywords` 배열 길이가 `max_keywords_per_stock`인 종목
  비율 ≤ 5%, 중앙값 ≤ 4) — 구체 수치는 acceptance.md에서 확정, M3 실행 후 실측으로
  재검증 가능하도록 스크립트화.
- REQ-AI091-010 스팟체크: `023790`/`105560`/`192080` 3종목의 정화 후 `keywords` 길이
  ≤ 3 확인 스크립트/테스트.
- REQ-AI091-011 회귀: `tests/test_services/test_news_crawler.py`(및 `theme_news_carry`/
  `theme_cluster` 관련 기존 테스트) 전체 스위트 무회귀 확인.
- 전체 테스트: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`
  (CLAUDE.local.md).
- 린트: `cd backend && uv run ruff check . && uv run mypy app/`.

---

## M5 (P2) — 문서·CHANGELOG 정합 (Sync 단계 위임)

**결정 재현성: 최저** — 순수 기계적 기록 단계, Run 단계 완료 후 manager-docs가 수행.

- `tech.md` SPEC Implementation History 표에 SPEC-AI-091 항목 추가(sync 단계).
- `CHANGELOG.md` `[Unreleased]`에 항목 추가(sync 단계, manager-docs 소유).

---

## Decision Points (Run 착수 시 확정)

- **DP-1 (한글 경계 가드 위치)**: `ai_classifier.py::_count_keyword_matches` 로직을 공유
  유틸로 추출할지, `keyword_tagging_service.py`에 국지적으로 재구현할지 — 순환 임포트
  제약 확인 후 결정.
- **DP-2 (다중 텍스트 출현 임계값)**: REQ-AI091-002의 최소 2개 임계값 — M3 재백필 실측
  결과로 조정 여지를 남긴다(acceptance.md에 초기값 명시, 조정 시 별도 SPEC 불필요 —
  파라미터 튜닝은 본 SPEC 범위 내).
- **DP-3 (정화 스크립트 실행 시점)**: M2(알고리즘 수정) 커밋 이후, M4(검증) 이전에 실행할지,
  아니면 M4 검증 스크립트를 먼저 준비해 M3 실행 직후 즉시 검증할지 — 순서는 Run 단계
  manager-develop 판단.
- **DP-4 (provenance 불명 종목의 리셋 제외 여부)**: REQ-AI091-008은 기본 포함(리셋)을
  규정하나, `created_at` 기반 휴리스틱으로 극소수를 제외할지는 진단 단계 카운트 결과에
  따라 Run 착수 시 재확인(카운트가 0에 가까우면 이 트레이드오프는 무의미).

## Risks (요약)

| 위험 | 완화 |
|------|------|
| M1 게이트가 indirect 관계 자체의 정당한 하류 소비(예: `volume_news_combo`)를 방해 | 게이트는 `stocks.keywords` 지속 태깅 트리거에만 적용, `NewsStockRelation` 생성 자체는 불변(REQ-AI091-005 문구가 "관계 생성 금지"가 아니라 "지속 태깅 호출 금지"임을 명확히) |
| M3 리셋이 극소수 수동 설정 키워드를 삭제 | REQ-AI091-008 진단 단계 + 운영자 확인 게이트 |
| M2 다중 텍스트 임계값이 너무 엄격해 정당한 키워드까지 배제 | DP-2로 조정 여지 남김, M4 분포 상한 관측으로 캘리브레이션 |
| Tier M 산정이 실제보다 과소평가 | Run 착수 시 실제 diff 크기가 1000 LOC/15 files를 초과하면 plan-auditor가 tier-up 제안(spec-workflow.md 정책) |

## Cross-References

- `.moai/specs/SPEC-AI-084/spec.md` — `stocks.keywords` 백필 인프라 원 설계.
- `.moai/specs/SPEC-AI-085/spec.md` — 설명 기반 관계 생성(`_resolve_description_relations`),
  본 SPEC의 REQ-AI091-006이 그 경로도 순환 고리에 포함됨을 확정.
- `backend/app/services/keyword_tagging_service.py`, `news_crawler.py`, `ai_classifier.py`.
- `CLAUDE.local.md` — 백엔드 검증 명령.
