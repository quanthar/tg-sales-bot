import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from src.config import BOT_TOKEN, PORT, WEATHER_NOTIFICATION_HOUR, WEATHER_NOTIFICATION_MINUTE
from src.database import db
from src.handlers import router
from src.web_server import start_web_server
from src.weather import fetch_weather_forecast
from src.keyboards import weather_inline_keyboard
from src.ai.prompts import get_current_time_info

# Обеспечиваем корректный вывод UTF-8 в консоль Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


async def daily_weather_scheduler(bot: Bot):
    """Фоновый планировщик ежедневной отправки прогноза погоды в 07:00 (МСК)."""
    logger.info(f"Планировщик погоды запущен. Время рассылки: {WEATHER_NOTIFICATION_HOUR:02d}:{WEATHER_NOTIFICATION_MINUTE:02d} (МСК).")
    last_sent_date = ""

    while True:
        try:
            await asyncio.sleep(25)
            now_msk = get_current_time_info()["now"]
            today_str = now_msk.strftime("%Y-%m-%d")

            if now_msk.hour == WEATHER_NOTIFICATION_HOUR and now_msk.minute == WEATHER_NOTIFICATION_MINUTE:
                if last_sent_date != today_str:
                    logger.info(f"Запуск ежедневной утренней рассылки прогноза погоды на {today_str}...")
                    forecast_text = await fetch_weather_forecast(force_refresh=True)
                    user_ids = await db.get_all_user_ids()
                    logger.info(f"Получателей прогноза погоды: {len(user_ids)}")

                    for uid in user_ids:
                        try:
                            await bot.send_message(
                                chat_id=uid,
                                text=f"🌅 **Доброе утро! Твой ежедневный прогноз погоды:**\n\n{forecast_text}",
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=weather_inline_keyboard()
                            )
                            await asyncio.sleep(0.08)
                        except Exception as e:
                            logger.warning(f"Не удалось отправить утреннюю погоду пользователю {uid}: {e}")

                    last_sent_date = today_str
                    logger.info("Утренняя рассылка погоды успешно завершена.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле планировщика погоды: {e}")
            await asyncio.sleep(30)


async def main():
    logger.info("Инициализация базы данных SQLite...")
    await db.init_db()

    logger.info(f"Запуск веб-сервера для Render на порту {PORT}...")
    web_runner = await start_web_server()

    if not BOT_TOKEN:
        logger.warning(
            "\n" + "=" * 60 + "\n"
            "⚠️ ВНИМАНИЕ: Токен бота BOT_TOKEN не найден в .env!\n"
            "Веб-сервер работает в штатном режиме (/health доступен),\n"
            "однако Telegram-бот не может подключиться без токена.\n"
            "Пожалуйста, добавьте строку в .env:\n"
            "BOT_TOKEN=ваш_токен_от_BotFather\n"
            "=" * 60 + "\n"
        )
        # Оставляем веб-сервер работать в цикле, чтобы процесс не падал
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            await web_runner.cleanup()
        return

    logger.info("Инициализация Telegram-бота (aiogram 3.x)...")
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    weather_task = None
    try:
        # Удаляем вебхуки перед запуском polling
        await bot.delete_webhook(drop_pending_updates=True)
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} успешно подключен к Telegram!")

        # Устанавливаем системное меню команд Telegram (кнопка Menu в левом нижнем углу)
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню и панель управления"),
            BotCommand(command="weather", description="Прогноз погоды в Санкт-Петербурге"),
            BotCommand(command="objections", description="Справочник 10 возражений и 50 ответов"),
            BotCommand(command="memory", description="Долговременная память"),
            BotCommand(command="skills", description="Управление скиллами и ролями"),
            BotCommand(command="model", description="Выбор модели ИИ"),
            BotCommand(command="clear", description="Очистить контекст диалога"),
            BotCommand(command="help", description="Справка по возможностям"),
        ])
        logger.info("Системное меню команд успешно зарегистрировано.")

        # Запускаем фоновый планировщик утренней погоды
        weather_task = asyncio.create_task(daily_weather_scheduler(bot))

        logger.info("Запуск polling сообщений...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}", exc_info=True)
    finally:
        logger.info("Остановка сервисов...")
        if weather_task:
            weather_task.cancel()
        await bot.session.close()
        await web_runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
