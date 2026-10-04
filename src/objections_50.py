"""
Модуль загрузки и предоставления базы «50 ответов на каждое возражение».
Загружает данные из файла 'Новые ответы на возражения.md' и кэширует в памяти.
"""
from pathlib import Path
from typing import List, Dict, Any, Optional
import re
import logging

logger = logging.getLogger(__name__)

# Путь к файлу с базой 50 ответов
MD_FILE = Path(__file__).resolve().parent.parent / "Новые ответы на возражения.md"

_OBJECTIONS_50_CACHE: Optional[List[Dict[str, Any]]] = None


def _format_clean_title(raw_title: str) -> str:
    """Форматирует название возражения: удаляет номер, очищает регистр для кнопок."""
    clean = re.sub(r'^\d+\.\s*', '', raw_title).strip()
    # Приводим к предложению с заглавной буквы
    if clean.isupper() and len(clean) > 3:
        clean = clean.capitalize()
    return clean


def load_objections_50(force_reload: bool = False) -> List[Dict[str, Any]]:
    """Парсит markdown-файл с 20 возражениями по 50 ответов в каждом."""
    global _OBJECTIONS_50_CACHE
    if _OBJECTIONS_50_CACHE is not None and not force_reload:
        return _OBJECTIONS_50_CACHE

    if not MD_FILE.exists():
        logger.error(f"Файл базы возражений не найден: {MD_FILE}")
        return []

    try:
        with open(MD_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        parts = content.split("-----—")[1:]
        objections = []

        for idx, part in enumerate(parts, 1):
            lines = [l.strip() for l in part.strip().split("\n") if l.strip()]
            if not lines:
                continue

            raw_title = lines[0]
            clean_title = _format_clean_title(raw_title)

            # Собираем ответы (1..50)
            answers = []
            for line in lines[1:]:
                # Удаляем префикс номера ("1. ", "50. ")
                ans_text = re.sub(r'^\d+\.\s*', '', line).strip()
                if ans_text:
                    answers.append(ans_text)

            # Название для кнопки (компактное)
            button_title = clean_title
            if idx == 5 and "не соответствует" in clean_title.lower():
                button_title = f"{clean_title} (часть 2)"

            objections.append({
                "id": idx,
                "title": clean_title,
                "button_title": f"{idx}. {button_title}",
                "answers": answers,
                "answers_count": len(answers)
            })

        _OBJECTIONS_50_CACHE = objections
        logger.info(f"Загружено {len(objections)} возражений из {MD_FILE.name}")
        return _OBJECTIONS_50_CACHE

    except Exception as e:
        logger.error(f"Ошибка при парсинге {MD_FILE}: {e}", exc_info=True)
        return []


def get_all_50_objections() -> List[Dict[str, Any]]:
    """Возвращает список всех возражений."""
    return load_objections_50()


def get_50_objection_by_id(obj_id: int) -> Optional[Dict[str, Any]]:
    """Поиск возражения по числовому id (1..20)."""
    for obj in get_all_50_objections():
        if obj["id"] == obj_id:
            return obj
    return None


def format_50_objection_text(obj: Dict[str, Any]) -> str:
    """Форматирует 50 ответов строго по формату: _возражение_:\\n1. ...\\n2. ..."""
    title = obj.get("title", "").strip()
    answers = obj.get("answers", [])
    ans_lines = []
    for i, ans in enumerate(answers, 1):
        clean_ans = re.sub(r'\[(?![^\]]*\]\(https?://[^\)]+\))', r'\[', ans)
        ans_lines.append(f"{i}. {clean_ans}")
    return f"_{title}_:\n\n" + "\n".join(ans_lines)
