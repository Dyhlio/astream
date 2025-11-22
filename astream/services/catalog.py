import asyncio
from typing import List, Dict, Any, Optional

from astream.utils.logger import logger
from astream.scrapers.animesama.client import animesama_api
from astream.scrapers.animesama.helpers import parse_genres_string
from astream.services.tmdb.service import tmdb_service
from astream.services.metadata import metadata_service
from astream.utils.cache import CacheKeys, CacheManager, cache_stats
from astream.utils.stremio_helpers import StremioMetaBuilder, StremioLinkBuilder
from astream.config.settings import settings


# ===========================
# Classe CatalogService
# ===========================
class CatalogService:
    """
    Service responsable de la gestion du catalogue et de la recherche d'anime.
    Gère la récupération des données, l'extraction des genres et l'enrichissement TMDB.
    """

    def __init__(self):
        self.animesama_api = animesama_api
        self.tmdb_service = tmdb_service

    async def get_complete_catalog(self, request, b64config: str, search: Optional[str] = None,
                                   genre: Optional[str] = None, config=None) -> List[Dict[str, Any]]:
        """
        Récupère le catalogue complet avec toute la logique.
        TOUTE la logique de récupération et construction du catalogue est ici.

        Args:
            request: Objet Request FastAPI
            b64config: Configuration encodée base64
            search: Terme de recherche optionnel
            genre: Genre à filtrer optionnel
            config: Configuration utilisateur

        Returns:
            Liste des objets meta formatés pour Stremio
        """
        logger.log("API", f"CATALOG - Catalogue Anime-Sama demandé, recherche: {search}, genre: {genre}")

        language_filter = config.language if config.language != "Tout" else None

        anime_data = await self._get_catalog_data(search, genre, language_filter)
        logger.log("API", f"Traitement de {len(anime_data)} anime.")

        enhanced_anime_data = await self._enrich_catalog_with_tmdb(anime_data, config)

        metas = await self._build_catalog_metas(request, b64config, enhanced_anime_data, config, metadata_service, genre)

        # Log résumé des stats de cache
        cache_stats.log_summary()
        cache_stats.reset()

        if search and genre:
            logger.log("API", f"CATALOG - Recherche '{search}' + Genre '{genre}': {len(metas)} anime trouvés")
        elif search:
            logger.log("API", f"CATALOG - Recherche '{search}': {len(metas)} anime trouvés")
        elif genre:
            logger.log("API", f"CATALOG - Genre '{genre}': {len(metas)} anime trouvés")
        else:
            logger.log("API", f"CATALOG - Retour de tous les {len(metas)} anime valides")

        return metas

    async def _get_catalog_data(self, search: Optional[str] = None, genre: Optional[str] = None,
                                language: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            if search:
                logger.log("ANIMESAMA", f"Recherche '{search}' (genre: {genre}, langue: {language})")
                return await self.animesama_api.search_anime(search, language, genre)
            else:
                logger.log("ANIMESAMA", "Récupération contenu homepage complet")
                return await self.animesama_api.get_homepage_content()

        except Exception as e:
            logger.error(f"Erreur récupération catalogue: {e}")
            return []

    def _extract_available_genres(self, catalog_data: List[Dict[str, Any]]) -> List[str]:
        try:
            genres = set()

            for anime in catalog_data:
                anime_genres = anime.get('genres', '')
                if isinstance(anime_genres, str) and anime_genres:
                    genre_list = parse_genres_string(anime_genres)
                    genres.update(genre_list)
                elif isinstance(anime_genres, list):
                    genres.update(anime_genres)

            cleaned_genres = [g for g in genres if len(g) > 1 and g not in ['N/A', 'n/a', '']]
            return sorted(cleaned_genres)

        except Exception as e:
            logger.warning(f"Erreur extraction genres: {e}")
            return []

    async def extract_unique_genres(self) -> List[str]:
        """
        Extrait les genres uniques depuis le catalogue Anime-Sama avec cache.
        Utilise le cache pour optimiser les performances avec DistributedLock.

        Returns:
            Liste triée des genres uniques
        """
        try:
            cache_key = CacheKeys.homepage()
            lock_key = "lock:homepage"

            async def fetch_homepage():
                logger.debug(f"Cache miss: {cache_key} - Récupération depuis Anime-Sama")
                anime_data = await self.animesama_api.get_homepage_content()
                if not anime_data:
                    return None
                return {"anime": anime_data, "total": len(anime_data)}

            cached_data = await CacheManager.get_or_fetch(
                cache_key=cache_key,
                fetch_func=fetch_homepage,
                lock_key=lock_key,
                ttl=settings.DYNAMIC_LIST_TTL
            )

            anime_data = cached_data.get("anime", []) if cached_data else []
            genres = self._extract_available_genres(anime_data)
            logger.debug(f"Extraction de {len(genres)} genres uniques depuis le catalogue")
            return genres

        except Exception as e:
            logger.error(f"Erreur extraction genres uniques: {e}")
            return []

    async def _enrich_catalog_with_tmdb(self, anime_data: list, config) -> list:
        if not config.tmdbEnabled or not (config.tmdbApiKey or settings.TMDB_API_KEY):
            return anime_data

        try:
            tasks = [self.tmdb_service.enhance_anime_metadata(anime, config) for anime in anime_data]
            enhanced_anime_data = await asyncio.gather(*tasks, return_exceptions=True)

            enriched_count = sum(1 for result in enhanced_anime_data if not isinstance(result, Exception) and result.get('poster'))
            enhanced_anime_data = [
                result if not isinstance(result, Exception) else anime_data[i]
                for i, result in enumerate(enhanced_anime_data)
            ]

            if enriched_count > 0:
                logger.log("TMDB", f"Enrichissement catalogue: {enriched_count}/{len(anime_data)} anime enrichis")

            return enhanced_anime_data
        except Exception as e:
            logger.error(f"Erreur enrichissement TMDB catalogue: {e}")
            return anime_data

    async def _build_catalog_metas(self, request, b64config: str, anime_data: list, config, metadata_service, genre_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Construit la liste des objets meta Stremio pour le catalogue.
        TOUTE la logique de traitement est ici.

        Args:
            request: Request FastAPI pour construction URLs
            b64config: Config base64
            anime_data: Liste des animes
            config: Configuration utilisateur
            metadata_service: Service metadata pour liens
            genre_filter: Filtre de genre optionnel

        Returns:
            Liste des objets meta formatés pour Stremio
        """
        metas = []

        for anime in anime_data:
            try:
                anime_slug = anime.get('slug', '')
                anime_title = anime.get('title', '').strip()

                if not anime_title:
                    anime_title = anime_slug.replace('-', ' ').title() if anime_slug else 'Titre indisponible'
                    logger.warning(f"CATALOG - Pas de titre pour {anime_slug}, utilisation de '{anime_title}'")

                genres_raw = anime.get('genres', '')
                genres = parse_genres_string(genres_raw) if isinstance(genres_raw, str) else genres_raw

                if genre_filter and genre_filter not in genres:
                    continue

                meta = StremioMetaBuilder.build_catalog_meta(anime, config)

                genre_links = StremioLinkBuilder.build_genre_links(request, b64config, genres)
                imdb_links = StremioLinkBuilder.build_imdb_link(anime)
                meta["links"] = genre_links + imdb_links

                meta["genres"] = genres

                metas.append(meta)

            except Exception as e:
                logger.error(f"Erreur construction meta pour {anime.get('slug', 'unknown')}: {e}")
                continue

        logo_count = sum(1 for anime in anime_data if anime.get('logo'))
        logger.log("API", f"CATALOG - Traitement terminé: {len(metas)} anime, {logo_count} avec logo TMDB")

        return metas


# ===========================
# Instance Singleton Globale
# ===========================
catalog_service = CatalogService()
