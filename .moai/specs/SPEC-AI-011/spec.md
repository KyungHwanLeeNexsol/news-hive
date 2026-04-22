---
id: SPEC-AI-011
version: 1.0.0
status: Planned
created: 2026-04-22
updated: 2026-04-22
author: MoAI
priority: High
issue_number: 0
title: AI 펀드매니저 지배구조 인식 기반 종목선택 개선
tags: [fund-manager, stock-relation, holding-company, candidate-pool, factor-scoring, briefing]
---

# SPEC-AI-011: AI 펀드매니저 지배구조 인식 기반 종목선택 개선

## HISTORY

- **v1.0.0 (2026-04-22)**: 초기 SPEC 작성. HD현대(267250) vs HD한국조선해양(009540) 운영사 오선택 사례를 근거로 지배구조 인식 로직 설계.

---

## 0. 배경 및 목적

### 문제 정의

현재 AI 펀드매니저는 뉴스에 언급된 종목의 **언급 빈도만으로** 후보 종목을 선정하며, **기업집단의 수직적 지배구조(지주사-자회사)를 이해하지 못한다.**

이로 인해 "사업 운영에 관한 뉴스"가 발생했을 때 실제 사업을 수행하는 자회사(운영사)가 아니라 **지분만 보유한 지주사**를 후보로 선정하는 오류가 반복된다.

### 운영 환경 검증 사례 (2026-04-21)

| 항목 | 내용 |
|------|------|
| 선정된 종목 | **HD현대 (267250)** — 지주회사 (Holding Company) |
| 선정되지 않은 종목 | **HD한국조선해양 (009540)** — 중간지주 + 실제 조선 사업 운영사 |
| 관련 뉴스 | "인도 합작 조선소 설립", "AI 조선소 추진", "자율 수상함 개발" |
| 뉴스 내용 특성 | 모두 조선업 **사업 운영**에 관한 뉴스 |
| HD한국조선해양 직전 시그널 | 2026-04-03 (3주 전) |
| 결과 | AI가 운영 실체 대신 지주사를 매수 |

### 왜 이것이 잘못인가

조선업 영업 뉴스는 **HD한국조선해양의 매출과 이익에 직접 영향**을 준다. 지주사인 HD현대는 지분/배당을 통한 **간접 수혜**에 그친다. 사업 운영 뉴스로 매수할 때 올바른 타겟은 **영업 실체(operating entity)**이다.

### 목표

- `StockRelation` 모델에 지배구조(holding_company / subsidiary) 관계 타입을 추가한다
- 지주사 뉴스 발생 시 자회사를 후보 풀에 자동 확장한다
- 브리핑 프롬프트가 지주사-자회사 구조를 인식하도록 컨텍스트를 주입한다
- Composite score 계산 시 지주사에 할인을 적용하여 운영 실체가 상위 랭크되도록 한다

---

## 1. 환경 (Environment)

### 1.1 기존 인프라

| 모듈 | 현재 상태 | SPEC-AI-011에서의 역할 |
|------|-----------|----------------------|
| `backend/app/models/stock_relation.py` | `StockRelation` 모델 존재. relation_type: 'competitor' \| 'supplier' \| 'equipment' \| 'material' \| 'customer' | `'holding_company'`, `'subsidiary'` 타입 추가 |
| `backend/app/services/fund_manager.py` | 2800+ 줄. 뉴스 언급 종목으로부터 후보 풀 구성 → 일일 브리핑 → 개별 시그널 생성 | 후보 풀 확장 로직 + 브리핑 프롬프트에 지주사 컨텍스트 주입 |
| `backend/app/services/factor_scoring.py` | composite_score 계산 및 factor_scores JSON 생성 | `holding_company_discount` 팩터 추가 |
| `backend/app/models/fund_signal.py` | signal, confidence, composite_score, signal_type, reasoning 컬럼 보유 | 변경 없음 (composite_score 값만 영향) |
| `backend/app/services/disclosure_impact_scorer.py` | 섹터 파급(sector ripple) 탐지 로직 | 구조적 레퍼런스로 활용 (새 relation 기반 후보 확장 패턴) |

### 1.2 기존 DB 모델

- `stock_relations` 테이블: source_stock_id, source_sector_id, target_stock_id, target_sector_id, relation_type, confidence, reason, created_at
  - 방향성 규약: **"target에 뉴스가 생기면 source에게 전파된다"**
  - **주의**: 본 SPEC의 지배구조 타입은 방향성 규약을 재해석한다 (§3.1 REQ-HIER-002 참조)
- `stocks` 테이블: id, name, stock_code, sector_id, market, market_cap
- `fund_signals` 테이블: 변경 없음

### 1.3 관련 SPEC

- **SPEC-RELATION-001**: `StockRelation` 모델의 기반 정의 (상속/확장)
- **SPEC-AI-006**: factor_scoring composite_score 체계 (확장)
- **SPEC-AI-004**: 구조적 레퍼런스 — 새 signal_type 추가 + 새 서비스 계층 패턴이 유사함

---

## 2. 가정 (Assumptions)

- **A1**: 한국 상장사의 주요 지주사-자회사 관계는 수동으로 초기 데이터를 구축 가능한 규모이다 (상위 100개 수준)
- **A2**: 지주사는 `StockRelation`에 `source_stock_id`로, 자회사는 `target_stock_id`로 표현한다. 이때 관계 타입은 `'holding_company'`이며 의미는 "source(지주사)가 target(자회사)를 지배한다"이다
- **A3**: 반대 방향 레코드(자회사 → 지주사, relation_type='subsidiary')는 조회 편의를 위한 쌍방 레코드로, 필수는 아니지만 권장된다
- **A4**: 자회사 확장은 1단계만 수행한다 (HD현대 → HD한국조선해양 → 현대중공업과 같은 재귀적 확장은 하지 않는다)
- **A5**: Composite score 계산은 0~100 또는 그 이상의 값을 가지며, -5 감산은 유의미한 랭크 변화를 만든다 (SPEC-AI-006에서 확인)
- **A6**: 운영 DB의 현재 `StockRelation.relation_type` 값 중 `'holding_company'` 또는 `'subsidiary'`를 사용하는 행은 존재하지 않는다 (안전하게 신규 추가 가능)

---

## 3. 요구사항 (Requirements)

### 3.1 StockRelation 지배구조 타입 확장 (REQ-HIER-001 ~ 004)

> **REQ-HIER-001 [Ubiquitous]**: 시스템은 `StockRelation.relation_type` 필드에 `'holding_company'`와 `'subsidiary'` 두 개의 값을 **항상** 수용해야 한다.
> WHY: 기존 'competitor' | 'supplier' | 'equipment' | 'material' | 'customer' 다섯 종류는 수평적 관계(같은 산업군 내 기업 간)만 표현하며, 수직적 지배구조(모-자회사)를 표현할 수 없다.

> **REQ-HIER-002 [Ubiquitous]**: `'holding_company'` 관계는 **source가 지주사, target이 자회사**의 의미를 **항상** 가져야 한다.
> WHY: StockRelation의 기본 방향성 규약(target 뉴스 → source 전파)과는 별개로, 지배구조 관계는 "source가 target을 소유한다"라는 소유 방향으로 해석된다. 본 SPEC의 후보 확장 로직은 이 해석을 전제로 한다.

> **REQ-HIER-003 [Ubiquitous]**: `'subsidiary'` 관계는 **source가 자회사, target이 지주사**의 의미를 **항상** 가져야 한다.
> WHY: `'holding_company'`의 역방향 조회 편의를 위한 쌍방 레코드이다. 하나의 지주사-자회사 쌍은 두 개의 `StockRelation` 레코드(holding_company 방향 + subsidiary 방향)로 표현될 수 있다.

> **REQ-HIER-004 [Event-Driven]**: **WHEN** Alembic 마이그레이션이 실행될 때 **THEN** 시스템은 HD현대(267250) → HD한국조선해양(009540), HD현대중공업(329180), HD현대삼호(010620), HD현대미포(010140)에 대한 초기 `'holding_company'` 관계 레코드를 `stock_relations` 테이블에 생성해야 한다.
> WHY: 최소 1건의 실제 사례를 투입해야 REQ-CAND-001 ~ REQ-DISC-001 계열의 end-to-end 검증이 가능하다.

### 3.2 후보 풀 확장 로직 (REQ-CAND-001 ~ 003)

> **REQ-CAND-001 [Event-Driven]**: **WHEN** `fund_manager.py`의 일일 브리핑 후보 수집 단계에서 뉴스 언급 종목을 수집한 직후 **THEN** 시스템은 각 후보 종목에 대해 `relation_type='holding_company'`이고 `source_stock_id`가 후보 종목 ID인 `StockRelation` 레코드를 조회하여, `target_stock_id`에 해당하는 자회사를 후보 풀에 추가해야 한다.
> WHY: 지주사 뉴스가 사업 운영에 관한 것일 때, 해당 운영을 수행하는 자회사가 브리핑 AI의 선택지에 포함되어야 한다.

> **REQ-CAND-002 [Event-Driven]**: **WHEN** REQ-CAND-001에 의해 후보 풀에 추가된 자회사 종목이 존재할 때 **THEN** 시스템은 해당 후보의 `candidate_data` JSON에 `"added_via": "subsidiary_expansion"` 태그와 `"parent_holding_company_id": <지주사 stock_id>`, `"parent_holding_company_name": <지주사 이름>` 필드를 포함해야 한다.
> WHY: 브리핑 AI와 후속 디버깅에서 이 종목이 뉴스 직접 언급이 아닌 지배구조 추론에 의해 추가되었음을 식별 가능해야 한다.

> **REQ-CAND-003 [Unwanted]**: 시스템은 자회사 확장을 수행할 때 **재귀적 확장을 해서는 안 된다**. 즉, 확장된 자회사가 또 다른 자회사를 가지고 있더라도 1단계(direct subsidiary)에서만 멈춰야 한다.
> WHY: HD현대 → HD한국조선해양 → (추가 하위 자회사가 있을 경우) 무한 확장으로 인해 후보 풀이 비정상적으로 팽창하는 것을 방지한다.

### 3.3 브리핑 프롬프트 지주사 인식 강화 (REQ-BRIEF-001 ~ 002)

> **REQ-BRIEF-001 [State-Driven]**: **IF** 후보 풀에 `relation_type='holding_company'`의 source로 등록된 종목(= 지주사로 확인된 종목)이 포함되어 있다면 **THEN** 시스템은 브리핑 프롬프트에 해당 종목에 대해 "이 종목은 지주사입니다. 뉴스가 조선/사업 운영에 관한 것이라면 자회사를 우선 검토하세요: [자회사 목록]"이라는 문구를 주입해야 한다.
> WHY: 브리핑 AI(Gemini/OpenRouter)가 지배구조를 이해하고 자회사 우선 선택을 유도하기 위함이다.

> **REQ-BRIEF-002 [State-Driven]**: **IF** REQ-BRIEF-001이 적용된 지주사 종목이 존재할 때 **THEN** 시스템은 해당 종목의 `candidate_data`에 `"holding_company_discount_note"` 필드를 추가하고, 그 값으로 자회사 목록(stock_code, name 배열)을 저장해야 한다.
> WHY: 프롬프트 주입 외에도 구조화된 형태로 자회사 정보를 보존하여 하위 로직(factor_scoring, 디버깅)에서 재활용할 수 있다.

### 3.4 지주사 할인 팩터 (REQ-FACTOR-001 ~ 003)

> **REQ-FACTOR-001 [Event-Driven]**: **WHEN** `factor_scoring.py`가 특정 종목의 composite_score를 계산할 때 **THEN** 시스템은 해당 종목이 `relation_type='holding_company'`의 source로 등록되어 있는지 확인하고, 등록되어 있다면 `holding_company_discount = -5`를 composite_score에 가산해야 한다.
> WHY: 동일한 사업 뉴스에 대해 자회사(운영 실체)가 지주사보다 composite_score 기준 상위에 랭크되도록 만든다. -5 값은 A5 가정에 따라 유의미한 랭크 변화를 유도하는 최소값이다.

> **REQ-FACTOR-002 [Event-Driven]**: **WHEN** REQ-FACTOR-001이 적용될 때 **THEN** 시스템은 `FundSignal.factor_scores` JSON에 `"holding_company_discount": -5`를 명시적으로 기록해야 한다.
> WHY: 사후 분석 및 디버깅 시 해당 종목의 점수 차감 이유가 지배구조에 기인함을 추적 가능해야 한다.

> **REQ-FACTOR-003 [Unwanted]**: 시스템은 자회사 또는 일반 단일 법인 종목에 대해 `holding_company_discount`를 **적용해서는 안 된다**. 즉, 할인은 오직 지주사(`'holding_company'` relation의 source로 등록된 종목)에만 적용되어야 한다.
> WHY: 자회사/단일 법인에 차등 할인이 누수되면 전체 시그널 생태계의 중립성이 훼손된다.

### 3.5 기존 시스템과의 호환성 (REQ-COMPAT-001 ~ 002)

> **REQ-COMPAT-001 [Unwanted]**: 시스템은 기존 signal_type(NULL, 'disclosure_impact', 'sector_ripple', 'gap_pullback_candidate')의 생성·검증·가상매매 로직을 **변경해서는 안 된다**.
> WHY: 본 SPEC은 후보 풀 확장 + composite_score 보정 + 프롬프트 강화의 3축만 다루며, 기존 시그널 생성 경로는 건드리지 않는다.

> **REQ-COMPAT-002 [Unwanted]**: 시스템은 기존 `VirtualTrade` 레코드 및 포트폴리오 상태를 **마이그레이션하거나 수정해서는 안 된다**.
> WHY: 본 SPEC은 앞으로의 후보 선택 개선이며, 과거 매매 기록에 소급 적용될 수 없다.

---

## 4. 제외사항 (Exclusions — What NOT to Build)

본 SPEC에서 다루지 **않는** 항목은 다음과 같다:

- **E1. 다단계 지배구조 추적**: HD현대 → HD한국조선해양 → HD현대중공업과 같은 다단계 구조는 초기 데이터에서 편평화하여 표현한다. 1:N 확장만 지원하며, 재귀적 1:N:M 확장은 구현하지 않는다 (REQ-CAND-003).
- **E2. 자회사 지분율 기반 가중치**: 지주사의 자회사 지분율(예: 30% vs 60%)에 따른 차등 할인은 본 SPEC에 포함되지 않는다. `-5` 고정값만 사용한다.
- **E3. DART 공시 기반 자동 관계 추출**: 자회사 관계의 초기 데이터는 **수동으로** 구축한다. DART 지분 공시를 파싱하여 자동 추출하는 로직은 미래 SPEC에서 다룬다.
- **E4. 역방향 자회사→지주사 선호**: 자회사 뉴스가 발생했을 때 지주사를 후보로 추가하는 로직은 포함하지 않는다 (자회사 뉴스는 자회사만 후보로 남긴다).
- **E5. 기존 FundSignal/VirtualTrade 재계산**: 과거 시그널의 composite_score를 소급 재계산하지 않는다 (REQ-COMPAT-002).
- **E6. 지주사 우대 케이스**: 배당·지분 평가차익 등 지주사가 오히려 유리한 뉴스 타입에 대한 역할인은 본 SPEC 범위 밖이다.
- **E7. Frontend UI 변경**: 백엔드 로직 개선만 다루며, 후보 태그·자회사 관계의 프론트엔드 시각화는 포함하지 않는다.

---

## 5. 사양 (Specifications — Logical)

본 섹션은 구현 계약(contract)만 정의한다. 구체 함수명/파일 레이아웃은 Run 단계에서 결정한다.

### 5.1 데이터 모델 변경

**`stock_relations.relation_type`**의 허용값 집합에 `'holding_company'`, `'subsidiary'` 추가.
- 데이터베이스 레벨: 체크 제약조건이 없으므로 Alembic 마이그레이션은 주석/문서 업데이트만 수행해도 되며, 모델 레이어에서 Enum을 사용하는 경우 Enum 확장이 필요하다.
- 초기 데이터 시딩: HD현대(267250)의 4개 자회사 관계 레코드 생성 (REQ-HIER-004).

### 5.2 후보 풀 확장 계층

`fund_manager.py`의 후보 수집 파이프라인에 **자회사 확장 단계(subsidiary expansion step)**를 추가한다.
- 입력: 뉴스 언급 종목 리스트
- 출력: 뉴스 언급 종목 + 해당 종목이 지주사인 경우 직속 자회사가 추가된 확장 리스트
- 각 확장 항목은 `added_via`, `parent_holding_company_id`, `parent_holding_company_name` 메타를 포함 (REQ-CAND-002).

### 5.3 브리핑 프롬프트 컨텍스트 주입 계층

브리핑 프롬프트 생성 시점에, 후보 중 지주사에 해당하는 항목을 식별하고 해당 항목에 대한 "지주사입니다. 자회사 검토 권장" 문구를 프롬프트 섹션에 포함한다 (REQ-BRIEF-001, REQ-BRIEF-002).

### 5.4 Factor Scoring 할인 팩터

`factor_scoring.py`의 composite_score 계산 파이프라인에 `holding_company_discount` 계산 단계를 추가한다.
- 지주사 판별: `stock_relations` 테이블에서 `source_stock_id == 대상 종목 && relation_type == 'holding_company'` 레코드 존재 여부로 판별
- 할인값: -5 (고정)
- factor_scores JSON에 `holding_company_discount` 키 기록 (REQ-FACTOR-002).

### 5.5 Alembic 마이그레이션

- 마이그레이션 파일: `036` 이후 순번 (down_revision은 현재 최신 리비전)
- 데이터 시딩: HD현대(267250) → [009540, 329180, 010620, 010140] 4개 레코드 삽입
- 역시딩(downgrade): 삽입한 4개 레코드 삭제

---

## 6. 관련 SPEC

- **SPEC-RELATION-001**: `StockRelation` 모델의 기반 정의 (본 SPEC이 확장함)
- **SPEC-AI-006**: factor_scoring composite_score 체계 (본 SPEC이 확장함)
- **SPEC-AI-004**: 구조적 레퍼런스 — 새 signal_type + 새 서비스 계층 추가 패턴
- **SPEC-AI-003**: 선행 기술 탐지 — `_gather_leading_candidates()` 이후 단계에 본 SPEC의 후보 확장이 삽입됨

---

## 7. 기술 제약

- Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic
- OCI VM.Standard.E2.1.Micro (1 OCPU, 1GB RAM) — `stock_relations` 조회는 기존 인덱스(`idx_stock_relations_target_stock`)를 활용하되, 추가로 `source_stock_id` + `relation_type` 조합 인덱스를 권장
- `code_comments: ko` (한국어 주석)
- `documentation: en`

---

## 8. 수용 기준 (Acceptance Criteria Summary)

전체 수용 기준은 `acceptance.md` 파일에서 Given/When/Then 형식으로 상세히 정의한다.

요약:

- **AC-HIER-001**: 마이그레이션 실행 후 `stock_relations` 테이블에 `'holding_company'` 타입의 HD현대 관계 레코드 4건이 존재한다.
- **AC-CAND-001**: 뉴스에 HD현대가 언급되면 HD한국조선해양(및 다른 3개 자회사)이 후보 풀에 포함된다.
- **AC-BRIEF-001**: HD현대가 후보에 있는 경우 브리핑 프롬프트에 "지주사입니다. 자회사: HD한국조선해양, ..." 문구가 주입된다.
- **AC-FACTOR-001**: HD현대의 composite_score가 `holding_company_discount` 팩터로 인해 -5만큼 낮아진다.

---

Version: 1.0.0
Status: Planned
Next Phase: Run (manager-ddd or manager-tdd per quality.yaml)
