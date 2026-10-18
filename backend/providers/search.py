"""
Search / Web Research provider abstraction.

Providers supported:
  - TavilyProvider     (primary — structured, curated results)
  - SerpAPIProvider    (fallback live provider — Google results via SerpAPI)
  - DemoSearchProvider (fixture-based, reliable for demos / offline)

Selection (get_search_provider):
  DEMO_MODE=true            → DemoSearchProvider
  TAVILY_API_KEY set        → Tavily, falling back to fixtures if it returns nothing
  SERPAPI_KEY set           → SerpAPI, falling back to fixtures if it returns nothing
  no keys                   → DemoSearchProvider

Every SearchResult carries `is_fixture`, so downstream agents can disclose
exactly which evidence came from pre-baked fixtures (honest demo mode).

Adding a new provider:
  1. Implement SearchProvider ABC
  2. Add to get_search_provider() factory

Custom fixtures:
  Drop JSON files into data/fixtures/ with the shape
    {"topic_name": {"triggers": ["word", ...],
                    "results": [{"title": ..., "url": ..., "snippet": ..., "source_type": "web"}]}}
  They are merged with the built-in fixtures below.
"""
from __future__ import annotations
import json
import logging
import random
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(settings.fixtures_dir)


class SearchResult:
    def __init__(
        self,
        title: str,
        url: str,
        snippet: str,
        source_type: str = "web",
        is_fixture: bool = False,
    ):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source_type = source_type
        self.is_fixture = is_fixture

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source_type": self.source_type,
            "is_fixture": self.is_fixture,
        }


class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def is_demo(self) -> bool:
        return False


class TavilyProvider(SearchProvider):
    """Tavily AI search — structured, citation-friendly, free tier available."""

    name = "tavily"

    def __init__(self):
        self.api_key = settings.tavily_api_key
        self.base_url = "https://api.tavily.com/search"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    self.base_url,
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "search_depth": "basic",
                        "max_results": max_results,
                        "include_raw_content": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                results = []
                for r in data.get("results", []):
                    results.append(SearchResult(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("content", ""),
                        source_type="web",
                    ))
                return results
        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            return []


class SerpAPIProvider(SearchProvider):
    """SerpAPI (Google) search — used when no Tavily key is configured."""

    name = "serpapi"

    def __init__(self):
        self.api_key = settings.serpapi_key
        self.base_url = "https://serpapi.com/search.json"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    self.base_url,
                    params={
                        "engine": "google",
                        "q": query,
                        "num": max_results,
                        "api_key": self.api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                results = []
                for r in data.get("organic_results", [])[:max_results]:
                    results.append(SearchResult(
                        title=r.get("title", ""),
                        url=r.get("link", ""),
                        snippet=r.get("snippet", ""),
                        source_type="web",
                    ))
                return results
        except Exception as e:
            logger.error(f"SerpAPI search failed: {e}")
            return []


def _r(title: str, url: str, snippet: str, source_type: str = "web") -> SearchResult:
    return SearchResult(title, url, snippet, source_type, is_fixture=True)


class DemoSearchProvider(SearchProvider):
    """
    Demo provider using built-in fixtures plus optional JSON files in data/fixtures/.
    Uses same SearchResult interface as real providers.
    Returns realistic but pre-baked evidence (always flagged is_fixture=True).
    """

    name = "demo"

    @property
    def is_demo(self) -> bool:
        return True

    # Built-in fixtures: topic → trigger words + results.
    # A query matches a topic if it contains any trigger word/phrase.
    FIXTURES: dict[str, dict] = {
        "price_sensitivity": {
            "triggers": ["price sensitivity", "elasticity", "price elastic", "willingness to pay",
                         "price-sensitive", "price sensitive", "wtp"],
            "results": [
                _r(
                    "Price Sensitivity in Emerging Markets — KPMG",
                    "https://kpmg.com/insights/price-sensitivity-emerging",
                    "Studies across Indian consumer segments show elasticity ranges from -0.8 (premium) to -1.6 (mass market). College students and young urban professionals exhibit elasticity around -1.2 to -1.4 for non-essential consumer goods.",
                ),
                _r(
                    "Indian Consumer Behavior Report 2025",
                    "https://mckinsey.com/india-consumer-2025",
                    "Price remains the primary decision driver for 68% of Indian Tier-2 consumers. Brand switching occurs at a 15–20% price differential. Students and young earners are disproportionately price-sensitive compared to household income levels.",
                ),
            ],
        },
        "competitor_price": {
            "triggers": ["competitor", "competition", "competitive", "rival", "tupperware", "cello",
                         "milton", "pricing benchmark", "market price"],
            "results": [
                _r(
                    "Competitor Pricing Analysis — Kitchen Storage Segment",
                    "https://businessline.in/kitchen-storage-pricing",
                    "The kitchen storage segment in India shows products priced ₹299–₹1,299. Leading brands (Cello, Tupperware) dominate the ₹499–₹799 band. D2C brands have gained traction at ₹699–₹899 with bundled starter kits. No player commands >18% share.",
                ),
                _r(
                    "Tupperware India Pricing",
                    "https://tupperware.in/collections/starter",
                    "Tupperware starter kitchen kit priced at ₹1,199 via direct sales. Cello modular storage at ₹549 via modern retail. Milton economy range at ₹399 via e-commerce.",
                ),
            ],
        },
        "market_size": {
            "triggers": ["market size", "market growth", "tam", "cagr", "industry size",
                         "demand", "market share", "penetration"],
            "results": [
                _r(
                    "India Kitchen Storage Market Report 2025",
                    "https://mordorintelligence.com/india-kitchen-storage",
                    "The Indian kitchen storage market is estimated at ₹8,200 crore in FY2025 and growing at 11.3% CAGR. Online channel penetration reached 34%. Tier-1 and Tier-2 cities account for 62% of organised market sales.",
                ),
            ],
        },
        "cac": {
            "triggers": ["customer acquisition", "cac", "acquisition cost", "marketing cost",
                         "advertising", "ad cost", "cpm", "performance marketing"],
            "results": [
                _r(
                    "D2C CAC Benchmarks India 2025",
                    "https://entrackr.com/d2c-cac-benchmarks-india",
                    "D2C consumer goods CAC in India ranges ₹180–₹420 depending on category and channel mix. Meta/Instagram-driven campaigns average ₹280 CAC for kitchen/lifestyle. Performance marketing CAC has risen 22% YoY due to ad cost inflation.",
                ),
                _r(
                    "Performance Marketing Costs Rising",
                    "https://afaqs.com/performance-marketing-india-2025",
                    "CPM costs on Meta properties increased 18–25% in H1 2025. Consumer brands report CAC erosion, with breakeven extending 30–45 days longer than 2024 estimates. Recommendation: diversify to influencer + organic.",
                    "news",
                ),
            ],
        },
        "distribution": {
            "triggers": ["distribution", "channel", "retail", "d2c", "e-commerce", "ecommerce",
                         "amazon", "flipkart", "logistics", "launch"],
            "results": [
                _r(
                    "Product Launch Strategy India — Common Pitfalls",
                    "https://yourstory.com/launch-india-pitfalls",
                    "Most D2C failures in India trace to under-estimating logistics complexity in Tier-2+ cities, overreliance on urban data, and insufficient investment in regional language content. Products priced ₹599–₹799 show best conversion in the home-goods category.",
                ),
                _r(
                    "Marketplace vs Modern Retail Margins — Home Goods",
                    "https://economictimes.com/home-goods-channel-margins",
                    "Modern retail chains typically take 28–35% margin on home-goods SKUs plus listing fees. Marketplaces charge 12–20% commission plus fulfilment. D2C websites retain full margin but carry higher CAC and return-handling costs.",
                ),
            ],
        },
        "regulatory": {
            "triggers": ["regulat", "compliance", "bis", "certification", "legal", "food-grade",
                         "food grade", "standard"],
            "results": [
                _r(
                    "BIS Certification Requirements for Kitchen Products",
                    "https://bis.gov.in/kitchen-plastics",
                    "Kitchen storage products using food-grade plastics require BIS certification under IS 10146. Certification timeline: 3–6 months. Non-certified products cannot be sold via major e-commerce platforms. Penalty: ₹2 lakh + product seizure.",
                ),
            ],
        },
        "default": {
            "triggers": [],
            "results": [
                _r(
                    "Strategic Market Entry — India Consumer Goods",
                    "https://bcg.com/india-consumer-market-entry",
                    "Successful entries in the Indian consumer market combine competitive pricing at entry, targeted digital marketing, and phased geographic expansion. Starting with 2–3 cities reduces execution risk while building proof points.",
                ),
            ],
        },
    }

    def __init__(self):
        # Copy built-ins so loading JSON never mutates the class attribute
        self.fixtures: dict[str, dict] = {
            k: {"triggers": list(v["triggers"]), "results": list(v["results"])}
            for k, v in self.FIXTURES.items()
        }
        self._load_json_fixtures()

    def _load_json_fixtures(self) -> None:
        if not FIXTURES_DIR.exists():
            return
        for path in sorted(FIXTURES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for topic, spec in data.items():
                    entry = self.fixtures.setdefault(topic, {"triggers": [], "results": []})
                    entry["triggers"].extend(t.lower() for t in spec.get("triggers", []))
                    for r in spec.get("results", []):
                        entry["results"].append(_r(
                            r.get("title", ""), r.get("url", ""),
                            r.get("snippet", ""), r.get("source_type", "web"),
                        ))
                logger.info(f"Loaded search fixtures from {path.name}")
            except Exception as e:
                logger.warning(f"Could not load fixture file {path.name}: {e}")

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        q_lower = query.lower()

        # Score each topic by how many of its trigger phrases appear in the query
        scored = sorted(
            (
                (sum(1 for t in spec["triggers"] if t in q_lower), topic)
                for topic, spec in self.fixtures.items()
                if topic != "default"
            ),
            reverse=True,
        )
        matched: list[SearchResult] = []
        for score, topic in scored:
            if score == 0:
                break
            for r in self.fixtures[topic]["results"]:
                if r not in matched:
                    matched.append(r)

        if not matched:
            matched = list(self.fixtures["default"]["results"])

        # Shuffle a *copy* so identical queries can vary without mutating fixtures
        random.shuffle(matched)
        return matched[:max_results]


class FallbackSearchProvider(SearchProvider):
    """Try a live provider first; use demo fixtures only if it returns nothing."""

    def __init__(self, primary: SearchProvider, fallback: SearchProvider):
        self.primary = primary
        self.fallback = fallback

    @property
    def name(self) -> str:
        return f"{self.primary.name}+{self.fallback.name}"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        results = await self.primary.search(query, max_results)
        if results:
            return results
        logger.warning(f"{self.primary.name} returned no results for '{query}' — using fixtures")
        return await self.fallback.search(query, max_results)


_provider: Optional[SearchProvider] = None


def get_search_provider() -> SearchProvider:
    global _provider
    if _provider is None:
        if settings.demo_mode:
            logger.info("Using DemoSearchProvider (DEMO_MODE=true)")
            _provider = DemoSearchProvider()
        elif settings.tavily_api_key:
            logger.info("Using Tavily search (fixtures as fallback)")
            _provider = FallbackSearchProvider(TavilyProvider(), DemoSearchProvider())
        elif settings.serpapi_key:
            logger.info("Using SerpAPI search (fixtures as fallback)")
            _provider = FallbackSearchProvider(SerpAPIProvider(), DemoSearchProvider())
        else:
            logger.info("Using DemoSearchProvider (no search API key configured)")
            _provider = DemoSearchProvider()
    return _provider
