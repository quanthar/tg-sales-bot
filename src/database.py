import aiosqlite
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.config import DB_FILE, OBJECTIONS_FILE, DEFAULT_MODEL, MAX_HISTORY_MESSAGES

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path = DB_FILE):
        self.db_path = db_path
        self._objections_cache: Optional[Dict[str, Any]] = None

    # ==========================================
    # Инициализация схемы базы данных
    # ==========================================
    async def init_db(self):
        """Инициализация всех таблиц базы данных SQLite."""
        async with aiosqlite.connect(self.db_path) as db:
            # 1. История диалога
            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON conversation_history(user_id)")

            # 2. Долгосрочная память (факты, заметки, предпочтения)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)")

            # 3. Скиллы (пользовательские и встроенные)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER DEFAULT 0,
                    name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    is_builtin INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, name)
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_skills_user ON skills(user_id)")

            # 4. Настройки пользователя (выбранная модель и т.д.)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    selected_model TEXT DEFAULT 'openrouter/free',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 5. Сохранение обратной совместимости с тренажером возражений
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_progress (
                    user_id INTEGER NOT NULL,
                    objection_id TEXT NOT NULL,
                    repetitions INTEGER DEFAULT 0,
                    interval_days REAL DEFAULT 0,
                    ease_factor REAL DEFAULT 2.5,
                    next_review TEXT,
                    last_score INTEGER DEFAULT 0,
                    last_reviewed TEXT,
                    PRIMARY KEY (user_id, objection_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS review_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    objection_id TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            await db.commit()

        # Инициализация предустановленных скиллов
        await self._init_builtin_skills()
        logger.info("База данных ассистента успешно инициализирована.")

    async def _init_builtin_skills(self):
        """Регистрация встроенных скиллов по умолчанию для менеджера по продажам."""
        builtin_skills = [
            {
                "name": "sales_coach",
                "title": "🎯 Тренер по продажам",
                "description": "Отработка возражений (дорого, подумаю, нет бюджета, работаем с другими) и ведение переговоров.",
                "prompt": (
                    "Ты — первоклассный эксперт по продажам и переговорам. Твоя цель — помогать менеджеру по продажам "
                    "отрабатывать любые возражения клиентов (дорого, подумаю, нет денег, отправьте на почту, уже работаем с другими), "
                    "готовить аргументы и закрывать сделки.\n"
                    "Используй проверенные техники: рефрейминг ценности, встречные квалифицирующие вопросы, разделение цены и результата, СПИН-продажи.\n"
                    "Если пользователь тренирует ответ на возражение — оцени его по 10-балльной шкале, укажи плюсы/минусы "
                    "и дай 2-3 сильных альтернативных ответа в формате: [Название тактики] — «Прямая речь для клиента»."
                ),
            },
            {
                "name": "cold_outreach",
                "title": "📞 Мастер холодных продаж",
                "description": "Сценарии холодных звонков, скрипты первого касания в Telegram/WhatsApp и пробивающие письма.",
                "prompt": (
                    "Ты — мастер холодных продаж и B2B коммуникаций. Твоя задача — создавать пробивающие первые касания "
                    "в Telegram, WhatsApp, email и сценарии звонков, которые вызывают интерес и получают ответы.\n"
                    "Правила: никаких клише ('вас беспокоит', 'выгодное предложение'). Фокусируйся на конкретной боли или выгоде клиента, "
                    "лаконичности (до 3-5 предложений для мессенджеров) и легком целевом действии (CTA без обязательств: созвон на 5 минут, аудит, демо).\n"
                    "Всегда давай готовые короткие варианты сообщений под отправку."
                ),
            },
            {
                "name": "web_researcher",
                "title": "🔍 Бизнес-разведка и фактчекинг",
                "description": "Поиск цен, сайтов конкурентов, анализа компаний и актуальных новостей рынка в реальном времени.",
                "prompt": (
                    "Ты — специалист по бизнес-разведке и анализу данных. Твоя задача — находить актуальные факты, "
                    "исследовать компании потенциальных клиентов, анализировать конкурентов и проверять данные в сети.\n"
                    "Всегда используй веб-поиск (инструмент web_search), когда требуются актуальные рыночные цены, новости или факты о компании. "
                    "Делай емкие структурированные выжимки с цифрами, тезисами и ссылками."
                ),
            },
            {
                "name": "skill_creator",
                "title": "🛠 Архитектор навыков продаж (Skill Creator)",
                "description": "Создание персональных ролей и скиллов под любые ниши, регламенты и скрипты продаж.",
                "prompt": (
                    "Ты — Архитектор навыков и специализаций для Telegram-помощника по продажам и бизнесу.\n"
                    "Когда пользователь просит создать, обучить или добавить новый скилл (например: 'создай скилл для продажи недвижимости', "
                    "'сделай скилл для общения в чате интернет-магазина', 'научись писать коммерческие предложения', 'создай скилл финансового советника'):\n"
                    "1. Выясни специфику: какая ниша, кому продаем (B2B или B2C), средний чек, главные боли клиентов и целевое действие.\n"
                    "2. Сформулируй концентрированный профессиональный системный промпт (Роль, Ключевые техники, Стиль общения под Telegram, "
                    "Запрещенные ошибки, Примеры сильных фраз).\n"
                    "3. ОБЯЗАТЕЛЬНО вызови инструмент `create_skill` со следующими параметрами:\n"
                    "   - name: уникальный латинский идентификатор (например: real_estate_sales, b2b_copywriter, objection_killer)\n"
                    "   - title: красивое название с эмодзи (например: '🏢 Эксперт по недвижимости')\n"
                    "   - description: краткое понятное описание назначения скилла\n"
                    "   - prompt: готовый детализированный системный промпт\n"
                    "4. После успешного создания навыка поздравь пользователя и напомни, что скилл уже активен и его можно переключать через /skills."
                ),
            },
        ]

        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            # Удаляем старый generic code_assistant из базы
            await db.execute("DELETE FROM skills WHERE user_id = 0 AND name = 'code_assistant'")
            for s in builtin_skills:
                await db.execute("""
                    INSERT INTO skills (user_id, name, title, description, prompt, is_active, is_builtin, created_at)
                    VALUES (0, ?, ?, ?, ?, 1, 1, ?)
                    ON CONFLICT(user_id, name) DO UPDATE SET
                        title = excluded.title,
                        description = excluded.description,
                        prompt = excluded.prompt
                """, (s["name"], s["title"], s["description"], s["prompt"], now))
            await db.commit()

    # ==========================================
    # Методы истории диалога (Контекст)
    # ==========================================
    async def add_message(self, user_id: int, role: str, content: str):
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO conversation_history (user_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, role, content, now))
            await db.commit()

    async def get_history(self, user_id: int, limit: int = MAX_HISTORY_MESSAGES) -> List[Dict[str, str]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT role, content FROM (
                    SELECT role, content, id FROM conversation_history
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
            """, (user_id, limit))
            rows = await cursor.fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in rows]

    async def clear_history(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM conversation_history WHERE user_id = ?", (user_id,))
            await db.commit()

    # ==========================================
    # Методы долгосрочной памяти (Memories)
    # ==========================================
    async def add_memory(self, user_id: int, content: str, category: str = "general") -> int:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO memories (user_id, content, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, content.strip(), category, now, now))
            await db.commit()
            return cursor.lastrowid

    async def get_memories(self, user_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, content, category, created_at FROM memories
                WHERE user_id = ?
                ORDER BY id ASC
            """, (user_id,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_memory(self, user_id: int, memory_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                DELETE FROM memories WHERE id = ? AND user_id = ?
            """, (memory_id, user_id))
            await db.commit()
            return cursor.rowcount > 0

    async def clear_memories(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
            await db.commit()
            return cursor.rowcount

    # ==========================================
    # Методы скиллов (Skills)
    # ==========================================
    async def add_skill(
        self,
        user_id: int,
        name: str,
        title: str,
        description: str,
        prompt: str,
        is_builtin: int = 0
    ) -> Dict[str, Any]:
        """Создание или обновление скилла."""
        now = datetime.now(timezone.utc).isoformat()
        clean_name = name.lower().strip().replace(" ", "_")
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO skills (user_id, name, title, description, prompt, is_active, is_builtin, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(user_id, name) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    prompt = excluded.prompt,
                    is_active = 1
            """, (user_id, clean_name, title.strip(), description.strip(), prompt.strip(), is_builtin, now))
            await db.commit()
            return {
                "id": cursor.lastrowid,
                "name": clean_name,
                "title": title,
                "description": description,
                "prompt": prompt,
                "is_active": 1
            }

    async def get_skills(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение всех доступных скиллов (встроенные + созданные пользователем)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, user_id, name, title, description, prompt, is_active, is_builtin
                FROM skills
                WHERE user_id = 0 OR user_id = ?
                ORDER BY is_builtin DESC, id ASC
            """, (user_id,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_skill(self, user_id: int, skill_id: int) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, user_id, name, title, description, prompt, is_active, is_builtin
                FROM skills
                WHERE id = ? AND (user_id = 0 OR user_id = ?)
            """, (skill_id, user_id))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def toggle_skill(self, user_id: int, skill_id: int) -> Optional[bool]:
        """Переключение активности скилла (on/off)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT is_active FROM skills WHERE id = ? AND (user_id = 0 OR user_id = ?)
            """, (skill_id, user_id))
            row = await cursor.fetchone()
            if not row:
                return None
            new_state = 0 if row[0] == 1 else 1
            await db.execute("""
                UPDATE skills SET is_active = ? WHERE id = ?
            """, (new_state, skill_id))
            await db.commit()
            return bool(new_state)

    async def delete_skill(self, user_id: int, skill_id: int) -> bool:
        """Удаление пользовательского скилла (встроенные скиллы удалить нельзя)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                DELETE FROM skills WHERE id = ? AND user_id = ? AND is_builtin = 0
            """, (skill_id, user_id))
            await db.commit()
            return cursor.rowcount > 0

    async def get_active_skills(self, user_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, name, title, description, prompt
                FROM skills
                WHERE (user_id = 0 OR user_id = ?) AND is_active = 1
            """, (user_id,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ==========================================
    # Настройки пользователя (Модель)
    # ==========================================
    async def get_user_model(self, user_id: int) -> str:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT selected_model FROM user_settings WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row and row[0]:
                return row[0]
            return DEFAULT_MODEL

    async def set_user_model(self, user_id: int, model: str):
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_settings (user_id, selected_model, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    selected_model = excluded.selected_model,
                    updated_at = excluded.updated_at
            """, (user_id, model, now, now))
            await db.commit()

    # ==========================================
    # Совместимость с исходной базой возражений
    # ==========================================
    def load_objections_data(self) -> Dict[str, Any]:
        """Загрузка базы возражений из JSON-файла."""
        if self._objections_cache is None:
            if OBJECTIONS_FILE.exists():
                with open(OBJECTIONS_FILE, "r", encoding="utf-8") as f:
                    self._objections_cache = json.load(f)
            else:
                self._objections_cache = {"categories": [], "objections": []}
        return self._objections_cache

    def get_categories(self) -> List[Dict[str, Any]]:
        return self.load_objections_data().get("categories", [])

    def get_objection_by_id(self, obj_id: str) -> Optional[Dict[str, Any]]:
        for obj in self.load_objections_data().get("objections", []):
            if obj["id"] == obj_id:
                return obj
        return None

    def get_objections_by_category(self, category_id: str) -> List[Dict[str, Any]]:
        return [o for o in self.load_objections_data().get("objections", []) if o.get("category_id") == category_id]

    def get_all_objections(self) -> List[Dict[str, Any]]:
        return self.load_objections_data().get("objections", [])

    async def record_review(self, user_id: int, objection_id: str, score: int) -> Dict[str, Any]:
        """Запись результата повторения по алгоритму SM-2."""
        now = datetime.now(timezone.utc)
        now_str = now.isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT repetitions, interval_days, ease_factor FROM user_progress WHERE user_id = ? AND objection_id = ?",
                (user_id, objection_id)
            )
            row = await cursor.fetchone()

            if row:
                repetitions, interval_days, ease_factor = row
            else:
                repetitions, interval_days, ease_factor = 0, 0.0, 2.5

            if score == 1:
                repetitions = 0
                interval_days = 0.01
                ease_factor = max(1.3, ease_factor - 0.2)
            elif score == 2:
                repetitions += 1
                interval_days = 1.0
                ease_factor = max(1.3, ease_factor - 0.05)
            elif score == 3:
                repetitions += 1
                if repetitions == 1:
                    interval_days = 1.5
                elif repetitions == 2:
                    interval_days = 3.5
                else:
                    interval_days = round(interval_days * ease_factor, 1)
                ease_factor = min(3.0, ease_factor + 0.15)

            next_review = now + timedelta(days=interval_days)
            next_review_str = next_review.isoformat()

            await db.execute("""
                INSERT INTO user_progress (user_id, objection_id, repetitions, interval_days, ease_factor, next_review, last_score, last_reviewed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, objection_id) DO UPDATE SET
                    repetitions = excluded.repetitions,
                    interval_days = excluded.interval_days,
                    ease_factor = excluded.ease_factor,
                    next_review = excluded.next_review,
                    last_score = excluded.last_score,
                    last_reviewed = excluded.last_reviewed
            """, (user_id, objection_id, repetitions, interval_days, ease_factor, next_review_str, score, now_str))

            await db.execute(
                "INSERT INTO review_logs (user_id, objection_id, score, created_at) VALUES (?, ?, ?, ?)",
                (user_id, objection_id, score, now_str)
            )
            await db.commit()

            return {
                "repetitions": repetitions,
                "interval_days": interval_days,
                "next_review": next_review
            }

    async def get_next_card(self, user_id: int, category_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        all_objs = self.get_objections_by_category(category_id) if category_id else self.get_all_objections()
        if not all_objs:
            return None

        now_str = datetime.now(timezone.utc).isoformat()
        obj_ids = [o["id"] for o in all_objs]
        placeholders = ",".join("?" for _ in obj_ids)

        async with aiosqlite.connect(self.db_path) as db:
            query = f"""
                SELECT objection_id, repetitions, next_review
                FROM user_progress
                WHERE user_id = ? AND objection_id IN ({placeholders})
            """
            cursor = await db.execute(query, [user_id] + obj_ids)
            progress_rows = await cursor.fetchall()
            progress_map = {row[0]: {"repetitions": row[1], "next_review": row[2]} for row in progress_rows}

        due_objs = []
        unseen_objs = []
        for obj in all_objs:
            oid = obj["id"]
            if oid in progress_map:
                if progress_map[oid]["next_review"] <= now_str:
                    due_objs.append(obj)
            else:
                unseen_objs.append(obj)

        if due_objs:
            return due_objs[0]
        if unseen_objs:
            return unseen_objs[0]

        sorted_objs = sorted(all_objs, key=lambda o: progress_map.get(o["id"], {}).get("repetitions", 0))
        return sorted_objs[0]

    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        all_objs = self.get_all_objections()
        total_objections = len(all_objs)
        now_str = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT repetitions, interval_days, next_review
                FROM user_progress
                WHERE user_id = ?
            """, (user_id,))
            rows = await cursor.fetchall()

            log_cursor = await db.execute("SELECT COUNT(*) FROM review_logs WHERE user_id = ?", (user_id,))
            total_reviews = (await log_cursor.fetchone())[0]

        studied_count = len(rows)
        mastered_count = sum(1 for r in rows if r[0] >= 3 and r[1] >= 3.0)
        in_progress_count = studied_count - mastered_count
        due_count = sum(1 for r in rows if r[2] <= now_str)

        return {
            "total_objections": total_objections,
            "total_answers": total_objections * 5,
            "studied_count": studied_count,
            "mastered_count": mastered_count,
            "in_progress_count": in_progress_count,
            "due_count": due_count,
            "total_reviews": total_reviews
        }


db = Database()
