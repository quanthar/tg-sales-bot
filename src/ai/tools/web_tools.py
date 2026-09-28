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
        items = []
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        try:
            with DDGS(timeout=7) as ddgs:
                # 1. Сначала пробуем обычный текстовый поиск
                raw_results = list(ddgs.text(clean_query, max_results=max_results))
                if raw_results:
                    for r in raw_results:
                        if r.get("href"):
                            items.append({
                                "title": r.get("title", ""),
                                "url": r.get("href", ""),
                                "snippet": r.get("body", "")
                            })
        except Exception as e:
            logger.warning(f"Ошибка ddgs.text: {e}")

        # 2. Если текстовый поиск пуст, пробуем поиск по новостям (для актуальных событий)
        if not items:
            try:
                with DDGS(timeout=7) as ddgs:
                    news_results = list(ddgs.news(clean_query, max_results=max_results))
                    if news_results:
                        for r in news_results:
                            if r.get("url"):
                                items.append({
                                    "title": r.get("title", ""),
                                    "url": r.get("url", ""),
                                    "snippet": r.get("body", "")
                                })
            except Exception as e:
                logger.warning(f"Ошибка ddgs.news: {e}")

        if items:
            return items

        # 3. Гарантированный возврат полезного ответа, если DuckDuckGo временно пуст
        return [
            {
                "title": f"Поиск: {clean_query}",
                "url": "",
                "snippet": f"Внешний поиск по запросу '{clean_query}' не вернул внешних ссылок. Ответь пользователю подробно, структурированно и экспертно, опираясь на свои системные знания."
            }
        ]

    loop = asyncio.get_running_loop()
    try:
        results = await asyncio.wait_for(loop.run_in_executor(None, _sync_ddg_search), timeout=10.0)
        return results
    except Exception as e:
        logger.error(f"Ошибка при выполнении web_search: {e}")
        return [
            {
                "title": f"Поиск: {clean_query}",
                "url": "",
                "snippet": f"Сервис поиска временно недоступен. Ответь пользователю на основе своих знаний."
            }
        ]


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
