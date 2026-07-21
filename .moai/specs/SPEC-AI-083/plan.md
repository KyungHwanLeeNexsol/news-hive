# Plan: SPEC-AI-083 — 장중 고빈도 재스캔 + 이벤트드리븐 즉시발화 활성화

## 목표

당일 급등 실현 시간대(주로 09:00~10:30)에 후보 탐지의 시간 해상도를 높여, 1회 스캔(10:00)으로 놓치던
종목을 조기·즉시 포착하고 그 포착을 recall에 반영한다. 두 방향:

- **방향 A**: 09:05~BUY_CUTOFF 구간에 후보 생성 스캔을 N분 간격으로 확장 + same-day 지평 귀속.
- **방향 B(재범위화)**: 공시 즉시발화(이미 활성)의 회귀 보호 + 뉴스 기반 이벤트 재스캔 플래그 활성화.

기존 T-1→T 배치·탐지기·앙상블·유니버스·매매 로직은 diff 0.

## 코드 검증 정정 (Plan 진입 전 확정)

작업 지시 전제 2건이 현행 코드와 불일치함을 read-only 재검증으로 확정했다(spec.md §2, HISTORY):

| 전제 | 작업 지시 | 실제(2026-07-21 코드) | 영향 |
|------|-----------|----------------------|------|
| immediate_surge | `enabled=false`(꺼짐) | `enabled: true`(surge_detection.yaml:288, 2026-07-16 배포) + same_day 평가 배선 완료 | 방향 B 재범위화: 재플립 대신 회귀 보호 + 뉴스 재스캔 활성화 |
| surge_check_exits 5분 잡 | "이미 돈다" | SPEC-AI-043으로 비활성(주석, scheduler.py:2428-2439) | 5분 패턴은 참고만, 재스캔 잡은 신규 등록 |

→ **오케스트레이터가 이 정정과 방향 B 재범위화(REQ-AI083-008 뉴스 재스캔 활성화)를 사용자에게 고지하고
annotation 단계에서 확인을 완료했다 — 사용자는 REQ-AI083-008 포함(권장안)을 승인(2026-07-21). 방향 B
범위는 "공시 즉시발화 회귀 보호 + 뉴스 재스캔 활성화"로 확정.**

## 기술 접근 (Technical Approach)

### 1. 장중 고빈도 재스캔 잡 등록 (REQ-001/002/003/013, OQ-1)

**현행**(`scheduler.py:2401-2412`): 10:00 KST 단일 cron 잡 `surge_signal_generate_intraday`,
콜백 `_run_surge_signal_generate`(15:20 배치와 공유), `max_instances=1, coalesce=True`.

**핵심 제약**: gather 1회 = 12~15분(정상)~20분(최악, `_GATHER_TIMEOUT_S=1200`). 재스캔 간격 N이
gather 소요보다 짧으면 `max_instances=1`이 후속 트리거를 misfire로 건너뛴다 → 실효 빈도가 gather
소요로 자연 수렴. 따라서 **진짜 분 단위 고빈도는 gather 재구조화([X-6]) 없이는 불가**하며, 본 SPEC의
"고빈도"는 gather 소요에 상한이 잡히는 현실적 재스캔이다.

**권장안(OQ-1 (b), 단순성 우선)**: 09:05~BUY_CUTOFF 구간에 **고정 cron 시각 다중 잡**을 등록한다.
gather 정상 상단(15분)+헤드룸을 고려해 ~20분 간격으로:

- 09:10 (조기 스캔 — 09:00~10:00 사각지대 축소, REQ-004)
- 09:35
- 10:00 (기존 잡 유지)
- 10:30
- 10:55 (BUY_CUTOFF 직전)

각 잡은 기존과 동일하게 `max_instances=1, coalesce=True, replace_existing=True`, distinct `id`
(`surge_signal_generate_intraday_0910` 등)로 등록해 상호 클로버를 방지한다. 콜백은
`_run_surge_signal_generate`를 재사용(후보 생성만 호출, 매수/청산 콜백 미참조 — REQ-010, [X-3]).

**대안(OQ-1 (a))**: 인터벌형 단일 잡(`"interval", minutes=N`, 09:05~11:00 창 게이팅을 콜백 내
KST 시각 체크로 구현). 인터벌형은 시작 시각 정렬이 불명확하고 창 게이팅 로직이 추가되므로, 고정 cron
다중 잡이 관측·검증에 유리하다. 최종 방식은 annotation 단계 확정.

**간격/시각 근거(REQ-013)**: gather 정상 상단 15분 대비 ~20분 간격은 겹침을 방지(REQ-002)하면서
장 초반 110분 창에 5회 스캔을 배치한다. 실측 프로파일이 가능하면 Run 단계에서 재조정(블로커 아님).

### 2. 당일 후보 same-day 지평 귀속 (REQ-005, OQ-4)

**문제**: 장중(T) 재스캔이 생성하는 후보는 `created_at=T`이나, 표준 평가는 `date(created_at)==T-1`
버킷을 T 실제 급등과 비교한다(`surge_evaluation_service.py`). 지평 태깅이 없으면 T 후보가 T+1 급등과
비교되어 recall이 안 움직인다(SPEC-AI-075/080이 교정한 지평 불일치와 동일).

**해법(SPEC-AI-080 인프라 재사용, 스키마 0)**: 장중 재스캔이 당일 급등 예측으로 생성한 후보의
`surge_metadata`에 `horizon="same_day"`를 부여한다. 평가측은 이미
`_is_same_day_event_horizon_signal`(`surge_evaluation_service.py:506`)로 same_day 시그널을 표준
T-1→T predicted_set에서 배제하고 별도 same-day 서브지표로 집계하므로, **평가측 신규 코드 없이**
당일 캐치가 올바른 날에 귀속된다.

**귀속 조건(OQ-4)**: SPEC-AI-080 `_classify_disclosure_horizon`의 시간 기반 규칙(평일 09:00~batch_cutoff
접수 → same_day)을 재사용해, 장중 재스캔 시각이 09:00~batch_cutoff(15:20) 구간이면 그 스캔의 후보를
same_day로 태깅하는 안이 유력. 구체 배선(run_surge_signal_generation 경로에서 horizon 주입 지점)은
Run 단계 ANALYZE에서 확정.

### 3. 방향 B — 공시 즉시발화 회귀 보호 + 뉴스 재스캔 활성화 (REQ-007/008/009)

**B-공시(회귀 보호, REQ-007)**: `immediate_surge.enabled=true`와 same_day 평가 경로는 이미 활성.
본 SPEC은 이를 변경하지 않으며, 방향 A 변경이 이 경로를 깨지 않음을 회귀 테스트로 고정([X-1]).

**B-뉴스(활성화, REQ-008/009 — 확정 범위, 사용자 승인 2026-07-21)**: `surge_detection.yaml:262`
`catalyst_conviction.event_rescan_enabled: false → true`. 인프라(`_maybe_trigger_event_rescan`
`scheduler.py:107-163`, keyword_matching 완료 훅 `:220-223`)와 가드(쿨다운 30분/일일 20회)는 이미
구현됨(SPEC-AI-066 REQ-007). 활성화는 **설정 플립 + 사전조건 검증**이며 인프라 신규 구현이 아니다.

- 사전조건 검증(회귀 리스크 점검): git 이력상 `event_rescan_enabled`가 처음부터 staged rollout용
  기본 false였는지(의도적 비활성 vs 미완성) 확인. 코드상 인프라·테스트가 존재하므로 "미완성으로 인한
  비활성"이 아니라 "staged rollout 기본값"으로 판단(SPEC-AI-079 패턴과 동형).
- 활성화 후 관측: 이벤트 재스캔 발화 횟수·쿨다운 적중·일일 상한 도달을 로그로 확인. precision 일시
  저하는 예측 기록 모드라 자금 리스크 0(§5 [R-3]).

### 4. 범위·불변 회귀 가드 (REQ-006/010/011/012)

- `gather_surge_candidates`(탐지 본체)·앙상블·가중치·임계·유니버스 diff 0.
- 15:20 T-1→T 배치 크론/평가 지평 diff 0.
- BUY_CUTOFF 값/비교 로직 diff 0(참조만).
- 매수/청산 잡(주석 처리된 `surge_execute_buys`/`surge_check_exits`) 미복구, `execute_signal_trade`
  미호출.
- 기존 급등 테스트 스위트 무회귀(특히 SPEC-AI-080/082 테스트).

## 변경 대상 파일 (예상)

| 파일 | 변경 내용 | 규모 |
|------|-----------|------|
| `backend/app/services/scheduler.py` | 09:05~BUY_CUTOFF 구간 재스캔 cron 잡 다중 등록(distinct id, max_instances=1/coalesce), 매수/청산 콜백 미참조 | 중 |
| `backend/app/services/fund_manager.py` 또는 `run_surge_signal_generation` 경로 | 장중 재스캔 후보에 same-day 지평(`horizon="same_day"`) 귀속 배선(SPEC-AI-080 메타데이터 재사용) | 소~중 |
| `backend/app/surge_config/surge_detection.yaml` | `catalyst_conviction.event_rescan_enabled: false→true`(뉴스 재스캔 활성화) | 소(1줄) |
| `backend/tests/test_surge_ai083_intraday_rescan.py` (신규) | 재스캔 잡 등록/간격·겹침 방지, same-day 귀속, 이벤트 재스캔 활성화, 범위 불변 회귀 | 중 |

**신규 테이블/마이그레이션 없음. 탐지 본체·앙상블·매매 로직 무변경. same-day 귀속은 기존
surge_metadata(JSON) + SPEC-AI-080 평가 경로 재사용으로 스키마 변경 없음.**

## 마일스톤 (우선순위 기반, 시간 추정 없음)

1. **Priority High — ANALYZE (DDD)**: 재스캔 잡 등록 지점(`scheduler.py` start_scheduler 급등 잡 블록),
   `run_surge_signal_generation`의 후보 생성·메타데이터 주입 경로, SPEC-AI-080 horizon 태깅/평가 경로,
   이벤트 재스캔 가드 경로를 정독. 특성화 대상 식별.
2. **Priority High — PRESERVE (특성화 테스트)**: 현행 단일 10:00 잡 + immediate_surge 활성 + 이벤트
   재스캔 비활성 상태의 관찰 가능 거동을 특성화(회귀 기준선).
3. **Priority High — IMPROVE: 재스캔 잡 확장 + same-day 귀속 (REQ-001~006)**: 09:05~BUY_CUTOFF cron
   다중 잡 등록, same-day 지평 귀속 배선, 겹침 방지(max_instances/coalesce) 검증.
4. **Priority High — IMPROVE: 방향 B 회귀 보호 + 뉴스 재스캔 활성화 (REQ-007/008/009)**: immediate_surge
   불변 확인 + `event_rescan_enabled` 활성화 + 가드 준수.
5. **Priority High — 공통 불변 회귀 가드 (REQ-010/011/012)**: 배치/BUY_CUTOFF/매매 diff 0, 매수/청산
   잡 미복구, `execute_signal_trade` 미호출. 기존 SPEC-AI-080/082 테스트 무회귀.
6. **Priority Medium — 최소 간격/시각 근거 문서화 (REQ-013)**: gather 소요·크롤 부하 근거를 spec/plan에
   확정, MX NOTE로 스케줄 근거 기록.
7. **Priority Low — 관측성**: 재스캔 발화·same-day 서브지표 편입·이벤트 재스캔 트리거 로그 확인.

## 리스크 및 완화

| 리스크 | 영향 | 완화 |
|--------|------|------|
| 재스캔 간격 < gather 소요 겹침([R-1]) | 명목 고빈도, 실효 빈도 저하 | 간격 ~20분(정상 상단+헤드룸), coalesce로 미스파이어 접기, 근본 상향은 [X-6] 후속 |
| 크롤/CPU 부하 증가([R-2]) | 서버 자원 | 09:05~11:00 창 + 유계 간격, 예측 기록 모드라 매수 부하 없음 |
| 뉴스 재스캔 트리거 품질 미검증·precision 저하/LLM 예산([R-3]) | 지표 일시 하락, 트리거 정밀도 미검증(활성화만으로 커버리지는 보장) | 기존 가드 준수, staged rollout, 롤백=플래그 false, 자금 리스크 0, 활성화 후 발화 로그·precision 관측. 사용자 확인 완료(2026-07-21, 승인) |
| same-day 귀속 누락([R-4], 최상위) | recall 무변화(SPEC 무효) | REQ-005 P0 HARD, same-day 서브지표 편입을 acceptance 관찰 증거로 검증 |
| 비활성 매수/청산 잡 오복구([R-5]) | 예측 기록 모드 파손 | [X-3] 명시, 재스캔 콜백은 후보 생성만 호출, 코드 리뷰 게이트 |

## 검증 명령 (CLAUDE.local.md)

```bash
cd backend && uv run pytest tests/test_surge_ai083_intraday_rescan.py --tb=short -q
cd backend && uv run pytest tests/test_surge_ai080_fund_manager.py \
  tests/test_surge_ai082_gather_timeout.py --tb=short -q          # 인접 SPEC 무회귀
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"     # 전체 회귀
cd backend && uv run pytest tests/ --tb=short -q -m "not slow" -n 4 # 전체 회귀(xdist)
cd backend && uv run ruff check . && uv run mypy app/
```

**프로덕션 배포 후 검증**: 다음 거래일 09:10~10:55 재스캔 잡 로그 발생 확인 +
`surge_universe_members`/`surge_detector_contribution` 당일 비-0행 + same-day 서브지표에 당일 캐치
편입 + 이벤트 재스캔 발화 로그(고확신 뉴스 시). journalctl 검색은 ASCII 잡 id(예:
`surge_signal_generate_intraday`)로 수행.

## 선행/관계 SPEC

- **SPEC-AI-013(선행)**: 급등 시그널 독립 생성 잡 원 소유. 본 SPEC은 스케줄만 확장.
- **SPEC-AI-038(인접)**: 10:00 장중 재탐지 잡 도입. 본 SPEC은 그 단일 잡을 고빈도로 확장.
- **SPEC-AI-080(재사용·회귀 보호)**: same_day 지평 평가 경로 + 공시 즉시발화. 방향 A가 재사용, 방향 B가
  회귀 보호.
- **SPEC-AI-066(활성화 대상)**: 뉴스 이벤트 재스캔 인프라. 방향 B가 플래그 활성화.
- **SPEC-AI-079(참고 패턴)**: 구현된 기능의 설정 플립 + staged rollout.
- **SPEC-AI-082(제약 출처)**: gather 최대 20분. 재스캔 간격 설계 제약.
- **SPEC-AI-043(계승)**: 예측 기록 모드(매매 무변경).
