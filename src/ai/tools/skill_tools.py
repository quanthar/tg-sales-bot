import logging
from typing import Dict, Any, List
from src.database import db

logger = logging.getLogger(__name__)


async def create_skill(
    user_id: int,
    name: str,
    title: str,
    description: str,
    prompt: str
) -> Dict[str, Any]:
    """
    Создание нового персонального скилла для пользователя прямо из диалога.
    """
    clean_name = name.lower().strip().replace(" ", "_")
    if not clean_name or not title or not prompt:
        return {"status": "error", "message": "Имя скилла, название и системный промпт обязательны."}

    skill = await db.add_skill(
        user_id=user_id,
        name=clean_name,
        title=title.strip(),
        description=description.strip() or title.strip(),
        prompt=prompt.strip(),
        is_builtin=0
    )
    logger.info(f"Создан новый скилл '{clean_name}' для user_id {user_id}")
    return {
        "status": "success",
        "message": f"Скилл '{title}' (@{clean_name}) успешно создан и активирован!",
        "skill": skill
    }


async def list_skills(user_id: int) -> List[Dict[str, Any]]:
    """
    Получение списка доступных скиллов.
    """
    return await db.get_skills(user_id)
