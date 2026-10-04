from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from typing import Optional, List, Dict, Any


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Главная нижняя панель кнопок для быстрого доступа в любой момент."""
    keyboard = [
        [
            KeyboardButton(text="☀️ Погода в СПб"),
            KeyboardButton(text="🧠 Память"),
            KeyboardButton(text="⚡ Скиллы"),
        ],
        [
            KeyboardButton(text="🤖 Модель"),
            KeyboardButton(text="🎯 Возражения"),
            KeyboardButton(text="🧹 Очистить"),
        ],
        [
            KeyboardButton(text="🔍 Поиск в сети"),
            KeyboardButton(text="🏠 Меню"),
            KeyboardButton(text="ℹ️ Помощь"),
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Напиши вопрос или выбери действие..."
    )


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
            InlineKeyboardButton(text="🎯 Возражения", callback_data="view_objections"),
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
# Клавиатура для вкладки возражений
# ==========================================
def objections_inline_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-кнопки под списком возражений."""
    keyboard = [
        [
            InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_main"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

