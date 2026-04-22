---
id: SPEC-AI-011
phase: acceptance
version: 1.0.0
created: 2026-04-22
updated: 2026-04-22
---

# SPEC-AI-011 Acceptance Criteria

## 개요

본 문서는 SPEC-AI-011의 모든 요구사항(REQ-HIER, REQ-CAND, REQ-BRIEF, REQ-FACTOR, REQ-COMPAT)에 대한 수용 기준을 Given/When/Then 형식으로 상세화한다.

---

## 1. StockRelation 타입 확장 (REQ-HIER-001 ~ 004)

### AC-HIER-001: 지배구조 관계 타입 수용

**Given**
- `StockRelation` 모델이 배포되어 있고 Python 레이어에 허용 relation_type 집합이 정의되어 있다

**When**
- 개발자가 `relation_type='holding_company'` 또는 `'subsidiary'` 값으로 `StockRelation` 레코드를 생성한다

**Then**
- 시스템은 예외 없이 레코드를 저장해야 한다
- 저장된 레코드는 `SELECT` 조회 시 동일한 값으로 반환되어야 한다

---

### AC-HIER-002: 초기 시딩 마이그레이션 정상 동작

**Given**
- 마이그레이션이 적용되기 전 DB 상태
- HD현대(stock_code=267250) 및 자회사 4개(009540, 329180, 010620, 010140)가 `stocks` 테이블에 존재한다

**When**
- `alembic upgrade head`를 실행한다

**Then**
- `stock_relations` 테이블에 `relation_type='holding_company'`이며 `source_stock_id = HD현대.id`인 레코드가 정확히 4건 존재해야 한다
- 각 레코드의 `target_stock_id`는 각각 009540, 329180, 010620, 010140에 해당하는 `stock.id`와 일치해야 한다

---

### AC-HIER-003: 마이그레이션 역방향(downgrade) 정상 동작

**Given**
- AC-HIER-002의 마이그레이션이 적용된 상태

**When**
- `alembic downgrade -1`을 실행한다

**Then**
- HD현대 관련 4개 `'holding_company'` 레코드가 모두 삭제되어야 한다
- 다른 `stock_relations` 레코드(competitor, supplier 등)는 영향받지 않아야 한다

---

### AC-HIER-004: 기존 relation_type 값 호환성

**Given**
- 기존 `stock_relations` 테이블에 `competitor`, `supplier`, `equipment`, `material`, `customer` 타입의 레코드가 존재한다

**When**
- 본 SPEC의 마이그레이션 및 모델 업데이트가 적용된 후

**Then**
- 기존 5가지 타입의 레코드는 모두 유지되어야 한다
- 기존 타입을 소비하는 코드(뉴스 전파 로직 등)에 회귀가 발생하지 않아야 한다

---

## 2. 후보 풀 확장 로직 (REQ-CAND-001 ~ 003)

### AC-CAND-001: 지주사 뉴스 언급 시 자회사 자동 확장

**Given**
- HD현대의 자회사 관계 4건이 DB에 시딩되어 있다
- 뉴스 크롤러가 "HD현대 인도 합작 조선소 설립" 뉴스를 수집하여 HD현대만 언급 종목으로 태깅했다

**When**
- `fund_manager.py`의 일일 브리핑 후보 수집 파이프라인이 실행된다

**Then**
- 후보 풀에 HD현대가 포함되어야 한다
- 후보 풀에 HD한국조선해양(009540), HD현대중공업(329180), HD현대삼호(010620), HD현대미포(010140)가 자동으로 포함되어야 한다

---

### AC-CAND-002: 확장된 자회사 후보 메타데이터

**Given**
- AC-CAND-001의 상황

**When**
- 후보 풀이 구성된 직후

**Then**
- 자동 추가된 4개 자회사 후보의 `candidate_data` JSON에는 다음 필드가 포함되어야 한다:
  - `"added_via": "subsidiary_expansion"`
  - `"parent_holding_company_id": <HD현대의 stock_id>`
  - `"parent_holding_company_name": "HD현대"`
- HD현대 자신의 `candidate_data`에는 `added_via` 필드가 포함되지 **않아야** 한다 (뉴스 직접 언급)

---

### AC-CAND-003: 재귀적 확장 방지

**Given**
- DB에 가상의 3단계 체인이 존재한다고 가정: A(지주사) → B(중간 지주사) → C(운영사), 두 개의 `'holding_company'` 레코드 A→B, B→C
- 뉴스 크롤러가 A만 언급 종목으로 태깅했다

**When**
- 후보 수집 파이프라인이 실행된다

**Then**
- 후보 풀에는 A와 B만 포함되어야 한다
- C는 포함되지 **않아야** 한다 (1단계 확장 제약)

---

### AC-CAND-004: 이미 직접 언급된 자회사의 중복 방지

**Given**
- 뉴스가 HD현대와 HD한국조선해양 두 종목을 모두 언급한 상황

**When**
- 후보 수집 파이프라인이 실행된다

**Then**
- 후보 풀에 HD한국조선해양은 **정확히 1회**만 포함되어야 한다
- 중복 추가로 인한 점수 왜곡이 발생하지 않아야 한다
- HD한국조선해양의 `candidate_data`에는 `added_via="subsidiary_expansion"`이 **포함되지 않아야** 한다 (뉴스 직접 언급이 우선)

---

## 3. 브리핑 프롬프트 지주사 인식 (REQ-BRIEF-001 ~ 002)

### AC-BRIEF-001: 지주사 컨텍스트 문구 주입

**Given**
- 후보 풀에 HD현대(지주사)와 HD한국조선해양(자회사)이 모두 포함된 상태
- `fund_manager.py`가 일일 브리핑 프롬프트를 조립 중

**When**
- 브리핑 프롬프트가 생성된다

**Then**
- 프롬프트 문자열 내에 다음 형태의 문구가 포함되어야 한다:
  - "이 종목은 지주사입니다. 뉴스가 ... 사업 운영에 관한 것이라면 자회사를 우선 검토하세요:" + 자회사 목록(HD한국조선해양, HD현대중공업, HD현대삼호, HD현대미포 중 후보 풀에 존재하는 것들)
- 문구는 한국어로 렌더링되어야 한다 (conversation_language=ko 준수)

---

### AC-BRIEF-002: 지주사가 아닌 후보에 대한 문구 미주입

**Given**
- 후보 풀에 지주사가 포함되지 않은 상황 (예: 단일 법인 종목만 10개)

**When**
- 브리핑 프롬프트가 생성된다

**Then**
- 프롬프트에 "지주사입니다" 문구가 **전혀** 나타나지 않아야 한다

---

### AC-BRIEF-003: candidate_data에 자회사 목록 기록

**Given**
- AC-BRIEF-001의 상황

**When**
- 후보가 최종 `candidate_data`로 직렬화된다

**Then**
- HD현대의 `candidate_data.holding_company_discount_note` 필드가 존재해야 한다
- 값은 자회사의 `{stock_code, name}` 객체 배열이어야 한다
- 예: `[{"stock_code": "009540", "name": "HD한국조선해양"}, {"stock_code": "329180", "name": "HD현대중공업"}, ...]`

---

## 4. 지주사 할인 팩터 (REQ-FACTOR-001 ~ 003)

### AC-FACTOR-001: 지주사에 할인 팩터 적용

**Given**
- HD현대가 FundSignal 생성 대상이며 composite_score 계산이 시작된다
- 만약 할인 팩터가 없었다면 composite_score = X (실측 기준 값)

**When**
- `factor_scoring.py`가 composite_score를 계산한다

**Then**
- 최종 composite_score는 정확히 **X - 5**여야 한다
- `factor_scores` JSON에 `"holding_company_discount": -5` 키-값 쌍이 포함되어야 한다

---

### AC-FACTOR-002: 자회사에는 할인 팩터 미적용

**Given**
- HD한국조선해양이 FundSignal 생성 대상

**When**
- `factor_scoring.py`가 composite_score를 계산한다

**Then**
- composite_score는 할인 없이 원래 계산된 값이어야 한다
- `factor_scores` JSON에 `"holding_company_discount"` 키가 **존재하지 않아야** 한다

---

### AC-FACTOR-003: 일반 단일 법인에는 할인 팩터 미적용

**Given**
- `stock_relations` 테이블에서 `source_stock_id`로 한 번도 등록되지 않은 일반 종목 (예: 삼성전자)

**When**
- `factor_scoring.py`가 composite_score를 계산한다

**Then**
- composite_score는 할인 없이 원래 계산된 값이어야 한다
- `factor_scores` JSON에 `"holding_company_discount"` 키가 **존재하지 않아야** 한다

---

### AC-FACTOR-004: 운영 실체가 지주사보다 상위 랭크

**Given**
- 동일한 조선업 운영 뉴스 컨텍스트에서 HD현대와 HD한국조선해양이 모두 후보로 평가된다
- 두 종목의 다른 팩터 점수가 동일하다고 가정 (뉴스 점수, 기술적 점수 등)

**When**
- 두 종목의 composite_score가 계산되고 랭킹된다

**Then**
- HD한국조선해양의 composite_score > HD현대의 composite_score (5점 차이 이상)
- 랭킹 정렬 시 HD한국조선해양이 HD현대보다 상위에 위치해야 한다

---

## 5. 호환성 (REQ-COMPAT-001 ~ 002)

### AC-COMPAT-001: 기존 시그널 타입 로직 보존

**Given**
- SPEC-AI-004의 `disclosure_impact`, `sector_ripple`, `gap_pullback_candidate` 시그널 생성 로직이 운영 중

**When**
- SPEC-AI-011이 배포된 후 기존 공시 기반 시그널이 생성되는 시나리오가 실행된다

**Then**
- 기존 시그널 생성 성공률이 변하지 않아야 한다 (회귀 없음)
- 기존 시그널의 `factor_scores`, `composite_score`, `signal_type` 필드 구조가 유지되어야 한다 (새 키 추가는 허용, 기존 키 제거/변경은 금지)

---

### AC-COMPAT-002: 기존 VirtualTrade 무결성

**Given**
- SPEC-AI-011 배포 전에 생성된 `VirtualTrade` 및 `PortfolioSnapshot` 레코드가 존재한다

**When**
- 마이그레이션 적용 및 코드 업데이트 완료 후

**Then**
- 기존 `VirtualTrade` 레코드는 **정확히 동일한 값**을 유지해야 한다
- 기존 포트폴리오 수익률/성과 지표에 어떤 변경도 발생하지 않아야 한다
- 소급 재계산(backfill)이 **수행되지 않아야** 한다

---

## 6. 엣지 케이스

### AC-EDGE-001: 지주사 등록되었으나 자회사 stock_id가 DB에 없는 경우

**Given**
- `stock_relations` 테이블에 `'holding_company'` 레코드가 있으나 `target_stock_id`가 가리키는 `stocks` 레코드가 삭제된 상황 (외래키 CASCADE로 함께 삭제되어야 하지만 데이터 정합성 오류 가정)

**When**
- 후보 풀 확장 로직이 해당 지주사에 대해 조회를 수행한다

**Then**
- 시스템은 예외를 발생시키지 않고 유효한 자회사만 반환해야 한다
- 로그에 경고를 남기는 것이 권장된다 (필수 아님)

---

### AC-EDGE-002: 빈 후보 풀에서 확장 로직 실행

**Given**
- 뉴스 수집 결과 후보가 0개인 상황

**When**
- 후보 풀 확장 로직이 호출된다

**Then**
- 시스템은 예외 없이 빈 리스트를 반환해야 한다
- DB 조회가 최소화되어야 한다 (불필요한 전체 스캔 금지)

---

### AC-EDGE-003: 동일 지주사를 가진 뉴스가 여러 개인 경우

**Given**
- 뉴스 A: HD현대 언급
- 뉴스 B: HD현대 언급 (다른 기사)

**When**
- 후보 풀 확장 로직이 실행된다

**Then**
- 자회사 4개 각각이 후보 풀에 **정확히 1회**만 포함되어야 한다 (중복 제거)
- 자회사의 `candidate_data.parent_holding_company_id`는 하나의 일관된 값(HD현대)을 가져야 한다

---

## 7. Quality Gate Criteria

### AC-QG-001: 테스트 커버리지

**Given**
- 본 SPEC의 모든 Run 작업이 완료됨

**When**
- `pytest --cov=app.services.fund_manager --cov=app.services.factor_scoring --cov-report=term-missing`를 실행한다

**Then**
- 본 SPEC에 의해 추가된 신규 로직의 라인 커버리지는 **85% 이상**이어야 한다
- M2, M3, M4 각각의 신규 함수/분기에 최소 1개 이상의 단위 테스트가 존재해야 한다

---

### AC-QG-002: Linting 및 타입 체킹

**Given**
- Run 단계 완료 직후

**When**
- `ruff check .` 및 `mypy app/`을 실행한다

**Then**
- Zero errors / Zero warnings가 달성되어야 한다

---

### AC-QG-003: LSP Quality Gate

**Given**
- Run 단계 완료 직후

**When**
- LSP 진단이 실행된다

**Then**
- Zero errors, zero type errors, zero lint errors가 확인되어야 한다 (plan/run/sync 공통 `run` 기준)

---

### AC-QG-004: 수동 검증 — 운영 DB 시나리오 재현

**Given**
- 개발 환경에 2026-04-21자 문제 상황을 재현한 데이터
- HD현대 조선업 관련 뉴스 3건이 주입된 상태

**When**
- 본 SPEC이 적용된 코드로 일일 브리핑 파이프라인을 수동 실행한다

**Then**
- 브리핑 AI의 최종 stock_picks에서 HD한국조선해양이 HD현대보다 상위에 선택되거나, 최소한 자회사도 후보로 평가되었음이 AI의 reasoning에 기록되어야 한다

---

## 8. Definition of Done (DoD)

SPEC-AI-011은 다음 모든 조건을 만족할 때 완료(Done)로 간주된다:

- [ ] M1 ~ M4 모든 마일스톤의 구현이 완료됨
- [ ] 본 문서의 모든 AC-HIER, AC-CAND, AC-BRIEF, AC-FACTOR, AC-COMPAT, AC-EDGE 수용 기준이 통과됨
- [ ] AC-QG-001 ~ AC-QG-004 Quality Gate가 모두 통과됨
- [ ] Alembic 마이그레이션이 upgrade/downgrade 양방향으로 검증됨
- [ ] 새로 추가된 신규 public 함수에 대한 docstring 작성 (code_comments=ko 준수)
- [ ] 관련 @MX 태그 부여 (새 exported 함수에 `@MX:NOTE` 또는 `@MX:ANCHOR` 검토)
- [ ] Git 커밋 메시지에 "SPEC-AI-011" 참조 포함
- [ ] `/moai sync SPEC-AI-011`로 문서 동기화 완료

---

Version: 1.0.0
Status: Ready for Run Phase Approval
