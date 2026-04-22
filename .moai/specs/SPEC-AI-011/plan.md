---
id: SPEC-AI-011
phase: plan
version: 1.0.0
created: 2026-04-22
updated: 2026-04-22
---

# SPEC-AI-011 Implementation Plan

## 개요

본 계획은 "지배구조 인식 기반 종목선택 개선"을 4개의 논리적 마일스톤으로 분해한다. 각 마일스톤은 독립적으로 검증 가능하며, 순서대로 진행되어야 한다 (M1 → M2 → M3 → M4).

---

## 마일스톤 (Priority-Based, No Time Estimates)

### M1 — Priority High: StockRelation 타입 확장 + 초기 데이터 시딩

**목표**: `'holding_company'`와 `'subsidiary'` 관계 타입을 시스템에 정식으로 도입하고, HD현대의 자회사 4개 초기 레코드를 DB에 삽입한다.

**대상 파일**:
- `backend/app/models/stock_relation.py` — docstring/주석 업데이트 (relation_type 집합 확장 명시)
- `backend/alembic/versions/036_*.py` (or 현재 최신 리비전 이후) — 새 마이그레이션 파일 신설
  - upgrade: HD현대(267250) → 009540, 329180, 010620, 010140의 4개 `'holding_company'` 레코드 삽입
  - downgrade: 삽입한 레코드 삭제

**대응 요구사항**: REQ-HIER-001, REQ-HIER-002, REQ-HIER-003, REQ-HIER-004

**검증**:
- 마이그레이션 적용 후 `SELECT COUNT(*) FROM stock_relations WHERE source_stock_id = <HD현대 ID> AND relation_type = 'holding_company'`가 4를 반환해야 한다
- `alembic downgrade -1` 후 0을 반환해야 한다

**완료 조건**:
- 마이그레이션 실행 성공 (양방향)
- 모델 docstring에 신규 relation_type이 명시됨
- 기존 마이그레이션 체인이 깨지지 않음

---

### M2 — Priority High: 후보 풀 자회사 확장 로직

**목표**: `fund_manager.py`의 후보 수집 파이프라인에 자회사 확장 단계를 삽입한다.

**대상 파일**:
- `backend/app/services/fund_manager.py` — 후보 수집 단계 내부에 `_expand_candidates_with_subsidiaries()` 성격의 새 메서드 추가 (구체 이름은 Run 단계에서 결정)
- 필요 시: `backend/app/services/stock_relation_service.py` 또는 유사한 헬퍼 모듈 (없을 경우 `fund_manager.py` 내부 private 함수로 충분)

**대응 요구사항**: REQ-CAND-001, REQ-CAND-002, REQ-CAND-003

**기술 접근**:
1. 뉴스 언급 종목 리스트를 수집한 직후 (기존 파이프라인 지점 유지)
2. 각 후보의 `stock_id`에 대해 `StockRelation.query.filter(source_stock_id=X, relation_type='holding_company').all()` 조회
3. 반환된 `target_stock_id` 집합을 수집하고, 중복 제거 후 원 후보 리스트에 append
4. 새로 추가된 자회사 후보의 `candidate_data` JSON에 `added_via`, `parent_holding_company_id`, `parent_holding_company_name` 필드 주입
5. 1단계 확장만 수행 (추가된 자회사에 대해서는 다시 REQ-CAND-001을 적용하지 않는다)

**검증**:
- 단위 테스트: HD현대만 뉴스 언급한 상황 → 후보 풀에 HD한국조선해양 외 3개 포함되는지 확인
- 단위 테스트: 확장된 자회사의 `candidate_data`에 `added_via='subsidiary_expansion'` 포함 확인
- 엣지 테스트: 이미 자회사가 뉴스로 언급된 경우 중복 추가 없이 유지되는지 확인

**완료 조건**:
- 기존 후보 수집 경로의 회귀 없음 (SPEC-AI-003/004의 `_gather_leading_candidates`, `_gather_disclosure_candidates` 동작 보존)
- 새 단위 테스트 통과
- `candidate_data` 메타 필드 올바르게 저장됨

---

### M3 — Priority Medium: 브리핑 프롬프트 지주사 컨텍스트 주입

**목표**: 브리핑 프롬프트 생성 시 지주사 종목에 대해 "지주사입니다 + 자회사 목록" 문구를 주입한다.

**대상 파일**:
- `backend/app/services/fund_manager.py` — 브리핑 프롬프트 조립 섹션 (일일 브리핑 프롬프트 빌더 부분)
- 테스트: `backend/tests/services/test_fund_manager_briefing.py` (없을 경우 신규 생성)

**대응 요구사항**: REQ-BRIEF-001, REQ-BRIEF-002

**기술 접근**:
1. 브리핑 프롬프트 조립 단계에서 후보 리스트를 순회
2. 각 후보가 지주사인지 판별 (`StockRelation.source_stock_id == 후보.stock_id && relation_type == 'holding_company'` 존재 여부)
3. 지주사인 경우:
   - 자회사 목록을 조회하여 `candidate_data.holding_company_discount_note`에 저장
   - 프롬프트 문자열에 "이 종목은 지주사입니다. 뉴스가 사업 운영에 관한 것이라면 자회사를 우선 검토하세요: [자회사 stock_code, name 목록]" 추가
4. 프롬프트 문구는 한국어 (conversation_language=ko 준수)

**검증**:
- 단위 테스트: HD현대가 포함된 후보 리스트로 프롬프트 생성 시 자회사 목록 문구 포함 확인
- 단위 테스트: 지주사가 아닌 종목만 있을 때는 해당 문구가 추가되지 않음 확인

**완료 조건**:
- 브리핑 프롬프트에 지주사 컨텍스트가 렌더링됨
- `candidate_data.holding_company_discount_note`가 구조화된 자회사 목록을 담음

---

### M4 — Priority Medium: Composite Score 지주사 할인 팩터

**목표**: `factor_scoring.py`의 composite_score 계산에 `holding_company_discount = -5` 팩터를 추가한다.

**대상 파일**:
- `backend/app/services/factor_scoring.py` — composite_score 계산 함수에 할인 팩터 추가
- `backend/app/models/fund_signal.py` — 변경 없음 (factor_scores JSON 필드 재사용)
- 테스트: `backend/tests/services/test_factor_scoring.py`

**대응 요구사항**: REQ-FACTOR-001, REQ-FACTOR-002, REQ-FACTOR-003

**기술 접근**:
1. composite_score 계산 파이프라인의 마지막 보정 단계에 지주사 판별 로직 삽입
2. 대상 종목이 `StockRelation` 상 `source_stock_id` + `relation_type='holding_company'`에 등록되어 있으면 -5 적용
3. `factor_scores` JSON에 `"holding_company_discount": -5` 키 기록
4. 판별이 참이 아닌 종목(자회사, 일반 단일 법인)에는 이 키를 기록하지 않음 (REQ-FACTOR-003)

**검증**:
- 단위 테스트: 지주사(HD현대)에 대해 composite_score가 -5 보정된 값을 반환하고 factor_scores에 키가 기록됨
- 단위 테스트: 자회사(HD한국조선해양)에 대해 composite_score가 보정되지 않으며 factor_scores에 키가 없음
- 통합 테스트: 동일 뉴스 컨텍스트에서 자회사의 composite_score가 지주사보다 높아짐

**완료 조건**:
- 모든 단위/통합 테스트 통과
- factor_scores JSON 스키마 문서 업데이트
- 기존 composite_score 사용 지점(랭킹, 상위 N 선정) 회귀 없음

---

## 기술 접근 (Technical Approach)

### DB 조회 최적화

- 기존 인덱스: `idx_stock_relations_target_stock`, `idx_stock_relations_target_sector`
- **추가 권장 인덱스** (M1 마이그레이션 내 또는 후속 마이그레이션):
  - `CREATE INDEX idx_stock_relations_source_type ON stock_relations (source_stock_id, relation_type);`
  - WHY: REQ-CAND-001, REQ-FACTOR-001의 조회 패턴이 `source_stock_id + relation_type` 필터이므로 전용 인덱스가 성능에 유리함

### 캐싱 전략

- 지주사 판별은 동일 브리핑 사이클 내에서 반복 호출될 수 있으므로, `fund_manager.py` 내 in-memory dict 캐시 사용 권장 (`{stock_id: is_holding_company}`)
- 캐시 수명: 단일 브리핑 실행 주기 (daily run 동안 유효)

### 테스트 전략

- `quality.yaml`의 `development_mode`가 TDD일 경우 Run 단계에서 RED → GREEN → REFACTOR 진행
- DDD일 경우 characterization test 우선 작성 후 IMPROVE
- 테스트 커버리지 목표: 85% 이상 (M2, M3, M4의 신규 로직에 대해)

---

## 리스크 (Risks)

### R1 — relation_type 체크 제약조건 부재로 인한 오타 유입

**설명**: `stock_relations.relation_type`은 String(20)으로 자유 텍스트이며, DB 레벨 Enum 제약이 없다. 개발자가 `'holdingcompany'` 같은 오타를 입력할 수 있다.

**완화 방안**:
- Python 레이어에 `RelationType` Literal/Enum 정의
- SQLAlchemy 모델의 docstring에 허용 값 명시 (이미 존재하는 주석 패턴 확장)

**완화 우선순위**: 중간

### R2 — 자회사 확장으로 인한 후보 풀 비대화

**설명**: 초기에는 HD현대 1건만 등록하지만, 향후 지주사 데이터가 누적되면 후보 풀이 과도하게 커질 수 있다.

**완화 방안**:
- REQ-CAND-003의 1단계 확장 제약 엄격 준수
- 향후 필요 시 "지주사 자회사 확장의 최대 N개" 제약 도입 검토 (본 SPEC 범위 외)

**완화 우선순위**: 낮음 (현재 데이터 규모 기준)

### R3 — 지주사 할인 -5 값의 적절성

**설명**: 본 SPEC은 -5를 고정값으로 지정하지만, composite_score의 평균 분포에 비해 과소/과대할 가능성이 있다.

**완화 방안**:
- Run 단계에서 SPEC-AI-006의 composite_score 실측 분포를 확인하고 -5가 실제 랭크를 뒤집기에 충분한지 통합 테스트로 검증
- 불충분할 경우 M4 Run 단계에서 Re-planning Gate를 통해 수정 제안

**완화 우선순위**: 중간 (검증 필수)

### R4 — 기존 FundSignal의 factor_scores 스키마 확장 호환성

**설명**: `factor_scores` JSON은 기존 키 집합을 가진다. 새 키 `holding_company_discount` 추가가 하위 소비자(프론트엔드, 리포트)에 영향을 줄 수 있다.

**완화 방안**:
- 기존 소비자는 JSON 키를 whitelist 방식으로 사용하지 않는지 확인 (일반적으로 dict iteration)
- 신규 키는 optional로 처리되도록 모든 consumer가 `.get()` 또는 default 처리하는지 확인

**완화 우선순위**: 낮음 (JSON 필드 추가는 일반적으로 비파괴적)

---

## 의존성 (Dependencies)

### 필수 선행 SPEC

- **SPEC-RELATION-001**: `StockRelation` 모델이 이미 존재해야 함 (현재 코드베이스에 존재 확인됨)
- **SPEC-AI-006**: `factor_scoring.py`의 composite_score 체계가 이미 존재해야 함 (본 SPEC이 팩터 추가로 확장)

### 병렬 실행 가능 SPEC

- SPEC-AI-003, SPEC-AI-004와 충돌 없음 (독립 레이어)

### 파급 효과 SPEC

- **향후 검토 대상**: 지주사 데이터 자동화 SPEC (DART 지분 공시 파싱 기반) — 본 SPEC 완료 후 제안 가능

---

## 오픈 질문 (Open Questions)

Run 단계에서 결정해야 할 사항:

1. **Q1**: `stock_relations.relation_type`에 DB 레벨 체크 제약 추가할 것인가? (현재는 없음)
   - 영향: 신규 타입 오타 방지 vs 마이그레이션 부담 증가
   - 권장 기본값: 추가하지 않음 (기존 코드베이스 관례 유지, Python 레이어 Enum으로 대체)

2. **Q2**: 자회사 확장 메서드의 구체 이름은?
   - 예: `_expand_candidates_with_subsidiaries`, `_apply_holding_company_expansion`, `_inject_subsidiary_candidates`
   - 권장 기본값: `_expand_candidates_with_subsidiaries` (행동 + 대상 명시)

3. **Q3**: 자회사 목록 조회를 `stock_relation_service.py`로 분리할 것인가, `fund_manager.py` 내부에 둘 것인가?
   - 영향: 재사용성 vs 파일 수 증가
   - 권장 기본값: Run 단계에서 M4(factor_scoring)도 동일 조회를 사용한다면 서비스 분리 검토

4. **Q4**: `subsidiary` 방향 레코드(자회사 → 지주사)를 시딩 시 함께 삽입할 것인가?
   - 영향: 조회 편의 vs 데이터 중복
   - 권장 기본값: REQ-HIER-003을 옵셔널로 해석하고, 초기 시딩은 `'holding_company'` 방향만 수행 (필요 시 후속 마이그레이션으로 추가)

---

## Quality Gates

- **TRUST 5** 준수:
  - **Tested**: M2, M3, M4 각각 단위 테스트 + 통합 테스트 추가 (커버리지 85% 이상)
  - **Readable**: 한국어 주석 (code_comments=ko), 변수명/함수명은 영어 snake_case
  - **Unified**: ruff + black 통과
  - **Secured**: SQL injection 방지 확인 (ORM 파라미터 바인딩만 사용, raw SQL 금지)
  - **Trackable**: 커밋 메시지에 "SPEC-AI-011" 참조, Conventional Commits 준수

- **LSP Gate**: Run 단계 종료 시 Zero errors / Zero type errors / Zero lint errors

---

Version: 1.0.0
Next: Proceed to Run phase via `/moai run SPEC-AI-011` after user approval
