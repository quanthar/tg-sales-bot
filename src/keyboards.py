from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional, List, Dict, Any


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    keyboard = [
        [
            InlineKeyboardButton(text="🎯 Учить по категориям", callback_data="menu_categories")
        ],
        [
            InlineKeyboardButton(text="⚡ Блиц-тренажер (Все возражения)", callback_data="train_all"),
        ],
        [
            InlineKeyboardButton(text="🧠 Умное повторение (Интервалы)", callback_data="train_smart"),
        ],
        [
            InlineKeyboardButton(text="📖 Шпаргалка: все 10 возражений", callback_data="guide_menu"),
            InlineKeyboardButton(text="📊 Мой прогресс", callback_data="my_stats")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def categories_keyboard(categories: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Меню выбора категории."""
    keyboard = []
    counts = {
        "money": 2,
        "no_interest": 2,
        "delay": 4,
        "decision_competitor": 2
    }
    for cat in categories:
        cid = cat["id"]
        count = counts.get(cid, "")
        count_str = f" ({count})" if count else ""
        keyboard.append([
            InlineKeyboardButton(
                text=f"{cat['emoji']} {cat['name']}{count_str}",
                callback_data=f"cat:{cid}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def category_detail_keyboard(category_id: str, objections: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Меню конкретной категории: запуск тренировки или выбор отдельного возражения."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="🚀 Начать тренировку категории",
                callback_data=f"train_cat:{category_id}"
            )
        ]
    ]
    for obj in objections:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{obj['num']}. {obj['title']}",
                callback_data=f"view_obj:{obj['id']}:{category_id}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 Назад к категориям", callback_data="menu_categories"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="menu_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def card_question_keyboard(obj_id: str, context_category: str = "all") -> InlineKeyboardMarkup:
    """Клавиатура перед показом ответа (этап Active Recall)."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="👁 Показать все 5 вариантов",
                callback_data=f"show_all:{obj_id}:{context_category}"
            )
        ],
        [
            InlineKeyboardButton(
                text="🎲 Случайный вариант ответа",
                callback_data=f"show_one:{obj_id}:{context_category}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⏭ Другое возражение",
                callback_data=f"next_card:{context_category}"
            ),
            InlineKeyboardButton(text="🏠 В меню", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def card_grading_keyboard(obj_id: str, context_category: str = "all") -> InlineKeyboardMarkup:
    """Клавиатура оценки после показа эталонных ответов."""
    keyboard = [
        [
            InlineKeyboardButton(
                text="🔴 Забыл (15 мин)",
                callback_data=f"grade:{obj_id}:1:{context_category}"
            ),
            InlineKeyboardButton(
                text="🟡 С трудом (1 день)",
                callback_data=f"grade:{obj_id}:2:{context_category}"
            ),
            InlineKeyboardButton(
                text="🟢 Легко (3+ дня)",
                callback_data=f"grade:{obj_id}:3:{context_category}"
            )
        ],
        [
            InlineKeyboardButton(
                text="⏭ Следующее возражение",
                callback_data=f"next_card:{context_category}"
            ),
            InlineKeyboardButton(text="🏠 В меню", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def guide_menu_keyboard(objections: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Шпаргалка: список всех возражений для быстрого просмотра."""
    keyboard = []
    # Размещаем по 2 кнопки в ряд
    row = []
    for obj in objections:
        row.append(
            InlineKeyboardButton(
                text=f"{obj['num']}. {obj['title']}",
                callback_data=f"guide_view:{obj['id']}"
            )
        )
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu_main")
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def back_to_guide_keyboard() -> InlineKeyboardMarkup:
    """Возврат в шпаргалку."""
    keyboard = [
        [
            InlineKeyboardButton(text="🔙 К списку шпаргалки", callback_data="guide_menu"),
            InlineKeyboardButton(text="🏠 В главное меню", callback_data="menu_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
