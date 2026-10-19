# Annotator Workstation Application (`annotator_app`)

Cross-platform desktop application and background sync agent for computer vision dataset annotators. Designed to interact seamlessly with the Central Annotation Platform server over HTTP/REST APIs.

---

## 🌟 Highlights & Features

- **Modern Tkinter GUI (`desktop_app.py`):**
  - Card-based UI with active assignment tracking, allocation counters, and live progress bars.
  - Multi-step guided action flow: **Fetch Images** ➔ **Open X-AnyLabeling** ➔ **Sync & Submit Review**.
  - Background declaration modal allowing annotators to submit non-annotated background images with structured justifications.
  - Direct connection to Central Server (`http://192.168.1.103:8080`) with user authentication (token-based session management).
- **Annotator Agent Engine (`annotator_agent/`):**
  - **`api_client.py`:** Robust HTTP client supporting login, assignment claims, heartbeat pings, background declarations, and batch completion submissions.
  - **`agent.py`:** Asynchronous lifecycle manager handling automatic assignment polling and background lease renewal.
  - **`local_cache.py`:** Local file integrity verification (SHA-256 checks) preventing corrupted or duplicate image transfers.
- **Cross-Platform 1-Click Launchers:**
  - Windows: `run_gui.bat` / `run_agent.ps1`
  - Linux/macOS: `run_gui.sh` / `run_agent.sh` / `AnnotationApp.desktop`

---

## 📂 Repository Structure

```
annotator_app/
├── desktop_app.py            # Primary Tkinter workstation GUI application
├── annotator_agent/          # Core client library
│   ├── agent.py              # Background worker & lifecycle orchestration
│   ├── api_client.py         # HTTP REST API client
│   ├── local_cache.py        # Workspace cache & SHA-256 integrity checks
│   └── __init__.py
├── tests/                    # Unit & UI test suite
│   ├── test_desktop_app.py   # Test cases for desktop application
│   └── __init__.py
├── run_gui.bat               # 1-Click launcher for Windows
├── run_gui.sh                # 1-Click launcher for Linux / macOS
├── run_agent.ps1             # Headless agent runner (Windows PowerShell)
├── run_agent.sh              # Headless agent runner (Linux Bash)
├── AnnotationApp.desktop     # Linux desktop application entry
├── requirements.txt          # Client dependencies
├── .env.example              # Sample client environment configuration
├── pytest.ini                # Pytest configuration
└── .github/workflows/
    └── app_tests.yml         # Automated CI testing pipeline
```

---

## 🚀 Quickstart Installation

### 1. Prerequisites
- Python 3.10+ installed
- Pip package manager
- Network connectivity to the central server (`http://192.168.1.103:8080`)

### 2. Setup Virtual Environment

#### On Windows:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### On Linux / macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 💻 Running the Application

### Option A: GUI Mode (Standard for Human Annotators)

- **Windows:** Double-click `run_gui.bat` or run:
  ```powershell
  python desktop_app.py
  ```
- **Linux:** Run:
  ```bash
  chmod +x run_gui.sh
  ./run_gui.sh
  ```

### Option B: Headless Agent Mode

Runs the background sync daemon without the graphical interface:
```bash
./run_agent.sh --server http://192.168.1.103:8080 --username <username> --password <password>
```

---

## 🔄 Daily Annotator Workflow

1. **Connect & Authenticate:**
   - Launch `desktop_app.py`.
   - Enter Central Server URL (default: `http://192.168.1.103:8080`) and your credentials.
   - Click **Connect & Login**.
2. **Fetch Assigned Images:**
   - The UI automatically loads your active batch from the server.
   - Click **📥 Step 1: Fetch Batch Images** to download image packages into your local workspace.
3. **Annotate in Tooling:**
   - Click **🎨 Step 2: Open Annotation Tool** (launches X-AnyLabeling or your preferred tool pointed at your workspace).
   - Draw labels, bounding boxes, or polygons.
4. **Mark Background Items (if applicable):**
   - If an image contains no detectable targets, use the **Mark as Background** button to declare it with a reason.
5. **Sync & Submit for Master Approval:**
   - Click **☁️ Step 3: Sync & Submit for Review**.
   - Your local annotations are verified and uploaded to the central server for master review.

---

## 🧪 Testing

Run automated tests:
```bash
pytest tests/ -v
```

---

## 🔗 Related Repositories

- **Main Orchestration Repo:** [Rushabh-Savla/nas_annotation_automation](https://github.com/Rushabh-Savla/nas_annotation_automation)
- **Web Admin Subrepo:** [Rushabh-Savla/admin_webpage](https://github.com/Rushabh-Savla/admin_webpage)