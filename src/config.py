import os
from pathlib import Path
from dotenv import load_dotenv

# Базовая директория проекта
BASE_DIR = Path(__file__).resolve().parent.parent

# Загрузка переменных окружения из .env
load_dotenv(BASE_DIR / ".env")

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# OpenRouter API Key (supports OPENROUTER_API_KEY and openroute_api from .env)
OPENROUTER_API_KEY = (
    os.getenv("OPENROUTER_API_KEY", "") or
    os.getenv("openroute_api", "") or
    os.getenv("OPENROUTE_API", "")
).strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Groq API Configuration (supports GROQ_API_KEY and GROQ_API from .env)
GROQ_API_KEY = (
    os.getenv("GROQ_API_KEY", "") or
    os.getenv("GROQ_API", "") or
    os.getenv("groq_api", "")
).strip()
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# Список топовых сверхбыстрых моделей Groq
GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]

# Список популярных бесплатных моделей на OpenRouter (резерв)
FREE_MODELS = [
    "openrouter/free",
    "qwen/qwen3.8-27b:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
]

# При наличии ключа Groq используем флагман 120B по умолчанию
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-oss-120b" if GROQ_API_KEY else "openrouter/free")

# Порт для веб-сервера (Render передает PORT автоматически)
PORT = int(os.getenv("PORT", "10000"))
HOST = os.getenv("HOST", "0.0.0.0")

# Часовой пояс по умолчанию для актуализации времени и поиска
BOT_TIMEZONE = os.getenv("BOT_TIMEZONE", "Europe/Moscow")

# Пути к файлам данных
DATA_DIR = BASE_DIR / "data"
OBJECTIONS_FILE = DATA_DIR / "objections.json"
DB_FILE = DATA_DIR / "assistant.db"  # Новая база для ассистента, памяти и скиллов
OLD_DB_FILE = DATA_DIR / "user_progress.db"

# Настройки контекста диалога
MAX_HISTORY_MESSAGES = 14

# Создаем директорию данных, если не существует
DATA_DIR.mkdir(parents=True, exist_ok=True)
