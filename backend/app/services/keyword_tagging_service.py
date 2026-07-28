"""SPEC-AI-084 그룹 C: 뉴스/공시 텍스트 기반 종목 테마 키워드 태깅 서비스.

``stocks.keywords``(ARRAY(Text), 기존 컬럼 — 마이그레이션 불필요)를 뉴스
(``NewsStockRelation`` 조인)/공시(``Disclosure``) 텍스트에서 추출한 테마 키워드로 채운다.
그룹 A(``detect_theme_news_carry``)가 소비하는 키워드 바스켓 데이터의 유일한 채움 경로다.

설계 결정 (OQ-1, plan.md 권고 계승 — 규칙/사전 우선):
    ``ThemeClusterConfig.keywords``(surge_detection.yaml에 이미 존재하는 20개 테마 어휘,
    theme_cluster 탐지기와 공유)를 재사용해 뉴스/공시 텍스트에 단순 포함(substring) 매칭한다.
    신규 LLM 인프라를 도입하지 않으므로 무유계 LLM 호출 자체가 존재하지 않아
    REQ-AI084-004(b)(예산 폭발 금지)가 구조적으로 충족된다.

멱등/무오염 설계 (REQ-AI084-004(a)):
    ``stocks.keywords``가 NULL 또는 빈 배열인 종목만 배치 백필 대상으로 삼는다. 수동 설정
    키워드(``routers/stocks.py`` API)나 이전 자동 태깅 결과는 항상 비어있지 않은 배열이므로
    구조적으로 재작성되지 않는다. following 시스템의 ``StockKeyword``/``StockFollowing``
    테이블은 이 서비스에서 전혀 참조·변경하지 않는다([X-8]).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.disclosure import Disclosure
from app.models.news import NewsArticle
from app.models.news_relation import NewsStockRelation
from app.models.stock import Stock
from app.services.ai_classifier import _count_keyword_matches

logger = logging.getLogger(__name__)

# REQ-AI084-003: 종목당 키워드 상한 (무한 증식 방지)
DEFAULT_MAX_KEYWORDS_PER_STOCK = 10

# REQ-AI091-002: 테마 키워드가 매칭으로 인정되기 위한 최소 서로 다른 소스 텍스트 출현 수.
# 단일 시황/묶음 기사의 우연한 언급 하나만으로 무관 종목에 테마가 전파되는 것을 방지한다.
# plan-phase 제안값(DP-2) — M3 재백필 실측 결과로 조정 여지를 남긴다(하드코딩 금지).
DEFAULT_MIN_TEXT_OCCURRENCES = 2

# 종목별 텍스트 조회 건수 상한 — 배치 비용을 유계화한다(REQ-AI084-002).
_MAX_ARTICLES_PER_STOCK = 50
_MAX_DISCLOSURES_PER_STOCK = 20


@dataclass
class KeywordTaggingResult:
    """백필 실행 결과 집계 (관측성 전용, 스키마 없음)."""

    stocks_scanned: int = 0
    stocks_tagged: int = 0
    stocks_skipped_existing: int = 0
    keywords_added_total: int = 0


def _default_theme_keywords() -> list[str]:
    """테마 어휘 소스: ``ThemeClusterConfig.keywords``(기존 자산 재사용, [E-4]).

    지연 임포트로 순환 임포트를 회피한다 — ``app.surge_config``는 이 서비스에 의존하지 않는다.
    """
    from app.surge_config.surge_settings import get_surge_config

    return list(get_surge_config().theme_cluster.keywords)


def _gather_stock_theme_texts(db: Session, stock_id: int) -> list[str]:
    """종목에 연결된 최근 뉴스(제목+본문)와 공시(보고서명) 텍스트를 조회한다.

    REQ-AI084-001 근거: ``NewsStockRelation`` 조인(뉴스) + ``Disclosure.stock_id``(공시).

    REQ-AI091-001: ``NewsStockRelation.relevance == "direct"``인 행에서 나온 뉴스
    텍스트만 반환한다 — "indirect"(같은 섹터/키워드를 공유할 뿐인 약한 신호) 텍스트는
    제외해, 관계 생성 시점에 이미 확립된 direct/indirect 신뢰도 구분을 텍스트 수집
    단계에도 일관되게 적용한다. 공시(disclosure) 조회는 ``relevance`` 개념이 없으므로
    (Disclosure.stock_id 직접 연결) 이 필터의 대상이 아니다.
    """
    news_rows = (
        db.query(NewsArticle.title, NewsArticle.content)
        .join(NewsStockRelation, NewsStockRelation.news_id == NewsArticle.id)
        .filter(NewsStockRelation.stock_id == stock_id)
        .filter(NewsStockRelation.relevance == "direct")
        .order_by(NewsArticle.id.desc())
        .limit(_MAX_ARTICLES_PER_STOCK)
        .all()
    )
    texts = [f"{title or ''} {content or ''}" for title, content in news_rows]

    disclosure_rows = (
        db.query(Disclosure.report_name)
        .filter(Disclosure.stock_id == stock_id)
        .order_by(Disclosure.id.desc())
        .limit(_MAX_DISCLOSURES_PER_STOCK)
        .all()
    )
    texts.extend(name for (name,) in disclosure_rows if name)
    return texts


def extract_theme_keywords(
    texts: list[str],
    theme_keywords: list[str] | None = None,
    min_text_occurrences: int = DEFAULT_MIN_TEXT_OCCURRENCES,
) -> list[str]:
    """개별 소스 텍스트 목록에서 테마 키워드 매칭 결과를 반환한다(규칙/사전 기반, LLM 미사용).

    REQ-AI091-002: 하나의 연결된 blob(``" ".join(texts)``)이 아니라 각 텍스트를 개별
    순회하며, 테마 키워드가 최소 ``min_text_occurrences``개의 **서로 다른** 텍스트에
    출현할 때만 매칭 결과에 포함한다 — 단일 시황/묶음 기사가 우연히 언급한 무관 테마
    단어가 연결 종목 전체에 전파되는 것을 방지한다.

    REQ-AI091-003: 매칭 위치 직전 문자가 한글 음절이면 해당 매칭을 거부하는 경계 가드는
    ``ai_classifier.py::_count_keyword_matches``의 기존 패턴을 그대로 재사용한다
    (Enforce Simplicity — 신규 로직을 발명하지 않는다).

    Args:
        texts: 종목에 연결된 뉴스 제목/본문, 공시 보고서명 등 개별 원문 텍스트 목록.
        theme_keywords: 매칭 대상 테마 어휘. None이면 ``ThemeClusterConfig.keywords`` 사용.
        min_text_occurrences: 키워드가 매칭으로 인정되기 위한 최소 서로 다른 텍스트
            출현 수(기본값 2 — 하드코딩 금지, 테스트/재캘리브레이션 용이성을 위해 파라미터화).

    Returns:
        매칭된 테마 키워드 목록(어휘 등장 순서, 중복 제거).
    """
    vocab = theme_keywords if theme_keywords is not None else _default_theme_keywords()
    matched: list[str] = []
    for kw in vocab:
        if not kw:
            continue
        occurrence_count = sum(
            1 for text in texts if text and _count_keyword_matches(text, [kw]) > 0
        )
        if occurrence_count >= min_text_occurrences:
            matched.append(kw)
    return matched


def backfill_stock_keywords(
    db: Session,
    theme_keywords: list[str] | None = None,
    max_keywords_per_stock: int = DEFAULT_MAX_KEYWORDS_PER_STOCK,
) -> KeywordTaggingResult:
    """REQ-AI084-002: 기존 추적 종목 유니버스에 대해 1회성 배치 백필을 수행한다.

    ``stocks.keywords``가 NULL 또는 빈 배열인 종목만 대상으로 하므로 유니버스 크기에 비례한
    유계 비용이고 멱등하다 — 이미 채워진(수동 설정 포함) 종목은 재실행 시 건드리지 않는다
    (REQ-AI084-004(a)).
    """
    vocab = theme_keywords if theme_keywords is not None else _default_theme_keywords()
    result = KeywordTaggingResult()

    stocks = db.query(Stock).all()
    result.stocks_scanned = len(stocks)

    for stock in stocks:
        if stock.keywords:
            # 이미 값이 있는 종목(수동 설정 포함)은 절대 건드리지 않는다 — 멱등 + 무오염.
            result.stocks_skipped_existing += 1
            continue

        try:
            texts = _gather_stock_theme_texts(db, stock.id)
        except Exception as e:
            logger.warning("[keyword_tagging] 텍스트 조회 실패 (stock_id=%s): %s", stock.id, e)
            continue

        if not texts:
            continue

        matched = extract_theme_keywords(texts, vocab)[:max_keywords_per_stock]
        if not matched:
            continue

        stock.keywords = matched
        result.stocks_tagged += 1
        result.keywords_added_total += len(matched)

    if result.stocks_tagged:
        db.commit()

    logger.info(
        "[keyword_tagging] 배치 백필 완료: 스캔 %d개, 신규 태깅 %d개, 기존 보존(스킵) %d개",
        result.stocks_scanned,
        result.stocks_tagged,
        result.stocks_skipped_existing,
    )

    return result


def refresh_stock_keywords(
    db: Session,
    stock_ids: list[int],
    theme_keywords: list[str] | None = None,
    max_keywords_per_stock: int = DEFAULT_MAX_KEYWORDS_PER_STOCK,
) -> int:
    """REQ-AI084-003: 신규 뉴스/공시가 유입된 종목에 대해 keywords를 갱신한다(지속 태깅).

    기존 키워드를 삭제하지 않고 신규 매칭 키워드를 병합(merge)한 뒤 종목당 상한으로 캡해
    무한 증식을 방지한다. 뉴스 크롤 배치 완료 훅에서 호출되며(수집 훅 방식, OQ-6 결정),
    이번 배치에서 신규 뉴스/공시가 유입된 종목으로만 스캔 범위를 한정해 비용을 유계화한다.

    Args:
        stock_ids: 이번 배치에서 신규 뉴스/공시가 유입된 종목 id 목록.

    Returns:
        keywords가 갱신된 종목 수.
    """
    if not stock_ids:
        return 0

    vocab = theme_keywords if theme_keywords is not None else _default_theme_keywords()
    updated = 0

    for stock_id in set(stock_ids):
        try:
            stock = db.query(Stock).filter(Stock.id == stock_id).first()
            if stock is None:
                continue

            texts = _gather_stock_theme_texts(db, stock_id)
            if not texts:
                continue

            matched = extract_theme_keywords(texts, vocab)
            if not matched:
                continue

            existing = list(stock.keywords) if stock.keywords else []
            merged = existing + [kw for kw in matched if kw not in existing]
            capped = merged[:max_keywords_per_stock]

            if capped != existing:
                stock.keywords = capped
                updated += 1
        except Exception as e:
            logger.warning("[keyword_tagging] 지속 태깅 실패 (stock_id=%s): %s", stock_id, e)
            continue

    if updated:
        db.commit()
        logger.info("[keyword_tagging] 지속 태깅 갱신: %d개 종목", updated)

    return updated
