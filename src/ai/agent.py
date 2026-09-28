import json
import logging
import re
from typing import Dict, Any, List, Optional, Callable, Awaitable

from src.database import db
from src.ai.client import ai_client
from src.ai.tools.registry import TOOLS_SCHEMA, execute_tool
from src.ai.prompts import build_hermes_system_prompt, get_current_time_info

logger = logging.getLogger(__name__)


class HermesAgent:
    """
    Агентный цикл Hermes с памятью, активными скиллами и инструментами (ReAct).
    """

    def __init__(self):
        self.client = ai_client
        # Кэш системного промпта пользователя: user_id -> {"date": "YYYY-MM-DD", "prompt": str}
        self._prompt_cache: Dict[int, Dict[str, Any]] = {}

    def clear_user_cache(self, user_id: int):
        """Инвалидация кэшированного состояния пользователя при очистке контекста или изменении данных."""
        self._prompt_cache.pop(user_id, None)

    async def _build_system_prompt(self, user_id: int, force_refresh: bool = False) -> str:
        """
        Формирование системного промпта с долгосрочной памятью, активными скиллами
        и актуальным временным контекстом с поддержкой кэша и принудительного обновления.
        """
        time_info = get_current_time_info()
        today = time_info["short_date"]

        if not force_refresh and user_id in self._prompt_cache:
            entry = self._prompt_cache[user_id]
            if entry.get("date") == today:
                return entry["prompt"]

        memories = await db.get_memories(user_id)
        active_skills = await db.get_active_skills(user_id)
        prompt = build_hermes_system_prompt(memories=memories, active_skills=active_skills)

        self._prompt_cache[user_id] = {
            "date": today,
            "prompt": prompt
        }
        return prompt

    def _extract_hermes_xml_tool_calls(self, content: str) -> List[Dict[str, Any]]:
        """
        Парсер вызовов инструментов в формате тегов Hermes:
        <tool_call>{"name": "...", "arguments": {...}}</tool_call>
        """
        calls = []
        pattern = r"<tool_call>\s*(\{.*?\})\s*</tool_call>"
        matches = re.findall(pattern, content, re.DOTALL)
        for m in matches:
            try:
                data = json.loads(m)
                if "name" in data:
                    calls.append({
                        "name": data["name"],
                        "arguments": data.get("arguments", {})
                    })
            except Exception:
                continue
        return calls

    async def run(
        self,
        user_id: int,
        user_message: str,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None
    ) -> str:
        """
        Главный цикл обработки сообщения пользователя.
        """
        # 1. Получаем модель пользователя
        selected_model = await db.get_user_model(user_id)

        # 2. Формируем системный промпт
        system_prompt = await self._build_system_prompt(user_id)

        # 3. Загружаем историю диалога (краткосрочная память)
        history = await db.get_history(user_id)

        # Собираем сообщения для запроса к LLM
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_message})

        max_iterations = 5
        iteration = 0
        final_response_text = ""

        # Инструменты для вызова
        tools = TOOLS_SCHEMA

        while iteration < max_iterations:
            iteration += 1

            if status_callback:
                if iteration == 1:
                    await status_callback("🤔 Думаю...")
                else:
                    await status_callback("⚙️ Обрабатываю результаты...")

            try:
                response = await self.client.create_chat_completion(
                    messages=messages,
                    model=selected_model,
                    tools=tools,
                    tool_choice="auto",
                )
            except Exception as e:
                logger.error(f"Ошибка при запросе к модели: {e}", exc_info=True)
                return f"⚠️ Произошла ошибка при обращении к ИИ ({selected_model}): {str(e)}"

            choice = response.choices[0]
            message = choice.message
            content = message.content or ""
            tool_calls = message.tool_calls

            # Проверяем нативные OpenAI tool_calls
            if tool_calls:
                # Добавляем ответ ассистента с вызовами инструментов
                # ВАЖНО: передаем только чистые поля role, content и tool_calls,
                # так как Pydantic model_dump() добавляет annotations, refusal, audio, что вызывает ошибку HTTP 400 в Groq!
                assistant_msg = {"role": "assistant"}
                if content:
                    assistant_msg["content"] = content
                else:
                    assistant_msg["content"] = None

                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in tool_calls
                ]
                messages.append(assistant_msg)

                for tc in tool_calls:
                    fn_name = tc.function.name
                    try:
                        fn_args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        fn_args = {}

                    logger.info(f"Вызов инструмента: {fn_name} с аргументами: {fn_args}")

                    if status_callback:
                        if fn_name == "web_search":
                            await status_callback(f"🔍 Ищу в интернете: «{fn_args.get('query', '')}»...")
                        elif fn_name == "fetch_webpage":
                            await status_callback("🌐 Изучаю веб-страницу...")
                        elif fn_name == "save_memory":
                            await status_callback("🧠 Сохраняю в память...")
                        elif fn_name == "create_skill":
                            await status_callback(f"⚡ Создаю новый скилл: {fn_args.get('title', '')}...")

                    # Выполняем инструмент
                    tool_output = await execute_tool(user_id, fn_name, fn_args)

                    # Инвалидация кэша промпта при изменении памяти или скиллов
                    if fn_name in ("save_memory", "delete_memory", "create_skill"):
                        self.clear_user_cache(user_id)

                    # Добавляем результат работы инструмента в сообщения
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": fn_name,
                        "content": tool_output
                    })

                # Следующая итерация для получения ответа с учетом результатов инструментов
                continue

            # Проверяем fallback парсер тегов <tool_call>
            xml_tool_calls = self._extract_hermes_xml_tool_calls(content)
            if xml_tool_calls:
                messages.append({"role": "assistant", "content": content})
                for call in xml_tool_calls:
                    fn_name = call["name"]
                    fn_args = call.get("arguments", {})

                    if status_callback:
                        if fn_name == "web_search":
                            await status_callback(f"🔍 Ищу в интернете: «{fn_args.get('query', '')}»...")
                        elif fn_name == "save_memory":
                            await status_callback("🧠 Сохраняю факт в память...")
                        elif fn_name == "create_skill":
                            await status_callback("⚡ Создаю новый скилл...")

                    tool_output = await execute_tool(user_id, fn_name, fn_args)
                    if fn_name in ("save_memory", "delete_memory", "create_skill"):
                        self.clear_user_cache(user_id)
                    messages.append({
                        "role": "user",
                        "content": f"[Результат инструмента {fn_name}]: {tool_output}"
                    })
                continue

            # Финальный текстовый ответ получен
            final_response_text = content.strip()
            # Очищаем теги <tool_call>, если вдруг остались
            final_response_text = re.sub(r"<tool_call>.*?</tool_call>", "", final_response_text, flags=re.DOTALL).strip()
            break

        if not final_response_text:
            logger.info("Ответ пуст после выполнения инструментов, запрашиваем итоговую формулировку у модели...")
            try:
                time_info = get_current_time_info()
                final_resp = await self.client.create_chat_completion(
                    messages=messages + [{
                        "role": "user",
                        "content": f"Сформулируй итоговый развернутый ответ для пользователя на основе полученных данных с учетом актуальной даты ({time_info['human_date']})."
                    }],
                    model=selected_model,
                    max_tokens=2500
                )
                final_response_text = (final_resp.choices[0].message.content or "").strip()
            except Exception as e:
                logger.error(f"Ошибка при синтезе финального ответа: {e}")

        if not final_response_text:
            final_response_text = "К сожалению, не удалось получить развернутый ответ по данному запросу. Попробуй переформулировать вопрос или уточнить детали."

        # Сохраняем диалог в историю (краткосрочная память)
        await db.add_message(user_id, "user", user_message)
        await db.add_message(user_id, "assistant", final_response_text)

        return final_response_text


agent = HermesAgent()
