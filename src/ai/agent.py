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

        # Проверяем, не является ли запрос продолжением предыдущего ответа
        is_continuation_request = user_message.strip().lower() in (
            "продолжи", "продолжай", "дальше", "продолжай дальше",
            "продолжи ответ", "продолжи пожалуйста", "еще", "далее", "continue"
        )

        # Собираем сообщения для запроса к LLM
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})

        if is_continuation_request:
            messages.append({
                "role": "system",
                "content": (
                    "ВНИМАНИЕ: Пользователь просит продолжить предыдущий ответ. "
                    "Продолжай мысль строго с того места, где прервался твой предыдущий ответ. "
                    "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО повторять заново то, что уже было выведено выше!"
                )
            })

        messages.append({"role": "user", "content": user_message})

        max_iterations = 5
        iteration = 0
        final_response_text = ""
        tools_executed: List[str] = []

        # Инструменты для вызова
        tools = TOOLS_SCHEMA

        while iteration < max_iterations:
            iteration += 1

            if status_callback:
                if iteration == 1:
                    await status_callback("🤔 Думаю...")
                else:
                    await status_callback("⚙️ Обрабатываю...")

            try:
                response = await self.client.create_chat_completion(
                    messages=messages,
                    model=selected_model,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=4000,
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
                    tools_executed.append(fn_name)

                    # Инструменты выполняются незаметно ("за кадром")
                    if status_callback and fn_name == "web_search":
                        await status_callback("🔍 Ищу актуальные данные в интернете...")

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

                continue

            # Проверяем fallback парсер тегов <tool_call>
            xml_tool_calls = self._extract_hermes_xml_tool_calls(content)
            if xml_tool_calls:
                messages.append({"role": "assistant", "content": content})
                for call in xml_tool_calls:
                    fn_name = call["name"]
                    fn_args = call.get("arguments", {})
                    tools_executed.append(fn_name)

                    if status_callback and fn_name == "web_search":
                        await status_callback("🔍 Ищу в интернете...")

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
            # Тщательно очищаем любые технические теги <tool_call>, если модель их вывела в текст
            final_response_text = re.sub(r"<tool_call>.*?</tool_call>", "", final_response_text, flags=re.DOTALL).strip()
            final_response_text = re.sub(r"\[Результат инструмента.*?\]", "", final_response_text, flags=re.DOTALL).strip()
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
                    max_tokens=4000
                )
                final_response_text = (final_resp.choices[0].message.content or "").strip()
                final_response_text = re.sub(r"<tool_call>.*?</tool_call>", "", final_response_text, flags=re.DOTALL).strip()
            except Exception as e:
                logger.error(f"Ошибка при синтезе финального ответа: {e}")

        if not final_response_text:
            final_response_text = "К сожалению, не удалось получить развернутый ответ по данному запросу. Попробуй переформулировать вопрос или уточнить детали."

        # Предохранитель (Fallback Auto-Save): если пользователь явно просил запомнить,
        # а модель забыла вызвать функцию save_memory
        if "save_memory" not in tools_executed:
            mem_match = re.search(r"^(?:запомни|сохрани в память|запиши в память)[:,\s]+(.+)", user_message.strip(), re.IGNORECASE)
            if mem_match:
                extracted_fact = mem_match.group(1).strip()
                if extracted_fact:
                    try:
                        await db.add_memory(user_id, extracted_fact)
                        self.clear_user_cache(user_id)
                        logger.info(f"Предохранитель памяти: факт автоматически сохранен для user {user_id}: {extracted_fact}")
                    except Exception as e:
                        logger.warning(f"Ошибка предохранителя памяти: {e}")

        # Предохранитель для скиллов: если пользователь просил создать скилл, а модель не вызвала create_skill
        if "create_skill" not in tools_executed:
            skill_match = re.search(r"(?:создай|сделай|добавь)\s+скилл\s+['\"]?([^'\"\n]+)['\"]?", user_message.strip(), re.IGNORECASE)
            if skill_match and ("создан" in final_response_text.lower() or "активирован" in final_response_text.lower()):
                skill_raw_name = skill_match.group(1).strip()
                skill_id_name = re.sub(r"[^a-zA-Z0-9_]", "_", skill_raw_name.lower())[:30].strip("_") or "custom_skill"
                try:
                    await db.add_skill(
                        user_id=user_id,
                        name=skill_id_name,
                        title=f"⚡ {skill_raw_name}",
                        description=f"Персональный скилл {skill_raw_name}",
                        prompt=f"Ты работаешь в режиме специалиста: {skill_raw_name}. Отвечай структурированно и экспертно.",
                        is_builtin=0
                    )
                    self.clear_user_cache(user_id)
                    logger.info(f"Предохранитель скиллов: скилл '{skill_id_name}' автоматически сохранен для user {user_id}")
                except Exception as e:
                    logger.warning(f"Ошибка предохранителя скиллов: {e}")

        # Сохраняем диалог в историю (краткосрочная память)
        await db.add_message(user_id, "user", user_message)
        await db.add_message(user_id, "assistant", final_response_text)

        return final_response_text


agent = HermesAgent()
