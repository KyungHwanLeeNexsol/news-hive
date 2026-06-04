# SPEC-AI-038: BEAR Threshold Cap, Volume Threshold 완화, 장중 재탐지

**Status**: DONE  
**Created**: 2026-06-04  
**Completed**: 2026-06-04  
**Branch**: main (직접 적용)

---

## 배경 및 동기

2026-06-04 운영 분석에서 발견된 3가지 미해결 문제:

1. **BEAR regime threshold 과도 상승**: win_rate=0.20 + BEAR×1.2 → threshold=0.60. 신규 combo 신호(0.24~0.28)가 전량 차단
2. **volume_zscore_threshold 2.5 기준 과엄격**: BEAR 시 3.0으로 올라가 combo 신호 미발화
3. **장 시작 전 1회 배치 한계**: 15:20 KST 1회만 → 당일 급등 실시간 감지 불가

추가로 SPEC-AI-037의 시총 하한 500억 확장 시 NULL 시총 1684건 포함으로 탐지기 timeout(550초+) 성능 회귀 발생.

---

## 요구사항

### REQ-038-001: volume_zscore_threshold 완화

- 기본값: 2.5 → **2.0**
- BEAR 오버라이드: 3.0 → **2.5** (BULL: 2.0 유지)
- 목적: combo 신호 감도 향상, BEAR에서도 거래량 이상 포착

### REQ-038-002: BEAR regime threshold 상한 설정

- `regime_multipliers.BEAR`: 1.2 → **1.05** (threshold 급등 방지)
- `final_clamp_max`: 0.85 → **0.65** (어떤 조건에서도 threshold ≤ 0.65)
- 기대 효과: BEAR + 저승률 조건에서 threshold 0.60 → **0.525**

### REQ-038-003: 10:00 KST 장중 재탐지 잡

- 스케줄러에 `surge_signal_generate_intraday` 잡 추가
- 시각: 평일 **10:00 KST** (BUY_CUTOFF 11:00보다 1시간 전)
- 10:30 execute_buys 잡이 당일 신규 시그널 수신 가능

### REQ-038-PF1~PF3: detect_theme_news_cluster 성능 패치

- **PF1**: NULL 시총 종목을 뉴스 창 내 언급된 종목만 포함 (2605건 → ~921건)
- **PF2**: theme_cluster_score < 0.10인 종목 가격 API 스킵 (사전 차단)
- **PF3**: 종목당 `_fetch_price_change_sync` 2회 → **0회** 통합 제거 (price_bonus=0.0 고정)
- 효과: 550초+ timeout → **17초 이하**

### REQ-038-PF4~PF5: volume_combo 탐지기 성능 패치

- **PF4**: `positive_news_stocks` 상위 50개 제한 (무제한 → 50개)
- **PF5**: `fetch_stock_price_history_sync` pages=3 → **pages=1** (종목당 3→1 HTTP 요청)
- 효과: 52초 → ~17초

---

## 구현 파일

| 파일 | 변경 내용 |
|------|---------|
| `backend/app/surge_config/surge_detection.yaml` | volume_zscore, BEAR multiplier, final_clamp_max 변경 |
| `backend/app/services/scheduler.py` | surge_signal_generate_intraday 잡 추가 |
| `backend/app/services/surge_detector.py` | NULL 시총 제거, 가격 API 제거, volume_combo 50개 상한, pages=1 |
| `backend/tests/test_surge_ai038.py` | 신규 9개 인수 테스트 (REQ-038-001~003) |
| `backend/tests/test_surge_ai029.py` | BEAR multiplier 1.2→1.05 반영 |
| `backend/tests/test_market_regime.py` | BEAR volume_zscore 3.0→2.5 반영 |
| `backend/tests/test_surge_scoring.py` | price_bonus 제거 반영 (TestPriceChangeBonus) |

---

## 수용 기준

- [x] AC-038-001: `cfg.volume_news_combo.volume_zscore_threshold == 2.0`
- [x] AC-038-002: BEAR regime threshold ≤ 0.65 (최악 조건에서도)
- [x] AC-038-003: `surge_signal_generate_intraday` 잡이 10:00 KST에 등록됨
- [x] AC-038-PF: detect_theme_news_cluster 실행 시간 < 60초 (목표 ~17초)

---

## 테스트 결과

```
tests/test_surge_ai038.py: 9/9 PASSED
tests/test_surge_ai029.py: 31/31 PASSED
tests/test_market_regime.py: 35/35 PASSED
tests/test_surge_scoring.py: 52/52 PASSED
tests/test_surge_detector.py: 22/22 PASSED
전체: 1387/1387 PASSED
```
