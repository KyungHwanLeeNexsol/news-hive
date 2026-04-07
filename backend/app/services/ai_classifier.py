import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# KeywordIndex 캐시 (모듈 레벨)
# 단일 워커(uvicorn) 환경을 전제로 하므로 스레드 안전성 고려하지 않음.
# ---------------------------------------------------------------------------
_cached_index: Optional["KeywordIndex"] = None
_cache_checkpoint: Optional[tuple[int, int, Optional[datetime], Optional[datetime]]] = None


@dataclass
class KeywordIndex:
    """Pre-built index for fast keyword matching against stock/sector names."""
    # stock_name -> (stock_id, sector_id)
    stock_names: dict[str, tuple[int, int]] = field(default_factory=dict)
    # keyword_lower -> list of (stock_id, sector_id)
    stock_keywords: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    # sector_keyword_lower -> sector_id
    sector_keywords: dict[str, int] = field(default_factory=dict)

    @classmethod
    def build(cls, sectors: list[Sector], stocks: list[Stock]) -> "KeywordIndex":
        idx = cls()
        sector_has_stock: set[int] = set()

        for stock in stocks:
            idx.stock_names[stock.name] = (stock.id, stock.sector_id)
            sector_has_stock.add(stock.sector_id)
            if stock.keywords:
                for kw in stock.keywords:
                    kw_lower = kw.lower()
                    if kw_lower not in idx.stock_keywords:
                        idx.stock_keywords[kw_lower] = []
                    idx.stock_keywords[kw_lower].append((stock.id, stock.sector_id))

        for sector in sectors:
            for kw in _extract_sector_keywords(sector.name):
                if kw not in idx.sector_keywords:
                    idx.sector_keywords[kw] = sector.id

        return idx


def get_or_build_index(db: Session) -> "KeywordIndex":
    """KeywordIndex를 캐시에서 반환하거나, 변경 감지 시 새로 빌드한다.

    체크포인트 = (stock_count, sector_count, max_stock_created_at, max_sector_created_at)
    stocks/sectors 테이블에 updated_at이 없으므로 COUNT + MAX(created_at)로 변경 감지.
    단일 워커(uvicorn) 환경 전제 — 스레드 안전성 불필요.
    """
    global _cached_index, _cache_checkpoint

    stock_count = db.query(func.count(Stock.id)).scalar() or 0
    sector_count = db.query(func.count(Sector.id)).scalar() or 0
    max_stock_created = db.query(func.max(Stock.created_at)).scalar()
    max_sector_created = db.query(func.max(Sector.created_at)).scalar()

    current_checkpoint = (stock_count, sector_count, max_stock_created, max_sector_created)

    if _cached_index is not None and _cache_checkpoint == current_checkpoint:
        logger.info("KeywordIndex: cache hit")
        return _cached_index

    # 캐시 미스 — 전체 재빌드
    sectors = db.query(Sector).all()
    stocks = db.query(Stock).all()
    _cached_index = KeywordIndex.build(sectors, stocks)
    _cache_checkpoint = current_checkpoint
    logger.info("KeywordIndex: cache miss (rebuilt)")
    return _cached_index


# Patterns indicating non-financial content (entertainment, sports, lifestyle, etc.)
_NON_FINANCIAL_PATTERNS: list[str] = [
    # TV/Entertainment — shows
    "동상이몽", "흑백요리사", "나는솔로", "나솔사제", "솔로지옥", "런닝맨", "무한도전",
    "놀면뭐하니", "전참시", "전지적참견시점", "라디오스타", "1박2일",
    "나혼자산다", "신서유기", "삼시세끼", "슈퍼맨이돌아왔다", "편스토랑",
    "예능", "드라마", "시청률", "방영", "출연", "MC", "리얼리티",
    # K-Pop / Artists
    "아이돌", "걸그룹", "보이그룹", "컴백", "음원", "뮤직비디오",
    "K-POP", "K팝", "케이팝", "팬미팅", "콘서트",
    "데뷔", "신보", "정규앨범", "미니앨범", "음반",
    "팬클럽", "팬덤", "팬사인회",
    "가수", "오디션", "트로트",
    # Film / Streaming
    "배우", "연기", "영화", "개봉", "흥행", "박스오피스",
    "넷플릭스", "디즈니플러스", "티빙", "쿠팡플레이", "웨이브",
    "뮤지컬",
    # Celebrity / Influencer
    "연예", "결혼", "열애", "파경", "이혼", "스캔들",
    "유튜버", "인플루언서", "크리에이터",
    # Sports (non-business context)
    "프로야구", "KBO", "K리그", "프로축구", "NBA", "MLB",
    "올림픽", "월드컵", "감독", "선발", "홈런", "타율",
    "득점", "골", "어시스트", "선수", "경기", "우승",
    # Lifestyle / Food
    "맛집", "레시피", "다이어트", "건강법", "운동법",
    # Weather / Nature (non-business)
    "일기예보", "기상청",
    # Photo / Video only articles (no real content)
    "[포토]", "[사진]", "[영상]", "[화보]", "[포토뉴스]",
    "[Photo]", "[VIDEO]",
    # Politics — parties & elections
    "국회의원", "대통령", "총리", "장관", "청와대", "용산",
    "여당", "야당", "정당", "국정감사", "국정조사", "탄핵", "공천", "당대표",
    "민주당", "국민의힘", "더불어민주당", "정의당",
    "대선", "총선", "보궐선거", "지방선거", "지선",
    "당선인", "낙선", "출마선언",
    "여야", "야권", "여권", "정치권", "정치인",
    "집권", "정권교체",
    "청문회", "대정부질문",
    "탈당", "입당", "대표경선",
    "자산공개", "재산공개", "슈퍼리치", "재산신고",
    # Government fiscal policy (macro, not direct market news)
    "추경", "추가경정", "본예산", "재정준칙", "나라살림",
    # Crime / Social (non-business context)
    "검찰", "경찰", "구속", "기소", "체포", "재판", "판결", "혐의",
    "사건", "사고", "사망", "범죄", "살인", "폭행", "피의자",
    # TV schedules / program highlights (non-investment)
    "TV하이라이트", "방송하이라이트", "오늘의TV", "편성표", "TV편성",
    "▣TV", "▣MBC", "▣KBS", "▣SBS", "▣JTBC", "▣tvN", "▣채널",
    # Local government / public welfare announcements (non-market)
    "통합돌봄", "복지급여", "육아나눔터", "공동육아나눔터", "돌봄센터",
    "해충방제", "전기포충기", "흡연위해예방", "흡연예방교실", "금연교실",
    "방역소독", "예방접종", "무상급식", "기초생활수급",
    "요양통합", "방문요양", "재가서비스", "노인돌봄",
    # Community / social welfare (지자체 보도자료 패턴)
    "찾아가는 유아", "찾아가는 어르신", "사각지대 해소", "복지사각지대",
    "위기가구 발굴", "수급자격",
    # Social isolation / welfare
    "고독사", "안부 확인 서비스", "이상징후 감지 출동",
    # Cultural festivals and events (non-investment)
    "문화축전", "궁중문화", "궁중 체험", "궁중새내기",
    "참여형 축제", "시간여행 체험",
    # Government-funded arts organizations (non-investment)
    "도립무용단", "시립무용단", "국립무용단", "도립교향악단",
    "문예회관", "무용단 공연",
    # Museum / gallery events (non-investment)
    "박물관·미술관", "박물관 주간", "미술관 주간",
    # Local government civic / aesthetic projects
    "불법 주정차", "주정차 신고", "교통행정 운영",
    "간판개선", "불법 광고물 정비",
]

# Compile regex for non-financial detection
_NON_FINANCIAL_RE = re.compile(
    "|".join(re.escape(p) for p in _NON_FINANCIAL_PATTERNS),
    re.IGNORECASE,
)


# Foreign non-investment source domains/suffixes in title or URL
# Note: Reuters, BBC, Bloomberg, CNBC etc. are ALLOWED (major financial sources)
_FOREIGN_SOURCE_PATTERNS = re.compile(
    r"(?:Vietnam\.vn|VnExpress|Thanh Niên|Tuổi Trẻ"
    r"|thehindu|timesofindia|dawn\.com|inquirer\.net"
    r"|rappler\.com|bangkokpost)",
    re.IGNORECASE,
)


def is_non_financial_article(title: str, url: str = "", description: str = "") -> bool:
    """Check if an article title/description indicates non-financial content.

    Covers entertainment/sports/lifestyle keywords, photo-only articles,
    and foreign non-investment news sources.
    """
    if _NON_FINANCIAL_RE.search(title):
        return True

    if description and _NON_FINANCIAL_RE.search(description):
        return True

    # Foreign source detection (by title suffix or URL)
    if _FOREIGN_SOURCE_PATTERNS.search(title) or _FOREIGN_SOURCE_PATTERNS.search(url):
        return True

    return False


# ---------------------------------------------------------------------------
# 소스 신뢰도 5단계 매핑
# ---------------------------------------------------------------------------
SOURCE_CREDIBILITY: dict[str, float] = {
    # Tier 1 (1.0x): 주요 경제지
    "한국경제": 1.0, "매일경제": 1.0, "서울경제": 1.0, "이데일리": 1.0,
    "머니투데이": 1.0, "한경": 1.0, "매경": 1.0, "서경": 1.0,
    "파이낸셜뉴스": 1.0, "아시아경제": 1.0, "헤럴드경제": 1.0,
    # Tier 2 (0.85x): 종합 일간지
    "조선일보": 0.85, "중앙일보": 0.85, "동아일보": 0.85,
    "한겨레": 0.85, "경향신문": 0.85, "조선비즈": 0.85,
    # Tier 3 (0.7x): 통신사 및 방송
    # 크롤러 집계 소스 (aggregator): 다양한 언론사 기사를 수집하므로 중간값 부여
    "naver": 0.75,    # 네이버 뉴스: 대부분 공신력 있는 언론사 기사
    "google": 0.70,   # 구글 뉴스: 다양한 소스 혼재
    "yahoo": 0.65,    # 야후 파이낸스: 영문 중심
    "korean_rss": 0.80,  # 한국 경제지 RSS 직접 수집
    "us_news": 0.70,  # 미국 업종별 뉴스
    # Tier 3 (0.7x): 통신사 및 방송
    "연합뉴스": 0.7, "뉴스1": 0.7, "뉴시스": 0.7,
    "YTN": 0.7, "SBS": 0.7, "KBS": 0.7, "MBC": 0.7, "JTBC": 0.7,
    # Tier 4 (0.5x): 전문지/온라인 매체
    "더벨": 0.5, "인포스탁데일리": 0.5, "팍스넷": 0.5,
    "이투데이": 0.5, "데일리안": 0.5, "뉴데일리": 0.5,
    # Tier 5 (0.3x): 기타 — 알 수 없는 소스 기본값
}

# 소스명 정규화를 위한 별칭 매핑
_SOURCE_ALIASES: dict[str, str] = {
    "한경": "한국경제", "매경": "매일경제", "서경": "서울경제",
    "조선비즈": "조선일보", "조비즈": "조선비즈",
}


def get_source_credibility(source: str) -> float:
    """소스 이름으로 신뢰도 가중치를 반환한다.

    정확히 매칭되지 않으면 부분 문자열 매칭을 시도하고,
    그래도 없으면 기본값 0.5를 반환한다.
    """
    if not source:
        return 0.5

    # 정확 매칭
    if source in SOURCE_CREDIBILITY:
        return SOURCE_CREDIBILITY[source]

    # 별칭 매칭
    if source in _SOURCE_ALIASES:
        canonical = _SOURCE_ALIASES[source]
        return SOURCE_CREDIBILITY.get(canonical, 0.5)

    # 부분 문자열 매칭 (소스명이 키를 포함하거나 키가 소스명을 포함)
    source_lower = source.lower()
    for key, weight in SOURCE_CREDIBILITY.items():
        if key.lower() in source_lower or source_lower in key.lower():
            return weight

    # 미매핑 소스 로깅
    logger.debug(f"미매핑 소스 신뢰도: '{source}' → 기본값 0.5")
    return 0.5


# ---------------------------------------------------------------------------
# 금융 키워드 및 관련성 점수 계산
# ---------------------------------------------------------------------------
FINANCIAL_KEYWORDS = [
    "실적", "영업이익", "매출", "순이익", "배당", "수주", "계약",
    "인수", "합병", "M&A", "IPO", "유상증자", "무상증자", "자사주",
    "공시", "분기", "반기", "결산",
]


def calculate_relevance_score(
    title: str,
    description: str | None,
    stock_name: str | None,
    sector_name: str | None,
    is_ai_classified: bool = False,
    source: str | None = None,
) -> int:
    """뉴스-종목/섹터 관련성 점수를 0-100으로 계산한다.

    점수 기준:
    - 제목에 종목명 포함: +40
    - 본문/설명에 종목명 포함: +20
    - 제목에 동일 섹터 키워드 포함: +15
    - 제목에 금융/실적 키워드 포함: +15
    - 비금융 기사 패턴 감지: -30
    - AI 분류 기사: 기본 +30 (키워드 매칭 불가했으므로 AI 판단 신뢰)

    최종 점수에 소스 신뢰도 가중치를 곱한다.
    """
    raw_score = 0
    title_lower = title.lower() if title else ""

    if is_ai_classified:
        # AI가 분류한 경우 기본 점수
        raw_score += 30
    else:
        # 제목에 종목명 포함: +40
        if stock_name and stock_name in title:
            raw_score += 40

        # 설명에 종목명 포함: +20
        if stock_name and stock_name in (description or ""):
            raw_score += 20

    # 제목에 섹터 키워드 포함: +15
    if sector_name:
        sector_parts = re.split(r"[와및·/,]", sector_name)
        for part in sector_parts:
            part = part.strip()
            if len(part) >= 2 and part.lower() in title_lower:
                raw_score += 15
                break

    # 제목에 금융 키워드 포함: +15
    for kw in FINANCIAL_KEYWORDS:
        if kw.lower() in title_lower:
            raw_score += 15
            break

    # 비금융 기사 패턴 감지: -30
    if is_non_financial_article(title, description=description or ""):
        raw_score -= 30

    # 0-100 범위 클램핑
    raw_score = max(0, min(100, raw_score))

    # 소스 신뢰도 가중치 적용
    credibility = get_source_credibility(source or "")
    final_score = int(raw_score * credibility)

    return max(0, min(100, final_score))


def classify_news(title: str, index: KeywordIndex) -> list[dict]:
    """Classify a news article using pre-built keyword index. O(keywords) not O(stocks)."""
    results = []
    matched_sector_ids: set[int] = set()
    title_lower = title.lower()

    # Match stock names in title — longest match first to avoid
    # shorter names matching inside longer ones (e.g. "이닉스" inside "SK하이닉스")
    matched_stock_ids: set[int] = set()
    sorted_names = sorted(index.stock_names.items(), key=lambda x: len(x[0]), reverse=True)
    matched_spans: list[tuple[int, int]] = []  # (start, end) of already matched substrings

    for stock_name, (stock_id, sector_id) in sorted_names:
        idx = title.find(stock_name)
        if idx == -1:
            continue
        end = idx + len(stock_name)
        # Skip if this match is fully contained within an already matched span
        if any(s <= idx and end <= e for s, e in matched_spans):
            continue
        # Skip if preceded by a Korean char (part of a longer word, e.g. "하이닉스" → "이닉스")
        if idx > 0 and "\uac00" <= title[idx - 1] <= "\ud7a3":
            continue
        matched_spans.append((idx, end))
        matched_stock_ids.add(stock_id)
        results.append({
            "stock_id": stock_id,
            "sector_id": sector_id,
            "match_type": "keyword",
            "relevance": "direct",
        })
        matched_sector_ids.add(sector_id)

    # Match stock custom keywords
    for kw, stock_list in index.stock_keywords.items():
        if kw in title_lower:
            for stock_id, sector_id in stock_list:
                if sector_id not in matched_sector_ids:
                    results.append({
                        "stock_id": stock_id,
                        "sector_id": sector_id,
                        "match_type": "keyword",
                        "relevance": "indirect",
                    })
                    matched_sector_ids.add(sector_id)

    # Match sector keywords
    for kw, sector_id in index.sector_keywords.items():
        if sector_id not in matched_sector_ids and kw in title_lower:
            # Ambiguous short keywords need a second confirming keyword from the
            # same sector to avoid false positives (e.g. "가구" in political news).
            if kw in _AMBIGUOUS_SECTOR_KEYWORDS:
                confirming = _AMBIGUOUS_SECTOR_KEYWORDS[kw]
                if not any(ck in title_lower for ck in confirming):
                    continue
            results.append({
                "stock_id": None,
                "sector_id": sector_id,
                "match_type": "keyword",
                "relevance": "indirect",
            })
            matched_sector_ids.add(sector_id)

    return results


def _count_keyword_matches(title: str, keywords: list[str]) -> int:
    """Count keyword matches ensuring they are not part of a larger word.

    A keyword matches only if its preceding character (if any) is NOT a Korean
    syllable — this prevents false positives like '이부진' matching '부진'.
    """
    count = 0
    for kw in keywords:
        start = 0
        while True:
            idx = title.find(kw, start)
            if idx == -1:
                break
            # Check that the character before the keyword is not Korean
            if idx > 0 and "\uac00" <= title[idx - 1] <= "\ud7a3":
                start = idx + 1
                continue
            count += 1
            break  # one match per keyword is enough

    return count


# ---------------------------------------------------------------------------
# 6단계 감성 분석
# ---------------------------------------------------------------------------
_VALID_SENTIMENTS = {
    "strong_positive", "positive", "mixed",
    "neutral", "negative", "strong_negative",
}

# 강한 긍정 키워드 (strong_positive 판별용)
_STRONG_POSITIVE_KEYWORDS = [
    "실적 서프라이즈", "사상최대", "대규모 수주", "깜짝 실적",
    "역대 최대", "역대 최고", "어닝 서프라이즈", "호실적 서프라이즈",
]

# 강한 부정 키워드 (strong_negative 판별용)
_STRONG_NEGATIVE_KEYWORDS = [
    "상장폐지", "적자전환", "횡령", "분식회계", "상폐",
    "워크아웃", "법정관리", "부도", "파산", "배임",
]

# 반전 패턴 키워드 (부정 → mixed 전환용)
_REVERSAL_PATTERNS = ["다만", "그러나", "한편", "반면", "하지만", "그럼에도"]

_POSITIVE_KEYWORDS = [
    "급등", "상승", "호재", "최고", "신고가", "흑자", "실적개선", "수주",
    "계약", "성장", "회복", "반등", "돌파", "호실적", "매출증가", "영업이익",
    "순이익", "사상최대", "투자유치", "상향", "기대감", "강세", "랠리",
    "호황", "확대", "증가", "수혜", "특수", "날개", "질주", "도약",
    "기대", "청신호", "훈풍", "활기", "부활", "선전", "약진", "쾌거",
]

_NEGATIVE_KEYWORDS = [
    "급락", "하락", "악재", "최저", "신저가", "적자", "실적악화", "손실",
    "감소", "위기", "폭락", "부진", "하향", "약세", "침체", "매각",
    "구조조정", "파산", "부도", "리콜", "소송", "제재", "벌금", "처분",
    "감사의견", "상폐", "상장폐지", "워크아웃", "법정관리", "불확실",
    "우려", "경고", "리스크", "충격", "타격", "먹구름", "한파", "적신호",
]


def classify_sentiment(title: str, content: str | None = None) -> str:
    """뉴스 감성을 6단계로 분류한다.

    반환값: strong_positive / positive / mixed / neutral / negative / strong_negative

    판별 로직:
    1. 강한 긍정 키워드 + pos_count >= 3 → strong_positive
    2. 강한 부정 키워드 + neg_count >= 3 → strong_negative
    3. pos > 0 AND neg > 0 → mixed
    4. pos > neg → positive
    5. neg > pos → negative
    6. 그 외 → neutral

    content가 있으면 반전 패턴을 감지하여 부정 → mixed로 전환한다.
    """
    title_lower = title.lower()

    pos_count = _count_keyword_matches(title_lower, _POSITIVE_KEYWORDS)
    neg_count = _count_keyword_matches(title_lower, _NEGATIVE_KEYWORDS)

    # 강한 긍정 감지
    has_strong_pos = any(kw in title for kw in _STRONG_POSITIVE_KEYWORDS)
    if has_strong_pos and pos_count >= 3:
        return "strong_positive"

    # 강한 부정 감지
    has_strong_neg = any(kw in title for kw in _STRONG_NEGATIVE_KEYWORDS)
    if has_strong_neg and neg_count >= 3:
        return "strong_negative"

    # 반전 패턴 감지 (content 기반)
    if content and neg_count > pos_count:
        content_lower = content.lower()
        has_reversal = any(rp in content_lower for rp in _REVERSAL_PATTERNS)
        if has_reversal:
            # 반전 패턴 뒤에 긍정 키워드가 있으면 mixed
            content_pos = _count_keyword_matches(content_lower, _POSITIVE_KEYWORDS)
            if content_pos > 0:
                return "mixed"

    # 양쪽 모두 존재하면 mixed
    if pos_count > 0 and neg_count > 0:
        return "mixed"

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    return "neutral"


async def classify_sentiment_with_ai(
    articles: list[dict],
) -> None:
    """AI를 사용하여 기사의 감성을 정밀 분석한다.

    키워드 기반 감성분석이 neutral인 기사에 대해 AI로 재분석.
    articles를 in-place로 수정하여 _ai_sentiment 필드를 추가한다.
    """
    import json as _json
    from app.services.ai_client import ask_ai

    # neutral인 기사만 AI 분석 대상 (이미 _ai_sentiment 설정된 것은 P3에서 처리됨 — 스킵)
    neutral_articles = [
        (i, a) for i, a in enumerate(articles)
        if classify_sentiment(a.get("title", "")) == "neutral"
        and a.get("_relations")
        and not a.get("_ai_sentiment")
    ]
    if not neutral_articles:
        return

    chunk_size = 30
    reclassified = 0

    for chunk_start in range(0, len(neutral_articles), chunk_size):
        chunk = neutral_articles[chunk_start:chunk_start + chunk_size]

        items = []
        for j, (_, a) in enumerate(chunk):
            title = a.get("title", "")
            desc = (a.get("description") or "")[:150]
            items.append({"id": j + 1, "title": title, "desc": desc})

        prompt = f"""다음 투자 관련 뉴스 기사들의 감성을 분류해주세요.
각 기사의 sentiment를 strong_positive/positive/mixed/neutral/negative/strong_negative 중 하나로 판단하세요.

- strong_positive: 실적 서프라이즈, 사상최대 등 매우 강한 호재
- positive: 일반적인 호재
- mixed: 긍정과 부정이 혼재
- neutral: 중립적 사실 보도
- negative: 일반적인 악재
- strong_negative: 상장폐지, 횡령, 분식회계 등 매우 강한 악재

기사 목록:
{_json.dumps(items, ensure_ascii=False)}

반드시 아래 JSON 배열 형식으로만 응답해주세요:
[{{"id": 1, "sentiment": "positive"}}, ...]"""

        try:
            text = await ask_ai(prompt, max_retries=3)
            if not text:
                continue

            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

            results = _json.loads(text)
            for item in results:
                idx = item.get("id", 0) - 1
                if 0 <= idx < len(chunk):
                    sentiment = item.get("sentiment", "neutral")
                    if sentiment in _VALID_SENTIMENTS and sentiment != "neutral":
                        orig_idx, article = chunk[idx]
                        article["_ai_sentiment"] = sentiment
                        reclassified += 1
        except Exception as e:
            logger.debug(f"AI sentiment classification chunk failed: {e}")

        if chunk_start + chunk_size < len(neutral_articles):
            import asyncio as _asyncio
            await _asyncio.sleep(2)

    if reclassified:
        logger.info(f"AI sentiment: reclassified {reclassified}/{len(neutral_articles)} neutral articles")


async def generate_ai_summary(title: str, description: str | None, relations: list[dict]) -> str | None:
    """Generate an AI investment analysis summary for a news article."""
    if not settings.GEMINI_API_KEY:
        return None

    related_entities = []
    for rel in relations:
        name = rel.get("stock_name") or rel.get("sector_name") or ""
        rel_type = "직접" if rel.get("relevance") == "direct" else "간접"
        if name:
            related_entities.append(f"{name} ({rel_type})")

    related_text = ", ".join(related_entities) if related_entities else "없음"
    desc_text = description if description else "없음"

    prompt = f"""다음 뉴스 기사를 투자자 관점에서 분석해주세요.

제목: "{title}"
기사 요약: {desc_text}
관련 종목/섹터: {related_text}

다음 내용을 포함하여 3-5문장으로 분석해주세요:
1. 기사의 핵심 내용
2. 관련 종목/섹터에 미칠 수 있는 영향
3. 투자자가 주목해야 할 포인트

한국어로 작성해주세요. 마크다운 없이 일반 텍스트로 응답해주세요."""

    from app.services.ai_client import ask_ai
    return await ask_ai(prompt, max_retries=5)


async def generate_disclosure_summary(
    report_name: str,
    report_type: str | None,
    corp_name: str,
) -> str | None:
    """Generate an AI summary for a DART disclosure aimed at beginner investors."""
    type_text = report_type if report_type else "미분류"

    prompt = f"""다음 DART 전자공시를 투자 초보자도 이해할 수 있도록 쉽게 설명해주세요.

회사: {corp_name}
공시 제목: "{report_name}"
공시 유형: {type_text}

다음 내용을 포함하여 3-5문장으로 설명해주세요:
1. 이 공시가 무엇인지 (전문용어 없이 쉬운 말로)
2. 이 공시가 주가나 투자자에게 어떤 의미가 있는지
3. 투자자가 주의해야 할 점이 있다면

한국어로 작성해주세요. 마크다운 없이 일반 텍스트로 응답해주세요."""

    from app.services.ai_client import ask_ai
    return await ask_ai(prompt, max_retries=5)


def _is_english_title(title: str) -> bool:
    """Check if a title is predominantly English (non-Korean)."""
    korean_chars = sum(1 for c in title if "\uac00" <= c <= "\ud7a3")
    return korean_chars < len(title) * 0.2


async def translate_articles_batch(articles: list[dict]) -> None:
    """Translate English titles and descriptions to Korean in-place using Gemini.

    Modifies articles in-place: translates title and description fields.
    Includes retry with exponential backoff for rate-limit (429) errors.
    """
    import asyncio as _asyncio
    import json as _json
    from app.services.ai_client import ask_ai

    en_articles = [(i, a) for i, a in enumerate(articles) if _is_english_title(a.get("title", ""))]
    if not en_articles:
        return

    # 청크당 20개 (Gemini 2.5 flash는 토큰 여유 충분 — 호출 수 4배 감소)
    chunk_size = 20
    for chunk_start in range(0, len(en_articles), chunk_size):
        chunk = en_articles[chunk_start:chunk_start + chunk_size]

        items = []
        for j, (_, a) in enumerate(chunk):
            desc = (a.get("description") or "").strip()
            items.append({"id": j + 1, "title": a["title"], "desc": desc[:300] if desc else ""})

        prompt = f"""다음 영문 뉴스 기사의 제목(title)과 요약(desc)을 한국어로 번역해주세요.
뉴스 제목답게 간결하게 번역하고, desc가 비어있으면 빈 문자열로 두세요.
반드시 아래 JSON 배열 형식으로만 응답해주세요. 다른 텍스트 없이 JSON만 출력하세요.

입력:
{_json.dumps(items, ensure_ascii=False)}

출력 형식:
[{{"id": 1, "title": "번역된 제목", "desc": "번역된 요약"}}, ...]"""

        try:
            text = await ask_ai(prompt, max_retries=5)
            if not text:
                continue

            # Strip markdown code block if present
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

            translated_items = _json.loads(text)

            for item in translated_items:
                idx = item.get("id", 0) - 1
                if 0 <= idx < len(chunk):
                    _, article = chunk[idx]
                    t = item.get("title", "").strip()
                    d = item.get("desc", "").strip()
                    if t and len(t) > 2:
                        article["original_title"] = article["title"]
                        article["title"] = t
                    if d and len(d) > 2:
                        article["description"] = d
        except Exception as e:
            logger.info(f"Translation skipped, keeping English titles: chunk {chunk_start // chunk_size + 1}: {e}")

        # 청크 간 짧은 지연 (rate limit 보호)
        if chunk_start + chunk_size < len(en_articles):
            await _asyncio.sleep(1)

    translated_count = sum(1 for _, a in en_articles if "original_title" in a)
    if translated_count:
        logger.info(f"Translated {translated_count}/{len(en_articles)} English articles to Korean")


# Ambiguous sector keywords that are common everyday words.
# Each maps to a list of confirming keywords — at least one must also
# appear in the title for the sector match to count.
_AMBIGUOUS_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "가구": ["가구업", "가구사", "가구제조", "인테리어", "소파", "침대", "매트리스", "가구산업", "리바트", "한샘", "에몬스"],
    "부동산": ["아파트", "전세", "매매", "분양", "임대", "공시지가", "토지", "재개발", "재건축", "건설사", "시행사", "부동산시장", "주택"],
    "건설": ["건설사", "시공", "착공", "준공", "분양", "건축", "재개발", "재건축", "도시정비"],
    "교육": ["학원", "입시", "수능", "에듀테크", "교육업", "학교", "온라인교육"],
    "식품": ["식품업", "가공식품", "식자재", "식품안전", "식품사"],
    "화학": ["화학업", "석유화학", "정밀화학", "화학사", "소재"],
    "기계": ["기계업", "공작기계", "산업용", "기계사", "로봇"],
    # "구리"는 지명/인명으로도 쓰여 오탐 많음 — 금속 문맥 확인 필요
    # "전선"은 광통신/반도체/건설 기사에서 "광섬유 vs 구리선(전선)" 비교로 오탐 발생 → 제거
    "구리": ["구리가격", "구리값", "동 가격", "동광", "구리선", "비철"],
    # "아연"도 단독으로는 의약/화학 맥락 혼용 가능
    "아연": ["아연도금", "아연가격", "아연값", "비철"],
    # "니켈"은 비교적 명확하지만 배터리 문맥에서 자동차 섹터와 중복 가능
    "니켈": ["니켈가격", "니켈값", "니켈광", "비철"],
}


# Extended keyword dictionary: sector name → additional topic keywords
# These catch articles that don't mention sector/stock names directly
_SECTOR_EXTRA_KEYWORDS: dict[str, list[str]] = {
    "건설": ["재개발", "재건축", "도시정비", "도심재생", "착공", "준공", "분양", "시공", "건축"],
    "부동산": ["부동산", "아파트", "전세", "매매", "임대", "분양가", "공시지가", "토지"],
    "반도체와반도체장비": ["반도체", "파운드리", "메모리", "HBM", "DRAM", "낸드", "NAND", "웨이퍼", "EUV", "패키징"],
    "소프트웨어": ["AI", "인공지능", "클라우드", "SaaS", "데이터센터", "LLM", "딥러닝", "머신러닝", "플랫폼"],
    "IT서비스": ["IT", "디지털전환", "DX", "스마트시티", "스마트팩토리", "SI", "시스템통합"],
    "자동차": ["전기차", "EV", "자율주행", "배터리", "충전소", "하이브리드", "수소차"],
    "자동차부품": ["전기차부품", "배터리팩", "모터", "인버터", "감속기"],
    "철강": ["철강", "제철", "고철", "철근", "강판", "스테인리스", "특수강"],
    "비철금속": ["비철금속", "알루미늄", "구리", "아연", "니켈", "리튬", "코발트", "희토류"],
    "화학": ["화학", "석유화학", "정밀화학", "2차전지소재", "양극재", "음극재", "전해질", "분리막"],
    "제약": ["제약", "신약", "임상", "바이오시밀러", "FDA", "식약처", "의약품", "항암제"],
    "생물공학": ["바이오", "유전자", "세포치료", "항체", "백신", "mRNA", "CGT"],
    "은행": ["은행", "금리", "대출", "예금", "기준금리", "통화정책", "중앙은행"],
    "증권": ["증권", "주식", "코스피", "코스닥", "IPO", "상장", "공모주", "증시"],
    "전기유틸리티": ["전력", "발전소", "송전", "배전", "전력거래", "신재생에너지"],
    "에너지장비및서비스": ["에너지", "태양광", "풍력", "신재생", "ESS", "전력저장"],
    "석유와가스": ["석유", "원유", "정유", "LNG", "천연가스", "유가", "OPEC"],
    "항공사": ["항공", "항공편", "노선", "운항", "공항", "여객"],
    "조선": ["조선", "선박", "해양플랜트", "LNG선", "컨테이너선", "조선소"],
    "운송인프라": ["트램", "철도", "고속도로", "교통", "물류센터", "인프라"],
    "도로와철도운송": ["택배", "물류", "운송", "화물", "트럭", "철도운송"],
    "무선통신서비스": ["5G", "6G", "통신", "이동통신", "주파수", "로밍"],
    "다각화된통신서비스": ["인터넷", "IPTV", "브로드밴드", "광통신", "통신서비스"],
    "게임엔터테인먼트": ["게임", "e스포츠", "모바일게임", "온라인게임", "메타버스"],
    "양방향미디어와서비스": ["포털", "검색엔진", "SNS", "디지털광고", "온라인플랫폼"],
    "전자장비와기기": ["센서", "MLCC", "커넥터", "PCB", "전자부품"],
    "디스플레이패널": ["디스플레이", "OLED", "LCD", "패널", "마이크로LED"],
    "핸드셋": ["스마트폰", "갤럭시", "아이폰", "모바일기기", "폴더블"],
    "우주항공과국방": ["국방", "방산", "미사일", "전투기", "위성", "우주", "방위산업", "군수"],
    "식품": ["식품", "가공식품", "식자재", "식품안전"],
    "음료": ["음료", "맥주", "소주", "커피", "차"],
    "화장품": ["화장품", "뷰티", "스킨케어", "K뷰티", "더마"],
    "건강관리장비와용품": ["의료기기", "진단키트", "체외진단", "의료장비"],
    "건강관리업체및서비스": ["병원", "의료서비스", "헬스케어", "원격의료", "디지털헬스"],
    "교육서비스": ["교육", "에듀테크", "학원", "온라인교육", "입시"],
    "전기장비": ["전선", "케이블", "변압기", "배전반", "전력기기", "초고압"],
    "기계": ["기계", "로봇", "공작기계", "산업용로봇", "자동화"],
    "가스유틸리티": ["도시가스", "가스배관", "LPG"],
    "손해보험": ["보험", "손해보험", "자동차보험", "화재보험"],
    "생명보험": ["생명보험", "종신보험", "연금보험"],
    "카드": ["카드", "결제", "핀테크", "간편결제", "페이"],
    "호텔,레스토랑,레저": ["호텔", "관광", "여행", "리조트", "카지노", "면세점", "레저"],
    "복합기업": ["복합기업", "지주회사", "그룹"],
    "전기제품": ["가전", "냉장고", "세탁기", "에어컨", "TV"],
    "포장재": ["포장재", "패키징", "골판지", "플라스틱용기"],
    "해운사": ["해운", "컨테이너", "벌크선", "운임", "해상운송"],
    "항공화물운송과물류": ["항공화물", "택배", "3PL", "풀필먼트"],
    "전자제품": ["가전제품", "소비자가전", "스마트홈", "IoT"],
    "광고": ["광고", "디지털마케팅", "미디어렙", "옥외광고"],
    "인터넷과카탈로그소매": ["이커머스", "온라인쇼핑", "라이브커머스"],
    "전문소매": ["편의점", "드럭스토어", "전문매장"],
    "건강관리기술": ["헬스테크", "디지털치료", "원격진료", "PHR"],
    "생명과학도구및서비스": ["CRO", "CMO", "CDMO", "임상대행", "바이오위탁"],
    "창업투자": ["벤처캐피탈", "스타트업", "벤처투자", "VC"],
    "상업서비스와공급품": ["인력파견", "시설관리", "보안서비스", "BPO"],
}


async def classify_news_with_ai(
    articles: list[dict],
    index: KeywordIndex,
    sectors: list,
) -> None:
    """AI를 사용하여 키워드 매칭이 안 된 기사의 관련 섹터를 분류한다.

    articles를 in-place로 수정하여 _relations 필드를 추가한다.
    비용 절감을 위해 배치로 처리하고, 키워드 매칭이 이미 된 기사는 건너뛴다.
    """
    import json as _json
    from app.services.ai_client import ask_ai

    # 키워드 매칭이 안 된 기사만 필터
    unmatched = [(i, a) for i, a in enumerate(articles) if not a.get("_relations")]
    if not unmatched:
        return

    # 섹터 목록 생성
    sector_map = {s.id: s.name for s in sectors}
    sector_list = "\n".join(f"- ID:{sid} {sname}" for sid, sname in sector_map.items())

    # 배치로 처리 (한 번에 30개씩)
    chunk_size = 30
    classified_count = 0

    for chunk_start in range(0, len(unmatched), chunk_size):
        chunk = unmatched[chunk_start:chunk_start + chunk_size]

        items = []
        for j, (_, a) in enumerate(chunk):
            title = a.get("title", "")
            desc = (a.get("description") or "")[:200]
            items.append({"id": j + 1, "title": title, "desc": desc})

        prompt = f"""다음 뉴스 기사들의 (1) 관련 투자 섹터와 (2) 감성을 동시에 분류해주세요.

등록된 섹터 목록:
{sector_list}

기사 목록:
{_json.dumps(items, ensure_ascii=False)}

각 기사에 대해:
- sectors: 관련 섹터 ID 배열 (관련 없으면 빈 배열)
- sentiment: strong_positive/positive/mixed/neutral/negative/strong_negative 중 하나

반드시 아래 JSON 배열 형식으로만 응답해주세요. 다른 텍스트 금지:
[{{"id": 1, "sectors": [섹터ID1, 섹터ID2], "sentiment": "positive"}}, ...]"""

        try:
            text = await ask_ai(prompt, max_retries=3)
            if not text:
                continue

            # Strip markdown code block
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

            results = _json.loads(text)
            for item in results:
                idx = item.get("id", 0) - 1
                if 0 <= idx < len(chunk):
                    orig_idx, article = chunk[idx]
                    sector_ids = item.get("sectors", [])
                    if sector_ids:
                        relations = []
                        for sid in sector_ids:
                            if sid in sector_map:
                                relations.append({
                                    "stock_id": None,
                                    "sector_id": sid,
                                    "match_type": "ai_classified",
                                    "relevance": "indirect",
                                })
                        if relations:
                            article["_relations"] = relations
                            classified_count += 1
                    # P3: 감성도 같은 호출에서 추출 (별도 sentiment AI 호출 절감)
                    sentiment = item.get("sentiment", "")
                    if sentiment in _VALID_SENTIMENTS and sentiment != "neutral":
                        article["_ai_sentiment"] = sentiment
        except Exception as e:
            logger.info(f"AI classification chunk {chunk_start // chunk_size + 1} failed: {e}")

        # Rate limit 방지
        if chunk_start + chunk_size < len(unmatched):
            import asyncio as _asyncio
            await _asyncio.sleep(2)

    if classified_count:
        logger.info(f"AI classified {classified_count}/{len(unmatched)} previously unmatched articles")


# ---------------------------------------------------------------------------
# 글로벌 뉴스 영향 분석
# ---------------------------------------------------------------------------
# 글로벌 뉴스 키워드 -> 한국 섹터 매핑
GLOBAL_KEYWORD_SECTOR_MAP: dict[str, list[str]] = {
    # 반도체 섹터
    "semiconductor": ["반도체"], "chip": ["반도체"], "TSMC": ["반도체"],
    "Nvidia": ["반도체"], "AMD": ["반도체"], "Intel": ["반도체"],
    "memory": ["반도체"], "DRAM": ["반도체"], "NAND": ["반도체"],
    "HBM": ["반도체"],
    # 정유/화학
    "oil price": ["정유", "화학"], "crude": ["정유", "화학"], "OPEC": ["정유"],
    "brent": ["정유"], "WTI": ["정유"],
    # 금융
    "Fed rate": ["금융", "은행"], "interest rate": ["금융", "은행"],
    "treasury": ["금융"], "Federal Reserve": ["금융"],
    # 2차전지
    "EV": ["2차전지", "자동차"], "battery": ["2차전지"],
    "lithium": ["2차전지"], "cathode": ["2차전지"], "anode": ["2차전지"],
    # 철강
    "steel": ["철강"], "iron ore": ["철강"],
    # 한국 대기업 (영문명)
    "Samsung": ["반도체", "전자"], "Hyundai": ["자동차", "건설"],
    "LG": ["전자", "2차전지"], "SK": ["반도체", "에너지"],
    "Kia": ["자동차"], "POSCO": ["철강"],
}

# 글로벌 소스 판별용 패턴
_GLOBAL_SOURCES = {"yahoo", "google", "reuters", "bloomberg", "cnbc", "bbc"}


def detect_global_impact(title: str, source: str) -> list[dict]:
    """글로벌 뉴스에서 한국 시장 영향을 감지한다.

    영문 소스(Yahoo, Google 등)의 기사 제목에서 글로벌 키워드를 탐지하고,
    해당 키워드가 영향을 줄 수 있는 한국 섹터를 매핑한다.

    Args:
        title: 뉴스 기사 제목
        source: 뉴스 소스명 (yahoo, google, naver 등)

    Returns:
        list of {"keyword": str, "sectors": list[str], "is_pre_market": bool}
        매칭되는 글로벌 키워드가 없으면 빈 리스트를 반환한다.
    """
    from datetime import datetime, timezone, timedelta

    # 글로벌 소스가 아니면 빈 리스트 반환
    source_lower = (source or "").lower()
    is_global_source = any(gs in source_lower for gs in _GLOBAL_SOURCES)
    if not is_global_source:
        return []

    # 프리마켓 판별 (KST 09:00 이전)
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    is_pre_market = now_kst.hour < 9

    results: list[dict] = []
    seen_keywords: set[str] = set()

    for keyword, sectors in GLOBAL_KEYWORD_SECTOR_MAP.items():
        # 대소문자 구분 없이 매칭 (단, 2글자 이하 키워드는 단어 경계 확인)
        kw_lower = keyword.lower()
        title_lower = title.lower()

        if len(keyword) <= 2:
            # 짧은 키워드(EV, LG, SK)는 단어 경계에서만 매칭
            if not re.search(rf"\b{re.escape(kw_lower)}\b", title_lower):
                continue
        else:
            if kw_lower not in title_lower:
                continue

        if kw_lower in seen_keywords:
            continue
        seen_keywords.add(kw_lower)

        results.append({
            "keyword": keyword,
            "sectors": sectors,
            "is_pre_market": is_pre_market,
        })

    if results:
        logger.info(
            f"글로벌 뉴스 영향 감지: {len(results)}개 키워드 매칭 "
            f"(pre_market={is_pre_market}, title='{title[:50]}...')"
        )

    return results


def _extract_sector_keywords(sector_name: str) -> list[str]:
    """Extract meaningful keywords from sector name + extended dictionary."""
    parts = re.split(r"[와및·/,]", sector_name)
    keywords = []
    for part in parts:
        part = part.strip()
        if len(part) >= 2:
            keywords.append(part.lower())
    if sector_name.lower() not in keywords:
        keywords.append(sector_name.lower())

    # Add extended topic keywords for this sector
    extra = _SECTOR_EXTRA_KEYWORDS.get(sector_name, [])
    for kw in extra:
        kw_lower = kw.lower()
        if kw_lower not in keywords:
            keywords.append(kw_lower)

    return keywords
