import aiohttp
import asyncio
from urllib.parse import quote

STEAM_BASE = "https://steamcommunity.com/market"
APP_ID = 730
CURRENCY = 3  # EUR


class SteamMarketAPI:
    def __init__(self):
        self._session = None
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers)
        return self._session

    async def get_price_overview(self, market_hash_name: str) -> dict:
        """Prix global de l'item (min, médiane, volume)."""
        session = await self._get_session()
        url = f"{STEAM_BASE}/priceoverview/"
        params = {
            "appid": APP_ID,
            "currency": CURRENCY,
            "market_hash_name": market_hash_name,
        }
        async with session.get(url, params=params) as resp:
            if resp.status == 429:
                raise RuntimeError("Rate limit Steam atteint, réessaie dans 1 minute.")
            if resp.status != 200:
                raise RuntimeError(f"Steam a répondu {resp.status}")
            return await resp.json(content_type=None)

    async def get_listings(self, market_hash_name: str, start: int = 0, count: int = 100) -> dict:
        """Récupère les listings actifs avec les descriptions des assets."""
        session = await self._get_session()
        encoded = quote(market_hash_name, safe="")
        url = f"{STEAM_BASE}/listings/{APP_ID}/{encoded}/render/"
        params = {
            "query": "",
            "start": start,
            "count": count,
            "country": "FR",
            "language": "french",
            "currency": CURRENCY,
            "format": "json",
        }
        async with session.get(url, params=params) as resp:
            if resp.status == 429:
                raise RuntimeError("Rate limit Steam atteint, réessaie dans 1 minute.")
            if resp.status != 200:
                raise RuntimeError(f"Steam a répondu {resp.status}")
            return await resp.json(content_type=None)

    async def get_all_listings(self, market_hash_name: str, pages: int = 2) -> dict:
        """Récupère plusieurs pages de listings (100 par page) avec délai anti rate-limit."""
        import asyncio
        merged_assets: dict = {}
        merged_listing: dict = {}

        for page in range(pages):
            data = await self.get_listings(market_hash_name, start=page * 100, count=100)

            raw = data.get("assets", {})
            if isinstance(raw, dict):
                inner = raw.get("730", {})
                if isinstance(inner, dict):
                    section = inner.get("2", {})
                    if isinstance(section, dict):
                        merged_assets.update(section)

            linfo = data.get("listinginfo", {})
            if isinstance(linfo, dict):
                merged_listing.update(linfo)

            if page < pages - 1:
                await asyncio.sleep(1.5)

        # Retourner la même structure que get_listings pour que analyzer.py puisse la lire
        return {
            "assets": {"730": {"2": merged_assets}},
            "listinginfo": merged_listing,
        }

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
