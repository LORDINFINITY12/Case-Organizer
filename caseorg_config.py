from pathlib import Path
import os, json

# Where the JSON config is stored (can be overridden by env)
CASEORG_CONFIG = Path(
    os.environ.get(
        "CASEORG_CONFIG",
        os.path.join(
            os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")),
            "case-organizer",
            "config.json",
        ),
    )
)

def _load():
    try:
        with open(CASEORG_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save(obj):
    CASEORG_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(CASEORG_CONFIG, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def save_fs_root(path_str):
    data = _load()
    data["FS_ROOT"] = path_str
    _save(data)

def save_users(users_list):
    data = _load()
    data["ALLOWED_USERS"] = users_list
    _save(data)

def save_password(pw):
    data = _load()
    data["PASSWORD"] = pw
    _save(data)

def is_storage_configured():
    return bool(_load().get("FS_ROOT"))

def is_users_configured():
    return bool(_load().get("ALLOWED_USERS"))

def is_password_configured():
    return _load().get("PASSWORD") not in (None, "")

# Expose live values for app.py
_cfg = _load()
FS_ROOT = _cfg.get("FS_ROOT")
ALLOWED_USERS = _cfg.get("ALLOWED_USERS", [])
PASSWORD = _cfg.get("PASSWORD")
SECRET_KEY = os.environ.get("CASEORG_SECRET_KEY", "dev-local-secret-key")

# Extensions allowed at runtime (can keep hardcoded)
ALLOWED_EXTENSIONS = {"pdf","docx","txt","png","jpg","jpeg","json"}


