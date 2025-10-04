from __future__ import annotations

import os
import re
import sqlite3
import shutil
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
import json
from typing import Dict, Any, Iterable, Optional

from flask import (
    Flask, request, jsonify, session, redirect, url_for,
    render_template, render_template_string, flash, send_file, g
)
from werkzeug.utils import secure_filename

# ---- App config (pulled from caseorg_config.py) ------------------------
try:
    import caseorg_config as config  # renamed to avoid clashing with Debian's 'config' module
except Exception as e:
    raise RuntimeError("caseorg_config.py missing or invalid") from e


FS_ROOT = Path(config.FS_ROOT).resolve() if getattr(config, "FS_ROOT", None) else None
ALLOWED_USERS = set(getattr(config, "ALLOWED_USERS", []))
PASSWORD = getattr(config, "PASSWORD", None)  # <-- plain-text password from config
SECRET_KEY = getattr(config, "SECRET_KEY", "dev-local-secret-key")
ALLOWED_EXTENSIONS = set(getattr(config, "ALLOWED_EXTENSIONS", []))


CASE_LAW_ROOT_NAME = "Case Law"
CASE_LAW_DB_NAME = "case_law_index.db"
CASE_LAW_PRIMARY_TYPES = ("Criminal", "Civil", "Commercial")
CASE_LAW_CASE_TYPES = {
    "Criminal": [
        "498A (Cruelty/Dowry)", "Murder", "Rape", "Sexual Harassment", "Hurt",
        "138 NI Act", "Fraud", "Human Trafficking", "NDPS", "PMLA", "POCSO", "Constitutional", "Others"
    ],
    "Civil": [
        "Property", "Rent Control", "Inheritance/Succession", "Contract",
        "Marital Divorce", "Marital Maintenance", "Marital Guardianship", "Constitutional", "Others"
    ],
    "Commercial": [
        "Trademark", "Copyright", "Patent", "Banking", "Others"
    ],
}


# ---- Flask setup --------------------------------------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY

print("Running app.py from:", os.path.abspath(__file__))
print("FS_ROOT:", FS_ROOT)

# ---- Utilities ----------------------------------------------------------
def ensure_root() -> None:
    """Create the storage root if configured."""
    if FS_ROOT:
        FS_ROOT.mkdir(parents=True, exist_ok=True)


def _case_law_root() -> Path:
    if not FS_ROOT:
        raise RuntimeError("Storage root is not configured yet")
    root = FS_ROOT / CASE_LAW_ROOT_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _case_law_db_file() -> Path:
    ensure_root()
    root = FS_ROOT
    if not root:
        raise RuntimeError("Storage root is not configured yet")
    return root / CASE_LAW_DB_NAME


def _ensure_case_law_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS case_law (
            id INTEGER PRIMARY KEY,
            petitioner TEXT NOT NULL,
            respondent TEXT NOT NULL,
            citation TEXT NOT NULL,
            decision_year INTEGER NOT NULL,
            decision_month TEXT,
            primary_type TEXT NOT NULL,
            subtype TEXT NOT NULL,
            folder_rel TEXT NOT NULL,
            file_name TEXT NOT NULL,
            note_path_rel TEXT NOT NULL,
            note_text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(petitioner, respondent, citation, primary_type, subtype, decision_year)
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS case_law_fts USING fts5(
            content,
            petitioner,
            respondent,
            citation,
            note,
            case_id UNINDEXED
        )
        """
    )


def get_case_law_db() -> sqlite3.Connection:
    if 'case_law_db' not in g:
        path = _case_law_db_file()
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        _ensure_case_law_schema(conn)
        g.case_law_db = conn
    return g.case_law_db


@app.teardown_appcontext
def close_case_law_db(_: Optional[BaseException]) -> None:
    conn = g.pop('case_law_db', None)
    if conn is not None:
        conn.close()


def refresh_case_law_index(
    conn: sqlite3.Connection,
    case_id: int,
    judgement_text: str,
    petitioner: str,
    respondent: str,
    citation: str,
    note_text: str,
) -> None:
    conn.execute("DELETE FROM case_law_fts WHERE rowid = ?", (case_id,))
    conn.execute(
        """
        INSERT INTO case_law_fts(rowid, content, petitioner, respondent, citation, note, case_id)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            judgement_text or "",
            petitioner,
            respondent,
            citation,
            note_text or "",
            case_id,
        ),
    )


_NEAR_RE = re.compile(r'("[^"]+"|\S+)\s+NEAR/(\d+)\s+("[^"]+"|\S+)', re.IGNORECASE)
_BOOLEAN_OPERATORS = {
    "and": "AND",
    "or": "OR",
    "not": "NOT",
    "near": "NEAR",
}


def normalize_boolean_query(raw: str) -> str:
    query = normalize_ws(raw)
    if not query:
        return ""

    def _near_sub(match: re.Match) -> str:
        left, distance, right = match.groups()
        return f"NEAR({left} {right}, {distance})"

    query = _NEAR_RE.sub(_near_sub, query)
    for lower, upper in _BOOLEAN_OPERATORS.items():
        query = re.sub(rf"\b{lower}\b", upper, query, flags=re.IGNORECASE)
    return query

@app.before_request
def _require_setup():
    # endpoints allowed without setup/login
    allowed_endpoints = {"setup", "set_password", "login", "static", "ping", "__routes"}

    storage_ok = config.is_storage_configured()
    users_ok   = config.is_users_configured()
    pass_ok    = config.is_password_configured()

    # Need storage+users first
    if not storage_ok or not users_ok:
        if request.endpoint not in allowed_endpoints:
            return redirect(url_for("setup"))
        return

    # Then require password
    if not pass_ok:
        if request.endpoint not in allowed_endpoints:
            return redirect(url_for("set_password"))
        return

    # Finally, require login for everything else
    if "user" not in session and request.endpoint not in allowed_endpoints:
        flash("Please log in first.", "error")
        return redirect(url_for("login"))


@app.route("/setup", methods=["GET", "POST"])
def setup():
    global FS_ROOT, ALLOWED_USERS
    if request.method == "POST":
        chosen = (request.form.get("fs_root") or "").strip()
        users_blob = (request.form.get("users") or "").strip()

        errs = []
        if not chosen:
            errs.append("Please provide a folder path.")
        user_list = [u.strip() for u in users_blob.splitlines() if u.strip()]
        if not user_list:
            errs.append("Enter at least one allowed user (one per line).")

        if not errs:
            try:
                p = Path(chosen).expanduser().resolve()
                p.mkdir(parents=True, exist_ok=True)
                config.save_fs_root(str(p))
                config.save_users(user_list)
                FS_ROOT = p
                ALLOWED_USERS = set(user_list)
                flash(f"Storage set to: {p}", "success")
                flash("Users saved. Next: set a password.", "info")
                return redirect(url_for("set_password"))
            except Exception as e:
                errs.append(f"Failed to save: {e}")

        for m in errs:
            flash(m, "error")

    return render_template_string("""
      <!doctype html>
      <title>Case Organizer – Setup</title>
      <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
      <div class="login-body">
        <div class="login-card">
          <h2>Initial Setup</h2>
          {% include '_flash.html' %}
          <form method="post" class="login-form">
            <label for="fs_root">Folder for fs-files</label>
            <input id="fs_root" name="fs_root" type="text" placeholder="/mnt/data/case-files" required>

            <label for="users">Allowed Users (one per line)</label>
            <textarea id="users" name="users" rows="4" placeholder="e.g.&#10;Jyoti Aggarwal&#10;Sanjivani Aggarwal" required></textarea>

            <button class="btn-primary" type="submit">Save & Continue</button>
          </form>
          <p class="login-foot">Settings saved to {{cfg}}</p>
        </div>
      </div>
    """, cfg=str(getattr(config, "CASEORG_CONFIG", "/etc/case-organizer/config.json")))

@app.route("/set_password", methods=["GET", "POST"])
def set_password():
    global PASSWORD
    if config.is_password_configured():
        return redirect(url_for("login"))

    if request.method == "POST":
        pw  = request.form.get("password") or ""
        pw2 = request.form.get("password2") or ""
        if not pw:
            flash("Enter a password.", "error")
        elif pw != pw2:
            flash("Passwords do not match.", "error")
        else:
            config.save_password(pw)
            PASSWORD = pw
            flash("Password set. You can now log in.", "success")
            return redirect(url_for("login"))

    return render_template_string("""
      <!doctype html>
      <title>Set Password</title>
      <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
      <div class="login-body">
        <div class="login-card">
          <h2>Set Password</h2>
          {% include '_flash.html' %}
          <form method="post" class="login-form">
            <label for="password">Shared Password</label>
            <input id="password" name="password" type="password" required>
            <label for="password2">Confirm Password</label>
            <input id="password2" name="password2" type="password" required>
            <button class="btn-primary" type="submit">Save Password</button>
          </form>
        </div>
      </div>
    """)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def month_dir_name(dt: datetime) -> str:
    # e.g., "Jan", "Feb" ...
    return dt.strftime("%b")

def ddmmyyyy(dt: datetime) -> str:
    return dt.strftime("%d%m%Y")

def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


_ILLEGAL_FS_CHARS = re.compile(r"[\\/:*?\"<>|]")


def sanitize_case_law_component(text: str, replacement: str = " ") -> str:
    cleaned = normalize_ws(text)
    cleaned = _ILLEGAL_FS_CHARS.sub(replacement, cleaned)
    cleaned = normalize_ws(cleaned)
    return cleaned


def build_case_law_display_name(petitioner: str, respondent: str, citation: str) -> str:
    return f"{petitioner} vs {respondent} [{citation}]"


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def normalize_primary_type(value: str) -> Optional[str]:
    candidate = normalize_ws(value)
    for option in CASE_LAW_PRIMARY_TYPES:
        if candidate.lower() == option.lower():
            return option
    return None


def normalize_case_type(primary: str, value: str) -> Optional[str]:
    pool = CASE_LAW_CASE_TYPES.get(primary)
    if not pool:
        return None
    candidate = normalize_ws(value)
    for option in pool:
        if candidate.lower() == option.lower():
            return option
    return None


def case_law_error(message: str, status: int = 400):
    return jsonify({"ok": False, "msg": message}), status


def short_excerpt(text: str, limit: int = 200) -> str:
    if not text:
        return ""
    compact = normalize_ws(text)
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


def extract_note_summary(content: str) -> str:
    raw = content or ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for key in ("Note", "note", "Summary", "summary", "Additional Notes", "additional_notes"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return normalize_ws(value)
    except json.JSONDecodeError:
        pass
    return normalize_ws(raw)


def fetch_case_law_record(conn: sqlite3.Connection, case_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM case_law WHERE id = ?", (case_id,)).fetchone()


def case_law_file_path(row: sqlite3.Row) -> Path:
    base = (FS_ROOT / row["folder_rel"]).resolve()
    full = (base / row["file_name"]).resolve()
    root = FS_ROOT.resolve()
    if not str(full).startswith(str(root)):
        raise RuntimeError("Resolved file path escapes storage root")
    return full


def case_law_note_path(row: sqlite3.Row) -> Path:
    note = (FS_ROOT / row["note_path_rel"]).resolve()
    root = FS_ROOT.resolve()
    if not str(note).startswith(str(root)):
        raise RuntimeError("Resolved note path escapes storage root")
    return note


def serialize_case_law(row: sqlite3.Row, text_preview: str = "") -> Dict[str, Any]:
    return {
        "id": row["id"],
        "petitioner": row["petitioner"],
        "respondent": row["respondent"],
        "citation": row["citation"],
        "decision_year": row["decision_year"],
        "decision_month": row["decision_month"],
        "primary_type": row["primary_type"],
        "case_type": row["case_type"],
        "folder": row["folder_rel"],
        "file_name": row["file_name"],
        "note_path": row["note_path_rel"],
        "note_preview": short_excerpt(row["note_text"]),
        "text_preview": short_excerpt(text_preview or row["note_text"]),
        "download_url": url_for("case_law_download", case_id=row["id"]),
        "note_url": url_for("case_law_note", case_id=row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

def case_dir(year: int, month_str: str, case_name: str) -> Path:
    return FS_ROOT / f"{year}" / month_str / case_name

def domain_code(domain: str) -> str:
    d = (domain or "").strip().lower()
    if d == "criminal": return "CRL"
    if d == "civil":    return "CIVIL"
    if d == "commercial": return "COMM"
    return d.upper() if d else ""

def type_code(main_type: str) -> str:
    m = (main_type or "").strip().lower()
    # Extend this mapping as needed
    if m == "transfer petition":      return "TP"
    if m == "criminal revision":      return "CRL.REV."
    if m == "writ petition":          return "WP"
    if m == "bail application":       return "BAIL"
    if m == "orders" or m == "order": return "ORD"
    if m == "criminal miscellaneous": return "CRL.MISC."
    return (main_type or "").upper()

def build_filename(dt: datetime, main_type: str, domain: str, case_name: str, ext: str) -> str:
    # (DDMMYYYY) TYPE DOMAIN Petitioner v. Respondent.ext
    prefix = f"({ddmmyyyy(dt)}) {type_code(main_type)} {domain_code(domain)} {case_name}"
    return f"{prefix}.{ext}"

def build_case_name_from_parties(petitioner: str, respondent: str) -> str:
    pn = normalize_ws(petitioner)
    rn = normalize_ws(respondent)
    return f"{pn} v. {rn}" if pn and rn else ""


def extract_text_for_index(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pdfminer.high_level import extract_text  # type: ignore

            return extract_text(str(file_path))
        if suffix == ".txt":
            return file_path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".docx":
            from docx import Document  # type: ignore

            doc = Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception as exc:
        print(f"[case-law] Failed to extract text from {file_path}: {exc}")
    return ""


def make_note_json(payload: Dict[str, Any]) -> str:
    """
    Produce a human-readable JSON-like text with blank lines between sections.
    Valid JSON with extra blank lines (allowed) for easy reading in editors.
    """
    from collections import OrderedDict
    from json import dumps

    od = OrderedDict()
    # Parties
    od["Petitioner Name"] = payload.get("Petitioner Name", "")
    od["Petitioner Address"] = payload.get("Petitioner Address", "")
    od["Petitioner Contact"] = payload.get("Petitioner Contact", "")
    od["__BLANK1__"] = ""
    od["Respondent Name"] = payload.get("Respondent Name", "")
    od["Respondent Address"] = payload.get("Respondent Address", "")
    od["Respondent Contact"] = payload.get("Respondent Contact", "")
    od["__BLANK2__"] = ""
    od["Our Party"] = payload.get("Our Party", "")
    od["__BLANK3__"] = ""
    # Classification
    od["Case Category"] = payload.get("Case Category", "")
    od["Case Subcategory"] = payload.get("Case Subcategory", "")
    od["Case Type"] = payload.get("Case Type", "")
    od["__BLANK4__"] = ""
    # Courts
    od["Court of Origin"] = {
        "State":   payload.get("Origin State", ""),
        "District":payload.get("Origin District", ""),
        "Court/Forum": payload.get("Origin Court/Forum", ""),
    }
    od["__BLANK5__"] = ""
    od["Current Court/Forum"] = {
        "State":   payload.get("Current State", ""),
        "District":payload.get("Current District", ""),
        "Court/Forum": payload.get("Current Court/Forum", ""),
    }
    od["__BLANK6__"] = ""
    od["Additional Notes"] = payload.get("Additional Notes", "")

    s = dumps(od, indent=2, ensure_ascii=False)
    # Replace spacer keys with blank lines
    s = re.sub(r'\n\s+"__BLANK[0-9]+__":\s*"",\n', "\n\n", s)
    return s

# ---- Diagnostics --------------------------------------------------------
@app.get("/ping")
def ping():
    return "pong"

@app.get("/__routes")
def __routes():
    lines = [
        f"{r.rule}  [{','.join(sorted(m for m in r.methods if m not in {'HEAD','OPTIONS'}))}]"
        for r in app.url_map.iter_rules()
    ]
    return "<pre>" + "\n".join(sorted(lines)) + "</pre>"

# ---- Browse APIs for Manage Case ---------------------------------------
@app.get("/api/years")
def api_years():
    years = []
    if FS_ROOT.exists():
        for p in FS_ROOT.iterdir():
            if p.is_dir() and re.fullmatch(r"\d{4}", p.name):
                years.append(p.name)
    years.sort()  # ascending "2024", "2025"
    return jsonify({"years": years})

@app.get("/api/months")
def api_months():
    year = (request.args.get("year") or "").strip()
    months = []
    base = FS_ROOT / year
    if year and base.exists() and base.is_dir():
        for m in base.iterdir():
            if m.is_dir():
                months.append(m.name)
    # order by calendar month if using Jan..Dec names
    order = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    months.sort(key=lambda x: order.index(x) if x in order else x)
    return jsonify({"months": months})

@app.get("/api/cases")
def api_cases():
    year  = (request.args.get("year") or "").strip()
    month = (request.args.get("month") or "").strip()
    cases = []
    base = FS_ROOT / year / month
    if base.exists() and base.is_dir():
        for d in base.iterdir():
            if d.is_dir():
                cases.append(d.name)
    cases.sort(key=lambda s: s.lower())  # alphabetical by case name
    return jsonify({"cases": cases})

# ---- Auth & Home --------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = normalize_ws(request.form.get("username"))
        pwd  = request.form.get("password") or ""
        if user in ALLOWED_USERS and PASSWORD is not None and pwd == PASSWORD:
            session["user"] = user
            flash("Welcome, " + user, "success")
            return redirect(url_for("home"))
        flash("Invalid credentials", "error")
    try:
        return render_template("login.html")
    except Exception:
        # Minimal fallback if template missing
        return render_template_string("""
            <!doctype html><title>Login</title>
            <h1>Case Organizer (fallback login)</h1>
            <form method="post">
              <input name="username" placeholder="Username" required>
              <input name="password" type="password" placeholder="Password" required>
              <button>Login</button>
            </form>
        """)

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

@app.route("/")
def home():
    try:
        return render_template("index.html")
    except Exception:
        return render_template_string("""
            <!doctype html><title>Home</title>
            <h1>Home (fallback)</h1>
            <p>Logged in as: {{ session.get('user') }}</p>
            <p><a href="{{ url_for('logout') }}">Logout</a></p>
        """)

# ---- Create Case --------------------------------------------------------
@app.post("/create-case")
def create_case():
    form = request.form

    # Parties (authoritative for Case Name)
    pn = normalize_ws(form.get("Petitioner Name"))
    rn = normalize_ws(form.get("Respondent Name"))
    case_name = normalize_ws(form.get("Case Name"))  # UI may send it; we recompute to be safe
    auto_case_name = build_case_name_from_parties(pn, rn)
    if not auto_case_name:
        return jsonify({"ok": False, "msg": "Petitioner Name and Respondent Name are required to form Case Name."}), 400
    if not case_name:
        case_name = auto_case_name

    # Date (YYYY-MM-DD) or today
    date_str = normalize_ws(form.get("Date"))
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now()
    except ValueError:
        return jsonify({"ok": False, "msg": "Invalid Date. Use YYYY-MM-DD."}), 400

    year = int(dt.strftime("%Y"))
    month = month_dir_name(dt)
    cdir = case_dir(year, month, case_name)
    cdir.mkdir(parents=True, exist_ok=True)

    # Note.json payload (Title Case keys with spaces)
    fields = [
        "Petitioner Name", "Petitioner Address", "Petitioner Contact",
        "Respondent Name", "Respondent Address", "Respondent Contact",
        "Our Party", "Case Category", "Case Subcategory", "Case Type",
        "Origin State", "Origin District", "Origin Court/Forum",
        "Current State", "Current District", "Current Court/Forum",
        "Additional Notes",
    ]
    payload = {k: form.get(k, "") for k in fields}
    # Ensure consistency with Case Name used
    payload["Petitioner Name"] = pn
    payload["Respondent Name"] = rn

    note_text = make_note_json(payload)
    (cdir / "Note.json").write_text(note_text, encoding="utf-8")

    return jsonify({"ok": True, "path": str(cdir)})

# ---- Manage Case (Upload, Copy & Rename) --------------------------------

@app.post("/manage-case/upload")
def manage_case_upload():
    form = request.form

    # Locate existing case folder by Year + Month + Case Name
    year_sel  = (form.get("Year") or "").strip()
    month_sel = (form.get("Month") or "").strip()
    case_name = normalize_ws(form.get("Case Name"))
    if not (year_sel and month_sel and case_name):
        return jsonify({"ok": False, "msg": "Year, Month, and Case Name are required."}), 400

    # Classification that influences filename
    domain      = normalize_ws(form.get("Domain"))        # Criminal / Civil / Commercial / Case Law
    subcategory = normalize_ws(form.get("Subcategory"))   # optional subfolder
    main_type   = normalize_ws(form.get("Main Type"))     # OPTIONAL now

    if not domain:
        return jsonify({"ok": False, "msg": "Case Category (Domain) is required."}), 400

    # Date used for filename (only in the 'typed' scheme)
    date_str = normalize_ws(form.get("Date"))
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now()
    except ValueError:
        return jsonify({"ok": False, "msg": "Invalid Date. Use YYYY-MM-DD."}), 401

    # Accept MULTIPLE files
    files = request.files.getlist("file")
    if not files:
        return jsonify({"ok": False, "msg": "No files provided."}), 400

    cdir = FS_ROOT / year_sel / month_sel / case_name
    if not cdir.exists():
        return jsonify({"ok": False, "msg": "Case directory does not exist. Create the case first."}), 400

    # Helper: safe original base (without extension)
    def safe_stem(filename: str) -> str:
        base = Path(secure_filename(filename)).stem
        return re.sub(r"\s+", " ", base).strip()

    saved_paths = []

    # ---------- NEW: Case Law handling ----------
    if domain.lower() == "case law":
        target_dir = cdir / "Case Laws"
        target_dir.mkdir(parents=True, exist_ok=True)

        for f in files:
            if not f or f.filename == "":
                continue
            if not allowed_file(f.filename):
                continue

            ext = f.filename.rsplit(".", 1)[1].lower()

            # Filename = Main Type (as typed) OR fallback to original stem
            base = (main_type or "").strip() or safe_stem(f.filename)
            # sanitize whitespace
            base = re.sub(r"\s+", " ", base).strip()
            new_name = f"{base}.{ext}"

            tmp = target_dir / secure_filename(f"_upload_{datetime.now().timestamp()}_{secure_filename(f.filename)}")
            f.save(tmp)
            dest = target_dir / new_name

            final_dest = dest
            counter = 1
            while final_dest.exists():
                final_dest = target_dir / (dest.stem + f"_{counter}" + dest.suffix)
                counter += 1

            shutil.copyfile(tmp, final_dest)
            tmp.unlink(missing_ok=True)
            saved_paths.append(str(final_dest))

        if not saved_paths:
            return jsonify({"ok": False, "msg": "No files were saved (unsupported type?)"}), 400

        return jsonify({"ok": True, "saved_as": saved_paths})
    # ---------- END Case Law handling ----------

    # Regular categories (Criminal/Civil/Commercial)
    target_dir = cdir / subcategory if subcategory else cdir
    target_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        if not f or f.filename == "":
            continue
        if not allowed_file(f.filename):
            continue

        ext = f.filename.rsplit(".", 1)[1].lower()

        # Naming rules:
        # - If subcategory is "Primary Documents" OR main_type is empty => keep original name, append " - {Case Name}"
        # - Else => use the typed scheme "(DDMMYYYY) TYPE DOMAIN CaseName.ext"
        is_primary_docs = subcategory and subcategory.strip().lower() == "primary documents"
        if is_primary_docs or not main_type:
            base = safe_stem(f.filename)
            new_name = f"{base} - {case_name}.{ext}"
        else:
            new_name = build_filename(dt, main_type, domain, case_name, ext)

        tmp = target_dir / secure_filename(f"_upload_{datetime.now().timestamp()}_{secure_filename(f.filename)}")
        f.save(tmp)
        dest = target_dir / new_name

        final_dest = dest
        counter = 1
        while final_dest.exists():
            final_dest = target_dir / (dest.stem + f"_{counter}" + dest.suffix)
            counter += 1

        shutil.copyfile(tmp, final_dest)
        tmp.unlink(missing_ok=True)
        saved_paths.append(str(final_dest))

    if not saved_paths:
        return jsonify({"ok": False, "msg": "No files were saved (unsupported type?)"}), 400

    return jsonify({"ok": True, "saved_as": saved_paths})

# ---- Safe file serving (whitelist FS_ROOT) ------------------------------

@app.get("/static-serve")
def static_serve():
    raw = request.args.get("path", "")
    download = request.args.get("download") in {"1", "true", "yes"}
    try:
        path = Path(raw).resolve(strict=True)
    except Exception:
        return "Not found", 404
    root = FS_ROOT.resolve()
    if not str(path).startswith(str(root)) or not path.is_file():
        return "Not found", 404
    return send_file(path, as_attachment=download)

# ---- Search -------------------------------------------------------------

@app.get("/search")
def search():
    """
    Query params:
      q: free text (matches relative path)
      year: '2025'
      month: 'Jan' | 'Feb' | ...
      party: fragment to match in Case folder name (Petitioner v. Respondent)
      domain: 'Criminal' | 'Civil' | 'Commercial'
      subcategory: subfolder name e.g. 'Transfer Petitions', 'Orders/Judgments', 'Primary Documents'
      type: ignored for folder-driven search (still accepted but not required)
    Behavior:
      - If domain is given but subcategory is empty => return empty result set (force specificity).
      - If subcategory is provided => enumerate case dirs and list files found under that subfolder only.
      - Otherwise (no domain/subcategory) => fallback to broad scan with q/party/year/month filters.
    """
    q        = normalize_ws(request.args.get("q"))
    year     = normalize_ws(request.args.get("year"))
    month    = normalize_ws(request.args.get("month"))
    party    = normalize_ws(request.args.get("party"))
    domain   = normalize_ws(request.args.get("domain"))        # used only to require subcat if provided
    subcat   = normalize_ws(request.args.get("subcategory"))
    # ftype kept for backward compat but not used in folder mode
    # ftype    = normalize_ws(request.args.get("type"))

    results = []
    if not FS_ROOT.exists():
        return jsonify({"results": results})

    # Helper: yield candidate month directories given year/month filters
    def month_dirs():
        root = FS_ROOT
        years = [FS_ROOT / year] if year else [d for d in root.iterdir() if d.is_dir()]
        for y in years:
            if not y.is_dir():
                continue
            months = [y / month] if month else [d for d in y.iterdir() if d.is_dir()]
            for m in months:
                if m.is_dir():
                    yield m  # e.g., fs-files/2025/Jan

    # HARD RULE: if domain is given but subcategory is missing -> force empty
    if domain and not subcat:
        return jsonify({"results": []})

    # FOLDER-DRIVEN SEARCH when subcategory is present
    if subcat:
        subcat_lower = subcat.lower()

        for mdir in month_dirs():
            # case directories: fs-files/YYYY/Mon/<Case Name>
            for case_dir_path in mdir.iterdir():
                if not case_dir_path.is_dir():
                    continue

                case_name = case_dir_path.name  # "Petitioner v. Respondent"

                # party filter against case folder name
                if party and party.lower() not in case_name.lower():
                    continue

                # locate a child directory whose name matches subcategory (case-insensitive)
                target = None
                for child in case_dir_path.iterdir():
                    if child.is_dir() and child.name.lower() == subcat_lower:
                        target = child
                        break
                if target is None:
                    continue  # this case has no such subcategory folder

                # list allowed files inside that subcategory folder (non-recursive)
                for name in sorted(os.listdir(target)):
                    p = target / name
                    if not p.is_file():
                        continue
                    if "." not in name:
                        continue
                    ext = name.rsplit(".", 1)[1].lower()
                    if ext not in ALLOWED_EXTENSIONS:
                        continue

                    rel = p.relative_to(FS_ROOT)
                    # optional q filter against relative path text
                    if q and (q.lower() not in str(rel).lower()):
                        continue

                    results.append({
                        "file": name,
                        "path": str(p),
                        "rel":  str(rel),
                    })

        return jsonify({"results": results})

    # FALLBACK: no subcategory provided -> optional broad search
    # (Only if user didn't specify domain; if domain is provided we already early-returned empty)
    for root, dirs, files in os.walk(FS_ROOT):
        # Apply year/month filters by relative path segments
        try:
            rel = Path(root).relative_to(FS_ROOT)
            parts = rel.parts  # e.g., ('2025','Jan','Case Name', 'Some Subdir'...)
        except Exception:
            parts = ()

        if year and (len(parts) < 1 or parts[0] != year):
            continue
        if month and (len(parts) < 2 or parts[1] != month):
            continue

        # party filter checks the Case Name when available (3rd segment)
        if party:
            case_seg = parts[2] if len(parts) >= 3 else ""
            if party.lower() not in case_seg.lower():
                continue

        for name in files:
            if "." not in name:
                continue
            ext = name.rsplit(".", 1)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue
            p = Path(root) / name
            rel_file = p.relative_to(FS_ROOT)

            if q and (q.lower() not in str(rel_file).lower()):
                continue

            results.append({
                "file": name,
                "path": str(p),
                "rel":  str(rel_file),
            })

    return jsonify({"results": results})

# ---- delete-file --------------------------------


@app.post("/api/delete-file")
def api_delete_file():
    """
    Delete a file under FS_ROOT, given JSON:
      {"path": "/full/path/inside/FS_ROOT/.."}
    """
    try:
        data = request.get_json(silent=True) or {}
        raw = (data.get("path") or "").strip()
        if not raw:
            return jsonify({"ok": False, "msg": "Missing 'path'"}), 400

        target = Path(raw).resolve(strict=True)
        root = FS_ROOT.resolve()
        if not str(target).startswith(str(root)):
            return jsonify({"ok": False, "msg": "Not found"}), 404
        if not target.is_file():
            return jsonify({"ok": False, "msg": "Not a file"}), 400

        target.unlink()
        return jsonify({"ok": True})
    except FileNotFoundError:
        return jsonify({"ok": False, "msg": "File not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Delete failed: {e}"}), 500


# ---- Case Law Upload & Search -------------------------------------------


@app.post("/case-law/upload")
def case_law_upload():
    if not FS_ROOT:
        return case_law_error("Storage root is not configured yet.")

    ensure_root()

    form = request.form
    petitioner = normalize_ws(form.get("petitioner") or "")
    respondent = normalize_ws(form.get("respondent") or "")
    citation = normalize_ws(form.get("citation") or "")
    decision_year_raw = normalize_ws(form.get("decision_year") or "")
    primary_raw = normalize_ws(form.get("primary_type") or "")
    case_type_raw = normalize_ws(form.get("case_type") or form.get("subtype") or "")
    note_text = (form.get("note") or "").strip()

    if not petitioner:
        return case_law_error("Petitioner name is required.")
    if not respondent:
        return case_law_error("Respondent name is required.")
    if not citation:
        return case_law_error("Citation is required.")

    try:
        decision_year = int(decision_year_raw)
    except ValueError:
        return case_law_error("Decision year must be a number.")

    current_year = datetime.now().year
    if decision_year < 1800 or decision_year > current_year + 1:
        return case_law_error("Decision year looks invalid.")

    decision_month = ""

    primary = normalize_primary_type(primary_raw)
    if not primary:
        return case_law_error("Primary classification must be Civil, Criminal, or Commercial.")

    case_type = normalize_case_type(primary, case_type_raw)
    if not case_type:
        return case_law_error("Please select a valid case type for the chosen classification.")

    if not note_text:
        return case_law_error("An additional note is required for case law entries.")

    upload = request.files.get("file")
    if not upload or upload.filename == "":
        return case_law_error("Attach the judgment file to upload.")

    if "." not in upload.filename:
        return case_law_error("The uploaded file must include an extension.")

    ext = upload.filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return case_law_error(f"File type '.{ext}' is not allowed.")

    conn = get_case_law_db()
    existing = conn.execute(
        """
        SELECT id FROM case_law
        WHERE petitioner = ? AND respondent = ? AND citation = ?
          AND primary_type = ? AND subtype = ? AND decision_year = ?
        """,
        (petitioner, respondent, citation, primary, case_type, decision_year),
    ).fetchone()
    if existing:
        return case_law_error("A case law record with the same metadata already exists.", 409)

    display_name = build_case_law_display_name(petitioner, respondent, citation)
    safe_case_name = sanitize_case_law_component(display_name) or f"Case Law {decision_year}"

    case_law_root = _case_law_root()
    primary_segment = sanitize_case_law_component(primary, replacement="-") or "General"
    type_segment = sanitize_case_law_component(case_type, replacement="-") or "General"
    base_dir = case_law_root / primary_segment / type_segment / str(decision_year)
    base_dir.mkdir(parents=True, exist_ok=True)

    case_dir = ensure_unique_path(base_dir / safe_case_name)
    case_dir.mkdir(exist_ok=False)

    tmp_name = secure_filename(f"upload_{datetime.now().timestamp()}_{upload.filename}")
    tmp_path = case_dir / tmp_name
    upload.save(tmp_path)

    target_file = case_dir / f"{safe_case_name}.{ext}"
    target_file = ensure_unique_path(target_file)
    tmp_path.rename(target_file)

    note_payload = {
        "Petitioner": petitioner,
        "Respondent": respondent,
        "Citation": citation,
        "Decision Year": decision_year,
        "Primary Type": primary,
        "Case Type": case_type,
        "Note": note_text,
        "Saved At": datetime.now().isoformat(timespec="seconds"),
    }
    note_json = json.dumps(note_payload, indent=2)

    note_file = case_dir / "note.json"
    note_file.write_text(note_json, encoding="utf-8")

    judgement_text = extract_text_for_index(target_file)
    folder_rel = str(case_dir.relative_to(FS_ROOT))
    note_rel = str(note_file.relative_to(FS_ROOT))

    try:
        cur = conn.execute(
            """
            INSERT INTO case_law (
                petitioner, respondent, citation, decision_year, decision_month,
                primary_type, subtype, folder_rel, file_name, note_path_rel, note_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                petitioner,
                respondent,
                citation,
                decision_year,
                decision_month,
                primary,
                case_type,
                folder_rel,
                target_file.name,
                note_rel,
                note_text,
            ),
        )
        case_id = cur.lastrowid
        refresh_case_law_index(
            conn,
            case_id,
            judgement_text,
            petitioner,
            respondent,
            citation,
            note_json,
        )
        conn.commit()
    except Exception as exc:
        shutil.rmtree(case_dir, ignore_errors=True)
        raise exc

    return jsonify({
        "ok": True,
        "case_id": case_id,
        "folder": folder_rel,
        "file": target_file.name,
        "note": note_rel,
    })


@app.get("/case-law/search")
def case_law_search():
    if not FS_ROOT:
        return jsonify({"results": [], "filters": {}})

    conn = get_case_law_db()
    params: list[Any] = []
    where: list[str] = []
    join_fts = False

    text_query_raw = request.args.get("text") or ""
    text_query = normalize_ws(text_query_raw)
    if text_query:
        fts_query = normalize_boolean_query(text_query)
        if not fts_query:
            return jsonify({"results": []})
        join_fts = True
        where.append("c.id IN (SELECT rowid FROM case_law_fts WHERE case_law_fts MATCH ?)")
        params.append(fts_query)

    party_raw = normalize_ws(request.args.get("party") or "")
    party_mode = normalize_ws(request.args.get("party_mode") or "either")
    if party_raw:
        like = f"%{party_raw.lower()}%"
        if party_mode == "petitioner":
            where.append("LOWER(c.petitioner) LIKE ?")
            params.append(like)
        elif party_mode == "respondent":
            where.append("LOWER(c.respondent) LIKE ?")
            params.append(like)
        else:
            where.append("(LOWER(c.petitioner) LIKE ? OR LOWER(c.respondent) LIKE ?)")
            params.extend([like, like])

    citation_raw = normalize_ws(request.args.get("citation") or "")
    if citation_raw:
        where.append("LOWER(c.citation) LIKE ?")
        params.append(f"%{citation_raw.lower()}%")

    year_raw = normalize_ws(request.args.get("year") or "")
    if year_raw:
        try:
            year_val = int(year_raw)
        except ValueError:
            return jsonify({"results": [], "error": "Invalid year filter supplied."}), 400
        where.append("c.decision_year = ?")
        params.append(year_val)

    primary_raw = normalize_ws(request.args.get("primary_type") or "")
    if primary_raw:
        primary = normalize_primary_type(primary_raw)
        if not primary:
            return jsonify({"results": [], "error": "Invalid primary classification."}), 400
        where.append("c.primary_type = ?")
        params.append(primary)

    case_type_raw = normalize_ws(request.args.get("case_type") or "")
    if case_type_raw and primary_raw:
        primary = normalize_primary_type(primary_raw)
        case_type = normalize_case_type(primary or "", case_type_raw)
        if not case_type:
            return jsonify({"results": [], "error": "Invalid case type supplied."}), 400
        where.append("c.subtype = ?")
        params.append(case_type)

    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))

    select_fields = [
        "c.id",
        "c.petitioner",
        "c.respondent",
        "c.citation",
        "c.decision_year",
        "c.decision_month",
        "c.primary_type",
        "c.subtype AS case_type",
        "c.folder_rel",
        "c.file_name",
        "c.note_path_rel",
        "c.note_text",
        "c.created_at",
        "c.updated_at",
    ]

    select_fields.append("'' AS fts_content")

    sql = "SELECT " + ", ".join(select_fields) + " FROM case_law c"

    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += " ORDER BY c.decision_year DESC, c.created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    results = [
        serialize_case_law(row, row["fts_content"]) for row in rows
    ]

    years = [r[0] for r in conn.execute("SELECT DISTINCT decision_year FROM case_law ORDER BY decision_year DESC").fetchall()]
    return jsonify({
        "results": results,
        "filters": {
            "years": years,
            "primary_types": list(CASE_LAW_PRIMARY_TYPES),
            "case_types": CASE_LAW_CASE_TYPES,
        },
    })


@app.get("/case-law/<int:case_id>/download")
def case_law_download(case_id: int):
    if not FS_ROOT:
        return "Not found", 404

    conn = get_case_law_db()
    row = fetch_case_law_record(conn, case_id)
    if not row:
        return "Not found", 404

    try:
        file_path = case_law_file_path(row)
    except Exception:
        return "Not found", 404

    if not file_path.exists():
        return "Not found", 404

    return send_file(file_path, as_attachment=True)


@app.route("/case-law/<int:case_id>/note", methods=["GET", "POST"])
def case_law_note(case_id: int):
    if not FS_ROOT:
        return case_law_error("Storage root is not configured yet.")

    conn = get_case_law_db()
    row = fetch_case_law_record(conn, case_id)
    if not row:
        return case_law_error("Case law record not found.", 404)

    try:
        note_path = case_law_note_path(row)
    except Exception:
        return case_law_error("Invalid note path for this record."), 400

    if request.method == "GET":
        content = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        return jsonify({
            "ok": True,
            "content": content,
            "summary": row["note_text"],
        })

    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    summary = extract_note_summary(content)

    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")

    judgement_row = conn.execute("SELECT content FROM case_law_fts WHERE rowid = ?", (case_id,)).fetchone()
    judgement_text = judgement_row["content"] if judgement_row else ""

    refresh_case_law_index(
        conn,
        case_id,
        judgement_text,
        row["petitioner"],
        row["respondent"],
        row["citation"],
        content,
    )

    conn.execute(
        "UPDATE case_law SET note_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (summary, case_id),
    )
    conn.commit()

    return jsonify({"ok": True, "summary": summary})


# ---- Directory Search --------------------------

@app.get("/api/dir-tree")
def api_dir_tree():
    """
    List directory contents starting from FS_ROOT.
    Query param:
      path: relative path under FS_ROOT (optional)
    Returns:
      { "dirs": [names], "files": [ {name, path} ] }
    """
    rel = (request.args.get("path") or "").strip()
    base = FS_ROOT
    try:
        if rel:
            base = (FS_ROOT / rel).resolve()
            # enforce FS_ROOT jail
            if not str(base).startswith(str(FS_ROOT.resolve())):
                return jsonify({"dirs": [], "files": []})
        if not base.exists() or not base.is_dir():
            return jsonify({"dirs": [], "files": []})

        dirs = []
        files = []
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir():
                dirs.append(entry.name)
            elif entry.is_file():
                if "." in entry.name and entry.name.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS:
                    files.append({"name": entry.name, "path": str(entry)})
        return jsonify({"dirs": dirs, "files": files})
    except Exception as e:
        return jsonify({"dirs": [], "files": [], "error": str(e)}), 500


# ---- API: fetch Note.json content (for modal) --------------------------
@app.route("/api/note/<year>/<month>/<case_name>", methods=["POST"])
def api_update_note(year, month, case_name):
    cdir = FS_ROOT / year / month / case_name
    note_path = cdir / "Note.json"

    if not note_path.exists():
        template = make_note_json({})
        return jsonify({"ok": False, "msg": "Note.json not found", "template": template}), 404

    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    try:
        note_path.write_text(content, encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Write failed: {e}"}), 500



# ---- API: Create Note.json --------------------------------
@app.post("/api/create-note")
def api_create_note():
    data = request.get_json(silent=True) or {}
    case_path = (data.get("case_path") or "").strip()
    if case_path:
        parts = Path(case_path).parts
        if len(parts) < 3:
            return jsonify({"ok": False, "msg": "Invalid case_path"}), 400
        year, month, case = parts[-3], parts[-2], parts[-1]
    else:
        year  = (data.get("year") or "").strip()
        month = (data.get("month") or "").strip()
        case  = normalize_ws(data.get("case") or "")

    if not (year and month and case):
        return jsonify({"ok": False, "msg": "Year, month, and case are required"}), 400

    cdir = (FS_ROOT / year / month / case).resolve()
    root = FS_ROOT.resolve()
    if not str(cdir).startswith(str(root)):
        return jsonify({"ok": False, "msg": "Invalid path"}), 400
    if not cdir.exists():
        return jsonify({"ok": False, "msg": "Case folder not found"}), 404

    note_file = cdir / "Note.json"
    if note_file.exists():
        return jsonify({"ok": False, "msg": "Note.json already exists"}), 400

    content = data.get("content") or ""

    payload: Dict[str, Any] = {}
    if content.strip():
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                payload = parsed
            else:
                payload = {"Additional Notes": content}
        except json.JSONDecodeError:
            payload = {"Additional Notes": content}

    try:
        text_out = make_note_json(payload)
        note_file.write_text(text_out, encoding="utf-8")
        return jsonify({"ok": True, "path": str(note_file)})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Write failed: {e}"}), 500

@app.route("/api/note/<year>/<month>/<case_name>", methods=["GET", "POST"])
def api_note(year, month, case_name):
    cdir = FS_ROOT / year / month / case_name
    note_path = cdir / "Note.json"
    if not note_path.exists():
        template = make_note_json({})
        return jsonify({"ok": False, "msg": "Note.json not found", "template": template}), 404

    if request.method == "GET":
        content = note_path.read_text(encoding="utf-8")
        return jsonify({"ok": True, "content": content, "template": make_note_json({})})

    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    try:
        note_path.write_text(content, encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Write failed: {e}"}), 500



# ---- Entrypoint ---------------------------------------------------------
if __name__ == "__main__":
    ensure_root()
    print("\nURL map:")
    for r in app.url_map.iter_rules():
        methods = ",".join(sorted(m for m in r.methods if m not in {"HEAD","OPTIONS"}))
        print(f"  {r.rule:22s} [{methods}]")
    print()
    app.run(host="0.0.0.0", port=5000, debug=True)
