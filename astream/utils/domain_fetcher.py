import asyncio
from typing import Optional
from bs4 import BeautifulSoup


async def fetch_animesama_domain() -> Optional[str]:
    status_url = "https://anime-sama.pw/"

    try:
        from curl_cffi.requests import AsyncSession

        async with AsyncSession(timeout=10, impersonate="chrome120") as session:
            response = await session.get(status_url)

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, 'html.parser')
            primary_link = soup.find('a', class_='btn-primary')

            if primary_link and primary_link.get('href'):
                return primary_link['href'].rstrip('/')

            table_body = soup.find('tbody', id='tableBody')
            if table_body:
                for row in table_body.find_all('tr'):
                    status_badge = row.find('span', class_='status-badge')
                    if status_badge and 'status-online' in status_badge.get('class', []):
                        domain_cell = row.find('td', class_='domain-name')
                        if domain_cell:
                            return f"https://{domain_cell.text.strip()}"

            return None

    except Exception:
        return None


def fetch_animesama_domain_sync() -> Optional[str]:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(fetch_animesama_domain())
        finally:
            loop.close()
    except Exception:
        return None
