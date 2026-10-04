from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from typing import Optional, List, Dict, Any


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Главная нижняя панель кнопок для быстрого доступа."""
    keyboard = [
        [
            KeyboardButton(text="🧠 Память"),
            KeyboardButton(text="⚡ Скиллы")
        ],
        [
            KeyboardButton(text="🔍 Поиск в сети"),
            KeyboardButton(text="🤖 Модель")
        ],
        [
            KeyboardButton(text="🧹 Очистить контекст"),
            KeyboardButton(text="ℹ️ Помощь")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def assistant_main_inline_keyboard() -> InlineKeyboardMarkup:
    """Главное инлайн-меню ассистента."""
    keyboard = [
        [
            InlineKeyboardButton(text="🧠 Память", callback_data="assistant_memory"),
            InlineKeyboardButton(text="⚡ Скиллы", callback_data="assistant_skills"),
        ],
        [
            InlineKeyboardButton(text="☀️ Погода в СПб", callback_data="weather_spb"),
            InlineKeyboardButton(text="🤖 Выбрать модель", callback_data="assistant_models"),
        ],
        [
            InlineKeyboardButton(text="🎯 Тренажер продаж", callback_data="menu_categories"),
            InlineKeyboardButton(text="🧹 Очистить диалог", callback_data="assistant_clear"),
        ],
        [
            InlineKeyboardButton(text="ℹ️ Помощь и команды", callback_data="assistant_help"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def weather_inline_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-кнопки под прогнозом погоды."""
    keyboard = [
        [
            InlineKeyboardButton(text="🔄 Обновить прогноз", callback_data="weather_refresh"),
            InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_main"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)



# ==========================================
# Клавиатуры управления памятью
# ==========================================
def memory_keyboard(memories: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура со списком воспоминаний и возможностью удаления."""
    keyboard = []
    for m in memories:
        mem_id = m["id"]
        text_preview = m["content"]
        if len(text_preview) > 30:
            text_preview = text_preview[:27] + "..."
        keyboard.append([
            InlineKeyboardButton(
                text=f"🗑 #{mem_id}: {text_preview}",
                callback_data=f"del_mem:{mem_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(text="➕ Как добавить факт?", callback_data="mem_help"),
        InlineKeyboardButton(text="🧹 Удалить всё", callback_data="mem_clear_all")
    ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ==========================================
# Клавиатуры управления скиллами
# ==========================================
def skills_keyboard(skills: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Инлайн-клавиатура скиллов (переключение on/off, удаление)."""
    keyboard = []
    for s in skills:
        sid = s["id"]
        is_active = bool(s.get("is_active", 1))
        icon = "✅" if is_active else "⚪"
        title = s.get("title", s.get("name"))
        keyboard.append([
            InlineKeyboardButton(
                text=f"{icon} {title}",
                callback_data=f"toggle_skill:{sid}"
            ),
            InlineKeyboardButton(
                text="ℹ️",
                callback_data=f"info_skill:{sid}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(text="➕ Создать новый скилл", callback_data="skill_create_help")
    ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def skill_detail_keyboard(skill: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Клавиатура детального просмотра скилла."""
    sid = skill["id"]
    is_active = bool(skill.get("is_active", 1))
    is_builtin = bool(skill.get("is_builtin", 0))

    keyboard = [
        [
            InlineKeyboardButton(
                text="Отключить ⚪" if is_active else "Включить ✅",
                callback_data=f"toggle_skill:{sid}"
            )
        ]
    ]
    if not is_builtin:
        keyboard.append([
            InlineKeyboardButton(text="🗑 Удалить скилл", callback_data=f"delete_skill:{sid}")
        ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 К списку скиллов", callback_data="assistant_skills")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ==========================================
# Клавиатура выбора модели
# ==========================================
def models_keyboard(available_models: List[str], current_model: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора активной модели ИИ (Groq LPU + OpenRouter)."""
    keyboard = []

    model_friendly_names = {
        "openai/gpt-oss-120b": "🧠 GPT OSS 120B (Groq Флагман)",
        "openai/gpt-oss-20b": "⚡ GPT OSS 20B (Groq Турбо)",
        "qwen/qwen3.8-27b": "🔍 Qwen 3.8 27B (Groq Поиск)",
        "openrouter/free": "🌐 Auto Free (OpenRouter)",
    }

    for m in available_models[:9]:
        is_selected = (m == current_model)
        mark = "✅ " if is_selected else ""
        friendly = model_friendly_names.get(m)
        if not friendly:
            clean = m.replace(":free", "")
            if len(clean) > 24:
                clean = clean[:22] + ".."
            friendly = f"🌐 {clean}"

        keyboard.append([
            InlineKeyboardButton(
                text=f"{mark}{friendly}",
                callback_data=f"set_model:{m}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ==========================================
# Клавиатуры для тренажера возражений (Sales Coach)
# ==========================================
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return assistant_main_inline_keyboard()


def categories_keyboard(categories: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    keyboard = []
    for cat in categories:
        cid = cat["id"]
        keyboard.append([
            InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}",
                callback_data=f"cat:{cid}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def category_detail_keyboard(category_id: str, objections: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(
                text="🚀 Начать тренировку категории",
                callback_data=f"train_cat:{category_id}"
            )
        ]
    ]
    for obj in objections:
        title = obj.get("title") or obj.get("text") or obj.get("client_phrase") or f"Возражение #{obj.get('num', '')}"
        keyboard.append([
            InlineKeyboardButton(
                text=f"🎯 {title}",
                callback_data=f"obj_view:{obj['id']}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 К категориям", callback_data="menu_categories")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def objection_practice_keyboard(objection_id: str, show_answer: bool = False) -> InlineKeyboardMarkup:
    keyboard = []
    if not show_answer:
        keyboard.append([
            InlineKeyboardButton(text="💡 Показать разбор и скрипты", callback_data=f"show_ans:{objection_id}")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton(text="🔴 Трудно (1)", callback_data=f"score:{objection_id}:1"),
            InlineKeyboardButton(text="🟡 Нормально (2)", callback_data=f"score:{objection_id}:2"),
            InlineKeyboardButton(text="🟢 Легко (3)", callback_data=f"score:{objection_id}:3")
        ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
