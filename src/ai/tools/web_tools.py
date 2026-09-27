import asyncio
import logging
import re
import aiohttp
from typing import List, Dict, Any
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


async def web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Поиск информации в интернете через DuckDuckGo (бесплатно, без API ключей).
    Возвращает список результатов с заголовками, ссылками и сниппетами.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    def _sync_ddg_search():
        try:
            # Сначала пробуем ddgs
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(clean_query, max_results=max_results))
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")
                    }
                    for r in results if r.get("href")
                ]
        except Exception as e1:
            logger.warning(f"Ошибка ddgs: {e1}, пробуем duckduckgo_search...")
            try:
                from duckduckgo_search import DDGS
                with DDGS() as ddgs:
                    results = list(ddgs.text(clean_query, max_results=max_results))
                    return [
                        {
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", "")
                        }
                        for r in results if r.get("href")
                    ]
            except Exception as e2:
                logger.error(f"Все методы DuckDuckGo завершились с ошибкой: {e2}")
                return []

    loop = asyncio.get_running_loop()
    try:
        # Выполняем синхронный поиск в пуле потоков
        results = await loop.run_in_executor(None, _sync_ddg_search)
        return results
    except Exception as e:
        logger.error(f"Ошибка при выполнении web_search: {e}")
        return []


async def fetch_webpage(url: str, max_chars: int = 4000) -> str:
    """
    Загрузка и извлечение чистого текстового содержимого с веб-страницы.
    """
    if not url.startswith(("http://", "https://")):
        return "Ошибка: Некорректный URL (должен начинаться с http:// или https://)"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=True) as response:
                if response.status != 200:
                    return f"Ошибка загрузки страницы: HTTP {response.status}"

                html = await response.text(errors="replace")
                soup = BeautifulSoup(html, "html.parser")

                # Удаляем ненужные теги
                for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg"]):
                    tag.decompose()

                text = soup.get_text(separator=" ", strip=True)
                # Убираем множественные пробелы и переносы
                text = re.sub(r"\s+", " ", text)

                if len(text) > max_chars:
                    text = text[:max_chars] + "... [контент обрезан]"

                return text if text else "Страница не содержит читаемого текста."
    except asyncio.TimeoutError:
        return "Ошибка: Превышено время ожидания ответа от сервера (таймаут 10с)."
    except Exception as e:
        logger.error(f"Ошибка при загрузке страницы {url}: {e}")
        return f"Ошибка при загрузке страницы: {str(e)}"
