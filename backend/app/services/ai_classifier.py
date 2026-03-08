import logging
import re
from dataclasses import dataclass, field

from app.config import settings
from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)


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


# Patterns indicating non-financial content (entertainment, sports, lifestyle, etc.)
_NON_FINANCIAL_PATTERNS: list[str] = [
    # TV/Entertainment
    "동상이몽", "흑백요리사", "나는솔로", "나솔사제", "솔로지옥", "런닝맨", "무한도전",
    "놀면뭐하니", "전참시", "전지적참견시점", "라디오스타", "1박2일",
    "나혼자산다", "신서유기", "삼시세끼", "슈퍼맨이돌아왔다", "편스토랑",
    "예능", "드라마", "시청률", "방영", "출연", "MC", "리얼리티",
    "아이돌", "걸그룹", "보이그룹", "컴백", "음원", "뮤직비디오",
    "K-POP", "K팝", "케이팝", "팬미팅", "콘서트",
    "배우", "연기", "영화", "개봉", "흥행", "박스오피스",
    "넷플릭스", "디즈니플러스", "티빙", "쿠팡플레이", "웨이브",
    "연예", "결혼", "열애", "파경", "이혼", "스캔들",
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
    # Politics / Government (non-business context)
    "국회의원", "의원", "대통령", "총리", "장관", "청와대", "용산",
    "여당", "야당", "정당", "국정감사", "국정조사", "탄핵", "선거", "공천", "당대표",
    "자산공개", "재산공개", "슈퍼리치", "재산신고",
    # Crime / Social (non-business context)
    "검찰", "경찰", "구속", "기소", "체포", "재판", "판결", "혐의",
    "사건", "사고", "사망", "범죄", "살인", "폭행", "피의자",
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


def classify_sentiment(title: str) -> str:
    """Classify news sentiment as positive/negative/neutral based on keywords."""
    title_lower = title.lower()

    positive_keywords = [
        "급등", "상승", "호재", "최고", "신고가", "흑자", "실적개선", "수주",
        "계약", "성장", "회복", "반등", "돌파", "호실적", "매출증가", "영업이익",
        "순이익", "사상최대", "투자유치", "상향", "기대감", "강세", "랠리",
        "호황", "확대", "증가", "수혜", "특수", "날개", "질주", "도약",
        "기대", "청신호", "훈풍", "활기", "부활", "선전", "약진", "쾌거",
    ]

    negative_keywords = [
        "급락", "하락", "악재", "최저", "신저가", "적자", "실적악화", "손실",
        "감소", "위기", "폭락", "부진", "하향", "약세", "침체", "매각",
        "구조조정", "파산", "부도", "리콜", "소송", "제재", "벌금", "처분",
        "감사의견", "상폐", "상장폐지", "워크아웃", "법정관리", "불확실",
        "우려", "경고", "리스크", "충격", "타격", "먹구름", "한파", "적신호",
    ]

    pos_count = _count_keyword_matches(title_lower, positive_keywords)
    neg_count = _count_keyword_matches(title_lower, negative_keywords)

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    return "neutral"


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

    # Process in chunks of 5 (smaller chunks to avoid rate limits)
    chunk_size = 5
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

        # Delay between chunks to avoid rate limits
        if chunk_start + chunk_size < len(en_articles):
            await _asyncio.sleep(5)

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
    "비철금속": ["비철금속", "알루미늄", "구리", "아연", "니켈", "리튬", "코발트", "희토류", "원자재"],
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
