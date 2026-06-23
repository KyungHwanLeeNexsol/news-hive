---
id: SPEC-AI-062
version: 0.1.0
status: completed
created: 2026-06-23
updated: 2026-06-23
author: manager-spec
priority: medium
issue_number: null
---

# SPEC-AI-062: 거래량 폭발 탐지기 (volume_breakout) 추가

## HISTORY

- 2026-06-23 (v0.1.0): 거래량 폭발 탐지기 신규 추가. Naver 거래량 순위 상위 100개 종목에서 20일 평균 대비 3배 이상 거래량 종목을 탐지. 7-탐지기 앙상블 구조로 전환. commit f6dfdea.

---

## Background

SPEC-AI-061 이후 앙상블에 weekend_gap_up(0.09) 고정 탐지기가 추가된 상태에서, 급등 직전 특징인 거래량 폭발 현상을 포착하는 전용 탐지기가 없었다. Naver 금융의 거래량 순위 API를 활용해 20일 평균 거래량 대비 3배 이상 급증 종목을 실시간 탐지하는 탐지기를 추가한다.

### 앙상블 가중치 변경 (6 → 7탐지기)

기존 6-탐지기 체계에서 volume_breakout(0.12) 신규 추가:

| 탐지기 | 이전 | 이후 |
|--------|------|------|
| theme_cluster | 0.25 | 0.22 |
| volume_news_combo | 0.32 | 0.28 |
| disclosure_pattern | 0.18 | 0.16 |
| news_delayed | 0.15 | 0.13 |
| weekend_gap_up | 0.10 | 0.09 |
| volume_breakout | — | **0.12** |
| legacy_detectors | 0.00 | 0.00 |

합계: 1.00 (변경 없음). `legacy_detectors`의 실효 가중치는 0으로 고정.

---

## Requirements

### REQ-VB-001: 거래량 순위 스크래핑

WHEN `detect_volume_breakout()` 실행 시
THE SYSTEM SHALL Naver 금융 거래량 순위(KOSPI + KOSDAQ) 상위 100개 종목 데이터를 수집한다.

### REQ-VB-002: 거래량 기준 필터링

WHEN 거래량 순위 데이터 수집 후
THE SYSTEM SHALL 20일 평균 거래량 대비 3배(`volume_ratio >= 3.0`) 이상인 종목만 `SurgeCandidate`로 반환한다.

### REQ-VB-003: 앙상블 통합

WHEN surge 탐지 앙상블 실행 시
THE SYSTEM SHALL `SurgeCandidate.volume_breakout_score` 필드를 통해 기존 앙상블과 통합하며, 가중치 0.12를 적용한다.

### REQ-VB-004: auto.yaml 호환성

WHEN `surge_auto_improver`가 앙상블 가중치 자동 개선 시
THE SYSTEM SHALL weekend_gap_up(0.09) + volume_breakout(0.12) = 0.21을 고정값으로 제외하고, 나머지 5개 탐지기의 합산 목표를 0.79로 유지한다.

### REQ-VB-005: 서버 auto.yaml 호환성

WHEN 신규 고정 탐지기 추가 후 서버 재배포 시
THE SYSTEM SHALL `surge_detection.auto.yaml`의 5탐지기 가중치 합계를 새 목표(0.79)에 맞게 비율 유지 스케일링해야 한다 (수동 조치 필요).

---

## Technical Approach

### 신규 함수

**`fetch_volume_leaders_sync(limit=100) -> list[dict]`** (`naver_finance.py`)
- Naver 거래량 순위 API 스크래핑 (KOSPI + KOSDAQ 합산)
- 반환: `[{"stock_code": str, "volume": int, "avg_volume_20d": int}, ...]`
- 실패 시 빈 리스트 반환 (fail-open)

**`detect_volume_breakout(db, config) -> list[SurgeCandidate]`** (`surge_detector.py`)
- `fetch_volume_leaders_sync()` 호출 후 `volume_ratio >= 3.0` 필터
- `SurgeCandidate.volume_breakout_score = min(volume_ratio / 5.0, 1.0)` 정규화

### 설정 클래스

**`VolumeBreakoutConfig`** (`surge_settings.py`)
- `enabled: bool = True`
- `weight: float = 0.12`
- `volume_ratio_threshold: float = 3.0`
- `max_candidates: int = 20`

### auto.yaml 수정 패턴

신규 고정 탐지기 추가 시 서버 `surge_detection.auto.yaml` 수동 조정 필요:
- 기존 5탐지기 합계를 새 `_wgu_target = 1.0 - fixed_weights`로 비율 유지 스케일
- 이번: 0.90 → 0.79 (weekend_gap_up 0.09 + volume_breakout 0.12 = 0.21 차감)

---

## Acceptance Criteria

- [x] `detect_volume_breakout()` 함수 구현 완료
- [x] `fetch_volume_leaders_sync()` Naver 스크래핑 함수 구현 완료
- [x] `SurgeCandidate.volume_breakout_score` 필드 추가
- [x] `VolumeBreakoutConfig` 설정 클래스 추가
- [x] 앙상블 가중치 7개 재배분 (합계 1.00 검증)
- [x] `surge_auto_improver._DETECTORS` 5개 합산 목표 0.79로 조정
- [x] 관련 테스트 6개 파일 1546개 전체 통과
- [x] ruff lint 통과
- [x] 서버 auto.yaml 호환성 복구 (수동 조치 완료)

---

## Implementation Notes

### 서버 배포 시 주의사항 (2026-06-23)

배포 후 서버 `surge_detection.auto.yaml` (gitignore 보호 파일)이 이전 5탐지기 합계 0.90을 유지하여 `1.11 = 0.90 + 0.09 + 0.12` 오류 발생. 서버에서 직접 Python 스크립트로 비율 유지 스케일다운 실행:

```
5탐지기 합계: 0.90 → 0.79 (비율 유지)
weekend_gap_up: 0.09 (고정)
volume_breakout: 0.12 (고정)
합계: 0.79 + 0.09 + 0.12 = 1.00 ✅
```

패턴: 신규 고정 탐지기 추가 시 서버 auto.yaml의 5탐지기 합계를 `1.0 - fixed_sum`으로 재조정 필요.
