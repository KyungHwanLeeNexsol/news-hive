# SPEC-AI-019: 급등 시그널 밸류에이션 필터 적용 범위 확장

## 개요

SPEC-AI-019 / SPEC-AI-018 Phase 3 적용 범위 확장

## 문제

SPEC-AI-018에서 도입한 밸류에이션 부적격 필터(PER > 500 또는 PBR > 30 종목 제외)가 `fund_manager.py`의 `_gather_leading_candidates()` 함수에만 적용되어 있다. 반면 SPEC-AI-013에서 분리된 전일 15:20 KST 독립 잡(`run_surge_signal_generation`)의 경로(Path B)에서는 해당 함수를 호출하지 않아 필터가 우회된다. 결과적으로 매일 15:20 잡이 생성하는 시그널 96건 중 극단 밸류에이션 종목이 포함될 가능성이 있다.

## 해결

Option A 채택: 탐지기 단계에서 per/pbr 데이터를 수집하고 `surge_detector` 모듈에 단일 지점 필터를 배치하여 모든 생성 경로가 동일한 필터를 통과하도록 통일. PER/PBR 데이터 추가 API 호출 없이 기존 시장 데이터 조회 경로에 piggy-back하여 수집.

## 변경 사항

### 코드 수정

- **SurgeCandidate 모델 확장** (REQ-AI019-001)
  - `per: float | None = None` 필드 추가 (기본값 None)
  - `pbr: float | None = None` 필드 추가 (기본값 None)

- **탐지기 단계 데이터 수집** (REQ-AI019-002)
  - `_extract_valuation(stock_code, market_data)` 헬퍼 함수 추가
  - KIS API 응답의 `per`/`pbr` 키를 `SurgeCandidate` 필드로 매핑
  - 추가 API 호출 0건 (KIS 캐시 재사용)

- **3개 탐지기에 piggy-back 수집** (REQ-AI019-002)
  - `detect_theme_cluster_candidates`: `_extract_valuation` 호출로 per/pbr 채우기
  - `detect_volume_news_combo_candidates`: 동일 패턴 적용
  - `detect_disclosure_pattern_candidates`: 동일 패턴 적용

- **단일 지점 밸류에이션 필터** (REQ-AI019-003, REQ-AI019-004, REQ-AI019-005)
  - `surge_detector.detect_surge_candidates()` 내부에 @MX:ANCHOR 필터 블록 추가
  - `ValuationDisqualifiersConfig`에서 `max_per=500, max_pbr=30` 로드
  - 필터 조건: `per > max_per OR pbr > max_pbr` 이면 제외
  - None/0 값은 통과 규칙 유지 (SPEC-AI-018 호환)

- **중복 필터 제거** (REQ-AI019-006)
  - `fund_manager.py:1707-1724` 중복 valuation 필터 블록 제거
  - Single Source of Truth를 `surge_detector`로 통일

### 테스트

- **신규 단위 테스트 32건 작성** (REQ-AI019-009)
  - `test_surge_ai019_path_b.py`: 17건 (Path B 경로 검증)
    - PER > 500 제외 테스트
    - PBR > 30 제외 테스트
    - PER=None 통과 테스트
    - 정상값 통과 테스트
    - Path A/B 동등성 검증
    - 경계값 검증 (PER=500 정확히, PBR=30 정확히)
    - piggy-back 호출 카운트 검증
  - `test_surge_ai019_characterization.py`: 15건 (dataclass 호환성, 기존 동작 보존)

### 회귀 검증

- SPEC-AI-018 회귀 테스트: 36건 모두 통과
- 전체 테스트 슈트: 1112개 통과 (기존 + 신규 포함)
- LSP/linting/type 검사: 통과

## 영향 범위

### 운영 영향

- **매 영업일 15:20 KST 잡이 생성하는 시그널 96건/일에서 PER>500 또는 PBR>30 종목 자동 제외**
- 다음 날 09:00 KST `surge_execute_buys` 잡이 소비하는 시그널의 품질 향상
- 극단 밸류에이션 종목의 모의 매수 실행 차단

### 코드 영향

- `SurgeCandidate` dataclass 스키마 변경 (호환 필드 추가, 기본값 지원)
- `surge_detector.detect_surge_candidates()` 필터 로직 추가 (기존 코드 보존)
- `fund_manager._gather_leading_candidates()` 중복 코드 제거 (기능 이상 없음)

## 테스트 결과

### 신규 테스트 (32건)

| 파일 | 케이스 | 결과 |
|------|--------|------|
| test_surge_ai019_path_b.py | 17 | PASSED ✓ |
| test_surge_ai019_characterization.py | 15 | PASSED ✓ |

### 회귀 테스트

| 대상 | 결과 |
|------|------|
| test_surge_ai018.py (36 case) | 36/36 PASSED ✓ |
| test_surge_detector.py | PASSED ✓ |
| test_surge_scoring.py | PASSED ✓ |
| 전체 슈트 (1112+) | 1112 PASSED ✓ |

## 관련 SPEC

- **SPEC-AI-018**: 급등 예측 신호 품질 개선 (Phase 3 밸류에이션 필터 도입)
  - 선행 SPEC, Phase 3 도입의 적용 범위 한정성 발견
  - 본 SPEC에서 REQ-AI018-006 ~ REQ-AI018-008 적용 범위 확장

- **SPEC-AI-013**: 급등 시그널 생성을 전일 15:20 KST 독립 잡으로 분리
  - 선행 SPEC, Path B(15:20 잡) 분리 도입
  - 본 SPEC에서 Path B의 누락된 필터링 복구

---

🗿 MoAI <email@mo.ai.kr>
