---
id: SPEC-AI-005
type: plan
version: 1.0.0
created: 2026-04-05
---

# SPEC-AI-005 구현 계획: 동적 목표가/손절가 계산 시스템

## 1. 마일스톤

### Primary Goal: ATR 기반 동적 계산 엔진 + AI 프롬프트 개선

**대상 요구사항**: REQ-TPSL-001~006

**구현 항목**:

1. `technical_indicators.py`에 `calculate_atr()` 함수 추가
   - True Range 계산: `max(high-low, abs(high-prev_close), abs(low-prev_close))`
   - 14일 기간 SMA 기반 ATR (Wilder's smoothing)
   - 입력: `list[dict]` (high, low, close), 반환: `float`

2. 새 서비스 `backend/app/services/dynamic_tp_sl.py` 생성
   - `calculate_dynamic_tp_sl()`: ATR 조회 -> confidence 배수 조정 -> TP/SL 반환
   - `naver_finance.py`에서 20일 가격 데이터 조회
   - ATR 불가 시 섹터 기본값 폴백 로직

3. `paper_trading.py` 수정
   - 라인 33-34: `DEFAULT_TARGET_PCT/DEFAULT_STOP_LOSS_PCT` 상수는 유지하되, 실제 사용처에서 `dynamic_tp_sl` 호출로 대체
   - 라인 199-200: `signal.target_price or dynamic_tp_sl.calculate_dynamic_tp_sl(...)["target_price"]`
   - 라인 280-281: 동일 패턴 적용

4. `fund_manager.py` AI 프롬프트 개선
   - 라인 1658-1659: Few-shot 예시 2개 추가
     - 예시 1: "현재가 50,000원 -> target_price: 55,000, stop_loss: 47,500"
     - 예시 2: "현재가 12,300원 -> target_price: 14,000, stop_loss: 11,500"
   - 라인 2168: 규칙 7번을 "target_price와 stop_loss는 반드시 0이 아닌 구체적 정수로 기입. null/0 금지."로 변경
   - 라인 1687-1688: 폴백 시 `dynamic_tp_sl` 호출 + `tp_sl_method` 설정

5. Alembic 마이그레이션
   - `fund_signals` 테이블에 `tp_sl_method VARCHAR(20) DEFAULT 'legacy_fixed'` 추가

**수정 파일 목록**:
- `backend/app/services/technical_indicators.py` (ATR 함수 추가)
- `backend/app/services/dynamic_tp_sl.py` (신규 생성)
- `backend/app/services/paper_trading.py` (동적 TP/SL 호출로 변경)
- `backend/app/services/fund_manager.py` (프롬프트 개선 + 폴백 수정)
- `backend/alembic/versions/xxx_add_tp_sl_method.py` (마이그레이션)
- `backend/app/models/` (FundSignal 모델에 tp_sl_method 필드 추가)

---

### Secondary Goal: Confidence 조정 + 섹터 기본값

**대상 요구사항**: REQ-TPSL-007~011

**구현 항목**:

1. `dynamic_tp_sl.py`에 confidence 기반 배수 조정 로직 추가
   - `confidence >= 0.8`: `atr_target_mult=2.5, atr_stop_mult=1.0`
   - `0.5 <= confidence < 0.8`: `atr_target_mult=2.0, atr_stop_mult=1.5` (기본)
   - `confidence < 0.5`: `atr_target_mult=1.5, atr_stop_mult=2.0`

2. 섹터 변동성 프로파일 매핑 구현
   - `get_sector_defaults(sector_id)` 함수
   - 섹터-카테고리 매핑 테이블 (코드 내 dict 또는 DB 설정)
   - 5개 카테고리: 고변동성/중고변동성/중변동성/저변동성/기타

**수정 파일 목록**:
- `backend/app/services/dynamic_tp_sl.py` (confidence 로직 + 섹터 매핑)

---

### Tertiary Goal: 트레일링 스톱

**대상 요구사항**: REQ-TPSL-012~014

**구현 항목**:

1. `virtual_trades` 테이블 확장 (마이그레이션)
   - `trailing_stop_active BOOLEAN DEFAULT FALSE`
   - `trailing_stop_price INT`
   - `high_water_mark INT`

2. `paper_trading.py` 포지션 체크 로직에 트레일링 스톱 추가
   - `_check_positions()` 또는 동등 함수에서:
     - 수익률 >= +5%이면 `trailing_stop_active = True`
     - `high_water_mark = max(high_water_mark, current_price)`
     - `trailing_stop_price = high_water_mark - (ATR * 1.5)`
     - 단조 증가 보장: `new_trailing_stop = max(old_trailing_stop, calculated_trailing_stop)`
     - 현재가 <= trailing_stop_price이면 매도 실행

3. `dynamic_tp_sl.py`에 트레일링 스톱 유틸 함수 추가
   - `calculate_trailing_stop(high_water_mark, atr)`
   - `should_activate_trailing_stop(entry_price, current_price)`

**수정 파일 목록**:
- `backend/alembic/versions/xxx_add_trailing_stop.py` (마이그레이션)
- `backend/app/models/` (VirtualTrade 모델 필드 추가)
- `backend/app/services/paper_trading.py` (트레일링 스톱 로직)
- `backend/app/services/dynamic_tp_sl.py` (유틸 함수)

---

### Optional Goal: 백테스트 + 기존 포지션 마이그레이션

**대상 요구사항**: REQ-TPSL-015~018

**구현 항목**:

1. 백테스트 API 엔드포인트
   - `/api/v1/portfolio/tp-sl-backtest`: 기존 시그널 데이터로 고정 vs 동적 성과 비교
   - `/api/v1/portfolio/tp-sl-stats`: 방식별 성과 통계
   - 기존 `signal_verifier.py` 패턴 참고하여 구현

2. 기존 포지션 마이그레이션 스케줄러 작업
   - `tp_sl_method IS NULL OR tp_sl_method = 'legacy_fixed'`인 활성 포지션 조회
   - ATR 기반 재계산 (단, `tp_sl_method = 'ai_provided'`는 제외)
   - 일회성 실행 후 완료

**수정 파일 목록**:
- `backend/app/api/v1/portfolio.py` (새 엔드포인트)
- `backend/app/services/paper_trading.py` (마이그레이션 함수)
- `backend/app/services/dynamic_tp_sl.py` (백테스트 비교 로직)

---

## 2. 기술적 접근 방식

### 아키텍처 설계 방향

```
FundSignal 생성
    |
    v
AI가 target_price 반환?
    |--- YES --> tp_sl_method = "ai_provided" (그대로 사용)
    |--- NO ---> ATR 계산 가능?
                    |--- YES --> confidence 기반 배수 적용 -> tp_sl_method = "atr_fallback"
                    |--- NO ---> 섹터 기본값 적용 -> tp_sl_method = "sector_default"
```

### 핵심 설계 결정

1. **ATR 캐싱**: 동일 종목의 ATR을 동일 거래일 내에서 반복 계산하지 않도록 메모리 캐시 적용 (단순 dict, TTL 1시간)
2. **하위 호환성**: 기존 `DEFAULT_TARGET_PCT`/`DEFAULT_STOP_LOSS_PCT` 상수는 삭제하지 않고, `sector_default` 중 "기타" 카테고리의 기본값으로 유지
3. **트레일링 스톱 주기**: 기존 포지션 체크 스케줄러 주기에서 함께 실행 (별도 스케줄러 불필요)

---

## 3. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|-------|------|------|
| `naver_finance.py`에서 20일 가격 데이터 조회 불가 | ATR 계산 실패 | 섹터 기본값 폴백으로 graceful degradation |
| AI 프롬프트 개선 후에도 반환율 낮음 | ATR 폴백에 지속 의존 | `tp_sl_method` 통계로 모니터링, 추가 프롬프트 개선 반복 |
| ATR 배수(2.0/1.5)가 한국 시장에 부적합 | 과도하거나 부족한 TP/SL | 백테스트 결과로 배수 파라미터 튜닝 |
| 트레일링 스톱 +5% 기준이 너무 빠름/느림 | 조기/지연 활성화 | 백테스트 결과로 활성화 기준 조정 |

---

## 4. 의존성

- `naver_finance.py`의 과거 가격 조회 함수가 고가/저가/종가를 반환해야 함 (현재 종가만 반환 시 확장 필요)
- `sectors` 테이블에 섹터 카테고리 매핑 가능해야 함 (섹터명 기반 매핑)
- SPEC-AI-004의 `disclosure_impact` 시그널도 동적 TP/SL 적용 대상 (통합 시점 조율 필요)
