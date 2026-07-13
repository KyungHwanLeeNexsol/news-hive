---
id: SPEC-AI-079
version: 0.1.0
status: draft
created: 2026-07-13
updated: 2026-07-13
author: Nexsol
priority: Medium
issue_number: null
---

# SPEC-AI-079: volume_breakout 상대임계(z-score) 확장 기능 활성화

## HISTORY

- 2026-07-13 (v0.1.0): draft 생성. SPEC-AI-066에서 이미 구현·테스트가 완료된
  `volume_breakout.relative_threshold_enabled` 기능을 프로덕션에서 최초 활성화.
  research.md의 코드/설정/테스트 주장 전량 검증 완료(설정 키 경로, 테스트 파일 존재,
  Pydantic 기본값과 YAML 값의 분리, 리더 유니버스 크기 정정 포함).

---

## 1. Overview (개요)

`detect_volume_breakout()`(`backend/app/services/surge_detector.py:3955`)는 급등 탐지기
8종 중 **유일하게 뉴스 기사나 공시 없이도 발화할 수 있는** 텍스트-무관 탐지기다. 그러나
현재 이 탐지기는 후보를 절대 거래량 리더 유니버스(`fetch_volume_leaders_sync(limit=cfg.max_candidates // 2)`
= 상위 50) 안에서만 찾고, 고정 3.0배 비율 조건을 요구한다. 이 때문에 **뉴스/공시 커버리지가
있는데도 절대 거래량 순위 밖이라는 이유만으로** 급등 종목을 놓친다.

SPEC-AI-066(REQ-AI066-005)은 이 문제를 해결하기 위해 이미:
1. 촉매 유니버스 확장 헬퍼 `_fetch_volume_breakout_catalyst_universe()`(`:3905`) — 당일/밤새
   공시 또는 최근 뉴스 커버리지가 있는 종목을 절대 거래량 순위 밖이어도 후보군에 합류,
2. 종목별 자기 20일 거래량 히스토리 기준 z-score >= 2.0 상대 임계 경로(`:4027-4033`) —
   고정 3.0배 비율에 못 미쳐도 자기 대비 이상치면 후보 인정
을 구현하고, 전용 테스트 스위트(`backend/tests/test_surge_ai066.py`의
`TestVolumeBreakoutRelative`)까지 작성했다.

그러나 이 기능은 `surge_detection.yaml`의 `volume_breakout.relative_threshold_enabled: false`
(`:217`, staged rollout 기본값)로 인해 **구현 이후 프로덕션에서 한 번도 가동된 적이 없다.**

본 SPEC은 **로직을 새로 구현하지 않는다.** SPEC-AI-066에서 완성·검증된 기능의 **활성화
스위치(설정 1줄)만 켜고**, 그 전환이 안전함(기존 테스트 무회귀)을 검증한다.

### 실증 사례 (2026-07-13)

에넥스(011090)는 당일 00:26 KST에 관련 뉴스("가구 뺀 에넥스, '1인·시니어 웰니스'로 승부수")가
이미 DB에 존재했으나, `relative_threshold_enabled=false`로 촉매 유니버스 확장 경로 자체가
실행되지 않아 절대 거래량 순위 밖이라는 이유로 후보에서 탈락했다. 실제 그날 종가 기준 +19.77% 상승.

---

## 2. Environment & Assumptions (환경 및 가정)

검증 완료(2026-07-13, 코드 read-only 확인):

- [E-1] 설정 키 경로 확정: `backend/app/surge_config/surge_detection.yaml`의
  `volume_breakout.relative_threshold_enabled`(`:217`), 현재 값 `false`.
- [E-2] 대상 로직은 이미 존재하며 이 플래그로만 게이팅된다:
  - 촉매 유니버스 확장: `surge_detector.py:3983-3990`(`if cfg.relative_threshold_enabled:`)
  - z-score 상대 임계: `surge_detector.py:4027-4033`(`if cfg.relative_threshold_enabled and not qualifies_flat:`)
  - z-score 임계 상수: `_VB_RELATIVE_Z_THRESHOLD = 2.0`(`:3879`)
- [E-3] 전용 테스트 스위트 `backend/tests/test_surge_ai066.py` 존재.
  `TestVolumeBreakoutRelative`가 플래그 True/False 두 경로를 모두 커버하며, 각 테스트가
  `vb_overrides`로 플래그를 **명시적으로 주입**한다(YAML 기본값에 의존하지 않음).
- [E-4] **[가정 → 검증됨] Pydantic 모델 기본값과 YAML 값은 별개다.**
  `VolumeBreakoutConfig.relative_threshold_enabled: bool = False`(`surge_settings.py:142`)는
  YAML 부재 시 폴백 기본값이고, `test_surge_ai066.py:223`
  (`test_new_fields_on_existing_configs`)이 이 **모델 기본값이 False임을 단언**한다.
  따라서 본 SPEC은 **YAML 런타임 값만** true로 바꾸고 **Pydantic 모델 기본값은 False로 유지**한다.
  (모델 기본값까지 바꾸면 해당 테스트가 깨진다.)
- [E-5] **[research.md 정정] 리더 유니버스 크기.** research.md는 "절대 거래량 상위 100~173위"로
  기술했으나, 실제 코드는 `fetch_volume_leaders_sync(limit=cfg.max_candidates // 2)` = **상위 50**을
  가져오고, 촉매 확장 후 `[: cfg.max_candidates]` = **100 상한**으로 절단한다(`:3975`, `:3987`).
  본 SPEC의 요구사항은 이 정정된 수치를 기준으로 한다.
- [E-6] 실매매 실행은 비활성(예측 기록 모드, SPEC-AI-043). 본 변경으로 자금 리스크 없음.

가정:
- [A-1] SPEC-AI-066에서 구현된 로직은 정확하며 재구현이 불필요하다(전용 테스트가 이를 뒷받침).
- [A-2] 촉매 유니버스 확장이 조회하는 Disclosure/NewsStockRelation 부하는 SPEC-AI-066 설계
  시점에 이미 고려된 것으로, 신규 성능 리스크는 낮다.

---

## 3. Requirements (EARS)

### REQ-AI079-001 (Ubiquitous, P0) — 활성화

프로덕션 급등 탐지 설정(`surge_detection.yaml`)은 `volume_breakout.relative_threshold_enabled`를
**`true`로 설정** SHALL 한다.

- 근거: SPEC-AI-066 REQ-AI066-005의 catalyst-universe 확장 + z-score 상대 임계 경로를 프로덕션에서 가동.

### REQ-AI079-002 (Event-Driven, P0) — 확장 경로 실행

**WHEN** `detect_volume_breakout()`이 프로덕션 설정으로 실행되면, 시스템은:
1. 절대 거래량 리더 유니버스 밖이라도 **당일/밤새 공시 또는 최근 뉴스 커버리지가 있는 촉매
   종목을 후보 유니버스에 합류**(`_fetch_volume_breakout_catalyst_universe`, `max_candidates`=100 상한)
2. 고정 `volume_ratio_threshold`(3.0배) 미달이라도 **종목 자기 20일 거래량 z-score >= 2.0(`_VB_RELATIVE_Z_THRESHOLD`)이면
   후보로 인정**
SHALL 한다.

- 표본 부족(cold-start, `sample_count < zscore_min_baseline_samples`)이면 z-score가 None →
  고정 3.0배 폴백으로 회귀 없이 동작 SHALL 한다.

### REQ-AI079-003 (Unwanted, P0) — 범위 봉쇄

이 활성화는 다음을 **변경하지 않아야** SHALL NOT 한다:
- `VolumeBreakoutConfig.relative_threshold_enabled`의 **Pydantic 모델 기본값**(`surge_settings.py:142`,
  `= False` 유지 — YAML 런타임 값만 변경)
- volume_breakout의 기타 임계값: `volume_ratio_threshold`(3.0), `max_candidates`(100),
  `baseline_days`(20), `min_history_days`(10), `confidence_denominator`(8.0), `max_score`(0.50),
  `volume_breakout_bypass_threshold`(0.30)
- AI-062 앙상블 가중치(`ensemble.weights.volume_breakout` = 0.11)
- AI-063 단독 bypass 경로
- 다른 어떤 탐지기의 로직, SPEC-AI-078의 Pool A 정렬 작업, 앙상블/임계/발신/매매 로직

### REQ-AI079-004 (State-Driven, P0) — 무회귀 검증

**WHILE** 플래그가 활성화된 상태에서, 백엔드 전체 회귀 스위트 — 특히
`test_surge_ai066.py`의 `TestVolumeBreakoutRelative`(True/False 양경로)와
`test_new_fields_on_existing_configs`(모델 기본값=False 단언) — 는 **전량 통과** SHALL 한다.

- 검증 명령: `cd backend && uv run pytest tests/test_surge_ai066.py --tb=short -q`
- 전체 회귀: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`

### REQ-AI079-005 (Optional, P2) — 관측성 (nice-to-have)

**WHERE** 활성화 이후 신호량 변화 관측이 필요한 경우, 시스템은 z-score 경로로 유입된 후보
(`qualifies_relative=True`)와 고정 3.0배 경로 후보(`qualifies_relative=False`)를 **구분하는
INFO 레벨 요약 로그**를 방출 MAY 한다.

- 현황: `[거래량폭발] 촉매 종목 N개 유니버스 합류`(INFO, `:3988`)와
  `[거래량폭발] N개 후보 탐지`(INFO, `:4059`)는 존재하나, z-score-vs-flat 구분은
  **DEBUG 레벨(`:4048`, `rel=%s`)에만** 있어 프로덕션(INFO)에서 보이지 않는다.
- 권장 구현 범위(과설계 금지): 스캔당 **집계 1줄** INFO 로그(예: `z-score 경로 X / flat 경로 Y`).
  **신규 테이블/컬럼/마이그레이션 금지, 종목별 INFO 스팸 금지.**
- 본 REQ는 P2 optional이며 활성화(001~004)의 blocker가 아니다.

---

## 4. Exclusions (What NOT to Build)

본 SPEC은 다음을 **명시적으로 범위에서 제외**한다:

- [X-1] **신규 탐지기 로직 구현 금지.** 기능 본체는 SPEC-AI-066이 소유·구현·테스트 완료.
  본 SPEC은 활성화 스위치만 켠다.
- [X-2] volume_breakout의 다른 임계값 변경 금지: `volume_ratio_threshold`(3.0),
  `max_candidates`(100), `baseline_days`(20), `min_history_days`(10),
  `confidence_denominator`(8.0), `max_score`(0.50), `volume_breakout_bypass_threshold`(0.30).
- [X-3] `_VB_RELATIVE_Z_THRESHOLD`(2.0) 값 변경 금지.
- [X-4] `VolumeBreakoutConfig`의 Pydantic 모델 기본값(`= False`) 변경 금지 — YAML 런타임 값만 변경.
- [X-5] SPEC-AI-078의 Pool A 정렬 작업 변경 금지(별개 영역).
- [X-6] 다른 어떤 탐지기, 앙상블 가중치(AI-062), bypass 경로(AI-063), 적응형 임계(AI-029/038),
  발신 게이팅, 매매 로직(AI-043 예측 기록 모드 유지) 변경 금지.
- [X-7] 신규 테이블/컬럼/마이그레이션 금지. 과거 데이터 백필 금지.
- [X-8] (P2 관측성 채택 시에도) 종목별 INFO 로그·신규 스키마·영속 지표 저장 금지 —
  스캔당 집계 1줄 INFO로 제한.

---

## 5. Risks (리스크)

- [R-1] **오탐(false positive) 증가 → precision 저하 가능성.** 후보 유니버스가 넓어지므로
  surge_candidate 신호 수가 늘어날 것으로 예상된다. recall 개선이 기대되지만 precision이
  일시 하락할 수 있다. **자금 리스크는 없음**(실매매 비활성, 예측 기록 모드, SPEC-AI-043).
  완화: REQ-AI079-005 관측성으로 활성화 후 며칠간 신호량/구성 변화를 관찰하고, 필요 시
  후속 SPEC에서 임계 조정(본 SPEC 범위 밖).
- [R-2] **성능.** `_fetch_volume_breakout_catalyst_universe()`가 Disclosure/NewsStockRelation
  추가 조회. SPEC-AI-066 설계 시점에 이미 반영된 경로이며, 신규 리스크 낮음.
- [R-3] **회귀.** `test_surge_ai066.py`가 이미 True/False 양경로를 커버 → 플래그 on 상태의
  회귀 가드로 재사용. 낮음.

---

## 6. Related SPECs (관련 SPEC)

- **SPEC-AI-066 (선행/소유, prerequisite)**: `relative_threshold_enabled` 기능 자체의
  설계·구현·테스트 소유. 본 SPEC은 **활성화 상태 전환만** 다루며 로직 재구현 없음.
- **SPEC-AI-062**: volume_breakout 탐지기 추가 및 앙상블 가중치(0.11) 소유 — 불변.
- **SPEC-AI-063**: volume_breakout 단독 bypass 경로(임계 0.30) 소유 — 불변.
- **SPEC-AI-065**: z-score 정규화 인프라(`surge_baseline_service`) 및 스캔 유니버스 원칙 소유 — 재사용만.
- **SPEC-AI-078 (관련, 별개)**: Pool A 정렬 수정(그림자 유니버스/평가 지표). 본 SPEC은 실제
  탐지기 동작(volume_breakout)을 바꾸는 것이라 성격이 다르며 상호 독립.
- **SPEC-AI-043**: 예측 기록(비-실매매) 모드 — 유지.
