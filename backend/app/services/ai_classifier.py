import json
import logging

from google import genai

from app.config import settings
from app.models.sector import Sector
from app.models.stock import Stock

logger = logging.getLogger(__name__)


async def classify_news(
    title: str,
    sectors: list[Sector],
    stocks: list[Stock],
) -> list[dict]:
    """Use Gemini API to classify a news article against registered sectors/stocks."""
    if not settings.GEMINI_API_KEY:
        return _keyword_fallback(title, sectors, stocks)

    # Build sector/stock map for the prompt
    sector_map: dict[str, list[str]] = {}
    stock_id_map: dict[str, int] = {}
    sector_id_map: dict[str, int] = {}
    for sector in sectors:
        sector_stocks = [s for s in stocks if s.sector_id == sector.id]
        if sector_stocks:
            sector_map[sector.name] = [s.name for s in sector_stocks]
            sector_id_map[sector.name] = sector.id
            for s in sector_stocks:
                stock_id_map[s.name] = s.id

    if not sector_map:
        return _keyword_fallback(title, sectors, stocks)

    sector_lines = []
    for sector_name, stock_names in sector_map.items():
        sector_lines.append(f"- {sector_name}: [{', '.join(stock_names)}]")
    sector_text = "\n".join(sector_lines)

    prompt = f"""뉴스 기사 제목: "{title}"

등록된 섹터/종목:
{sector_text}

이 뉴스가 관련된 섹터와 종목을 JSON 배열로 응답해.
직접 언급된 종목은 "direct", 간접 영향은 "indirect"로 표시.
관련 없으면 빈 배열 []을 반환.

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
        return _keyword_fallback(title, sectors, stocks)

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
    """Fallback: simple keyword matching when AI is unavailable."""
    results = []
    title_lower = title.lower()

    for stock in stocks:
        if stock.name in title_lower:
            results.append(
                {
                    "stock_id": stock.id,
                    "sector_id": stock.sector_id,
                    "match_type": "keyword",
                    "relevance": "direct",
                }
            )
        elif stock.keywords:
            for kw in stock.keywords:
                if kw.lower() in title_lower:
                    results.append(
                        {
                            "stock_id": stock.id,
                            "sector_id": stock.sector_id,
                            "match_type": "keyword",
                            "relevance": "indirect",
                        }
                    )
                    break

    return results
