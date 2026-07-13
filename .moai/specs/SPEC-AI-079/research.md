# Research: SPEC-AI-079 — volume_breakout 상대임계(z-score) 확장 기능 활성화

## 배경

[[project_systemic_prediction_gap_2026_07_13]] 심층조사에서 확정: 급등예측 recall 저조의 핵심 원인 중
하나는 `detect_volume_breakout()`이 유일하게 텍스트(공시/뉴스) 무관 탐지기인데도 절대거래량 상위
100~173위 안에서만 후보를 찾는다는 것. 이 문제를 풀기 위해 SPEC-AI-066에서 이미
`relative_threshold_enabled` 기능을 만들고 전용 테스트(`test_surge_ai066.py`)까지 작성했으나,
`surge_detection.yaml` 기본값이 `false`로 남아 프로덕션에서 한 번도 가동된 적이 없다.

## 현재 코드 상태 (2026-07-13 확인)

`backend/app/services/surge_detector.py`:

- `_VB_RELATIVE_Z_THRESHOLD = 2.0` (line 3879)
- `_fetch_volume_breakout_catalyst_universe()` (line 3905-3952): 당일 공시 또는 최근 뉴스 커버리지가
  있는 종목을 절대거래량 순위 밖이어도 후보군에 합류시킴 (`config.disclosure_pattern.disclosure_window_hours`,
  `config.volume_news_combo.news_window_hours` 재사용)
- `detect_volume_breakout()` (line 3955-):
  - `cfg.relative_threshold_enabled`가 true일 때만 촉매 유니버스 확장 실행 (line 3983-3990)
  - 종목별 z-score(자기 자신의 20일 거래량 히스토리 기준) >= 2.0이면 고정 3.0배 비율 없이도 후보 인정
    (line 4027-4033)

`backend/app/surge_config/surge_detection.yaml`:
```yaml
volume_breakout:
  ...
  relative_threshold_enabled: false  # SPEC-AI-066 REQ-AI066-005, 기본 false, staged rollout
```

## 실증 사례 (2026-07-13)

에넥스(011090)가 오늘 00:26 KST에 관련 뉴스("가구 뺀 에넥스, '1인·시니어 웰니스'로 승부수")가 이미
DB에 존재했음에도, `relative_threshold_enabled=false`라 촉매 유니버스 확장 경로 자체가 실행되지 않아
절대거래량 순위 밖이라는 이유만으로 후보에서 탈락. 실제 그날 종가 기준 +19.77% 상승.

## 리스크

- **오탐(false positive) 증가**: 후보군이 넓어지므로 surge_candidate 시그널 수가 늘어날 것으로 예상됨.
  precision 저하 가능성 — 다만 실매매는 비활성(예측 기록 모드)이라 자금 리스크는 없음.
- **성능**: `_fetch_volume_breakout_catalyst_universe()`가 Disclosure/NewsStockRelation을 추가 조회 —
  이미 SPEC-AI-066 구현 시점에 설계된 것이라 신규 성능 리스크는 낮음.
- **회귀**: `test_surge_ai066.py`가 이미 이 기능을 커버 — 토글 on 상태에서의 회귀 테스트로 재사용 가능.

## 제안 범위

1. `surge_detection.yaml`의 `volume_breakout.relative_threshold_enabled`를 `true`로 변경 (설정 1줄)
2. `test_surge_ai066.py` + 관련 회귀 스위트(`test_spec_ai_065.py`, volume_breakout 관련 테스트) 전량 통과 확인
3. 관측성: 오늘 활성화 이후 며칠간 surge_candidate 신호 수/구성(z-score 경로로 유입된 종목 비율) 변화를
   `[거래량폭발]` 로그로 관찰 가능한지 확인(이미 line 3988 로그 존재 — 신규 로깅 불필요할 수 있음)

## 관련 SPEC

- **SPEC-AI-066**(선행): 이 기능 자체의 설계·구현·테스트 소유. 본 SPEC은 활성화(설정값 변경)만 다룸,
  로직 재구현 없음.
- **SPEC-AI-078**(관련, 별개): Pool A 정렬 수정 — evaluation 지표 개선. 본 SPEC은 실제 탐지기 동작을
  바꾸는 것이라 SPEC-AI-078과 성격이 다름(그림자 유니버스 vs 실제 탐지기).
