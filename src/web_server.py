import logging
from aiohttp import web
from src.config import PORT, HOST
from src.database import db

logger = logging.getLogger(__name__)


async def handle_health(request: web.Request) -> web.Response:
    """Эндпоинт проверки здоровья для Render.com и сервисов пингования (cron-job.org)."""
    categories = db.get_categories()
    objections = db.get_all_objections()

    data = {
        "status": "healthy",
        "service": "Sales Objection Telegram Bot",
        "uptime": "active",
        "categories_count": len(categories),
        "objections_count": len(objections),
        "answers_count": len(objections) * 5
    }
    return web.json_response(data)


async def handle_root(request: web.Request) -> web.Response:
    """Корневой эндпоинт."""
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Sales Objection Bot Server</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
            .card { background: #1e293b; padding: 32px 48px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; border: 1px solid #334155; }
            .badge { display: inline-block; background: #10b981; color: white; padding: 6px 14px; border-radius: 9999px; font-weight: bold; font-size: 14px; margin-bottom: 16px; }
            h1 { margin: 0 0 10px 0; font-size: 24px; }
            p { color: #94a3b8; margin: 5px 0; }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="badge">● Active & Online</div>
            <h1>Тренажер возражений в продажах</h1>
            <p>Бот успешно запущен и обрабатывает сообщения в Telegram.</p>
            <p>Эндпоинт для пингования: <code>/health</code></p>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html_content, content_type="text/html")


def create_web_app() -> web.Application:
    """Создание aiohttp приложения."""
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ping", handle_health)
    return app


async def start_web_server():
    """Запуск фонового веб-сервера."""
    app = create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    logger.info(f"Веб-сервер успешно запущен на {HOST}:{PORT}")
    return runner
