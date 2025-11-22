from typing import Dict, List, Any, Optional
from fastapi import APIRouter, Request, Path
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from astream.config.settings import settings, web_config, get_base_manifest
from astream.utils.filters import get_all_excluded_domains
from astream.utils.validators import validate_config, ConfigModel
from astream.utils.logger import logger
from astream.services.stream import stream_service
from astream.services.catalog import catalog_service
from astream.services.metadata import metadata_service


# ===========================
# Routeur et Templates
# ===========================
templates = Jinja2Templates("astream/public")
main = APIRouter()


# ===========================
# Points de terminaison Web
# ===========================
@main.get("/", summary="Accueil", description="Redirige vers la page de configuration")
async def root() -> RedirectResponse:
    return RedirectResponse("/configure")


@main.get("/configure", summary="Configuration", description="Interface web pour configurer l'addon")
async def configure(request: Request) -> Any:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "CUSTOM_HEADER_HTML": settings.CUSTOM_HEADER_HTML or "",
            "EXCLUDED_DOMAINS": get_all_excluded_domains(),
            "webConfig": {**web_config, "ADDON_NAME": settings.ADDON_NAME},
        },
    )


@main.get("/{b64config}/configure", summary="Reconfiguration", description="Modifier une configuration existante")
async def configure_addon(
    request: Request,
    b64config: str = Path(..., description="Configuration encodée en base64")
) -> Any:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "CUSTOM_HEADER_HTML": settings.CUSTOM_HEADER_HTML or "",
            "EXCLUDED_DOMAINS": get_all_excluded_domains(),
            "webConfig": {**web_config, "ADDON_NAME": settings.ADDON_NAME},
        },
    )


# ===========================
# Points de terminaison Stremio
# ===========================
@main.get("/{b64config}/manifest.json", summary="Manifeste Stremio", description="Retourne les métadonnées de l'addon pour l'installation avec genres dynamiques")
async def manifest(
    request: Request,
    b64config: str = Path(..., description="Configuration encodée en base64")
) -> Dict[str, Any]:
    base_manifest = get_base_manifest()
    config = validate_config(b64config)

    language_extension = config.get("language", "Tout")
    if language_extension != "Tout":
        base_manifest["name"] = f"{settings.ADDON_NAME} | {language_extension}"
    else:
        base_manifest["name"] = settings.ADDON_NAME

    try:
        unique_genres = await catalog_service.extract_unique_genres()
        base_manifest["catalogs"][0]["extra"][2]["options"] = unique_genres
        logger.log("API", f"MANIFEST - Ajout de {len(unique_genres)} options de genre depuis le catalogue")
    except Exception as e:
        logger.error(f"MANIFEST - Echec de l'extraction des genres: {e}")

    return base_manifest


@main.get("/{b64config}/catalog/anime/animesama_catalog.json", summary="Catalogue d'anime", description="Retourne le catalogue d'anime avec recherche, filtrage par genre et langue, enrichissement TMDB")
@main.get("/{b64config}/catalog/anime/animesama_catalog/search={search}.json", summary="Recherche d'anime", description="Recherche d'anime par titre avec configuration")
@main.get("/{b64config}/catalog/anime/animesama_catalog/genre={genre}.json", summary="Filtrage par genre", description="Filtre le catalogue par genre avec configuration")
@main.get("/{b64config}/catalog/anime/animesama_catalog/search={search}&genre={genre}.json", summary="Recherche et filtrage", description="Recherche d'anime par titre et genre avec configuration")
async def animesama_catalog(
    request: Request,
    b64config: Optional[str] = None,
    search: Optional[str] = None,
    genre: Optional[str] = None
) -> Dict[str, List[Dict[str, Any]]]:
    try:
        if not search and "search" in request.query_params:
            search = request.query_params.get("search")
        if not genre and "genre" in request.query_params:
            genre = request.query_params.get("genre")

        config_dict = validate_config(b64config)
        config = ConfigModel(**config_dict)

        metas = await catalog_service.get_complete_catalog(
            request=request,
            b64config=b64config,
            search=search,
            genre=genre,
            config=config
        )

        return {"metas": metas}

    except Exception as e:
        logger.error(f"Erreur dans le catalogue: {e}")
        return {"metas": []}


@main.get("/{b64config}/meta/anime/{id}.json", summary="Métadonnées d'anime", description="Retourne les métadonnées complètes de l'anime avec liste d'épisodes et enrichissement TMDB")
async def animesama_meta(
    request: Request,
    id: str = Path(..., description="Identifiant d'anime (format: as:slug)"),
    b64config: str = Path(..., description="Configuration encodée en base64")
) -> Dict[str, Any]:
    config_dict = validate_config(b64config)
    config = ConfigModel(**config_dict)

    meta = await metadata_service.get_complete_anime_meta(
        anime_id=id,
        config=config,
        request=request,
        b64config=b64config
    )

    return {"meta": meta}


@main.get("/{b64config}/stream/anime/{episode_id}.json", summary="Obtenir les flux", description="Retourne les flux vidéo disponibles pour l'épisode demandé avec fusion dataset + scraping et filtrage de langue")
async def get_anime_stream(
    request: Request,
    episode_id: str = Path(..., description="Identifiant d'épisode (format: as:slug:s1e1)"),
    b64config: str = Path(..., description="Configuration encodée en base64")
) -> Dict[str, List[Dict[str, Any]]]:
    logger.log("STREAM", f"Demande de flux pour: {episode_id}")

    config = validate_config(b64config)
    episode_id_formatted = episode_id.replace(".json", "")
    language_filter = config.get("language", "Tout")
    language_order = config.get("languageOrder", "VOSTFR,VF")

    try:
        streams = await stream_service.get_episode_streams(
            episode_id=episode_id_formatted,
            language_filter=language_filter,
            language_order=language_order,
            config=config
        )

        logger.log("STREAM", f"{len(streams)} flux trouvés pour {episode_id}")
        return {"streams": streams}

    except Exception as e:
        logger.error(f"Erreur lors de la récupération des flux: {e}")
        return {"streams": []}


@main.get("/manifest.json", summary="Manifeste Stremio", description="Retourne les métadonnées de l'addon pour l'installation avec genres dynamiques")
async def manifest_default(request: Request) -> Dict[str, Any]:
    base_manifest = get_base_manifest()

    base_manifest["name"] = "| AStream"
    base_manifest["description"] = (
        f"CONFIGURATION OBSELETE, VEUILLEZ RECONFIGURER SUR {request.url.scheme}://{request.url.netloc}"
    )

    try:
        unique_genres = await catalog_service.extract_unique_genres()
        base_manifest["catalogs"][0]["extra"][2]["options"] = unique_genres
        logger.log("API", f"MANIFEST - Ajout de {len(unique_genres)} options de genre depuis le catalogue")
    except Exception as e:
        logger.error(f"MANIFEST - Echec de l'extraction des genres: {e}")

    return base_manifest


@main.get("/catalog/anime/animesama_catalog.json", summary="Catalogue d'anime", description="Retourne le catalogue d'anime avec recherche, filtrage par genre et langue, enrichissement TMDB")
@main.get("/catalog/anime/animesama_catalog/search={search}.json", summary="Recherche d'anime", description="Recherche d'anime par titre")
@main.get("/catalog/anime/animesama_catalog/genre={genre}.json", summary="Filtrage par genre", description="Filtre le catalogue par genre")
@main.get("/catalog/anime/animesama_catalog/search={search}&genre={genre}.json", summary="Recherche et filtrage", description="Recherche d'anime par titre et genre")
async def catalog_default(request: Request) -> Dict[str, List[Dict[str, Any]]]:
    try:
        search = request.query_params.get("search")
        genre = request.query_params.get("genre")

        config = ConfigModel()

        metas = await catalog_service.get_complete_catalog(
            request=request,
            b64config=None,
            search=search,
            genre=genre,
            config=config
        )

        return {"metas": metas}

    except Exception as e:
        logger.error(f"Erreur dans le catalogue: {e}")
        return {"metas": []}


@main.get("/meta/anime/{id}.json", summary="Métadonnées d'anime", description="Retourne les métadonnées complètes de l'anime avec liste d'épisodes et enrichissement TMDB")
async def meta_default(
    request: Request,
    id: str = Path(..., description="Identifiant d'anime (format: as:slug)")
) -> Dict[str, Any]:
    config = ConfigModel()

    meta = await metadata_service.get_complete_anime_meta(
        anime_id=id,
        config=config,
        request=request,
        b64config=None
    )

    return {"meta": meta}


@main.get("/stream/anime/{episode_id}.json", summary="Obtenir les flux", description="Retourne les flux vidéo disponibles pour l'épisode demandé avec fusion dataset + scraping et filtrage de langue")
async def stream_default(
    request: Request,
    episode_id: str = Path(..., description="Identifiant d'épisode (format: as:slug:s1e1)")
) -> Dict[str, List[Dict[str, Any]]]:
    logger.log("STREAM", f"Demande de flux pour: {episode_id}")

    episode_id_formatted = episode_id.replace(".json", "")
    config = ConfigModel()

    try:
        streams = await stream_service.get_episode_streams(
            episode_id=episode_id_formatted,
            language_filter=config.language,
            language_order=config.languageOrder,
            config=config.model_dump()
        )

        logger.log("STREAM", f"{len(streams)} flux trouvés pour {episode_id}")
        return {"streams": streams}

    except Exception as e:
        logger.error(f"Erreur lors de la récupération des flux: {e}")
        return {"streams": []}


@main.get("/health", summary="État de santé", description="Retourne l'état de santé actuel du service")
async def health() -> Dict[str, str]:
    return {"status": "ok"}
