import logging
from typing import Dict, Any, List
from src.database import db

logger = logging.getLogger(__name__)


async def save_memory(user_id: int, fact: str, category: str = "general") -> Dict[str, Any]:
    """
    Сохранение важного факта или предпочтения о пользователе в долговременную память.
    """
    clean_fact = fact.strip()
    if not clean_fact:
        return {"status": "error", "message": "Факт не может быть пустым."}

    # Проверяем, нет ли уже такого же воспоминания
    existing = await db.get_memories(user_id)
    for m in existing:
        if m["content"].lower() == clean_fact.lower():
            return {"status": "already_exists", "message": "Этот факт уже сохранен в памяти.", "id": m["id"]}

    mem_id = await db.add_memory(user_id=user_id, content=clean_fact, category=category)
    logger.info(f"Сохранено воспоминание #{mem_id} для user_id {user_id}: {clean_fact}")
    return {"status": "success", "message": f"Факт успешно сохранен под ID #{mem_id}", "id": mem_id}


async def get_memories(user_id: int) -> List[Dict[str, Any]]:
    """
    Получение всех сохраненных фактов о пользователе.
    """
    return await db.get_memories(user_id)


async def delete_memory(user_id: int, memory_id: int) -> Dict[str, Any]:
    """
    Удаление факта из памяти по его ID.
    """
    success = await db.delete_memory(user_id, memory_id)
    if success:
        logger.info(f"Удалено воспоминание #{memory_id} для user_id {user_id}")
        return {"status": "success", "message": f"Воспоминание #{memory_id} успешно удалено."}
    return {"status": "not_found", "message": f"Воспоминание #{memory_id} не найдено."}
