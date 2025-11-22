import re
import asyncio
from typing import Set
from astream.utils.logger import logger
from astream.scrapers.base import BaseScraper
from astream.utils.cache import CacheManager, CacheKeys
from astream.config.settings import settings


# ===========================
# Classe AnimeSamaPlanning
# ===========================
class AnimeSamaPlanning(BaseScraper):

    def __init__(self, client):
        super().__init__(client, settings.ANIMESAMA_URL)
        self.planning_url = f"{settings.ANIMESAMA_URL}/planning/"

    async def get_current_planning_anime(self) -> Set[str]:

        cache_key = CacheKeys.planning()
        lock_key = "lock:planning"

        async def fetch_planning():
            logger.log("ANIMESAMA", "Scraping du planning en cours")
            response = await self._internal_request('get', self.planning_url)
            if not response:
                logger.warning("Impossible de récupérer le planning")
                return None

            anime_slugs = self._extract_anime_slugs_from_planning(response.text)

            if not anime_slugs:
                logger.log("DATABASE", "Planning vide après extraction - pas de cache")
                return None

            planning_data = {"anime_slugs": list(anime_slugs)}
            logger.log("ANIMESAMA", f"Planning mis à jour: {len(anime_slugs)} anime actifs")
            return planning_data

        try:
            cached_planning = await CacheManager.get_or_fetch(
                cache_key=cache_key,
                fetch_func=fetch_planning,
                lock_key=lock_key,
                ttl=settings.PLANNING_TTL
            )

            if cached_planning:
                logger.log("PERFORMANCE", "Planning récupéré depuis le cache")
                return set(cached_planning.get("anime_slugs", []))

            return set()

        except Exception as e:
            logger.error(f"Erreur scraping planning: {e}")
            return set()

    def _extract_anime_slugs_from_planning(self, html_content: str) -> Set[str]:

        anime_slugs = set()

        try:
            pattern = r'anime-card[^"]*planning-card"[^>]*>[\s\S]*?href="/catalogue/([^/"]+)'
            matches = re.findall(pattern, html_content)

            for slug in matches:
                if slug:
                    anime_slugs.add(slug)

            logger.debug(f"Slugs planning extraits: {sorted(anime_slugs)}")

        except Exception as e:
            logger.error(f"Erreur extraction slugs planning: {e}")

        return anime_slugs

    async def is_anime_ongoing(self, anime_slug: str) -> bool:

        current_planning = await self.get_current_planning_anime()

        is_ongoing = (
            anime_slug in current_planning or
            any(slug.startswith(anime_slug) for slug in current_planning) or
            any(anime_slug.startswith(slug) for slug in current_planning)
        )

        return is_ongoing


# ===========================
# Vérificateur de planning global
# ===========================
_planning_checker = None
_planning_checker_lock = asyncio.Lock()


# ===========================
# Fonctions d'aide
# ===========================
async def get_planning_checker():
    """
    Récupère ou initialise le planning checker avec protection contre les race conditions.
    """
    global _planning_checker
    async with _planning_checker_lock:
        if _planning_checker is None:
            from astream.scrapers.animesama.client import animesama_api
            _planning_checker = AnimeSamaPlanning(animesama_api.client)
        return _planning_checker


async def is_anime_ongoing(anime_slug: str) -> bool:

    checker = await get_planning_checker()
    return await checker.is_anime_ongoing(anime_slug)


async def get_smart_cache_ttl(anime_slug: str) -> int:
    try:
        if await is_anime_ongoing(anime_slug):
            ttl = settings.ONGOING_ANIME_TTL
            logger.log("PERFORMANCE", f"TTL anime EN COURS '{anime_slug}': {ttl}s")
        else:
            ttl = settings.FINISHED_ANIME_TTL
            logger.log("PERFORMANCE", f"TTL anime TERMINÉ '{anime_slug}': {ttl}s")

        return ttl

    except Exception as e:
        logger.warning(f"Erreur calcul TTL '{anime_slug}': {e}")
        return settings.ONGOING_ANIME_TTL
