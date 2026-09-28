import json
import logging
from typing import Dict, Any, List

from src.ai.tools.web_tools import web_search, fetch_webpage
from src.ai.tools.memory_tools import save_memory, get_memories, delete_memory
from src.ai.tools.skill_tools import create_skill, list_skills
from src.ai.prompts import get_current_time_info

logger = logging.getLogger(__name__)

# OpenAI-совместимая схема инструментов
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Поиск актуальной информации, новостей, фактов, курсов валют, цен и веб-страниц в интернете через DuckDuckGo в реальном времени. "
                "ВАЖНО: для поиска актуальных данных формулируй запрос с указанием текущего года или даты (например: 'новости ИИ 2026' или 'курс доллара 28.09.2026')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос. Формулируй с временным контекстом актуального года/месяца, если запрос касается свежих событий или меняющихся данных."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Количество результатов поиска (по умолчанию 5)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Загрузка и чтение содержимого веб-страницы по указанному URL (для подробного изучения статей и документации).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Полный URL веб-страницы (начиная с https:// или http://)"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Сохранить важный факт, предпочтение, биографические данные или заметку о пользователе в долговременную память.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "Факт, который нужно запомнить (например: 'Пользователя зовут Михаил, он работает DevOps-инженером')"
                    },
                    "category": {
                        "type": "string",
                        "description": "Категория факта (например: 'profile', 'work', 'preference', 'general')",
                        "default": "general"
                    }
                },
                "required": ["fact"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_memories",
            "description": "Получить список всех сохраненных фактов и воспоминаний о пользователе из долговременной памяти.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory",
            "description": "Удалить факт из долговременной памяти по его идентификатору (ID).",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "integer",
                        "description": "ID воспоминания для удаления"
                    }
                },
                "required": ["memory_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_skill",
            "description": "Создать новый скилл (специализацию, роль или режим работы) для ассистента прямо по запросу пользователя.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Уникальный краткий латинский идентификатор скилла (например: 'crypto_analyst', 'english_tutor', 'fitness_coach')"
                    },
                    "title": {
                        "type": "string",
                        "description": "Читаемое название скилла с эмодзи (например: '📊 Крипто-аналитик', '🇬🇧 Репетитор английского')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Краткое описание назначения скилла"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Инструкция (системный промпт), определяющая роль, стиль ответов, правила и поведение ассистента при активации скилла"
                    }
                },
                "required": ["name", "title", "description", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "Получить список всех зарегистрированных скиллов (включая встроенные и пользовательские).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


async def execute_tool(user_id: int, tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    Выполнение вызова инструмента и возврат результата в формате строки/JSON.
    """
    try:
        if tool_name == "web_search":
            query = arguments.get("query", "")
            max_results = int(arguments.get("max_results", 5))
            results = await web_search(query, max_results=max_results)
            time_info = get_current_time_info()
            enriched_output = {
                "search_timestamp": time_info["human_full"],
                "current_year": time_info["year"],
                "temporal_note": f"Поиск выполнен в реальном времени. Текущая дата: {time_info['human_date']}.",
                "query": query,
                "results": results
            }
            return json.dumps(enriched_output, ensure_ascii=False, indent=2)

        elif tool_name == "fetch_webpage":
            url = arguments.get("url", "")
            result = await fetch_webpage(url)
            time_info = get_current_time_info()
            return f"[Чтение веб-страницы в реальном времени: {time_info['human_full']}]\nURL: {url}\n\n{result}"

        elif tool_name == "save_memory":
            fact = arguments.get("fact", "")
            category = arguments.get("category", "general")
            res = await save_memory(user_id, fact, category)
            return json.dumps(res, ensure_ascii=False)

        elif tool_name == "get_memories":
            mems = await get_memories(user_id)
            return json.dumps(mems, ensure_ascii=False, indent=2)

        elif tool_name == "delete_memory":
            mem_id = int(arguments.get("memory_id", 0))
            res = await delete_memory(user_id, mem_id)
            return json.dumps(res, ensure_ascii=False)

        elif tool_name == "create_skill":
            name = arguments.get("name", "")
            title = arguments.get("title", "")
            desc = arguments.get("description", "")
            prompt = arguments.get("prompt", "")
            res = await create_skill(user_id, name, title, desc, prompt)
            return json.dumps(res, ensure_ascii=False)

        elif tool_name == "list_skills":
            skills = await list_skills(user_id)
            return json.dumps(skills, ensure_ascii=False, indent=2)

        else:
            return json.dumps({"error": f"Неизвестный инструмент '{tool_name}'"}, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Ошибка при вызове инструмента {tool_name} с аргументами {arguments}: {e}", exc_info=True)
        return json.dumps({"error": f"Ошибка выполнения {tool_name}: {str(e)}"}, ensure_ascii=False)
