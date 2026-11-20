#!/usr/bin/env python3
"""
Cross-Platform Desktop Icon & Launcher Installer
Installs a 1-click desktop icon for NAS Annotation Workstation on Linux and Windows.
Resolves installation paths so the launcher works reliably from anywhere.
"""

import os
import sys
import platform
import subprocess
from pathlib import Path


def get_local_app_dir() -> Path:
    return Path(__file__).resolve().parent


def save_registered_app_path(app_dir: Path, is_windows: bool) -> None:
    """Persists the installation directory so standalone shortcuts know where local-app lives."""
    try:
        if is_windows:
            config_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "nas_annotation"
        else:
            config_dir = Path.home() / ".config" / "nas_annotation"
        config_dir.mkdir(parents=True, exist_ok=True)
        path_file = config_dir / ("app_path.txt" if is_windows else "app_path")
        path_file.write_text(str(app_dir.resolve()), encoding="utf-8")
        print(f"[*] Registered app directory: {app_dir}")
    except Exception as e:
        print(f"[!] Warning: Could not save app_path: {e}")


def install_linux(app_dir: Path) -> bool:
    print("[*] Installing Desktop Launcher for Linux...")
    run_gui_sh = app_dir / "run_gui.sh"
    run_gui_sh.chmod(run_gui_sh.stat().st_mode | 0o755)

    icon_png = app_dir / "assets" / "app_icon.png"
    if not icon_png.exists():
        icon_path_str = "applications-graphics"
    else:
        icon_path_str = str(icon_png.resolve())

    # Get XDG Desktop directory if available, else default to ~/Desktop
    desktop_dir = Path.home() / "Desktop"
    try:
        xdg_desktop = subprocess.check_output(["xdg-user-dir", "DESKTOP"], text=True).strip()
        if xdg_desktop and os.path.isdir(xdg_desktop):
            desktop_dir = Path(xdg_desktop)
    except Exception:
        pass

    apps_dir = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)

    desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=NAS Annotation Workstation
Comment=Centralized Dataset Annotation Desktop App
Exec="{run_gui_sh.resolve()}"
Path={app_dir.resolve()}
Icon={icon_path_str}
Terminal=false
Categories=Graphics;Development;
StartupNotify=true
"""

    # 1. Update repo's AnnotationApp.desktop
    local_desktop_file = app_dir / "AnnotationApp.desktop"
    local_desktop_file.write_text(desktop_content, encoding="utf-8")
    local_desktop_file.chmod(local_desktop_file.stat().st_mode | 0o755)

    # 2. Install to Desktop
    desktop_dir.mkdir(parents=True, exist_ok=True)
    desktop_target = desktop_dir / "AnnotationApp.desktop"
    desktop_target.write_text(desktop_content, encoding="utf-8")
    desktop_target.chmod(desktop_target.stat().st_mode | 0o755)
    print(f"[✓] Desktop shortcut created at: {desktop_target}")

    # Mark trusted in GNOME if gio is available
    try:
        subprocess.run(["gio", "set", str(desktop_target), "metadata::trusted", "true"], check=False)
    except Exception:
        pass

    # 3. Install to Application Menu (~/.local/share/applications)
    menu_target = apps_dir / "AnnotationApp.desktop"
    menu_target.write_text(desktop_content, encoding="utf-8")
    menu_target.chmod(menu_target.stat().st_mode | 0o755)
    print(f"[✓] Application menu entry created at: {menu_target}")

    # Update desktop database if available
    try:
        subprocess.run(["update-desktop-database", str(apps_dir)], check=False)
    except Exception:
        pass

    return True


def install_windows(app_dir: Path) -> bool:
    print("[*] Installing Desktop Launcher for Windows...")
    run_gui_bat = app_dir / "run_gui.bat"
    icon_ico = app_dir / "assets" / "app_icon.ico"
    icon_path_str = str(icon_ico.resolve()) if icon_ico.exists() else ""

    desktop_dir = Path.home() / "Desktop"
    # Try getting actual desktop path from environment
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        desktop_dir = Path(user_profile) / "Desktop"

    start_menu_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell

# Desktop shortcut
$DesktopPath = [System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop'), 'NAS Annotation Workstation.lnk')
$Shortcut = $WshShell.CreateShortcut($DesktopPath)
$Shortcut.TargetPath = '{run_gui_bat.resolve()}'
$Shortcut.WorkingDirectory = '{app_dir.resolve()}'
$Shortcut.Description = 'NAS Dataset Annotation Workstation'
if ('{icon_path_str}') {{
    $Shortcut.IconLocation = '{icon_path_str}'
}}
$Shortcut.Save()
Write-Host "[✓] Desktop shortcut created at: $DesktopPath"

# Start Menu shortcut
$StartMenuPath = [System.IO.Path]::Combine([System.Environment]::GetFolderPath('Programs'), 'NAS Annotation Workstation.lnk')
$Shortcut2 = $WshShell.CreateShortcut($StartMenuPath)
$Shortcut2.TargetPath = '{run_gui_bat.resolve()}'
$Shortcut2.WorkingDirectory = '{app_dir.resolve()}'
$Shortcut2.Description = 'NAS Dataset Annotation Workstation'
if ('{icon_path_str}') {{
    $Shortcut2.IconLocation = '{icon_path_str}'
}}
$Shortcut2.Save()
Write-Host "[✓] Start Menu shortcut created at: $StartMenuPath"
"""

    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, check=True)
        print(res.stdout.strip())
        return True
    except Exception as e:
        print(f"[!] PowerShell shortcut creation failed: {e}")
        # Fallback to VBScript
        return _install_windows_vbs(app_dir, run_gui_bat, icon_path_str, desktop_dir)


def _install_windows_vbs(app_dir: Path, target_bat: Path, icon_path: str, desktop_dir: Path) -> bool:
    try:
        vbs_path = app_dir / "create_shortcut_temp.vbs"
        shortcut_path = desktop_dir / "NAS Annotation Workstation.lnk"
        vbs_content = f"""
Set WshShell = CreateObject("WScript.Shell")
Set Shortcut = WshShell.CreateShortcut("{shortcut_path}")
Shortcut.TargetPath = "{target_bat.resolve()}"
Shortcut.WorkingDirectory = "{app_dir.resolve()}"
Shortcut.Description = "NAS Dataset Annotation Workstation"
"""
        if icon_path:
            vbs_content += f'Shortcut.IconLocation = "{icon_path}"\n'
        vbs_content += "Shortcut.Save\n"
        vbs_path.write_text(vbs_content, encoding="utf-8")
        subprocess.run(["cscript", "//nologo", str(vbs_path)], check=True)
        vbs_path.unlink(missing_ok=True)
        print(f"[✓] Created Windows shortcut via VBScript at: {shortcut_path}")
        return True
    except Exception as e:
        print(f"[!] VBScript fallback failed: {e}")
        return False


def main():
    app_dir = get_local_app_dir()
    os_name = platform.system()
    is_windows = os_name == "Windows"

    save_registered_app_path(app_dir, is_windows)

    if is_windows:
        install_windows(app_dir)
    else:
        install_linux(app_dir)

    print("\n[✓] Setup completed successfully! You can now launch the app directly from your Desktop icon.")


if __name__ == "__main__":
    main()
