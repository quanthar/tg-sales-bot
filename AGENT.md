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
        ├── agent.py         # HermesAgent: цикл ReAct, tool calling, синтез ответов
        ├── prompts.py       # Системный промпт Hermes, динамическая дата, темпоральный поиск
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
BOT_TIMEZONE="Europe/Moscow"    # Часовой пояс по умолчанию для актуальной даты
```

---

## 4. 🧠 Ключевые модули и их логика

### `src/ai/prompts.py` (`build_hermes_system_prompt`, `get_current_time_info`)
- **Динамический временной контекст**:
  - Точная дата, день недели, месяц прописью, год, время и часовой пояс (по умолчанию `Europe/Moscow` / МСК).
  - Преодоление даты отсечки знаний (Knowledge Cutoff): модель прямо проинструктирована, какой сейчас год и день, с запретом называть 2023/2024 текущими годами.
- **Архитектурное описание роли Hermes**:
  - Эксперт по продажам, B2B/B2C переговорам, закрытию сделок и преодолению возражений (50+ тактик, SPIN, рефрейминг ценности, декомпозиция цены).
  - Мастер первых касаний и холодных продаж (Telegram, WhatsApp, email, звонки).
  - Архитектор кастомных скиллов (`create_skill`).
  - Бизнес-разведчик и фактчекер (`web_search`, `fetch_webpage`).
- **Темпоральный поиск (Temporal Search Awareness)**:
  - При любых поисковых задачах модель ОБЯЗАНА формулировать поисковый запрос `query` с указанием текущего года или даты (например: `тренды B2B продаж 2026`).
  - Анализ дат в сниппетах выдачи и приоритет свежести.
  - Обязательная фиксация даты актуальности данных в итоговом ответе («_По состоянию на 28 сентября 2026 года:_ ...»).
- **Динамические блоки**: долговременная память (`memories`) и активные скиллы (`skills`).

### `src/ai/client.py` (`MultiProviderAIClient`)
- **Основной провайдер**: `Groq` (`https://api.groq.com/openai/v1`).
  - Обязателен заголовок `User-Agent: Mozilla/5.0` (иначе Cloudflare возвращает HTTP 403).
  - Модели Groq: `openai/gpt-oss-120b` (флагман по умолчанию), `openai/gpt-oss-20b` (турбо), `qwen/qwen3.8-27b` (поиск/исследования).
  - Бюджет токенов: `tokens_budget = min(max(max_tokens, 1200), 1600)` — идеально для Telegram и не превышает лимит 8000 TPM на бесплатном тарифе Groq.
- **Резервный провайдер**: `OpenRouter` (`openrouter/free`, `google/gemma-4-31b-it:free` и др.).
- **Каскадный Fallback**: при 429 (Rate Limit) или 5xx ошибке на Groq запрос автоматически перенаправляется на OpenRouter без прерывания сессии пользователя.

### `src/ai/agent.py` (`HermesAgent`)
- **Формирование промпта** (`_build_system_prompt`):
  - Вызов `build_hermes_system_prompt` с передачей воспоминаний и активных скиллов.
  - Локальный кэш промпта `_prompt_cache` с инвалидацией через `clear_user_cache(user_id)` при `/clear`, изменении памяти или переключении скиллов.
- **ReAct Цикл вызова инструментов**:
  - Поддерживает нативный `tool_calls` OpenAI/Groq (до 4 итераций).
  - **КРИТИЧЕСКИ ВАЖНО ДЛЯ GROQ**: в `messages.append()` добавляется очищенный словарь ассистента `{"role": "assistant", "content": ..., "tool_calls": [...]}`. Запрещено передавать сырой `message.model_dump()`, так как Groq отклоняет запросы с `annotations` или `audio` ошибкой HTTP 400.
  - **Safety Synthesis Fallback**: если после выполнения инструментов финальный текст пуст, делается запрос на синтез ответа с передачей актуальной даты.

### `src/handlers.py` (Telegram UX и защита от сбоев)
1. **`smart_split_text(text, max_len=3900)`**:
   - Разбивает длинные ответы бота на части <= 3900 символов по границам абзацев/строк.
   - Автоматически балансирует открывающие/закрывающие блоки кода ```` ``` ```` между сообщениями.
   - Добавляет нумерацию `[1/N]` и отправляет через `safe_reply` с задержкой 0.08с.
   - При ошибке парсинга Markdown автоматически переключается на отправку обычным текстом.
2. **`schedule_user_message(message, text)` (Debouncing)**:
   - Если пользователь вставляет длинный текст, который Telegram режет на 2–3 сообщения, таймер (1.2 сек) и `asyncio.Lock` склеивают их в один запрос.
3. **Чистка контекста (`/clear` и кнопка `🧹 Очистить диалог`)**:
   - Очищает историю сообщений диалога `db.clear_history(user_id)`.
   - Инвалидирует кэш промпта и сессии `agent.clear_user_cache(user_id)`.
   - Сбрасывает зависшие буферы склейки сообщений `USER_BUFFERS[user_id]`.
4. **`extract_message_context(message)`**:
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
   - Подробная инструкция вынесена в специальный раздел **6. 🚀 Полное руководство по деплою (Deploy Guide)** ниже.
   - Ветка `main` на GitHub синхронизирована с Render через auto-deploy.
   - Веб-сервер в `src/web_server.py` обязан слушать порт `0.0.0.0:10000` и отдавать `200 OK` на `/health`.

---

## 6. 🚀 Полное руководство по деплою (Deploy Guide)

Этот раздел содержит исчерпывающее руководство для разработчика или ИИ-агента по развертыванию, мониторингу и поддержке непрерывной работы бота на облачной платформе **Render.com**.

---

### 6.1. Архитектура работы на Render (Web Service vs Worker)
- **Почему Web Service, а не Background Worker?**  
  На бесплатном тарифе Render тип «Background Worker» недоступен или ограничен. Поэтому бот задеплоен как **Web Service**.
- **Двойной режим работы в `main.py`**:
  1. В фоновом режиме запускается легковесный HTTP веб-сервер на базе `aiohttp` (`src/web_server.py`), который слушает `0.0.0.0:10000` и отдает статус здоровья по путям `/health` и `/ping`.
  2. В основном цикле событий запускается `dp.start_polling(bot)` библиотеки `aiogram 3.x` с предварительным сбросом вебхуков (`drop_pending_updates=True`).
- **Требование Render к порту**:  
  Render автоматически передает переменную окружения `PORT` (по умолчанию `10000`). Если приложение не открывает веб-порт в течение времени деплоя, Render завершает сборку ошибкой *«Port scan timeout»*. Наша архитектура запускает веб-сервер до блокирующего polling бота, гарантируя немедленный биндинг порта.

---

### 6.2. Пошаговый деплой с нуля (New Web Service)

1. **Подготовка репозитория**:
   - Убедитесь, что все актуальные файлы закоммичены и отправлены в GitHub:
     ```bash
     git add .
     git commit -m "feat: prepare project for render deployment"
     git push origin main
     ```
2. **Создание сервиса в панели Render**:
   - Войдите в [Render Dashboard](https://dashboard.render.com).
   - Нажмите **New +** → выберите **Web Service**.
   - Подключите свой GitHub-репозиторий (например, `quanthar/tg-sales-bot`).
3. **Параметры сервиса (Settings)**:
   - **Name**: `tg-sales-bot` (или любое желаемое имя).
   - **Region**: `Frankfurt (EU Central)` (рекомендуется для минимальной сетевой задержки до серверов Telegram).
   - **Branch**: `main`.
   - **Runtime**: `Python 3`.
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Instance Type**: `Free`.
   - **Health Check Path**: `/health` (в разделе *Advanced*).
   - **Auto-Deploy**: `Yes` (включен по умолчанию).

---

### 6.3. Настройка переменных окружения (Environment Variables)

В панели Render перейдите во вкладку **Environment** сервиса и добавьте следующие ключи:

| Переменная | Описание | Пример значения / Источник |
|---|---|---|
| `BOT_TOKEN` | Токен Telegram-бота | Получить у [@BotFather](https://t.me/BotFather) |
| `GROQ_API` | API ключ Groq (основной LPU провайдер) | `gsk_...` из [console.groq.com](https://console.groq.com) |
| `openroute_api` | Резервный API ключ OpenRouter | `sk-or-v1-...` из [openrouter.ai](https://openrouter.ai) |
| `PORT` | Порт внутреннего веб-сервера | `10000` (Render подставляет автоматически) |
| `BOT_TIMEZONE` | Часовой пояс для системного времени | `Europe/Moscow` (по умолчанию) |
| `RENDER_API` | *(Опционально)* API-ключ Render | Для триггера деплоя из терминала/скрипта |

> ⚠️ **КРИТИЧЕСКИ ВАЖНО**: Никогда не сохраняйте эти значения в открытом виде в файле `render.yaml` или репозитории Git! В `render.yaml` переменные должны иметь флаг `sync: false`.

---

### 6.4. Непрерывный деплой (Continuous Deployment / CI-CD)

Благодаря интеграции GitHub и Render процесс обновления бота полностью автоматизирован:
1. Вы вносите изменения в локальный код.
2. Делаете коммит и пуш:
   ```bash
   git add .
   git commit -m "fix: update sales prompt tactics"
   git push origin main
   ```
3. Render перехватывает Webhook от GitHub, автоматически собирает контейнер (`pip install`), перезапускает сервис (`python main.py`) и проверяет `/health`. Время выкатки обычно составляет 40–90 секунд.

---

### 6.5. Защита от засыпания 24/7 (Free Tier Sleep Prevention)

#### Проблема засыпания:
- На бесплатном тарифе Render Web Service **автоматически засыпает (Spins Down) через 15 минут отсутствия входящего HTTP-трафика**.
- Telegram-бот работает по протоколу **Long-Polling** (`getUpdates`). Это *исходящие* HTTPS-запросы с сервера Render к серверам Telegram. **Render НЕ считает их входящим трафиком!** Без внешних обращений контейнер уснет через 15 минут, и бот перестанет реагировать на сообщения.

#### Решение (Пингование каждые 9–10 минут):
1. Зарегистрируйтесь на бесплатном сервисе мониторинга: [cron-job.org](https://cron-job.org) (или [UptimeRobot](https://uptimerobot.com)).
2. Создайте новую задачу (Cronjob / Monitor):
   - **Title**: `TG Sales Bot Health Ping`
   - **URL**: `https://<ваше-имя-сервиса>.onrender.com/health` (например, `https://tg-sales-bot-qj8e.onrender.com/health`)
   - **Schedule**: Каждые 9 или 10 минут (`*/9 * * * *` или `*/10 * * * *`).
   - **Request method**: `GET`.
3. Каждые 10 минут эндпоинт `/health` будет получать HTTP-запрос и возвращать JSON `{"status": "healthy", ...}`, сбрасывая 15-минутный таймер сна Render. Бот будет онлайн 24/7.

---

### 6.6. Управление и ручной деплой через Render REST API

Если требуется запустить деплой без коммита или проверить статус через скрипт/терминал, используйте Render API:

- **ID текущего сервиса**: `srv-dasmq2ojo6nc73cfuebg`
- **Запуск принудительного редеплоя**:
  ```bash
  curl -X POST "https://api.render.com/v1/services/srv-dasmq2ojo6nc73cfuebg/deploys" \
    -H "Authorization: Bearer $RENDER_API" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -d '{"clearCache": "do_not_clear"}'
  ```
- **Проверка статуса последнего деплоя**:
  ```bash
  curl -s "https://api.render.com/v1/services/srv-dasmq2ojo6nc73cfuebg/deploys?limit=1" \
    -H "Authorization: Bearer $RENDER_API"
  ```
  *(Возможные статусы: `build_in_progress`, `live`, `build_failed`, `canceled`).*

---

### 6.7. Диагностика и устранение неполадок (Troubleshooting)

1. **Ошибка `TelegramConflictError: terminated by other getUpdates request`**:
   - **Причина**: Бот с данным `BOT_TOKEN` запущен одновременно в двух местах (например, локально на компьютере разработчика и в облаке Render). Telegram допускает только один активный polling-клиент.
   - **Решение**: Остановите локальный процесс бота (`Ctrl+C` в терминале или завершите процесс python) перед тестированием на Render.
2. **Ошибка `Cloudflare 403 Forbidden` при обращении к Groq**:
   - **Причина**: Groq защищен Cloudflare, блокирующим дефолтный User-Agent клиента `httpx`/`openai`.
   - **Решение**: В `src/ai/client.py` уже вшит заголовок `default_headers={"User-Agent": "Mozilla/5.0"}`. Убедитесь, что клиент инициализируется с этим заголовком.
3. **Ошибка `Timed out waiting for port 10000` при деплое**:
   - **Причина**: Веб-сервер в `main.py` не успел стартовать или упал из-за фатальной ошибки в импортах/базе.
   - **Решение**: Проверьте вкладку **Logs** в Render. `start_web_server()` вызывается до создания бота, что позволяет веб-серверу отвечать даже при отсутствии токена.
4. **Бот отвечает: `Я выполнил поиск, но ответ получился пустым`**:
   - **Причина**: Модель вызвала веб-поиск, но не сформулировала финальный текст, либо провайдер вернул пустой `content`.
   - **Решение**: В `src/ai/agent.py` внедрен синтез-фоллбэк, который повторно запрашивает у модели генерацию итогового ответа на базе полученных поисковых сниппетов.

---

### 6.8. Локальный запуск и Docker

Для локальной отладки без облака:

- **Локальный запуск (Python)**:
  ```bash
  python -m venv venv
  # Windows:
  .\venv\Scripts\activate
  # Linux/macOS:
  source venv/bin/activate

  pip install -r requirements.txt
  python main.py
  ```

- **Запуск в Docker**:
  ```bash
  docker build -t tg-sales-bot .
  docker run -d --name tg-bot --env-file .env -p 10000:10000 tg-sales-bot
  ```

