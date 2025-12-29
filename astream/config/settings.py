from typing import Optional, Dict, Any
from databases import Database
from pydantic_settings import BaseSettings, SettingsConfigDict
import sys

# ===========================
# Domaines exclus
# ===========================
DEFAULT_EXCLUDED_DOMAINS = [
    "s22.anime-sama.fr",
    "vk.com",
    "vkvideo.ru",
    "moly.to",
    "vidmoly.net"
]

# ===========================
# Saisons spéciales
# ===========================
SEASON_TYPE_SPECIAL = 0        # Saison 0: Épisodes spéciaux/extras
SEASON_TYPE_FILM = 990          # Saison 990: Films (valeur haute pour tri en fin de liste)
SEASON_TYPE_OVA = 991           # Saison 991: OVA/OAV (valeur haute pour tri en fin de liste)
SPECIAL_SEASON_THRESHOLD = 900  # Seuil: saisons >= 900 sont considérées comme "spéciales" (films/OVA)

# ===========================
# Langues supportées
# ===========================
SUPPORTED_LANGUAGES = ["Tout", "VOSTFR", "VF"]
VALID_LANGUAGE_CODES = ["VOSTFR", "VF", "VF1", "VF2"]
LANGUAGES_TO_CHECK = ["vostfr", "vf", "vf1", "vf2"]

# ===========================
# TMDB
# ===========================
TMDB_ANIMATION_GENRE_ID = 16


# ===========================
# Classe AppSettings
# ===========================
class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ANIMESAMA_URL: Optional[str] = None
    ADDON_ID: Optional[str] = "community.astream"
    ADDON_NAME: Optional[str] = "AStream"
    FASTAPI_HOST: Optional[str] = "0.0.0.0"
    FASTAPI_PORT: Optional[int] = 8000
    FASTAPI_WORKERS: Optional[int] = 1
    USE_GUNICORN: Optional[bool] = True
    DATABASE_TYPE: Optional[str] = "sqlite"
    DATABASE_URL: Optional[str] = "username:password@hostname:port"
    DATABASE_PATH: Optional[str] = "data/astream.db"
    DATASET_ENABLED: Optional[bool] = True
    DATASET_URL: Optional[str] = None
    DATASET_UPDATE_INTERVAL: Optional[int] = 3600
    EPISODE_TTL: Optional[int] = 3600
    DYNAMIC_LIST_TTL: Optional[int] = 3600
    PLANNING_TTL: Optional[int] = 3600
    ONGOING_ANIME_TTL: Optional[int] = 3600
    FINISHED_ANIME_TTL: Optional[int] = 604800
    SCRAPE_LOCK_TTL: Optional[int] = 300
    SCRAPE_WAIT_TIMEOUT: Optional[int] = 30
    HTTP_TIMEOUT: Optional[int] = 15
    PROXY_URL: Optional[str] = None
    EXCLUDED_DOMAINS: Optional[str] = ""
    CUSTOM_HEADER_HTML: Optional[str] = None
    LOG_LEVEL: Optional[str] = "DEBUG"
    TMDB_API_KEY: Optional[str] = None
    TMDB_TTL: Optional[int] = 604800


# ===========================
# Instance Singleton
# ===========================
settings = AppSettings()

# ===========================
# Validation de la configuration
# ===========================
if not settings.ANIMESAMA_URL:
    from astream.utils.domain_fetcher import fetch_animesama_domain_sync
    fetched = fetch_animesama_domain_sync()
    if fetched:
        settings.ANIMESAMA_URL = fetched
    else:
        sys.stderr.write("ERROR: ANIMESAMA_URL not configured. See README: https://github.com/Dyhlio/astream#configuration\n")
        sys.exit(1)

if settings.ANIMESAMA_URL.endswith('/'):
    settings.ANIMESAMA_URL = settings.ANIMESAMA_URL.rstrip('/')

if not settings.ANIMESAMA_URL.startswith(('http://', 'https://')):
    settings.ANIMESAMA_URL = f"https://{settings.ANIMESAMA_URL}"

web_config = {
    "languages": {
        "Tout": "Tout afficher",
        "VOSTFR": "VOSTFR uniquement",
        "VF": "VF uniquement"
    },
    "tmdb": {
        "enabled": bool(settings.TMDB_API_KEY),
        "episode_mapping": False
    }
}


# ===========================
# Manifest Stremio de base
# ===========================
def get_base_manifest() -> Dict[str, Any]:
    """
    Retourne le manifest Stremio de base de l'addon.
    Ce manifest est ensuite personnalisé dans routes.py selon la config utilisateur.
    """
    return {
        "id": settings.ADDON_ID,
        "name": settings.ADDON_NAME,
        "description": f"{settings.ADDON_NAME} – Addon non officiel pour accéder au contenu d'Anime-Sama",
        "version": "2.1.3",
        "catalogs": [
            {
                "type": "anime",
                "id": "animesama_catalog",
                "name": "Anime-Sama",
                "extra": [
                    {"name": "search", "isRequired": False},
                    {"name": "genre", "isRequired": False, "options": []}
                ]
            }
        ],
        "resources": [
            "catalog",
            {"name": "meta", "types": ["anime"], "idPrefixes": ["as"]},
            {"name": "stream", "types": ["anime"], "idPrefixes": ["as"]}
        ],
        "types": ["anime"],
        "logo": "https://raw.githubusercontent.com/Dyhlio/astream/refs/heads/main/astream/public/astream-logo.jpg",
        "background": "https://raw.githubusercontent.com/Dyhlio/astream/refs/heads/main/astream/public/astream-background.png",
        "behaviorHints": {"configurable": True, "configurationRequired": False},
    }


# ===========================
# Configuration de la base de données
# ===========================
database_url = settings.DATABASE_PATH if settings.DATABASE_TYPE == "sqlite" else settings.DATABASE_URL
database = Database(f"{'sqlite' if settings.DATABASE_TYPE == 'sqlite' else 'postgresql'}://{'/' if settings.DATABASE_TYPE == 'sqlite' else ''}{database_url}")
