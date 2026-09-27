import os
from pathlib import Path
from dotenv import load_dotenv

# Базовая директория проекта
BASE_DIR = Path(__file__).resolve().parent.parent

# Загрузка переменных окружения из .env
load_dotenv(BASE_DIR / ".env")

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Порт для веб-сервера (Render передает PORT автоматически)
PORT = int(os.getenv("PORT", "10000"))
HOST = os.getenv("HOST", "0.0.0.0")

# Пути к файлам данных
DATA_DIR = BASE_DIR / "data"
OBJECTIONS_FILE = DATA_DIR / "objections.json"
DB_FILE = DATA_DIR / "user_progress.db"

# Создаем директорию данных, если не существует
DATA_DIR.mkdir(parents=True, exist_ok=True)
