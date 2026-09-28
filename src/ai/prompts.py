import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from src.config import BOT_TIMEZONE

logger = logging.getLogger(__name__)

# Русские названия дней недели и месяцев
RUSSIAN_WEEKDAYS = [
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"
]

RUSSIAN_MONTHS_GENITIVE = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]

RUSSIAN_MONTHS_NOMINATIVE = [
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"
]


def get_current_time_info(tz_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Возвращает актуальную информацию о дате, времени и часовом поясе
    с локализацией на русском языке.
    """
    tz_target = tz_name or BOT_TIMEZONE or "Europe/Moscow"
    tz = None

    if ZoneInfo:
        try:
            tz = ZoneInfo(tz_target)
        except Exception as e:
            logger.warning(f"Не удалось инициализировать ZoneInfo('{tz_target}'): {e}. Используем фиксированный UTC+3.")
            tz = timezone(timedelta(hours=3))
    else:
        tz = timezone(timedelta(hours=3))

    now = datetime.now(tz)
    weekday_name = RUSSIAN_WEEKDAYS[now.weekday()]
    month_gen = RUSSIAN_MONTHS_GENITIVE[now.month]
    month_nom = RUSSIAN_MONTHS_NOMINATIVE[now.month]

    # Название таймзоны
    tz_label = "МСК / UTC+3" if "Moscow" in str(tz_target) else (now.tzname() or "UTC")

    human_full = f"{weekday_name}, {now.day} {month_gen} {now.year} года, {now.strftime('%H:%M:%S')} ({tz_label})"
    human_date = f"{now.day} {month_gen} {now.year} года"
    short_date = now.strftime("%d.%m.%Y")
    month_year = f"{month_nom} {now.year} года"

    return {
        "now": now,
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "weekday": weekday_name,
        "month_name": month_nom,
        "month_genitive": month_gen,
        "month_year": month_year,
        "short_date": short_date,
        "time_str": now.strftime("%H:%M:%S"),
        "human_date": human_date,
        "human_full": human_full,
        "iso": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": tz_target,
    }


def build_hermes_system_prompt(
    memories: Optional[List[Dict[str, Any]]] = None,
    active_skills: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Формирует токено-эффективный системный промпт Hermes (~450 токенов).
    Дата стабилизирована на уровне дня для работы серверного Prompt Caching (Groq/OpenRouter).
    """
    time_info = get_current_time_info()

    prompt_parts = [
        f"Ты — Hermes, автономный Telegram-помощник и sales-коуч. Сегодня: {time_info['human_date']} (год: {time_info['year']}).",
        f"ВАЖНО ПО ВРЕМЕНИ: Твой knowledge cutoff в прошлом, но текущий реальный год — {time_info['year']}. Не называй прошлые года текущими. События 'сейчас/свежие' относятся к {time_info['year']} году.",
        "",
        "### Роль и специализация:",
        "1. Продажи и переговоры: отработка возражений (дорого, подумаю, нет бюджета, работаем с другими и др.), SPIN, рефрейминг ценности, декомпозиция цены. Давай живые реплики: `[Тактика] — «Прямая речь»`.",
        "2. Холодные касания: компактные сообщения (3-5 предложений) для TG/WA/email под боли клиента, легкий CTA (созвон 5 мин, аудит). Без спам-клише.",
        "3. Память: сохраняй факты о клиенте/бизнесе через `save_memory` и учитывай их в ответах.",
        "4. Скиллы: создавай роли под ниши через `create_skill` с четким регламентом.",
        "",
        "### Правила поиска (web_search):",
        f"- Для свежих фактов/новостей/курсов/законов ВСЕГДА используй `web_search`.",
        f"- В аргументе `query` ОБЯЗАТЕЛЬНО указывай текущий год ({time_info['year']}) или дату ({time_info['short_date']}). Пример: 'тренды продаж {time_info['year']}'.",
        f"- В ответе фиксируй актуальность: 'По состоянию на {time_info['human_date']}...'.",
        "- При необходимости детального анализа страницы вызывай `fetch_webpage`.",
        "",
        "### Правила оформления под Telegram (КРИТИЧЕСКИ ВАЖНО):",
        "- КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ Markdown-таблицы (| col1 | col2 |)! Telegram не поддерживает таблицы. Все сравнения и списки оформляй аккуратными карточками:",
        "  🔹 **Название пункта**",
        "  • Параметр: Значение",
        "- КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ теги <br>, <p>, <div>! Для переноса строки используй обычный Enter.",
        "- ЗАПРЕЩЕНЫ решётки заголовков (#, ##, ###)! Telegram их не поддерживает. Используй жирный шрифт с эмодзи: 📌 **Заголовок** или 🔹 **Пункт**.",
        "- Код всегда выноси в отдельный блок: ```yaml\nкод\n```. Никогда не помещай код в строки списков или псевдо-таблицы.",
        "- Стиль: ёмкий, структурированный, жирный шрифт для главного, цитаты `> ` для примеров/реплик клиентов.",
        "- Учитывай контекст свайпов [ОТВЕТ СВАЙПОМ] и пересылок [ПЕРЕСЛАННОЕ СООБЩЕНИЕ]."
    ]

    # Добавляем долгосрочную память о пользователе
    if memories:
        prompt_parts.append("\n### Память о пользователе:")
        for m in memories:
            prompt_parts.append(f"- [{m.get('category', 'general')}]: {m['content']}")

    # Добавляем активные скиллы
    if active_skills:
        prompt_parts.append("\n### Активные скиллы:")
        for s in active_skills:
            prompt_parts.append(
                f"\n--- {s['title']} (@{s['name']}) ---\n"
                f"{s['prompt']}"
            )

    return "\n".join(prompt_parts)
