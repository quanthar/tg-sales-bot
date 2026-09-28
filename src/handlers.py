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
from src.ai.prompts import get_current_time_info
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


import re
from typing import Dict, Any, List, Optional


def format_telegram_text(text: str) -> str:
    """
    Преобразует сырой вывод LLM в читабельный Telegram-формат:
    1. Автоматически превращает уродливые Markdown-таблицы (| col | col |) в красивые структурированные карточки (🔹 ...).
    2. Извлекает код из ячеек таблиц и оборачивает в валидные блоки кода (```lang).
    3. Заменяет теги <br> на нормальные переносы строк с аккуратными отступами.
    4. Преобразует Markdown-заголовки (###, ##, #) в жирный шрифт с эмодзи.
    5. Заменяет длинные разделители (---) на аккуратные разделители.
    6. Сохраняет блоки кода (```) в исходном виде без искажений.
    """
    if not text:
        return ""

    lines = text.split("\n")
    output_lines = []
    i = 0
    in_code_block = False

    while i < len(lines):
        line = lines[i]

        # Отслеживаем блоки кода (не ломаем их внутреннее содержимое)
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            output_lines.append(line)
            i += 1
            continue

        if in_code_block:
            output_lines.append(line)
            i += 1
            continue

        # Проверяем, является ли строка заголовком Markdown-таблицы (| ... |)
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?[\s\-:|]+\|?\s*$", lines[i + 1]):
            raw_headers = [h.strip() for h in line.strip().strip("|").split("|")]
            headers = [re.sub(r"<br\s*/?>", " ", h, flags=re.IGNORECASE).strip() for h in raw_headers]
            i += 2  # Пропускаем строку заголовка и разделитель

            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if row and any(row):
                    card_title = row[0] if len(row) > 0 else ""
                    card_title = re.sub(r"<br\s*/?>", " ", card_title, flags=re.IGNORECASE).strip()

                    output_lines.append(f"🔹 **{card_title}**")

                    for h_idx in range(1, len(row)):
                        h_name = headers[h_idx] if h_idx < len(headers) else ""
                        val = row[h_idx]
                        val = re.sub(r"<br\s*/?>", "\n", val, flags=re.IGNORECASE).strip()

                        # Проверяем, не засунут ли сюда код
                        code_match = re.match(
                            r"^(yaml|python|bash|json|sh|dockerfile|html|css|js|ts)\n(.*)",
                            val,
                            flags=re.DOTALL | re.IGNORECASE,
                        )
                        if code_match:
                            lang = code_match.group(1).lower()
                            code_body = code_match.group(2).strip()
                            if h_name:
                                output_lines.append(f"  • **{h_name}**:")
                            output_lines.append(f"```{lang}\n{code_body}\n```")
                        else:
                            if "\n" in val:
                                indented = val.replace("\n", "\n    ")
                                if h_name:
                                    output_lines.append(f"  • **{h_name}**:\n    {indented}")
                                else:
                                    output_lines.append(f"    {indented}")
                            else:
                                if h_name:
                                    output_lines.append(f"  • **{h_name}**: {val}")
                                else:
                                    output_lines.append(f"  • {val}")
                    output_lines.append("")
                i += 1
            continue

        # Вне кода преобразуем заголовки ###, ##, # в эмодзи-заголовки
        h3_match = re.match(r"^###\s+(.+)$", line)
        h2_match = re.match(r"^##\s+(.+)$", line)
        h1_match = re.match(r"^#\s+(.+)$", line)
        if h3_match:
            output_lines.append(f"📌 **{h3_match.group(1).strip()}**")
        elif h2_match:
            output_lines.append(f"📁 **{h2_match.group(1).strip()}**")
        elif h1_match:
            output_lines.append(f"🏷 **{h1_match.group(1).strip()}**")
        else:
            # Заменяем <br> вне кода
            cleaned_line = re.sub(r"<br\s*/?>", "\n", line, flags=re.IGNORECASE)
            output_lines.append(cleaned_line)
        i += 1

    res = "\n".join(output_lines)
    # Преобразуем разделители ---
    res = re.sub(r"^\s*[-*_]{3,}\s*$", r"───────────────", res, flags=re.MULTILINE)
    res = re.sub(r"\n{3,}", "\n\n", res)
    return res.strip()


def smart_split_text(text: str, max_chunk_size: int = 3900) -> list[str]:
    """
    Интеллектуальная разбивка длинного текста на части для Telegram (лимит 4096 символов).
    Гарантирует:
    1. Длина каждого куска <= max_chunk_size.
    2. Разрезы происходят по границам абзацев, строк, предложений или слов.
    3. Блоки кода (```) корректно закрываются в конце текущего поста и открываются в начале следующего.
    """
    if not text:
        return []
    if len(text) <= max_chunk_size:
        return [text]

    # 1. Разбиваем на параграфы
    paragraphs = text.split("\n\n")
    raw_chunks = []
    current_chunk = []
    current_len = 0

    for para in paragraphs:
        p_len = len(para) + 2
        if current_len + p_len <= max_chunk_size:
            current_chunk.append(para)
            current_len += p_len
        else:
            if current_chunk:
                raw_chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_len = 0

            # Если сам параграф длиннее лимита, разбиваем его по строкам
            if len(para) > max_chunk_size:
                lines = para.split("\n")
                line_chunk = []
                line_len = 0
                for line in lines:
                    l_len = len(line) + 1
                    if line_len + l_len <= max_chunk_size:
                        line_chunk.append(line)
                        line_len += l_len
                    else:
                        if line_chunk:
                            raw_chunks.append("\n".join(line_chunk))
                            line_chunk = []
                            line_len = 0

                        # Если отдельная строка превышает лимит, делим по предложениям
                        if len(line) > max_chunk_size:
                            sentences = re.split(r"(?<=[.!?])\s+", line)
                            sent_chunk = []
                            sent_len = 0
                            for sent in sentences:
                                s_len = len(sent) + 1
                                if sent_len + s_len <= max_chunk_size:
                                    sent_chunk.append(sent)
                                    sent_len += s_len
                                else:
                                    if sent_chunk:
                                        raw_chunks.append(" ".join(sent_chunk))
                                        sent_chunk = []
                                        sent_len = 0
                                    if len(sent) > max_chunk_size:
                                        words = sent.split(" ")
                                        w_chunk = []
                                        w_len = 0
                                        for w in words:
                                            wl = len(w) + 1
                                            if w_len + wl <= max_chunk_size:
                                                w_chunk.append(w)
                                                w_len += wl
                                            else:
                                                if w_chunk:
                                                    raw_chunks.append(" ".join(w_chunk))
                                                    w_chunk = []
                                                    w_len = 0
                                                if len(w) > max_chunk_size:
                                                    for i in range(0, len(w), max_chunk_size):
                                                        raw_chunks.append(w[i : i + max_chunk_size])
                                                else:
                                                    w_chunk.append(w)
                                                    w_len += wl
                                        if w_chunk:
                                            raw_chunks.append(" ".join(w_chunk))
                                    else:
                                        sent_chunk.append(sent)
                                        sent_len += s_len
                            if sent_chunk:
                                raw_chunks.append(" ".join(sent_chunk))
                        else:
                            line_chunk.append(line)
                            line_len += l_len
                if line_chunk:
                    raw_chunks.append("\n".join(line_chunk))
            else:
                current_chunk.append(para)
                current_len += p_len

    if current_chunk:
        raw_chunks.append("\n\n".join(current_chunk))

    # 2. Балансировка блоков кода (```) между чанками
    balanced_chunks = []
    in_code_block = False
    code_fence_lang = ""

    for chunk in raw_chunks:
        prefix = ""
        suffix = ""
        if in_code_block:
            prefix = f"```{code_fence_lang}\n"

        fence_matches = re.findall(r"```([a-zA-Z0-9_\-]*)", chunk)
        if len(fence_matches) % 2 == 1:
            if in_code_block:
                in_code_block = False
                code_fence_lang = ""
            else:
                in_code_block = True
                code_fence_lang = fence_matches[-1]
                suffix = "\n```"

        chunk_content = prefix + chunk + suffix
        balanced_chunks.append(chunk_content)

    return [c for c in balanced_chunks if c.strip()]


async def safe_reply(message: Message, text: str, reply_markup=None):
    """Безопасная отправка длинных сообщений с автоформатированием, разбивкой на посты и fallback при ошибках Markdown."""
    formatted_text = format_telegram_text(text)
    chunks = smart_split_text(formatted_text)
    if not chunks:
        return

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == total - 1 else None

        content = chunk
        if total > 1:
            if i == 0:
                content = content + "\n\n_— продолжение в следующем сообщении ↓ —_"
            else:
                content = f"_— часть {i+1} из {total}: —_\n\n" + content

        try:
            await message.reply(content, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"Ошибка парсинга Markdown при отправке части #{i+1}: {e}")
            try:
                # Если в ответе некорректный Markdown, отправляем обычным текстом
                await message.reply(content, reply_markup=markup, parse_mode=None)
            except Exception as e2:
                logger.error(f"Не удалось отправить часть сообщения #{i+1}: {e2}")

        if i < total - 1:
            await asyncio.sleep(0.08)


def extract_message_context(message: Message) -> str:
    """
    Извлечение полного контекста сообщения:
    - текст сообщения или подпись к медиа (caption)
    - ответ на предыдущее сообщение (свайп / Reply)
    - пересланное сообщение (forward_origin или forward_from)
    - цитата (quote)
    """
    content = message.text or message.caption or ""
    extra_context = []
    is_reply = False

    # 1. Проверяем ответ на сообщение (Reply свайпом)
    if message.reply_to_message:
        is_reply = True
        replied = message.reply_to_message
        sender_title = "Бота" if (replied.from_user and replied.from_user.is_bot) else (replied.from_user.full_name if replied.from_user else "Собеседник")
        replied_text = replied.text or replied.caption or ""
        if replied_text:
            trimmed_reply = replied_text[:1200] + ("..." if len(replied_text) > 1200 else "")
            extra_context.append(
                f"[ОТВЕТ СВАЙПОМ НА СООБЩЕНИЕ ОТ {sender_title}]:\n«««\n{trimmed_reply}\n»»»"
            )

    # 2. Проверяем цитату (Telegram Bot API 7.0 quote)
    if hasattr(message, "quote") and message.quote and getattr(message.quote, "text", None):
        extra_context.append(f"[ВЫБРАННАЯ ЦИТАТА ИЗ СООБЩЕНИЯ]:\n«{message.quote.text}»")

    # 3. Проверяем пересылку (Forward)
    forward_source = None
    if hasattr(message, "forward_origin") and message.forward_origin:
        origin = message.forward_origin
        origin_type = getattr(origin, "type", None)
        if origin_type == "user" and hasattr(origin, "sender_user"):
            forward_source = f"Пользователь {origin.sender_user.full_name}"
            if origin.sender_user.username:
                forward_source += f" (@{origin.sender_user.username})"
        elif origin_type == "hidden_user" and hasattr(origin, "sender_user_name"):
            forward_source = f"Пользователь {origin.sender_user_name}"
        elif origin_type == "chat" and hasattr(origin, "sender_chat"):
            forward_source = f"Чат/Канал «{origin.sender_chat.title}»"
        elif origin_type == "channel" and hasattr(origin, "chat"):
            forward_source = f"Канал «{origin.chat.title}»"
    elif message.forward_from:
        forward_source = f"Пользователь {message.forward_from.full_name}"
    elif message.forward_from_chat:
        forward_source = f"Канал «{message.forward_from_chat.title}»"
    elif message.forward_sender_name:
        forward_source = f"Пользователь {message.forward_sender_name}"

    if forward_source:
        if not is_reply:
            return (
                f"[ПЕРЕСЛАННОЕ СООБЩЕНИЕ (Источник: {forward_source})]:\n"
                f"«««\n{content}\n»»»\n\n"
                f"(Пользователь переслал это сообщение для анализа. Проанализируй его содержание и дай полезный, структурированный ответ или комментарий)."
            )
        else:
            extra_context.append(f"[ИСТОЧНИК ПЕРЕСЛАННОГО СООБЩЕНИЯ]: {forward_source}")

    if extra_context:
        header = "\n\n".join(extra_context)
        if content:
            return f"{header}\n\n[СООБЩЕНИЕ / ВОПРОС ПОЛЬЗОВАТЕЛЯ]:\n{content}"
        else:
            return f"{header}\n\n(Пользователь сослался на это сообщение свайпом без текста. Проанализируй контекст и помоги)."

    return content


class UserMessageBuffer:
    def __init__(self):
        self.parts: List[str] = []
        self.last_message: Optional[Message] = None
        self.timer_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()


USER_BUFFERS: Dict[int, UserMessageBuffer] = {}
DEBOUNCE_DELAY = 1.2  # Задержка в 1.2 секунды для объединения кусков длинного текста


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
        "  *«Создай скилл B2B-продажника в оптовой торговле»* или *«Создай скилл для написания продающих офферов»*\n\n"
        "🔍 **Поиск информации:**\n"
        "• Любой вопрос с актуальными данными: *«Новости рынка недвижимости»*, *«Курс валют ЦБ»*\n"
        "• Команда `/search <запрос>` для принудительного поиска\n\n"
        "🤖 **Выбор модели:**\n"
        "• `/model` — переключение моделей ИИ (сверхбыстрый Groq LPU до 1000/день + OpenRouter)\n\n"
        "🧹 **Контекст:**\n"
        "• `/clear` — сбросить текущий диалог и начать беседу заново"
    )
    await safe_reply(message, help_text)


@router.message(Command("clear"))
@router.message(F.text == "🧹 Очистить контекст")
async def cmd_clear(message: Message):
    user_id = message.from_user.id
    await db.clear_history(user_id)
    agent.clear_user_cache(user_id)
    if user_id in USER_BUFFERS:
        USER_BUFFERS[user_id].parts.clear()
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
        "⚡ **Как создать персональный скилл:**\n\n"
        "Ты можешь создать скилл прямо в обычном диалоге с ассистентом!\n\n"
        "**Примеры запросов:**\n"
        "• _«Создай скилл B2B-менеджера по продажам в сфере логистики»_\n"
        "• _«Создай скилл эксперта по отработке возражения 'Дорого, конкуренты предлагают дешевле'»_\n"
        "• _«Создай скилл копирайтера продающих коммерческих предложений и писем»_\n"
        "• _«Создай скилл менеджера по работе с ключевыми клиентами (VIP-клиенты)»_\n\n"
        "Архитектор скиллов сформирует промпт, сохранит его и сразу активирует в твоем меню `/skills`!"
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
    available_models = await ai_client.fetch_available_free_models()

    text = (
        f"🤖 **Текущая активная модель:** `{current_model}`\n\n"
        "⚡ **Модели Groq LPU (сверхбыстрые, до 1000 запросов/день):**\n"
        "• `🧠 GPT OSS 120B` — флагман: сложный анализ, скрипты, глубокие переговоры\n"
        "• `⚡ GPT OSS 20B` — мгновенные ответы и быстрый чат\n"
        "• `🔍 Qwen 3.8 27B` — исследование тем, веб-поиск и анализ\n\n"
        "🌐 **Модели OpenRouter Free:**\n"
        "• Доступны в качестве автоматического резерва при перегрузках.\n\n"
        "Выбери модель кнопкой ниже:"
    )
    await message.answer(text, reply_markup=models_keyboard(available_models, current_model), parse_mode=ParseMode.MARKDOWN)


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
    time_info = get_current_time_info()
    prompt_text = (
        f"[Поиск информации в реальном времени. Текущая дата: {time_info['human_full']}]: "
        f"Найди в интернете актуальную информацию на {time_info['human_date']} и подробно расскажи: {query}"
    )
    await run_agent_message(message, prompt_text)


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
    agent.clear_user_cache(user_id)
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
    agent.clear_user_cache(user_id)
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
        agent.clear_user_cache(user_id)
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
    models = await ai_client.fetch_available_free_models()
    text = f"🤖 **Выбор модели ИИ (Groq LPU + OpenRouter):**\n\nТекущая активная: `{current_model}`"
    await callback.message.edit_text(text, reply_markup=models_keyboard(models, current_model), parse_mode=ParseMode.MARKDOWN)
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
    agent.clear_user_cache(user_id)
    if user_id in USER_BUFFERS:
        USER_BUFFERS[user_id].parts.clear()
    await callback.answer("Диалог очищен!", show_alert=True)
    await callback.message.edit_text("🧹 **Контекст текущего диалога очищен.** Чем могу помочь?", reply_markup=assistant_main_inline_keyboard(), parse_mode=ParseMode.MARKDOWN)


# ==========================================
# Обработчик тренировки возражений (Sales Coach)
# ==========================================
@router.callback_query(F.data == "menu_categories")
async def cb_categories(callback: CallbackQuery):
    try:
        categories = db.get_categories()
        text = (
            "🎯 **Тренажер 10 возражений в продажах:**\n\n"
            "Выберите категорию для тренировки:"
        )
        await callback.message.edit_text(text, reply_markup=categories_keyboard(categories), parse_mode=ParseMode.MARKDOWN)
    finally:
        await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category_detail(callback: CallbackQuery):
    try:
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
            f"Возражений в категории: {len(objections)}.\n"
            "Выберите конкретное возражение или нажмите кнопку запуска тренировки всей категории:"
        )
        await callback.message.edit_text(text, reply_markup=category_detail_keyboard(cat_id, objections), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Ошибка в cb_category_detail: {e}", exc_info=True)
        await callback.message.answer("⚠️ Не удалось загрузить категорию.")
    finally:
        await callback.answer()


@router.callback_query(F.data.startswith("train_cat:"))
async def cb_train_category(callback: CallbackQuery):
    try:
        cat_id = callback.data.split(":")[1]
        user_id = callback.from_user.id
        card = await db.get_next_card(user_id, cat_id)
        if not card:
            await callback.answer("Все возражения в этой категории пройдены!", show_alert=True)
            return

        text = (
            f"🎯 **Возражение №{card['num']}: {card['title']}**\n\n"
            f"🗣 *Клиент говорит:* «{card['client_phrase']}»\n\n"
            "Сформулируйте ответ вслух или напишите в чат, а затем нажмите кнопку проверки:"
        )
        await callback.message.edit_text(text, reply_markup=objection_practice_keyboard(card["id"], show_answer=False), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Ошибка в cb_train_category: {e}", exc_info=True)
    finally:
        await callback.answer()


@router.callback_query(F.data.startswith("obj_view:"))
async def cb_obj_view(callback: CallbackQuery):
    try:
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
    except Exception as e:
        logger.error(f"Ошибка в cb_obj_view: {e}", exc_info=True)
    finally:
        await callback.answer()


@router.callback_query(F.data.startswith("show_ans:"))
async def cb_show_ans(callback: CallbackQuery):
    try:
        obj_id = callback.data.split(":")[1]
        obj = db.get_objection_by_id(obj_id)
        if not obj:
            await callback.answer("Возражение не найдено", show_alert=True)
            return

        text = f"🎯 **Разбор возражения: {obj['title']}**\n\n"
        for ans in obj["answers"]:
            text += f"🔹 **{ans['id']}. {ans['strategy']}**\n«{ans['text']}»\n"
            if ans.get("comment"):
                text += f"   _{ans['comment']}_\n"
            text += "\n"

        text += "⭐️ Оцените, насколько легко вам дается этот ответ:"
        await callback.message.edit_text(text, reply_markup=objection_practice_keyboard(obj_id, show_answer=True), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Ошибка в cb_show_ans: {e}", exc_info=True)
    finally:
        await callback.answer()


@router.callback_query(F.data.startswith("score:"))
async def cb_score_objection(callback: CallbackQuery):
    try:
        parts = callback.data.split(":")
        obj_id = parts[1]
        score = int(parts[2])
        user_id = callback.from_user.id
        await db.record_review(user_id, obj_id, score)

        msg = "🔴 Повторим скоро!" if score == 1 else ("🟡 Записано на завтра" if score == 2 else "🟢 Отлично освоено!")
        await callback.answer(msg)
        await cb_categories(callback)
    except Exception as e:
        logger.error(f"Ошибка в cb_score_objection: {e}", exc_info=True)
        await callback.answer()


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


async def schedule_user_message(message: Message, extracted_text: str):
    """
    Буферизация входящих сообщений (Debouncing).
    Если пользователь отправляет длинный текст, разбитый Telegram на несколько сообщений,
    или быстро пересылает несколько сообщений подряд, они склеиваются в один запрос.
    """
    user_id = message.from_user.id
    if user_id not in USER_BUFFERS:
        USER_BUFFERS[user_id] = UserMessageBuffer()

    buf = USER_BUFFERS[user_id]
    buf.parts.append(extracted_text)
    buf.last_message = message

    # Сбрасываем таймер при поступлении очередного сообщения в пакете
    if buf.timer_task and not buf.timer_task.done():
        buf.timer_task.cancel()

    async def process_batch():
        try:
            await asyncio.sleep(DEBOUNCE_DELAY)
            async with buf.lock:
                if not buf.parts:
                    return
                combined_text = "\n\n".join(buf.parts)
                target_msg = buf.last_message
                buf.parts.clear()
                buf.last_message = None

                if target_msg:
                    await run_agent_message(target_msg, combined_text)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ошибка при обработке пакета сообщений user_id {user_id}: {e}", exc_info=True)

    buf.timer_task = asyncio.create_task(process_batch())


@router.message(F.text | F.caption | F.forward_origin | F.forward_from | F.forward_from_chat | F.reply_to_message)
async def default_chat_handler(message: Message):
    """
    Обработка входящих текстовых сообщений, подписей к медиа, ответов (свайпом) и пересылок.
    """
    extracted = extract_message_context(message)
    if not extracted.strip():
        return

    await schedule_user_message(message, extracted.strip())
