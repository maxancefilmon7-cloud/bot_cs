import json
import os
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "charms_db.json")


def _load() -> dict:
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _save(data: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_charm(
    weapon: str,
    charm_name: str,
    price_with_charm: float,
    price_without_charm: float | None,
    charm_standalone: float | None,
):
    db = _load()
    db[weapon] = {
        "charm_name": charm_name,
        "price_with_charm": price_with_charm,
        "price_without_charm": price_without_charm,
        "charm_standalone": charm_standalone,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _save(db)


def get_all() -> dict:
    return _load()


def count() -> int:
    return len(_load())
