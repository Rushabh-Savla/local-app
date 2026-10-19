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
local_app/
├── README.md
├── .env.example
├── .env                     # local machine config; not committed to Git
├── .gitignore              # excludes local secrets and virtualenvs
├── config.env              # NAS/dataset workflow configuration
├── requirements_agent.txt
├── desktop_app.py          # main GUI application
├── run_gui.sh              # Linux/macOS launcher
├── run_gui.bat             # Windows launcher
├── run_agent.sh            # Linux CLI launcher
├── run_agent.ps1           # Windows PowerShell launcher
├── annotator_agent/
│   ├── __init__.py
│   ├── agent.py
│   ├── api_client.py
│   └── local_cache.py
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
cd local_app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements_agent.txt
```

#### Windows PowerShell
```powershell
cd local_app
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements_agent.txt
```

#### Windows CMD
```cmd
cd local_app
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

Then edit `.env` with absolute paths:

```bash
SERVER_URL="http://<SERVER_IP>:8080"
ROOT="/home/<your_user>/nas_annotation_workspace"
```

Example:

```bash
SERVER_URL="http://192.168.1.10:8080"
ROOT="/home/annotator/nas_annotation_workspace"
```

Use the real absolute path for the current PC. Do not leave `ROOT` as a relative value like `home/nas_annotation_workspace` or `./nas_annotation_workspace`.

### 3) Run the app

#### Linux / macOS
```bash
cd local_app
source .venv/bin/activate
./run_gui.sh
```

Or directly:
```bash
python3 desktop_app.py
```

#### Windows
```cmd
cd local_app
.venv\Scripts\activate.bat
run_gui.bat
```

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

