import asyncio
import logging
import random
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

from src.database import db
from src.ai.agent import agent
from src.ai.client import ai_client
from src.keyboards import (
    main_reply_keyboard,
    assistant_main_inline_keyboard,
    memory_keyboard,
    skills_keyboard,
    skill_detail_keyboard,
    models_keyboard,
    categories_keyboard,
    category_detail_keyboard,
    objection_practice_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()


def split_text(text: str, max_chunk_size: int = 4000) -> list[str]:
    """Разбивка длинного текста на части для ограничений Telegram (4096 символов)."""
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = []
    current_length = 0

    for line in lines:
        if current_length + len(line) + 1 > max_chunk_size:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_length = len(line) + 1
        else:
            current_chunk.append(line)
            current_length += len(line) + 1

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


async def safe_reply(message: Message, text: str, reply_markup=None):
    """Безопасная отправка сообщений с разбивкой и fallback при ошибках Markdown."""
    chunks = split_text(text)
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        try:
            await message.reply(chunk, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            # Если в ответе некорректный Markdown, отправляем обычным текстом
            await message.reply(chunk, reply_markup=markup, parse_mode=None)


# ==========================================
# Команды бота (/start, /help, /menu, /clear)
# ==========================================
@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message):
    """Приветствие и главное меню."""
    user_name = message.from_user.first_name or "друг"
    welcome_text = (
        f"👋 **Привет, {user_name}! Я твой автономный ИИ-помощник Hermes.**\n\n"
        "⚡ **Что я умею:**\n"
        "• 🧠 **Долговременная память**: запоминаю твои предпочтения, факты, стек и цели.\n"
        "• ⚡ **Динамические скиллы**: ты можешь создавать новые скиллы и роли прямо в чате!\n"
        "• 🔍 **Поиск в интернете**: нахожу свежую информацию через DuckDuckGo без ограничений.\n"
        "• 🤖 **Бесплатные ИИ-модели**: работаю через OpenRouter с авто-ротацией.\n"
        "• 🎯 **Тренер по продажам**: встроенный модуль отработки возражений.\n\n"
        "💬 *Просто напиши мне любой вопрос или задачу в чат, либо воспользуйся кнопками меню ниже:*"
    )
    # Отправляем reply клавиатуру для быстрого доступа
    await message.answer("Загружаю панель управления...", reply_markup=main_reply_keyboard())
    # Отправляем главное инлайн-меню
    await message.answer(welcome_text, reply_markup=assistant_main_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    help_text = (
        "📖 **Справка по командам и возможностям Hermes:**\n\n"
        "💬 **Обычное общение:**\n"
        "Просто пиши любой запрос в чат. Я сам вызову поиск в сети, сохраню важные факты о тебе или активирую нужные навыки.\n\n"
        "🧠 **Управление памятью:**\n"
        "• `/memory` — посмотреть и отредактировать сохраненные факты\n"
        "• `/remember <факт>` — быстро записать факт (например: `/remember Я люблю Python`)\n"
        "• `/forget <id>` — удалить факт по ID\n"
        "• Либо в диалоге: *«Запомни, что мой проект называется HermesBot»*\n\n"
        "⚡ **Скиллы (Навыки и роли):**\n"
        "• `/skills` — список активных скиллов, включение/выключение\n"
        "• Создание из чата: просто напиши:\n"
        "  *«Создай скилл 'Аналитик криптовалют', который кратко анализирует графики и дает выжимку по рискам»*\n\n"
        "🔍 **Поиск информации:**\n"
        "• Любой вопрос с актуальными данными: *«Кто победил на Оскаре в этом году?»*, *«Курс TON к USD»*\n"
        "• Команда `/search <запрос>` для принудительного поиска\n\n"
        "🤖 **Выбор модели:**\n"
        "• `/model` — переключение между бесплатными моделями OpenRouter\n\n"
        "🧹 **Контекст:**\n"
        "• `/clear` — сбросить текущий диалог и начать беседу заново"
    )
    await safe_reply(message, help_text)


@router.message(Command("clear"))
@router.message(F.text == "🧹 Очистить контекст")
async def cmd_clear(message: Message):
    user_id = message.from_user.id
    await db.clear_history(user_id)
    await message.reply("🧹 **Контекст текущего диалога очищен.** Память и скиллы сохранены!", parse_mode=ParseMode.MARKDOWN)


# ==========================================
# Обработчики памяти (/memory, /remember, /forget)
# ==========================================
@router.message(Command("memory"))
@router.message(F.text == "🧠 Память")
async def cmd_memory(message: Message):
    user_id = message.from_user.id
    memories = await db.get_memories(user_id)

    if not memories:
        text = (
            "🧠 **Твоя долговременная память пока пуста.**\n\n"
            "Я автоматически сохраняю важные детали о тебе из наших разговоров "
            "(имя, интересы, проекты, предпочтения).\n\n"
            "Ты также можешь добавить факт вручную:\n"
            "👉 `/remember Меня зовут Алексей, я изучаю ИИ`"
        )
    else:
        text = f"🧠 **Сохраненные факты и знания о тебе ({len(memories)}):**\n\n"
        for m in memories:
            text += f"• `#{m['id']}`: {m['content']}\n"
        text += "\n*Нажми на кнопку ниже, чтобы удалить ненужный факт:*"

    await message.answer(text, reply_markup=memory_keyboard(memories), parse_mode=ParseMode.MARKDOWN)


@router.message(Command("remember"))
async def cmd_remember(message: Message):
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply("⚠️ Укажи факт для сохранения, например:\n`/remember Мой любимый язык — Python`", parse_mode=ParseMode.MARKDOWN)
        return

    fact = parts[1].strip()
    mem_id = await db.add_memory(user_id, fact)
    await message.reply(f"✅ **Факт сохранен в память!** (ID: `#{mem_id}`)\n_{fact}_", parse_mode=ParseMode.MARKDOWN)


@router.message(Command("forget"))
async def cmd_forget(message: Message):
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("⚠️ Укажи числовой ID воспоминания, например:\n`/forget 1`", parse_mode=ParseMode.MARKDOWN)
        return

    mem_id = int(parts[1].strip())
    success = await db.delete_memory(user_id, mem_id)
    if success:
        await message.reply(f"🗑 **Воспоминание #{mem_id} успешно удалено.**", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(f"❌ Воспоминание #{mem_id} не найдено в твоем списке.", parse_mode=ParseMode.MARKDOWN)


# ==========================================
# Обработчики скиллов (/skills, /newskill)
# ==========================================
@router.message(Command("skills"))
@router.message(F.text == "⚡ Скиллы")
async def cmd_skills(message: Message):
    user_id = message.from_user.id
    skills = await db.get_skills(user_id)
    text = (
        "⚡ **Управление скиллами и ролями:**\n\n"
        "Скиллы определяют специализацию, стиль ответов и правила ассистента.\n"
        "Нажимай на скилл, чтобы **включить (✅)** или **выключить (⚪)** его.\n"
        "Нажми ℹ️ для просмотра инструкций скилла.\n\n"
        "💡 *Ты можешь создать новый скилл прямо из разговора, просто сказав:*\n"
        "_«Создай скилл маркетолога для написания постов в Telegram»_"
    )
    await message.answer(text, reply_markup=skills_keyboard(skills), parse_mode=ParseMode.MARKDOWN)


@router.message(Command("newskill"))
async def cmd_newskill(message: Message):
    text = (
        "⚡ **Как создать новый скилл:**\n\n"
        "Ты можешь создать скилл прямо в обычном сообщении ассистенту!\n\n"
        "**Примеры фраз:**\n"
        "• _«Создай скилл 'Репетитор испанского', который объясняет грамматику для новичков с примерами»_\n"
        "• _«Создай скилл 'Code Reviewer', который ищет ошибки и уязвимости в Python-коде»_\n"
        "• _«Создай скилл 'Копирайтер', который пишет цепляющие посты по формуле AIDA»_\n\n"
        "ИИ автоматически сгенерирует название, системный промпт и зарегистрирует скилл в твоем списке!"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


# ==========================================
# Обработчик выбора модели (/model)
# ==========================================
@router.message(Command("model"))
@router.message(F.text == "🤖 Модель")
async def cmd_model(message: Message):
    user_id = message.from_user.id
    current_model = await db.get_user_model(user_id)
    free_models = await ai_client.fetch_available_free_models()

    text = (
        f"🤖 **Текущая модель:** `{current_model}`\n\n"
        "Выбери бесплатную модель OpenRouter из списка ниже:\n"
        "• `openrouter/free` — автоматический выбор лучшей свободной модели\n"
        "• При перегрузке или лимитах ассистент автоматически переключается на резервную модель."
    )
    await message.answer(text, reply_markup=models_keyboard(free_models, current_model), parse_mode=ParseMode.MARKDOWN)


# ==========================================
# Обработчик поиска (/search)
# ==========================================
@router.message(Command("search"))
@router.message(F.text == "🔍 Поиск в сети")
async def cmd_search(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip() or message.text == "🔍 Поиск в сети":
        await message.reply(
            "🔍 **Поиск информации в интернете:**\n\n"
            "Напиши запрос, например:\n"
            "`/search последние новости искусственного интеллекта`\n\n"
            "Либо просто спроси меня в чате: *«Найди в сети курс валют на сегодня»*",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    query = parts[1].strip()
    await run_agent_message(message, f"Найди в интернете и подробно расскажи: {query}")


# ==========================================
# Callbacks для интерфейса ассистента
# ==========================================
@router.callback_query(F.data == "menu_main")
async def cb_main_menu(callback: CallbackQuery):
    welcome_text = (
        "🏠 **Главное меню Hermes Assistant**\n\n"
        "Выберите раздел для настройки:"
    )
    await callback.message.edit_text(welcome_text, reply_markup=assistant_main_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data == "assistant_memory")
async def cb_assistant_memory(callback: CallbackQuery):
    user_id = callback.from_user.id
    memories = await db.get_memories(user_id)
    if not memories:
        text = "🧠 **Твоя долговременная память пуста.**\n\nДобавь факт: `/remember <факт>` или просто скажи в диалоге."
    else:
        text = f"🧠 **Сохраненные факты о тебе ({len(memories)}):**\n\n"
        for m in memories:
            text += f"• `#{m['id']}`: {m['content']}\n"
    await callback.message.edit_text(text, reply_markup=memory_keyboard(memories), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("del_mem:"))
async def cb_del_mem(callback: CallbackQuery):
    user_id = callback.from_user.id
    mem_id = int(callback.data.split(":")[1])
    await db.delete_memory(user_id, mem_id)
    await callback.answer(f"Воспоминание #{mem_id} удалено!", show_alert=False)

    memories = await db.get_memories(user_id)
    text = f"🧠 **Сохраненные факты о тебе ({len(memories)}):**\n\n"
    for m in memories:
        text += f"• `#{m['id']}`: {m['content']}\n"
    if not memories:
        text = "🧠 Память очищена."

    await callback.message.edit_text(text, reply_markup=memory_keyboard(memories), parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data == "mem_clear_all")
async def cb_clear_all_mem(callback: CallbackQuery):
    user_id = callback.from_user.id
    count = await db.clear_memories(user_id)
    await callback.answer(f"Удалено {count} воспоминаний", show_alert=True)
    await callback.message.edit_text("🧠 **Все воспоминания удалены.**", reply_markup=memory_keyboard([]), parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data == "mem_help")
async def cb_mem_help(callback: CallbackQuery):
    text = (
        "🧠 **Как работает долговременная память:**\n\n"
        "1. **Автоматически:** когда ты рассказываешь о своих проектах, имени, профессии, интересах, ИИ сам вызывает инструмент сохранения.\n"
        "2. **Вручную:** команда `/remember <текст>`.\n"
        "3. **Удаление:** нажми на кнопку с ID воспоминания, чтобы стереть его."
    )
    await callback.answer()
    await callback.message.answer(text, parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data == "assistant_skills")
async def cb_assistant_skills(callback: CallbackQuery):
    user_id = callback.from_user.id
    skills = await db.get_skills(user_id)
    text = (
        "⚡ **Твои скиллы (навыки и роли):**\n\n"
        "Нажимай на кнопку скилла для включения (✅) или отключения (⚪):\n"
    )
    await callback.message.edit_text(text, reply_markup=skills_keyboard(skills), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_skill:"))
async def cb_toggle_skill(callback: CallbackQuery):
    user_id = callback.from_user.id
    skill_id = int(callback.data.split(":")[1])
    new_state = await db.toggle_skill(user_id, skill_id)
    state_str = "включен ✅" if new_state else "отключен ⚪"
    await callback.answer(f"Скилл {state_str}")

    skills = await db.get_skills(user_id)
    await callback.message.edit_reply_markup(reply_markup=skills_keyboard(skills))


@router.callback_query(F.data.startswith("info_skill:"))
async def cb_info_skill(callback: CallbackQuery):
    user_id = callback.from_user.id
    skill_id = int(callback.data.split(":")[1])
    skill = await db.get_skill(user_id, skill_id)
    if not skill:
        await callback.answer("Скилл не найден", show_alert=True)
        return

    is_builtin_str = "Встроенный" if skill.get("is_builtin") else "Пользовательский"
    status_str = "Активен ✅" if skill.get("is_active") else "Отключен ⚪"
    text = (
        f"⚡ **Скилл: {skill['title']}**\n"
        f"Тип: {is_builtin_str} | Статус: {status_str}\n\n"
        f"📝 **Описание:** {skill['description']}\n\n"
        f"🎯 **Системные инструкции:**\n`{skill['prompt']}`"
    )
    await callback.message.edit_text(text, reply_markup=skill_detail_keyboard(skill), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("delete_skill:"))
async def cb_delete_skill(callback: CallbackQuery):
    user_id = callback.from_user.id
    skill_id = int(callback.data.split(":")[1])
    deleted = await db.delete_skill(user_id, skill_id)
    if deleted:
        await callback.answer("Скилл успешно удален!", show_alert=True)
    else:
        await callback.answer("Невозможно удалить встроенный скилл.", show_alert=True)

    skills = await db.get_skills(user_id)
    await callback.message.edit_text("⚡ **Список скиллов обновлен:**", reply_markup=skills_keyboard(skills), parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data == "skill_create_help")
async def cb_skill_create_help(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "💡 **Как создать скилл:**\n"
        "Просто напиши в чат запрос вроде:\n"
        "«_Создай скилл 'Консультант по стартапам' для оценки бизнес-идей и юнит-экономики_»",
        parse_mode=ParseMode.MARKDOWN
    )


@router.callback_query(F.data == "assistant_models")
async def cb_assistant_models(callback: CallbackQuery):
    user_id = callback.from_user.id
    current_model = await db.get_user_model(user_id)
    free_models = await ai_client.fetch_available_free_models()
    text = f"🤖 **Выбор модели ИИ (OpenRouter Free):**\n\nТекущая: `{current_model}`"
    await callback.message.edit_text(text, reply_markup=models_keyboard(free_models, current_model), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("set_model:"))
async def cb_set_model(callback: CallbackQuery):
    user_id = callback.from_user.id
    model_name = callback.data.split("set_model:")[1]
    await db.set_user_model(user_id, model_name)
    await callback.answer(f"Модель изменена на {model_name}")

    free_models = await ai_client.fetch_available_free_models()
    text = f"🤖 **Модель успешно изменена на:** `{model_name}`"
    await callback.message.edit_text(text, reply_markup=models_keyboard(free_models, model_name), parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data == "assistant_clear")
async def cb_assistant_clear(callback: CallbackQuery):
    user_id = callback.from_user.id
    await db.clear_history(user_id)
    await callback.answer("Диалог очищен!", show_alert=True)
    await callback.message.edit_text("🧹 **Контекст текущего диалога очищен.** Чем могу помочь?", reply_markup=assistant_main_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)


# ==========================================
# Обработчик тренировки возражений (Sales Coach)
# ==========================================
@router.callback_query(F.data == "menu_categories")
async def cb_categories(callback: CallbackQuery):
    categories = db.get_categories()
    text = (
        "🎯 **Тренажер 10 возражений в продажах:**\n\n"
        "Выберите категорию для тренировки:"
    )
    await callback.message.edit_text(text, reply_markup=categories_keyboard(categories), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category_detail(callback: CallbackQuery):
    cat_id = callback.data.split(":")[1]
    categories = db.get_categories()
    selected_cat = next((c for c in categories if c["id"] == cat_id), None)
    if not selected_cat:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    objections = db.get_objections_by_category(cat_id)
    text = (
        f"{selected_cat['emoji']} **Категория: {selected_cat['name']}**\n\n"
        f"📝 _{selected_cat['description']}_\n\n"
        f"Возражений в категории: {len(objections)}."
    )
    await callback.message.edit_text(text, reply_markup=category_detail_keyboard(cat_id, objections), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("obj_view:"))
async def cb_obj_view(callback: CallbackQuery):
    obj_id = callback.data.split(":")[1]
    obj = db.get_objection_by_id(obj_id)
    if not obj:
        await callback.answer("Возражение не найдено", show_alert=True)
        return

    text = (
        f"🎯 **Возражение №{obj['num']}: {obj['title']}**\n\n"
        f"🗣 *Клиент говорит:* «{obj['client_phrase']}»\n\n"
        "Нажмите кнопку ниже, чтобы увидеть разбор и скрипты ответа:"
    )
    await callback.message.edit_text(text, reply_markup=objection_practice_keyboard(obj_id, show_answer=False), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("show_ans:"))
async def cb_show_ans(callback: CallbackQuery):
    obj_id = callback.data.split(":")[1]
    obj = db.get_objection_by_id(obj_id)
    if not obj:
        await callback.answer("Возражение не найдено", show_alert=True)
        return

    text = f"🎯 **Разбор возражения: {obj['title']}**\n\n"
    for ans in obj["answers"]:
        text += f"🔹 **{ans['id']}. {ans['strategy']}**\n«{ans['text']}»\n\n"

    text += "⭐️ Оцените, насколько легко вам дается этот ответ:"
    await callback.message.edit_text(text, reply_markup=objection_practice_keyboard(obj_id, show_answer=True), parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


@router.callback_query(F.data.startswith("score:"))
async def cb_score_objection(callback: CallbackQuery):
    parts = callback.data.split(":")
    obj_id = parts[1]
    score = int(parts[2])
    user_id = callback.from_user.id
    await db.record_review(user_id, obj_id, score)

    msg = "🔴 Повторим скоро!" if score == 1 else ("🟡 Записано на завтра" if score == 2 else "🟢 Отлично освоено!")
    await callback.answer(msg)
    await cb_categories(callback)


# ==========================================
# Главный обработчик диалога с агентом Hermes
# ==========================================
async def run_agent_message(message: Message, prompt_text: str):
    user_id = message.from_user.id

    # Индикатор набора текста
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Сообщение о статусе (обновляется по ходу размышлений агента)
    status_msg: Optional[Message] = None

    async def update_status(text: str):
        nonlocal status_msg
        try:
            await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
            if status_msg is None:
                status_msg = await message.answer(f"_{text}_", parse_mode=ParseMode.MARKDOWN)
            else:
                await status_msg.edit_text(f"_{text}_", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

    try:
        response = await agent.run(user_id, prompt_text, status_callback=update_status)

        # Удаляем временное статусное сообщение, если было создано
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

        await safe_reply(message, response)

    except Exception as e:
        logger.error(f"Ошибка при работе агента для user {user_id}: {e}", exc_info=True)
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass
        await message.reply(f"⚠️ Извини, произошла непредвиденная ошибка: {str(e)}")


@router.message(F.text)
async def default_chat_handler(message: Message):
    """
    Обработка любого входящего текстового сообщения через автономный агент Hermes.
    """
    text = message.text.strip()
    if not text:
        return

    await run_agent_message(message, text)
