import logging
import re
from dataclasses import dataclass, field

from google import genai

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


def classify_news(title: str, index: KeywordIndex) -> list[dict]:
    """Classify a news article using pre-built keyword index. O(keywords) not O(stocks)."""
    results = []
    matched_sector_ids: set[int] = set()
    title_lower = title.lower()

    # Match stock names in title (exact substring match)
    for stock_name, (stock_id, sector_id) in index.stock_names.items():
        if stock_name in title:
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
            results.append({
                "stock_id": None,
                "sector_id": sector_id,
                "match_type": "keyword",
                "relevance": "indirect",
            })
            matched_sector_ids.add(sector_id)

    return results


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

    pos_count = sum(1 for kw in positive_keywords if kw in title_lower)
    neg_count = sum(1 for kw in negative_keywords if kw in title_lower)

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

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        logger.warning(f"AI summary generation failed: {e}")
        return None


def _is_english_title(title: str) -> bool:
    """Check if a title is predominantly English (non-Korean)."""
    korean_chars = sum(1 for c in title if "\uac00" <= c <= "\ud7a3")
    return korean_chars < len(title) * 0.2


async def translate_articles_batch(articles: list[dict]) -> None:
    """Translate English titles and descriptions to Korean in-place using Gemini.

    Modifies articles in-place: translates title and description fields.
    """
    import json as _json

    if not settings.GEMINI_API_KEY:
        return

    en_articles = [(i, a) for i, a in enumerate(articles) if _is_english_title(a.get("title", ""))]
    if not en_articles:
        return

    # Process in chunks of 10 (title + description per item)
    chunk_size = 10
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
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            text = response.text.strip()
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
            logger.warning(f"Batch translation failed: {e}")

    translated_count = sum(1 for _, a in en_articles if "original_title" in a)
    if translated_count:
        logger.info(f"Translated {translated_count}/{len(en_articles)} English articles to Korean")


def _extract_sector_keywords(sector_name: str) -> list[str]:
    """Extract meaningful keywords from sector name for matching."""
    parts = re.split(r"[와및·/,]", sector_name)
    keywords = []
    for part in parts:
        part = part.strip()
        if len(part) >= 2:
            keywords.append(part.lower())
    if sector_name.lower() not in keywords:
        keywords.append(sector_name.lower())
    return keywords
