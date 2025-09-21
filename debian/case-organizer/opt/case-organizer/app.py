
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from functools import wraps
from pathlib import Path
import json
from typing import Dict, Any

from flask import (
    Flask, request, jsonify, session, redirect, url_for,
    render_template, render_template_string, flash, send_file
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


# ---- View/Edit Note.json --------------------------------
@app.route("/view_note/<year>/<month>/<case_name>", methods=["GET", "POST"])
def view_note(year, month, case_name):
    cdir = FS_ROOT / year / month / case_name
    note_path = cdir / "Note.json"

    if request.method == "POST":
        new_content = request.form.get("note_content", "")
        try:
            # validate JSON
            data = json.loads(new_content)
            note_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
            flash("Note.json updated successfully!", "success")
        except Exception as e:
            flash(f"Invalid JSON: {e}", "error")

    if note_path.exists():
        content = note_path.read_text(encoding="utf-8")
    else:
        content = "{}"

    return render_template("view_note.html",
                           year=year, month=month, case_name=case_name,
                           content=content)



# ---- Entrypoint ---------------------------------------------------------
if __name__ == "__main__":
    ensure_root()
    print("\nURL map:")
    for r in app.url_map.iter_rules():
        methods = ",".join(sorted(m for m in r.methods if m not in {"HEAD","OPTIONS"}))
        print(f"  {r.rule:22s} [{methods}]")
    print()
    app.run(host="0.0.0.0", port=5000, debug=True)

