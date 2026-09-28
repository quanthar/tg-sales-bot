# AGENT.md — Архитектурная карта проекта Telegram Sales & AI Assistant

Этот файл предназначен для ИИ-агентов и разработчиков, чтобы мгновенно понять назначение проекта, структуру файлов, ключевые функции, алгоритмы и правила расширения кодовой базы.

---

## 1. 📌 О проекте (High-Level Overview)

- **Назначение**: Персональный Telegram-помощник и тренажер для менеджера по продажам с элементами автономного ИИ-агента.
- **Возможности**:
  1. **Интервальное обучение возражениям (Active Recall & SM-2)**: 10 возражений, 50 эталонных тактик преодоления из `data/objections.json`.
  2. **Сверхбыстрый ИИ (Groq LPU + OpenRouter Fallback)**: генерация за ~0.5–1 сек на моделях уровня 120B параметров с суточным лимитом в 1000+ запросов.
  3. **Долговременная память (Long-term Memory)**: бот автоматически или вручную сохраняет факты о пользователе в SQLite и учитывает их в системном промпте.
  4. **Модульная система скиллов (Skills)**: активация/деактивация ролей через меню `/skills`, создание новых кастомных скиллов прямо из диалога через `create_skill`.
  5. **Автономные инструменты (Tool Calling)**: веб-поиск в реальном времени (DuckDuckGo text + news), парсинг страниц по URL (`fetch_webpage`), память, скиллы.
  6. **Обработка Telegram UI-механик**: поддержка свайпов (Reply), цитат (Quote), пересланных постов (Forward), склейка разбитых длинных входящих сообщений (Debounce) и автоматическая пагинация длинных ответов бота.
- **Хостинг**: Render.com (Web Service), непрерывная работа через встроенный `/health` эндпоинт на порту `10000`.

---

## 2. 📂 Структура репозитория

```text
d:\ai\tg_bot\
├── main.py                  # Точка входа: параллельный запуск aiohttp сервера и бота
├── render.yaml              # Декларативная конфигурация деплоя на Render
├── requirements.txt         # Зависимости Python
├── Dockerfile               # Контейнеризация проекта
├── .gitignore               # Исключения (.env, data/*.db, __pycache__)
├── data/
│   ├── objections.json      # База категорий, возражений и 50 готовых скриптов продаж
│   └── assistant.db         # SQLite БД (создается автоматически при старте)
└── src/
    ├── config.py            # Загрузка .env, конфигурация моделей и путей
    ├── database.py          # SQLite ORM (aiosqlite): память, скиллы, история, SM-2
    ├── handlers.py          # Роутинг команд, debounce, разбивка сообщений, callback'и
    ├── keyboards.py         # Все InlineKeyboardMarkup для меню, возражений, скиллов и моделей
    ├── web_server.py        # aiohttp сервер для healthcheck (/health) на Render
    └── ai/
        ├── client.py        # Мульти-провайдерный AI-клиент (Groq LPU + OpenRouter fallback)
        ├── agent.py         # HermesAgent: цикл ReAct, системный промпт, tool calling
        └── tools/
            ├── registry.py  # TOOLS_SCHEMA (OpenAI format) и диспетчер execute_tool()
            ├── web_tools.py # web_search (DuckDuckGo + News) и fetch_webpage (BS4)
            ├── memory_tools.py # save_memory, get_memories, delete_memory
            └── skill_tools.py  # create_skill, list_skills
```

---

## 3. ⚙️ Переменные окружения (`.env`)

```env
BOT_TOKEN="8521109598:..."      # Токен бота из @BotFather
GROQ_API="gsk_..."              # API ключ от Groq Console (основной LPU провайдер)
openroute_api="sk-or-v1-..."    # API ключ OpenRouter (резервный fallback)
RENDER_API="rnd_..."            # API ключ Render для автоматизации деплоя
PORT=10000                      # Порт веб-сервера для Render
```

---

## 4. 🧠 Ключевые модули и их логика

### `src/ai/client.py` (`MultiProviderAIClient`)
- **Основной провайдер**: `Groq` (`https://api.groq.com/openai/v1`).
  - Обязателен заголовок `User-Agent: Mozilla/5.0` (иначе Cloudflare возвращает HTTP 403).
  - Модели Groq: `openai/gpt-oss-120b` (флагман по умолчанию), `openai/gpt-oss-20b` (турбо), `qwen/qwen3.8-27b` (поиск/исследования).
  - Бюджет токенов: `tokens_budget = min(max(max_tokens, 1200), 1600)` — идеально для Telegram и не превышает лимит 8000 TPM на бесплатном тарифе Groq.
- **Резервный провайдер**: `OpenRouter` (`openrouter/free`, `google/gemma-4-31b-it:free` и др.).
- **Каскадный Fallback**: при 429 (Rate Limit) или 5xx ошибке на Groq запрос автоматически перенаправляется на OpenRouter без прерывания сессии пользователя.

### `src/ai/agent.py` (`HermesAgent`)
- **Формирование промпта** (`_build_system_prompt`):
  - Базовые правила и контекст продаж.
  - Динамическая подстановка долговременных фактов из БД о пользователе (`db.get_memories`).
  - Динамическая подстановка активных скиллов (`db.get_active_skills`).
- **ReAct Цикл вызова инструментов**:
  - Поддерживает нативный `tool_calls` OpenAI/Groq (до 4 итераций).
  - **КРИТИЧЕСКИ ВАЖНО ДЛЯ GROQ**: в `messages.append()` добавляется очищенный словарь ассистента `{"role": "assistant", "content": ..., "tool_calls": [...]}`. Запрещено передавать сырой `message.model_dump()`, так как Groq отклоняет запросы с `annotations` или `audio` ошибкой HTTP 400.
  - **Safety Synthesis Fallback**: если после выполнения инструментов финальный текст пуст, делается финальный запрос на синтез ответа.

### `src/handlers.py` (Telegram UX и защита от сбоев)
1. **`smart_split_text(text, max_len=3900)`**:
   - Разбивает длинные ответы бота на части <= 3900 символов по границам абзацев/строк.
   - Автоматически балансирует открывающие/закрывающие блоки кода ```` ``` ```` между сообщениями.
   - Добавляет нумерацию `[1/N]` и отправляет через `safe_reply` с задержкой 0.08с.
   - При ошибке парсинга Markdown автоматически переключается на отправку обычным текстом.
2. **`schedule_user_message(message, text)` (Debouncing)**:
   - Если пользователь вставляет длинный текст, который Telegram режет на 2–3 сообщения, таймер (1.2 сек) и `asyncio.Lock` склеивают их в один запрос.
3. **`extract_message_context(message)`**:
   - Извлекает контекст свайпа (`reply_to_message` с текстом собеседника или бота).
   - Извлекает цитаты (`quote`).
   - Извлекает метаданные пересланных сообщений (`forward_origin`, канал, автор).

### `src/database.py` (`DatabaseManager`)
- Хранит данные в `data/assistant.db` через `aiosqlite`.
- Встроенные скиллы (пользователь `user_id = 0`):
  - 🎯 `sales_coach`: отработка возражений («дорого», «подумаю», «нет бюджета»), техники SPIN.
  - 📞 `cold_outreach`: первое касание, сценарии звонков, Telegram/WhatsApp письма.
  - 🔍 `web_researcher`: бизнес-разведка, поиск цен и конкурентов.
  - 🛠 `skill_creator`: интерактивное создание персональных ролей продаж.
- Тренажер возражений: таблица `user_progress` с реализацией интервального алгоритма **SM-2** (SuperMemo-2: `ease_factor`, `interval_days`, `repetitions`).

### `src/ai/tools/web_tools.py`
- `web_search(query, max_results=5)`:
  - 1-й шаг: текстовый поиск DuckDuckGo (`ddgs.text`).
  - 2-й шаг: поиск по новостям (`ddgs.news`), если текст пуст.
  - Защита таймаутом: `timeout=7s` в DDGS + `asyncio.wait_for(..., timeout=10.0s)`.

---

## 5. ⚠️ Правила и ограничения для разработчиков и ИИ-агентов

1. **Безопасность токенов**:
   - Никогда не коммитить `.env`, токены Telegram или ключи API в Git. Всегда проверять через `git status` и `git diff`.
2. **Сериализация вызовов инструментов**:
   - При передаче истории сообщений в Groq/OpenRouter никогда не передавать поля, не описанные в спецификации OpenAI Chat Completion (`annotations`, `refusal`, `reasoning` в role `assistant` должны удаляться).
3. **Обработка CallbackQuery в aiogram**:
   - Любой обработчик `callback_query` ОБЯЗАТЕЛЬНО должен оборачиваться в `try ... finally: await callback.answer()`, иначе кнопка в Telegram будет бесконечно крутить индикатор загрузки.
4. **Асинхронность и блокировки**:
   - Никогда не выполнять блокирующие синхронные операции (сетевые запросы `requests`, тяжелые парсеры) в основном event loop aiogram — использовать `loop.run_in_executor` или асинхронные библиотеки (`aiohttp`).
5. **Деплой на Render**:
   - Ветка `main` на GitHub синхронизирована с Render через auto-deploy.
   - Веб-сервер в `src/web_server.py` обязан слушать порт `0.0.0.0:10000` и отдавать `200 OK` на `/health`.
