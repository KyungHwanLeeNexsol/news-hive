# SPEC-AI-084 — Implementation Plan (구현 계획)

> Plan 단계 산출물. 구현 미포함. 구체 함수·설정키·임계값은 Run(annotation 확정) 단계에서 최종화한다.

## 단일 SPEC 결정 (One SPEC vs Split)

**결정: 하나의 SPEC-AI-084 + 세 REQ 그룹**(그룹 C → B → A, 의존 순서)으로 작성한다.

판단 근거:

1. **상호 의존성.** 그룹 A(뉴스 테마 전파 탐지기)는 그룹 C(키워드 채움)의 데이터에 **하드 의존**한다
   (`stocks.keywords`가 없으면 바스켓 형성 불가). 분할 시 A는 C 완료 전까지 테스트 불가 →
   교차-SPEC 의존 체인 관리 오버헤드가 발생.
2. **사용자 요청.** 사용자가 AskUserQuestion으로 세 방향을 **모두 함께** 추진하기로 선택했고, 세 역량은
   하나의 실세계 사건(07-22 로봇 랠리 미탐)에 대한 응집된 대응이다. "왜"(근본원인)와 공통 제외
   ([X-1] first-mover 비목표)를 한 곳에 유지하는 편이 정합적.
3. **선례.** SPEC-AI-083(방향 A/방향 B 두 그룹)·SPEC-AI-080(REQ 7종)이 응집 관심사를 다중 REQ 그룹으로
   묶는 프로젝트 관례를 이미 확립.
4. **분할 옵션 검토·기각.** 그룹 B(긴급도)는 기술적으로 독립이라 단독 SPEC 가능하나, (a) 사용자가 함께
   요청했고 (b) 그룹 A의 테마 활성 확인(REQ-011)에 그룹 B의 고긴급 뉴스가 입력으로 기여하므로 같은
   SPEC에 두는 편이 추적성이 높다. **단, 프로젝트가 향후 분할을 원하면 그룹 B는 독립 후속 SPEC으로
   깔끔히 분리 가능**(공유 코드는 `_classify_urgency` 하나뿐).

의존 순서: **C(키워드 인프라, 선행조건) → B(긴급도 재보정, 독립) → A(전파 탐지기, C·B 소비).**
단 그룹 A는 REQ-AI084-012(바스켓 부재 시 no-op)로 C 미완 상태에서도 안전 배포 가능하므로, 배포
독립성은 확보된다.

## Tier 판단

**Tier M~L 경계** (신규 탐지기 + 신규 태깅 인프라 + 분류기 재보정, ~6-8 파일, 추정 500~1000+ LOC).
프로젝트 관례에 따라 3-file 세트(spec/plan/acceptance)로 작성한다. Run 단계에서 Milestone(M1~M5)로
분해한다.

## Milestones (우선순위 기반, 시간 추정 없음)

### M1 — 그룹 C 배치 백필 (선행조건, Priority High)

- 뉴스(`NewsStockRelation` 조인)/공시 텍스트에서 테마 키워드 추출 → `stocks.keywords` 채움.
- 기존 추출 자산 우선 재사용: `ai_classifier._extract_sector_keywords`, `sector_theme_map`,
  (필요 시) `keyword_generator`. **규칙/사전 우선, LLM은 예산 가드 하 보조**(OQ-1).
- 1회성 배치 = 유계·멱등(재실행 안전), 종목당 키워드 캡, 정규화 어휘.
- 수동/following 키워드 오염 금지(REQ-004).
- **AC: AC-084-001~004.**

### M2 — 그룹 C 지속 태깅 파이프라인 (Priority Medium)

- 신규 뉴스/공시 유입 반영 갱신(스케줄 크론 vs 수집 훅 — OQ-6). 종목당 키워드 무한증식 방지 캡.
- **AC: AC-084-005.**

### M3 — 그룹 B 긴급도 재보정 (독립, Priority High)

- `_classify_urgency` 호출부(`news_crawler.py:577`)에 `recent_topic_counts` 공급 → 기존 co-mention
  경로 활성화(REQ-005). co-mention 카운트 산정(윈도우/테마 키)은 OQ-4.
- `_IMPORTANT_KEYWORDS`/breaking 커버리지 확장(REQ-006), 단 음성 대조군(REQ-007) 통과 필수.
- 설정 플래그 게이팅 + 단계적 롤아웃(REQ-008, SPEC-AI-079 관례).
- DDD 재현 우선: 07-22 로봇 기사 15행(현재 전부 routine) 특성화 → 재보정 후 co-mention 버스트 존재 시
  ≥ important 검증. 기존 routine 분류 무회귀.
- **AC: AC-084-006~009.**

### M4 — 그룹 A 뉴스 테마 전파 탐지기 (핵심, Priority High)

- `detect_theme_group_carry_forward`(surge_detector.py:3012) 패턴 미러링, **키워드 바스켓 키잉**:
  - 키워드 바스켓(공유 `stocks.keywords`) 정의(OQ-2).
  - 앵커 활성화 판정: 가격 변화 및/또는 고긴급 뉴스가 임계 초과(REQ-009).
  - 미이동 멤버 한정 전파(`existing_ids` 패턴, REQ-010).
  - **테마 활성 확인 게이트**(복수 멤버 이동 OR 고긴급 테마 뉴스 + 앵커 이동, REQ-011, 임계 OQ-3).
  - 바스켓 부재 시 안전 no-op(REQ-012).
  - `surge_metadata.surge_basis=["theme_news_carry"]`, `signal_type="surge_candidate"`,
    `paper_executed=True`, 바스켓당 캡, 크로스바스켓 dedup, 예외 격리.
- **배선**: `fund_manager._run_coverage_expansion()`에 additive 등록([E-5]) → SPEC-AI-083 장중 재스캔에서
  자동 반복 실행. 기존 탐지기/앙상블/유니버스 무변경(REQ-015/016).
- 실매매 미트리거(REQ-014).
- **AC: AC-084-010, 011, 012, 014, 015 (same-day AC-084-013은 M5).**

### M5 — 그룹 A same-day 지평 귀속 + 평가 편입 (최상위 필수, Priority High)

- 전파 후보를 `fund_signals` 영속화 시 `surge_metadata["horizon"] = "same_day"`로 태깅(SPEC-AI-080
  지평 메타데이터 재사용, 신규 스키마 없음) → `_is_same_day_event_horizon_signal`
  (surge_evaluation_service.py:506-524, 계약 `surge_metadata.get("horizon") == "same_day"`) 평가 경로
  편입(REQ-013).
- **필드/값 계약은 확정(firm)**: `horizon="same_day"`를 전파-생성 신호에 **설정**하는 것은 열린 질문이
  아니며 필드 수준 PASS/FAIL 테스트(전파 `fund_signals` 행의 `surge_metadata.horizon` DB 어서션)를
  갖는다. **오직 트리거 임계**(어떤 후보에 same_day를 부여할지: 전량 vs 특정 조건)만 OQ-5/DP-5에 위임.
- 이 마일스톤 누락 시 SPEC 목적 무효(R-4) → 독립 검증.
- **AC: AC-084-013(최상위 same-day). 공통 AC-084-016(first-mover 제외, 명명 음성 테스트)/017(DDD 재현).**

> **의존 그래프**: M1 → M4/M5(A는 C 데이터 소비). M3(B)는 독립이나 M4 확인 게이트에 기여. M2는 M1 이후.
> 배포 순서 권고: M1 → M3 → M4 → M5 (M2는 병행/후행). 단 M4는 REQ-012로 M1 미완에서도 안전.

## Technical Approach (그룹별 기술 접근)

### 그룹 C — 키워드 태깅

- **재사용 우선(Enforce Simplicity 사다리)**: `_extract_sector_keywords`(sector→키워드),
  `sector_theme_map`(theme→섹터, 역방향 활용 가능), `NewsStockRelation`(종목↔뉴스 조인, NewsArticle에
  stock_code 없음). LLM 추출은 예산 가드 하 보조.
- **데이터 경로**: `stocks.keywords`는 이미 ARRAY(Text) 컬럼 → UPDATE만. **마이그레이션 불필요**([X-4]).
- **멱등/유계**: 배치는 재실행 시 파괴적이지 않게(기존 키워드 병합/치환 규칙 확정), 종목당 상한.

### 그룹 B — 긴급도 재보정

- **최소 변경 축**: `_classify_urgency`의 co-mention 경로는 이미 존재([E-1]) → 호출부에 카운트 공급.
- **커버리지 확장**: `_IMPORTANT_KEYWORDS`/`_BREAKING_RE` 보강은 음성 대조군(REQ-007)에 종속.
- **게이팅**: 설정 플래그(surge/news 설정 섹션 — Run 확정), 기본 보수, 롤백=플래그 복귀.

### 그룹 A — 전파 탐지기

- **구조 미러**: `detect_theme_group_carry_forward`의 골격(config.enabled 게이트 / KST today-start /
  `existing_ids` dedup / 앵커 임계 / 멤버 전파 / per-basket 캡 / cross-basket dedup / surge_metadata /
  paper_executed / 예외 격리)을 그대로 따르되, "그룹 멤버"를 "키워드 바스켓 멤버"로 치환.
- **앵커/확인**: 계열 그룹은 지정 `anchor_stock`이 있으나 바스켓은 없음 → 테마 활성 확인 게이트로 대체
  (REQ-011). 이 부분이 신규 설계의 핵심(OQ-3).
- **same-day**: SPEC-AI-080 지평 태깅 재사용(신규 스키마 없이).

## Files to Modify (예상)

| 파일 | 그룹 | 변경 성격 |
|------|------|-----------|
| `backend/app/services/keyword_tagging_service.py` (신규 예상) | C | 배치 백필 + 지속 태깅 |
| `backend/app/services/scheduler.py` | C(M2) | 지속 태깅 잡 등록(택1: 훅) |
| `backend/app/services/news_crawler.py` | B | `_classify_urgency` 호출부 카운트 공급 + 키워드 확장 |
| `backend/app/services/surge_detector.py` | A | `detect_theme_news_carry`(신규) additive 탐지기 |
| `backend/app/services/fund_manager.py` | A | `_run_coverage_expansion()` 배선 |
| `backend/app/surge_config/surge_detection.yaml` + `surge_settings.py` | A/B | 신규 config 섹션·플래그 |
| `backend/app/services/surge_evaluation_service.py` | A(M5) | same-day 편입(기존 경로 재사용) |
| `backend/tests/test_*` (신규) | 전부 | 특성화 + 신규 테스트 |

> 실제 파일/함수명은 Run annotation 단계 확정. `stocks.keywords` 컬럼은 기존 → **마이그레이션 없음**.

## Decision Points (Run 확정 — spec.md §7 OQ와 연동)

- **DP-1(=OQ-1)**: 키워드 추출 방식(규칙/LLM/혼합) — 예산·품질.
- **DP-2(=OQ-2)**: 바스켓 정의 입도(단일 키워드 교집합 vs 클러스터).
- **DP-3(=OQ-3)**: 테마 활성 확인 임계(멤버 수 N / 긴급도 조합) — 07-22 로봇 랠리 replay로 캘리브레이션.
- **DP-4(=OQ-4)**: co-mention 카운트 윈도우·테마 키.
- **DP-5(=OQ-5)**: same-day 귀속 트리거(전량 vs 조건).
- **DP-6(=OQ-6)**: 지속 태깅 트리거(크론 vs 훅).

## 검증 (DDD)

- 방법론: DDD ANALYZE-PRESERVE-IMPROVE + Reproduction-First(REQ-018).
- 명령: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`; 린트
  `cd backend && uv run ruff check .`.
- 공유 코드(`_classify_urgency`, `_run_coverage_expansion`) 변경은 특성화 테스트 선행 → 기존 발신/분류
  무회귀 확인(R-5).

## Risks (요약 — spec.md §5 참조)

- R-1 오전파/precision(그룹 A) / R-2 키워드 품질(C) / R-3 긴급도 오상향(B) / **R-4 same-day 귀속 누락
  (최상위)** / R-5 공유 코드 회귀 / R-6 LLM 예산. 모두 예측 기록 모드라 자금 리스크 0.
