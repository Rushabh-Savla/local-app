# Local Desktop Annotation App

This project is a local desktop annotation workstation for annotators. It runs on each annotator's laptop or PC, connects to the central server, and stores local work in a machine-specific workspace.

This app is designed to be run locally on a workstation and is not a Dockerized service.

---

## Prerequisites

- Python 3.10 or newer is recommended
- Tkinter support for the desktop GUI
- Access to the central annotation platform running at a known server URL
- Local folder permissions for the workspace storage path

> Different PCs may use different Python versions and folder layouts. That is why the project uses a local virtual environment and a per-machine `.env` file.

---

## Project Structure

```text
local-app/
├── README.md               # Detailed workstation setup & usage documentation
├── .env.example            # Workstation configuration template
├── .env                    # Local machine config (SERVER_URL, ROOT); not committed
├── .gitignore              # Excludes local secrets, SQLite cache, and virtualenvs
├── config.env              # Workflow configuration
├── requirements_agent.txt  # Lightweight client dependencies (httpx)
├── desktop_app.py          # Tkinter desktop GUI workstation application
├── run_gui.sh              # 1-Click GUI launcher for Linux & macOS (auto-resolving)
├── run_gui.bat             # 1-Click GUI launcher for Windows (auto-resolving)
├── setup_desktop.sh        # 1-Click Desktop Icon Installer for Linux & macOS
├── setup_desktop.bat       # 1-Click Desktop Shortcut Installer for Windows
├── setup_desktop_icon.py   # Cross-platform desktop shortcut generator
├── AnnotationApp.desktop   # Linux desktop entry launcher specification
├── assets/
│   ├── app_icon.png        # Workstation logo (Linux desktop & window decoration)
│   └── app_icon.ico        # Multi-resolution Windows application icon
├── run_agent.sh            # Headless Linux agent runner
├── run_agent.ps1           # Headless Windows PowerShell agent runner
├── annotator_agent/        # Core agent client modules
│   ├── __init__.py
│   ├── agent.py            # Local cache, batch checkout, and sync agent logic
│   ├── api_client.py       # REST API client for central controller
│   └── local_cache.py      # SQLite offline-resilient lease & submission cache
└── scripts/
    └── manager.py
```

---

## What each config file is for

1. `.env` — machine-specific runtime config for the desktop app
   - `SERVER_URL` = central platform URL for this PC
   - `ROOT` = local working directory for downloaded annotation data

2. `.env.example` — template for new machines
   - copy it to `.env` and customize for the current PC

3. `config.env` — helper/NAS workflow settings
   - used for dataset and NAS-related workflows
   - not for the app login URL

---

## Setup on Your Machine

### 1) Create a virtual environment

#### Linux / macOS
```bash
cd local-app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements_agent.txt
```

#### Windows PowerShell
```powershell
cd local-app
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements_agent.txt
```

#### Windows CMD
```cmd
cd local-app
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements_agent.txt
```

> If your PC uses Python 3.12 instead, replace `3.11` with your installed version. The important part is to keep the environment local to that machine.

### 2) Create the local app env file
```bash
cp .env.example .env
```

Then edit `.env` for your machine:

```bash
SERVER_URL="http://<SERVER_IP>:8080"
ROOT="$HOME/nas_annotation_workspace"
```

Example on Linux:
```bash
SERVER_URL="http://192.168.1.10:8080"
ROOT="/home/easemyai/nas_annotation_workspace"
# Or conveniently:
# ROOT="$HOME/nas_annotation_workspace"
```

Example on Windows:
```bash
SERVER_URL="http://192.168.1.103:8080"
ROOT="C:\\nas_annotation_workspace"
```

> **PermissionError Troubleshooting (`Permission denied: '/home/annotator'`):**
> If you encounter:
> ```text
> PermissionError: [Errno 13] Permission denied: '/home/annotator'
> ```
> This occurs because `.env` is set to `/home/annotator/nas_annotation_workspace`, but your Linux username is different (e.g. `easemyai`). Linux users do not have permissions to create new folders directly in `/home/`.
> **Fix:** Change `ROOT` in `.env` to point inside your actual user directory, e.g.:
> `ROOT="$HOME/nas_annotation_workspace"` or `ROOT="/home/<your_username>/nas_annotation_workspace"`.

### 3) 1-Click Desktop Icon Installation (Recommended)

Set up a branded desktop shortcut that allows launching the application with a single click from your **Desktop** or **Applications/Start Menu**. The launcher includes dynamic path resolution, ensuring it starts properly even if the shortcut icon is copied or moved anywhere.

#### On Linux / macOS
Run the 1-click desktop setup script:
```bash
cd local-app
chmod +x setup_desktop.sh run_gui.sh
./setup_desktop.sh
```

**What this does automatically:**
1. Dynamically resolves the installation directory of `local-app`.
2. Registers the path in `~/.config/nas_annotation/app_path`.
3. Creates a desktop icon at `~/Desktop/AnnotationApp.desktop` with the official workstation logo ([assets/app_icon.png](file:///D:/EaseMyAi/annotation_automation/nas_annotation_automation/local-app/assets/app_icon.png)).
4. Adds an entry to `~/.local/share/applications/AnnotationApp.desktop` so the app is searchable in your GNOME / KDE Application Grid / Dock.
5. Sets executable permissions (`chmod +x`) and configures GNOME trust metadata (`gio set metadata::trusted true`).

> **First-time GNOME Launch Note:** On some Ubuntu / GNOME versions, double-click the desktop icon once. If prompted with *"Untrusted Desktop Entry"*, right-click the icon and select **"Allow Launching"**. The icon will immediately turn into the custom logo and launch seamlessly thereafter.

---

#### On Windows
- **Method 1 (1-Click Graphical):**
  Open File Explorer, go to the `local-app` folder, and **double-click** `setup_desktop.bat`.

- **Method 2 (Command Prompt / PowerShell):**
  ```cmd
  cd local-app
  setup_desktop.bat
  ```
  or with Python:
  ```powershell
  cd local-app
  python setup_desktop_icon.py
  ```

**What this does automatically:**
1. Registers the absolute path in `%LOCALAPPDATA%\nas_annotation\app_path.txt`.
2. Creates a branded shortcut on your **Desktop**: `%USERPROFILE%\Desktop\NAS Annotation Workstation.lnk` using the high-resolution Windows icon ([assets/app_icon.ico](file:///D:/EaseMyAi/annotation_automation/nas_annotation_automation/local-app/assets/app_icon.ico)).
3. Adds a shortcut to your **Windows Start Menu** under `Programs`.
4. Binds the correct working directory and Python launcher, with automatic fallback to WSL bash if native Windows Python is not configured.

---

### 4) Manual / Terminal Launch Options

If you prefer to run the application directly from your terminal:

#### Linux / macOS
```bash
cd local-app
source .venv/bin/activate
./run_gui.sh
```
Or directly with Python:
```bash
python3 desktop_app.py
```

#### Windows
From Command Prompt:
```cmd
cd local-app
.venv\Scripts\activate.bat
run_gui.bat
```
Or directly with Python:
```cmd
python desktop_app.py
```

---

### 5) How "Launch from Anywhere" Auto-Discovery Works

Both `run_gui.sh` and `run_gui.bat` are designed to self-locate the project root:
- **Symlink Resolution:** `run_gui.sh` resolves all symlinks recursively using `readlink` logic. You can symlink `run_gui.sh` into `~/bin` or `/usr/local/bin` and run `run_gui.sh` from any working directory.
- **Persistent App Registration:** Running `setup_desktop.sh` or `setup_desktop.bat` stores the real path in your user profile (`~/.config/nas_annotation/app_path` on Linux, `%LOCALAPPDATA%\nas_annotation\app_path.txt` on Windows). If a launcher is invoked from outside the project directory, it checks this registration file to locate `desktop_app.py`.
- **Relocation:** If you move the repository to a new directory, simply run `./setup_desktop.sh` or `setup_desktop.bat` once to update the registered path.

---

## Runtime Configuration Notes

- Each PC should have its own `.env` file.
- Do not commit `.env` to Git.
- Keep `SERVER_URL` and `ROOT` local to the machine.
- `config.env` is separate and may be used by NAS helper scripts.

Example `config.env` for a dataset workflow:

```bash
REMOTE="annotation_nas"
DATASET="ai_data_collection/test/new_dataset/n01494475"
ROOT="/home/<your_user>/nas_annotation_workspace"
```

Do not put the server URL into `config.env` unless a helper script specifically expects it.

---

## Login and Usage

1. Launch the desktop app.
2. Enter the annotator username and password.
3. The latest username and password are saved locally on that PC.
4. When the app restarts, the last-entered credentials are restored automatically.
5. The app fetches assigned batches from the central platform and uploads completed work.

---

## Production-Ready Notes

- Keep `.env` out of source control.
- Keep the Python environment inside the repo or local workstation folder, not system-wide.
- Each annotator machine should have its own `ROOT` path and `SERVER_URL` values.
- Use the same repo codebase but different local runtime settings per machine.

This keeps the project portable across different laptops and PCs while remaining easy to run and safe for GitHub-based collaboration.

