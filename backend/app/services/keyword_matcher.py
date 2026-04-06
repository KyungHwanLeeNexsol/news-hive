"""키워드 매칭 및 알림 발송 서비스 (SPEC-FOLLOW-001).

신규 뉴스/공시에서 사용자 팔로잉 키워드를 매칭하고 알림을 발송한다.
"""

import asyncio
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 모듈 수준 상태: 마지막 실행 시각 (첫 실행 시 None)
_last_run: datetime | None = None

# AI 관련성 점수 임계값 (>= 통과)
RELEVANCE_THRESHOLD = 6

# 관련성 결과 캐시: {(content_type, content_id, keyword, company_name): score}
# 동일 사이클/근접 사이클 내 동일 콘텐츠 재평가 방지 (최대 2048개 LRU 흉내)
_relevance_cache: dict[tuple, int] = {}
_RELEVANCE_CACHE_MAX = 2048


def _cache_set(key: tuple, score: int) -> None:
    if len(_relevance_cache) >= _RELEVANCE_CACHE_MAX:
        _relevance_cache.pop(next(iter(_relevance_cache)))
    _relevance_cache[key] = score


def _shortcut_score(keyword: str, company_name: str, search_text: str) -> int | None:
    """AI 호출 없이 결정 가능한 shortcut 점수.

    - 키워드가 곧 기업명(또는 그 일부) → 10점 (자명한 관련)
    - 기업명이 본문에도 함께 등장 → 8점 (자명한 관련)
    - 그 외 → None (AI 평가 필요)
    """
    if not company_name:
        return None
    kw_l = keyword.lower().strip()
    name_l = company_name.lower().strip()
    if not kw_l or not name_l:
        return None
    # 키워드 = 기업명 (또는 한쪽이 다른 쪽을 포함)
    if kw_l == name_l or kw_l in name_l or name_l in kw_l:
        return 10
    # 기업명이 콘텐츠 본문에 함께 등장하면 직접 관련 가능성 높음
    if name_l in search_text:
        return 8
    return None


def _batch_evaluate(
    *,
    content_type: str,
    content_id: int,
    title: str,
    extra: str,
    search_text: str,
    pairs: list[tuple[str, str, str | None]],
) -> None:
    """한 콘텐츠에 대해 여러 (키워드, 기업명, 종목코드) 페어를 한 번의 AI 호출로 평가하고 캐시에 저장한다.

    Shortcut 적용 가능한 페어는 AI 호출 전에 캐시에 직접 저장된다.
    AI 호출 실패 시 해당 페어들은 캐시에 저장되지 않으며 호출자는 -1(폴백)로 처리한다.
    """
    # 1) Shortcut 처리 + 미해결 페어 수집
    pending: list[tuple[str, str, str | None]] = []
    seen: set[tuple] = set()
    for kw, name, code in pairs:
        cache_key = (content_type, content_id, kw, name)
        if cache_key in _relevance_cache or cache_key in seen:
            continue
        seen.add(cache_key)
        sc = _shortcut_score(kw, name, search_text)
        if sc is not None:
            _cache_set(cache_key, sc)
            continue
        pending.append((kw, name, code))

    if not pending:
        return

    # 2) 단일 AI 호출로 일괄 평가
    type_label = {"news": "뉴스", "disclosure": "공시", "report": "리포트"}.get(content_type, "콘텐츠")
    pair_lines = "\n".join(
        f'{i+1}. 키워드="{kw}", 기업명="{name}"{f" ({code})" if code else ""}'
        for i, (kw, name, code) in enumerate(pending)
    )

    prompt = (
        "당신은 금융 뉴스 관련성 분석가입니다.\n\n"
        f"다음 {type_label}이(가) 아래 각 (키워드, 기업명) 조합과 얼마나 관련 있는지 0~10으로 평가하세요.\n\n"
        f"제목: {title}\n"
        f"본문 요약: {extra}\n\n"
        "평가 대상:\n"
        f"{pair_lines}\n\n"
        "평가 기준:\n"
        "- 키워드가 해당 기업의 비즈니스/주가/실적/리스크와 직접 관련되는가\n"
        "- 단순 동음이의어/지명/인물 일치는 0~3점\n"
        "- 약한 간접 연관(산업 전반·경쟁사 언급)은 4~5점\n"
        "- 직접 관련(해당 기업과 키워드가 본질적 주제)은 6~10점\n\n"
        "JSON 배열로만 응답하세요. 다른 텍스트 금지.\n"
        '[{"i": 1, "score": 0-10}, {"i": 2, "score": 0-10}, ...]'
    )

    try:
        from app.services.ai_client import ask_ai

        response = asyncio.run(ask_ai(prompt))
        if not response:
            return

        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()

        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            return
        data = json.loads(match.group(0))
        if not isinstance(data, list):
            return

        for item in data:
            try:
                idx = int(item.get("i", 0)) - 1
                score = int(item.get("score", -1))
                if not 0 <= idx < len(pending):
                    continue
                if not 0 <= score <= 10:
                    continue
                kw, name, _code = pending[idx]
                _cache_set((content_type, content_id, kw, name), score)
            except (TypeError, ValueError):
                continue
    except Exception as e:  # noqa: BLE001
        logger.debug(f"배치 관련성 평가 실패 ({content_type}#{content_id}): {e}")


def _check_relevance(
    *,
    keyword: str,
    company_name: str,
    content_type: str,
    content_id: int,
) -> int:
    """캐시에서 관련성 점수를 조회한다. 없으면 -1 (폴백 = 발송)."""
    return _relevance_cache.get((content_type, content_id, keyword, company_name), -1)


def match_keywords_and_notify(db: Session) -> dict:
    """마지막 실행 이후 신규 뉴스/공시에서 사용자 키워드를 매칭하고 알림을 발송한다.

    Args:
        db: SQLAlchemy 세션

    Returns:
        실행 통계 딕셔너리.
        예: {"matched": 5, "notified": 3, "skipped_duplicates": 2}
    """
    global _last_run

    from app.models.news import NewsArticle
    from app.models.disclosure import Disclosure
    from app.models.following import StockFollowing, StockKeyword, KeywordNotification

    stats = {"matched": 0, "notified": 0, "skipped_duplicates": 0}

    # 마지막 실행 이후 기간 결정 (첫 실행이면 최근 1시간)
    since = _last_run if _last_run else datetime.now(timezone.utc) - timedelta(hours=1)

    # 당일 기준 시작 시각 (KST 00:00 → UTC)
    kst = timezone(timedelta(hours=9))
    today_start_kst = datetime.now(kst).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_kst.astimezone(timezone.utc)

    try:
        # 신규 뉴스 조회 (당일 발행 뉴스만)
        recent_news = (
            db.query(NewsArticle)
            .filter(
                NewsArticle.collected_at > since,
                NewsArticle.published_at >= today_start_utc,
            )
            .all()
        )

        # 신규 공시 조회 (당일 기준)
        recent_disclosures = (
            db.query(Disclosure)
            .filter(
                Disclosure.created_at > since,
                Disclosure.created_at >= today_start_utc,
            )
            .all()
        )

        # 활성 키워드를 user_id별로 그룹화
        # {user_id: [(keyword_id, keyword, stock_id), ...]}
        keyword_rows = (
            db.query(StockKeyword, StockFollowing.user_id, StockFollowing.stock_id)
            .join(StockFollowing, StockKeyword.following_id == StockFollowing.id)
            .all()
        )

        user_keywords: dict[int, list[tuple[int, str, int]]] = {}
        for kw, user_id, stock_id in keyword_rows:
            user_keywords.setdefault(user_id, []).append((kw.id, kw.keyword, stock_id))

        # stock_id → 기업명/종목코드 매핑 (알림 메시지 기업명·주가 표시용)
        from app.models.stock import Stock
        _stock_rows = db.query(Stock.id, Stock.name, Stock.stock_code).all()
        stock_name_map: dict[int, str] = {s.id: s.name for s in _stock_rows}
        stock_code_map: dict[int, str | None] = {s.id: s.stock_code for s in _stock_rows}

        if not user_keywords:
            # 팔로잉 키워드가 없으면 스킵
            _last_run = datetime.now(timezone.utc)
            return stats

        # 뉴스 매칭
        for article in recent_news:
            # 검색 텍스트: 제목 + (ai_summary 또는 content) 최대 500자
            extra = (article.ai_summary or article.content or "")[:500]
            search_text = (article.title + " " + extra).lower()

            # 콘텐츠당 1회 배치 AI 평가
            _candidate_pairs: list[tuple[str, str, str | None]] = []
            for _u, _kws in user_keywords.items():
                for _kid, _kw, _sid in _kws:
                    if len(_kw) < 2 or _kw.lower() not in search_text:
                        continue
                    _candidate_pairs.append(
                        (_kw, stock_name_map.get(_sid, ""), stock_code_map.get(_sid))
                    )
            if _candidate_pairs:
                _batch_evaluate(
                    content_type="news",
                    content_id=article.id,
                    title=article.title,
                    extra=extra,
                    search_text=search_text,
                    pairs=_candidate_pairs,
                )

            for user_id, kw_list in user_keywords.items():
                for kw_id, keyword, stock_id in kw_list:
                    # 최소 2자 이상 키워드만 매칭
                    if len(keyword) < 2:
                        continue
                    if keyword.lower() not in search_text:
                        continue

                    stats["matched"] += 1

                    # 중복 알림 확인
                    existing = (
                        db.query(KeywordNotification)
                        .filter(
                            KeywordNotification.user_id == user_id,
                            KeywordNotification.content_type == "news",
                            KeywordNotification.content_id == article.id,
                        )
                        .first()
                    )
                    if existing:
                        stats["skipped_duplicates"] += 1
                        break  # 동일 뉴스에 이미 알림 발송됨

                    # AI 관련성 게이트 (점수 < 임계값이면 스킵, -1=폴백 발송)
                    score = _check_relevance(
                        keyword=keyword,
                        company_name=stock_name_map.get(stock_id, ""),
                        content_type="news",
                        content_id=article.id,
                    )
                    if 0 <= score < RELEVANCE_THRESHOLD:
                        stats.setdefault("filtered_low_relevance", 0)
                        stats["filtered_low_relevance"] += 1
                        break

                    # 알림 발송
                    channel = _dispatch_notification(
                        db=db,
                        user_id=user_id,
                        keyword_id=kw_id,
                        content_type="news",
                        content_id=article.id,
                        content_title=article.title,
                        content_url=article.url,
                        keyword_text=keyword,
                        company_name=stock_name_map.get(stock_id, ""),
                        stock_code=stock_code_map.get(stock_id),
                    )
                    if channel != "none":
                        stats["notified"] += 1
                    break  # 사용자당 뉴스 1건에 첫 매칭 키워드만 사용

        # 공시 매칭
        for disclosure in recent_disclosures:
            extra = (disclosure.ai_summary or "")[:500]
            search_text = (disclosure.report_name + " " + disclosure.corp_name + " " + extra).lower()

            _candidate_pairs = []
            for _u, _kws in user_keywords.items():
                for _kid, _kw, _sid in _kws:
                    if len(_kw) < 2 or _kw.lower() not in search_text:
                        continue
                    _candidate_pairs.append(
                        (_kw, stock_name_map.get(_sid, ""), stock_code_map.get(_sid))
                    )
            if _candidate_pairs:
                _batch_evaluate(
                    content_type="disclosure",
                    content_id=disclosure.id,
                    title=disclosure.report_name,
                    extra=extra,
                    search_text=search_text,
                    pairs=_candidate_pairs,
                )

            for user_id, kw_list in user_keywords.items():
                for kw_id, keyword, stock_id in kw_list:
                    if len(keyword) < 2:
                        continue
                    if keyword.lower() not in search_text:
                        continue

                    stats["matched"] += 1

                    # 중복 알림 확인
                    existing = (
                        db.query(KeywordNotification)
                        .filter(
                            KeywordNotification.user_id == user_id,
                            KeywordNotification.content_type == "disclosure",
                            KeywordNotification.content_id == disclosure.id,
                        )
                        .first()
                    )
                    if existing:
                        stats["skipped_duplicates"] += 1
                        break

                    score = _check_relevance(
                        keyword=keyword,
                        company_name=stock_name_map.get(stock_id, ""),
                        content_type="disclosure",
                        content_id=disclosure.id,
                    )
                    if 0 <= score < RELEVANCE_THRESHOLD:
                        stats.setdefault("filtered_low_relevance", 0)
                        stats["filtered_low_relevance"] += 1
                        break

                    # 알림 발송
                    channel = _dispatch_notification(
                        db=db,
                        user_id=user_id,
                        keyword_id=kw_id,
                        content_type="disclosure",
                        content_id=disclosure.id,
                        content_title=disclosure.report_name,
                        content_url=disclosure.url,
                        keyword_text=keyword,
                        company_name=stock_name_map.get(stock_id, ""),
                        stock_code=stock_code_map.get(stock_id),
                    )
                    if channel != "none":
                        stats["notified"] += 1
                    break

        # 리포트 매칭 (SPEC-FOLLOW-002)
        from app.models.securities_report import SecuritiesReport

        recent_reports = (
            db.query(SecuritiesReport)
            .filter(
                SecuritiesReport.collected_at > since,
                SecuritiesReport.collected_at >= today_start_utc,
            )
            .all()
        )
        for report in recent_reports:
            search_text = (
                report.title + " " + report.company_name + " " + (report.opinion or "")
            ).lower()
            _report_extra = (report.opinion or "")[:500]

            _candidate_pairs = []
            for _u, _kws in user_keywords.items():
                for _kid, _kw, _sid in _kws:
                    if len(_kw) < 2 or _kw.lower() not in search_text:
                        continue
                    _candidate_pairs.append(
                        (_kw, stock_name_map.get(_sid, ""), stock_code_map.get(_sid))
                    )
            if _candidate_pairs:
                _batch_evaluate(
                    content_type="report",
                    content_id=report.id,
                    title=report.title,
                    extra=_report_extra,
                    search_text=search_text,
                    pairs=_candidate_pairs,
                )

            for user_id, kw_list in user_keywords.items():
                for kw_id, keyword, stock_id in kw_list:
                    if len(keyword) < 2:
                        continue
                    if keyword.lower() not in search_text:
                        continue

                    stats["matched"] += 1

                    # 중복 알림 확인
                    existing = (
                        db.query(KeywordNotification)
                        .filter(
                            KeywordNotification.user_id == user_id,
                            KeywordNotification.content_type == "report",
                            KeywordNotification.content_id == report.id,
                        )
                        .first()
                    )
                    if existing:
                        stats["skipped_duplicates"] += 1
                        break

                    score = _check_relevance(
                        keyword=keyword,
                        company_name=stock_name_map.get(stock_id, ""),
                        content_type="report",
                        content_id=report.id,
                    )
                    if 0 <= score < RELEVANCE_THRESHOLD:
                        stats.setdefault("filtered_low_relevance", 0)
                        stats["filtered_low_relevance"] += 1
                        break

                    # 알림 발송
                    channel = _dispatch_notification(
                        db=db,
                        user_id=user_id,
                        keyword_id=kw_id,
                        content_type="report",
                        content_id=report.id,
                        content_title=report.title,
                        content_url=report.url,
                        keyword_text=keyword,
                        company_name=stock_name_map.get(stock_id, ""),
                        stock_code=stock_code_map.get(stock_id),
                    )
                    if channel != "none":
                        stats["notified"] += 1
                    break

        db.commit()

    except Exception as e:
        logger.error(f"키워드 매칭 실패: {e}")
        db.rollback()
    finally:
        _last_run = datetime.now(timezone.utc)

    return stats


def _dispatch_notification(
    db: Session,
    user_id: int,
    keyword_id: int,
    content_type: str,
    content_id: int,
    content_title: str,
    content_url: str,
    keyword_text: str,
    company_name: str = "",
    stock_code: str | None = None,
) -> str:
    """알림을 발송하고 채널명을 반환한다.

    Args:
        db: SQLAlchemy 세션
        user_id: 알림 수신 사용자 ID
        keyword_id: 매칭된 키워드 ID
        content_type: 콘텐츠 유형 (news|disclosure|report)
        content_id: 콘텐츠 ID
        content_title: 콘텐츠 제목
        content_url: 콘텐츠 URL
        keyword_text: 매칭된 키워드 텍스트
        company_name: 팔로잉 종목명 (메시지 헤더에 표시)
        stock_code: 종목코드 (현재 주가 조회에 사용)

    Returns:
        사용된 채널명: "telegram" | "web_push" | "none"
    """
    from app.models.following import KeywordNotification
    from app.models.user import User
    from app.models.user import PushSubscription

    channel = "none"

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return channel

    # 현재 주가 조회 (종목코드가 있는 경우)
    price_suffix = ""
    if stock_code:
        try:
            from app.services.naver_finance import fetch_current_price_with_change
            price_data = asyncio.run(fetch_current_price_with_change(stock_code))
            if price_data:
                price = price_data["current_price"]
                rate = price_data["change_rate"]
                sign = "+" if rate >= 0 else ""
                price_suffix = f" | {price:,}원 ({sign}{rate:.2f}%)"
        except Exception as e:
            logger.debug(f"주가 조회 실패 ({stock_code}): {e}")

    # 알림 메시지 구성 (SPEC-FOLLOW-002: 리포트 타입 추가)
    type_label = {"news": "뉴스", "disclosure": "공시", "report": "리포트"}.get(content_type, "알림")
    header = f"[키워드 알림] {keyword_text}"
    if company_name:
        header = f"[키워드 알림] {keyword_text} | {company_name}{price_suffix}"
    elif price_suffix:
        header = f"[키워드 알림] {keyword_text}{price_suffix}"
    safe_url = html.escape(content_url)
    message = (
        f"<b>{header}</b>\n\n"
        f"<b>{type_label}</b>: {content_title}\n"
        f"<a href=\"{safe_url}\">자세히 보기</a>"
    )

    # 인라인 키보드: 키워드 삭제 버튼
    reply_markup = {
        "inline_keyboard": [[
            {"text": "이 키워드 삭제", "callback_data": f"del_kw:{keyword_id}"}
        ]]
    }

    # 텔레그램 우선 발송
    if user.telegram_chat_id:
        try:
            from app.services.telegram_service import send_telegram_message

            # BackgroundScheduler는 동기 컨텍스트이므로 asyncio.run() 사용
            success = asyncio.run(send_telegram_message(user.telegram_chat_id, message, reply_markup=reply_markup))
            if success:
                channel = "telegram"
        except Exception as e:
            logger.error(f"텔레그램 발송 실패 (user={user_id}): {e}")

    # 텔레그램 미발송 시 Web Push 폴백
    if channel == "none":
        subscriptions = (
            db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
        )
        if subscriptions:
            from app.services.push_service import send_push_notification

            for sub in subscriptions:
                try:
                    success = asyncio.run(
                        send_push_notification(
                            endpoint=sub.endpoint,
                            p256dh_key=sub.p256dh_key,
                            auth_key=sub.auth_key,
                            title=f"[키워드 알림] {keyword_text}",
                            body=content_title,
                            url=content_url,
                        )
                    )
                    if success:
                        channel = "web_push"
                        break
                except Exception as e:
                    logger.error(f"Web Push 발송 실패 (user={user_id}): {e}")

    if channel == "none":
        return channel

    # 알림 이력 저장
    try:
        notification = KeywordNotification(
            user_id=user_id,
            keyword_id=keyword_id,
            content_type=content_type,
            content_id=content_id,
            content_title=content_title[:500],
            content_url=content_url[:1000],
            channel=channel,
        )
        db.add(notification)
        # 커밋은 호출자(match_keywords_and_notify)가 일괄 처리
    except Exception as e:
        logger.error(f"알림 이력 저장 실패 (user={user_id}): {e}")

    return channel
