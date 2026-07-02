# SPEC-AI-068 구현 계획 (plan.md)

## 목표

평가지표를 **Scannable Recall(알고리즘 품질)** 과 **Coverage(유니버스 설계 품질)** 로 분리하고,
그 계산에 필요한 **스캔 유니버스 종목코드 영속화 + 급등 유형 라벨링** 진단 인프라를 구축한다.
이 SPEC은 후속 SPEC-AI-069(자동개선 재타게팅)와 전체 급등 개선의 **측정 기반**이다.

## 기술 접근 (Technical Approach)

### 1. 유니버스 코드 영속화 (REQ-001)
- **결정 필요(RUN 단계)**: (A) `SurgeUniversePoolHistory`에 JSON 컬럼(`member_codes_json`)
  추가 vs (B) 신규 자식 테이블 `surge_universe_members(trading_date, stock_code, entry_pool)`.
  - 권장: (B) 정규화 테이블 — 사후 조인(FundSignal→Stock, SurgeActualOutcome) 및 풀별 집계에 유리.
- 기록 지점: `build_scan_universe`(`surge_detector.py:3960`) 호출 직후, 유니버스 확정 결과를
  기존 pool_counts 저장 경로와 동일 트랜잭션에서 upsert.
- 개수 컬럼(`pool_a/b/c_count`, `scan_universe_size`)은 하위호환 유지.

### 2. 지표 컬럼 추가 (REQ-002/003)
- `SurgePredictionEvaluation`(`surge_prediction_evaluation.py`)에 컬럼 추가:
  `scannable_recall FLOAT NULL`, `coverage FLOAT NULL`,
  `scannable_actual_count INT`, `total_actual_count INT`.
- Alembic 마이그레이션 1건 — `down_revision`은 RUN 단계에서 실제 head 재확인 후 설정
  (AI-065가 063 추가했으므로 그 이후 head).

### 3. 평가 로직 재작성 (REQ-002/003/004)
- 대상: `surge_evaluation_service.py` `evaluate_surge_predictions`(:515~566 영역).
- 절차:
  1. `actual_set` = SurgeActualOutcome(was_surge) — **전체 실제급등주**(현행 유지, Coverage 분모).
  2. `universe_set` = REQ-001 영속화 종목코드(T-1).
  3. `scannable_actual = actual_set ∩ universe_set`.
  4. `predicted_set` = T-1 surge_candidate 시그널(현행 :515-526).
  5. `scannable_recall = |scannable_actual ∩ predicted_set| / |scannable_actual|` (0분모→null).
  6. `coverage = |scannable_actual| / |actual_set|`.
  7. 기존 단일 `recall`은 Scannable Recall로 의미 전환, 시장전체 수치는 `coverage`로 재라벨.
- **:531-535 거짓 전제 주석 제거** + 유니버스 교집합 기반으로 분모 교정(REQ-004).

### 4. 유형 라벨링 (REQ-005)
- `scannable_actual`에 속하면 `surge_type="scannable"`, 아니면 `"non_scannable"`.
- 저장: SurgeActualOutcome에 `surge_type` 컬럼 추가(위 마이그레이션에 병합) 또는 평가 결과
  per-stock JSON에 기록(AI-060 `per_stock_analysis_json` 관례 재사용 검토).
- 트랙 경계는 문서(본 SPEC) + 코드 주석(@MX:NOTE)으로 명문화, 파이프라인 미구현.

## 파일 영향 범위 (예상)

| 파일 | 변경 유형 | 근거 |
|------|----------|------|
| `backend/app/models/surge_universe_pool_history.py` 또는 신규 `surge_universe_members.py` | 확장/신규 | REQ-001 |
| `backend/app/models/surge_prediction_evaluation.py` | 컬럼 추가 | REQ-002/003 |
| `backend/app/services/surge_detector.py` (build_scan_universe 호출부) | 기록 훅 추가 | REQ-001 |
| `backend/app/services/surge_evaluation_service.py` (:515~566) | 로직 재작성 | REQ-002/003/004/005 |
| `backend/alembic/versions/0XX_*.py` | 신규 마이그레이션 | 컬럼/테이블 |
| `backend/tests/test_surge_evaluation*.py` 등 | 테스트 추가/수정 | 지표 검증 |

## 마일스톤 (우선순위 기반, 시간 추정 없음)

- **M1 (P0)**: 마이그레이션 + 모델 확장(REQ-001 테이블/컬럼, REQ-002/003 컬럼). 스키마 선착.
- **M2 (P0)**: `build_scan_universe` 기록 훅 — 유니버스 코드 영속화 활성(REQ-001).
- **M3 (P0)**: 평가 로직 재작성 — Scannable Recall/Coverage 계산 + 거짓 전제 제거(REQ-002/003/004).
- **M4 (P1)**: 유형 라벨링 + 트랙 경계 명문화(REQ-005).
- **M5 (P0)**: 테스트(단위/특성화) + 전체 급등 스위트 회귀 확인 + 린트/타입.

## 리스크 & 완화

- **과거 데이터 백필 불가**: 유니버스 코드가 없던 과거는 Scannable Recall `null`. 완화: 신규
  수집 시점부터 전향적으로 축적, 과거는 coverage-미상 표기(REQ-004).
- **평가 잡 트랜잭션 안전성**: AI-061이 이미 core eval을 optional 블록보다 먼저 commit하도록
  강화. 신규 지표 계산은 core eval 내부에 두되, 예외 시 지표만 null로 두고 잡 전체를 죽이지 않음.
- **유니버스-정답 조인 키**: FundSignal은 stock_code 직접 컬럼 없음 → Stock 조인 필수.
  SurgeActualOutcome/유니버스 멤버는 stock_code 보유. 조인 경로 일관성 검증.

## 검증 방법

- 특정 거래일에 대해: 유니버스 코드 집합, scannable_actual, predicted를 로그로 덤프하고
  손계산과 대조하여 Scannable Recall/Coverage 정합성 확인.
- 회귀: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 통과.
- 예측기록 모드 불변: 매수/포트폴리오 관련 파일 diff 0.

## 롤백 전략

- 신규 컬럼/테이블은 additive → 문제 시 지표 계산부만 비활성(로그 후 skip)하고 기존 평가 유지.
- 마이그레이션은 `down_revision` 역방향 제공. Deploy Guard 15:15~15:45 KST 준수.
