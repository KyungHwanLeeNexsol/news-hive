"""종목토론방(종토방) 크롤러 (SPEC-AI-008).

# @MX:NOTE: 종토방 크롤러. 역발상 지표용 데이터 수집
# @MX:WARN: Naver 차단 위험: 요청 간격 3초 준수, User-Agent 반드시 설정
# @MX:REASON: 과도한 요청 시 IP 차단으로 전체 크롤러 시스템 장애 발생 가능
"""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stock_forum import StockForumHourly, StockForumPost
from app.services.circuit_breaker import api_circuit_breaker as circuit_breaker

logger = logging.getLogger(__name__)

# KST 타임존
_KST = timezone(timedelta(hours=9))

# 차단 backoff 상태 (모듈 레벨 전역 — 동일 이벤트 루프 내 공유)
# @MX:WARN: 전역 상태 변이. BackgroundScheduler 스레드가 asyncio.run()으로 실행하므로
#           루프 간 경쟁 조건은 발생하지 않지만, 재시작 시 초기화됨에 유의
# @MX:REASON: 네이버 IP 차단 방어용 서킷브레이커 보조 장치
_backoff_until: datetime | None = None
_consecutive_failures: int = 0
_MAX_CONSECUTIVE_FAILURES = 5
_BACKOFF_SECONDS = 120

# 감성 분류 키워드 사전
# @MX:TODO: 키워드 사전 확장 권장 (종목별 은어 미반영)
BULLISH_KEYWORDS = [
    "매수", "올라", "상승", "돌파", "급등", "장대양봉", "목표가",
    "좋아", "✅", "🚀", "저점", "반등", "상방",
]
BEARISH_KEYWORDS = [
    "매도", "내려", "하락", "손절", "급락", "음봉",
    "별로", "😭", "📉", "고점", "폭락", "탈출",
]


def classify_sentiment(text: str) -> str:
    """게시글 제목/내용으로 감성을 분류한다.

    Args:
        text: 분류할 텍스트 (게시글 제목 또는 미리보기).

    Returns:
        "bullish" | "bearish" | "neutral"
    """
    bullish_cnt = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
    bearish_cnt = sum(1 for kw in BEARISH_KEYWORDS if kw in text)

    if bullish_cnt == 0 and bearish_cnt == 0:
        return "neutral"
    if bullish_cnt > bearish_cnt:
        return "bullish"
    if bearish_cnt > bullish_cnt:
        return "bearish"
    # 동수인 경우 neutral
    return "neutral"


def _is_market_hours() -> bool:
    """현재 시각이 KST 평일 09:00~18:00인지 확인한다."""
    now_kst = datetime.now(_KST)
    # 주말(5=토, 6=일) 제외
    if now_kst.weekday() >= 5:
        return False
    market_open = time(9, 0)
    market_close = time(18, 0)
    return market_open <= now_kst.time() <= market_close


async def crawl_stock_forum(stock_code: str, pages: int = 3) -> list[dict[str, Any]]:
    """네이버 금융 종목토론방 게시글을 크롤링한다.

    Args:
        stock_code: 종목 코드 (예: "005930").
        pages: 수집할 페이지 수 (기본 3페이지).

    Returns:
        게시글 dict 리스트. 각 항목: stock_code, content, nickname, post_date,
        view_count, agree_count, disagree_count, sentiment.
    """
    global _backoff_until, _consecutive_failures

    # 차단 backoff 중이면 빈 리스트 반환
    if _backoff_until and datetime.now(_KST) < _backoff_until:
        remaining = (_backoff_until - datetime.now(_KST)).seconds
        logger.debug(f"Forum crawler in backoff for {remaining}s (code={stock_code})")
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://finance.naver.com/item/main.naver?code={stock_code}",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    posts: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for page in range(1, pages + 1):
            url = f"https://finance.naver.com/item/board.nhn?code={stock_code}&page={page}"
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()

                # 성공 시 실패 카운터 초기화
                _consecutive_failures = 0
                _backoff_until = None

            except httpx.HTTPStatusError as e:
                _consecutive_failures += 1
                logger.warning(
                    f"Forum HTTP error {e.response.status_code} for {stock_code} page {page} "
                    f"(failures={_consecutive_failures})"
                )
                if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    _backoff_until = datetime.now(_KST) + timedelta(seconds=_BACKOFF_SECONDS)
                    try:
                        circuit_breaker.record_failure("naver_forum")
                    except Exception:
                        pass
                    logger.error(
                        f"Forum crawler circuit opened after {_consecutive_failures} failures. "
                        f"Backoff until {_backoff_until.isoformat()}"
                    )
                break

            except httpx.RequestError as e:
                _consecutive_failures += 1
                logger.error(f"Forum request error for {stock_code} page {page}: {e}")
                break

            # HTML 파싱
            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", class_="type2")
            if not table:
                logger.debug(f"No forum table found for {stock_code} page {page}")
                break

            rows = table.find_all("tr")  # type: ignore[union-attr]
            for row in rows:
                # 헤더(th 포함) 또는 빈 행 건너뜀
                if row.find("th"):
                    continue
                cols = row.find_all("td")
                if len(cols) < 6:
                    continue

                # 실제 컬럼 순서: 날짜(0), 제목(1), 작성자(2), 조회(3), 찬성(4), 반대(5)
                title_tag = cols[1].find("a")
                title_text = title_tag.get_text(strip=True) if title_tag else ""
                content = title_text[:200] if title_text else None

                nickname_tag = cols[2].find("span") or cols[2]
                nickname = nickname_tag.get_text(strip=True)[:100] if nickname_tag else None

                date_str = cols[0].get_text(strip=True)
                post_date: datetime | None = None
                if date_str:
                    for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d"):
                        try:
                            naive = datetime.strptime(date_str, fmt)
                            post_date = naive.replace(tzinfo=_KST)
                            break
                        except ValueError:
                            continue

                def _parse_int(td_tag: Any) -> int:
                    txt = td_tag.get_text(strip=True).replace(",", "")
                    try:
                        return int(txt)
                    except ValueError:
                        return 0

                view_count = _parse_int(cols[3])
                agree_count = _parse_int(cols[4])
                disagree_count = _parse_int(cols[5])

                sentiment = classify_sentiment(content or "")

                posts.append({
                    "stock_code": stock_code,
                    "content": content,
                    "nickname": nickname,
                    "post_date": post_date,
                    "view_count": view_count,
                    "agree_count": agree_count,
                    "disagree_count": disagree_count,
                    "sentiment": sentiment,
                })

            # REQ-FORUM-008: 요청 간격 3초 준수
            if page < pages:
                await asyncio.sleep(3)

    return posts


async def save_forum_posts(
    db: Session,
    stock_id: int,
    stock_code: str,
    posts: list[dict[str, Any]],
) -> int:
    """크롤링된 게시글을 DB에 저장한다 (중복 건 자동 건너뜀).

    Args:
        db: SQLAlchemy 세션.
        stock_id: 종목 PK.
        stock_code: 종목 코드.
        posts: crawl_stock_forum() 반환 리스트.

    Returns:
        신규 저장된 게시글 수.
    """
    new_count = 0
    for post_data in posts:
        # 중복 체크: (stock_code, post_date, nickname) UniqueConstraint 기준
        exists = (
            db.query(StockForumPost.id)
            .filter(
                StockForumPost.stock_code == post_data["stock_code"],
                StockForumPost.post_date == post_data["post_date"],
                StockForumPost.nickname == post_data["nickname"],
            )
            .first()
        )
        if exists:
            continue

        post = StockForumPost(
            stock_id=stock_id,
            stock_code=stock_code,
            content=post_data.get("content"),
            nickname=post_data.get("nickname"),
            post_date=post_data.get("post_date"),
            view_count=post_data.get("view_count", 0),
            agree_count=post_data.get("agree_count", 0),
            disagree_count=post_data.get("disagree_count", 0),
            sentiment=post_data.get("sentiment", "neutral"),
        )
        db.add(post)
        new_count += 1

    if new_count > 0:
        db.commit()

    return new_count


async def aggregate_forum_hourly(
    db: Session,
    stock_id: int,
) -> StockForumHourly | None:
    """최근 1시간 게시글을 집계하여 StockForumHourly를 upsert한다.

    Args:
        db: SQLAlchemy 세션.
        stock_id: 종목 PK.

    Returns:
        upsert된 StockForumHourly 레코드, 또는 게시글이 없으면 None.
    """
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    # 최근 1시간 게시글 조회
    recent_posts: list[StockForumPost] = (
        db.query(StockForumPost)
        .filter(
            StockForumPost.stock_id == stock_id,
            StockForumPost.post_date >= one_hour_ago,
        )
        .all()
    )

    total = len(recent_posts)
    bullish_count = sum(1 for p in recent_posts if p.sentiment == "bullish")
    bearish_count = sum(1 for p in recent_posts if p.sentiment == "bearish")
    neutral_count = total - bullish_count - bearish_count

    bullish_ratio = bullish_count / total if total > 0 else 0.0

    # 7일 평균 볼륨 (StockForumHourly 기준)
    seven_days_ago = now - timedelta(days=7)
    avg_result = (
        db.query(func.avg(StockForumHourly.total_posts))
        .filter(
            StockForumHourly.stock_id == stock_id,
            StockForumHourly.aggregated_at >= seven_days_ago,
        )
        .scalar()
    )
    avg_7d_volume: float = float(avg_result) if avg_result is not None else 0.0

    # 볼륨 급등 여부: 현재 볼륨이 7일 평균의 3배 이상
    volume_surge = (avg_7d_volume > 0) and (total > avg_7d_volume * 3)

    # 과열 경보: 직전 2개 시간 집계에서 모두 bullish_ratio > 0.8
    last_two: list[StockForumHourly] = (
        db.query(StockForumHourly)
        .filter(StockForumHourly.stock_id == stock_id)
        .order_by(StockForumHourly.aggregated_at.desc())
        .limit(2)
        .all()
    )
    overheating_alert = (
        len(last_two) >= 2
        and all(h.bullish_ratio > 0.8 for h in last_two)
    )

    # 시간 단위로 truncate (분·초 제거)
    aggregated_at = now.replace(minute=0, second=0, microsecond=0)

    # upsert: 같은 (stock_id, aggregated_at) 레코드가 있으면 업데이트
    existing: StockForumHourly | None = (
        db.query(StockForumHourly)
        .filter(
            StockForumHourly.stock_id == stock_id,
            StockForumHourly.aggregated_at == aggregated_at,
        )
        .first()
    )

    if existing:
        existing.total_posts = total
        existing.bullish_count = bullish_count
        existing.bearish_count = bearish_count
        existing.neutral_count = neutral_count
        existing.bullish_ratio = bullish_ratio
        existing.comment_volume = total
        existing.avg_7d_volume = avg_7d_volume
        existing.volume_surge = volume_surge
        existing.overheating_alert = overheating_alert
        record = existing
    else:
        record = StockForumHourly(
            stock_id=stock_id,
            aggregated_at=aggregated_at,
            total_posts=total,
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            neutral_count=neutral_count,
            bullish_ratio=bullish_ratio,
            comment_volume=total,
            avg_7d_volume=avg_7d_volume,
            volume_surge=volume_surge,
            overheating_alert=overheating_alert,
        )
        db.add(record)

    db.commit()
    db.refresh(record)
    return record


async def crawl_and_aggregate(
    db: Session,
    stock_id: int,
    stock_code: str,
) -> dict[str, Any]:
    """스케줄러 진입점: 크롤링 → 저장 → 집계를 순서대로 실행한다.

    장 시간(KST 평일 09:00~18:00) 외에는 건너뛴다.

    Args:
        db: SQLAlchemy 세션.
        stock_id: 종목 PK.
        stock_code: 종목 코드.

    Returns:
        요약 dict: {stock_code, new_posts, hourly_summary}
    """
    if not _is_market_hours():
        logger.debug(f"Forum crawl skipped (outside market hours): {stock_code}")
        return {"stock_code": stock_code, "new_posts": 0, "hourly_summary": None}

    posts = await crawl_stock_forum(stock_code, pages=3)
    new_posts = await save_forum_posts(db, stock_id, stock_code, posts)

    hourly = await aggregate_forum_hourly(db, stock_id)

    return {
        "stock_code": stock_code,
        "new_posts": new_posts,
        "hourly_summary": {
            "total_posts": hourly.total_posts if hourly else 0,
            "bullish_ratio": hourly.bullish_ratio if hourly else 0.0,
            "volume_surge": hourly.volume_surge if hourly else False,
            "overheating_alert": hourly.overheating_alert if hourly else False,
        },
    }
