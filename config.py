# config.py — plain-text password, first-run setup
import os, json
from pathlib import Path

CASEORG_CONFIG = Path(os.getenv(
    "CASEORG_CONFIG",
    Path.home() / ".config" / "case-organizer" / "config.json"
))

def _load():
    if CASEORG_CONFIG.is_file():
        try:
            return json.loads(CASEORG_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save(d: dict):
    CASEORG_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CASEORG_CONFIG.write_text(json.dumps(d, indent=2), encoding="utf-8")

_cfg = _load()

# May be None/empty until setup
FS_ROOT = (os.getenv("CASEORG_FS_ROOT") or _cfg.get("fs_root") or None)
ALLOWED_USERS = set(_cfg.get("allowed_users", []))
PASSWORD = _cfg.get("password")  # PLAIN TEXT per your request

SECRET_KEY = os.getenv("SECRET_KEY", "dev-local-secret-key")
ALLOWED_EXTENSIONS = {"pdf","docx","txt","png","jpg","jpeg","json"}

def save_fs_root(path_str: str) -> None:
    from pathlib import Path as _P
    _cfg["fs_root"] = str(_P(path_str).expanduser().resolve())
    _save(_cfg)

def save_users(users: list[str]) -> None:
    _cfg["allowed_users"] = users
    _save(_cfg)

def save_password(pw: str) -> None:
    _cfg["password"] = pw
    _save(_cfg)

def is_storage_configured() -> bool:
    return bool(FS_ROOT)

def is_users_configured() -> bool:
    return bool(ALLOWED_USERS)

def is_password_configured() -> bool:
    return PASSWORD not in (None, "")

def is_fully_configured() -> bool:
    return is_storage_configured() and is_users_configured() and is_password_configured()

