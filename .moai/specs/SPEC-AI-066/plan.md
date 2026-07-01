# SPEC-AI-066 구현 계획 (Implementation Plan)

## 기술 접근 개요

본 SPEC은 **촉매 확신도(catalyst conviction)** 라는 공통 판별 신호를 도입하고, 확신도가
HIGH일 때만 각 탐지기의 게이트를 통제된 범위에서 조건부 완화한다. 신규 탐지기·매매 엔진·
외부 데이터 소스를 추가하지 않고, 이미 조회 중인 뉴스/공시 데이터의 집계 확장과 SPEC-AI-065
베이스라인 서비스 재사용으로 구현한다.

핵심 불변식(모든 마일스톤에서 유지):
- SPEC-AI-030 신선도(Gate2)·분산(Gate3)·combo 단독 차단(Gate4)은 확신도와 무관하게 항상 활성.
- 앙상블 가중치·컨센서스 배율·적응형 임계값·가중치 자동보정은 무변경.
- `catalyst_conviction.enabled=false`이면 전체 완화 비활성 → SPEC-AI-030/028 동작 복원.

---

## 마일스톤 (우선순위 기반, 시간 추정 없음)

### Milestone 1 (P0) — 확신도 산출 + config 골격 (REQ-001, REQ-006)

- `CatalystConvictionConfig` Pydantic 모델 및 `surge_detection.yaml` 섹션 추가.
- combo 탐지기의 NewsStockRelation 조회(surge_detector.py:539~558)를 확장: 종목당
  max sentiment만 보관하던 것을 **기사 수 + min/max published_at + 감성 분포**까지 집계.
- 확신도 산출 헬퍼 함수 신규(순수 함수, DB 세션 불필요하게 설계 — 집계 dict 입력).
- 확신도 tier 분류(LOW/MEDIUM/HIGH) 로직. 단위 테스트로 tier 경계 고정.

### Milestone 2 (P0) — combo 과열 게이트 확신도 차등 완화 (REQ-002)

- `combo_chase_guard.overheat_change_pct_high_conviction` 추가.
- surge_detector.py:641 과열 게이트를 확신도 분기로 교체(HIGH → 상향 상한, 그 외 → 기존 5%).
- Gate2/3/4 코드 경로는 손대지 않음(회귀 방지).
- 테스트: HIGH 확신도 +12% 통과, HIGH 확신도지만 change_rate<0(분산) 여전히 차단,
  HIGH 확신도지만 freshness<1.5 여전히 차단, non-HIGH +7% 기존대로 차단, enabled=false 폴백.

### Milestone 3 (P0) — 전략적 인수 공시 페널티 예외 (REQ-003)

- `disclosure_type_filter.acquisition_exemption_enabled` + `disclosure_type_filter.acquisition_penalty_factor`(기본 0.7) + `catalyst_conviction.acquisition_keywords` 추가.
- surge_detector.py:976,986 페널티 적용부에 예외 조건 삽입: 페널티 매칭 공시가
  (인수/합병/경영권 키워드) AND (positive+ 감성) AND (change_rate>=0)이면 penalty_factor를
  **0.3→0.7로 부분 완화**(완전 면제 아님 — 최대주주변경 잔여 리스크 반영).
- 부실 매각/경영권 분쟁성(호재 근거 없음)은 penalty_factor 0.3 유지.
- 테스트: 위메이드형 인수 최대주주변경 0.7 적용, distress 최대주주변경 0.3 유지, 스위치 off 폴백.

### Milestone 4 (P1) — 뉴스 공동언급 테마 자동 확장 (REQ-004) *(분리 가능)*

- cluster_window 내 기사별 종목 co-mention 집계 → 임계 이상 동반 등장 종목 클러스터 식별.
- theme_cluster 후보 보강 또는 확신도 보조 근거로 연결.
- group_cascade(AI-027/035) 계열사 클러스터와 중복 배제 로직.
- 기본 `comention_theme_enabled=false`(단계적 롤아웃). 활성 시 테스트.

### Milestone 5 (P1) — volume_breakout 유니버스 확장 + 상대 임계 (REQ-005) *(분리 가능)*

- 유니버스에 촉매 종목(공시/뉴스 커버리지 보유) 합류.
- `surge_baseline_service`(AI-065) 재사용한 종목별 상대(z-score) 임계 경로 추가.
- cold start 시 고정 3.0x 폴백. `relative_threshold_enabled=false` 기본(단계적).
- AI-062 가중치·AI-063 bypass 임계 불변 확인.

### Milestone 5.5 (P1) — 고임팩트 뉴스 이벤트 구동 재스캔 (REQ-007)

- `catalyst_conviction`에 `event_rescan_enabled`(기본 false)/`event_rescan_cooldown_minutes`(30)/
  `max_daily_event_triggers`(20) 추가.
- scheduler.py `_run_crawl_job`(:37~81)에서 `_run_keyword_matching()` 완료 직후 훅 삽입:
  신규 저장 기사에 대해 HIGH-conviction 판정(REQ-001 재사용) → 충족 시
  `run_surge_signal_generation`(fund_manager.py:2976) 비동기 1회 트리거.
- 남용/예산 가드: 종목당 쿨다운(30분) 상태맵 + 일일 트리거 카운터(20회 상한). 상한/쿨다운
  도달 시 스킵하고 정기 스캔에 위임.
- 정기 잡(`_run_surge_signal_generate` 15:20/intraday) 등록·스케줄은 불변(회귀 확인).
- LLM 예산(Gemini 무료 tier) 소모를 고려해 일일 상한은 필수. `event_rescan_enabled=false`이면
  전체 비활성(정기 스캔만).
- 테스트: HIGH 기사 저장→트리거 발생, 쿨다운 내 재트리거 차단, 일일 상한 초과 스킵,
  정기 스캔 불변, 스위치 off 폴백.

### Milestone 6 — 통합 검증

- `catalyst_conviction.enabled=false` 전체 폴백이 SPEC-AI-030/028과 바이트 동등 동작인지 검증.
- 위메이드형 합성 시나리오(4경로)에서 최소 1개 경로가 신호를 생성하는지 확인.
- 회귀: 기존 surge 테스트 스위트 통과.

---

## REQ-002 핵심 설계 결정 — 과열 게이트 판별 방식 (3개 옵션)

task 요청에 따라 "확정 강한 촉매, 초기"와 "애매한 급증, 스마트머니 이탈"을 구분하는 방식을
3개 옵션으로 제시한다.

### Option A — 확신도 2단 이산 상한 (권장)

- non-HIGH: 기존 상한 `overheat_change_pct=5.0` 유지. HIGH: `overheat_change_pct_high_conviction=15.0`.
- 확신도 HIGH 조건 = (기사 수 >= min_article_count_high) AND (커버리지 지속시간 >= min_coverage_hours_high)
  AND (감성 강도 >= min_sentiment_high)  —  또는 공시 뒷받침 존재.
- **장점**: 최소 변경·낮은 blast radius. SPEC-AI-030 기본 동작을 비트 단위로 보존. 테스트·
  롤백·설명이 쉬움. HIGH 조건에 "지속적 다출처 커버리지"를 요구해 순간 펌프를 위장하기 어려움.
- **단점**: 이산 경계라 경계 근처 미세 최적화 여지 적음. HIGH 임계 튜닝 필요.
- **위험 완화**: 분산 게이트(Gate3)가 하락 중 물량을 계속 차단하고, HIGH 조건의 지속시간
  요건이 펌프앤덤프를 배제. SPEC-AI-030 실패(2026-06-02)의 재현 위험 최소.

### Option B — 공시 뒷받침에 한정한 상한 우회

- pure-news 촉매는 5% 유지, **DART 공시로 확정된 촉매만** 상한 우회(사실상 무제한).
- **장점**: 가장 보수적(공시=검증된 사실). 거짓 양성 위험 최저.
- **단점**: 위메이드처럼 **뉴스가 공시보다 먼저 확산**되는 경우, 08:00 스캔 시점에 공시가
  아직 접수/파싱 전이면 여전히 놓침. recall 개선폭이 작음. 순수 뉴스 촉매(비공시 M&A 보도,
  업황 뉴스 랠리)를 구조적으로 못 잡음.

### Option C — 확신도 연속 스케일 상한

- 상한 = f(확신도), 확신도 0→5%, 1→20% 선형/시그모이드 보간.
- **장점**: 가장 매끄러운 튜닝. 촉매 강도에 비례한 관용.
- **단점**: 추론·테스트·설명 난이도 최고. 노브 증가로 오보정 위험. SPEC-AI-030 실패 재현
  안 함을 증명하기 어려움(연속 함수의 임의 지점 검증 부담).

### 확정: **Option A** (사용자 승인 2026-07-01)

이산 2단이 recall 개선과 SPEC-AI-030 보존의 균형이 가장 좋고, 테스트·롤백·설명이 쉽다.
"확정-초기"와 "애매-후발"을 명확한 확신도 임계로 가르며, 하드-투-캘리브레이트 연속 함수
없이 목표를 달성한다. Option B의 공시 한정은 pure-news 촉매(위메이드 시나리오의 핵심)를
놓칠 수 있어 단독 채택 부적합 — 다만 "공시 뒷받침"을 Option A의 HIGH 승격 근거 중 하나로
포함해 B의 장점을 흡수한다.

---

## REQ-004 설계 노트 — co-mention 테마 (데이터 파이프라인 고려)

- 최소 구현: cluster_window 뉴스에 대해 기사별 NewsStockRelation 종목 집합을 만들고,
  종목 쌍(pair) co-occurrence를 카운트해 `comention_min_pairs` 이상 동반 등장한 종목들을
  임시 클러스터로 묶는다. 기존 NewsStockRelation 데이터만 사용 → 신규 파이프라인 불필요.
- 확장(별도 SPEC 후보): 가격 상관(co-movement correlation) 기반 클러스터링, 지속적
  클러스터 마스터 테이블화. 이는 별도 데이터 파이프라인·저장소가 필요하므로 본 SPEC에
  포함하지 않고 자매 SPEC(예: SPEC-AI-067 "테마 자동 파생 파이프라인")으로 분리 권장.
- group_cascade(AI-027/035) 중복 배제: 파생 클러스터가 동일 사업그룹 계열사로만 구성되면
  group_cascade 소관 → 제외. 비계열 동조 클러스터만 본 REQ가 소유.

---

## REQ-005 설계 노트 — volume_breakout 상대 임계

- SPEC-AI-065 `surge_baseline_service` API를 Run 단계에서 먼저 확인(함수 시그니처·반환형)
  후 재사용. 미존재/불충분 시 인라인 z-score(순수 파이썬, statistics 모듈) 폴백.
- 유니버스 확장은 촉매 종목(당일 공시 종목 + 뉴스 커버리지 종목)을 leader_codes에 합집합.
  중복 제거·상한(max_candidates) 준수.
- AI-062 가중치와 AI-063 bypass 임계는 절대 불변(회귀 테스트로 고정).

---

## 기술 리스크 및 완화

| 리스크 | 완화 |
|---|---|
| 확신도 완화가 SPEC-AI-030 추격매수 실패를 재현 | Gate2/3/4 전 구간 유지 + HIGH 조건에 지속 다출처 커버리지 요구 + 분산 게이트로 하락 물량 차단. enabled=false 즉시 롤백. |
| 공시 페널티 예외가 진짜 악재(부실 매각)를 통과 | 예외는 (인수 키워드 AND positive 감성 AND change_rate>=0) 3중 조건 동시 충족 시에만. 하나라도 불충족이면 페널티 유지. |
| 종목당 뉴스 재집계로 DB 부하 증가 | 이미 조회 중인 행 집합 재사용(신규 쿼리 없음). 집계는 인메모리. |
| co-mention/상대임계가 거짓 양성 증가 | 두 P1 기능 모두 기본 비활성(단계적 롤아웃) + SPEC-AI-041 평가 루프로 정밀도 관측 후 활성. |
| surge_baseline_service API 불일치 | Run 단계 선확인 + 인라인 폴백. |

---

## 결정 사항 (사용자 확정 2026-07-01)

1. **REQ-004/005 분리 여부** → **분리하지 않음.** 6개 REQ + REQ-007을 SPEC-AI-066 하나로 유지.
2. **REQ-002 판별 방식** → **Option A 확정** (확신도 2단 이산 LOW/HIGH, HIGH일 때만 과열
   상한 5%→15%).
3. **스캔 주기/이벤트 트리거** → **본 SPEC에 포함** (REQ-AI066-007 신규 추가). 이벤트 구동
   재스캔을 뉴스 크롤러 저장 완료 훅 방식으로 구현하며, 쿨다운 30분·일일 상한 20회로 남용
   방지. 정기 스캔은 불변.
4. **REQ-003 면제 강도** → **부분 완화(0.3→0.7) 확정** (완전 면제 아님). config
   `acquisition_penalty_factor` 기본 0.7.

## 잔여 튜닝 항목 (구현 시 확정, 블로킹 아님)

- HIGH 확신도 임계 초기값(`min_article_count_high` / `min_coverage_hours_high` /
  `min_sentiment_high`) 제안치 — Run 단계에서 최근 뉴스 분포로 캘리브레이션.
- `event_rescan_cooldown_minutes`(30)/`max_daily_event_triggers`(20) 초기값 — 운영 관측 후
  SPEC-AI-041 평가 루프로 조정 가능.
- P1 기능(REQ-004/005/007) 기본 비활성(staged) → 정밀도 관측 후 단계적 활성.
