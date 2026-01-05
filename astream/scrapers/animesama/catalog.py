from typing import List, Optional, Dict, Any
from urllib.parse import quote
from bs4 import BeautifulSoup

from astream.utils.http_client import HttpClient
from astream.utils.logger import logger
from astream.scrapers.base import BaseScraper
from astream.utils.cache import CacheManager
from astream.config.settings import settings
from astream.scrapers.animesama.card_parser import CardParser
from astream.scrapers.animesama.parser import is_valid_content_type


# ===========================
# Classe AnimeSamaCatalog
# ===========================
class AnimeSamaCatalog(BaseScraper):

    def __init__(self, client: HttpClient):
        super().__init__(client, settings.ANIMESAMA_URL)

    async def get_homepage_content(self) -> List[Dict[str, Any]]:
        cache_key = "as:homepage"
        lock_key = "lock:homepage"

        async def fetch_homepage():
            logger.debug(f"Cache miss {cache_key} - Scraping homepage")
            response = await self._internal_request('get', f"{self.base_url}/")
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            all_anime = []
            seen_slugs = set()

            new_releases = await self._scrape_new_releases(soup, seen_slugs)
            all_anime.extend(new_releases)

            classics = await self._scrape_classics(soup, seen_slugs)
            all_anime.extend(classics)

            pepites = await self._scrape_pepites(soup, seen_slugs)
            all_anime.extend(pepites)

            logger.log("ANIMESAMA", f"Homepage: {len(all_anime)} anime récupérés")

            if not all_anime:
                logger.log("DATABASE", "Aucun anime trouvé sur homepage - pas de cache")
                return None

            return {"anime": all_anime, "total": len(all_anime)}

        try:
            cached_data = await CacheManager.get_or_fetch(
                cache_key=cache_key,
                fetch_func=fetch_homepage,
                lock_key=lock_key,
                ttl=settings.DYNAMIC_LIST_TTL
            )

            return cached_data.get("anime", []) if cached_data else []

        except Exception as e:
            logger.error(f"Échec récupération homepage: {e}")
            return []

    async def search_anime(self, query: str, language: Optional[str] = None, genre: Optional[str] = None) -> List[Dict[str, Any]]:
        cache_key = f"as:search:{query}"
        lock_key = f"lock:search:{query}"

        async def fetch_search_results():
            logger.log("DATABASE", f"Cache miss {cache_key} - Recherche live")
            all_results = []

            types_to_search = ["Anime", "Film", "Autres"]

            for content_type in types_to_search:
                try:
                    search_url = f"{self.base_url}/catalogue/?search={quote(query)}"

                    if language and language in ["VOSTFR", "VF"]:
                        search_url += f"&langue[]={language}"

                    if genre:
                        search_url += f"&genre[]={quote(genre)}"

                    search_url += f"&type[]={content_type}"

                    logger.debug(f"Recherche {content_type.lower()}: {search_url}")
                    response = await self._internal_request('get', search_url)
                    response.raise_for_status()

                    soup = BeautifulSoup(response.text, 'html.parser')

                    anime_cards = soup.find_all('a', href=lambda x: x and '/catalogue/' in x)

                    for card in anime_cards:
                        anime_data = CardParser.parse_anime_card(card)
                        if anime_data:
                            all_results.append(anime_data)

                except Exception as e:
                    logger.warning(f"Erreur recherche {content_type}: {e}")
                    continue

            logger.log("ANIMESAMA", f"Trouvé {len(all_results)} résultats pour '{query}'")

            if not all_results:
                logger.log("DATABASE", f"Pas de cache pour {cache_key} - 0 résultats")
                return None

            cache_data = {"results": all_results, "query": query, "total_found": len(all_results)}
            logger.log("DATABASE", f"Cache set {cache_key} - {len(all_results)} résultats")
            return cache_data

        try:
            cached_data = await CacheManager.get_or_fetch(
                cache_key=cache_key,
                fetch_func=fetch_search_results,
                lock_key=lock_key,
                ttl=settings.DYNAMIC_LIST_TTL
            )

            return cached_data.get("results", []) if cached_data else []

        except Exception as e:
            logger.error(f"Échec recherche anime: {e}")
            return []

    async def _scrape_container(self, soup: BeautifulSoup, container_id: str, parser_method, seen_slugs: set, section_name: str) -> List[Dict[str, Any]]:
        try:
            anime = []
            container = soup.find('div', id=container_id)
            if not container:
                return []

            anime_cards = container.find_all('div', class_='shrink-0')

            for card in anime_cards:
                link = card.find('a', href=lambda x: x and '/catalogue/' in x)
                if not link:
                    continue

                anime_data = parser_method(link)
                if anime_data and is_valid_content_type(anime_data.get('type', '')) and anime_data['slug'] not in seen_slugs:
                    seen_slugs.add(anime_data['slug'])
                    anime.append(anime_data)

            return anime

        except Exception as e:
            logger.warning(f"Erreur scraping {section_name}: {e}")
            return []

    async def _scrape_new_releases(self, soup: BeautifulSoup, seen_slugs: set) -> List[Dict[str, Any]]:
        return await self._scrape_container(soup, 'containerSorties', CardParser.parse_anime_card, seen_slugs, 'nouveaux contenus')

    async def _scrape_classics(self, soup: BeautifulSoup, seen_slugs: set) -> List[Dict[str, Any]]:
        return await self._scrape_container(soup, 'containerClassiques', CardParser.parse_anime_card, seen_slugs, 'classiques')

    async def _scrape_pepites(self, soup: BeautifulSoup, seen_slugs: set) -> List[Dict[str, Any]]:
        return await self._scrape_container(soup, 'containerPepites', CardParser.parse_pepites_card, seen_slugs, 'pépites')
