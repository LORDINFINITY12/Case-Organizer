# Case Organizer

Case Organizer is a lightweight Flask-based file and case management tool designed for law practice workflows.  
It organizes case files into a structured hierarchy (`fs-files`) and provides a browser-based UI for creating cases, uploading/categorizing files, and searching across case directories.

---

## Features

- **Initial Setup Flow**
  - Choose the storage root (`fs-files` location).
  - Define allowed users.
  - Set a shared password for login.

- **Authentication**
  - Shared password + username-based login.
  - Session-based authentication enforced globally.

- **Case Management**
  - Create new case directories with Petitioner/Respondent info.
  - Auto-generate `Note.json` metadata file in human-readable format.
  - Upload files into categorized subdirectories:
    - Criminal / Civil / Commercial
    - Subcategories like Transfer Petitions, Appeals, Orders/Judgments, Primary Documents, etc.
  - File types supported: **PDF, DOCX, TXT, PNG, JPG, JPEG, JSON**

- **File Naming**
  - Automatically renames uploaded files in the format:
    ```
    (DDMMYYYY) TYPE DOMAIN Petitioner v. Respondent.ext
    ```
  - Reference/Primary Documents keep their original names with case name appended.

- **Search**
  - Search by:
    - Year, Month
    - Party name (Petitioner/Respondent)
    - Domain + Subcategory
    - Free-text query
  - Domain filters require a subcategory (e.g. Civil + Transfer Petitions).

- **Safe File Serving**
  - Files are only served from within the configured `fs-files` root.

---

## Installation

### Requirements
- Python 3.10+
- Flask
- Werkzeug

### Clone & Setup
```bash
git clone https://github.com/<your-org>/case-organizer.git
cd case-organizer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Run

Start the application with:

```bash
python app.py
```

The app runs on:

```none
http://localhost:5000
```

---

## First Run Flow

1. **Setup Storage & Users**  
   On first run, the app will redirect you to `/setup`.  
   Choose the folder for your `fs-files` root.  
   Add allowed users (one per line).

2. **Set Password**  
   Next, you will be prompted to create a shared password.

3. **Login**  
   Login using one of the allowed usernames and the shared password.

4. **Home Page**  
   Use:  
   - **Create Case** → make new case directories + notes.  
   - **Manage Case** → upload and categorize files.  
   - **Search** → search across structured case files.

---

## File Structure

Cases are organized as:

```none
fs-files/
  2025/
    Jan/
      Petitioner v. Respondent/
        Note.json
        [Petitions/Applications]/
        Orders/Judgments/
        Primary Documents/
```

Example Filename:

```none
(14092025) TP CIVIL Petitioner v. Respondent.pdf
```

Case-laws are organized as:

```none
case-law/
  2025/
    Primary Type/
      Case Type/
        Petitioner v. Respondent/
          Note.json
          Petitioner v. Respondent [citation].pdf
```

Example Filename:

```none
Petitioner v. Respondent [citation].pdf
```

---

## Development Notes

- Configuration is stored in `config.py` and updated during setup.  
- Allowed file extensions: `.pdf`, `.docx`, `.txt`, `.png`, `.jpg`, `.jpeg`, `.json`.

Routes for diagnostics:  
- `/ping` → quick test  
- `/__routes` → list all routes

---

## Roadmap

- Debian packaging with install-time setup script  
- Extended metadata editing from the UI  

---
