import asyncio
import logging
import aiohttp
import openai
from typing import List, Dict, Any, Optional

from src.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODELS,
    DEFAULT_MODEL,
    FREE_MODELS,
)

logger = logging.getLogger(__name__)


class MultiProviderAIClient:
    """
    Универсальный клиент ИИ с поддержкой сверхбыстрого Groq LPU (1000+ запросов/день)
    и OpenRouter (как резервный fallback-провайдер).
    """
    def __init__(self):
        self.groq_api_key = GROQ_API_KEY
        self.groq_base_url = GROQ_BASE_URL
        self.openrouter_api_key = OPENROUTER_API_KEY
        self.openrouter_base_url = OPENROUTER_BASE_URL
        self.default_model = DEFAULT_MODEL
        self.groq_models = list(GROQ_MODELS)
        self._cached_openrouter_models: List[str] = list(FREE_MODELS)
        self._last_models_fetch: float = 0

        # Клиент Groq (сверхбыстрый LPU, до 800 токенов/сек)
        self.groq_client = None
        if self.groq_api_key:
            self.groq_client = openai.AsyncOpenAI(
                base_url=self.groq_base_url,
                api_key=self.groq_api_key,
                default_headers={
                    "User-Agent": "Mozilla/5.0",
                }
            )

        # Клиент OpenRouter (для резервного переключения)
        self.openrouter_client = None
        if self.openrouter_api_key:
            self.openrouter_client = openai.AsyncOpenAI(
                base_url=self.openrouter_base_url,
                api_key=self.openrouter_api_key,
                default_headers={
                    "HTTP-Referer": "https://github.com/quanthar/tg-sales-bot",
                    "X-Title": "Telegram Sales & Assistant Bot",
                }
            )

    def is_groq_model(self, model_name: str) -> bool:
        """Проверка, относится ли модель к провайдеру Groq."""
        if not self.groq_client:
            return False
        if model_name in self.groq_models:
            return True
        return any(model_name.startswith(p) for p in ["openai/gpt-oss", "qwen/qwen3.8-27b"])

    async def fetch_available_free_models(self) -> List[str]:
        """
        Получение полного списка доступных моделей (сначала Groq, затем OpenRouter).
        Сохранено имя fetch_available_free_models для совместимости.
        """
        all_models = []
        if self.groq_client:
            all_models.extend(self.groq_models)

        # Дополняем моделями OpenRouter
        if self.openrouter_client:
            now = asyncio.get_event_loop().time()
            if not self._cached_openrouter_models or (now - self._last_models_fetch >= 1800):
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
                                    self._cached_openrouter_models = free
                                    self._last_models_fetch = now
                except Exception as e:
                    logger.warning(f"Не удалось обновить список моделей OpenRouter: {e}")

            for m in self._cached_openrouter_models:
                if m not in all_models:
                    all_models.append(m)

        return all_models or [self.default_model]

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 2500,
    ) -> Any:
        """
        Умная маршрутизация запроса к ИИ с автоматическим переключением провайдеров при ошибках или исчерпании лимитов.
        """
        target_model = model or self.default_model
        route_to_groq = self.is_groq_model(target_model)

        # 1. Если модель принадлежит Groq (или по умолчанию)
        if route_to_groq and self.groq_client:
            try:
                return await self._call_groq_with_fallback(
                    messages=messages,
                    primary_model=target_model,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                logger.warning(f"Все модели Groq временно недоступны ({e}). Переключаемся на OpenRouter...")
                if self.openrouter_client:
                    return await self._call_openrouter_with_fallback(
                        messages=messages,
                        primary_model="openrouter/free",
                        tools=tools,
                        tool_choice=tool_choice,
                        temperature=temperature,
                        max_tokens=1500,
                    )
                raise e

        # 2. Если модель принадлежит OpenRouter
        if self.openrouter_client:
            try:
                return await self._call_openrouter_with_fallback(
                    messages=messages,
                    primary_model=target_model,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                logger.warning(f"OpenRouter недоступен ({e}). Переключаемся на флагман Groq...")
                if self.groq_client:
                    return await self._call_groq_with_fallback(
                        messages=messages,
                        primary_model="openai/gpt-oss-120b",
                        tools=tools,
                        tool_choice=tool_choice,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                raise e

        raise RuntimeError("Ни один провайдер ИИ не настроен. Проверьте переменные GROQ_API или openroute_api в .env")

    async def _call_groq_with_fallback(
        self,
        messages: List[Dict[str, Any]],
        primary_model: str,
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: str,
        temperature: float,
        max_tokens: int,
    ) -> Any:
        """Попытка запроса к Groq с резервным перебором моделей Groq."""
        models_to_try = [primary_model]
        for m in self.groq_models:
            if m not in models_to_try:
                models_to_try.append(m)

        last_error = None
        for attempt_model in models_to_try:
            try:
                logger.info(f"Запрос к Groq LPU с моделью: {attempt_model}")
                # Оптимальный бюджет токенов для Telegram (1200-1500 токенов):
                # хватает на рассуждения (reasoning) и полный пост, при этом не исчерпывает 8000 TPM лимит Groq
                tokens_budget = min(max(max_tokens, 1200), 1600)

                kwargs = {
                    "model": attempt_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": tokens_budget,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice

                response = await self.groq_client.chat.completions.create(**kwargs)

                # Безопасная нормализация ответа (если content пуст из-за reasoning)
                if response.choices:
                    msg = response.choices[0].message
                    if not msg.content and getattr(msg, "reasoning", None) and not msg.tool_calls:
                        msg.content = msg.reasoning

                return response

            except openai.RateLimitError as e:
                logger.warning(f"Лимит запросов Groq (429) для {attempt_model}: {e}. Пробуем резервную...")
                last_error = e
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка вызова модели Groq {attempt_model}: {e}")
                last_error = e

        raise last_error or RuntimeError("Все модели Groq завершились с ошибкой.")

    async def _call_openrouter_with_fallback(
        self,
        messages: List[Dict[str, Any]],
        primary_model: str,
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: str,
        temperature: float,
        max_tokens: int,
    ) -> Any:
        """Попытка запроса к OpenRouter с резервным перебором моделей."""
        models_to_try = [primary_model]
        for m in self._cached_openrouter_models:
            if m not in models_to_try:
                models_to_try.append(m)
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

                response = await self.openrouter_client.chat.completions.create(**kwargs)
                return response
            except openai.RateLimitError as e:
                logger.warning(f"Лимит OpenRouter (429) для {attempt_model}: {e}. Пробуем следующую...")
                last_error = e
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Ошибка вызова OpenRouter {attempt_model}: {e}")
                last_error = e

        raise last_error or RuntimeError("Все модели OpenRouter завершились с ошибкой.")


ai_client = MultiProviderAIClient()
