import asyncio
import logging
import aiohttp
import openai
from typing import List, Dict, Any, Optional

from src.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    DEFAULT_MODEL,
    FREE_MODELS,
)

logger = logging.getLogger(__name__)


class OpenRouterClient:
    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        self.base_url = OPENROUTER_BASE_URL
        self.default_model = DEFAULT_MODEL
        self._cached_free_models: List[str] = list(FREE_MODELS)
        self._last_models_fetch: float = 0

        self.client = openai.AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            default_headers={
                "HTTP-Referer": "https://github.com/quanthar/tg-sales-bot",
                "X-Title": "Telegram Hermes Assistant",
            }
        )

    async def fetch_available_free_models(self) -> List[str]:
        """
        Динамическое получение актуального списка бесплатных моделей из OpenRouter.
        """
        now = asyncio.get_event_loop().time()
        if self._cached_free_models and (now - self._last_models_fetch < 1800):
            return self._cached_free_models

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://openrouter.ai/api/v1/models", timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = data.get("data", [])
                        free = [
                            m["id"] for m in models
                            if m.get("pricing", {}).get("prompt") == "0" or ":free" in m["id"]
                        ]
                        if "openrouter/free" in [m["id"] for m in models]:
                            free.insert(0, "openrouter/free")

                        if free:
                            self._cached_free_models = free
                            self._last_models_fetch = now
                            logger.info(f"Обновлен список бесплатных моделей OpenRouter ({len(free)} доступно).")
        except Exception as e:
            logger.warning(f"Не удалось обновить список моделей OpenRouter: {e}")

        return self._cached_free_models

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 1500,
    ) -> Any:
        """
        Отправка запроса в OpenRouter с автоматическим переключением на резервные модели при ошибках.
        """
        models_to_try = []
        target_model = model or self.default_model

        if target_model:
            models_to_try.append(target_model)

        # Добавляем fallback-модели из кэша
        for m in self._cached_free_models:
            if m not in models_to_try:
                models_to_try.append(m)

        # Ограничиваем число попыток
        models_to_try = models_to_try[:4]

        last_error = None
        for attempt_model in models_to_try:
            try:
                logger.info(f"Запрос к OpenRouter с моделью: {attempt_model}")
                kwargs = {
                    "model": attempt_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice

                response = await self.client.chat.completions.create(**kwargs)
                return response
            except openai.RateLimitError as e:
                logger.warning(f"Лимит запросов (429) для модели {attempt_model}: {e}. Пробуем следующую модель...")
                last_error = e
                await asyncio.sleep(1)
            except openai.NotFoundError as e:
                logger.warning(f"Модель {attempt_model} недоступна (404): {e}. Пробуем следующую...")
                last_error = e
            except openai.BadRequestError as e:
                # Если модель не поддерживает tools, пробуем без tools или следующую модель
                err_msg = str(e).lower()
                if "tool" in err_msg and tools:
                    logger.warning(f"Модель {attempt_model} не поддерживает tools. Пробуем следующую модель...")
                last_error = e
            except Exception as e:
                logger.error(f"Ошибка при вызове OpenRouter ({attempt_model}): {e}")
                last_error = e

        raise last_error or RuntimeError("Все попытки обращения к моделям OpenRouter завершились с ошибкой.")


ai_client = OpenRouterClient()
