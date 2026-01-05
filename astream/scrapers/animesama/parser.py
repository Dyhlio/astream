from typing import List, Optional, Dict, Any
import re
from bs4 import BeautifulSoup

from astream.utils.logger import logger
from astream.config.settings import SEASON_TYPE_FILM, SEASON_TYPE_SPECIAL, SEASON_TYPE_OVA
from astream.scrapers.animesama.helpers import (
    PANNEAU_ANIME_PATTERN,
    NEWSPF_PATTERN,
    SEASON_PATTERNS,
    clean_anime_title,
    parse_genres_string
)


# ===========================
# Analyse des détails d'anime
# ===========================
def parse_anime_details_from_html(soup: BeautifulSoup, anime_slug: str) -> Dict[str, Any]:
    try:
        anime_data = {
            "slug": anime_slug,
            "title": "",
            "synopsis": "",
            "image": "",
            "genres": [],
            "languages": "",
            "type": "anime"
        }
        title_elem = soup.find('h4', {'id': 'titreOeuvre'})
        if title_elem:
            anime_data["title"] = clean_anime_title(title_elem.get_text(strip=True))
        else:
            title_elem = soup.find('h1')
            if title_elem:
                anime_data["title"] = clean_anime_title(title_elem.get_text(strip=True))
        img_elem = soup.find('img', {'id': 'imgOeuvre'}) or soup.find('img', {'id': 'coverOeuvre'})
        if img_elem:
            anime_data["image"] = img_elem.get('src', '')
        synopsis_header = None
        for h2 in soup.find_all('h2'):
            if 'synopsis' in h2.get_text().lower():
                synopsis_header = h2
                break

        if synopsis_header:
            synopsis_elem = synopsis_header.find_next_sibling('p')
            if synopsis_elem:
                anime_data["synopsis"] = synopsis_elem.get_text(strip=True)
        genres_header = None
        for h2 in soup.find_all('h2'):
            if 'genres' in h2.get_text().lower():
                genres_header = h2
                break

        if genres_header:
            genres_elem = genres_header.find_next_sibling('a')
            if genres_elem:
                genres_text = genres_elem.get_text(strip=True)
                anime_data["genres"] = parse_genres_string(genres_text)

        return anime_data

    except Exception as e:
        logger.warning(f"Erreur lors du parsing des détails {anime_slug}: {e}")
        return {
            "slug": anime_slug,
            "title": "",
            "synopsis": "",
            "image": "",
            "genres": [],
            "languages": "",
            "type": "anime"
        }


# ===========================
# Aide à la détection des langues (DRY)
# ===========================
def _detect_language_markers_in_text(text: str) -> List[str]:
    try:
        languages = set()
        text_lower = text.lower()

        if '/vostfr' in text_lower:
            languages.add('VOSTFR')
        if '/vf/' in text_lower or text_lower.endswith('/vf'):
            languages.add('VF')
        if '/vf1' in text_lower:
            languages.add('VF1')
        if '/vf2' in text_lower:
            languages.add('VF2')

        default = ['VOSTFR']
        return sorted(languages) if languages else default

    except Exception as e:
        logger.warning(f"Erreur détection marqueurs langues: {e}")
        return ['VOSTFR']


# ===========================
# Analyse des langues
# ===========================
def parse_languages_from_html(html: str) -> List[str]:
    try:
        html_clean = re.sub(r'/\*.*?\*/', '', html, flags=re.DOTALL)

        panneau_matches = PANNEAU_ANIME_PATTERN.findall(html_clean)
        all_urls = ' '.join([url for _, url in panneau_matches])

        return _detect_language_markers_in_text(all_urls)

    except Exception as e:
        logger.warning(f"Erreur détection langues HTML: {e}")
        return ["VOSTFR"]


# ===========================
# Analyse des saisons
# ===========================
def parse_seasons_from_html(html: str, anime_slug: str, base_url: str) -> List[Dict[str, Any]]:
    try:
        seasons = []
        season_mapping = {}

        html_clean = re.sub(r'/\*.*?\*/', '', html, flags=re.DOTALL)

        season_matches = PANNEAU_ANIME_PATTERN.findall(html_clean)

        if not season_matches:
            logger.warning(f"Aucun panneauAnime() pour {anime_slug}")
            return []

        for name, url in season_matches:
            if name == "nom" and url == "url":
                continue

            season_info = parse_season_name(name, url)
            if not season_info:
                continue

            base_season_num = season_info["base_season_number"]

            # Regrouper les sous-saisons (VF1, VF2, etc.) sous la saison principale
            main_season_key = base_season_num

            if main_season_key not in season_mapping:
                season_mapping[main_season_key] = {
                    "season_number": base_season_num,
                    "name": season_info["display_name"],
                    "path": season_info["path"],
                    "languages": [],
                    "sub_seasons": []
                }

            languages = extract_languages_from_url(url)

            for lang in languages:
                if lang not in season_mapping[main_season_key]["languages"]:
                    season_mapping[main_season_key]["languages"].append(lang)

            if season_info.get("is_sub_season"):
                sub_season_url = season_info.get("sub_season_url", url)
                if not sub_season_url.startswith('http'):
                    sub_season_url = f"{base_url}/catalogue/{anime_slug}/{sub_season_url}"

                season_mapping[main_season_key]["sub_seasons"].append({
                    "name": name,
                    "url": sub_season_url,
                    "languages": languages
                })

        for season_data in season_mapping.values():
            seasons.append(season_data)

        seasons.sort(key=lambda x: x["season_number"])

        return seasons

    except Exception as e:
        logger.error(f"Échec parsing saisons {anime_slug}: {e}")
        return []


# ===========================
# Analyse du nom de saison
# ===========================
def parse_season_name(name: str, url: str) -> Optional[Dict[str, Any]]:
    """Parse le nom/URL de saison en numéro, path et détecte sous-saisons (saison1-2, OAV, films)."""
    try:
        path = url.split('/')[-2] if '/' in url else ''

        url_season_match = re.search(r'saison(\d+)$', path)
        if url_season_match:
            season_num = int(url_season_match.group(1))
            return {
                "season_number": season_num,
                "base_season_number": season_num,
                "display_name": f"Saison {season_num}",
                "path": f"saison{season_num}",
                "is_sub_season": False
            }

        url_sub_season_match = re.search(r'saison(\d+)-(\d+)', path)
        if url_sub_season_match:
            base_season = int(url_sub_season_match.group(1))
            sub_part = int(url_sub_season_match.group(2))
            return {
                "season_number": base_season,
                "base_season_number": base_season,
                "display_name": f"Saison {base_season}",
                "path": f"saison{base_season}",
                "is_sub_season": True,
                "sub_season_number": sub_part,
                "sub_season_url": url
            }

        if 'film' in name.lower() or 'film' in path:
            return {
                "season_number": SEASON_TYPE_FILM,
                "base_season_number": SEASON_TYPE_FILM,
                "display_name": "Films",
                "path": "film",
                "is_sub_season": False
            }

        if any(x in name.lower() for x in ['oav', 'ova', 'spécial', 'special']) or 'oav' in path:
            return {
                "season_number": SEASON_TYPE_SPECIAL,
                "base_season_number": SEASON_TYPE_SPECIAL,
                "display_name": "Spéciaux",
                "path": "oav",
                "is_sub_season": False
            }

        if 'hs' in path or 'hors' in name.lower():
            hs_match = re.search(r'(\d+)', path)
            if hs_match:
                base_season = int(hs_match.group(1))
                return {
                    "season_number": SEASON_TYPE_OVA,
                    "base_season_number": SEASON_TYPE_OVA,
                    "display_name": f"Saison {base_season} HS",
                    "path": f"saison{base_season}hs",
                    "is_sub_season": False
                }

        for pattern in SEASON_PATTERNS:
            match = pattern.search(name.lower())
            if match:
                base_season = int(match.group(1))
                sub_season = match.group(2)

                if sub_season:
                    return {
                        "season_number": base_season,
                        "base_season_number": base_season,
                        "display_name": f"Saison {base_season}",
                        "path": f"saison{base_season}",
                        "is_sub_season": True,
                        "sub_season_number": int(sub_season),
                        "sub_season_url": url
                    }
                else:
                    return {
                        "season_number": base_season,
                        "base_season_number": base_season,
                        "display_name": f"Saison {base_season}",
                        "path": f"saison{base_season}",
                        "is_sub_season": False
                    }

        logger.warning(f"Parser nom saison impossible: '{name}' (URL: '{url}')")
        return None

    except Exception as e:
        logger.warning(f"Erreur parsing '{name}': {e}")
        return None


# ===========================
# Extraction de la langue depuis l'URL
# ===========================
def extract_languages_from_url(url: str) -> List[str]:
    return _detect_language_markers_in_text(url)


# ===========================
# Analyse des titres de films
# ===========================
def parse_film_titles_from_html(html: str) -> List[str]:

    try:
        film_titles = NEWSPF_PATTERN.findall(html)

        if film_titles:
            logger.debug(f"{len(film_titles)} titres films extraits")
        return [title.strip() for title in film_titles]

    except Exception as e:
        logger.warning(f"Erreur extraction titres films: {e}")
        return []


# ===========================
# Validation du type de contenu
# ===========================
def is_valid_content_type(content_type: str) -> bool:

    if not content_type:
        return False
    content_lower = content_type.lower()
    return "anime" in content_lower or "film" in content_lower or "autres" in content_lower
