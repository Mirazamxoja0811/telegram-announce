import json
import os
import asyncio

DB_FILE = os.path.join(os.path.dirname(__file__), "data.json")
_lock = None

def _get_lock():
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock

def _load_data() -> dict:
    if not os.path.exists(DB_FILE):
        return {"users": {}}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}}

def _save_data(data: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def init_db():
    async with _get_lock():
        if not os.path.exists(DB_FILE):
            _save_data({"users": {}})

async def get_user(user_id: int) -> dict:
    uid_str = str(user_id)
    async with _get_lock():
        data = _load_data()
        users = data.get("users", {})
        if uid_str not in users:
            users[uid_str] = {
                "user_id": user_id,
                "interval_minutes": 10,
                "is_active": 0,
                "message_type": "text",
                "message_text": None,
                "message_file_id": None,
                "message_caption": None,
                "phone_number": None,
                "phone_code_hash": None,
                "session_string": None,
                "selected_groups": []  # List of {"group_id": int, "group_title": str}
            }
            data["users"] = users
            _save_data(data)
        return users[uid_str]

async def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    uid_str = str(user_id)
    async with _get_lock():
        data = _load_data()
        users = data.get("users", {})
        if uid_str in users:
            users[uid_str].update(kwargs)
            data["users"] = users
            _save_data(data)

async def get_selected_groups(user_id: int) -> list:
    user = await get_user(user_id)
    return user.get("selected_groups", [])

async def is_group_selected(user_id: int, group_id: int) -> bool:
    groups = await get_selected_groups(user_id)
    return any(g["group_id"] == group_id for g in groups)

async def toggle_group_selection(user_id: int, group_id: int, group_title: str):
    uid_str = str(user_id)
    async with _get_lock():
        data = _load_data()
        users = data.get("users", {})
        if uid_str in users:
            groups = users[uid_str].get("selected_groups", [])
            existing_ids = [g["group_id"] for g in groups]
            if group_id in existing_ids:
                groups = [g for g in groups if g["group_id"] != group_id]
            else:
                groups.append({"group_id": group_id, "group_title": group_title})
            users[uid_str]["selected_groups"] = groups
            data["users"] = users
            _save_data(data)

async def select_all_groups(user_id: int, groups_list: list):
    uid_str = str(user_id)
    async with _get_lock():
        data = _load_data()
        users = data.get("users", {})
        if uid_str in users:
            users[uid_str]["selected_groups"] = groups_list
            data["users"] = users
            _save_data(data)

async def clear_selected_groups(user_id: int):
    uid_str = str(user_id)
    async with _get_lock():
        data = _load_data()
        users = data.get("users", {})
        if uid_str in users:
            users[uid_str]["selected_groups"] = []
            data["users"] = users
            _save_data(data)

async def remove_selected_group(user_id: int, group_id: int):
    uid_str = str(user_id)
    async with _get_lock():
        data = _load_data()
        users = data.get("users", {})
        if uid_str in users:
            groups = users[uid_str].get("selected_groups", [])
            users[uid_str]["selected_groups"] = [
                group for group in groups if group.get("group_id") != group_id
            ]
            data["users"] = users
            _save_data(data)
