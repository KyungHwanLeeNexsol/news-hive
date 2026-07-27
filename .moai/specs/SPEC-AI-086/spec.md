---
id: SPEC-AI-086
version: 0.1.1
status: completed
created: 2026-07-24
created_at: "2026-07-24"
updated: 2026-07-27
author: Nexsol
priority: medium
issue_number: null
lifecycle_level: 1
tier: M
labels: [surge-detection, scan-universe, coverage, measurement-layer, quota, diagnostics, non-scannable, backend]
---

# SPEC-AI-086: 스캔 유니버스 커버리지 확장 — 진단 우선 + 소스 풀/상한 유연화 (측정 계층 한정)

## HISTORY

- 2026-07-24 v0.1.0 (draft): 초안 생성. 2026-07-23 공식 평가(scannable=19, non_scannable=129/148=87%)
  구조적 커버리지 천장 문제 대응. **핵심 재구성**: read-only 코드 검증으로 `build_scan_universe`가
  탐지 입력이 아닌 측정 전용 '그림자 유니버스'임을 확인 → 작업 지시의 "상한↑ → recall↑ / LLM 비용↑"
  전제를 정직하게 정정. 본 SPEC은 측정 계층(커버리지 지표) 확장 + 진단 관측성에 한정하며, 유니버스를
  실제 탐지에 배선하는 recall 상향은 별도 후속 SPEC으로 분리(Exclusion 1). 사용자 승인: Option A 확정.
- 2026-07-24 v0.1.1 (draft): plan-audit iteration-1(FAIL, 0.55) 결함 반영. D2/D7 프론트매터
  (`created_at`/`labels`/`lifecycle_level` 추가 + `priority` 소문자화, SPEC-AI-084/085 컨벤션 정렬),
  D1 acceptance AC를 EARS 문장 선두 + Given/When/Then 테스트 시나리오 부속으로 재작성, D3 REQ-004·008
  대응 AC-086-008·009 신설(REQ-001~008 전량 커버리지 확보), D4 REQ 정규문에서 리터럴 식별자를 "구현
  참고" 부속 라인으로 이관, D5 REQ-003 신규 풀 유계 fetch와 REQ-005 fetch-증가 금지의 범위 모순 명시
  해소, D6 AC-086-007 "구분 기록"을 명명 필드 기반 기계 검증으로 구체화. 요구사항 실질(범위) 무변경.

## Context / Problem

NewsHive 급등예측은 매일 실제 급등 종목의 87%(2026-07-23: 129/148)가 스캔 유니버스(150) 밖에 존재하는
구조적 커버리지 천장을 갖는다. coverage(=scannable/actual=19/148=12.8%)는 산술적으로 recall의 상한이며,
현재 TP=3이므로 완벽 탐지를 가정해도 recall은 12.8%를 넘을 수 없다.

### 검증된 아키텍처 사실 (read-only, 2026-07-24)

- **[F-1] `build_scan_universe`(`surge_detector.py:4383`)는 측정 전용 그림자 유니버스다.** 탐지기는
  각자 자기 입력원에서 후보를 만들고(`gather_surge_candidates:1829`), `build_scan_universe`는 그 **이후**
  `existing_codes=set(merged.keys())`로 호출(`:1933`)되어 (a) entry_pool 태깅, (b) 커버리지 지표 영속화
  (`persist_pool_counts`/`persist_universe_members`, SPEC-AI-068)에만 소비된다. `_universe_codes`는
  탐지기에 재투입되지 않는다. 스케줄러 호출부(`:1226`/`:1243`)는 결과를 로그만 찍고 폐기한다(`:1944` 주석).
- **[F-2] 따라서 `max_scan_universe`(150) 상향은 탐지 도달 범위를 넓히지 못한다.** 바뀌는 것은
  `scan_universe_size` 분모와 영속 universe_members 행 수뿐이다(측정 전용). recall은 불변,
  scannable_recall(TP/scannable)은 scannable 증가로 **산술 하락**한다.
- **[F-3] 상한 상향의 실비용은 근사 0이다.** Pool B는 `max_scan_universe`와 무관하게 이미 `limit=140`만큼
  fetch하고, 상한은 최종 리스트만 절단한다. 상한 상향은 추가 Naver fetch·탐지기 실행·LLM 발신 호출을
  유발하지 않는다. 작업 지시가 가정한 "상한↑ → Gemini 무료티어 비용↑" 결합은 현재 구조에 없다.
- **[F-4] 진짜 recall 레버는 유니버스를 탐지 입력으로 배선하는 것이며, 그때 비로소 gather wall-time
  (SPEC-AI-082 1200s 타임아웃) + 발신 LLM 비용이 실제로 발생한다.** 이는 본 SPEC 범위 밖(Exclusion 1).
- **[F-5] non_scannable 129건의 원인이 (a) Pool A/B/C raw에 있으나 150 절단으로 탈락한 것인지,
  (b) 애초에 어떤 풀에도 없는 것인지 현재 지표로는 구분 불가.** SPEC-AI-076이 pool_*_scanned를 추가했으나
  실제 급등 종목별 "왜 non_scannable인가"는 미기록. 이 구분이 상한↑(a에만 유효) vs 신규풀(b에 유효) 선택을 좌우.

### Goal

측정 계층 한정으로: (1) non_scannable 원인을 진단 가능하게 만들고, (2) `max_scan_universe`와 풀 구성을
설정 기반으로 유연화하며, (3) absent-from-source 격차를 줄이는 신규 소스 풀을 설정 게이팅(기본 OFF)으로
도입한다. **발신 시그널 수 증가가 아니라 채점 커버리지(coverage) 개선이 목적**이며, 커버리지 지표가 실제로
도달 가능해지려면 유니버스→탐지 배선(별도 SPEC)이 필수임을 명시한다.

## Requirements (EARS)

> [D4] 각 요구사항의 정규 "shall" 문장은 서술적 용어로 유지하고, 구체 함수/테이블/설정 식별자는
> 각 REQ 하단의 "구현 참고" 부속 라인으로 이관한다(WHAT/WHY 수준 보존).

### REQ-AI086-001 (State-Driven, P0) — 스캔 유니버스 상한 설정 유연화 + 경계 clamp
**While** 운영자가 스캔 유니버스 상한을 안전 경계 `[하한, 상한]`(예: [50, 600]) 이내 값으로 설정하는 동안,
the system **shall** 그 값을 경계 이내로 clamp하여 적용하고, 미설정 시 현재 기본 상한(150)을 유지한다
(제로-diff 백워드 호환). 경계 밖 오설정 시 the system **shall** 값을 clamp하고 경고 로그를 남기며 예외 없이
완료한다.
> 구현 참고: 대상 설정 키 `max_scan_universe`(`surge_settings.py:532`, 현재 기본값 150), 경계 상수 신설.

### REQ-AI086-002 (Ubiquitous, P0) — non_scannable 원인 진단 관측성 [HARD]
The system **shall** 각 평가일의 실제 급등 종목 중 스캔 유니버스에 포함되지 못한(non_scannable) 종목에
대해, 그것이 **절단-바운드(truncated: 후보 풀에는 존재했으나 상한 절단으로 탈락)**인지 **소스-부재
(absent: 어떤 풀 기준도 충족하지 못함)**인지를 구분 가능한 진단 정보를 기록하며, 신규 DB 마이그레이션
없이 이를 달성한다.
> 구현 참고: 기존 `SurgeUniverseMember`(entry_pool) + `pool_*_scanned`(SPEC-AI-076) + `SurgeActualOutcome`
> 조인 재사용(로그 + 기존 테이블), 신규 컬럼/마이그레이션 회피.

### REQ-AI086-003 (Where/Optional, P1) — 신규 소스 풀(quota 통합) 설정 게이팅 도입
**Where** 신규 측정 소스 풀(당일 뉴스 언급 종목 또는 광의 장중 등락 종목)이 설정으로 활성화된 경우,
the system **shall** 그 풀을 기존 예약 슬롯(quota) 배분에 통합하여 소스-부재 non_scannable을 축소하고,
그 풀을 **기본값 비활성(OFF)**으로 단계적 롤아웃한다. **Where** 신규 풀 소싱이 외부 조회를 유발하는 경우,
the system **shall** 그 조회를 유계(bounded)로 제한한다. 이 신규-풀 소싱 조회는 REQ-005의 기존-경로
fetch-증가 금지 불변식과 **별개의 명시적으로 허용된 측정 유니버스 구성 비용**이다(범위 경계는 REQ-005 참조).
> 구현 참고: 신규 풀=Pool D(뉴스=`NewsStockRelation` / 장중 등락), 예약 슬롯 필드 `pool_d_min_slots`
> (SPEC-AI-076 `reserved_*` 패턴 확장), SPEC-AI-079 단계적 롤아웃 관례.

### REQ-AI086-004 (Where/State, P1) — 장중 시간대별 동적 상한 (선택)
**Where** 시간대별 동적 상한이 설정으로 활성화된 경우, the system **shall** 현재 스캔 시각이 속한 시간대에
할당된 상한을 적용한다(예: 오전 초반 스캔과 장 마감 전 스캔에 서로 다른 상한). **Where** 동적 상한이
미설정(기본값)인 경우, the system **shall** REQ-001과 동일한 단일 평탄 상한을 적용한다.

### REQ-AI086-005 (Unwanted, P0) — 측정 전용 비용 경계 [HARD]
**If** 본 SPEC의 확장(상한 상향 / 신규 풀 / 동적 상한)이 적용되더라도, **then** the system **shall NOT**
기존 탐지 경로의 탐지기 실행 수, 후보 수집(gather) 소요시간, 스캔당 외부 시세 조회 수, 또는 LLM 발신 호출
수를 증가시키며, 측정 유니버스 구성 결과를 신규 탐지 패스에 투입하지 아니한다.
**범위 명확화 [D5]**: 본 불변식의 "외부 조회 증가 금지"는 **기존 Pool A/B/C 및 후보 수집(gather)·탐지
경로**에 국한된다. REQ-003 신규 풀(Pool D)의 유계·기본-OFF 소싱 조회는 **측정 유니버스 구성 비용**으로서
이 불변식과 별개이며 명시적으로 허용된다(탐지·발신 경로 비용이 아님). 유니버스→탐지 배선은 Exclusion 1로
분리한다.
> 구현 참고: 측정 유니버스 구성 함수 `build_scan_universe`는 탐지 이후 구성으로 유지, `_universe_codes`의
> 탐지 재투입 금지(회귀 assert), 외부 조회=Naver 시세 fetch.

### REQ-AI086-006 (Unwanted, P0) — 커버리지 지표 정합성 [HARD]
**If** 스캔 유니버스가 확장되어 scannable_recall(적중/scannable)이 탐지 무변경 상태에서 산술적으로
하락하더라도, **then** the system **shall NOT** 이를 탐지 성능 회귀로 오기록하며, coverage/scannable_recall의
분모 의미를 보존하고, 그 하락이 탐지 회귀가 아님을 **기계적으로 검증 가능한 명명 필드/메타 표식**으로
구분 기록한다.
> 구현 참고: 지표 계산식(SPEC-AI-068) 불변, 확장 사실을 평가 레코드 메타의 명명 필드(예:
> `scannable_denominator_expanded` 불리언 또는 동등 로그 토큰)로 표식(AC-086-007 검증 지점).

### REQ-AI086-007 (State-Driven, P0) — 백워드 호환 탈출구
**While** 신규 설정이 모두 기본값(상한=150, 신규 풀 OFF, 동적 상한 OFF)일 때, the system **shall**
현재 측정 유니버스 구성 출력과 바이트 동등한 결과를 낸다.
> 구현 참고: SPEC-AI-076 REQ-004 백워드 호환 관례(예약 슬롯=0 → 레거시 엄격 절단과 동등).

### REQ-AI086-008 (Optional, P2) — 관측성
**Where** 로깅이 유효한 경우, the system **shall** 적용된 상한 값, 풀별 raw/scanned 카운트, 신규 풀 카운트,
non_scannable 원인 분류 요약을 단일 로그 라인으로 기록하며, 신규 스키마를 도입하지 아니하고 종목별 상세
로그를 남기지 아니한다.

## Exclusions (What NOT to Build)

1. **[HARD] 유니버스 → 탐지 배선(universe를 실제 탐지 입력으로 사용)은 범위 밖.** 이것이 recall을 실제로
   올리는 진짜 레버지만, gather wall-time(SPEC-AI-082 1200s 타임아웃 재현 위험) + 발신 LLM 비용을 유발하는
   대규모·고위험 변경이라 **별도 후속 SPEC**으로 분리한다. 본 SPEC은 탐지 도달 범위를 넓히지 않는다(측정 전용).
2. **auto_improve_enabled 재활성화 금지** (2026-07-02부터 정지, SPEC-AI-069 설계된 기본값, 별개 이슈).
3. **`existing_codes` 병합 필터 pre-existing 버그 미수정** (SPEC-AI-076 Exclusion 10에서 의도적 보존 —
   본 SPEC의 배분 로직과 인접하나 손대지 않음).
4. 탐지기 본체 / 앙상블 가중치 / 적응형 임계 / 발신 게이팅 / 매매(SPEC-AI-043 예측기록모드) 무변경.
5. Pool A/B/C 후보 **소싱** 로직(SPEC-AI-073 Pool A / 074 Pool B / 078 Pool A 정렬 / 065 Pool C) 무변경 —
   본 SPEC은 배분·상한·신규 풀 통합만.
6. `_min_ratio`(2.0) 변경 금지, `gather_surge_candidates` HTTP 재구조화(SPEC-AI-082 §8) 범위 밖.
7. 과거 coverage/universe_members 백필 금지 (전진 적용만).

## Ownership

- **본 SPEC**: 측정 계층 유연화(상한 설정화 + 신규 풀 quota 통합 + non_scannable 진단 관측성).
- SPEC-AI-065: `max_scan_universe` 값·유니버스 입력 원칙(본 SPEC은 설정 유연화만, 기본값 150 보존).
- SPEC-AI-076: quota 예약 배분(본 SPEC은 pool_d 예약 슬롯으로 확장).
- SPEC-AI-068: 커버리지/Scannable Recall 지표(본 SPEC은 진단 정보만 추가, 계산식 불변).
- SPEC-AI-082: gather 타임아웃 제약(탐지 배선 후속 SPEC의 선결 조건).
