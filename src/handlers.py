import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from src.database import db
from src.keyboards import (
    main_menu_keyboard,
    categories_keyboard,
    category_detail_keyboard,
    card_question_keyboard,
    card_grading_keyboard,
    guide_menu_keyboard,
    back_to_guide_keyboard
)

router = Router()


def format_objection_card(obj: dict, category_name: str = "") -> str:
    """Форматирование карточки с вопросом (до показа ответов)."""
    cat_str = f" [{category_name}]" if category_name else ""
    return (
        f"🎯 <b>Возражение №{obj['num']}: {obj['title']}</b>{cat_str}\n\n"
        f"🗣 <b>Клиент говорит:</b>\n"
        f"<i>{obj['client_phrase']}</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 <b>Active Recall (Активное вспоминание):</b>\n"
        f"Сначала сформулируйте ответ <b>в голове</b> или <b>вслух</b> (либо отправьте сообщением в чат).\n"
        f"Затем нажмите кнопку ниже, чтобы сверить себя с эталонами."
    )


def format_answers_text(obj: dict, single_answer: dict = None) -> str:
    """Форматирование эталонных ответов."""
    header = f"🎯 <b>Возражение №{obj['num']}: {obj['title']}</b>\n"
    header += f"🗣 <i>{obj['client_phrase']}</i>\n\n"

    if single_answer:
        content = (
            f"🎲 <b>Вариант {single_answer['id']} [{single_answer['strategy']}]:</b>\n"
            f"«<b>{single_answer['text']}</b>»\n"
        )
        if single_answer.get("comment"):
            content += f"\n{single_answer['comment']}\n"
    else:
        content = "📋 <b>5 вариантов отработки:</b>\n\n"
        for ans in obj["answers"]:
            content += f"<b>{ans['id']}. {ans['strategy']}:</b>\n«{ans['text']}»\n"
            if ans.get("comment"):
                content += f"   <i>{ans['comment']}</i>\n"
            content += "\n"

    footer = "━━━━━━━━━━━━━━━━━━━\n" \
             "⭐️ <b>Как вы справились? Оцените себя для интервального повторения:</b>"
    return header + content + footer


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message):
    """Приветствие и главное меню."""
    welcome_text = (
        "👋 <b>Приветствую, коллега!</b>\n\n"
        "Этот бот — твой персональный тренажер <b>10 ключевых возражений в продажах</b> "
        "(всего 50 эталонных приемов отработки).\n\n"
        "🔥 <b>Как учить эффективно (без нудной зубрежки):</b>\n"
        "1. <b>Учи по категориям</b> — начни с тех, которые даются сложнее всего.\n"
        "2. <b>Вспоминай сам (Active Recall)</b> — не подглядывай сразу, напрягай память.\n"
        "3. <b>Оценивай честно</b> — алгоритм интервальных повторений сам напомнит "
        "сложные возражения в нужный момент.\n\n"
        "Выбери режим обучения ниже:"
    )
    await message.answer(welcome_text, reply_markup=main_menu_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "menu_main")
async def cb_main_menu(callback: CallbackQuery):
    """Возврат в главное меню."""
    text = (
        "🏠 <b>Главное меню тренажера возражений</b>\n\n"
        "Выберите желаемый режим тренировки:"
    )
    await callback.message.edit_text(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "menu_categories")
async def cb_categories(callback: CallbackQuery):
    """Меню категорий возражений."""
    categories = db.get_categories()
    text = (
        "🎯 <b>Выберите категорию для изучения:</b>\n\n"
        "Все 10 возражений разбиты на 4 понятные группы. "
        "Рекомендуется осваивать их по очереди."
    )
    await callback.message.edit_text(text, reply_markup=categories_keyboard(categories), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category_detail(callback: CallbackQuery):
    """Детали выбранной категории."""
    cat_id = callback.data.split(":")[1]
    categories = db.get_categories()
    selected_cat = next((c for c in categories if c["id"] == cat_id), None)
    if not selected_cat:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    objections = db.get_objections_by_category(cat_id)
    text = (
        f"{selected_cat['emoji']} <b>Категория: {selected_cat['name']}</b>\n\n"
        f"📝 <i>{selected_cat['description']}</i>\n\n"
        f"В этой категории <b>{len(objections)} возражения</b> (и {len(objections)*5} готовых вариантов ответа).\n"
        f"Вы можете запустить тренировку всей категории или выбрать конкретное возражение:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=category_detail_keyboard(cat_id, objections),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("view_obj:"))
async def cb_view_single_obj(callback: CallbackQuery):
    """Просмотр конкретного возражения."""
    parts = callback.data.split(":")
    obj_id = parts[1]
    context_cat = parts[2] if len(parts) > 2 else "all"

    obj = db.get_objection_by_id(obj_id)
    if not obj:
        await callback.answer("Возражение не найдено", show_alert=True)
        return

    text = format_answers_text(obj)
    await callback.message.edit_text(
        text,
        reply_markup=card_grading_keyboard(obj_id, context_cat),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("train_cat:"))
@router.callback_query(F.data == "train_all")
@router.callback_query(F.data == "train_smart")
@router.callback_query(F.data.startswith("next_card:"))
async def cb_train_flow(callback: CallbackQuery):
    """Запуск и показ карточки тренировки."""
    data = callback.data
    user_id = callback.from_user.id

    if data.startswith("train_cat:"):
        context_cat = data.split(":")[1]
    elif data.startswith("next_card:"):
        context_cat = data.split(":")[1]
    elif data == "train_all":
        context_cat = "all"
    elif data == "train_smart":
        context_cat = "smart"
    else:
        context_cat = "all"

    cat_filter = None if context_cat in ("all", "smart") else context_cat
    card = await db.get_next_card(user_id, cat_filter)

    if not card:
        await callback.message.edit_text(
            "🎉 <b>Отличная работа!</b>\nВсе возражения в этом разделе уже отработаны на сегодня.",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # Получаем имя категории для заголовка
    categories = db.get_categories()
    cat_obj = next((c for c in categories if c["id"] == card["category_id"]), None)
    cat_name = f"{cat_obj['emoji']} {cat_obj['name']}" if cat_obj else ""

    text = format_objection_card(card, cat_name)
    await callback.message.edit_text(
        text,
        reply_markup=card_question_keyboard(card["id"], context_cat),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("show_all:"))
async def cb_show_all_answers(callback: CallbackQuery):
    """Показать все 5 вариантов ответа."""
    parts = callback.data.split(":")
    obj_id = parts[1]
    context_cat = parts[2] if len(parts) > 2 else "all"

    obj = db.get_objection_by_id(obj_id)
    if not obj:
        await callback.answer("Ошибка данных", show_alert=True)
        return

    text = format_answers_text(obj)
    await callback.message.edit_text(
        text,
        reply_markup=card_grading_keyboard(obj_id, context_cat),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("show_one:"))
async def cb_show_one_answer(callback: CallbackQuery):
    """Показать 1 случайный эталонный ответ."""
    parts = callback.data.split(":")
    obj_id = parts[1]
    context_cat = parts[2] if len(parts) > 2 else "all"

    obj = db.get_objection_by_id(obj_id)
    if not obj:
        await callback.answer("Ошибка данных", show_alert=True)
        return

    single_ans = random.choice(obj["answers"])
    text = format_answers_text(obj, single_answer=single_ans)
    await callback.message.edit_text(
        text,
        reply_markup=card_grading_keyboard(obj_id, context_cat),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("grade:"))
async def cb_grade_answer(callback: CallbackQuery):
    """Оценка ответа по системе SM-2 и переход к следующему возражению."""
    parts = callback.data.split(":")
    obj_id = parts[1]
    score = int(parts[2])
    context_cat = parts[3] if len(parts) > 3 else "all"
    user_id = callback.from_user.id

    result = await db.record_review(user_id, obj_id, score)

    # Всплывающее уведомление
    if score == 1:
        alert_msg = "🔴 Записано: повторим через 15 минут!"
    elif score == 2:
        alert_msg = "🟡 Записано: запланировано на завтра."
    else:
        days = result["interval_days"]
        alert_msg = f"🟢 Отлично! Следующий повтор через {days:.1f} дн."

    await callback.answer(alert_msg, show_alert=False)

    # Сразу открываем следующую карточку
    cat_filter = None if context_cat in ("all", "smart") else context_cat
    card = await db.get_next_card(user_id, cat_filter)

    if not card:
        await callback.message.edit_text(
            f"{alert_msg}\n\n🎉 <b>Поздравляем!</b> На сегодня все запланированные карточки отработаны.",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML"
        )
        return

    categories = db.get_categories()
    cat_obj = next((c for c in categories if c["id"] == card["category_id"]), None)
    cat_name = f"{cat_obj['emoji']} {cat_obj['name']}" if cat_obj else ""

    text = format_objection_card(card, cat_name)
    await callback.message.edit_text(
        text,
        reply_markup=card_question_keyboard(card["id"], context_cat),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "guide_menu")
async def cb_guide_menu(callback: CallbackQuery):
    """Меню шпаргалки со всеми 10 возражениями."""
    all_objs = db.get_all_objections()
    text = (
        "📖 <b>Шпаргалка: все 10 возражений</b>\n\n"
        "Нажмите на любое возражение, чтобы сразу увидеть все 5 вариантов его отработки:"
    )
    await callback.message.edit_text(text, reply_markup=guide_menu_keyboard(all_objs), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("guide_view:"))
async def cb_guide_view(callback: CallbackQuery):
    """Просмотр шпаргалки по конкретному возражению."""
    obj_id = callback.data.split(":")[1]
    obj = db.get_objection_by_id(obj_id)
    if not obj:
        await callback.answer("Возражение не найдено", show_alert=True)
        return

    text = f"📖 <b>Шпаргалка по возражению №{obj['num']}:</b>\n\n"
    text += f"🗣 <b>Клиент:</b> <i>{obj['client_phrase']}</i>\n\n"
    for ans in obj["answers"]:
        text += f"🔹 <b>{ans['id']}. {ans['strategy']}:</b>\n«{ans['text']}»\n"
        if ans.get("comment"):
            text += f"   <i>{ans['comment']}</i>\n"
        text += "\n"

    await callback.message.edit_text(text, reply_markup=back_to_guide_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "my_stats")
async def cb_my_stats(callback: CallbackQuery):
    """Статистика успехов пользователя."""
    user_id = callback.from_user.id
    stats = await db.get_user_stats(user_id)

    percent = int((stats["mastered_count"] / stats["total_objections"]) * 100) if stats["total_objections"] > 0 else 0

    text = (
        "📊 <b>Ваш прогресс обучения</b>\n\n"
        f"🎯 Всего возражений в базе: <b>{stats['total_objections']}</b> (50 приемов)\n"
        f"📖 Начато изучение: <b>{stats['studied_count']} / {stats['total_objections']}</b>\n"
        f"🏆 Уверенно освоено (3+ повтора): <b>{stats['mastered_count']} / {stats['total_objections']} ({percent}%)</b>\n"
        f"⏳ Требуют повторения прямо сейчас: <b>{stats['due_count']}</b>\n"
        f"🔁 Всего ответов отработано: <b>{stats['total_reviews']}</b>\n\n"
        "💡 <i>Повторяйте по 5–10 минут каждый день перед сменой, чтобы довести ответы до автоматизма!</i>"
    )
    await callback.message.edit_text(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message()
async def text_recall_handler(message: Message):
    """
    Если пользователь пишет свой ответ текстом в чат во время раздумий,
    бот хвалит за Active Recall и предлагает сверить с вариантами.
    """
    reply_text = (
        "👏 <b>Отличная попытка формулировки!</b>\n\n"
        "Именно так тренируется навык быстрых ответов в реальном разговоре. "
        "Теперь используйте кнопки в карточке выше, чтобы сверить свои мысли "
        "с эталонами и отметить результат."
    )
    await message.reply(reply_text, parse_mode="HTML")
