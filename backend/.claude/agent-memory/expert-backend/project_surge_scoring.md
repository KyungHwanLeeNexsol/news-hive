---
name: project-surge-scoring-spec-ai-014
description: SPEC-AI-014 급등 신호 스코어링 개선 구현 현황 — 종목 수준 개인화, 컨센서스 보너스, 가격 모멘텀 필터
metadata:
  type: project
---

SPEC-AI-014 구현 완료 (2026-05-18).

**Why:** 기존 detect_theme_news_cluster()가 모든 종목에 동일한 점수를 부여하는 문제와, 앙상블 스코어가 단일 탐지기 신호를 과대평가하는 문제를 해결.

**How to apply:** 이 SPEC의 변경사항은 surge_detector.py와 surge_trading_service.py에 반영됨. 후속 변경 시 하위 호환성 주의.

## 변경된 파일

1. `backend/app/surge_config/surge_detection.yaml` — ensemble 가중치 변경 (theme: 0.25→0.35, combo: 0.30→0.35, disclosure: 0.25→0.20, legacy: 0.20→0.10)
2. `backend/app/services/surge_detector.py` — REQ-001/002/003/004 구현
3. `backend/app/services/surge_trading_service.py` — REQ-005 구현, 단일 탐지기 임계값 0.40→0.30 완화
4. `backend/tests/test_surge_scoring.py` (신규) — T-001~T-011 단위 테스트
5. `backend/tests/test_surge_detector.py` (수정) — 새 가중치/컨센서스 배율에 맞게 기댓값 수정

## 주요 설계 결정

- `_price_change_provider`: 테스트 주입용 전역 변수. `_volume_provider` 패턴과 동일.
- `_fetch_price_change_sync()`: `_get_current_price_sync()` 패턴을 그대로 따름.
- 단일 탐지기 임계값: 0.40→0.30 완화 (컨센서스 보너스가 1.00이면 30% 신호도 허용).
- 가격 모멘텀 필터는 score threshold 통과 후 적용 (순서 중요).

## 테스트 결과

- test_surge_scoring.py: 26/26 통과
- test_surge_detector.py: 18/18 통과
- test_surge_trading.py: 39/40 통과 (1 실패는 `jose` 모듈 미설치 문제 — SPEC-AI-014 무관)
