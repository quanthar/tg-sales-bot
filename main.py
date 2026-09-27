import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from src.config import BOT_TOKEN, PORT
from src.database import db
from src.handlers import router
from src.web_server import start_web_server

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

    try:
        # Удаляем вебхуки перед запуском polling
        await bot.delete_webhook(drop_pending_updates=True)
        bot_info = await bot.get_me()
        logger.info(f"✅ Бот @{bot_info.username} успешно подключен к Telegram!")
        logger.info("Запуск polling сообщений...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}", exc_info=True)
    finally:
        logger.info("Остановка сервисов...")
        await bot.session.close()
        await web_runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
