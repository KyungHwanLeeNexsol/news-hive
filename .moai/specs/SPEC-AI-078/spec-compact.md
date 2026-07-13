# SPEC-AI-078 (compact)

- id: SPEC-AI-078 | status: draft | priority: High | created: 2026-07-13
- title: Pool A 공시 후보 impact_score 기반 우선순위 절단 교정
- goal: `build_scan_universe()` Pool A 후보를 impact_score 내림차순 정렬 → 절단 불가피한 날 고impact
  공시가 우선 잔존. recall 근-0%(2026-07-06~07-10) 근본원인 교정.
- root cause: Pool A 쿼리(`surge_detector.py:4230-4238`)에 `ORDER BY` 부재 → DB 반환 순서 사용. Pool A
  raw(232건, impact>=20만 155건)가 실질 슬롯(~100~130) 초과 시 최종 슬라이스(`:4427`)가 신호 품질과
  무관하게 임의 절단. 실증: 058730(다스코) impact=20 정상 스코어링됐으나 무순위 절단으로 유니버스 부재.

## REQ (7)
- REQ-AI078-001 (P0, State): WHILE 절단 발생, SHALL Pool A를 impact_score DESC 정렬 후 절단(고impact 우선 잔존).
- REQ-AI078-002 (P0, Unwanted): IF 미스코어링(NULL) 공시 포함, THEN NULL을 스코어링 공시보다 상위 정렬 금지
  + 완전 배제 금지(NULLS LAST 동급, 후순위 유지). Postgres 기본 NULLS FIRST 역효과 방지.
- REQ-AI078-003 (P0, Ubiquitous): SHALL 복수 공시 종목을 그 종목의 MAX(impact_score)로 대표 정렬.
- REQ-AI078-004 (P0, Unwanted): SHALL NOT max_scan_universe(150,AI-065)/AI-076 quota 메커니즘/pool_a raw
  카운트 의미 변경. 정렬은 순서만, 길이·카운트·quota diff 0.
- REQ-AI078-005 (P0, Event): WHEN 토글(pool_a_rank_by_impact) 비활성 OR 무절단, SHALL 레거시 동등
  (집합·entry_pool_map 동일). SPEC-AI-076 백워드 호환 토글 패턴 계승.
- REQ-AI078-006 (P1, Event): WHEN 07-08형 재현, SHALL 수정 전 "058730형 고impact 종목 부재" 실패 테스트
  → 수정 후 잔존 통과(재현 우선, CLAUDE.md Rule 4).
- REQ-AI078-007 (P2, Optional): WHERE 진단 필요, 절단 컷오프 impact 로깅(in-memory, 스키마 0).

## Exclusions
- max_scan_universe(150) 상향/하향 금지 — AI-065 소유, 읽어 사용만.
- SPEC-AI-076 quota(pool_b/c_min_slots) 메커니즘·floors==0 레거시 동등성 무변경. 정렬은 예약 이전 단계.
- pool_a raw 카운트 의미(pool_counts["pool_a"]/SurgeUniversePoolHistory) 변경 금지(AI-065 REQ-5 소비).
- Pool A/B/C 후보 소싱 필터 무변경(오직 Pool A 정렬만). 탐지기/앙상블/발신/임계/매매 diff 0(AI-043).
- 신규 테이블/마이그레이션/백필 없음(전진 적용만).
- [별도 백로그, 본 SPEC 밖] OPENAI_API_KEY 프로덕션 미설정 / LLM 미스분석 5종목 샘플링 캡 /
  263800·189330 LLM 미스분석 환각 가능성 — 별개 관심사(운영·후속 조사).

## Deps
- extends AI-065(유니버스 상한 상위)/AI-076(quota 배분). 정렬은 AI-076 예약 이전 단계라 상호 독립.
- context AI-073(DART 복구 → Pool A 절단 압력 최초 발생). AI-043 예측 기록 모드(매매 무개입).
