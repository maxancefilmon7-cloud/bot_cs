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

    async def get_listings(self, market_hash_name: str, count: int = 30) -> dict:
        """Récupère les listings actifs avec les descriptions des assets."""
        session = await self._get_session()
        encoded = quote(market_hash_name, safe="")
        url = f"{STEAM_BASE}/listings/{APP_ID}/{encoded}/render/"
        params = {
            "query": "",
            "start": 0,
            "count": count,
            "country": "FR",
            "language": "english",
            "currency": CURRENCY,
            "format": "json",
        }
        async with session.get(url, params=params) as resp:
            if resp.status == 429:
                raise RuntimeError("Rate limit Steam atteint, réessaie dans 1 minute.")
            if resp.status != 200:
                raise RuntimeError(f"Steam a répondu {resp.status}")
            return await resp.json(content_type=None)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
