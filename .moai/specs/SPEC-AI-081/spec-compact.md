# SPEC-AI-081 (compact)

- id: SPEC-AI-081 | status: draft | priority: High | created: 2026-07-15
- title: 공시 충격 스코어링 flat-base 카테고리(주요사항보고/지분공시) 콘텐츠 인식 정밀화
- goal: `score_disclosure_impact()`의 flat-base 경로에 (1) 최대주주 지배권 변경 키워드 커버리지
  확장, (2) 희석성 증권 발행결정(전환사채 등)의 스코어링-국소 재분류를 추가해, 재료 있는 공시가
  정당한 근거로 더 높게 평가되고 재료 없는 공시는 인플레이션되지 않도록 한다. 두 독립 일자쌍
  (07-13→07-14, 07-09→07-10)에서 scannable 미탐 100%가 확정된 후속 조사에서 발견.
- root cause: `_get_keyword_tier_multiplier`의 Tier1 "최대주주 변경"(공백 포함 리터럴)이 DART 표준
  제목 "최대주주등소유주식변동신고서"와 불일치(006340형). `dart_crawler._REPORT_TYPE_PATTERNS`의
  `("주요사항보고서", "주요사항보고")`가 `("전환사채", "발행공시")`보다 먼저 매칭되어 CB 발행결정이
  "주요사항보고서(전환사채권발행결정)" 제목 형식에서 항상 주요사항보고로 오분류(038880형).
  465770형("투자판단관련주요경영사항")은 진짜 무신호 — report_name/ai_summary 어디에도 추출 가능한
  신호가 없음(DART 원문 본문 미보유, ai_summary는 DART 수집 시점에 사실상 항상 None — 온디맨드
  프런트엔드 생성 경로만 존재).

## 연구 정정 (원 조사 대비)

- "flat 카테고리는 ai_summary를 전혀 안 읽는다" → 부정확. Tier 배수는 모든 카테고리에서 이미
  report_name+ai_summary를 읽는다. 실제 문제는 키워드 목록의 협소함 + ai_summary가 스코어링 시점에
  거의 항상 비어있다는 것(온디맨드 생성, DART 파이프라인 미연결).
- "DART 자체 분류가 틀렸다" → 부정확. `report_type`은 이 프로젝트 자체 `_classify_report_type()`의
  순서 있는 패턴 리스트 결과(첫 매칭 우선 버그), DART API 값이 아님.
- 038880형 재분류는 flat +20보다 **더 높은** 점수를 보장하지 않음(희석 신호는 방향성 불명, report_name
  만으로 판별 불가) — "상향"이 아닌 "차등 처리"로 acceptance 범위 재조정([X-9]).

## REQ (8)

- REQ-AI081-001 (P0, Ubiquitous): 최대주주 지배권 변경 DART 표준 제목(예: "최대주주등소유주식변동
  신고서")을 정규화 매칭(공백/·제거)으로 Tier1 수준(×2.0) 신호로 인식하도록 키워드 커버리지 확장.
- REQ-AI081-002 (P0, Event): WHEN report_type=="주요사항보고" AND report_name에 희석성 증권 발행
  키워드(전환사채/신주인수권/교환사채/유상증자/무상증자/파생결합증권), SHALL 발행공시 스코어링
  경로로 로컬 재분류(스코어링 함수 내부 한정, `dart_crawler.py`/저장 `report_type` 불변, [X-2]).
- REQ-AI081-003 (P0, Unwanted) [HARD]: ai_summary를 1차/필수 신호원으로 의존 금지 — DART 수집
  시점 사실상 항상 None. 1차 신호원은 report_name.
- REQ-AI081-004 (P0, State) [HARD]: 신규 설정 플래그(`disclosure_content_aware_scoring.enabled`,
  기본 false) 비활성 시 레거시 완전 동등(SPEC-AI-079/080 롤아웃 패턴 계승).
- REQ-AI081-005 (P0, Unwanted) [HARD]: 신호 키워드 무매칭 공시(465770형)는 flat 기본값 대비
  인위적 상향 금지 — 오탐 회귀 방지.
- REQ-AI081-006 (P0, Ubiquitous) [HARD]: 다른 5개 report_type 카테고리, 하위 소비자
  (process_disclosure_impact/즉시발화/섹터파급/미반영갭) 게이팅 로직 자체, `report_type`
  저장값/`dart_crawler.py` — SHALL NOT 변경.
- REQ-AI081-007 (P0, Unwanted) [HARD]: 변경 전 특성화 테스트 선행(DDD ANALYZE-PRESERVE, 재현
  우선 — CLAUDE.md Rule 4).
- REQ-AI081-008 (P2, Optional): 재분류/키워드확장 트리거 시 관측성 로그(선택, 스키마 변경 없음).

## Exclusions

- DART 공시 원문 본문 수집/파싱 신설 금지([X-1], 465770형 근본 해결은 별도 대형 SPEC 후속 후보).
- `dart_crawler._classify_report_type()`/`Disclosure.report_type` 저장값 변경 금지([X-2]) —
  재분류는 스코어링 로컬 변수(`effective_report_type`)로 한정.
- SPEC-AI-080 `immediate_surge.enabled`/이벤트 화이트리스트, `auto_improve_enabled`, disclosures
  5일 보존 정책, near_limit_up_carry 로직 — 전부 무변경.
- 006120형(공시·뉴스 전무 순수 가격/거래량 급등) 탐지 아키텍처 개선 — 범위 밖([X-7]).
- 신규 테이블/마이그레이션/과거 데이터 백필 금지(전진 적용만).
- [핵심] 038880형이 flat +20보다 "더 높은" 점수를 받는다는 보장 없음([X-9]) — 방향성 불명 신호를
  인위적으로 상향 고정하면 통상 CB/증자 공시 전반에 오탐 유발 위험.

## Deps

- extends SPEC-AI-004(원 소유)/SPEC-AI-051(Tier 메커니즘, 커버리지만 확장, 구조 불변).
- context SPEC-AI-080(impact_score 소비자, 게이팅 로직 불변)/SPEC-AI-028(report_type 소비자, 무관
  — report_type 저장값 불변이므로).
- pattern SPEC-AI-079(공유 고 fan-in 함수 변경 시 기본값 OFF 롤아웃).
