# config.py
from __future__ import annotations
import os, json
from pathlib import Path

# Where the package will keep its config (env override if needed)
CONFIG_PATH = Path(os.getenv("CASEORG_CONFIG", "/etc/case-organizer/config.json"))

# Defaults
DEFAULTS = {
    "fs_root": "",          # set during /setup
    "allowed_users": [],    # set during /setup
    "password": None,       # set during /set_password
    "secret_key": "dev-local-secret-key",  # you can rotate this later
    "allowed_extensions": ["pdf","docx","txt","png","jpg","jpeg","json"],
}

def _load() -> dict:
    try:
        if CONFIG_PATH.exists():
            return {**DEFAULTS, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
    except Exception:
        pass
    return DEFAULTS.copy()

def _save(obj: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

# Public helpers your app already calls during setup
def save_fs_root(path: str) -> None:
    cfg = _load()
    cfg["fs_root"] = str(Path(path).expanduser())
    _save(cfg)

def save_users(users: list[str]) -> None:
    cfg = _load()
    cfg["allowed_users"] = users
    _save(cfg)

def save_password(pw: str) -> None:
    cfg = _load()
    cfg["password"] = pw  # plain, per your preference
    _save(cfg)

# “is configured?” checks used by before_request/setup flow
def is_storage_configured() -> bool:
    return bool(_load().get("fs_root"))

def is_users_configured() -> bool:
    return bool(_load().get("allowed_users"))

def is_password_configured() -> bool:
    return _load().get("password") not in (None, "")

# Exported values (so app.py can import constants)
_cfg = _load()
FS_ROOT = Path(_cfg["fs_root"]).expanduser() if _cfg["fs_root"] else Path()
ALLOWED_USERS = _cfg["allowed_users"]
PASSWORD = _cfg["password"]
SECRET_KEY = _cfg["secret_key"]
ALLOWED_EXTENSIONS = set(_cfg["allowed_extensions"])

