#!/usr/bin/env python3
"""Desktop GUI for NAS Dataset Annotation Workstation.

Enterprise-Grade Desktop Application for Data Annotation Operations:
1. Central Production Mode (Multi-Computer Workstation):
   - Left sidebar navigation with modern enterprise aesthetic
   - Real-time connection & user status pills
   - Metric KPI summary panels & dynamic actionable hero guidance
   - 4-Step visual annotation workflow (Fetch -> Annotate -> Upload & Sync -> Clean)
   - Real-time Assigned Projects & Batches Table (Treeview) with search filtering
   - Monospace audit activity log with syntax tagging & clipboard export
   - Safe token-based authentication and lease renewal
2. Standalone Legacy Mode (Single-PC POC):
   - Direct local config and legacy scripts with full backward compatibility
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Optional, Any

import tkinter as tk
from tkinter import messagebox, ttk

# Optional import of centralized annotator agent
try:
    from annotator_agent.agent import AnnotatorAgent
except ImportError:
    # If launched outside pythonpath, add project root
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from annotator_agent.agent import AnnotatorAgent
    except Exception:
        AnnotatorAgent = None


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.env"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


ENV_CONFIG: Dict[str, str] = {}


def _load_env_file() -> Dict[str, str]:
    """Strictly load and parse key-value pairs from .env file into ENV_CONFIG and os.environ.
    
    Values in .env strictly override any ambient environment variables so that local
    configuration is always respected without falling back to arbitrary hardcoded defaults.
    """
    global ENV_CONFIG
    candidates = [
        PROJECT_ROOT / ".env",
        Path.cwd() / ".env",
    ]
    env_file = None
    for c in candidates:
        if c.is_file():
            env_file = c
            break

    if not env_file:
        return ENV_CONFIG

    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                # Remove enclosing quotes
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                else:
                    # Strip inline comments if present
                    if " #" in v:
                        v = v.split(" #", 1)[0].strip()
                    elif "\t#" in v:
                        v = v.split("\t#", 1)[0].strip()

                v = os.path.expandvars(os.path.expanduser(v)).strip()
                if k:
                    ENV_CONFIG[k] = v
                    # Strictly override os.environ with the explicit .env value
                    os.environ[k] = v
    except Exception as exc:
        print(f"Warning: Failed to parse .env file at {env_file}: {exc}")

    return ENV_CONFIG


_load_env_file()


def normalize_remote_path(value: str, remote_name: str | None = None) -> str:
    """Normalize a dataset path and strip any configured remote prefix."""
    text = (value or "").strip()
    if not text:
        return text
    text = text.replace("\\", "/")
    if text.startswith("/"):
        return text.lstrip("/")

    remote_prefix = (remote_name or "").strip()
    if remote_prefix:
        remote_prefix = remote_prefix.strip().rstrip(":/")
        for candidate in (f"{remote_prefix}:", f"{remote_prefix}/"):
            if text.startswith(candidate):
                text = text[len(candidate):]
                break

    if ":" in text:
        head, rest = text.split(":", 1)
        if rest:
            return rest.strip("/")
    if "/" in text:
        head, rest = text.split("/", 1)
        if remote_prefix and head == remote_prefix:
            return rest.strip("/")
    return text.strip("/")


def read_config_file(path: Path | str = CONFIG_PATH) -> Dict[str, str]:
    config = {}
    file_path = Path(path)
    if not file_path.exists():
        return config
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        value = os.path.expandvars(os.path.expanduser(value))
        config[key] = value
    return config


def is_local_path(path_value: str) -> bool:
    text = (path_value or "").strip()
    if not text:
        return False
    candidate = Path(text).expanduser()
    if candidate.as_posix() in {"/proc", "/sys", "/dev", "/run"}:
        return False
    if not candidate.exists():
        return candidate.parent.exists() and str(candidate).startswith("/")
    try:
        fs = subprocess.run(
            ["findmnt", "-T", str(candidate), "-o", "FSTYPE", "-n"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return True
    fstype = (fs.stdout or "").strip()
    if fstype.lower() in {"cifs", "nfs", "nfs4", "fuse.rclone", "fuse.sshfs", "sshfs"}:
        return False
    return True


def validate_config(cfg: Dict[str, str]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    remote = (cfg.get("REMOTE") or "").strip()
    dataset = (cfg.get("DATASET") or "").strip()
    root = (cfg.get("ROOT") or "").strip()
    batch_size = (cfg.get("BATCH_SIZE") or "200").strip()
    try:
        batch_value = int(batch_size)
        if batch_value <= 0:
            errors.append("BATCH_SIZE must be greater than zero.")
    except ValueError:
        errors.append("BATCH_SIZE must be an integer.")

    if not remote:
        errors.append("REMOTE is required in config.env.")
    if not dataset:
        errors.append("DATASET is required in config.env.")
    if root:
        root_path = Path(root).expanduser()
        if not root_path.is_absolute():
            errors.append("ROOT must be an absolute path, for example /home/annotator/nas_annotation_workspace")
        if not root_path.exists():
            parent = root_path.parent
            if not parent.exists():
                errors.append(f"ROOT path does not exist: {root}")
        if not is_local_path(str(root_path)):
            errors.append("ROOT must be a local filesystem, not a NAS mount or remote filesystem.")
    else:
        errors.append("ROOT is required in config.env.")

    normalized = normalize_remote_path(dataset)
    if "\\" in dataset:
        dataset = normalized
    if not normalized:
        errors.append("DATASET must be a path relative to the remote, e.g. ai_data_collection/test/images_yolo8")
    if ":" in dataset and not dataset.startswith("/"):
        dataset = normalized

    rclone_bin = (cfg.get("RCLONE_BIN") or "rclone").strip()
    if not shutil.which(rclone_bin):
        errors.append(f"Rclone executable not found: {rclone_bin}")

    xany = (cfg.get("XANYLABELING") or "xanylabeling").strip()
    if not xany:
        errors.append("XANYLABELING executable is required.")

    return (not errors, errors)


def save_config(path: Path | str, values: Dict[str, str]) -> None:
    """Update config.env in place while preserving unrelated content as much as possible."""
    target = Path(path)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    lines = existing.splitlines()
    updated: List[str] = []
    seen = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            updated.append(line)
            continue
        key, _ = stripped.split("=", 1)
        key = key.strip()
        if key in values:
            value = str(values[key]).strip()
            if value.isdigit():
                line_text = f"{key}={value}"
            else:
                line_text = f'{key}="{value}"'
            updated.append(line_text)
            seen.add(key)
        else:
            updated.append(line)
    for key, value in values.items():
        if key in seen:
            continue
        value = str(value).strip()
        if value.isdigit():
            updated.append(f"{key}={value}")
        else:
            updated.append(f'{key}="{value}"')
    content = "\n".join(updated) + ("\n" if updated else "")
    temp_path = target.with_suffix(target.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    os.replace(temp_path, target)


def build_xanylabeling_command(xany_cmd: str, working_dir: str, launch_script: str) -> List[str]:
    """Build a bash command that activates the environment and launches XAnyLabeling from the batch directory."""
    activation = (launch_script or "").strip()
    command = f"cd '{working_dir}'"
    if activation:
        command += f" && {activation}"
    command += f" && QT_OPENGL=software {xany_cmd} --qt-platform xcb"
    return ["bash", "-lc", command]


def manager_runner(*args: str) -> Tuple[int, str]:
    command = [sys.executable, str(SCRIPTS_DIR / "manager.py"), *args]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False, timeout=5)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "Operation timed out (5s limit reached)"
    except Exception as exc:
        return -1, str(exc)


def run_script(script_name: str, *args: str) -> Tuple[int, str]:
    command = ["bash", str(SCRIPTS_DIR / script_name), *args]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False, timeout=5)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "Operation timed out (5s limit reached)"
    except Exception as exc:
        return -1, str(exc)


def parse_status(output: str) -> Dict[str, object]:
    if not output:
        return {}
    text = output.strip()
    if not text:
        return {}
    start = text.find("{")
    if start == -1:
        return {}
    decoder = json.JSONDecoder()
    for offset in range(start, len(text)):
        if text[offset] != "{":
            continue
        try:
            payload, end = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def query_status() -> Dict[str, object]:
    code, stdout = manager_runner("status")
    status = parse_status(stdout)
    if status:
        return status
    return {"state": "UNKNOWN", "error": stdout.strip() or "status unavailable"}


def health_check() -> bool:
    code, _ = run_script("health.sh")
    return code == 0


def build_xanylabeling_launch_script() -> str:
    return "source ~/xanylabeling-venv-new/bin/activate"


# =============================================================================
# REDESIGNED ENTERPRISE ANNOTATOR WORKSTATION APPLICATION
# =============================================================================

class AnnotationDesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("NAS Dataset Annotation Workstation")
        self.geometry("1180x820")
        self.minsize(980, 680)
        self.project_root = PROJECT_ROOT
        self.config_path = CONFIG_PATH
        self.credentials_file = self.project_root / ".app_credentials.json"
        self.active_task: str | None = None
        self.agent: AnnotatorAgent | None = None
        self.my_assignments_data: List[Dict[str, Any]] = []
        self.password_visible = False
        self.last_sync_success = False

        # Widget references
        self.step2_widget_frame = None
        self.action_card_outer = None
        self.btn_wf_sync = None
        self.btn_secondary_action = None
        self.btn_main_action = None
        self.btn_wf_fetch = None
        self.wf_progress_bar = None

        # 1. Color Palette & Typography
        self._init_colors()
        self._configure_style()

        # 2. Agent & State Variables
        self._init_agent()
        self._init_state_vars()

        # 3. Main GUI Shell
        self._make_ui()

        # 4. Initial Auth & Screen Check (Deferred so Tk mainloop starts first)
        self.after(100, self.initial_check)

        # 5. Background Live Watcher for XAnyLabeling Progress
        self.after(1000, self._start_workspace_watcher)

        # 6. Global Ergonomic Keyboard Shortcuts
        self.bind("<Return>", self._on_global_return_key)
        self.bind("<F5>", lambda e: self.refresh_all())

    def safe_after(self, ms: int, func: Any, *args: Any) -> None:
        """Thread-safe UI callback scheduler that never throws if mainloop hasn't started or is closing."""
        try:
            if self.winfo_exists():
                self.after(ms, func, *args)
        except Exception:
            pass

    def _init_colors(self) -> None:
        # Base Surfaces
        self.C_APP_BG = "#F8FAFC"        # Slate 50
        self.C_CARD_BG = "#FFFFFF"       # White
        self.C_CARD_BORDER = "#E2E8F0"   # Slate 200
        self.C_BORDER = "#E2E8F0"        # Slate 200 alias
        self.C_SURFACE_ALT = "#F1F5F9"   # Slate 100
        self.C_TEXT_PRIMARY = "#0F172A"  # Slate 900
        self.C_TEXT_MUTED = "#64748B"    # Slate 500
        self.C_TEXT_LIGHT = "#94A3B8"    # Slate 400

        # Left Sidebar Theme
        self.C_SIDEBAR_BG = "#0F172A"       # Deep Slate 900
        self.C_SIDEBAR_HOVER = "#1E293B"    # Slate 800
        self.C_SIDEBAR_ACTIVE = "#1E293B"   # Active item background
        self.C_SIDEBAR_TEXT = "#F8FAFC"     # Slate 50
        self.C_SIDEBAR_MUTED = "#94A3B8"    # Slate 400
        self.C_SIDEBAR_ACCENT = "#6366F1"   # Indigo 500
        self.C_SIDEBAR_BORDER = "#1E293B"   # Slate 800

        # Semantics & Accents
        self.C_PRIMARY = "#4F46E5"          # Indigo 600
        self.C_PRIMARY_HOVER = "#4338CA"    # Indigo 700
        self.C_PRIMARY_LIGHT = "#EEF2FF"    # Indigo 50
        self.C_SUCCESS = "#16A34A"          # Green 600
        self.C_SUCCESS_LIGHT = "#DCFCE7"    # Green 100
        self.C_SUCCESS_TEXT = "#15803D"     # Green 700
        self.C_WARNING = "#D97706"          # Amber 600
        self.C_WARNING_LIGHT = "#FEF3C7"    # Amber 100
        self.C_WARNING_TEXT = "#B45309"     # Amber 700
        self.C_DANGER = "#DC2626"           # Red 600
        self.C_DANGER_LIGHT = "#FEE2E2"     # Red 100
        self.C_DANGER_TEXT = "#B91C1C"      # Red 700

    def _configure_style(self) -> None:
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Typography configuration
        self.font_brand = ("Helvetica", 12, "bold") if sys.platform != "win32" else ("Segoe UI", 12, "bold")
        self.font_title = ("Helvetica", 14, "bold") if sys.platform != "win32" else ("Segoe UI", 14, "bold")
        self.font_sub = ("Helvetica", 9) if sys.platform != "win32" else ("Segoe UI", 9)
        self.font_caption = ("Helvetica", 8) if sys.platform != "win32" else ("Segoe UI", 8)
        self.font_heading = ("Helvetica", 11, "bold") if sys.platform != "win32" else ("Segoe UI", 11, "bold")
        self.font_body = ("Helvetica", 10) if sys.platform != "win32" else ("Segoe UI", 10)
        self.font_body_bold = ("Helvetica", 10, "bold") if sys.platform != "win32" else ("Segoe UI", 10, "bold")
        self.font_mono = ("Courier", 9) if sys.platform != "win32" else ("Consolas", 9)

        # Flat button styles
        self.style.configure(
            "TButton",
            font=self.font_body,
            background="#FFFFFF",
            foreground=self.C_TEXT_PRIMARY,
            borderwidth=1,
            relief="solid",
            padding=(10, 6),
        )
        self.style.map(
            "TButton",
            background=[("active", "#F1F5F9"), ("pressed", "#E2E8F0"), ("disabled", "#F8FAFC")],
            foreground=[("disabled", "#94A3B8")],
        )

        self.style.configure(
            "Primary.TButton",
            font=self.font_body_bold,
            background=self.C_PRIMARY,
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(12, 7),
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", self.C_PRIMARY_HOVER), ("pressed", "#3730A3"), ("disabled", "#C7D2FE")],
            foreground=[("disabled", "#FFFFFF")],
        )

        self.style.configure(
            "Success.TButton",
            font=self.font_body_bold,
            background=self.C_SUCCESS,
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(12, 7),
        )
        self.style.map(
            "Success.TButton",
            background=[("active", "#15803D"), ("pressed", "#166534"), ("disabled", "#BBF7D0")],
        )

        self.style.configure(
            "Danger.TButton",
            font=self.font_body,
            background="#FFFFFF",
            foreground=self.C_DANGER,
            borderwidth=1,
            padding=(10, 6),
        )
        self.style.map(
            "Danger.TButton",
            background=[("active", self.C_DANGER_LIGHT), ("pressed", "#FECACA")],
        )

        # Progress bar
        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor=self.C_CARD_BORDER,
            background=self.C_PRIMARY,
            lightcolor=self.C_PRIMARY,
            darkcolor=self.C_PRIMARY,
            bordercolor=self.C_CARD_BORDER,
            thickness=10,
        )

        # Treeview styling
        self.style.configure(
            "Treeview",
            font=self.font_body,
            rowheight=28,
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground=self.C_TEXT_PRIMARY,
            borderwidth=0,
        )
        self.style.configure(
            "Treeview.Heading",
            font=self.font_body_bold,
            background="#F1F5F9",
            foreground=self.C_TEXT_MUTED,
            relief="flat",
            padding=(6, 4),
        )
        self.style.map(
            "Treeview",
            background=[("selected", self.C_PRIMARY_LIGHT)],
            foreground=[("selected", self.C_PRIMARY)],
        )

    def _get_default_server_url(self) -> str:
        """Strictly read server URL from .env file, eliminating hardcoded default IPs."""
        url = (
            ENV_CONFIG.get("SERVER_URL")
            or os.getenv("SERVER_URL")
            or ENV_CONFIG.get("PUBLIC_BASE_URL")
            or os.getenv("PUBLIC_BASE_URL")
            or ""
        ).strip()
        return url.rstrip("/")

    def _get_dashboard_url(self) -> str:
        """Return dynamic web dashboard URL based on the active server URL."""
        base = ""
        central_var = self.__dict__.get("central_url_var")
        if central_var is not None and hasattr(central_var, "get") and central_var.get().strip():
            base = central_var.get().strip()
        elif self.__dict__.get("agent") is not None and getattr(self.agent, "server_url", None):
            base = self.agent.server_url.strip()
        else:
            base = self._get_default_server_url()
        return f"{base.rstrip('/')}/dashboard" if base else "/dashboard"

    def _init_agent(self) -> None:
        if AnnotatorAgent is not None:
            default_server = self._get_default_server_url()
            raw_root = (ENV_CONFIG.get("ROOT") or os.getenv("ROOT") or str(Path.home() / "nas_annotation_workspace")).strip().strip("'\"")
            default_root = os.path.expandvars(os.path.expanduser(raw_root))
            self.agent = AnnotatorAgent(server_url=default_server, local_root=default_root)

    def _load_saved_credentials(self) -> tuple[str, str]:
        default_user = "annotator1"
        default_pass = "Annotator@2026"
        try:
            if self.credentials_file.exists():
                data = json.loads(self.credentials_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    saved_user = str(data.get("username", default_user)).strip()
                    saved_pass = str(data.get("password", default_pass)).strip()
                    if saved_user:
                        default_user = saved_user
                    if saved_pass:
                        default_pass = saved_pass
        except Exception:
            pass
        return default_user, default_pass

    def _save_credentials(self, username: str, password: str) -> None:
        try:
            payload = {
                "username": (username or "").strip(),
                "password": (password or "").strip(),
            }
            self.credentials_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            try:
                os.chmod(self.credentials_file, 0o600)
            except OSError:
                pass
        except Exception:
            pass

    def _init_state_vars(self) -> None:
        # Central auth & status variables
        default_server = self._get_default_server_url()
        saved_user, saved_pass = self._load_saved_credentials()
        self.central_url_var = tk.StringVar(value=default_server)
        self.central_user_var = tk.StringVar(value=saved_user)
        self.central_pass_var = tk.StringVar(value=saved_pass)
        self.central_auth_status_var = tk.StringVar(value="Checking connection..." if default_server else "Server URL missing in .env")
        self.central_assign_var = tk.StringVar(value="No active assignment loaded.")
        self.central_counts_var = tk.StringVar(value="Images in workspace: 0 | Annotated: 0")
        self.nas_assigned_path_var = tk.StringVar(value="None")

        # Top Bar & Navigation state
        self.top_title_var = tk.StringVar(value="System Overview")
        self.top_subtitle_var = tk.StringVar(value="Workstation health, assigned dataset batches, and recommended operations.")
        self.connection_pill_var = tk.StringVar(value="⚪ Connecting...")
        self.nas_pill_var = tk.StringVar(value="⚪ NAS: Checking...")
        self.nas_alert_var = tk.StringVar(value="")
        self.user_badge_var = tk.StringVar(value="👤 Not Logged In")
        self.is_nas_connected = True

        # Overview KPI metric variables
        self.kpi_assign_id_var = tk.StringVar(value="--")
        self.kpi_assign_status_var = tk.StringVar(value="No active batch")
        self.kpi_allocated_var = tk.StringVar(value="0")
        self.kpi_allocated_sub_var = tk.StringVar(value="Assigned images")
        self.kpi_workspace_var = tk.StringVar(value="0 / 0")
        self.kpi_workspace_sub_var = tk.StringVar(value="Downloaded locally")
        self.kpi_progress_var = tk.StringVar(value="0%")
        self.kpi_progress_sub_var = tk.StringVar(value="0 annotations synced")

        # Hero Banner action variables
        self.hero_tag_var = tk.StringVar(value="RECOMMENDED NEXT ACTION")
        self.hero_title_var = tk.StringVar(value="Checking Workstation Status...")
        self.hero_desc_var = tk.StringVar(value="Connecting to the central annotation server to load your allocated batches.")
        self.hero_btn_text_var = tk.StringVar(value="Refresh Status")

        # Active step tracker in batch workflow (1 to 4)
        self.current_workflow_step = 1

        # Sequential Workflow & Task Selection variables
        self.is_logged_in = False
        self.selected_assignment: Optional[Dict[str, Any]] = None
        self.datasets_lookup: Dict[int, Dict[str, Any]] = {}
        self.assignment_choice_map: Dict[str, Dict[str, Any]] = {}
        self.assignments_dropdown_var = tk.StringVar(value="")
        self.wf_proj_name_var = tk.StringVar(value="--")
        self.wf_alloc_count_var = tk.StringVar(value="0 images")
        self.wf_folder_var = tk.StringVar(value="None")
        self.wf_status_var = tk.StringVar(value="No task selected")
        self.wf_workspace_var = tk.StringVar(value="0 downloaded locally | 0 annotated")
        self.wf_fetch_status_var = tk.StringVar(value="Ready to download")
        self.wf_annotate_status_var = tk.StringVar(value="Waiting for download")
        self.wf_annotate_count_var = tk.StringVar(value="0 / 0 images labeled (0%)")
        self.wf_sync_status_var = tk.StringVar(value="Waiting for annotations")
        self.wf_clean_status_var = tk.StringVar(value="Locked until submission")
        self.wf_next_title_var = tk.StringVar(value="Checking your assigned projects...")
        self.wf_next_desc_var = tk.StringVar(value="Loading your tasks from the central server.")
        self.wf_next_action_btn_text = tk.StringVar(value="Check Tasks")
        self.login_error_var = tk.StringVar(value="")

        # Projects treeview filtering
        self.projects_search_var = tk.StringVar(value="")
        self.selected_assign_info_var = tk.StringVar(value="Select an assignment above to inspect manifest metadata.")

        # Logs autoscroll
        self.autoscroll_var = tk.BooleanVar(value=True)

        # Standalone Legacy Mode variables (Single-PC POC compatibility)
        self.status_var = tk.StringVar(value="Checking status...")
        self.nas_var = tk.StringVar(value="Checking connection...")
        self.progress_var = tk.StringVar(value="Waiting for catalog state...")
        self.config_vars: Dict[str, ttk.Entry] = {}
        self.action_buttons: Dict[str, ttk.Button] = {}

    # -------------------------------------------------------------------------
    # MAIN APPLICATION SHELL & SIDEBAR NAVIGATION
    # -------------------------------------------------------------------------
    def _make_ui(self) -> None:
        self.configure(bg=self.C_APP_BG)

        # Full-Width Modern Content Workspace
        self.sidebar = tk.Frame(self, bg=self.C_SIDEBAR_BG, width=240)
        # Build sidebar references so all properties exist, but keep it unpacked for clean annotator UX
        self._build_sidebar()

        self.main_container = tk.Frame(self, bg=self.C_APP_BG)
        self.main_container.pack(fill="both", expand=True)

        # 1. Build Top Header Bar in Main Area
        self._build_top_bar()

        # 2. Real-time NAS Disconnection Alert Banner
        self.nas_alert_frame = tk.Frame(
            self.main_container,
            bg="#FEE2E2",
            highlightbackground="#EF4444",
            highlightthickness=1,
            padx=16,
            pady=10,
        )
        # Packed dynamically when NAS is disconnected

        alert_left = tk.Frame(self.nas_alert_frame, bg="#FEE2E2")
        alert_left.pack(side="left", fill="x", expand=True)

        tk.Label(
            alert_left,
            text="⚠️ NAS Storage Disconnected:",
            font=("Helvetica", 10, "bold"),
            fg="#991B1B",
            bg="#FEE2E2",
        ).pack(side="left", padx=(0, 6))

        tk.Label(
            alert_left,
            textvariable=self.nas_alert_var,
            font=("Helvetica", 9),
            fg="#991B1B",
            bg="#FEE2E2",
            wraplength=700,
            justify="left",
        ).pack(side="left", fill="x", expand=True)

        btn_recheck = tk.Button(
            self.nas_alert_frame,
            text="⟳ Re-check NAS Connection",
            font=("Helvetica", 9, "bold"),
            bg="#EF4444",
            fg="#FFFFFF",
            relief="flat",
            bd=0,
            padx=12,
            pady=4,
            cursor="hand2",
            command=lambda: threading.Thread(target=self.check_nas_connection, daemon=True).start(),
        )
        btn_recheck.pack(side="right")

        # 3. Build Multi-Page Views Container
        self.views_container = tk.Frame(self.main_container, bg=self.C_APP_BG)
        self.views_container.pack(fill="both", expand=True, padx=20, pady=(12, 16))
        self.views_container.rowconfigure(0, weight=1)
        self.views_container.columnconfigure(0, weight=1)

        # Build each destination screen
        self.views: Dict[str, tk.Frame] = {}
        self._build_screen_login()
        self._build_screen_overview()
        self._build_screen_projects()
        self._build_screen_logs()
        self._build_screen_settings()
        self.views["batch"] = self.views["overview"]

        # Default view is login (initial_check will switch to overview if authenticated)
        self.switch_view("login")

    def _build_sidebar(self) -> None:
        # Header Brand area
        brand_frame = tk.Frame(self.sidebar, bg=self.C_SIDEBAR_BG, padx=16, pady=20)
        brand_frame.pack(fill="x")

        logo_row = tk.Frame(brand_frame, bg=self.C_SIDEBAR_BG)
        logo_row.pack(fill="x")

        # Geometric Logo Badge
        logo_badge = tk.Label(
            logo_row,
            text="◈",
            font=("Helvetica", 14, "bold"),
            fg="#818CF8",
            bg="#1E293B",
            padx=7,
            pady=2,
            relief="flat",
        )
        logo_badge.pack(side="left")

        title_box = tk.Frame(logo_row, bg=self.C_SIDEBAR_BG)
        title_box.pack(side="left", padx=(10, 0))

        tk.Label(
            title_box,
            text="NAS Annotation",
            font=self.font_brand,
            fg=self.C_SIDEBAR_TEXT,
            bg=self.C_SIDEBAR_BG,
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="Workstation Studio v2.0",
            font=("Helvetica", 8),
            fg=self.C_SIDEBAR_MUTED,
            bg=self.C_SIDEBAR_BG,
            anchor="w",
        ).pack(anchor="w")

        # Subtle divider
        tk.Frame(self.sidebar, bg=self.C_SIDEBAR_BORDER, height=1).pack(fill="x", padx=16, pady=(10, 14))

        # Navigation Menu List
        self.nav_items: Dict[str, Dict[str, Any]] = {}
        nav_destinations = [
            ("overview", "⚡", "My Work (Step-by-Step)", "Select project & complete 4-step workflow"),
            ("projects", "📁", "All Assigned Tasks", "View all assigned projects and batches"),
            ("logs", "📜", "Activity Logs", "Workstation audit trail"),
            ("settings", "⚙", "Settings & Config", "Credentials & legacy mode"),
        ]

        menu_frame = tk.Frame(self.sidebar, bg=self.C_SIDEBAR_BG)
        menu_frame.pack(fill="x", expand=True, anchor="n")

        for key, glyph, title, _ in nav_destinations:
            item_frame = tk.Frame(menu_frame, bg=self.C_SIDEBAR_BG, cursor="hand2")
            item_frame.pack(fill="x", pady=2)

            stripe = tk.Frame(item_frame, bg=self.C_SIDEBAR_BG, width=4)
            stripe.pack(side="left", fill="y")

            glyph_lbl = tk.Label(
                item_frame,
                text=glyph,
                font=("Helvetica", 11),
                fg=self.C_SIDEBAR_MUTED,
                bg=self.C_SIDEBAR_BG,
                padx=8,
                pady=10,
                cursor="hand2",
            )
            glyph_lbl.pack(side="left")

            text_lbl = tk.Label(
                item_frame,
                text=title,
                font=self.font_body_bold,
                fg=self.C_SIDEBAR_MUTED,
                bg=self.C_SIDEBAR_BG,
                anchor="w",
                pady=10,
                cursor="hand2",
            )
            text_lbl.pack(side="left", fill="x", expand=True)

            self.nav_items[key] = {
                "frame": item_frame,
                "stripe": stripe,
                "glyph": glyph_lbl,
                "text": text_lbl,
            }

            # Bind events for clicking and hover states
            for widget in (item_frame, stripe, glyph_lbl, text_lbl):
                widget.bind("<Button-1>", lambda e, k=key: self.switch_view(k))
                widget.bind("<Enter>", lambda e, k=key: self._on_nav_hover(k, True))
                widget.bind("<Leave>", lambda e, k=key: self._on_nav_hover(k, False))

        # Bottom User Identity Card
        user_card = tk.Frame(self.sidebar, bg=self.C_SIDEBAR_BG, padx=16, pady=16)
        user_card.pack(side="bottom", fill="x")

        tk.Frame(user_card, bg=self.C_SIDEBAR_BORDER, height=1).pack(fill="x", pady=(0, 12))

        user_row = tk.Frame(user_card, bg=self.C_SIDEBAR_BG)
        user_row.pack(fill="x")

        avatar = tk.Label(
            user_row,
            text="👤",
            font=("Helvetica", 10),
            bg="#1E293B",
            fg="#94A3B8",
            padx=6,
            pady=4,
        )
        avatar.pack(side="left")

        user_info = tk.Frame(user_row, bg=self.C_SIDEBAR_BG)
        user_info.pack(side="left", padx=(10, 0), fill="x", expand=True)

        self.sidebar_user_lbl = tk.Label(
            user_info,
            text="annotator1",
            font=self.font_body_bold,
            fg=self.C_SIDEBAR_TEXT,
            bg=self.C_SIDEBAR_BG,
            anchor="w",
        )
        self.sidebar_user_lbl.pack(anchor="w")

        self.sidebar_status_lbl = tk.Label(
            user_info,
            text="● Online",
            font=("Helvetica", 8),
            fg="#22C55E",
            bg=self.C_SIDEBAR_BG,
            anchor="w",
        )
        self.sidebar_status_lbl.pack(anchor="w")

        # Sidebar Logout button
        tk.Button(
            user_card,
            text="🚪 Log Out",
            font=("Helvetica", 9),
            bg="#1E293B",
            fg="#F87171",
            activebackground="#334155",
            activeforeground="#EF4444",
            relief="flat",
            bd=0,
            cursor="hand2",
            pady=4,
            command=self.central_logout,
        ).pack(fill="x", pady=(8, 0))

    def _build_top_bar(self) -> None:
        self.top_bar = tk.Frame(
            self.main_container,
            bg=self.C_CARD_BG,
            highlightbackground=self.C_CARD_BORDER,
            highlightthickness=1,
            padx=20,
            pady=10,
        )
        self.top_bar.pack(fill="x")

        # Left brand & user badge
        left_box = tk.Frame(self.top_bar, bg=self.C_CARD_BG)
        left_box.pack(side="left")

        brand_row = tk.Frame(left_box, bg=self.C_CARD_BG)
        brand_row.pack(anchor="w")

        tk.Label(
            brand_row,
            text="◈ NAS Annotation Studio",
            font=self.font_brand,
            fg=self.C_PRIMARY,
            bg=self.C_CARD_BG,
        ).pack(side="left")

        self.user_badge_lbl = tk.Label(
            brand_row,
            textvariable=self.user_badge_var,
            font=("Helvetica", 9, "bold"),
            fg=self.C_TEXT_MUTED,
            bg="#F1F5F9",
            padx=8,
            pady=2,
        )
        self.user_badge_lbl.pack(side="left", padx=(10, 0))

        # Center segmented horizontal navigation tabs
        tabs_frame = tk.Frame(self.top_bar, bg=self.C_CARD_BG)
        tabs_frame.pack(side="left", padx=(28, 0))

        self.tab_buttons: Dict[str, tk.Button] = {}
        tab_defs = [
            ("overview", "⚡ My Work"),
            ("projects", "📁 Assigned Tasks"),
            ("logs", "📜 Activity Log"),
        ]
        for target, label in tab_defs:
            btn = tk.Button(
                tabs_frame,
                text=label,
                font=self.font_body_bold,
                bg="#1E293B" if target == "overview" else "#F1F5F9",
                fg="#FFFFFF" if target == "overview" else self.C_TEXT_PRIMARY,
                relief="flat",
                bd=0,
                padx=14,
                pady=5,
                cursor="hand2",
                command=lambda t=target: self.switch_view(t),
            )
            btn.pack(side="left", padx=3)
            self.tab_buttons[target] = btn

        # Right status pills & actions
        right_box = tk.Frame(self.top_bar, bg=self.C_CARD_BG)
        right_box.pack(side="right")

        # Server Connection Pill
        self.conn_pill = tk.Label(
            right_box,
            textvariable=self.connection_pill_var,
            font=("Helvetica", 9, "bold"),
            fg=self.C_SUCCESS_TEXT,
            bg=self.C_SUCCESS_LIGHT,
            padx=10,
            pady=4,
            relief="flat",
        )
        self.conn_pill.pack(side="left", padx=(0, 6))

        # NAS Connection Pill
        self.nas_pill = tk.Label(
            right_box,
            textvariable=self.nas_pill_var,
            font=("Helvetica", 9, "bold"),
            fg=self.C_SUCCESS_TEXT,
            bg=self.C_SUCCESS_LIGHT,
            padx=10,
            pady=4,
            relief="flat",
        )
        self.nas_pill.pack(side="left", padx=(0, 10))

        # Global Refresh Button
        refresh_btn = tk.Button(
            right_box,
            text="⟳ Refresh",
            font=self.font_body,
            bg=self.C_APP_BG,
            fg=self.C_TEXT_PRIMARY,
            activebackground=self.C_CARD_BORDER,
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=self.C_CARD_BORDER,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self.refresh_all,
        )
        refresh_btn.pack(side="left")

        # Logout button in top bar
        logout_btn = tk.Button(
            right_box,
            text="🚪 Log Out",
            font=self.font_body,
            bg=self.C_APP_BG,
            fg=self.C_DANGER,
            activebackground=self.C_DANGER_LIGHT,
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=self.C_CARD_BORDER,
            padx=10,
            pady=3,
            cursor="hand2",
            command=self.central_logout,
        )
        logout_btn.pack(side="left", padx=(6, 0))

    def _on_nav_hover(self, key: str, is_enter: bool) -> None:
        if self.current_view == key:
            return
        if key in self.nav_items:
            item = self.nav_items[key]
            bg_col = self.C_SIDEBAR_HOVER if is_enter else self.C_SIDEBAR_BG
            item["frame"].configure(bg=bg_col)
            item["glyph"].configure(bg=bg_col)
            item["text"].configure(bg=bg_col)
            item["stripe"].configure(bg=bg_col)

    def switch_view(self, target: str) -> None:
        self.current_view = target

        if target == "login":
            if hasattr(self, "sidebar") and self.sidebar.winfo_ismapped():
                self.sidebar.pack_forget()
            if hasattr(self, "top_bar") and self.top_bar.winfo_ismapped():
                self.top_bar.pack_forget()
            if hasattr(self, "nas_alert_frame") and self.nas_alert_frame.winfo_ismapped():
                self.nas_alert_frame.pack_forget()
            def set_login_focus():
                if hasattr(self, "login_pass_entry") and hasattr(self, "login_user_entry"):
                    if self.central_user_var.get().strip():
                        self.login_pass_entry.focus_set()
                    else:
                        self.login_user_entry.focus_set()
            self.safe_after(50, set_login_focus)
        else:
            if hasattr(self, "top_bar") and not self.top_bar.winfo_ismapped():
                self.top_bar.pack(fill="x", before=self.views_container)
            if not self.is_nas_connected and hasattr(self, "nas_alert_frame") and not self.nas_alert_frame.winfo_ismapped():
                self.nas_alert_frame.pack(fill="x", padx=20, pady=(10, 0), before=self.views_container)

        # Update top navigation tab buttons styling
        if hasattr(self, "tab_buttons"):
            for key, btn in self.tab_buttons.items():
                is_active = (key == target) or (target == "batch" and key == "overview")
                btn.configure(
                    bg="#1E293B" if is_active else "#F1F5F9",
                    fg="#FFFFFF" if is_active else self.C_TEXT_PRIMARY,
                )

        # Update sidebar navigation styling if mapped
        for key, item in getattr(self, "nav_items", {}).items():
            is_active = (key == target)
            bg_col = self.C_SIDEBAR_ACTIVE if is_active else self.C_SIDEBAR_BG
            fg_col = self.C_SIDEBAR_TEXT if is_active else self.C_SIDEBAR_MUTED
            stripe_col = self.C_SIDEBAR_ACCENT if is_active else self.C_SIDEBAR_BG

            item["frame"].configure(bg=bg_col)
            item["glyph"].configure(bg=bg_col, fg=fg_col)
            item["text"].configure(bg=bg_col, fg=fg_col)
            item["stripe"].configure(bg=stripe_col)

        # Update top header title & subtitle
        headers = {
            "overview": (
                "Sequential Annotation Workflow",
                "Step 1: Select your assigned project. Step 2: Complete the 4-step workflow in order.",
            ),
            "batch": (
                "Sequential Annotation Workflow",
                "Step 1: Select your assigned project. Step 2: Complete the 4-step workflow in order.",
            ),
            "projects": (
                "All Assigned Tasks",
                "Full catalog of dataset assignments allocated to your account by the project manager.",
            ),
            "logs": (
                "Activity Logs",
                "Audit trail of downloads, annotations, and NAS synchronization operations.",
            ),
            "settings": (
                "Workstation Settings",
                "Central server authentication and standalone local single-PC configuration.",
            ),
        }
        title, sub = headers.get(target, ("Workstation", ""))
        self.top_title_var.set(title)
        self.top_subtitle_var.set(sub)

        # Raise target view
        if target in self.views:
            self.views[target].tkraise()

        # Trigger project refresh on opening projects view
        if target == "projects":
            self.refresh_assignments()
        elif target == "overview":
            self.central_refresh_status()
            self.refresh_assignments()

    def _create_card(
        self,
        parent: tk.Widget,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        padx: int = 16,
        pady: int = 14,
        highlightbackground: Optional[str] = None,
    ) -> Tuple[tk.Frame, tk.Frame]:
        """Creates a clean, flat card container with 1px border."""
        border_col = highlightbackground or self.C_CARD_BORDER
        card_outer = tk.Frame(
            parent,
            bg=self.C_CARD_BG,
            highlightbackground=border_col,
            highlightthickness=1,
            padx=padx,
            pady=pady,
        )

        if title:
            header_box = tk.Frame(card_outer, bg=self.C_CARD_BG)
            header_box.pack(fill="x", pady=(0, 10))

            tk.Label(
                header_box,
                text=title,
                font=self.font_heading,
                fg=self.C_TEXT_PRIMARY,
                bg=self.C_CARD_BG,
                anchor="w",
            ).pack(side="left")

            if subtitle:
                tk.Label(
                    header_box,
                    text=f"•  {subtitle}",
                    font=self.font_sub,
                    fg=self.C_TEXT_MUTED,
                    bg=self.C_CARD_BG,
                    anchor="w",
                ).pack(side="left", padx=(8, 0))

        content_box = tk.Frame(card_outer, bg=self.C_CARD_BG)
        content_box.pack(fill="both", expand=True)

        card_outer.header_box = header_box if title else None
        card_outer.content_box = content_box

        return card_outer, content_box

    # -------------------------------------------------------------------------
    # 0. SCREEN: DEDICATED OPERATOR LOGIN
    # -------------------------------------------------------------------------
    def _build_screen_login(self) -> None:
        view = tk.Frame(self.views_container, bg=self.C_APP_BG)
        view.grid(row=0, column=0, sticky="nsew")
        self.views["login"] = view

        # Centered frame container
        center_box = tk.Frame(view, bg=self.C_APP_BG)
        center_box.place(relx=0.5, rely=0.5, anchor="center")

        card_outer, card_inner = self._create_card(center_box, padx=32, pady=28)
        card_outer.pack(fill="both", expand=True)

        # Brand header
        header_row = tk.Frame(card_inner, bg=self.C_CARD_BG)
        header_row.pack(fill="x", pady=(0, 6))

        logo_lbl = tk.Label(
            header_row,
            text="◈",
            font=("Helvetica", 16, "bold"),
            fg="#818CF8",
            bg="#1E293B",
            padx=8,
            pady=3,
        )
        logo_lbl.pack(side="left")

        title_box = tk.Frame(header_row, bg=self.C_CARD_BG)
        title_box.pack(side="left", padx=(12, 0))

        tk.Label(
            title_box,
            text="NAS Annotation Workstation",
            font=self.font_title,
            fg=self.C_TEXT_PRIMARY,
            bg=self.C_CARD_BG,
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="Operator Login — Start Your Annotation Shift",
            font=self.font_sub,
            fg=self.C_TEXT_MUTED,
            bg=self.C_CARD_BG,
            anchor="w",
        ).pack(anchor="w")

        # Divider
        tk.Frame(card_inner, bg=self.C_CARD_BORDER, height=1).pack(fill="x", pady=(12, 16))

        # Login Form
        form = tk.Frame(card_inner, bg=self.C_CARD_BG)
        form.pack(fill="x", pady=(0, 10))

        tk.Label(form, text="Username:", font=self.font_body_bold, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).pack(anchor="w", pady=(0, 4))
        self.login_user_entry = ttk.Entry(form, textvariable=self.central_user_var, font=self.font_body, width=32)
        self.login_user_entry.pack(fill="x", pady=(0, 12))
        self.login_user_entry.bind("<KeyRelease>", lambda e: self._save_credentials(self.central_user_var.get(), self.central_pass_var.get()))

        tk.Label(form, text="Password:", font=self.font_body_bold, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).pack(anchor="w", pady=(0, 4))

        pass_row = tk.Frame(form, bg=self.C_CARD_BG)
        pass_row.pack(fill="x", pady=(0, 14))

        self.login_pass_entry = ttk.Entry(pass_row, textvariable=self.central_pass_var, show="*", font=self.font_body)
        self.login_pass_entry.pack(side="left", fill="x", expand=True)
        self.login_pass_entry.bind("<KeyRelease>", lambda e: self._save_credentials(self.central_user_var.get(), self.central_pass_var.get()))

        self.btn_login_toggle_pass = ttk.Button(pass_row, text="👁 Show", width=7, command=self._toggle_login_pass_visibility)
        self.btn_login_toggle_pass.pack(side="left", padx=(6, 0))

        # Error label
        tk.Label(
            card_inner,
            textvariable=self.login_error_var,
            font=self.font_sub,
            fg=self.C_DANGER,
            bg=self.C_CARD_BG,
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # Submit button
        self.login_btn_row = tk.Frame(card_inner, bg=self.C_CARD_BG)
        self.login_btn_row.pack(fill="x")

        self.btn_login_submit = tk.Button(
            self.login_btn_row,
            text="🚀 Start Work / Log In",
            font=self.font_body_bold,
            bg=self.C_PRIMARY,
            fg="#FFFFFF",
            activebackground=self.C_PRIMARY_HOVER,
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=18,
            pady=10,
            cursor="hand2",
            command=self.central_login,
        )
        self.btn_login_submit.pack(fill="x")

        # Bind Enter key
        self.login_user_entry.bind("<Return>", lambda e: self.central_login())
        self.login_pass_entry.bind("<Return>", lambda e: self.central_login())

    def _toggle_login_pass_visibility(self) -> None:
        if self.login_pass_entry.cget("show") == "*":
            self.login_pass_entry.configure(show="")
            self.btn_login_toggle_pass.configure(text="🔒 Hide")
        else:
            self.login_pass_entry.configure(show="*")
            self.btn_login_toggle_pass.configure(text="👁 Show")

    # -------------------------------------------------------------------------
    # 1. SCREEN: SEQUENTIAL ANNOTATION WORKFLOW
    # -------------------------------------------------------------------------
    def _build_screen_overview(self) -> None:
        view = tk.Frame(self.views_container, bg=self.C_APP_BG)
        view.grid(row=0, column=0, sticky="nsew")
        self.views["overview"] = view

        # ---------------------------------------------------------------------
        # 1. TASK SELECTION & METADATA BAR
        # ---------------------------------------------------------------------
        p_outer, p_inner = self._create_card(
            view,
            title="📁 Step 1: Select Assigned Project & Batch",
            subtitle="Choose the task allocated to your account by your supervisor",
            padx=18,
            pady=12,
        )
        p_outer.pack(fill="x", pady=(0, 10))

        sel_row = tk.Frame(p_inner, bg=self.C_CARD_BG)
        sel_row.pack(fill="x", pady=(0, 10))

        tk.Label(
            sel_row,
            text="Assigned Task:",
            font=self.font_body_bold,
            fg=self.C_TEXT_PRIMARY,
            bg=self.C_CARD_BG,
        ).pack(side="left", padx=(0, 10))

        self.assignment_combobox = ttk.Combobox(
            sel_row,
            textvariable=self.assignments_dropdown_var,
            state="readonly",
            font=self.font_body,
            width=55,
        )
        self.assignment_combobox.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.assignment_combobox.bind("<<ComboboxSelected>>", self._on_assignment_combobox_change)

        ttk.Button(
            sel_row,
            text="🔄 Check for New Tasks",
            command=self.refresh_assignments,
        ).pack(side="left")

        # Compact Task Metadata Badges
        p_summary_frame = tk.Frame(p_inner, bg="#F1F5F9", padx=14, pady=10)
        p_summary_frame.pack(fill="x")

        for c_idx in range(4):
            p_summary_frame.columnconfigure(c_idx, weight=1)

        summary_fields = [
            ("PROJECT NAME", self.wf_proj_name_var, self.C_PRIMARY),
            ("ALLOCATED IMAGES", self.wf_alloc_count_var, "#0EA5E9"),
            ("STATUS", self.wf_status_var, self.C_SUCCESS),
            ("TARGET FOLDER", self.wf_folder_var, self.C_TEXT_MUTED),
        ]

        for idx, (label, s_var, col) in enumerate(summary_fields):
            box = tk.Frame(p_summary_frame, bg="#F1F5F9")
            box.grid(row=0, column=idx, sticky="w", padx=8)

            tk.Label(box, text=label, font=("Helvetica", 8, "bold"), fg=self.C_TEXT_MUTED, bg="#F1F5F9").pack(anchor="w")
            tk.Label(box, textvariable=s_var, font=self.font_body_bold, fg=col, bg="#F1F5F9").pack(anchor="w", pady=(1, 0))

        # ---------------------------------------------------------------------
        # 2. SEQUENTIAL 4-STEP PROGRESS INDICATOR TRAIL
        # ---------------------------------------------------------------------
        stepper_bar = tk.Frame(view, bg=self.C_APP_BG)
        stepper_bar.pack(fill="x", pady=(0, 10))

        self.step_labels = []
        step_items = [
            ("1. Download", "📥"),
            ("2. Annotate in Tool", "🎨"),
            ("3. Submit Work", "🚀"),
            ("4. Clean & Finish", "🧹"),
        ]
        for idx, (s_name, s_icon) in enumerate(step_items):
            s_box = tk.Frame(stepper_bar, bg=self.C_APP_BG)
            s_box.pack(side="left", fill="x", expand=True)

            s_lbl = tk.Label(
                s_box,
                text=f"{s_icon} {s_name}",
                font=self.font_body_bold,
                fg=self.C_TEXT_MUTED,
                bg="#F1F5F9",
                padx=14,
                pady=6,
                relief="flat",
            )
            s_lbl.pack(side="left", fill="x", expand=True)
            self.step_labels.append(s_lbl)

            if idx < len(step_items) - 1:
                tk.Label(s_box, text="➔", font=("Helvetica", 11, "bold"), fg=self.C_TEXT_LIGHT, bg=self.C_APP_BG).pack(side="right", padx=6)

        # ---------------------------------------------------------------------
        # 3. THE UNIFIED ACTION STAGE (THE ONLY PRIMARY ACTION CARD)
        # ---------------------------------------------------------------------
        self.action_card_outer, self.action_card_inner = self._create_card(
            view,
            padx=24,
            pady=18,
            highlightbackground="#818CF8",
        )
        self.action_card_outer.pack(fill="x", pady=(0, 10))

        # Step Pill & Headline
        head_row = tk.Frame(self.action_card_inner, bg=self.C_CARD_BG)
        head_row.pack(fill="x", pady=(0, 4))

        tk.Label(
            head_row,
            textvariable=self.hero_tag_var,
            font=("Helvetica", 8, "bold"),
            fg=self.C_PRIMARY,
            bg=self.C_PRIMARY_LIGHT,
            padx=10,
            pady=3,
        ).pack(side="left")

        tk.Label(
            self.action_card_inner,
            textvariable=self.wf_next_title_var,
            font=("Helvetica", 14, "bold"),
            fg=self.C_TEXT_PRIMARY,
            bg=self.C_CARD_BG,
            anchor="w",
        ).pack(anchor="w", pady=(4, 2))

        tk.Label(
            self.action_card_inner,
            textvariable=self.wf_next_desc_var,
            font=self.font_body,
            fg=self.C_TEXT_MUTED,
            bg=self.C_CARD_BG,
            anchor="w",
            wraplength=850,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # Main Tactile Action Button Row
        action_btn_box = tk.Frame(self.action_card_inner, bg=self.C_CARD_BG)
        action_btn_box.pack(anchor="w", fill="x", pady=(2, 6))

        self.btn_main_action = tk.Button(
            action_btn_box,
            textvariable=self.wf_next_action_btn_text,
            font=("Helvetica", 12, "bold"),
            bg=self.C_PRIMARY,
            fg="#FFFFFF",
            activebackground=self.C_PRIMARY_HOVER,
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=24,
            pady=10,
            cursor="hand2",
            command=self.central_fetch,
        )
        self.btn_main_action.pack(side="left", padx=(0, 12))

        # Step 2 Specific Widgets: Progress bar & Secondary "Submit Early" button
        self.step2_widget_frame = tk.Frame(action_btn_box, bg=self.C_CARD_BG)
        # (Packed/unpacked dynamically in _update_workflow_state)

        self.wf_progress_bar = ttk.Progressbar(
            self.step2_widget_frame,
            orient="horizontal",
            mode="determinate",
            length=200,
            style="Horizontal.TProgressbar",
        )
        self.wf_progress_bar.pack(side="left", padx=(0, 10))

        tk.Label(
            self.step2_widget_frame,
            textvariable=self.wf_annotate_count_var,
            font=self.font_body_bold,
            fg=self.C_TEXT_PRIMARY,
            bg=self.C_CARD_BG,
        ).pack(side="left", padx=(0, 12))

        self.btn_secondary_action = tk.Button(
            self.step2_widget_frame,
            text="🚀 Submit Work Now",
            font=self.font_body_bold,
            bg=self.C_SUCCESS,
            fg="#FFFFFF",
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            cursor="hand2",
            command=self.central_sync,
        )
        self.btn_secondary_action.pack(side="left")

        # Redownload / Reset Cache Button
        self.btn_reset_cache = tk.Button(
            action_btn_box,
            text="🔄 Redownload from Scratch",
            font=self.font_caption,
            bg=self.C_SURFACE_ALT,
            fg=self.C_TEXT_MUTED,
            activebackground=self.C_BORDER,
            activeforeground=self.C_TEXT_PRIMARY,
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
            command=self.central_reset_local_cache,
        )
        self.btn_reset_cache.pack(side="right", padx=(10, 0))

        # Action status label
        tk.Label(
            self.action_card_inner,
            textvariable=self.wf_fetch_status_var,
            font=("Helvetica", 9),
            fg=self.C_TEXT_MUTED,
            bg=self.C_CARD_BG,
        ).pack(anchor="w", pady=(4, 0))

        # Compatibility Aliases so all callbacks work unchanged
        self.hero_outer = self.action_card_outer
        self.hero_action_btn = self.btn_main_action
        self.btn_wf_fetch = self.btn_main_action
        self.btn_wf_annotate = self.btn_main_action
        self.btn_wf_sync = self.btn_main_action
        self.btn_wf_clean = self.btn_main_action
        self.c1_outer = self.action_card_outer
        self.c2_outer = self.action_card_outer
        self.c3_outer = self.action_card_outer
        self.c4_outer = self.action_card_outer
        self.c1_badge = tk.Label()
        self.c2_badge = tk.Label()
        self.c3_badge = tk.Label()
        self.c4_badge = tk.Label()

        # ---------------------------------------------------------------------
        # 4. RECENT ACTIVITY CONSOLE (COMPACT MINI LOG)
        # ---------------------------------------------------------------------
        log_card_outer, log_card_inner = self._create_card(
            view,
            title="📋 Workstation Status & Recent Events",
            padx=14,
            pady=8,
        )
        log_card_outer.pack(fill="both", expand=True)

        self.overview_log_text = tk.Text(
            log_card_inner,
            height=4,
            bg="#FFFFFF",
            fg=self.C_TEXT_PRIMARY,
            font=self.font_mono,
            wrap="word",
            relief="flat",
            padx=8,
            pady=6,
        )
        self.overview_log_text.pack(side="left", fill="both", expand=True)

        log_scroll = ttk.Scrollbar(log_card_inner, orient="vertical", command=self.overview_log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.overview_log_text.config(yscrollcommand=log_scroll.set)

    # -------------------------------------------------------------------------
    # 3. SCREEN: ASSIGNED PROJECTS & BATCHES
    # -------------------------------------------------------------------------
    def _build_screen_projects(self) -> None:
        view = tk.Frame(self.views_container, bg=self.C_APP_BG)
        view.grid(row=0, column=0, sticky="nsew")
        self.views["projects"] = view

        # 1. Projects Toolbar
        tb_outer, tb_inner = self._create_card(view, padx=14, pady=10)
        tb_outer.pack(fill="x", pady=(0, 12))

        tk.Label(
            tb_inner,
            text="Search / Filter:",
            font=self.font_body_bold,
            fg=self.C_TEXT_PRIMARY,
            bg=self.C_CARD_BG,
        ).pack(side="left", padx=(0, 8))

        search_entry = ttk.Entry(tb_inner, textvariable=self.projects_search_var, width=32)
        search_entry.pack(side="left", padx=(0, 12))
        search_entry.bind("<KeyRelease>", lambda e: self._filter_projects_tree())

        ttk.Button(
            tb_inner,
            text="⟳ Refresh Assignments",
            command=self.refresh_assignments,
        ).pack(side="left")

        # 2. Table / Treeview Container
        table_outer, table_inner = self._create_card(
            view,
            title="My Assigned Batches",
            subtitle="Batches allocated to current user",
            padx=12,
            pady=12,
        )
        table_outer.pack(fill="both", expand=True, pady=(0, 12))

        columns = ("id", "dataset_id", "scope", "workspace_path", "allocated", "status", "created_at")
        self.projects_tree = ttk.Treeview(
            table_inner,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        col_configs = [
            ("id", "Assignment ID", 110, "center"),
            ("dataset_id", "Dataset ID", 80, "center"),
            ("scope", "Directory Scope", 220, "w"),
            ("workspace_path", "NAS Assigned Path", 280, "w"),
            ("allocated", "Allocated", 80, "center"),
            ("status", "Status", 100, "center"),
            ("created_at", "Created At", 150, "center"),
        ]

        for cid, heading, width, anchor in col_configs:
            self.projects_tree.heading(cid, text=heading)
            self.projects_tree.column(cid, width=width, anchor=anchor)

        self.projects_tree.tag_configure("even", background="#FFFFFF")
        self.projects_tree.tag_configure("odd", background="#F8FAFC")
        self.projects_tree.bind("<<TreeviewSelect>>", self._on_project_selected)

        tree_scroll = ttk.Scrollbar(table_inner, orient="vertical", command=self.projects_tree.yview)
        self.projects_tree.configure(yscrollcommand=tree_scroll.set)

        self.projects_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # 3. Selected Assignment Details Preview
        dt_outer, dt_inner = self._create_card(
            view,
            title="Assignment Details",
            subtitle="Metadata and quick actions for selected batch",
            padx=14,
            pady=10,
        )
        dt_outer.pack(fill="x")

        dt_row = tk.Frame(dt_inner, bg=self.C_CARD_BG)
        dt_row.pack(fill="x")

        tk.Label(
            dt_row,
            textvariable=self.selected_assign_info_var,
            font=self.font_sub,
            fg=self.C_TEXT_PRIMARY,
            bg=self.C_CARD_BG,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        ttk.Button(
            dt_row,
            text="⚡ Work on this in My Work",
            style="Primary.TButton",
            command=self._open_selected_project_in_workflow,
        ).pack(side="right")

    def _open_selected_project_in_workflow(self) -> None:
        sel = self.projects_tree.selection()
        if not sel:
            self.switch_view("overview")
            return
        item = self.projects_tree.item(sel[0])
        vals = item.get("values", [])
        if vals:
            target_id = vals[0]
            for label, a in self.assignment_choice_map.items():
                if a.get("id") == target_id:
                    self.assignments_dropdown_var.set(label)
                    self._on_assignment_combobox_change()
                    break
        self.switch_view("overview")

    def _on_project_selected(self, event=None) -> None:
        sel = self.projects_tree.selection()
        if not sel:
            return
        item = self.projects_tree.item(sel[0])
        vals = item.get("values", [])
        if vals:
            ds = self.datasets_lookup.get(vals[1], {})
            p_name = ds.get("name") or f"Dataset #{vals[1]}"
            p_title = ds.get("title") or ""
            proj_display = f"{p_name} ({p_title})" if p_title else p_name
            info = f"Project: {proj_display} | Assignment #{vals[0]} | Allocated: {vals[4]} images | Status: {vals[5]}"
            self.selected_assign_info_var.set(info)

    def _filter_projects_tree(self) -> None:
        query = self.projects_search_var.get().strip().lower()
        self.projects_tree.delete(*self.projects_tree.get_children())
        for idx, a in enumerate(self.my_assignments_data):
            aid = str(a.get("id", ""))
            scope = str(a.get("directory_scope", "")).lower()
            astatus = str(a.get("status", "")).lower()
            ws_path = str(a.get("workspace_path", "")).lower()
            if not query or query in aid or query in scope or query in astatus or query in ws_path:
                tag = "even" if idx % 2 == 0 else "odd"
                self.projects_tree.insert(
                    "",
                    "end",
                    values=(
                        a.get("id"),
                        a.get("dataset_id"),
                        a.get("directory_scope") or "(root)",
                        a.get("workspace_path") or "(pending staging)",
                        a.get("allocated_count", a.get("requested_count")),
                        a.get("status"),
                        str(a.get("created_at", ""))[:19],
                    ),
                    tags=(tag,),
                )

    def _on_assignment_combobox_change(self, event=None) -> None:
        sel_label = self.assignments_dropdown_var.get()
        a = self.assignment_choice_map.get(sel_label)
        if not a:
            return
        self.selected_assignment = a
        aid = a.get("id")
        ds = self.datasets_lookup.get(a.get("dataset_id"), {})
        p_name = ds.get("name") or f"Dataset #{a.get('dataset_id')}"
        p_title = ds.get("title") or ""
        cnt = a.get("allocated_count") or a.get("requested_count") or 0
        st = a.get("status") or "READY"
        raw_path = a.get("workspace_path") or ""
        clean_path = raw_path.replace("annotation_nas:", "").replace("ai_data_collection/test/", "")

        self.wf_proj_name_var.set(f"{p_name} ({p_title})" if p_title else p_name)
        self.wf_alloc_count_var.set(f"{cnt} images")
        self.wf_status_var.set(st)
        self.wf_folder_var.set(clean_path or "(Staging on NAS...)")

        self.central_refresh_status()

    def refresh_assignments(self) -> None:
        if not self.agent or not self.agent.client.token:
            return

        def run():
            try:
                assignments = self.agent.client.get_my_assignments()
                datasets = self.agent.client.get_datasets()
                self.datasets_lookup = {d["id"]: d for d in datasets}
                self.my_assignments_data = assignments

                choices = []
                choice_map = {}
                for a in assignments:
                    aid = a.get("id")
                    ds = self.datasets_lookup.get(a.get("dataset_id"), {})
                    p_name = ds.get("name") or f"Dataset #{a.get('dataset_id')}"
                    p_title = ds.get("title") or ""
                    cnt = a.get("allocated_count") or a.get("requested_count") or 0
                    st = a.get("status") or "READY"
                    label = f"Assignment #{aid}: {p_name}" + (f" ({p_title})" if p_title else "") + f" — {cnt} Images [{st}]"
                    choices.append(label)
                    choice_map[label] = a

                self.assignment_choice_map = choice_map

                def update():
                    self._filter_projects_tree()
                    if choices:
                        if hasattr(self, "assignment_combobox"):
                            self.assignment_combobox["values"] = choices
                        curr_label = self.assignments_dropdown_var.get()
                        if curr_label not in choice_map:
                            selected_label = choices[0]
                            for c in choices:
                                if "[READY]" in c or "[IN_PROGRESS]" in c:
                                    selected_label = c
                                    break
                            self.assignments_dropdown_var.set(selected_label)
                            self._on_assignment_combobox_change()
                        else:
                            self._on_assignment_combobox_change()
                        self.selected_assign_info_var.set(f"Loaded {len(assignments)} assignments from Central Server.")
                    else:
                        if hasattr(self, "assignment_combobox"):
                            self.assignment_combobox["values"] = ["No assignments currently allocated"]
                        self.assignments_dropdown_var.set("No assignments currently allocated")
                        self.selected_assignment = None
                        self.wf_proj_name_var.set("None")
                        self.wf_alloc_count_var.set("0 images")
                        self.wf_status_var.set("No task")
                        self.wf_folder_var.set("None")
                        self.selected_assign_info_var.set("No assignments currently allocated to your account.")
                        self.central_refresh_status()

                self.safe_after(0, update)
            except Exception as exc:
                err_msg = str(exc)
                self.safe_after(0, lambda msg=err_msg: self.selected_assign_info_var.set(f"Could not load assignments: {msg}"))

        threading.Thread(target=run, daemon=True).start()

    # -------------------------------------------------------------------------
    # 4. SCREEN: ACTIVITY LOGS
    # -------------------------------------------------------------------------
    def _build_screen_logs(self) -> None:
        view = tk.Frame(self.views_container, bg=self.C_APP_BG)
        view.grid(row=0, column=0, sticky="nsew")
        self.views["logs"] = view

        # 1. Logs Toolbar
        tb_outer, tb_inner = self._create_card(view, padx=14, pady=10)
        tb_outer.pack(fill="x", pady=(0, 12))

        tk.Label(
            tb_inner,
            text="Activity & Event Audit Stream",
            font=self.font_heading,
            fg=self.C_TEXT_PRIMARY,
            bg=self.C_CARD_BG,
        ).pack(side="left")

        actions_box = tk.Frame(tb_inner, bg=self.C_CARD_BG)
        actions_box.pack(side="right")

        tk.Checkbutton(
            actions_box,
            text="Auto-scroll",
            variable=self.autoscroll_var,
            font=self.font_sub,
            bg=self.C_CARD_BG,
            fg=self.C_TEXT_PRIMARY,
            activebackground=self.C_CARD_BG,
        ).pack(side="left", padx=(0, 10))

        ttk.Button(actions_box, text="📋 Copy Log", command=self.copy_logs).pack(side="left", padx=(0, 6))
        ttk.Button(actions_box, text="🗑️ Clear Log", command=self.clear_logs).pack(side="left")

        # 2. Log Text View
        log_outer, log_inner = self._create_card(view, padx=8, pady=8)
        log_outer.pack(fill="both", expand=True)

        self.central_log_text = tk.Text(
            log_inner,
            bg="#FFFFFF",
            fg=self.C_TEXT_PRIMARY,
            font=self.font_mono,
            wrap="word",
            relief="flat",
            padx=12,
            pady=10,
        )
        self.central_log_text.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(log_inner, orient="vertical", command=self.central_log_text.yview)
        scroll.pack(side="right", fill="y")
        self.central_log_text.config(yscrollcommand=scroll.set)

        # Configure color tags
        self.central_log_text.tag_configure("stamp", foreground=self.C_TEXT_LIGHT)
        self.central_log_text.tag_configure("info", foreground="#2563EB")
        self.central_log_text.tag_configure("success", foreground=self.C_SUCCESS)
        self.central_log_text.tag_configure("warning", foreground=self.C_WARNING)
        self.central_log_text.tag_configure("error", foreground=self.C_DANGER)

    def central_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        tag = "info"
        if "✅" in text or "success" in text.lower() or "complete" in text.lower() or "🎉" in text:
            tag = "success"
        elif "❌" in text or "fail" in text.lower() or "error" in text.lower():
            tag = "error"
        elif "⚠️" in text or "warning" in text.lower():
            tag = "warning"

        if hasattr(self, "central_log_text") and self.central_log_text.winfo_exists():
            self.central_log_text.insert(tk.END, f"[{stamp}] ", "stamp")
            self.central_log_text.insert(tk.END, f"{text}\n", tag)
            if self.autoscroll_var.get():
                self.central_log_text.see(tk.END)

        if hasattr(self, "overview_log_text") and self.overview_log_text.winfo_exists():
            self.overview_log_text.insert(tk.END, f"[{stamp}] {text}\n")
            self.overview_log_text.see(tk.END)

        self.update_idletasks()

        # Mirror to legacy log if exists
        self.log(text)

    def clear_logs(self) -> None:
        self.central_log_text.delete("1.0", tk.END)
        self.central_log("Logs cleared.")

    def copy_logs(self) -> None:
        content = self.central_log_text.get("1.0", tk.END).strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            messagebox.showinfo("Clipboard", "Activity logs copied to clipboard.")

    # -------------------------------------------------------------------------
    # 5. SCREEN: SETTINGS & CONFIGURATION
    # -------------------------------------------------------------------------
    def _build_screen_settings(self) -> None:
        view = tk.Frame(self.views_container, bg=self.C_APP_BG)
        view.grid(row=0, column=0, sticky="nsew")
        self.views["settings"] = view

        # Mode Selector Tabs
        selector_outer, selector_inner = self._create_card(view, padx=10, pady=8)
        selector_outer.pack(fill="x", pady=(0, 12))

        self.settings_mode_var = tk.StringVar(value="central")

        btn_central_mode = tk.Radiobutton(
            selector_inner,
            text="Central Production Mode (Recommended)",
            variable=self.settings_mode_var,
            value="central",
            command=self._toggle_settings_subview,
            font=self.font_body_bold,
            bg=self.C_CARD_BG,
            fg=self.C_TEXT_PRIMARY,
            activebackground=self.C_CARD_BG,
        )
        btn_central_mode.pack(side="left", padx=(10, 20))

        btn_legacy_mode = tk.Radiobutton(
            selector_inner,
            text="Standalone Legacy Mode (Single-PC POC)",
            variable=self.settings_mode_var,
            value="legacy",
            command=self._toggle_settings_subview,
            font=self.font_body_bold,
            bg=self.C_CARD_BG,
            fg=self.C_TEXT_PRIMARY,
            activebackground=self.C_CARD_BG,
        )
        btn_legacy_mode.pack(side="left")

        # Container for Settings Subviews
        self.settings_sub_container = tk.Frame(view, bg=self.C_APP_BG)
        self.settings_sub_container.pack(fill="both", expand=True)
        self.settings_sub_container.rowconfigure(0, weight=1)
        self.settings_sub_container.columnconfigure(0, weight=1)

        self.sub_settings_central = tk.Frame(self.settings_sub_container, bg=self.C_APP_BG)
        self.sub_settings_central.grid(row=0, column=0, sticky="nsew")

        self.sub_settings_legacy = tk.Frame(self.settings_sub_container, bg=self.C_APP_BG)
        self.sub_settings_legacy.grid(row=0, column=0, sticky="nsew")

        # Build Subviews
        self._build_settings_central(self.sub_settings_central)
        self._build_settings_legacy(self.sub_settings_legacy)

        self.sub_settings_central.tkraise()

    def _toggle_settings_subview(self) -> None:
        if self.settings_mode_var.get() == "central":
            self.sub_settings_central.tkraise()
        else:
            self.sub_settings_legacy.tkraise()

    def _build_settings_central(self, parent: tk.Frame) -> None:
        # Central Server Authentication Card
        auth_outer, auth_inner = self._create_card(
            parent,
            title="Central Server Authentication",
            subtitle="Connect to multi-computer controller & assigner service",
        )
        auth_outer.pack(fill="x", pady=(0, 12))

        form_grid = tk.Frame(auth_inner, bg=self.C_CARD_BG)
        form_grid.pack(fill="x", pady=(0, 10))
        form_grid.columnconfigure(1, weight=1)

        tk.Label(form_grid, text="Server URL:", font=self.font_body_bold, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(form_grid, textvariable=self.central_url_var).grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=6)

        tk.Label(form_grid, text="Username:", font=self.font_body_bold, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(form_grid, textvariable=self.central_user_var).grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=6)

        tk.Label(form_grid, text="Password:", font=self.font_body_bold, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).grid(row=2, column=0, sticky="w", pady=6)
        pass_row = tk.Frame(form_grid, bg=self.C_CARD_BG)
        pass_row.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=6)
        pass_row.columnconfigure(0, weight=1)

        self.central_pass_entry = ttk.Entry(pass_row, textvariable=self.central_pass_var, show="*")
        self.central_pass_entry.grid(row=0, column=0, sticky="ew")

        self.btn_toggle_pass = ttk.Button(pass_row, text="👁 Show", width=8, command=self.toggle_password_visibility)
        self.btn_toggle_pass.grid(row=0, column=1, padx=(6, 0))

        # Auth Buttons row
        btn_row = tk.Frame(auth_inner, bg=self.C_CARD_BG)
        btn_row.pack(fill="x", pady=(8, 4))

        self.btn_login = ttk.Button(
            btn_row,
            text="🔑 Log In & Authenticate",
            style="Primary.TButton",
            command=self.central_login,
        )
        self.btn_login.pack(side="left", padx=(0, 10))

        self.btn_logout = ttk.Button(
            btn_row,
            text="Log Out",
            command=self.central_logout,
        )
        self.btn_logout.pack(side="left")

        # Connection status label
        tk.Label(
            auth_inner,
            textvariable=self.central_auth_status_var,
            font=self.font_body_bold,
            fg=self.C_TEXT_PRIMARY,
            bg=self.C_CARD_BG,
            anchor="w",
        ).pack(anchor="w", pady=(10, 0))

        # Workstation Workspace Path Card
        path_outer, path_inner = self._create_card(
            parent,
            title="Local Directory Storage",
            subtitle="High-speed staging location on local disk",
        )
        path_outer.pack(fill="x")

        root_path = Path.home() / "nas_annotation_workspace"
        path_info = [
            ("Root Directory", str(root_path)),
            ("Active Batch (current)", str(root_path / "current")),
            ("Local Backups", str(root_path / "backups")),
            ("Token & Cache State", str(root_path / "state" / "agent_cache.db")),
        ]
        for key, val in path_info:
            r = tk.Frame(path_inner, bg=self.C_CARD_BG)
            r.pack(fill="x", pady=3)
            tk.Label(r, text=f"{key}:", font=self.font_body_bold, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG, width=22, anchor="w").pack(side="left")
            tk.Label(r, text=val, font=self.font_sub, fg=self.C_TEXT_MUTED, bg=self.C_CARD_BG, anchor="w").pack(side="left", fill="x", expand=True)

    def toggle_password_visibility(self) -> None:
        self.password_visible = not self.password_visible
        if self.password_visible:
            self.central_pass_entry.configure(show="")
            self.btn_toggle_pass.configure(text="🔒 Hide")
        else:
            self.central_pass_entry.configure(show="*")
            self.btn_toggle_pass.configure(text="👁 Show")

    def _build_settings_legacy(self, parent: tk.Frame) -> None:
        # Legacy Single-PC Configuration Form
        config_outer, config_inner = self._create_card(
            parent,
            title="Project Configuration (Standalone Legacy Mode)",
            subtitle="Local config.env settings without Central Server",
        )
        config_outer.pack(fill="x", pady=(0, 12))

        form = tk.Frame(config_inner, bg=self.C_CARD_BG)
        form.pack(fill="x", pady=(0, 10))
        form.columnconfigure(1, weight=1)

        fields = [
            ("Remote source", "REMOTE"),
            ("Dataset path", "DATASET"),
            ("Local destination", "ROOT"),
            ("Batch size", "BATCH_SIZE"),
            ("Bandwidth", "BANDWIDTH"),
            ("Transfer concurrency", "TRANSFERS"),
            ("Retries", "RETRIES"),
            ("Config file", "CONFIG_PATH"),
        ]
        self.config_vars = {}
        for index, (label, key) in enumerate(fields):
            tk.Label(form, text=f"{label}:", font=self.font_body, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).grid(
                row=index, column=0, sticky="w", pady=3
            )
            entry = ttk.Entry(form)
            entry.grid(row=index, column=1, sticky="ew", padx=(10, 0), pady=3)
            self.config_vars[key] = entry

        # Save & Open Config buttons
        actions = tk.Frame(config_inner, bg=self.C_CARD_BG)
        actions.pack(fill="x", pady=(4, 0))
        ttk.Button(actions, text="Save Configuration", style="Primary.TButton", command=self.save_configuration).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Open config file", command=self.open_config_file).pack(side="left")

        # Legacy Batch Status Card
        status_outer, status_inner = self._create_card(
            parent,
            title="NAS & Legacy Batch State",
            subtitle="Single-PC scripts state",
        )
        status_outer.pack(fill="x", pady=(0, 12))

        s_grid = tk.Frame(status_inner, bg=self.C_CARD_BG)
        s_grid.pack(fill="x", pady=(0, 8))
        s_grid.columnconfigure(1, weight=1)

        tk.Label(s_grid, text="Status:", font=self.font_body_bold, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).grid(row=0, column=0, sticky="w", pady=2)
        tk.Label(s_grid, textvariable=self.status_var, font=self.font_body, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).grid(row=0, column=1, sticky="w", padx=(10, 0), pady=2)

        tk.Label(s_grid, text="NAS Connection:", font=self.font_body_bold, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).grid(row=1, column=0, sticky="w", pady=2)
        tk.Label(s_grid, textvariable=self.nas_var, font=self.font_body, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).grid(row=1, column=1, sticky="w", padx=(10, 0), pady=2)

        tk.Label(s_grid, text="Progress:", font=self.font_body_bold, fg=self.C_TEXT_PRIMARY, bg=self.C_CARD_BG).grid(row=2, column=0, sticky="w", pady=2)
        tk.Label(s_grid, textvariable=self.progress_var, font=self.font_sub, fg=self.C_TEXT_MUTED, bg=self.C_CARD_BG).grid(row=2, column=1, sticky="w", padx=(10, 0), pady=2)

        # Legacy Action Buttons
        btn_outer, btn_inner = self._create_card(parent, title="Legacy Operations")
        btn_outer.pack(fill="x", pady=(0, 12))

        btn_row = tk.Frame(btn_inner, bg=self.C_CARD_BG)
        btn_row.pack(fill="x")
        for i in range(5):
            btn_row.columnconfigure(i, weight=1)

        self.action_buttons = {
            "download": ttk.Button(btn_row, text="Download Images", command=self.download_images),
            "upload": ttk.Button(btn_row, text="Upload Images & Labels", command=self.upload_images),
            "annotate": ttk.Button(btn_row, text="Start Annotation", command=self.start_annotation),
            "finish": ttk.Button(btn_row, text="Finish Batch", command=self.finish_batch),
            "project": ttk.Button(btn_row, text="Complete Project", command=self.complete_project),
        }
        for idx, (name, button) in enumerate(self.action_buttons.items()):
            button.grid(row=0, column=idx, sticky="ew", padx=4)

        # Legacy Log Text widget
        self.log_widget = tk.Text(parent, height=6, bg="#FFFFFF", fg=self.C_TEXT_PRIMARY, font=self.font_mono)

    # -------------------------------------------------------------------------
    # CENTRAL PRODUCTION CONTROLLER & AGENT INTERACTIONS
    # -------------------------------------------------------------------------
    def initial_check(self) -> None:
        """Determines if the workstation is authenticated or should present the login screen."""
        if self.agent and self.agent.client.token:
            username = getattr(self.agent, "saved_username", None) or self.central_user_var.get().strip() or "annotator1"
            self.central_user_var.set(username)
            self.is_logged_in = True
            self.user_badge_var.set(f"👤 {username}")
            self.sidebar_user_lbl.configure(text=username)
            self.sidebar_status_lbl.configure(text="● Online", fg="#22C55E")
            self.connection_pill_var.set(f"🟢 Connected ({username})")
            self.switch_view("overview")
            self.refresh_assignments()
            self.central_refresh_status()
            threading.Thread(target=self.check_nas_connection, daemon=True).start()
        else:
            self.is_logged_in = False
            self.user_badge_var.set("👤 Not Logged In")
            self.switch_view("login")

    def central_login(self) -> None:
        if not self.agent:
            self._init_agent()
        server_url = self.central_url_var.get().strip()
        username = self.central_user_var.get().strip()
        password = self.central_pass_var.get().strip()

        if not server_url:
            self.login_error_var.set("Server URL is missing! Set SERVER_URL in .env or enter it above.")
            return
        if not username or not password:
            self.login_error_var.set("Please enter both Username and Password.")
            return

        if hasattr(self, "btn_login_submit"):
            self.btn_login_submit.configure(state="disabled")
        if hasattr(self, "btn_login"):
            self.btn_login.configure(state="disabled")
        self.login_error_var.set("Connecting and authenticating...")
        self.central_auth_status_var.set("Connecting and authenticating...")
        self.connection_pill_var.set("🟡 Connecting...")

        def run():
            try:
                self.agent.server_url = server_url
                self.agent.client.base_url = server_url
                self.agent.login(username, password)
                self._save_credentials(username, password)
                self.is_logged_in = True
                self.central_log(f"✅ Successfully logged in as '{username}' to {server_url}")

                def on_success():
                    self.login_error_var.set("")
                    self.user_badge_var.set(f"👤 {username}")
                    self.sidebar_user_lbl.configure(text=username)
                    self.sidebar_status_lbl.configure(text="● Online", fg="#22C55E")
                    self.connection_pill_var.set(f"🟢 Connected ({username})")
                    self.central_auth_status_var.set(f"🟢 Connected as '{username}' to {server_url}")
                    self.switch_view("overview")
                    self.refresh_assignments()
                    self.central_refresh_status()
                    threading.Thread(target=self.check_nas_connection, daemon=True).start()

                self.safe_after(0, on_success)
            except Exception as exc:
                err_msg = str(exc)
                self.central_log(f"❌ Login failed: {err_msg}")
                self.safe_after(0, lambda msg=err_msg: self.login_error_var.set(f"❌ Login failed: {msg}"))
                self.safe_after(0, lambda msg=err_msg: self.central_auth_status_var.set(f"🔴 Login failed: {msg}"))
                self.safe_after(0, lambda: self.connection_pill_var.set("🔴 Disconnected"))
            finally:
                def enable_btn():
                    if hasattr(self, "btn_login_submit"):
                        self.btn_login_submit.configure(state="normal")
                    if hasattr(self, "btn_login"):
                        self.btn_login.configure(state="normal")
                self.safe_after(0, enable_btn)

        threading.Thread(target=run, daemon=True).start()

    def central_logout(self) -> None:
        if self.agent:
            self.agent.client.token = None
            if self.agent.token_file.exists():
                self.agent.token_file.unlink(missing_ok=True)
        self.is_logged_in = False
        self.selected_assignment = None
        self.assignment_choice_map = {}
        self.assignments_dropdown_var.set("")
        self.user_badge_var.set("👤 Not Logged In")
        self.central_auth_status_var.set("⚪ Logged out")
        self.connection_pill_var.set("⚪ Not Logged In")
        self.sidebar_user_lbl.configure(text="Not Logged In")
        self.sidebar_status_lbl.configure(text="○ Offline", fg="#94A3B8")
        self.login_error_var.set("")
        self.switch_view("login")
        self.central_log("Logged out.")

    def central_refresh_status(self) -> None:
        if not self.agent or not self.agent.client.token:
            self.central_auth_status_var.set("⚪ Not logged in.")
            self.connection_pill_var.set("⚪ Not Logged In")
            self.sidebar_user_lbl.configure(text="Not Logged In")
            self.sidebar_status_lbl.configure(text="○ Offline", fg="#94A3B8")
            self.is_logged_in = False
            self.switch_view("login")
            return

        username = self.central_user_var.get().strip()

        def run():
            try:
                active = self.selected_assignment or self.agent.get_active_assignment()

                # Local workspace file count (case-insensitive & recursive)
                curr_dir = Path(self.agent.current_dir)
                img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
                total_imgs = 0
                total_jsons = 0
                if curr_dir.exists():
                    for f in curr_dir.rglob("*"):
                        if f.is_file():
                            suf = f.suffix.lower()
                            if suf in img_exts:
                                total_imgs += 1
                            elif suf == ".json":
                                total_jsons += 1

                if active:
                    aid = active.get("id")
                    count = active.get("allocated_count", active.get("requested_count", 0))
                    status_text = active.get("status", "READY")
                    raw_nas_path = active.get("workspace_path") or ""
                    nas_path = raw_nas_path.replace("annotation_nas:", "").replace("ai_data_collection/test/", "")
                    assign_summary = f"Assignment #{aid} ({status_text}) — {count} images"

                    # Query local database cache for submitted items count
                    submitted_in_db = 0
                    if getattr(self, "agent", None) and aid:
                        try:
                            summary = self.agent.cache.get_assignment_status_summary(aid)
                            submitted_in_db = summary.get("SUBMITTED", 0)
                        except Exception:
                            pass
                else:
                    aid = None
                    count = 0
                    status_text = "NONE"
                    nas_path = ""
                    assign_summary = "No assignment selected or loaded."
                    submitted_in_db = 0

                # Progress percentage based on allocated count and all completed images
                target_count = count if count > 0 else (total_imgs + submitted_in_db)
                total_completed = submitted_in_db + total_jsons
                pct = (total_completed / target_count * 100) if target_count > 0 else 0

                def update_ui():
                    self.central_auth_status_var.set(f"🟢 Connected as '{username}' to {self.agent.server_url}")
                    self.connection_pill_var.set(f"🟢 Connected ({username})")
                    if hasattr(self, "conn_pill"):
                        self.conn_pill.configure(bg=self.C_SUCCESS_LIGHT, fg=self.C_SUCCESS_TEXT)
                    self.sidebar_user_lbl.configure(text=username)
                    self.sidebar_status_lbl.configure(text="● Online", fg="#22C55E")

                    # Sequential workflow counts
                    self.wf_workspace_var.set(f"{total_imgs} images in local batch | {total_jsons} labeled | {submitted_in_db} submitted to server")
                    self.wf_annotate_count_var.set(f"{total_completed} / {target_count} images completed ({pct:.0f}%)")
                    if hasattr(self, "wf_progress_bar"):
                        self.wf_progress_bar.configure(value=pct)

                    is_synced = self.last_sync_success
                    self._update_workflow_state(
                        aid,
                        count,
                        total_imgs,
                        total_jsons,
                        is_synced=is_synced,
                        status_text=status_text,
                        nas_path=nas_path,
                        submitted_in_db=submitted_in_db,
                    )

                self.safe_after(0, update_ui)
            except Exception as exc:
                err_msg = str(exc)
                self.safe_after(0, lambda msg=err_msg: self.central_auth_status_var.set(f"🟡 Connection issue: {msg}"))
                self.safe_after(0, lambda: self.connection_pill_var.set("🟡 Offline / Reconnecting"))
                if hasattr(self, "conn_pill"):
                    self.safe_after(0, lambda: self.conn_pill.configure(bg=self.C_WARNING_LIGHT, fg=self.C_WARNING_TEXT))

        threading.Thread(target=run, daemon=True).start()

    def check_nas_connection(self, notify_gui: bool = True) -> bool:
        """Checks NAS connectivity via the central agent and updates the top bar pill and alert banner."""
        if not self.agent or not self.agent.client.token:
            return True
        try:
            res = self.agent.get_nas_status()
            connected = bool(res.get("connected", False))
            error_msg = res.get("error", "")
            self.is_nas_connected = connected

            def update_ui():
                if connected:
                    self.nas_pill_var.set("🟢 NAS: Connected")
                    if hasattr(self, "nas_pill"):
                        self.nas_pill.configure(
                            fg=self.C_SUCCESS_TEXT,
                            bg=self.C_SUCCESS_LIGHT,
                        )
                    if hasattr(self, "nas_alert_frame") and self.nas_alert_frame.winfo_ismapped():
                        self.nas_alert_frame.pack_forget()
                else:
                    self.nas_pill_var.set("🔴 NAS: Disconnected")
                    if hasattr(self, "nas_pill"):
                        self.nas_pill.configure(
                            fg=self.C_DANGER,
                            bg=self.C_DANGER_LIGHT,
                        )
                    err_hint = f" ({error_msg})" if error_msg else ""
                    self.nas_alert_var.set(
                        f"Cannot reach NAS remote storage.{err_hint} "
                        "Downloading images and submitting annotations are temporarily paused. Please check your network connection."
                    )
                    if hasattr(self, "nas_alert_frame") and not self.nas_alert_frame.winfo_ismapped():
                        if hasattr(self, "views_container"):
                            self.nas_alert_frame.pack(fill="x", padx=20, pady=(10, 0), before=self.views_container)

            self.safe_after(0, update_ui)
            return connected
        except Exception as exc:
            self.is_nas_connected = False
            def update_err():
                self.nas_pill_var.set("🔴 NAS: Unreachable")
                if hasattr(self, "nas_pill"):
                    self.nas_pill.configure(
                        fg=self.C_DANGER,
                        bg=self.C_DANGER_LIGHT,
                    )
                self.nas_alert_var.set(f"Cannot reach NAS storage: {exc}")
                if hasattr(self, "nas_alert_frame") and not self.nas_alert_frame.winfo_ismapped():
                    if hasattr(self, "views_container"):
                        self.nas_alert_frame.pack(fill="x", padx=20, pady=(10, 0), before=self.views_container)
            self.safe_after(0, update_err)
            return False

    def _update_workflow_state(
        self,
        aid: Optional[int],
        count: int,
        total_imgs: int,
        total_jsons: int,
        is_synced: bool = False,
        status_text: str = "READY",
        nas_path: str = "",
        submitted_in_db: int = 0,
    ) -> None:
        """Determines the exact next action for non-technical annotators and highlights it on the unified action stage."""
        # Reset all 4 stepper labels to neutral
        for idx, lbl in enumerate(self.step_labels):
            lbl.configure(fg=self.C_TEXT_MUTED, bg="#F1F5F9")

        # Hide step 2 widget frame by default
        if self.__dict__.get("step2_widget_frame") is not None:
            self.step2_widget_frame.pack_forget()

        if not aid:
            self.hero_tag_var.set("WAITING FOR ASSIGNMENT")
            self.wf_next_title_var.set("No Assignment Selected")
            self.wf_next_desc_var.set("You are connected to the central server. Please select an assigned project from the dropdown above or click 'Check for New Tasks'.")
            self.wf_next_action_btn_text.set("⟳ Check for New Tasks")
            self.btn_main_action.configure(command=self.refresh_assignments, state="normal", bg=self.C_PRIMARY)
            if self.__dict__.get("action_card_outer") is not None:
                self.action_card_outer.configure(highlightbackground=self.C_PRIMARY)
            self.wf_fetch_status_var.set("No task selected")
            self.wf_annotate_status_var.set("Waiting for task")
            self.wf_sync_status_var.set("Waiting for task")
            self.wf_clean_status_var.set("Waiting for task")
            self.current_workflow_step = 1
            return

        if status_text == "PREPARING":
            self.hero_tag_var.set("STAGING ON NAS")
            self.wf_next_title_var.set(f"Staging Batch Images on NAS ({count} Images)")
            self.wf_next_desc_var.set(
                f"Your supervisor allocated {count} images. The server is preparing your directory on the NAS ({nas_path}). "
                f"Please wait a few moments — click check below to refresh."
            )
            self.wf_next_action_btn_text.set("⟳ Check Staging Status")
            self.btn_main_action.configure(command=self.refresh_assignments, state="normal", bg=self.C_WARNING)
            if self.__dict__.get("action_card_outer") is not None:
                self.action_card_outer.configure(highlightbackground=self.C_WARNING)
            self.wf_fetch_status_var.set("⏳ Staging on NAS in progress...")
            self.step_labels[0].configure(text="⏳ 1. Staging...", fg="#FFFFFF", bg=self.C_WARNING)
            self.current_workflow_step = 1
            return

        # Normal Ready or In Progress
        if total_imgs == 0:
            if submitted_in_db >= count and count > 0:
                # Entire assignment completed!
                self.current_workflow_step = 4
                self.step_labels[0].configure(text="✓ 1. Downloaded", fg="#15803D", bg="#DCFCE7")
                self.step_labels[1].configure(text="✓ 2. All Labeled", fg="#15803D", bg="#DCFCE7")
                self.step_labels[2].configure(text="✓ 3. Saved to NAS", fg="#15803D", bg="#DCFCE7")
                self.step_labels[3].configure(text="● 4. Finished (100%)", fg="#FFFFFF", bg=self.C_SUCCESS)

                if self.__dict__.get("action_card_outer") is not None:
                    self.action_card_outer.configure(highlightbackground=self.C_SUCCESS)
                self.hero_tag_var.set("ALL BATCHES COMPLETE — 100% DONE")
                self.wf_next_title_var.set(f"🎉 Assignment #{aid} 100% Finished ({count}/{count} Completed)")
                self.wf_next_desc_var.set(f"All {count} images in this assignment are fully completed, verified, and saved to NAS! You can choose another assignment above.")
                self.wf_next_action_btn_text.set("✓ All Batches Finished")
                self.btn_main_action.configure(state="disabled", bg=self.C_SUCCESS)
                self.wf_fetch_status_var.set(f"🎉 All {count} images in this assignment are complete!")
                return

            elif submitted_in_db > 0 and submitted_in_db < count:
                # Ready for Next Batch
                rem_in_assign = count - submitted_in_db
                ag = self.__dict__.get("agent")
                batch_limit = getattr(ag, "batch_size", 2000) or 2000
                next_batch_size = min(batch_limit, rem_in_assign)

                self.current_workflow_step = 1
                self.step_labels[0].configure(text=f"● 1. Next Batch ({next_batch_size})", fg="#FFFFFF", bg=self.C_PRIMARY)

                if self.__dict__.get("action_card_outer") is not None:
                    self.action_card_outer.configure(highlightbackground=self.C_PRIMARY)
                self.hero_tag_var.set("STEP 1 OF 4 — DOWNLOAD NEXT BATCH")
                self.wf_next_title_var.set(f"Step 1: Download Next Batch ({next_batch_size} of {rem_in_assign} Remaining)")
                self.wf_next_desc_var.set(f"You completed {submitted_in_db} / {count} images so far! Click below to download the next batch of {next_batch_size} images to your computer.")
                self.wf_next_action_btn_text.set(f"📥 1. Download Next Batch ({next_batch_size})")
                self.btn_main_action.configure(command=self.central_fetch, state="normal", bg=self.C_PRIMARY)
                self.wf_fetch_status_var.set(f"⏳ Ready to download next {next_batch_size} images ({submitted_in_db}/{count} completed)")
                return

            else:
                # Step 1: First Batch Download
                ag = self.__dict__.get("agent")
                batch_limit = getattr(ag, "batch_size", 2000) or 2000
                first_batch_size = min(batch_limit, count) if count > 0 else count

                self.current_workflow_step = 1
                self.step_labels[0].configure(text="● 1. Download", fg="#FFFFFF", bg=self.C_PRIMARY)

                if self.__dict__.get("action_card_outer") is not None:
                    self.action_card_outer.configure(highlightbackground=self.C_PRIMARY)
                self.hero_tag_var.set("STEP 1 OF 4 — START HERE")
                self.wf_next_title_var.set(f"Step 1: Download Assigned Images ({first_batch_size} of {count} Allocated)")
                self.wf_next_desc_var.set("Click the button below to download your assigned images from NAS storage directly to your computer's SSD.")
                self.wf_next_action_btn_text.set(f"📥 1. Download Assigned Images ({first_batch_size})")
                self.btn_main_action.configure(command=self.central_fetch, state="normal", bg=self.C_PRIMARY)
                self.wf_fetch_status_var.set(f"⏳ Ready to download {first_batch_size} images from NAS")
                return

        elif total_jsons < total_imgs:
            # Step 2: Annotate
            self.current_workflow_step = 2
            pct = (total_jsons / total_imgs * 100) if total_imgs > 0 else 0
            self.step_labels[0].configure(text=f"✓ 1. Downloaded ({total_imgs})", fg="#15803D", bg="#DCFCE7")
            self.step_labels[1].configure(text=f"● 2. Annotating ({pct:.0f}%)", fg="#FFFFFF", bg=self.C_PRIMARY)

            if self.__dict__.get("action_card_outer") is not None:
                self.action_card_outer.configure(highlightbackground=self.C_PRIMARY)
            self.hero_tag_var.set("STEP 2 OF 4 — DRAW LABELS IN XANYLABELING")
            self.wf_next_title_var.set(f"Step 2: Label in XAnyLabeling ({total_jsons}/{total_imgs} Labeled — {pct:.0f}%)")
            self.wf_next_desc_var.set("Click '🎨 2. Open XAnyLabeling Tool' to launch the annotation software. Draw labels and press Ctrl+S in the tool to save. Progress auto-detects in real-time.")
            self.wf_next_action_btn_text.set("🎨 2. Open XAnyLabeling Tool")
            self.btn_main_action.configure(command=self.central_launch_xany, state="normal", bg=self.C_PRIMARY)

            if self.__dict__.get("step2_widget_frame") is not None:
                self.step2_widget_frame.pack(side="left")

            rem = total_imgs - total_jsons
            self.wf_fetch_status_var.set(f"🎨 {total_jsons} / {total_imgs} images labeled ({rem} remaining in current batch)")

        elif not is_synced:
            # Step 3: Submit Work
            self.current_workflow_step = 3
            self.step_labels[0].configure(text=f"✓ 1. Downloaded ({total_imgs})", fg="#15803D", bg="#DCFCE7")
            self.step_labels[1].configure(text="✓ 2. All Labeled (100%)", fg="#15803D", bg="#DCFCE7")
            self.step_labels[2].configure(text="● 3. Submit Work", fg="#FFFFFF", bg=self.C_SUCCESS)

            if self.__dict__.get("action_card_outer") is not None:
                self.action_card_outer.configure(highlightbackground=self.C_SUCCESS)
            self.hero_tag_var.set("STEP 3 OF 4 — SUBMIT WORK TO SERVER & NAS")
            self.wf_next_title_var.set(f"🎉 Step 3: All Images Labeled! Submit Work ({total_jsons} Ready)")
            self.wf_next_desc_var.set("All images in this batch are labeled. Click below to validate, create local backups, and save your annotations to the server and NAS.")
            self.wf_next_action_btn_text.set("🚀 3. Submit Work to Server & NAS")
            self.btn_main_action.configure(command=self.central_sync, state="normal", bg=self.C_SUCCESS)
            self.wf_fetch_status_var.set(f"🚀 Ready to submit {total_jsons} completed annotations")

        else:
            # Step 4: Clean Workspace & Finish
            self.current_workflow_step = 4
            self.step_labels[0].configure(text=f"✓ 1. Downloaded", fg="#15803D", bg="#DCFCE7")
            self.step_labels[1].configure(text="✓ 2. Labeled", fg="#15803D", bg="#DCFCE7")
            self.step_labels[2].configure(text="✓ 3. Saved to NAS", fg="#15803D", bg="#DCFCE7")
            self.step_labels[3].configure(text="● 4. Clean & Finish", fg="#FFFFFF", bg=self.C_WARNING)

            if self.__dict__.get("action_card_outer") is not None:
                self.action_card_outer.configure(highlightbackground=self.C_WARNING)
            self.hero_tag_var.set("STEP 4 OF 4 — BATCH COMPLETE & VERIFIED")
            self.wf_next_title_var.set("Step 4: Clean Workspace & Finish Assignment")
            self.wf_next_desc_var.set("Your annotations are safely submitted and verified on the server! Click below to remove local images from your computer and choose your next task.")
            self.wf_next_action_btn_text.set("🧹 4. Finish Assignment & Clean Workspace")
            self.btn_main_action.configure(command=self.central_clean, state="normal", bg=self.C_WARNING)
            self.wf_fetch_status_var.set("✅ Submitted & verified on NAS. Click above to clean up.")

    def _start_workspace_watcher(self) -> None:
        """Lightweight live watcher that auto-detects annotations saved in XAnyLabeling in real time."""
        self._last_watched_imgs = -1
        self._last_watched_jsons = -1
        self._schedule_workspace_tick()

    def _schedule_workspace_tick(self) -> None:
        self.safe_after(2000, self._workspace_watcher_tick)

    def _workspace_watcher_tick(self) -> None:
        try:
            if getattr(self, "is_logged_in", False) and getattr(self, "agent", None):
                curr_dir = Path(self.agent.current_dir)
                if curr_dir.exists():
                    img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
                    img_count = 0
                    json_count = 0
                    for f in curr_dir.rglob("*"):
                        if f.is_file():
                            suf = f.suffix.lower()
                            if suf in img_exts:
                                img_count += 1
                            elif suf == ".json":
                                json_count += 1

                    if img_count != self._last_watched_imgs or json_count != self._last_watched_jsons:
                        self._last_watched_imgs = img_count
                        self._last_watched_jsons = json_count
                        self.central_refresh_status()
        except Exception:
            pass
        finally:
            self._nas_tick_counter = getattr(self, "_nas_tick_counter", 0) + 1
            if self._nas_tick_counter >= 15:  # Check NAS every 30s (15 * 2s) to prevent NAS traffic
                self._nas_tick_counter = 0
                if getattr(self, "is_logged_in", False) and getattr(self, "agent", None):
                    threading.Thread(target=self.check_nas_connection, daemon=True).start()
            self._schedule_workspace_tick()

    def _on_global_return_key(self, event=None) -> None:
        focused = self.focus_get()
        if getattr(self, "current_view", "") == "login":
            self.central_login()
        elif getattr(self, "current_view", "") in {"overview", "batch"}:
            if not isinstance(focused, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
                if hasattr(self, "hero_action_btn") and self.hero_action_btn.cget("state") == "normal":
                    self.hero_action_btn.invoke()

    def central_fetch(self) -> None:
        if not self.agent or not self.agent.client.token:
            messagebox.showwarning("Login Required", "Please log in before downloading images.")
            self.switch_view("login")
            return

        if not self.is_nas_connected:
            messagebox.showwarning(
                "NAS Disconnected",
                "Cannot download images: NAS storage is unreachable.\n\n"
                "Please verify your network connection to the NAS and click 'Re-check NAS Connection' before continuing.",
            )
            return

        active = self.selected_assignment or (self.agent.get_active_assignment() if self.agent else None)
        if not active:
            messagebox.showwarning("No Assignment Selected", "Please select an assigned project or task above before downloading.")
            return

        aid = active["id"]
        total_alloc = active.get("allocated_count", active.get("requested_count", 0))
        if hasattr(self, "btn_wf_fetch"):
            self.btn_wf_fetch.configure(state="disabled", text="⏳ Downloading...")
        self.wf_fetch_status_var.set(f"⏳ Downloading assigned images (0 / {total_alloc})...")
        self.central_log(f"📥 Downloading single batch of {total_alloc} images for assignment #{aid}...")

        def on_progress(done: int, total: int):
            pct = (done / total * 100) if total > 0 else 0
            def update_prog():
                self.wf_fetch_status_var.set(f"⏳ Downloading: {done} / {total} images ({pct:.0f}%)...")
                if hasattr(self, "wf_progress_bar"):
                    self.wf_progress_bar.configure(value=pct)
            self.safe_after(0, update_prog)

        def run():
            try:
                count = self.agent.fetch_batch(aid, limit=None, progress_callback=on_progress)
                self.last_sync_success = False
                self.safe_after(0, self.central_refresh_status)

                def on_done():
                    open_now = messagebox.askyesno(
                        "Download Complete",
                        f"Successfully downloaded all {count} images in one batch!\n\nWould you like to open the XAnyLabeling annotation tool now?",
                    )
                    if open_now:
                        self.central_launch_xany()

                self.safe_after(0, on_done)
            except Exception as exc:
                err_msg = str(exc)
                self.central_log(f"❌ Download failed: {err_msg}")
                self.safe_after(0, lambda msg=err_msg: messagebox.showerror("Download Failed", msg))
            finally:
                if hasattr(self, "btn_wf_fetch"):
                    self.safe_after(0, lambda: self.btn_wf_fetch.configure(state="normal", text="📥 1. Download Assigned Images"))

        threading.Thread(target=run, daemon=True).start()

    def central_launch_xany(self) -> None:
        if not self.agent:
            return
        curr_dir = Path(self.agent.current_dir)
        curr_dir.mkdir(parents=True, exist_ok=True)

        self.central_log(f"🎨 Opening XAnyLabeling on workspace: {curr_dir}")
        proc = self.agent.launch_xanylabeling()
        if proc:
            self.central_log(f"XAnyLabeling running (PID: {proc.pid}). Annotate images and press Ctrl+S to save.")

            def wait_for_exit(p):
                try:
                    p.wait()
                except Exception:
                    pass
                self.safe_after(0, self._on_xanylabeling_closed)

            threading.Thread(target=wait_for_exit, args=(proc,), daemon=True).start()
        else:
            messagebox.showerror(
                "Launch Failed",
                "Could not launch XAnyLabeling.\nPlease ensure XAnyLabeling is installed in ~/xanylabeling-venv-new or your environment.",
            )

    def _on_xanylabeling_closed(self) -> None:
        self.central_log("ℹ️ XAnyLabeling was closed. Refreshing local annotations...")
        self.central_refresh_status()

        if not self.agent:
            return
        curr_dir = Path(self.agent.current_dir)
        jsons = [f for f in curr_dir.rglob("*.json") if f.is_file()]
        if jsons:
            self.central_log(f"✅ Found {len(jsons)} saved annotation(s). Ready to sync with server.")
            sync_now = messagebox.askyesno(
                "Sync Annotations to Web & NAS",
                f"Annotation session finished!\n\n"
                f"You have {len(jsons)} saved annotation(s) on your computer.\n\n"
                f"Would you like to sync them now so your progress is updated on the Web Dashboard ({self._get_dashboard_url()})?",
            )
            if sync_now:
                self.central_sync()

    def central_sync(self) -> None:
        if not self.agent or not self.agent.client.token:
            messagebox.showwarning("Login Required", "Please log in before syncing annotations.")
            self.switch_view("login")
            return

        if not self.is_nas_connected:
            messagebox.showwarning(
                "NAS Disconnected",
                "Cannot submit annotations: NAS storage is unreachable.\n\n"
                "Your annotations are kept safely on your computer. Please verify your network connection and click 'Re-check NAS Connection' before submitting.",
            )
            return

        active = self.selected_assignment or (self.agent.get_active_assignment() if self.agent else None)
        if not active:
            messagebox.showwarning("No Assignment Selected", "Please select an assignment first.")
            return

        aid = active["id"]
        lease_gen = active.get("lease_generation", 1)

        # Inspect current batch workspace
        curr_dir = Path(self.agent.current_dir)
        img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
        local_imgs = [f for f in curr_dir.rglob("*") if f.is_file() and f.suffix.lower() in img_exts]
        local_jsons = [f for f in curr_dir.rglob("*.json") if f.is_file()]
        total_imgs = len(local_imgs)
        total_jsons = len(local_jsons)

        if total_imgs == 0 and total_jsons == 0:
            messagebox.showinfo(
                "No Images in Workspace",
                "There are no images currently in your local workspace.\n\n"
                "Please download your assigned batch of images first.",
            )
            return

        # If some images in this batch are unannotated, prompt with the batch submission dialog
        if total_jsons < total_imgs:
            self._show_submit_confirmation_dialog(aid, lease_gen, total_imgs, total_jsons)
        else:
            # All images in batch are labeled
            confirm = messagebox.askyesno(
                "Submit Completed Batch",
                f"All {total_imgs} images in this batch are labeled!\n\n"
                f"Submit all {total_jsons} annotations to Central Server and sync to NAS?",
            )
            if confirm:
                self._execute_sync(aid, lease_gen, declare_remaining_as_background=False, is_full_batch=True)

    def _show_submit_confirmation_dialog(self, aid: int, lease_gen: int, total_imgs: int, total_jsons: int) -> None:
        unannotated = max(0, total_imgs - total_jsons)

        dlg = tk.Toplevel(self)
        dlg.title("Submit Work & Batch Status")
        dlg.configure(bg=self.C_APP_BG)
        dlg.transient(self)
        dlg.grab_set()

        dlg_w = 640
        dlg_h = 580
        self.update_idletasks()
        rx = self.winfo_rootx()
        ry = self.winfo_rooty()
        rw = self.winfo_width()
        rh = self.winfo_height()
        pos_x = max(0, rx + (rw - dlg_w) // 2)
        pos_y = max(0, ry + (rh - dlg_h) // 2)
        dlg.geometry(f"{dlg_w}x{dlg_h}+{pos_x}+{pos_y}")
        dlg.resizable(False, False)

        # Header Frame
        hdr = tk.Frame(dlg, bg=self.C_APP_BG, padx=24, pady=16)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text="🚀 Submit Work & Batch Status",
            font=self.font_title,
            fg=self.C_TEXT_PRIMARY,
            bg=self.C_APP_BG,
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text=f"Assignment #{aid} • Choose how to record your progress with Server & NAS",
            font=self.font_sub,
            fg=self.C_TEXT_MUTED,
            bg=self.C_APP_BG,
        ).pack(anchor="w", pady=(2, 0))

        # Stats Card
        stats_outer = tk.Frame(dlg, bg=self.C_CARD_BORDER, padx=1, pady=1)
        stats_outer.pack(fill="x", padx=24, pady=(0, 14))
        stats_card = tk.Frame(stats_outer, bg="#FFFFFF", padx=16, pady=12)
        stats_card.pack(fill="x")

        stats_grid = tk.Frame(stats_card, bg="#FFFFFF")
        stats_grid.pack(fill="x")

        # Col 0: Batch Total
        c0 = tk.Frame(stats_grid, bg="#FFFFFF")
        c0.pack(side="left", expand=True, fill="x")
        tk.Label(c0, text="BATCH TOTAL", font=self.font_caption, fg=self.C_TEXT_MUTED, bg="#FFFFFF").pack(anchor="w")
        tk.Label(c0, text=f"{total_imgs} images", font=self.font_heading, fg=self.C_TEXT_PRIMARY, bg="#FFFFFF").pack(anchor="w")

        # Col 1: Labeled
        c1 = tk.Frame(stats_grid, bg="#FFFFFF")
        c1.pack(side="left", expand=True, fill="x")
        tk.Label(c1, text="LABELED WITH OBJECTS", font=self.font_caption, fg=self.C_SUCCESS_TEXT, bg="#FFFFFF").pack(anchor="w")
        tk.Label(c1, text=f"{total_jsons} (.json)", font=self.font_heading, fg=self.C_SUCCESS, bg="#FFFFFF").pack(anchor="w")

        # Col 2: Unannotated
        c2 = tk.Frame(stats_grid, bg="#FFFFFF")
        c2.pack(side="left", expand=True, fill="x")
        tk.Label(c2, text="UNLABELED IMAGES", font=self.font_caption, fg=self.C_WARNING_TEXT, bg="#FFFFFF").pack(anchor="w")
        tk.Label(c2, text=f"{unannotated} remaining", font=self.font_heading, fg=self.C_WARNING, bg="#FFFFFF").pack(anchor="w")

        # Options Container
        opts_box = tk.Frame(dlg, bg=self.C_APP_BG, padx=24)
        opts_box.pack(fill="both", expand=True)

        mode_var = tk.StringVar(value="partial" if total_jsons > 0 else "background")
        reason_var = tk.StringVar(value="Background / Negative sample (no target objects)")

        # Option A: Partial Progress
        opt_a_border = tk.Frame(opts_box, bg=self.C_CARD_BORDER, padx=1, pady=1)
        opt_a_border.pack(fill="x", pady=(0, 10))
        opt_a_card = tk.Frame(opt_a_border, bg="#FFFFFF", padx=14, pady=10)
        opt_a_card.pack(fill="x")

        rb_a = tk.Radiobutton(
            opt_a_card,
            variable=mode_var,
            value="partial",
            text=" 💾 Save Partial Progress (I will continue labeling later)",
            font=self.font_body_bold,
            fg=self.C_TEXT_PRIMARY,
            bg="#FFFFFF",
            activebackground="#FFFFFF",
            selectcolor="#FFFFFF",
            anchor="w",
        )
        rb_a.pack(fill="x")
        desc_a = (
            f"• Upload {total_jsons} annotation(s) to Server & NAS now.\n"
            f"• Keep remaining {unannotated} unannotated image(s) on your computer to finish tomorrow.\n"
            f"• Web Dashboard will immediately reflect {total_jsons} completed images."
        )
        tk.Label(
            opt_a_card,
            text=desc_a,
            font=self.font_sub,
            fg=self.C_TEXT_MUTED,
            bg="#FFFFFF",
            justify="left",
            padx=24,
        ).pack(anchor="w", pady=(4, 0))

        # Option B: Batch Complete with Background
        opt_b_border = tk.Frame(opts_box, bg=self.C_CARD_BORDER, padx=1, pady=1)
        opt_b_border.pack(fill="x", pady=(0, 10))
        opt_b_card = tk.Frame(opt_b_border, bg="#FFFFFF", padx=14, pady=10)
        opt_b_card.pack(fill="x")

        rb_b = tk.Radiobutton(
            opt_b_card,
            variable=mode_var,
            value="background",
            text=f" 🏁 Mark Batch Complete (Remaining {unannotated} are Background)",
            font=self.font_body_bold,
            fg=self.C_TEXT_PRIMARY,
            bg="#FFFFFF",
            activebackground="#FFFFFF",
            selectcolor="#FFFFFF",
            anchor="w",
        )
        rb_b.pack(fill="x")
        desc_b = (
            f"• All {total_imgs} images were inspected! {total_jsons} have objects, {unannotated} have no objects.\n"
            f"• Declares remaining {unannotated} image(s) as background & marks batch 100% finished.\n"
            f"• Cleans local workstation disk and unlocks the Next Batch!"
        )
        tk.Label(
            opt_b_card,
            text=desc_b,
            font=self.font_sub,
            fg=self.C_TEXT_MUTED,
            bg="#FFFFFF",
            justify="left",
            padx=24,
        ).pack(anchor="w", pady=(4, 6))

        # Reason Row inside Option B
        reason_frame = tk.Frame(opt_b_card, bg="#FFFFFF", padx=24)
        reason_frame.pack(fill="x")
        tk.Label(
            reason_frame,
            text="Reason: ",
            font=self.font_caption,
            fg=self.C_TEXT_MUTED,
            bg="#FFFFFF",
        ).pack(side="left")
        cb_reason = ttk.Combobox(
            reason_frame,
            textvariable=reason_var,
            values=[
                "Background / Negative sample (no target objects)",
                "Reviewed image — zero annotation objects detected",
                "Blank or unusable background frame",
            ],
            font=self.font_sub,
            width=45,
            state="readonly",
        )
        cb_reason.pack(side="left", fill="x", expand=True)

        # Footer Buttons
        btn_row = tk.Frame(dlg, bg=self.C_APP_BG, padx=24, pady=16)
        btn_row.pack(fill="x", side="bottom")

        def on_confirm():
            chosen_mode = mode_var.get()
            chosen_reason = reason_var.get()
            dlg.destroy()
            if chosen_mode == "background":
                self._execute_sync(
                    aid=aid,
                    lease_gen=lease_gen,
                    declare_remaining_as_background=True,
                    background_reason=chosen_reason,
                    is_full_batch=True,
                )
            else:
                self._execute_sync(
                    aid=aid,
                    lease_gen=lease_gen,
                    declare_remaining_as_background=False,
                    is_full_batch=False,
                )

        btn_cancel = tk.Button(
            btn_row,
            text="Cancel",
            font=self.font_body,
            bg="#FFFFFF",
            fg=self.C_TEXT_PRIMARY,
            relief="solid",
            bd=1,
            padx=16,
            pady=8,
            cursor="hand2",
            command=dlg.destroy,
        )
        btn_cancel.pack(side="right", padx=(10, 0))

        btn_submit = tk.Button(
            btn_row,
            text="🚀 Submit to Server & NAS",
            font=self.font_body_bold,
            bg=self.C_PRIMARY,
            fg="#FFFFFF",
            relief="flat",
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=on_confirm,
        )
        btn_submit.pack(side="right")

    def _execute_sync(
        self,
        aid: int,
        lease_gen: int,
        declare_remaining_as_background: bool = False,
        background_reason: str = "Background / Negative sample (no target objects)",
        is_full_batch: bool = False,
    ) -> None:
        if hasattr(self, "btn_wf_sync"):
            self.btn_wf_sync.configure(state="disabled", text="⏳ Submitting...")
        if hasattr(self, "btn_secondary_action"):
            self.btn_secondary_action.configure(state="disabled", text="⏳ Submitting...")
        if hasattr(self, "btn_main_action"):
            self.btn_main_action.configure(state="disabled", text="⏳ Submitting...")

        self.central_log(f"🚀 Submitting annotations for assignment #{aid} to Server & NAS...")

        def run():
            try:
                res = self.agent.sync_annotations(
                    assignment_id=aid,
                    ownership_generation=lease_gen,
                    declare_remaining_as_background=declare_remaining_as_background,
                    background_reason=background_reason,
                )
                submitted = res.get("submitted", 0)
                background = res.get("background", 0)
                errors = res.get("errors", 0)
                batch_completed = res.get("batch_completed", False) or is_full_batch or declare_remaining_as_background

                if errors == 0:
                    self.last_sync_success = True
                    self.central_log(f"🎉 Sync Complete! Submitted: {submitted}, Background: {background}")

                    if batch_completed:
                        # Notify server that annotator submitted for completion review
                        try:
                            self.agent.client.submit_completion(aid)
                            self.central_log(f"📋 Submitted Assignment #{aid} to Master for completion approval.")
                        except Exception as e:
                            logger.warning(f"Could not submit completion notification: {e}")

                        # Clean local workspace files to prepare for next batch
                        # Note: clear_cache=False preserves local database record that these items are SUBMITTED
                        cleaned = self.agent.clean_workspace(aid, clear_cache=False)
                        self.central_log(f"🧹 Cleaned {cleaned} local files. Ready for next batch.")
                        self.safe_after(0, self.central_refresh_status)
                        self.safe_after(0, self.refresh_assignments)

                        self.safe_after(
                            0,
                            lambda: messagebox.showinfo(
                                "Batch Completed Successfully",
                                f"🎉 Batch Finished & Verified!\n\n"
                                f"• Object Annotations Uploaded: {submitted}\n"
                                f"• Background Images Declared: {background}\n"
                                f"• Total Batch Completed: {submitted + background}\n\n"
                                f"Your work is safely recorded on the Central Server and synced to NAS.\n"
                                f"Your local workspace is cleaned and ready for the next batch!\n\n"
                                f"Live Web Dashboard: {self._get_dashboard_url()}",
                            ),
                        )
                    else:
                        # Partial progress saved
                        self.safe_after(0, self.central_refresh_status)
                        self.safe_after(0, self.refresh_assignments)

                        self.safe_after(
                            0,
                            lambda: messagebox.showinfo(
                                "Progress Saved",
                                f"🎉 Partial Progress Saved!\n\n"
                                f"• Uploaded & Verified: {submitted} annotation(s)\n\n"
                                f"Your work is safely saved on the Central Server and synced to NAS.\n"
                                f"The remaining unannotated images stay on your computer so you can continue labeling.\n\n"
                                f"Live Web Dashboard: {self._get_dashboard_url()}",
                            ),
                        )
                else:
                    self.central_log(f"⚠️ Submission finished with {errors} error(s). {submitted} succeeded.")
                    self.safe_after(0, self.central_refresh_status)
                    self.safe_after(
                        0,
                        lambda: messagebox.showwarning(
                            "Submission Completed with Warnings",
                            f"Submitted {submitted} annotation(s), but encountered {errors} error(s).\n\n"
                            f"Please check the log output below for details.",
                        ),
                    )

            except Exception as exc:
                err_msg = str(exc)
                self.central_log(f"❌ Submission failed: {err_msg}")
                self.safe_after(0, lambda msg=err_msg: messagebox.showerror("Submission Failed", msg))
            finally:
                if hasattr(self, "btn_wf_sync"):
                    self.safe_after(0, lambda: self.btn_wf_sync.configure(state="normal", text="🚀 3. Submit Work to Server"))
                if hasattr(self, "btn_secondary_action"):
                    self.safe_after(0, lambda: self.btn_secondary_action.configure(state="normal", text="🚀 Submit Work Now"))
                if hasattr(self, "btn_main_action"):
                    self.safe_after(0, self.central_refresh_status)

        threading.Thread(target=run, daemon=True).start()

    def central_reset_local_cache(self) -> None:
        if not self.agent:
            return
        active = self.selected_assignment or (self.agent.get_active_assignment() if self.agent else None)
        aid = active["id"] if active else None
        alloc_count = active.get("allocated_count", active.get("requested_count", 0)) if active else 0

        confirmed = messagebox.askyesno(
            "Reset Local Downloads & Cache",
            "This will delete all locally downloaded images on this computer and clear the local download database cache.\n\n"
            f"You will be able to download the entire assignment fresh from image #1 (0 / {alloc_count}).\n\n"
            "Do you want to continue?",
        )
        if not confirmed:
            return

        count = self.agent.clean_workspace(aid)
        self.last_sync_success = False
        if hasattr(self, "wf_progress_bar"):
            self.wf_progress_bar.configure(value=0)
        self.wf_fetch_status_var.set("Ready to download from scratch (0 downloaded).")
        self.central_log(f"🧹 Local cache reset. Removed {count} local files and cleared download records for assignment #{aid if aid else 'all'}.")
        self.central_refresh_status()
        self.refresh_assignments()
        messagebox.showinfo("Cache Reset", "Local cache and downloaded images cleared! Click 'Download Assigned Images' to download from the beginning.")

    def central_clean(self) -> None:
        if not self.agent:
            return
        active = self.selected_assignment or (self.agent.get_active_assignment() if self.agent else None)
        aid = active["id"] if active else None

        confirmed = messagebox.askyesno(
            "Clean Workspace",
            "Are you sure you want to clean completed images from your computer?\n\nMake sure you have clicked 'Submit Work to Server' first so your annotations are safely saved on the server!",
        )
        if not confirmed:
            return

        count = self.agent.clean_workspace(aid)
        self.last_sync_success = False
        self.central_log(f"🧹 Workspace cleaned. Removed {count} local files and reset cache.")
        self.central_refresh_status()
        self.refresh_assignments()
        messagebox.showinfo("Workspace Cleaned", "Local workspace cleared successfully! You can now select your next assignment.")

    # -------------------------------------------------------------------------
    # STANDALONE LEGACY SINGLE-PC POC COMPATIBILITY
    # -------------------------------------------------------------------------
    def log(self, text: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(self, "log_widget") and self.log_widget.winfo_exists():
            self.log_widget.insert(tk.END, f"[{stamp}] {text}\n")
            self.log_widget.see(tk.END)
        self.update_idletasks()

    def load_config_values(self) -> Dict[str, str]:
        cfg = read_config_file(self.config_path)
        remote = cfg.get("REMOTE", "")
        dataset = cfg.get("DATASET", "")
        root = cfg.get("ROOT", "")
        batch = cfg.get("BATCH_SIZE", "200")
        bandwidth = cfg.get("BANDWIDTH", "")
        transfers = cfg.get("TRANSFERS", "1")
        retries = cfg.get("RETRIES", "3")
        values = {
            "REMOTE": remote,
            "DATASET": dataset,
            "ROOT": root,
            "BATCH_SIZE": batch,
            "BANDWIDTH": bandwidth,
            "TRANSFERS": transfers,
            "RETRIES": retries,
            "CONFIG_PATH": str(self.config_path),
        }
        for key, widget in self.config_vars.items():
            if key == "CONFIG_PATH":
                widget.delete(0, tk.END)
                widget.insert(0, str(self.config_path))
            else:
                widget.delete(0, tk.END)
                widget.insert(0, values.get(key, ""))
        return cfg

    def save_configuration(self) -> None:
        remote_name = self.config_vars["REMOTE"].get().strip()
        values = {
            "REMOTE": remote_name,
            "DATASET": normalize_remote_path(self.config_vars["DATASET"].get().strip(), remote_name),
            "ROOT": self.config_vars["ROOT"].get().strip(),
            "BATCH_SIZE": self.config_vars["BATCH_SIZE"].get().strip(),
            "BANDWIDTH": self.config_vars["BANDWIDTH"].get().strip(),
            "TRANSFERS": self.config_vars["TRANSFERS"].get().strip(),
            "RETRIES": self.config_vars["RETRIES"].get().strip(),
        }
        ok, errors = validate_config(values)
        if not ok:
            messagebox.showerror("Invalid configuration", "\n".join(errors))
            return
        save_config(self.config_path, values)
        self.central_log(f"Saved configuration to {self.config_path}")
        self.refresh_all()

    def open_config_file(self) -> None:
        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(self.config_path)])
            else:
                subprocess.Popen(["notepad", str(self.config_path)])
            self.central_log(f"Opened configuration file: {self.config_path}")
        except Exception as exc:
            self.central_log(f"Could not open config file: {exc}")

    def refresh_all(self) -> None:
        # 1. Refresh Central Agent & Assignments
        self.refresh_assignments()
        self.central_refresh_status()
        threading.Thread(target=self.check_nas_connection, daemon=True).start()

        # 2. Refresh Legacy Tab (Async in thread so it never blocks GUI startup)
        def run_legacy():
            try:
                cfg = self.load_config_values()
                if not cfg:
                    self.safe_after(0, lambda: self.status_var.set("Configuration missing"))
                    self.safe_after(0, lambda: self.nas_var.set("Unavailable"))
                    self.safe_after(0, lambda: self.progress_var.set("No project config loaded"))
                    return

                ok, errors = validate_config(cfg)
                if not ok:
                    self.safe_after(0, lambda: self.status_var.set("Configuration invalid"))
                    self.safe_after(0, lambda: self.nas_var.set("Needs correction"))
                    self.safe_after(0, lambda: self.progress_var.set("; ".join(errors[:2])))
                    return

                self.safe_after(0, lambda: self.status_var.set("Configuration loaded"))
                self.safe_after(0, lambda: self.nas_var.set("Checking connection..."))

                try:
                    connected = health_check()
                    nas_text = "Connected" if connected else "Disconnected"
                except Exception:
                    nas_text = "Disconnected"

                status = query_status()
                state = status.get("state", "IDLE")
                catalog = status.get("catalog", 0)
                done = status.get("done", 0)
                batch = status.get("batch")
                counts = status.get("counts", {})
                annotated = int(counts.get("ANNOTATED", counts.get("annotated", 0) or 0))
                unannotated = int(counts.get("UNANNOTATED", counts.get("unannotated", 0) or 0))

                def update_legacy_ui():
                    self.nas_var.set(nas_text)
                    for name, button in self.action_buttons.items():
                        button.configure(state="normal")

                    if state == "AWAITING_APPROVAL":
                        self.status_var.set("Project state: AWAITING_APPROVAL")
                        self.progress_var.set(
                            f"Batch {batch} is waiting for approval: {annotated} annotated, {unannotated} intentionally unannotated."
                        )
                        self.action_buttons["annotate"].configure(state="disabled")
                        self.action_buttons["upload"].configure(state="disabled")
                        self.action_buttons["finish"].configure(text="Approve and continue")
                        return

                    self.action_buttons["finish"].configure(text="Finish annotation for batch")
                    self.status_var.set(f"Project state: {state}")
                    if batch is not None:
                        self.progress_var.set(
                            f"Batch {batch} - {state} | completed {done}/{catalog} | current counts: {counts}"
                        )
                    else:
                        self.progress_var.set(f"Total catalogued: {catalog} | completed: {done}")

                self.safe_after(0, update_legacy_ui)
            except Exception:
                pass

        threading.Thread(target=run_legacy, daemon=True).start()

    def _run_action(self, label: str, func) -> None:
        self.active_task = label
        self.status_var.set(f"Running {label}...")
        try:
            func()
            self.central_log(f"Action complete: {label}")
        except Exception as exc:
            self.central_log(f"Action failed: {label}: {exc}")
            messagebox.showerror("Operation failed", str(exc))
        finally:
            self.active_task = None
            self.refresh_all()

    def _start_worker(self, label: str, func) -> None:
        if self.active_task is not None:
            messagebox.showwarning("Busy", f"Another operation is already running: {self.active_task}")
            return
        thread = threading.Thread(target=self._run_action, args=(label, func), daemon=True)
        thread.start()

    def download_images(self) -> None:
        def action() -> None:
            ok, errors = validate_config(read_config_file(self.config_path))
            if not ok:
                raise RuntimeError("\n".join(errors))
            if not health_check():
                raise RuntimeError("NAS is unavailable. The local batch is safe and will retry later.")
            code, output = run_script("prepare.sh")
            if code != 0:
                raise RuntimeError(output.strip() or "Download preparation failed.")
            code2, output2 = run_script("sync_now.sh")
            if code2 != 0:
                raise RuntimeError(output2.strip() or "Download did not complete successfully.")
            self.central_log(output2.strip() or "Download action invoked through manager sync.")
            status = query_status()
            self.central_log(f"Current manager status after download: {status}")
            if status.get("state") in {"DOWNLOADING", "ANNOTATING", "UPLOAD_PENDING", "AWAITING_APPROVAL", "REVIEW_REQUIRED"}:
                self.central_log("Batch is active and ready for the next workflow step.")
        self._start_worker("download", action)

    def upload_images(self) -> None:
        def action() -> None:
            ok, errors = validate_config(read_config_file(self.config_path))
            if not ok:
                raise RuntimeError("\n".join(errors))
            if not health_check():
                raise RuntimeError("NAS is unavailable. Upload was not started to protect the local batch.")
            status = query_status()
            if status.get("state") == "AWAITING_APPROVAL":
                self.central_log("Batch is waiting for approval before upload; user must confirm unannotated images.")
                should_approve = messagebox.askyesno(
                    "Batch awaiting approval",
                    "This batch contains intentionally unannotated images.\n\n"
                    "Approve upload and continue, or keep the batch local for more annotation?",
                )
                self._approve_or_keep_batch("yes" if should_approve else "no")
                return
            code, output = run_script("sync_now.sh")
            if code != 0:
                raise RuntimeError(output.strip() or "Upload failed.")
            self.central_log(output.strip() or "Upload sync operation requested.")
            status = query_status()
            self.central_log(f"Upload status after manager sync: {status}")
        self._start_worker("upload", action)

    def start_annotation(self) -> None:
        def action() -> None:
            status = query_status()
            batch = status.get("batch")
            if batch is None:
                self.central_log("No active batch is ready. Running manager to prepare one.")
                code, output = run_script("prepare.sh")
                if code != 0:
                    raise RuntimeError(output.strip() or "No batch is ready to annotate.")
                status = query_status()
                batch = status.get("batch")
            if batch is None:
                raise RuntimeError("No current batch exists. Download a batch before starting annotation.")
            root_dir = Path(self.config_vars["ROOT"].get().strip())
            active_batch_dir = root_dir / "current"
            if not active_batch_dir.exists() and active_batch_dir.is_symlink() is False:
                self.central_log("Current batch not found on disk; creating it via manager.")
                code, output = run_script("sync_now.sh")
                if code != 0:
                    raise RuntimeError(output.strip() or "The batch could not be prepared.")
            launch_script = build_xanylabeling_launch_script()
            args = build_xanylabeling_command(
                (read_config_file(self.config_path).get("XANYLABELING") or "xanylabeling"),
                str(root_dir / "current"),
                launch_script,
            )
            self.central_log(f"Launching XAnyLabeling in {root_dir / 'current'}")
            subprocess.Popen(args, cwd=str(root_dir / "current"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.central_log("XAnyLabeling was launched as a separate process.")
        self._start_worker("annotation", action)

    def _approve_or_keep_batch(self, choice: str) -> None:
        status = query_status()
        if status.get("state") not in {"AWAITING_APPROVAL", "REVIEW_REQUIRED"}:
            return
        choice = "yes" if choice == "yes" else "no"
        code, output = manager_runner("approve", choice)
        if code != 0:
            raise RuntimeError(output.strip() or f"Approval decision failed for {choice}.")
        self.central_log(f"User approval decision: {choice}")
        self.central_log(output.strip() or f"Batch approval set to {choice}.")

    def finish_batch(self) -> None:
        def action() -> None:
            status = query_status()
            if status.get("state") == "AWAITING_APPROVAL":
                should_approve = messagebox.askyesno(
                    "Batch awaiting approval",
                    "This batch has annotated images and intentionally unannotated images.\n\n"
                    "Approve the upload and continue to the next batch?\n\n"
                    "Choose No to keep the batch local for further editing.",
                )
                self._approve_or_keep_batch("yes" if should_approve else "no")
                return
            code, output = run_script("close_batch.sh")
            if code != 0:
                raise RuntimeError(output.strip() or "Batch finalization failed.")
            self.central_log(output.strip() or "Batch close request sent to the project manager.")
            status = query_status()
            self.central_log(f"Status after batch closure: {status}")
        self._start_worker("finish_batch", action)

    def complete_project(self) -> None:
        def action() -> None:
            status = query_status()
            if status.get("batch") is not None and status.get("state") not in {"SYNCED", "CLEANED", "DONE", "IDLE"}:
                raise RuntimeError("Unfinished work remains. The project is not safe to finalize yet.")
            self.central_log("Project completion requested: unfinished work checks passed.")
            messagebox.showinfo("Project complete", "All visible work is complete or safely preserved. No local batch was deleted.")
        self._start_worker("project_complete", action)


def main() -> None:
    app = AnnotationDesktopApp()
    app.mainloop()


if __name__ == "__main__":
    main()
