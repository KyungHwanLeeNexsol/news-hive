# SPEC-AI-098 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `quality.yaml`
`constitution.development_mode: ddd`). 데이터 모델 변경/새 결정 가능성이 가장 큰
"어느 경계 가드를 재사용할지"(D1)와 "설정 필드를 어떻게 배선할지"(D3)를 먼저 다루고,
로깅 전용 관측성 추가(D4)와 별칭 후보 스크립트(D2)는 뒤로 미룬다 — 리뷰가 되돌리기
어려운 결정(재사용 대상 함수, 설정 필드 존재 여부)에 먼저 집중하도록 순서를 배치했다.

핵심 판단:

- 이 SPEC의 위험은 새 알고리즘을 발명하는 데 있지 않다 — 이미 검증된 두 개의 경계
  가드 중 하나를 재사용하고(D1), 이미 검증된 관측 지표 정의(AC-AI091-009)를 반복
  측정하는 것(D4)이 핵심이다. 새 위험은 오직 §문제 3(섹터 전용 스코어링)의 설정 필드가
  기본값에서 바이트 동등을 지키지 못하는 경우다.
- `theme_news_carry`/`keyword_tagging_service.py`의 기존 로직은 spec.md §Out of Scope에
  따라 완전히 무수정이다 — 이 SPEC의 어떤 TASK도 그 파일들의 동작을 바꾸지 않는다.

### A.1 수정 지점 (정확한 위치)

| 위치 | 현행 | 변경 |
|------|------|------|
| `surge_detector.py:434-438` | `v in text`, `stock.stock_code in text` 가드 없는 substring | `keyword_matcher.py`의 경계 가드 함수를 import해 동등 판정으로 교체 |
| `keyword_matcher.py` | `_keyword_in_text`가 모듈 프라이빗 | 크로스모듈 재사용을 위해 그대로 import(기존 SPEC-AI-091이 `ai_classifier._count_keyword_matches`를 `keyword_tagging_service.py`에서 크로스모듈 import한 선례를 따름 — 신규 공개 API 설계 불필요) |
| `surge_config/surge_settings.py` `ThemeClusterConfig` | — | `sector_only_penalty: float = 0.5`, `sector_only_max_candidates: int \| None = None` 신규 필드 |
| `surge_detector.py:444-449` | 하드코딩 `0.5` | `config.theme_cluster.sector_only_penalty` 참조 + 절단 로직 추가 |
| 신규 `backend/scripts/suggest_stock_name_aliases.py` | — | 한글 음역 패턴 후보 제안 스크립트(dry-run 전용, 파일 수정 없음) |
| 신규 관측 함수(위치 확정: `surge_detector.py` 또는 `keyword_tagging_service.py` 인접) | — | AC-AI091-009 지표 재계산 + `theme_news_carry` 기여 비율 로깅 |
| `scheduler.py` | — | 신규 관측 함수를 위한 잡 등록(24시간 주기 제안, `keyword_backfill`과 동일 패턴) |

경계 가드 교체의 구체 형태(구현 시 확정 — 함수를 그대로 import할지, 얇은 wrapper를
둘지는 TASK-001에서 결정):

```python
from app.services.keyword_matcher import _keyword_in_text  # 제안 — 확정은 TASK-001

def _name_or_code_in_article(needle: str, article_text: str) -> bool:
    return _keyword_in_text(needle, article_text.lower())
```

> `_keyword_in_text`는 `text`가 이미 소문자로 변환되어 있다고 가정한다(`keyword_matcher.py`
> docstring, 53행). `surge_detector.py`의 현행 코드는 소문자 변환을 하지 않으므로,
> 교체 시 `article_text.lower()` 적용이 REQ-AI098-001 이행에 필수적이다(누락 시 영문
> 별칭 매칭이 대소문자 불일치로 조용히 실패할 수 있다 — 회귀 테스트로 반드시 커버).

### A.5 PRESERVE 목록 (수정 금지)

| 대상 | 사유 |
|------|------|
| `keyword_tagging_service.py::extract_theme_keywords()`/`refresh_stock_keywords()` | SPEC-AI-091 소유, 이미 프로덕션 정화·재측정 완료 — 무수정(spec.md §Out of Scope) |
| `ai_classifier.py::_count_keyword_matches()` | 위와 동일 이유로 무수정. 본 SPEC은 별개 함수(`_keyword_in_text`)를 새 소비처에 배선한다 |
| `detect_theme_news_carry()`의 전파 로직(테마 활성 게이트, 앵커 자기제외, `max_signals_per_basket`) | REQ-AI098-006 — 재구현 금지, 관측성만 추가 |
| `surge_detector.py:284-317` (뉴스 조회, `keyword_counts` 활성 테마 판정) | REQ-AI098-001은 종목 귀속 단계에만 적용 — 테마 활성 판정 단계는 무관 |
| `surge_detector.py:378-392` (시총 필터), SPEC-AI-038 NULL 시총 언급 필터 | 포함 여부 결정 로직 — 본 SPEC은 포함 이후 점수만 다룸 |
| `_STOCK_NAME_ALIASES` 딕셔너리 자체(자동 수정 금지) | REQ-AI098-002 — 사람 검토 없이 자동 변경 금지 |
| `stocks.keywords` 데이터, 관련 마이그레이션 | 재백필/재정화 범위 밖 |
| `ThemeGroupCarryConfig`/`detect_theme_group_carry_forward()` | 별개 탐지기(SPEC-AI-025), 무관 |

## B. 작업 분해

### TASK-001: 경계 가드 교체 (REQ-AI098-001)

- 대상: `backend/app/services/surge_detector.py` `detect_theme_news_cluster()`
- `keyword_matcher.py::_keyword_in_text`를 import해 `stock_articles` 리스트
  컴프리헨션(434-438행)의 매칭 판정을 교체한다. 이름 변형(`_name_variants`)과
  종목코드 양쪽에 적용한다.
- 소문자 변환(`article_text.lower()`) 누락 여부를 명시적으로 검증한다(A.1 경고 참고).
- `@MX:SPEC` 서브라인에 `SPEC-AI-098 REQ-AI098-001` 추가.

추적: REQ-AI098-001 / AC-098-001, AC-098-002

### TASK-002: 섹터 전용 스코어링 설정화 (REQ-AI098-003)

- 대상: `backend/app/surge_config/surge_settings.py`(`ThemeClusterConfig`),
  `backend/app/services/surge_detector.py:444-449`
- `sector_only_penalty: float = 0.5`, `sector_only_max_candidates: int | None = None`
  신규 필드 추가. 필드 주석에 "기본값 변경 없이는 현행과 바이트 동등, 활성화 시
  섹터 전용 후보 수가 줄어들 수 있음" 명시.
- 섹터 전용 분기(449행)에서 하드코딩 `0.5` 대신 `config.sector_only_penalty` 참조.
- `sector_only_max_candidates`가 설정된 경우, 함수 반환 직전(섹터 전용 후보만 대상)
  `theme_cluster_score` 내림차순 상위 N개만 유지하는 절단 로직 추가. 직접 언급 종목은
  이 절단의 영향을 받지 않는다.

추적: REQ-AI098-003 / AC-098-003, AC-098-004, AC-098-005

### TASK-003: 별칭 후보 제안 스크립트 (REQ-AI098-002)

- 대상: 신규 `backend/scripts/suggest_stock_name_aliases.py`
- 기존 11개 별칭에서 관찰되는 "한글 음역 영문 접미어" 매핑(에스=S, 케이=K, 엘지=LG,
  디=D 등, 구현 시 확정할 매핑 표)을 규칙으로 삼아, `_STOCK_NAME_ALIASES`에 없는 종목명
  중 이 패턴에 해당하는 후보를 DB 전체 종목명 대상으로 스캔해 콘솔에 출력한다.
- `remediate_keyword_tagging.py`의 dry-run 관례를 따르되, 이 스크립트는 애초에 DB나
  코드 파일을 수정하는 `--execute` 모드 자체가 없다(순수 후보 나열).
- `_STOCK_NAME_ALIASES` 딕셔너리는 절대 자동 수정하지 않는다 — 사람이 후보를 검토해
  수동으로 추가한다.

추적: REQ-AI098-002 / AC-098-006

### TASK-004: `theme_news_carry` 관측성 로깅 (REQ-AI098-004, REQ-AI098-005)

- 대상: 신규 함수(위치는 `keyword_tagging_service.py` 인접 또는 `surge_detector.py`
  인접 중 구현 시 확정 — 관측 대상이 `stocks.keywords`이므로 전자가 더 응집도 높음)
- AC-AI091-009와 동일한 SQL 집계(10개 보유 비율, 키워드 개수 중앙값)를 계산해 로그로
  남긴다.
- `surge_backtest.py::_extract_combo_key()`를 재사용해 당일 `surge_candidate` 시그널
  중 `theme_news_carry` 포함 비율을 계산해 로그로 남긴다.
- 계산 실패는 `try/except` + 로그로 격리하고 다른 스케줄 잡에 영향을 주지 않는다
  (`@retry_with_backoff` 기존 관례 재사용).
- Should-Pass: 비율이 설정 임계값(신규 config 필드, 기본값은 Open Question 2에 따라
  구현 시 보수적으로 설정하거나 비활성)을 초과하면 기존 `send_telegram_message` 재사용.

추적: REQ-AI098-004, REQ-AI098-005 / AC-098-007, AC-098-008, AC-098-009

### TASK-005: 스케줄러 잡 등록

- 대상: `backend/app/services/scheduler.py`
- TASK-004의 관측 함수를 24시간 주기 잡으로 등록(`keyword_backfill`과 동일한
  `add_job(..., "interval", hours=24, id="theme_carry_observability", replace_existing=True)`
  패턴).
- 이 24시간 주기는 잠정 설계다 — spec.md §Open Questions 1(일 1회 vs 스캔
  사이클마다)이 구현 착수 전 확정되지 않으면, 이 TASK의 스케줄 등록 방식을
  그 결정에 맞춰 조정한다(예: 스캔 사이클마다 실행이 확정되면 별도 interval
  잡 대신 기존 스캔 파이프라인 훅에 연결).

추적: REQ-AI098-004, REQ-AI098-005 / AC-098-007, AC-098-008

### TASK-006: 무회귀·신규 검증

- 대상: 신규 `backend/tests/test_spec_ai_098.py`
- 케이스: 경계 가드 적용 전/후 매칭 결과 비교(자회사/별칭 케이스로 개선 확인, 오탐
  후보로 회귀 없음 확인), 섹터 전용 설정 기본값 바이트 동등, `sector_only_max_candidates`
  절단 동작, 관측 로그 필드 존재(`caplog`), `theme_news_carry`/`keyword_tagging_service.py`
  무수정 확인(diff grep).
- 기존 테스트(`test_spec_ai_012.py`/`test_spec_ai_014.py`/`test_spec_ai_038.py`/
  `test_spec_ai_091.py`/`test_keyword_tagging_service.py` 등, 실제 파일명은 구현 시
  `ls backend/tests/`로 재확인) 전체 무수정 통과 확인.

추적: REQ-AI098-001~006 전체 / AC-098-001~010

## C. 검증 계획

타겟 테스트:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_098.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_keyword_tagging_service.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_091.py -q
```

전체 회귀:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q -m "not slow"
```

정적 검사:

```powershell
.\backend\.venv\Scripts\ruff.exe check .\backend
.\backend\.venv\Scripts\python.exe -m mypy .\backend\app
```

범위 규율 grep (기존 검증된 경로 무변경 확인, REQ-AI098-006):

```bash
git diff --name-only | grep -E 'keyword_tagging_service\.py'
# 기대: 0 매치 (신규 관측 함수를 이 파일에 배치하기로 확정한 경우, 이 grep은
# TASK-004 구현 위치 확정 이후 plan.md 갱신과 함께 조정한다 — 현재는 잠정 가드)
```

> 검증 계획 주의: TASK-004의 관측 함수 배치 위치가 `keyword_tagging_service.py`
> 인접으로 확정되면, 위 grep은 "로직 함수 추가"와 "기존 함수 수정"을 구분해야 한다.
> 이 grep은 후자(기존 함수 수정)만 0건이어야 함을 검증하는 것이 목적이며, 신규 함수
> 추가로 인한 파일 diff 자체는 REQ-AI098-006 위반이 아니다 — 실제 사용할 검증은
> `git diff <파일> -- :^backend/tests` 후 `extract_theme_keywords`/
> `refresh_stock_keywords`/`_count_keyword_matches` 함수 본문에 변경이 없는지 코드
> 리뷰로 확인한다(자동 grep만으로는 완전히 커버되지 않음 — Gap으로 progress.md에
> 기록).

## D. 배포/롤백

TASK-001(경계 가드)은 즉시 동작 변화를 일으킨다 — 이전에 매칭되지 않던 자회사/별칭
언급이 매칭되기 시작하므로 `theme_cluster` 후보 구성이 바뀔 수 있다. TASK-002(섹터
전용 설정화)는 기본값에서 바이트 동등이므로 배포 자체는 무해하다. TASK-003(별칭
스크립트)/TASK-004~005(관측성)는 관측 전용, 프로덕션 매매/시그널 로직에 영향 없음.

롤백 트리거:

- TASK-001 배포 후 `theme_cluster` 후보 수가 급격히(예: 2배 이상) 증가 → 경계 가드가
  의도치 않게 완화 방향으로 작동했을 가능성, 즉시 조사
- 기존 `test_spec_ai_012.py`/`test_spec_ai_014.py`류 characterization 테스트가 깨짐
  → 즉시 되돌림
- 관측 잡(TASK-005)이 다른 스케줄 잡의 실행 시간에 영향 → 관측 잡만 비활성화

롤백 단위: TASK-001은 import를 되돌리고 원래 substring 컴프리헨션으로 복귀하면 완전
복구. TASK-002는 설정 필드가 기본값이면 무해하므로 롤백 불필요. TASK-003~005는 독립
파일/함수이므로 삭제만으로 완전 롤백된다.

## E. 리스크

- **경계 가드 강화로 인한 후보 수 변화의 방향 불확실성**: TASK-001은 "놓치던 매칭을
  잡는" 개선과 "우연히 맞던 매칭을 거르는" 회귀를 동시에 일으킬 수 있다(경계 가드는
  양쪽으로 작용). 순net 효과는 사전에 정량 예측할 수 없다 — TASK-006 회귀 테스트가
  대표 사례만 커버하며, 실제 운영 영향은 배포 후 관찰 대상이다.
- **소문자 변환 누락 위험**: A.1에서 명시한 `_keyword_in_text`의 소문자 입력 가정을
  놓치면 영문 별칭(SKT, LG전자 등) 매칭이 조용히 실패한다 — TASK-006에 영문 별칭
  회귀 케이스를 반드시 포함해야 한다.
- **별칭 후보 스크립트의 오탐 후보 생성 위험**: 한글 음역 규칙은 완벽하지 않다(예:
  우연히 음역 패턴처럼 보이는 순우리말 종목명). 사람 검토 단계가 유일한 방어선이다
  (D2) — 스크립트 자체가 표를 수정하지 않으므로 최악의 경우도 "쓸모없는 후보 목록"에
  그친다.
- **관측 로깅만으로는 재발을 놓칠 수 있다**: REQ-AI098-004/005는 로그 라인 생성까지만
  Must-Pass다. 아무도 로그를 정기적으로 확인하지 않으면 실효성이 없다 — Should-Pass인
  Telegram 경보(임계값 미확정)가 이 리스크를 완화하나, 본 SPEC 범위에서는 확정하지
  않는다(Open Question 2).
- **`theme_news_carry` 재발 감지의 관측 기간 부재**: 재활성화(오늘) 이후 "정상" 기준선
  데이터가 아직 없다. 관측 함수 배포 직후 며칠간은 임계값 판단 근거가 부족하다는 점을
  인지하고 있어야 한다.
