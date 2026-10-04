import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import aiohttp

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from src.config import OPENWEATHERMAP_API_KEY, BOT_TIMEZONE

logger = logging.getLogger(__name__)

# Санкт-Петербург координаты
SPB_LAT = 59.9343
SPB_LON = 30.3351
SPB_CITY_NAME = "Санкт-Петербург"

# Кэш прогноза погоды: {"timestamp": float, "text": str, "data": dict}
_WEATHER_CACHE: Dict[str, Any] = {
    "timestamp": 0,
    "text": "",
    "data": None,
}
# Время жизни кэша: 45 минут (достаточно для отслеживания дождей и исключения лишних API-вызовов)
WEATHER_CACHE_TTL = 45 * 60


def _get_spb_tz():
    tz_target = BOT_TIMEZONE or "Europe/Moscow"
    if ZoneInfo:
        try:
            return ZoneInfo(tz_target)
        except Exception:
            pass
    return timezone(timedelta(hours=3))


def _weather_icon_emoji(icon_code: str, main: str) -> str:
    """Подбор подходящего эмодзи по коду погоды."""
    code = (icon_code or "").lower()
    main = (main or "").lower()
    if "01" in code:
        return "☀️" if "d" in code else "🌙"
    if "02" in code:
        return "⛅"
    if "03" in code or "04" in code:
        return "☁️"
    if "09" in code or "10" in code or "rain" in main:
        return "🌧"
    if "11" in code or "thunderstorm" in main:
        return "⛈"
    if "13" in code or "snow" in main:
        return "❄️"
    if "50" in code or "mist" in main or "fog" in main:
        return "🌫"
    return "🌤"


async def fetch_weather_forecast(force_refresh: bool = False) -> str:
    """
    Получение прогноза погоды по Санкт-Петербургу на текущий день
    (утро, день, вечер, ночь) с кэшированием и отслеживанием осадков.
    """
    now_loop = asyncio.get_event_loop().time()
    if not force_refresh and _WEATHER_CACHE["text"] and (now_loop - _WEATHER_CACHE["timestamp"] < WEATHER_CACHE_TTL):
        return _WEATHER_CACHE["text"]

    if not OPENWEATHERMAP_API_KEY:
        return "⚠️ API-ключ OpenWeatherMap не настроен в файле .env (`openweathermap_api`)."

    spb_tz = _get_spb_tz()
    current_time = datetime.now(spb_tz)
    today_str = current_time.strftime("%Y-%m-%d")

    url = (
        f"https://api.openweathermap.org/data/2.5/forecast"
        f"?lat={SPB_LAT}&lon={SPB_LON}&appid={OPENWEATHERMAP_API_KEY}&units=metric&lang=ru"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Ошибка OpenWeatherMap HTTP {resp.status}: {error_text}")
                    if _WEATHER_CACHE["text"]:
                        return _WEATHER_CACHE["text"]
                    return f"⚠️ Не удалось получить прогноз погоды (код {resp.status})."

                data = await resp.json()

    except Exception as e:
        logger.error(f"Сетевая ошибка при запросе погоды: {e}")
        if _WEATHER_CACHE["text"]:
            return _WEATHER_CACHE["text"]
        return f"⚠️ Ошибка соединения с погодным сервисом: {e}"

    entries = data.get("list", [])
    if not entries:
        return "⚠️ Сервис погоды вернул пустые данные."

    # Определяем, какой день показывать:
    # Если текущее время >= 18:00, утренние/дневные интервалы сегодня уже прошли,
    # поэтому показываем ближайшую ночь и полный следующий день (утро, день, вечер, ночь).
    # Если утро/день (< 18:00), показываем текущий день (утро, день, вечер, ночь).
    is_late_evening = current_time.hour >= 18
    target_date = (current_time + timedelta(days=1)).date() if is_late_evening else current_time.date()
    target_date_str = target_date.strftime("%d.%m.%Y")

    slots = {
        "утро": None,
        "день": None,
        "вечер": None,
        "ночь": None,
    }

    has_rain = False
    has_snow = False
    max_wind = 0.0

    for item in entries:
        dt_utc = datetime.fromtimestamp(item["dt"], tz=timezone.utc)
        dt_local = dt_utc.astimezone(spb_tz)
        local_date = dt_local.date()
        hour = dt_local.hour

        # Проверяем осадки на ближайшие 24 часа
        if (dt_local - current_time).total_seconds() <= 24 * 3600:
            weather_list = item.get("weather", [{}])
            condition = weather_list[0].get("main", "").lower()
            desc = weather_list[0].get("description", "").lower()

            if "rain" in condition or "дожд" in desc or "drizzle" in condition:
                has_rain = True
            if "snow" in condition or "снег" in desc:
                has_snow = True

            wind_speed = item.get("wind", {}).get("speed", 0)
            if wind_speed > max_wind:
                max_wind = wind_speed

        # Заполняем слоты целевого дня
        if local_date == target_date:
            if 5 <= hour <= 10 and slots["утро"] is None:
                slots["утро"] = item
            elif 11 <= hour <= 16 and slots["день"] is None:
                slots["день"] = item
            elif 17 <= hour <= 22 and slots["вечер"] is None:
                slots["вечер"] = item
            elif hour >= 23 and slots["ночь"] is None:
                slots["ночь"] = item
        # Ночь целевого дня (00:00 - 04:00 следующих суток)
        elif local_date == (target_date + timedelta(days=1)):
            if 0 <= hour <= 4 and slots["ночь"] is None:
                slots["ночь"] = item

    # Дополнительный фоллбэк: если слот все еще пуст, подбираем ближайшие доступные интервалы
    for item in entries:
        dt_local = datetime.fromtimestamp(item["dt"], tz=timezone.utc).astimezone(spb_tz)
        hour = dt_local.hour
        if not is_late_evening and dt_local.date() == current_time.date():
            if slots["утро"] is None and hour < 12:
                slots["утро"] = item
            elif slots["день"] is None and 11 <= hour < 17:
                slots["день"] = item
            elif slots["вечер"] is None and 17 <= hour <= 23:
                slots["вечер"] = item

    def format_slot(slot_item, label: str, default_icon: str) -> str:
        if not slot_item:
            return f"  {default_icon} **{label}**: ~"
        main_data = slot_item.get("main", {})
        temp = round(main_data.get("temp", 0))
        feels = round(main_data.get("feels_like", 0))
        weather_info = slot_item.get("weather", [{}])[0]
        desc = weather_info.get("description", "облачно").capitalize()
        icon = _weather_icon_emoji(weather_info.get("icon", ""), weather_info.get("main", ""))

        temp_sign = "+" if temp > 0 else ""
        feels_sign = "+" if feels > 0 else ""

        return (
            f"  {icon} **{label}**:\n"
            f"     Температура: **{temp_sign}{temp}°C** (ощущается как **{feels_sign}{feels}°C**)\n"
            f"     Условия: _{desc}_"
        )

    # Давление и влажность по текущему/первому интервалу
    first_item = entries[0]
    pressure_hpa = first_item.get("main", {}).get("pressure", 1013)
    pressure_mm = round(pressure_hpa * 0.750062)
    humidity = first_item.get("main", {}).get("humidity", 70)
    wind_now = first_item.get("wind", {}).get("speed", 0)

    # Сводка осадков
    precipitation_alert = ""
    if has_rain and has_snow:
        precipitation_alert = "\n⚠️ **Внимание:** ожидаются осадки (дождь со снегом)! Одевайтесь теплее и возьмите зонт ☂️"
    elif has_rain:
        precipitation_alert = "\n🌧 **Внимание:** сегодня в течение дня ожидается дождь! Не забудьте зонт ☂️"
    elif has_snow:
        precipitation_alert = "\n❄️ **Внимание:** ожидается снег! На дорогах возможна гололедица."
    else:
        precipitation_alert = "\n☀️ **Без существенных осадков.** Отличный день для прогулок и встреч!"

    date_prefix = "на завтра" if is_late_evening else "на сегодня"
    updated_time = current_time.strftime("%H:%M")
    card_text = (
        f"🌤 **Погода в Санкт-Петербурге ({date_prefix}, {target_date_str})**\n\n"
        f"{format_slot(slots['утро'], 'Утро (06:00-09:00)', '🌅')}\n\n"
        f"{format_slot(slots['день'], 'День (12:00-15:00)', '☀️')}\n\n"
        f"{format_slot(slots['вечер'], 'Вечер (18:00-21:00)', '🌆')}\n\n"
        f"{format_slot(slots['ночь'], 'Ночь (00:00-03:00)', '🌙')}\n"
        f"{precipitation_alert}\n\n"
        f"📊 **Параметры атмосферы:**\n"
        f"  • Давление: **{pressure_mm} мм рт. ст.**\n"
        f"  • Влажность: **{humidity}%**\n"
        f"  • Ветер: **{wind_now} м/с** (порывы до {max_wind} м/с)\n\n"
        f"_⏱ Актуализировано в {updated_time} (МСК). Прогноз обновляется автоматически._"
    )

    _WEATHER_CACHE["timestamp"] = now_loop
    _WEATHER_CACHE["text"] = card_text
    _WEATHER_CACHE["data"] = data

    return card_text
