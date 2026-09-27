import aiosqlite
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.config import DB_FILE, OBJECTIONS_FILE


class Database:
    def __init__(self, db_path: Path = DB_FILE):
        self.db_path = db_path
        self._objections_cache: Optional[Dict[str, Any]] = None

    def load_objections_data(self) -> Dict[str, Any]:
        """Загрузка базы возражений из JSON-файла."""
        if self._objections_cache is None:
            with open(OBJECTIONS_FILE, "r", encoding="utf-8") as f:
                self._objections_cache = json.load(f)
        return self._objections_cache

    def get_categories(self) -> List[Dict[str, Any]]:
        """Получить список всех категорий."""
        data = self.load_objections_data()
        return data.get("categories", [])

    def get_objection_by_id(self, obj_id: str) -> Optional[Dict[str, Any]]:
        """Найти возражение по ID."""
        data = self.load_objections_data()
        for obj in data.get("objections", []):
            if obj["id"] == obj_id:
                return obj
        return None

    def get_objections_by_category(self, category_id: str) -> List[Dict[str, Any]]:
        """Получить возражения выбранной категории."""
        data = self.load_objections_data()
        return [o for o in data.get("objections", []) if o.get("category_id") == category_id]

    def get_all_objections(self) -> List[Dict[str, Any]]:
        """Получить все возражения."""
        data = self.load_objections_data()
        return data.get("objections", [])

    async def init_db(self):
        """Инициализация таблиц базы данных SQLite."""
        async with aiosqlite.connect(self.db_path) as db:
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

    async def record_review(self, user_id: int, objection_id: str, score: int) -> Dict[str, Any]:
        """
        Запись результата повторения по алгоритму интервального повторения SM-2.
        score:
          1 = Забыл / не вспомнил (красный)
          2 = Вспомнил с трудом (желтый)
          3 = Ответил легко (зеленый)
        """
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
                # Сброс при ошибке: повтор через 15 минут
                repetitions = 0
                interval_days = 0.01  # ~15 минут
                ease_factor = max(1.3, ease_factor - 0.2)
            elif score == 2:
                # С трудом: повтор через 1 день
                repetitions += 1
                interval_days = 1.0
                ease_factor = max(1.3, ease_factor - 0.05)
            elif score == 3:
                # Легко: интервал увеличивается
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

            # Логируем попытку
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
        """
        Умный выбор следующего возражения для изучения:
        1. Сначала карточки, срок повторения которых наступил (due).
        2. Затем еще не изученные карточки.
        3. Затем карточки с наименьшим числом повторений.
        """
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

        # 1. Ищем те, у которых наступил срок повторения (next_review <= now)
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

        # 3. Если все повторено, выбираем карточку с минимальным числом повторений
        sorted_objs = sorted(all_objs, key=lambda o: progress_map.get(o["id"], {}).get("repetitions", 0))
        return sorted_objs[0]

    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Статистика успехов пользователя."""
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


# Глобальный экземпляр базы данных
db = Database()
