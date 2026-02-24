import json
import logging

from google import genai

from app.config import settings
from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)

# Max stocks to include in AI prompt to keep it under token limits
MAX_STOCKS_IN_PROMPT = 200


async def classify_news(
    title: str,
    sectors: list[Sector],
    stocks: list[Stock],
) -> list[dict]:
    """Classify a news article against registered sectors/stocks.

    Two-phase approach for large stock lists:
    1. Fast keyword scan — exact name match in title
    2. AI classification with sector-level context (sector names + sampled stocks)
    """
    # Phase 1: keyword matching (fast, covers all stocks)
    keyword_results = _keyword_fallback(title, sectors, stocks)
    if keyword_results:
        return keyword_results

    # Phase 2: AI classification
    if not settings.GEMINI_API_KEY:
        return []

    return await _ai_classify(title, sectors, stocks)


async def _ai_classify(
    title: str,
    sectors: list[Sector],
    stocks: list[Stock],
) -> list[dict]:
    """Use Gemini API with a compact prompt."""
    sector_map: dict[str, list[str]] = {}
    stock_id_map: dict[str, int] = {}
    sector_id_map: dict[str, int] = {}

    for sector in sectors:
        sector_stocks = [s for s in stocks if s.sector_id == sector.id]
        if sector_stocks:
            # Only include top N stocks per sector to keep prompt small
            sample = sector_stocks[:15]
            sector_map[sector.name] = [s.name for s in sample]
            sector_id_map[sector.name] = sector.id
            for s in sample:
                stock_id_map[s.name] = s.id

    if not sector_map:
        return []

    sector_lines = []
    for sector_name, stock_names in sector_map.items():
        sector_lines.append(f"- {sector_name}: [{', '.join(stock_names)}]")
    sector_text = "\n".join(sector_lines)

    prompt = f"""뉴스 기사 제목: "{title}"

등록된 섹터/종목:
{sector_text}

이 뉴스가 관련된 섹터와 종목을 JSON 배열로 응답해.
직접 언급된 종목은 "direct", 간접 영향은 "indirect"로 표시.

중요: 반드시 최소 1개 이상의 섹터를 포함해야 합니다. 직접적으로 관련된 섹터가 없더라도 가장 관련성이 높은 섹터를 "indirect"로 포함하세요.

응답 형식 (JSON만 반환, 마크다운 코드블록 없이):
[
  {{"type": "stock", "name": "종목명", "relevance": "direct"}},
  {{"type": "sector", "name": "섹터명", "relevance": "indirect"}}
]"""

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        content = response.text.strip()

        # Extract JSON from response
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        classifications = json.loads(content)
    except Exception as e:
        logger.warning(f"AI classification failed: {e}")
        return []

    # Convert to relation format
    results = []
    for cls in classifications:
        if cls.get("type") == "stock" and cls.get("name") in stock_id_map:
            stock = next((s for s in stocks if s.name == cls["name"]), None)
            results.append(
                {
                    "stock_id": stock_id_map[cls["name"]],
                    "sector_id": stock.sector_id if stock else None,
                    "match_type": "ai_classified",
                    "relevance": cls.get("relevance", "indirect"),
                }
            )
        elif cls.get("type") == "sector" and cls.get("name") in sector_id_map:
            results.append(
                {
                    "stock_id": None,
                    "sector_id": sector_id_map[cls["name"]],
                    "match_type": "ai_classified",
                    "relevance": cls.get("relevance", "indirect"),
                }
            )

    return results


def _keyword_fallback(
    title: str,
    sectors: list[Sector],
    stocks: list[Stock],
) -> list[dict]:
    """Fast keyword matching — scans all stocks and sector names."""
    results = []
    matched_sector_ids: set[int] = set()

    # Match stock names in title
    for stock in stocks:
        if stock.name in title:
            results.append(
                {
                    "stock_id": stock.id,
                    "sector_id": stock.sector_id,
                    "match_type": "keyword",
                    "relevance": "direct",
                }
            )
            matched_sector_ids.add(stock.sector_id)
        elif stock.keywords:
            for kw in stock.keywords:
                if kw.lower() in title.lower():
                    results.append(
                        {
                            "stock_id": stock.id,
                            "sector_id": stock.sector_id,
                            "match_type": "keyword",
                            "relevance": "indirect",
                        }
                    )
                    matched_sector_ids.add(stock.sector_id)
                    break

    # Match sector names in title (only if not already matched via stock)
    title_lower = title.lower()
    for sector in sectors:
        if sector.id in matched_sector_ids:
            continue
        # Use short keywords from sector name for matching
        # e.g. "반도체와반도체장비" → check if "반도체" is in title
        sector_keywords = _extract_sector_keywords(sector.name)
        for kw in sector_keywords:
            if kw in title_lower:
                results.append(
                    {
                        "stock_id": None,
                        "sector_id": sector.id,
                        "match_type": "keyword",
                        "relevance": "indirect",
                    }
                )
                break

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
    """Generate an AI investment analysis summary for a news article.

    Uses Gemini 2.0 Flash to produce a Korean-language investment analysis.
    """
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


def _extract_sector_keywords(sector_name: str) -> list[str]:
    """Extract meaningful keywords from sector name for matching.

    E.g. "반도체와반도체장비" → ["반도체"]
         "자동차부품" → ["자동차"]
         "건설" → ["건설"]
    """
    import re
    # Split by common connectors: 와, 및, ,, ·, /
    parts = re.split(r"[와및·/,]", sector_name)
    keywords = []
    for part in parts:
        part = part.strip()
        if len(part) >= 2:  # Skip single-char fragments
            keywords.append(part.lower())
    # Also add the full name
    if sector_name.lower() not in keywords:
        keywords.append(sector_name.lower())
    return keywords
