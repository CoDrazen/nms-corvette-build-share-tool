import os
import argparse
import csv
import re
import json
import shutil
import subprocess
import sys
import ctypes
import ctypes.wintypes
import tkinter as tk
import threading
import traceback
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from datetime import datetime, timezone


# Portable app paths
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    RUNTIME_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    RUNTIME_DIR = APP_DIR

# App metadata + settings path
APP_NAME = "NMS Corvette Build Share Tool"
APP_VENDOR = "CoDrazen"
APP_VERSION = "1.0.1"


def default_settings_dir() -> str:
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return os.path.join(local_app_data, APP_VENDOR, APP_NAME)
    return APP_DIR


SETTINGS_DIR = default_settings_dir()
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "nms_corvette_tool_settings.json")

# Portable bundled EXE path
LIBNOM_EXE = os.path.join(RUNTIME_DIR, "libNOM", "libNOM.io.cli.exe")
APP_ICON_ICO = os.path.join(RUNTIME_DIR, "icons", "nms-app-icon-galaxy-nobg-256.ico")

# Set via run_debug.bat to print pairing diagnostics to the terminal
DEBUG_PAIRING = os.environ.get("NMS_CORVETTE_DEBUG_PAIRING", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Wrapper file format constants
BUILD_FORMAT = "NMS-CorvetteBuild"
BUILD_VERSION = 1
SUPPORTED_BUILD_VERSIONS = {BUILD_VERSION}

# Tool workspace folder (created next to st_... save folder)
TOOL_ROOT_NAME = "NMS_CorvetteTool"
MAX_TRACKED_WORK_ROOTS = 12

PLATFORM_LABELS = [
    "Auto-detect",
    "Steam",
    "GOG",
    "Microsoft",
    "PlayStation",
    "Switch",
]

PLATFORM_LABEL_TO_VALUE = {
    "Steam": "Steam",
    "GOG": "Gog",
    "Microsoft": "Microsoft",
    "PlayStation": "Playstation",
    "Switch": "Switch",
}


def default_workspace_root_for_save(save_folder: str) -> str:
    save_folder = os.path.abspath(save_folder)
    parent = os.path.dirname(save_folder)
    return os.path.join(parent, TOOL_ROOT_NAME)


def sanitize_app_settings(settings) -> dict:
    if not isinstance(settings, dict):
        return {}

    cleaned = {}

    workspace_root = settings.get("workspace_root", "")
    if isinstance(workspace_root, str) and workspace_root.strip():
        cleaned["workspace_root"] = os.path.abspath(workspace_root.strip())

    recent_work_roots = normalize_recent_work_roots(settings.get("recent_work_roots", []))
    if recent_work_roots:
        cleaned["recent_work_roots"] = recent_work_roots

    return cleaned


def load_app_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return sanitize_app_settings(data)
    except Exception:
        pass
    return {}


def save_app_settings(settings: dict) -> bool:
    try:
        payload = sanitize_app_settings(settings)

        if not payload:
            if os.path.isfile(SETTINGS_PATH):
                os.remove(SETTINGS_PATH)
            try:
                if os.path.isdir(SETTINGS_DIR) and not os.listdir(SETTINGS_DIR):
                    os.rmdir(SETTINGS_DIR)
            except Exception:
                pass
            return True

        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def short_display_path(path: str, tail_parts: int = 3, max_chars: int = 74) -> str:
    if not isinstance(path, str) or not path.strip():
        return ""

    full = os.path.abspath(path)
    if len(full) <= max_chars:
        return full

    parts = full.split(os.sep)
    if len(parts) <= tail_parts + 1:
        return full

    drive = parts[0]
    tail = os.sep.join(parts[-tail_parts:])
    if drive.endswith(":"):
        return f"{drive}{os.sep}...{os.sep}{tail}"
    return f"...{os.sep}{tail}"


def normalize_recent_work_roots(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []

    out = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        path = os.path.abspath(item.strip())
        if os.path.basename(path).lower() != "work":
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
        if len(out) >= MAX_TRACKED_WORK_ROOTS:
            break
    return out


def resolve_platform_format(save_folder: str, preferred_save_file: str, selected_label: str) -> str:
    label = (selected_label or "Auto-detect").strip()
    if label and label != "Auto-detect":
        platform_value = PLATFORM_LABEL_TO_VALUE.get(label)
        if platform_value:
            return platform_value
        raise ValueError(f"Unsupported manual platform selection: {label}")

    detected = detect_platform_format_from_savehg(save_folder, preferred_save_file)
    if detected:
        return detected

    raise RuntimeError(
        "Could not detect the save platform automatically.\n\n"
        "Choose the platform manually from the Platform dropdown and try again."
    )


def apply_app_icon(root: tk.Tk):
    try:
        if os.path.isfile(APP_ICON_ICO):
            root.iconbitmap(APP_ICON_ICO)
    except Exception:
        pass
    return None


def windows_apps_use_dark_mode() -> bool:
    if os.name != "nt":
        return False

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except Exception:
        # Default to dark because the app itself uses a dark theme.
        return True


def apply_windows_title_bar_theme(root: tk.Tk) -> bool:
    if os.name != "nt":
        return False

    try:
        root.update_idletasks()
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi

        GA_ROOT = 2
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
        DWMWA_BORDER_COLOR = 34
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36

        hwnd = user32.GetAncestor(root.winfo_id(), GA_ROOT)
        if not hwnd:
            hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        if not hwnd:
            return False

        use_dark = windows_apps_use_dark_mode()
        dark_mode_value = ctypes.c_int(1 if use_dark else 0)

        applied = False
        for attr in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD):
            result = dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(attr),
                ctypes.byref(dark_mode_value),
                ctypes.sizeof(dark_mode_value)
            )
            if result == 0:
                applied = True

        if use_dark:
            # COLORREF uses 0x00bbggrr.
            caption_color = ctypes.c_uint(0x001E1E1E)
            text_color = ctypes.c_uint(0x00E6E6E6)
            border_color = ctypes.c_uint(0x00333333)

            for attr, value in (
                (DWMWA_CAPTION_COLOR, caption_color),
                (DWMWA_TEXT_COLOR, text_color),
                (DWMWA_BORDER_COLOR, border_color),
            ):
                result = dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd),
                    ctypes.c_uint(attr),
                    ctypes.byref(value),
                    ctypes.sizeof(value)
                )
                if result == 0:
                    applied = True

        user32.SetWindowPos(
            ctypes.c_void_p(hwnd),
            ctypes.c_void_p(0),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
        )
        return applied
    except Exception:
        pass

    return False


def apply_dark_theme(root: tk.Tk):
    """
    Simple dark theme for ttk + base Tk widgets.
    Works on Windows/macOS/Linux (with small native differences).
    """
    root.configure(bg="#1e1e1e")

    style = ttk.Style(root)

    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background="#1e1e1e", foreground="#e6e6e6")
    style.configure("TFrame", background="#1e1e1e")
    style.configure("TLabel", background="#1e1e1e", foreground="#e6e6e6")
    style.configure("Hint.TLabel", background="#1e1e1e", foreground="#a7a7a7")
    style.configure("Path.TLabel", background="#1e1e1e", foreground="#cfd7e6")

    style.configure(
        "TButton",
        background="#2a2a2a",
        foreground="#e6e6e6",
        padding=(10, 6)
    )
    style.map(
        "TButton",
        background=[("active", "#3a3a3a"), ("disabled", "#2a2a2a")],
        foreground=[("disabled", "#777777")]
    )

    style.configure(
        "Accent.TButton",
        background="#365f42",
        foreground="#f2fff4",
        padding=(12, 6)
    )
    style.map(
        "Accent.TButton",
        background=[("active", "#42744f"), ("disabled", "#2f3a32")],
        foreground=[("disabled", "#93a193")]
    )

    style.configure(
        "TCombobox",
        fieldbackground="#2a2a2a",
        background="#2a2a2a",
        foreground="#e6e6e6",
        arrowcolor="#e6e6e6"
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", "#2a2a2a")],
        foreground=[("readonly", "#e6e6e6")]
    )

    style.configure("TNotebook", background="#1e1e1e", borderwidth=0)
    style.configure("TNotebook.Tab", background="#2a2a2a", foreground="#e6e6e6", padding=(12, 6))
    style.map("TNotebook.Tab", background=[("selected", "#3a3a3a")])

    style.configure("TSeparator", background="#333333")
    style.configure("TLabelframe", background="#1e1e1e", foreground="#e6e6e6")
    style.configure("TLabelframe.Label", background="#1e1e1e", foreground="#e6e6e6")
    style.configure("TCheckbutton", background="#1e1e1e", foreground="#e6e6e6")


# -----------------------------
# Save slot helpers
# -----------------------------

_SAVE_RE = re.compile(r"^save(\d*)\.hg$", re.IGNORECASE)

def _save_num_from_name(name: str) -> int:
    """
    save.hg -> 1
    save2.hg -> 2
    save3.hg -> 3
    ...
    """
    m = _SAVE_RE.match(name.strip())
    if not m:
        return -1
    digits = m.group(1)
    if not digits:
        return 1
    try:
        return int(digits)
    except Exception:
        return -1


def list_save_slots(save_folder: str) -> list[dict]:
    """
    Returns list of slots present in folder.
    Slot mapping:
      Slot 1: save.hg (1) + save2.hg (2)
      Slot 2: save3.hg (3) + save4.hg (4)
      Slot 3: save5.hg (5) + save6.hg (6)
      ...
    We consider a slot "present" if at least one of its pair files exists,
    but we strongly prefer slots where BOTH exist.
    """
    try:
        names = os.listdir(save_folder)
    except Exception:
        return []

    present_nums = set()
    for n in names:
        k = _save_num_from_name(n)
        if k > 0:
            present_nums.add(k)

    slots = []
    # Slot 1 special
    pair1 = (1, 2)
    has1 = any(x in present_nums for x in pair1)
    if has1:
        slots.append({
            "slot": 1,
            "auto_num": 1,
            "restore_num": 2,
            "auto_file": "save.hg",
            "restore_file": "save2.hg",
            "both": (1 in present_nums and 2 in present_nums),
        })

    # Slot 2+ (odd/even pairs)
    # Find max numeric save index
    maxn = max(present_nums) if present_nums else 0
    # slot n uses (2n-1, 2n) where n>=2
    n = 2
    while True:
        a = 2 * n - 1
        b = 2 * n
        if a > maxn and b > maxn:
            break
        if a in present_nums or b in present_nums:
            slots.append({
                "slot": n,
                "auto_num": a,
                "restore_num": b,
                "auto_file": f"save{a}.hg",
                "restore_file": f"save{b}.hg",
                "both": (a in present_nums and b in present_nums),
            })
        n += 1

    # Prefer fully-present slots first, then slot order
    slots.sort(key=lambda s: (0 if s["both"] else 1, s["slot"]))
    return slots


def slot_display_label(slot_info: dict) -> str:
    s = slot_info["slot"]
    a = slot_info["auto_file"]
    r = slot_info["restore_file"]
    suffix = "" if slot_info.get("both") else " (incomplete)"
    return f"Slot {s}  [{a} + {r}]{suffix}"


def mf_name_for_save(save_name: str) -> str:
    """
    save.hg      -> mf_save.hg
    save2.hg     -> mf_save2.hg
    save12.hg    -> mf_save12.hg
    """
    n = save_name.strip()
    low = n.lower()
    if not low.endswith(".hg"):
        return "mf_" + n
    stem = n[:-3]  # remove ".hg"
    if stem.lower() == "save":
        return "mf_save.hg"
    return f"mf_{stem}.hg"


# -----------------------------
# Tool workspace helpers
# -----------------------------

def ensure_tool_dirs_for_save(save_folder: str, workspace_root_override: str = "") -> dict:
    r"""
    Creates (if missing) a tool workspace next to the save folder:

      <parent>\NMS_CorvetteTool\
          Backups\
          Builds\
          Work\
              Export\<save_id>\
              Import\<save_id>\

    Returns dict with paths:
      tool_root, backups_dir, builds_dir,
      work_root, export_work_dir, import_work_dir,
      save_id
    """
    save_folder = os.path.abspath(save_folder)
    save_id = os.path.basename(save_folder)

    if isinstance(workspace_root_override, str) and workspace_root_override.strip():
        tool_root = os.path.abspath(workspace_root_override.strip())
    else:
        tool_root = default_workspace_root_for_save(save_folder)

    backups_dir = os.path.join(tool_root, "Backups")
    builds_dir = os.path.join(tool_root, "Builds")
    work_root = os.path.join(tool_root, "Work")

    export_work_dir = os.path.join(work_root, "Export", save_id)
    import_work_dir = os.path.join(work_root, "Import", save_id)

    os.makedirs(backups_dir, exist_ok=True)
    os.makedirs(builds_dir, exist_ok=True)
    os.makedirs(export_work_dir, exist_ok=True)
    os.makedirs(import_work_dir, exist_ok=True)

    return {
        "tool_root": tool_root,
        "backups_dir": backups_dir,
        "builds_dir": builds_dir,
        "work_root": work_root,
        "export_work_dir": export_work_dir,
        "import_work_dir": import_work_dir,
        "save_id": save_id,
    }


def stable_work_json_path(work_dir: str, save_id: str, slot_num: int) -> str:
    # stable per-slot json filename
    return os.path.join(work_dir, f"{save_id}.slot{slot_num}.save.json")


def is_transient_work_artifact(name: str) -> bool:
    if not isinstance(name, str):
        return False
    return name.lower().endswith((".json", ".data", ".meta"))


def clean_transient_work_dir(work_dir: str) -> None:
    """
    Remove app-generated transient files from one slot-specific Work directory.
    Builds are stored elsewhere, so JSON/data/meta files here are safe to clear.
    """
    if not isinstance(work_dir, str) or not work_dir.strip() or not os.path.isdir(work_dir):
        return

    try:
        for name in os.listdir(work_dir):
            if not is_transient_work_artifact(name):
                continue
            try:
                os.remove(os.path.join(work_dir, name))
            except Exception:
                pass
    except Exception:
        pass


def clean_transient_work_root(work_root: str) -> None:
    """
    Remove transient files from an internal Work root, including Export/Import
    subfolders for any save IDs touched in this session.
    """
    if not isinstance(work_root, str) or not work_root.strip() or not os.path.isdir(work_root):
        return

    try:
        for root, _, files in os.walk(work_root):
            for name in files:
                if not is_transient_work_artifact(name):
                    continue
                try:
                    os.remove(os.path.join(root, name))
                except Exception:
                    pass
    except Exception:
        pass


def clean_work_json(work_dir: str, save_id: str, slot_num: int) -> None:
    """
    Clean ONLY inside this slot-specific work_dir:
      - delete stable JSON produced for viewing in the app
      - delete any leftover libNOM JSON/data/meta outputs
    """
    clean_transient_work_dir(work_dir)


# -----------------------------
# libNOM helpers
# -----------------------------

def _windows_no_console_startupinfo():
    if os.name != "nt":
        return None, 0
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    creationflags = subprocess.CREATE_NO_WINDOW
    return startupinfo, creationflags


def _run_libnom(args: list[str], cwd: str | None = None, input_text: str | None = None) -> str:
    startupinfo, creationflags = _windows_no_console_startupinfo()

    if os.path.isfile(LIBNOM_EXE):
        cmd = [LIBNOM_EXE] + args
    else:
        raise FileNotFoundError(
            "libNOM CLI not found.\n\n"
            f"Expected EXE:\n  {LIBNOM_EXE}\n\n"
            "Fix: put libNOM.io.cli.exe inside the app's libNOM folder."
        )

    p = subprocess.run(
        cmd,
        cwd=cwd,
        input=input_text,
        text=True,
        errors="ignore",
        shell=False,
        startupinfo=startupinfo,
        creationflags=creationflags,
        capture_output=True,
        check=True
    )
    return (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")


def run_convert_savehg_to_json(save_folder: str, save_file_name: str, work_dir: str, save_id: str, slot_num: int) -> str:
    r"""
    Converts <save_folder>\<save_file_name> to JSON, outputs into work_dir.
    Returns stable JSON path:
      <work_dir>\<save_id>.slot<slot_num>.save.json
    """
    save_hg = os.path.join(save_folder, save_file_name)
    if not os.path.isfile(save_hg):
        raise FileNotFoundError(f"{save_file_name} not found in: {save_folder}")

    clean_work_json(work_dir, save_id, slot_num)

    cmd = [
        "Convert",
        "-I", save_hg,
        "-O", work_dir,
        "-F", "Json",
        "-J", "True",
        "-Js", "True",
    ]

    before = set(os.listdir(work_dir))
    _run_libnom(cmd)
    after = set(os.listdir(work_dir))

    created = sorted([f for f in (after - before) if f.lower().endswith(".json")])
    if not created:
        # fallback: pick newest matching save*.hg.*.json
        candidates = [
            f for f in os.listdir(work_dir)
            if f.lower().startswith("save") and f.lower().endswith(".json") and ".hg." in f.lower()
        ]
        if not candidates:
            raise RuntimeError("Convert ran but no JSON was created/found in Work folder.")
        candidates.sort(key=lambda f: os.path.getmtime(os.path.join(work_dir, f)), reverse=True)
        created_path = os.path.join(work_dir, candidates[0])
    else:
        # prefer json whose prefix matches the input save file
        prefix = save_file_name.lower() + "."
        match = [f for f in created if f.lower().startswith(prefix)]
        pick = match[0] if match else created[0]
        created_path = os.path.join(work_dir, pick)

    stable_path = stable_work_json_path(work_dir, save_id, slot_num)
    try:
        if os.path.abspath(created_path) != os.path.abspath(stable_path):
            if os.path.isfile(stable_path):
                try:
                    os.remove(stable_path)
                except Exception:
                    pass
            os.replace(created_path, stable_path)
    except Exception:
        return created_path

    return stable_path


def detect_platform_format_from_savehg(save_folder: str, preferred_save_file: str) -> str:
    if os.path.isfile(os.path.join(save_folder, "steam_autocloud.vdf")):
        return "Steam"

    candidate = os.path.join(save_folder, preferred_save_file)
    if not os.path.isfile(candidate):
        # fallback to any existing save file
        for alt in ("save2.hg", "save.hg"):
            ap = os.path.join(save_folder, alt)
            if os.path.isfile(ap):
                candidate = ap
                break

    if not os.path.isfile(candidate):
        return ""

    try:
        out = _run_libnom(["Analyze", "-I", candidate])
        u = out.upper()
        if "MICROSOFT" in u:
            return "Microsoft"
        if "GOG" in u:
            return "Gog"
        if "SWITCH" in u:
            return "Switch"
        if "PLAYSTATION" in u or "PS4" in u or "PS5" in u:
            return "Playstation"
        if "STEAM" in u:
            return "Steam"
    except Exception:
        pass

    return ""


def convert_json_to_savehg(platform_format: str, json_in_path: str, save_folder: str, work_dir: str, out_name: str) -> None:
    r"""
    Convert JSON -> platform output in work_dir.
    Writes BOTH:
      - <save_folder>\<out_name>            from newest .data
      - <save_folder>\<mf_out_name>         from newest .meta
    Then deletes ALL .data/.meta from work_dir.
    """
    if not os.path.isfile(json_in_path):
        raise FileNotFoundError(f"JSON input not found: {json_in_path}")

    save_hg = os.path.join(save_folder, out_name)
    mf_name = mf_name_for_save(out_name)
    mf_save_hg = os.path.join(save_folder, mf_name)

    tmp_target_data = save_hg + ".tmp"
    tmp_target_meta = mf_save_hg + ".tmp"

    # Clean workdir of previous outputs
    for name in list(os.listdir(work_dir)):
        if name.lower().endswith((".data", ".meta")):
            try:
                os.remove(os.path.join(work_dir, name))
            except Exception:
                pass

    before = set(os.listdir(work_dir))

    _run_libnom([
        "Convert",
        "-I", json_in_path,
        "-O", work_dir,
        "-F", platform_format
    ])

    after = set(os.listdir(work_dir))
    created = list(after - before)

    data_candidates = [f for f in created if f.lower().endswith(".data")]
    meta_candidates = [f for f in created if f.lower().endswith(".meta")]

    if not data_candidates:
        data_candidates = [f for f in os.listdir(work_dir) if f.lower().endswith(".data")]
    if not meta_candidates:
        meta_candidates = [f for f in os.listdir(work_dir) if f.lower().endswith(".meta")]

    if not data_candidates:
        raise RuntimeError("Convert succeeded but no .data output was found in the work folder.")
    if not meta_candidates:
        raise RuntimeError("Convert succeeded but no .meta output was found in the work folder.")

    data_candidates.sort(key=lambda f: os.path.getmtime(os.path.join(work_dir, f)), reverse=True)
    meta_candidates.sort(key=lambda f: os.path.getmtime(os.path.join(work_dir, f)), reverse=True)

    data_path = os.path.join(work_dir, data_candidates[0])
    meta_path = os.path.join(work_dir, meta_candidates[0])

    # Atomic replace (data)
    shutil.copy2(data_path, tmp_target_data)
    os.replace(tmp_target_data, save_hg)

    # Atomic replace (meta -> mf_save*.hg)
    shutil.copy2(meta_path, tmp_target_meta)
    os.replace(tmp_target_meta, mf_save_hg)

    # FULL cleanup
    try:
        for name in os.listdir(work_dir):
            if name.lower().endswith((".data", ".meta")):
                try:
                    os.remove(os.path.join(work_dir, name))
                except Exception:
                    pass
    except Exception:
        pass


# -----------------------------
# JSON navigation helpers
# -----------------------------

def deep_get(d: dict, keys: list, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def normalize_filename(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return s.replace("\\", "/").strip().upper()


def resource_seed_hex(res: dict) -> str:
    if not isinstance(res, dict):
        return ""
    seed = res.get("Seed")
    if isinstance(seed, list) and len(seed) >= 2 and isinstance(seed[1], str):
        return seed[1].strip().lower()
    return ""


# -----------------------------
# Safety checks
# -----------------------------

def is_nms_running() -> bool:
    possible = {"nms.exe", "nomanssky.exe"}
    try:
        startupinfo, creationflags = _windows_no_console_startupinfo()
        out = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            errors="ignore",
            startupinfo=startupinfo,
            creationflags=creationflags
        )
        for row in csv.reader(out.splitlines()):
            if not row:
                continue
            image_name = (row[0] or "").strip().strip('"').lower()
            if image_name in possible:
                return True
        return False
    except Exception:
        return False


def get_primary_ship_index(root: dict):
    v = deep_get(root, ["BaseContext", "PlayerStateData", "PrimaryShip"], default=None)
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return None


def coerce_int_like(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if s and s.lstrip("+-").isdigit():
            try:
                return int(s, 10)
            except Exception:
                return None
    return None


def normalize_corvette_link_value(value) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str):
        return value.strip()
    return ""


def get_shipownership_list(root: dict) -> list:
    for path in (
        ["ShipOwnership"],
        ["BaseContext", "PlayerStateData", "ShipOwnership"],
        ["CommonStateData", "ShipOwnership"],
    ):
        v = deep_get(root, path)
        if isinstance(v, list):
            return v
    return []


def get_shipownership_entry(root: dict, idx: int) -> dict:
    ships = get_shipownership_list(root)
    if not isinstance(idx, int) or idx < 0 or idx >= len(ships):
        return {}
    ship = ships[idx]
    return ship if isinstance(ship, dict) else {}


def get_shipownership_resource(root: dict, idx: int) -> dict:
    ship = get_shipownership_entry(root, idx)
    res = ship.get("Resource")
    return res if isinstance(res, dict) else {}


def get_base_shipownership_index(base: dict):
    for path in (
        ["UserData"],
        ["Base", "UserData"],
        ["BaseData", "UserData"],
    ):
        value = deep_get(base, path) if len(path) > 1 else base.get(path[0])
        idx = coerce_int_like(value)
        if idx is not None:
            return idx
    return None


def get_base_shipownership_link_value(base: dict) -> str:
    for path in (
        ["UserData"],
        ["Base", "UserData"],
        ["BaseData", "UserData"],
    ):
        value = deep_get(base, path) if len(path) > 1 else base.get(path[0])
        normalized = normalize_corvette_link_value(value)
        if normalized:
            return normalized
    return ""


def get_shipownership_link_value(ship: dict) -> str:
    for path in (
        ["UserData"],
        ["ShipData", "UserData"],
        ["Data", "UserData"],
    ):
        value = deep_get(ship, path) if len(path) > 1 else ship.get(path[0])
        normalized = normalize_corvette_link_value(value)
        if normalized:
            return normalized
    return ""


def find_shipownership_entry_for_base(root: dict, base: dict) -> tuple[dict, int | None, str]:
    ship_i = get_base_shipownership_index(base)
    if ship_i is not None:
        ship = get_shipownership_entry(root, ship_i)
        if ship:
            return ship, ship_i, "userdata_index"

    link_value = get_base_shipownership_link_value(base)
    if link_value:
        for i, ship in enumerate(get_shipownership_list(root)):
            if not isinstance(ship, dict):
                continue
            if get_shipownership_link_value(ship) == link_value:
                return ship, i, "userdata_value"

    return {}, None, ""


def get_active_ship_reference(root: dict) -> tuple[int | None, str]:
    primary_i = get_primary_ship_index(root)
    active_res = get_shipownership_resource(root, primary_i) if primary_i is not None else {}
    active_seed = resource_seed_hex(active_res).lower()
    return primary_i, active_seed


def base_matches_active_ship(root: dict, base: dict, paired_seed: str = "") -> tuple[bool, int | None, int | None, str]:
    primary_i, active_seed = get_active_ship_reference(root)
    _ship, base_ship_i, _link_method = find_shipownership_entry_for_base(root, base)

    if primary_i is not None and base_ship_i is not None:
        return base_ship_i == primary_i, primary_i, base_ship_i, active_seed

    fallback_seed = (paired_seed or "").lower()
    if active_seed and fallback_seed:
        return active_seed == fallback_seed, primary_i, base_ship_i, active_seed

    return False, primary_i, base_ship_i, active_seed


# -----------------------------
# Ship base extraction (PlayerShipBase)
# -----------------------------

def find_player_ship_bases(root: dict) -> list:
    bases = deep_get(root, ["BaseContext", "PlayerStateData", "PersistentPlayerBases"], default=[])
    if not isinstance(bases, list):
        return []

    ship_bases = []
    for b in bases:
        if not isinstance(b, dict):
            continue

        bt = b.get("BaseType")
        bt_val = bt.get("PersistentBaseTypes") if isinstance(bt, dict) else bt
        if bt_val == "PlayerShipBase":
            ship_bases.append(b)

    return ship_bases


def get_base_objects_ref(base: dict):
    for path in (
        ["Objects"],
        ["Base", "Objects"],
        ["BaseData", "Objects"],
    ):
        if len(path) == 1:
            key = path[0]
            if isinstance(base.get(key), list):
                return base, key
        else:
            parent = deep_get(base, path[:-1])
            key = path[-1]
            if isinstance(parent, dict) and isinstance(parent.get(key), list):
                return parent, key
    return None, None


def get_base_objects(base: dict):
    parent, key = get_base_objects_ref(base)
    if parent is None:
        return []
    v = parent.get(key)
    return v if isinstance(v, list) else []


# -----------------------------
# Corvette ship record harvesting (name + seed hex) + pairing
# -----------------------------

def looks_like_corvette_record(obj: dict) -> bool:
    if not isinstance(obj, dict):
        return False
    name = obj.get("Name")
    res = obj.get("Resource")
    if not isinstance(name, str) or not isinstance(res, dict):
        return False

    fn = res.get("Filename")
    seed = res.get("Seed")
    if not (isinstance(fn, str) and fn.strip()):
        return False
    if not (isinstance(seed, list) and len(seed) >= 2):
        return False
    if not (isinstance(seed[1], str) and seed[1].lower().startswith("0x")):
        return False

    fn_u = fn.replace("\\", "/").upper()
    return "/BIGGS/" in fn_u


def walk_collect_corvette_records(node, out_list, in_shipownership=False):
    if isinstance(node, dict):
        if looks_like_corvette_record(node):
            out_list.append((node, in_shipownership))
        for k, v in node.items():
            walk_collect_corvette_records(v, out_list, in_shipownership or (k == "ShipOwnership"))
    elif isinstance(node, list):
        for it in node:
            walk_collect_corvette_records(it, out_list, in_shipownership)


def seed_hex_to_unix(seed_hex: str) -> int | None:
    if not isinstance(seed_hex, str) or not seed_hex.lower().startswith("0x"):
        return None
    try:
        return int(seed_hex, 16)
    except Exception:
        return None


def seed_hex_to_prefixes(seed_hex: str) -> list[str]:
    val = seed_hex_to_unix(seed_hex)
    if val is None:
        return []
    s = str(val)
    prefixes = [s]
    for drop in (1, 2, 3):
        if len(s) > drop:
            prefixes.append(s[:-drop])
    out = []
    for p in prefixes:
        if p not in out:
            out.append(p)
    return out


def collect_unix_timestamps_anywhere(node) -> set[int]:
    out = set()

    def rec(x):
        if isinstance(x, dict):
            for v in x.values():
                rec(v)
        elif isinstance(x, list):
            for it in x:
                rec(it)
        elif isinstance(x, int):
            if 946684800 <= x <= 4102444800:
                out.add(x)
        elif isinstance(x, str) and x.isdigit():
            try:
                iv = int(x)
                if 946684800 <= iv <= 4102444800:
                    out.add(iv)
            except Exception:
                pass

    rec(node)
    return out


def score_match(base_ts: set[int], seed_unix: int, prefixes: list[str]) -> int:
    if seed_unix in base_ts:
        return 300

    for window, sc in ((10, 250), (120, 200), (600, 160)):
        for t in base_ts:
            if abs(t - seed_unix) <= window:
                return sc

    base_strs = [str(t) for t in base_ts]
    for i, p in enumerate(prefixes):
        if p and any(s.startswith(p) for s in base_strs):
            return [140, 120, 100, 80][min(i, 3)]

    return 0


def format_corvette_display_name(nm: str, seed_hex: str) -> str:
    if isinstance(nm, str) and nm.strip():
        return nm.strip()
    return f"Unnamed Corvette (Seed {seed_hex})"


def corvette_info_from_shipownership_entry(ship: dict):
    if not looks_like_corvette_record(ship):
        return None

    nm_raw = ship.get("Name", "")
    nm_raw = nm_raw if isinstance(nm_raw, str) else ""
    seed_hex = deep_get(ship, ["Resource", "Seed"], default=[None, None])[1]
    if not isinstance(seed_hex, str) or not seed_hex.lower().startswith("0x"):
        return None

    return {
        "name": format_corvette_display_name(nm_raw, seed_hex),
        "seed": seed_hex.lower(),
    }


def pair_bases_to_corvette_info_by_seed_heuristic(
    root: dict,
    ship_bases: list[dict],
    excluded_base_indices: set[int] | None = None,
    excluded_seed_keys: set[str] | None = None,
) -> dict[int, dict]:
    excluded_base_indices = set(excluded_base_indices or ())
    excluded_seed_keys = {s.lower() for s in (excluded_seed_keys or set()) if isinstance(s, str) and s}

    raw_records = []
    walk_collect_corvette_records(root, raw_records)

    seen = set()
    records = []
    for rec, in_shipownership in raw_records:
        nm_raw = rec.get("Name", "")
        nm_raw = nm_raw if isinstance(nm_raw, str) else ""
        seed_hex = deep_get(rec, ["Resource", "Seed"], default=[None, None])[1]

        if not isinstance(seed_hex, str) or not seed_hex.lower().startswith("0x"):
            continue

        seed_unix = seed_hex_to_unix(seed_hex)
        if seed_unix is None:
            continue

        display_name = format_corvette_display_name(nm_raw, seed_hex)

        key = seed_hex.lower()
        if key in seen or key in excluded_seed_keys:
            continue
        seen.add(key)

        prefixes = seed_hex_to_prefixes(seed_hex)
        boost = 5 if in_shipownership else 0
        records.append((display_name, seed_hex, seed_unix, prefixes, boost))

    base_ts_list = [collect_unix_timestamps_anywhere(b) for b in ship_bases]

    candidates = []
    for base_i, base_ts in enumerate(base_ts_list):
        if base_i in excluded_base_indices:
            continue
        for (display_name, seed_hex, seed_unix, prefixes, boost) in records:
            sc = score_match(base_ts, seed_unix, prefixes)
            if sc > 0:
                candidates.append((sc, boost, base_i, display_name, seed_hex))

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)

    assigned_base = set(excluded_base_indices)
    assigned_seed = set(excluded_seed_keys)
    mapping = {}

    for sc, boost, base_i, display_name, seed_hex in candidates:
        if base_i in assigned_base:
            continue
        if seed_hex.lower() in assigned_seed:
            continue
        mapping[base_i] = {"name": display_name, "seed": seed_hex.lower()}
        assigned_base.add(base_i)
        assigned_seed.add(seed_hex.lower())

    return mapping


def pair_bases_to_corvette_info(root: dict, ship_bases: list[dict]) -> dict[int, dict]:
    mapping = {}
    claimed_seeds = set()

    for base_i, base in enumerate(ship_bases):
        ship, ship_i, pairing_method = find_shipownership_entry_for_base(root, base)
        if ship_i is None:
            continue

        info = corvette_info_from_shipownership_entry(ship)
        if not info:
            continue

        mapping[base_i] = {
            "name": info["name"],
            "seed": info["seed"],
            "ship_index": ship_i,
            "pairing": pairing_method or "userdata_index",
        }
        claimed_seeds.add(info["seed"].lower())

    fallback = pair_bases_to_corvette_info_by_seed_heuristic(
        root,
        ship_bases,
        excluded_base_indices=set(mapping),
        excluded_seed_keys=claimed_seeds,
    )

    for base_i, info in fallback.items():
        if base_i not in mapping:
            mapping[base_i] = {
                "name": info["name"],
                "seed": info["seed"],
                "pairing": "seed_heuristic",
            }

    if DEBUG_PAIRING:
        print("\n=== DEBUG: Corvette pairing ===")
        raw_records = []
        walk_collect_corvette_records(root, raw_records)
        print(f"Bases={len(ship_bases)} Records={len(raw_records)}\n")
        for i, b in enumerate(ship_bases):
            ga = b.get("GalacticAddress")
            _ship, ship_i, link_method = find_shipownership_entry_for_base(root, b)
            info = mapping.get(i)
            label = info["name"] if info else "<NO MATCH>"
            seed = info["seed"] if info else ""
            pairing = info.get("pairing", "") if info else ""
            print(f"Base[{i}] GA={ga} ShipOwnership={ship_i} link={link_method} -> {label} {seed} {pairing}")

    return mapping


# -----------------------------
# Backup + filenames
# -----------------------------

def safe_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in s)
    out = out.strip().strip(".")
    return out or "export"


def mandatory_backup(save_folder: str, backups_root: str) -> str:
    save_id = os.path.basename(os.path.abspath(save_folder))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_dir = os.path.join(backups_root, save_id, f"backup_{stamp}")
    os.makedirs(backup_dir, exist_ok=True)

    failures = []
    copied = 0
    for name in os.listdir(save_folder):
        src = os.path.join(save_folder, name)
        if os.path.isfile(src):
            try:
                shutil.copy2(src, os.path.join(backup_dir, name))
                copied += 1
            except Exception as e:
                failures.append(f"{name}: {e}")

    if copied == 0:
        raise RuntimeError(
            "Backup failed: no save files were copied before import.\n\n"
            f"Attempted backup folder:\n{backup_dir}"
        )

    if failures:
        details = "\n".join(failures[:8])
        raise RuntimeError(
            "Backup failed: not every file in the save folder could be copied.\n\n"
            f"Backup folder:\n{backup_dir}\n\n"
            f"Details:\n{details}"
        )

    return backup_dir


# -----------------------------
# Build file (wrapper) helpers
# -----------------------------

def utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_build_file(path: str) -> tuple[list, dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data, {"compat_mode": "raw-objects-list"}

    if isinstance(data, dict):
        objs = data.get("objects")
        if isinstance(objs, list):
            if data.get("format") != BUILD_FORMAT:
                raise ValueError(
                    f"Unsupported build wrapper format.\n\n"
                    f"Expected format: {BUILD_FORMAT}\n"
                    f"Found: {data.get('format')!r}"
                )

            version = data.get("version")
            if version not in SUPPORTED_BUILD_VERSIONS:
                raise ValueError(
                    "Unsupported build wrapper version.\n\n"
                    f"Supported version(s): {sorted(SUPPORTED_BUILD_VERSIONS)}\n"
                    f"Found: {version!r}"
                )

            meta = dict(data)
            meta.pop("objects", None)
            return objs, meta

        objs2 = data.get("Objects")
        if isinstance(objs2, list):
            meta = dict(data)
            meta.pop("Objects", None)
            meta["compat_mode"] = "Objects-wrapper"
            return objs2, meta

    raise ValueError(
        "Build file must be one of:\n"
        "- an official wrapper with 'format', 'version', and 'objects'\n"
        "- a raw JSON list representing Objects[] directly\n"
        "- a compatibility wrapper containing 'Objects'"
    )


def build_wrapper(objects: list, name: str, author: str) -> dict:
    return {
        "format": BUILD_FORMAT,
        "version": BUILD_VERSION,
        "name": name.strip() if isinstance(name, str) else "",
        "author": author.strip() if isinstance(author, str) else "",
        "created_utc": utc_now_iso_z(),
        "objects": objects
    }


# -----------------------------
# UI helpers for consistent warnings
# -----------------------------

def pre_convert_warning_gate(parent_window) -> bool:
    warnings = []
    if is_nms_running():
        warnings.append(
            "• No Man’s Sky appears to be RUNNING.\n"
            "  Close the game before converting to avoid corrupt/partial data."
        )

    warnings.append(
        "• Make sure the Corvette you want to export/import is NOT your active ship.\n"
        "  Switch to a different ship in-game, save, then fully close the game."
    )

    msg = "Before converting your save:\n\n" + "\n\n".join(warnings) + "\n\nContinue anyway?"
    return messagebox.askokcancel("Safety check", msg, parent=parent_window)


# -----------------------------
# Two-tab App
# -----------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = load_app_settings()
        self.workspace_root_override = str(self.settings.get("workspace_root", "") or "").strip()
        self._tracked_work_roots = normalize_recent_work_roots(self.settings.get("recent_work_roots", []))
        self._cleanup_tracked_work_roots()

        apply_dark_theme(self)
        self._icon_images = apply_app_icon(self)
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1200x760")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Map>", self._refresh_title_bar_theme, add="+")
        for delay in (0, 50, 200, 500):
            self.after(delay, self._refresh_title_bar_theme)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        self.export_tab = ExportTab(nb, self)
        self.import_tab = ImportTab(nb, self)

        nb.add(self.export_tab, text="Export")
        nb.add(self.import_tab, text="Import")

    def _refresh_title_bar_theme(self, *_):
        self.after_idle(lambda: apply_windows_title_bar_theme(self))

    def get_workspace_root_override(self) -> str:
        return self.workspace_root_override

    def set_workspace_root_override(self, path: str) -> bool:
        cleaned = os.path.abspath(path.strip()) if isinstance(path, str) and path.strip() else ""
        current = str(self.settings.get("workspace_root", "") or "").strip()
        if cleaned == current and cleaned == self.workspace_root_override:
            return True

        self.workspace_root_override = cleaned
        if cleaned:
            self.settings["workspace_root"] = cleaned
        else:
            self.settings.pop("workspace_root", None)
        return save_app_settings(self.settings)

    def refresh_workspace_views(self):
        for tab in (self.export_tab, self.import_tab):
            if hasattr(tab, "_refresh_workspace_root_display"):
                tab._refresh_workspace_root_display()

    def _save_tracked_work_roots(self):
        current = normalize_recent_work_roots(self.settings.get("recent_work_roots", []))
        desired = list(self._tracked_work_roots[:MAX_TRACKED_WORK_ROOTS])
        if desired == current:
            return True

        if desired:
            self.settings["recent_work_roots"] = desired
        else:
            self.settings.pop("recent_work_roots", None)
        return save_app_settings(self.settings)

    def register_work_root(self, work_root: str):
        if not isinstance(work_root, str) or not work_root.strip():
            return

        path = os.path.abspath(work_root.strip())
        if os.path.basename(path).lower() != "work":
            return

        existing = [p for p in self._tracked_work_roots if p.lower() != path.lower()]
        desired = [path] + existing[:MAX_TRACKED_WORK_ROOTS - 1]
        if desired == list(self._tracked_work_roots):
            return

        self._tracked_work_roots = desired
        self._save_tracked_work_roots()

    def _any_operation_busy(self) -> bool:
        tabs = [getattr(self, "export_tab", None), getattr(self, "import_tab", None)]
        return any(bool(getattr(tab, "_busy", False)) for tab in tabs if tab is not None)

    def _cleanup_tracked_work_roots(self):
        for work_root in list(self._tracked_work_roots):
            clean_transient_work_root(work_root)

    def _on_close(self):
        if self._any_operation_busy():
            msg = (
                "An export or import operation is still running.\n\n"
                "If you close now, temporary Work files may be left behind.\n\n"
                "Close anyway?"
            )
            if not messagebox.askokcancel("Close app", msg, parent=self):
                return
            self.destroy()
            return

        self._cleanup_tracked_work_roots()
        self.destroy()


class ExportTab(ttk.Frame):
    def __init__(self, parent, root_app: App):
        super().__init__(parent, padding=10)
        self.root_app = root_app

        # state
        self.save_folder = tk.StringVar()
        self.save_folder_display = tk.StringVar(value="No save folder selected.")
        self.json_path = tk.StringVar()
        self.json_path_display = tk.StringVar(value="No converted JSON loaded.")
        self.ship_label_var = tk.StringVar()
        self.workspace_root_display = tk.StringVar()
        self.workspace_mode_var = tk.StringVar()
        self.details_status_var = tk.StringVar(value="Technical details are hidden.")
        self.platform_choice = tk.StringVar(value="Auto-detect")
        self.show_details_var = tk.BooleanVar(value=False)

        # SLOT state
        self.slot_label_var = tk.StringVar()
        self._slots: list[dict] = []
        self._selected_slot: dict | None = None

        self.ship_bases = []
        self.ship_labels = []
        self.ship_names_only = []
        self.ship_seeds = []
        self.last_loaded_root = None
        self.active_seed = ""
        self.platform_format = ""

        # workspace
        self.tool_root = ""
        self.backups_dir = ""
        self.builds_dir = ""
        self.work_root = ""
        self.export_work_dir = ""
        self.import_work_dir = ""
        self.save_id = ""

        top = ttk.Frame(self)
        top.pack(fill="x")

        self._busy = False

        self.choose_folder_btn = ttk.Button(top, text="Choose SAVE Folder (Export)", command=self.choose_folder)
        self.choose_folder_btn.pack(side="left")
        ttk.Label(top, textvariable=self.save_folder_display, style="Path.TLabel").pack(side="left", padx=10, fill="x", expand=True)

        self.convert_btn = ttk.Button(top, text="Convert + Load Corvettes", command=self.convert_and_load)
        self.convert_btn.pack(side="left", padx=10)

        self.export_btn = ttk.Button(top, text="Export Build", command=self.export_selected, state="disabled", style="Accent.TButton")
        self.export_btn.pack(side="left", padx=10)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        ttk.Label(
            self,
            text="Choose a save folder, close the game, then convert the slot you want to read.",
            style="Hint.TLabel"
        ).pack(fill="x", pady=(8, 0))

        workspace_row = ttk.Frame(self)
        workspace_row.pack(fill="x", pady=(10, 0))
        ttk.Label(workspace_row, text="Workspace Root:").pack(side="left")
        self.choose_workspace_btn = ttk.Button(workspace_row, text="Choose Workspace Root", command=self.choose_workspace_root)
        self.choose_workspace_btn.pack(side="left", padx=(8, 0))
        self.default_workspace_btn = ttk.Button(workspace_row, text="Use Default", command=self.use_default_workspace_root)
        self.default_workspace_btn.pack(side="left", padx=(8, 0))
        ttk.Label(workspace_row, textvariable=self.workspace_root_display, style="Path.TLabel").pack(
            side="left", padx=10, fill="x", expand=True
        )

        ttk.Label(self, textvariable=self.workspace_mode_var, style="Hint.TLabel").pack(fill="x", pady=(4, 0))

        platform_row = ttk.Frame(self)
        platform_row.pack(fill="x", pady=(10, 0))
        ttk.Label(platform_row, text="Platform:").pack(side="left")
        self.platform_combo = ttk.Combobox(
            platform_row,
            textvariable=self.platform_choice,
            state="readonly",
            width=16,
            values=PLATFORM_LABELS
        )
        self.platform_combo.pack(side="left", padx=(8, 0))
        ttk.Label(
            platform_row,
            text="Use Auto-detect for normal saves. Pick one manually if detection is unclear or you switch formats.",
            style="Hint.TLabel"
        ).pack(side="left", padx=12)

        mid = ttk.Frame(self)
        mid.pack(fill="x", pady=(10, 0))

        # Left: Slot
        left = ttk.Frame(mid)
        left.pack(side="left", fill="x", expand=True)

        ttk.Label(left, text="Slot:").pack(side="left")
        self.slot_combo = ttk.Combobox(left, textvariable=self.slot_label_var, state="readonly", width=22)
        self.slot_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.slot_combo.bind("<<ComboboxSelected>>", self.on_slot_changed)  # if you have this handler

        # Right: Corvette
        right = ttk.Frame(mid)
        right.pack(side="left", fill="x", expand=True, padx=(12, 0))

        ttk.Label(right, text="Corvette:").pack(side="left")
        self.ship_combo = ttk.Combobox(right, textvariable=self.ship_label_var, state="readonly", width=60)
        self.ship_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.ship_combo.bind("<<ComboboxSelected>>", self.on_ship_selected)

        details_bar = ttk.Frame(self)
        details_bar.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(
            details_bar,
            text="Show technical details",
            variable=self.show_details_var,
            command=self._toggle_details
        ).pack(side="left")
        ttk.Label(details_bar, textvariable=self.details_status_var, style="Hint.TLabel").pack(side="left", padx=(12, 0))

        self.details_frame = ttk.Labelframe(self, text="Technical Details")
        details_info = ttk.Frame(self.details_frame)
        details_info.pack(fill="x", pady=(0, 8))
        ttk.Label(details_info, text="Decoded JSON (Work\\Export):").pack(side="left")
        ttk.Label(details_info, textvariable=self.json_path_display, style="Path.TLabel").pack(
            side="left", padx=8, fill="x", expand=True
        )

        self.text = ScrolledText(self.details_frame, wrap="none", height=24)
        self.text.configure(
            bg="#151515",
            fg="#e6e6e6",
            insertbackground="#e6e6e6",
            selectbackground="#404040",
            selectforeground="#ffffff"
        )
        self.text.pack(fill="both", expand=True)

        self._refresh_workspace_root_display()

    def _set_busy(self, busy: bool, status: str | None = None):
        self._busy = busy
        if status is not None:
            self.status_var.set(status)

        self.choose_folder_btn.config(state="disabled" if busy else "normal")
        self.choose_workspace_btn.config(state="disabled" if busy else "normal")
        self.default_workspace_btn.config(state="disabled" if busy else "normal")
        self.convert_btn.config(state="disabled" if busy else "normal")
        self.platform_combo.config(state="disabled" if busy else "readonly")
        self.slot_combo.config(state="disabled" if busy else "readonly")
        self.ship_combo.config(state="disabled" if busy else "readonly")

        if busy:
            self.export_btn.config(state="disabled")

        try:
            self.root_app.configure(cursor="watch" if busy else "")
            self.root_app.update_idletasks()
        except Exception:
            pass

    def _set_workspace_from_dict(self, d: dict):
        self.tool_root = d["tool_root"]
        self.backups_dir = d["backups_dir"]
        self.builds_dir = d["builds_dir"]
        self.work_root = d["work_root"]
        self.export_work_dir = d["export_work_dir"]
        self.import_work_dir = d["import_work_dir"]
        self.save_id = d["save_id"]
        self.root_app.register_work_root(self.work_root)
        self._refresh_workspace_root_display()

    def _clear_loaded_state(self):
        self.ship_bases = []
        self.ship_labels = []
        self.ship_names_only = []
        self.ship_seeds = []
        self.last_loaded_root = None
        self.active_seed = ""
        self.platform_format = ""
        self.json_path.set("")
        self.json_path_display.set("No converted JSON loaded.")
        self.ship_combo["values"] = []
        self.export_btn.config(state="disabled")
        self.text.delete("1.0", tk.END)
        self.status_var.set("Ready.")
        self.ship_combo.set("")
        self.ship_label_var.set("")
        self._refresh_details_status()

    def _refresh_details_status(self):
        if self.show_details_var.get():
            if self.json_path.get().strip():
                self.details_status_var.set("Showing decoded Objects[] for the selected corvette.")
            else:
                self.details_status_var.set("Technical details will appear after a slot is loaded.")
        else:
            self.details_status_var.set("Technical details are hidden.")

    def _toggle_details(self):
        if self.show_details_var.get():
            self.details_frame.pack(fill="both", expand=True, pady=(10, 0))
        else:
            self.details_frame.pack_forget()
        self._refresh_details_status()

    def _refresh_workspace_root_display(self):
        current_save = self.save_folder.get().strip()
        if current_save:
            override = self.root_app.get_workspace_root_override()
            preview = override or default_workspace_root_for_save(current_save)
        elif self.tool_root:
            preview = self.tool_root
        else:
            preview = self.root_app.get_workspace_root_override()

        if preview:
            self.workspace_root_display.set(short_display_path(preview))
        else:
            self.workspace_root_display.set("Choose a save folder to preview the default workspace root.")

        if self.root_app.get_workspace_root_override():
            self.workspace_mode_var.set("Custom workspace root is active for both tabs.")
        else:
            self.workspace_mode_var.set("Default workspace root lives next to the selected save folder.")

    def choose_workspace_root(self):
        current_save = self.save_folder.get().strip()
        initial_dir = self.tool_root or self.root_app.get_workspace_root_override() or APP_DIR
        folder = filedialog.askdirectory(title="Choose a workspace root for Backups, Builds, and Work", initialdir=initial_dir)
        if folder:
            persisted = self.root_app.set_workspace_root_override(folder)
            if current_save:
                d = ensure_tool_dirs_for_save(current_save, self.root_app.get_workspace_root_override())
                self._set_workspace_from_dict(d)
                self._clear_loaded_state()
            else:
                self.tool_root = os.path.abspath(folder)
            self.root_app.refresh_workspace_views()
            if not persisted:
                messagebox.showwarning(
                    "Settings not saved",
                    "The workspace root changed for this session, but the app could not save the preference to disk.",
                    parent=self
                )

    def use_default_workspace_root(self):
        persisted = self.root_app.set_workspace_root_override("")
        current_save = self.save_folder.get().strip()
        if current_save:
            d = ensure_tool_dirs_for_save(current_save, "")
            self._set_workspace_from_dict(d)
            self._clear_loaded_state()
        else:
            self.tool_root = ""
        self.root_app.refresh_workspace_views()
        if not persisted:
            messagebox.showwarning(
                "Settings not saved",
                "The workspace root was reset for this session, but the app could not save the preference to disk.",
                parent=self
            )

    def _populate_slots(self, folder: str):
        self._slots = list_save_slots(folder)
        labels = [slot_display_label(s) for s in self._slots]
        self.slot_combo["values"] = labels
        if labels:
            self.slot_combo.current(0)
            self._selected_slot = self._slots[0]
            self.slot_label_var.set(labels[0])
        else:
            self._selected_slot = None
            self.slot_label_var.set("")
            self.slot_combo["values"] = []

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select your NMS SAVE folder to EXPORT from")
        if folder:
            self.save_folder.set(folder)
            self.save_folder_display.set(short_display_path(folder))
            d = ensure_tool_dirs_for_save(folder, self.root_app.get_workspace_root_override())
            self._set_workspace_from_dict(d)
            self._clear_loaded_state()
            self._populate_slots(folder)

    def on_slot_changed(self, *_):
        if self._busy:
            return
        idx = self.slot_combo.current()
        self._clear_loaded_state()  # clear ship/json first

        if 0 <= idx < len(self._slots):
            self._selected_slot = self._slots[idx]
            self.slot_label_var.set(self.slot_combo["values"][idx])
        else:
            self._selected_slot = None
            self.slot_label_var.set("")

    def _selected_restore_file(self) -> str:
        # We convert from Restore Point file by default (even number / save2.hg for slot 1)
        if not self._selected_slot:
            return "save2.hg"
        return self._selected_slot["restore_file"]

    def _selected_auto_file(self) -> str:
        if not self._selected_slot:
            return "save.hg"
        return self._selected_slot["auto_file"]

    def convert_and_load(self):
        if self._busy:
            return

        folder = self.save_folder.get().strip()
        if not folder:
            messagebox.showerror("Missing folder", "Choose the export save folder first.", parent=self)
            return

        if not os.path.isfile(LIBNOM_EXE):
            messagebox.showerror(
                "libNOM missing",
                "libNOM CLI not found.\n\n"
                f"Expected:\n{LIBNOM_EXE}\n\n"
                "Fix: put libNOM.io.cli.exe inside the app's libNOM folder.",
                parent=self
            )
            return

        if not self._selected_slot:
            messagebox.showerror(
                "No slots found",
                "No save.hg/save2.hg/save3.hg... files were detected in that folder.",
                parent=self
            )
            return

        d = ensure_tool_dirs_for_save(folder, self.root_app.get_workspace_root_override())
        self._set_workspace_from_dict(d)

        if not pre_convert_warning_gate(self):
            return

        self.export_btn.config(state="disabled")
        self.ship_combo["values"] = []
        self.text.delete("1.0", tk.END)

        slot_num = int(self._selected_slot["slot"])
        restore_file = self._selected_restore_file()

        self._set_busy(True, f"Converting Slot {slot_num} ({restore_file}) to JSON…")

        def worker():
            try:
                platform_format = resolve_platform_format(folder, restore_file, self.platform_choice.get())
                self.after(0, lambda: self.status_var.set(
                    f"Detected: {platform_format} — Converting Slot {slot_num}…"
                ))

                out_json = run_convert_savehg_to_json(folder, restore_file, self.export_work_dir, self.save_id, slot_num)

                self.after(0, lambda: self.status_var.set("Loading JSON…"))
                with open(out_json, "r", encoding="utf-8") as f:
                    data = json.load(f)

                self.after(0, lambda: self.status_var.set("Scanning corvettes…"))
                ship_bases = find_player_ship_bases(data)
                if not ship_bases:
                    raise RuntimeError(
                        "Converted JSON loaded, but no Corvette bases were found at:\n"
                        "BaseContext → PlayerStateData → PersistentPlayerBases (BaseType=PlayerShipBase)"
                    )

                info_by_base_index = pair_bases_to_corvette_info(data, ship_bases)

                _primary_i, active_seed = get_active_ship_reference(data)

                labels, names_only, seeds = [], [], []
                for i, b in enumerate(ship_bases):
                    info = info_by_base_index.get(i)
                    if info:
                        nm = info["name"]
                        seed = info["seed"]
                    else:
                        ga = b.get("GalacticAddress")
                        nm = "Corvette (Unknown)" + (f" @ {ga}" if isinstance(ga, int) else "")
                        seed = ""

                    obj_count = len(get_base_objects(b))
                    is_active, _active_i, _base_ship_i, _active_seed = base_matches_active_ship(data, b, seed)
                    active_tag = " [ACTIVE]" if is_active else ""

                    labels.append(f"{i+1}. {nm}{active_tag}  (Objects: {obj_count})")
                    names_only.append(nm)
                    seeds.append(seed)

                def on_success():
                    self.platform_format = platform_format
                    self.json_path.set(out_json)
                    self.json_path_display.set(short_display_path(out_json))
                    self.last_loaded_root = data
                    self.active_seed = active_seed

                    self.ship_bases = ship_bases
                    self.ship_labels = labels
                    self.ship_names_only = names_only
                    self.ship_seeds = seeds

                    self.ship_combo["values"] = self.ship_labels
                    self.ship_combo.current(0)

                    self.export_btn.config(state="normal")
                    self.on_ship_selected()
                    self._refresh_details_status()
                    self._set_busy(False, "Ready.")

                self.after(0, on_success)

            except subprocess.CalledProcessError as e:
                def on_fail():
                    stdout = (getattr(e, "stdout", "") or "").strip()
                    stderr = (getattr(e, "stderr", "") or "").strip()
                    details = "\n\n".join([t for t in (stdout, stderr) if t]) or str(e)
                    messagebox.showerror("Convert failed", "libNOM failed.\n\n" + details, parent=self)
                    self._set_busy(False, "Ready.")
                self.after(0, on_fail)

            except Exception as e:
                def on_fail2():
                    messagebox.showerror("Error", str(e), parent=self)
                    self._set_busy(False, "Ready.")
                self.after(0, on_fail2)

        threading.Thread(target=worker, daemon=True).start()

    def on_ship_selected(self, *_):
        idx = self.ship_combo.current()
        if idx < 0 or idx >= len(self.ship_bases):
            return
        base = self.ship_bases[idx]
        payload = get_base_objects(base)
        pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, pretty)

    def _block_if_active_selected(self, action_name: str) -> bool:
        if not isinstance(self.last_loaded_root, dict):
            return True

        sel_i = self.ship_combo.current()
        if sel_i < 0 or sel_i >= len(self.ship_bases):
            return True

        selected_base = self.ship_bases[sel_i]
        sel_seed = (self.ship_seeds[sel_i] or "").lower() if 0 <= sel_i < len(self.ship_seeds) else ""
        is_active, active_i, sel_ship_i, active_seed = base_matches_active_ship(self.last_loaded_root, selected_base, sel_seed)

        if DEBUG_PAIRING:
            label = self.ship_names_only[sel_i] if sel_i < len(self.ship_names_only) else "<unknown>"
            print(f"\n=== DEBUG: Active-ship check ({action_name}) [EXPORT] ===")
            print("Selected:", label)
            print("PrimaryShip index:", active_i)
            print("Selected ship index:", sel_ship_i)
            print("Active seed:", active_seed)
            print("Selected seed:", sel_seed)

        if active_i is None and not active_seed:
            ok = messagebox.askokcancel(
                "Can't verify active ship",
                f"I couldn't determine which Corvette is active from this converted save JSON.\n\n"
                f"Make sure the Corvette you're about to {action_name.lower()} is NOT active.\n\nContinue?",
                parent=self
            )
            return ok

        if is_active:
            label = self.ship_names_only[sel_i] if sel_i < len(self.ship_names_only) else "Selected Corvette"
            messagebox.showwarning(
                "Active ship detected",
                f"{action_name} blocked:\n\n"
                f"'{label}' appears to be your CURRENT ACTIVE SHIP.\n\n"
                "Switch to a different ship in-game, save, fully close the game, then convert again.",
                parent=self
            )
            return False

        return True

    def export_selected(self):
        idx = self.ship_combo.current()
        if idx < 0 or idx >= len(self.ship_bases):
            messagebox.showerror("Nothing selected", "Select a corvette first.", parent=self)
            return

        if not self._block_if_active_selected("Export"):
            return

        base = self.ship_bases[idx]
        objects = get_base_objects(base)
        if not isinstance(objects, list) or not objects:
            messagebox.showwarning("No objects", "This corvette has no Objects[] to export.", parent=self)
            return

        default_build_name = self.ship_names_only[idx] if idx < len(self.ship_names_only) else f"Corvette {idx+1}"
        build_name = simpledialog.askstring("Build name", "Build name:", initialvalue=default_build_name, parent=self)
        if build_name is None:
            return

        author = simpledialog.askstring(
            "Author (optional)",
            "Author name (optional — leave blank for anonymous):",
            initialvalue="",
            parent=self
        )
        if author is None:
            return

        wrapper = build_wrapper(objects, build_name, author or "")
        ship_name_safe = safe_filename(build_name)
        default_name = f"{idx+1}_{ship_name_safe}_build.json"

        out_path = filedialog.asksaveasfilename(
            title="Save exported Corvette build as...",
            defaultextension=".json",
            initialdir=self.builds_dir if self.builds_dir else None,
            initialfile=default_name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not out_path:
            return

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(wrapper, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Export complete", f"Exported build ({len(objects)} objects) to:\n{out_path}", parent=self)
        except Exception as e:
            messagebox.showerror("Export failed", str(e), parent=self)


class ImportTab(ttk.Frame):
    def __init__(self, parent, root_app: App):
        super().__init__(parent, padding=10)
        self.root_app = root_app

        self.save_folder = tk.StringVar()
        self.save_folder_display = tk.StringVar(value="No target save folder selected.")
        self.json_path = tk.StringVar()
        self.json_path_display = tk.StringVar(value="No converted JSON loaded.")
        self.ship_label_var = tk.StringVar()
        self.workspace_root_display = tk.StringVar()
        self.workspace_mode_var = tk.StringVar()
        self.details_status_var = tk.StringVar(value="Technical details are hidden.")
        self.platform_choice = tk.StringVar(value="Auto-detect")
        self.show_details_var = tk.BooleanVar(value=False)

        # SLOT state
        self.slot_label_var = tk.StringVar()
        self._slots: list[dict] = []
        self._selected_slot: dict | None = None

        self.ship_bases = []
        self.ship_labels = []
        self.ship_names_only = []
        self.ship_seeds = []
        self.last_loaded_root = None
        self.active_seed = ""
        self.platform_format = ""

        self.tool_root = ""
        self.backups_dir = ""
        self.builds_dir = ""
        self.work_root = ""
        self.export_work_dir = ""
        self.import_work_dir = ""
        self.save_id = ""

        top = ttk.Frame(self)
        top.pack(fill="x")

        self._busy = False

        self.choose_folder_btn = ttk.Button(top, text="Choose TARGET Save Folder (Import)", command=self.choose_folder)
        self.choose_folder_btn.pack(side="left")
        ttk.Label(top, textvariable=self.save_folder_display, style="Path.TLabel").pack(side="left", padx=10, fill="x", expand=True)

        self.convert_btn = ttk.Button(top, text="Convert + Load Corvettes", command=self.convert_and_load)
        self.convert_btn.pack(side="left", padx=10)

        self.import_btn = ttk.Button(top, text="Import Build (Replace)", command=self.import_into_selected, state="disabled", style="Accent.TButton")
        self.import_btn.pack(side="left", padx=10)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        ttk.Label(
            self,
            text="Choose the target save folder, close the game, then load the slot you want to overwrite.",
            style="Hint.TLabel"
        ).pack(fill="x", pady=(8, 0))

        workspace_row = ttk.Frame(self)
        workspace_row.pack(fill="x", pady=(10, 0))
        ttk.Label(workspace_row, text="Workspace Root:").pack(side="left")
        self.choose_workspace_btn = ttk.Button(workspace_row, text="Choose Workspace Root", command=self.choose_workspace_root)
        self.choose_workspace_btn.pack(side="left", padx=(8, 0))
        self.default_workspace_btn = ttk.Button(workspace_row, text="Use Default", command=self.use_default_workspace_root)
        self.default_workspace_btn.pack(side="left", padx=(8, 0))
        ttk.Label(workspace_row, textvariable=self.workspace_root_display, style="Path.TLabel").pack(
            side="left", padx=10, fill="x", expand=True
        )

        ttk.Label(self, textvariable=self.workspace_mode_var, style="Hint.TLabel").pack(fill="x", pady=(4, 0))

        platform_row = ttk.Frame(self)
        platform_row.pack(fill="x", pady=(10, 0))
        ttk.Label(platform_row, text="Platform:").pack(side="left")
        self.platform_combo = ttk.Combobox(
            platform_row,
            textvariable=self.platform_choice,
            state="readonly",
            width=16,
            values=PLATFORM_LABELS
        )
        self.platform_combo.pack(side="left", padx=(8, 0))
        ttk.Label(
            platform_row,
            text="Use Auto-detect for normal saves. Pick one manually if detection is unclear or you switch formats.",
            style="Hint.TLabel"
        ).pack(side="left", padx=12)

        mid = ttk.Frame(self)
        mid.pack(fill="x", pady=(10, 0))

        # Left: Slot
        left = ttk.Frame(mid)
        left.pack(side="left", fill="x", expand=True)

        ttk.Label(left, text="Slot:").pack(side="left")
        self.slot_combo = ttk.Combobox(left, textvariable=self.slot_label_var, state="readonly", width=22)
        self.slot_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.slot_combo.bind("<<ComboboxSelected>>", self.on_slot_changed)

        # Right: Corvette
        right = ttk.Frame(mid)
        right.pack(side="left", fill="x", expand=True, padx=(12, 0))

        ttk.Label(right, text="Target Corvette:").pack(side="left")
        self.ship_combo = ttk.Combobox(right, textvariable=self.ship_label_var, state="readonly", width=60)
        self.ship_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.ship_combo.bind("<<ComboboxSelected>>", self.on_ship_selected)

        details_bar = ttk.Frame(self)
        details_bar.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(
            details_bar,
            text="Show technical details",
            variable=self.show_details_var,
            command=self._toggle_details
        ).pack(side="left")
        ttk.Label(details_bar, textvariable=self.details_status_var, style="Hint.TLabel").pack(side="left", padx=(12, 0))

        self.details_frame = ttk.Labelframe(self, text="Technical Details")
        details_info = ttk.Frame(self.details_frame)
        details_info.pack(fill="x", pady=(0, 8))
        ttk.Label(details_info, text="Decoded JSON (Work\\Import):").pack(side="left")
        ttk.Label(details_info, textvariable=self.json_path_display, style="Path.TLabel").pack(
            side="left", padx=8, fill="x", expand=True
        )

        self.text = ScrolledText(self.details_frame, wrap="none", height=24)
        self.text.configure(
            bg="#151515",
            fg="#e6e6e6",
            insertbackground="#e6e6e6",
            selectbackground="#404040",
            selectforeground="#ffffff"
        )
        self.text.pack(fill="both", expand=True)

        self._refresh_workspace_root_display()

    def _set_busy(self, busy: bool, status: str | None = None):
        self._busy = busy
        if status is not None:
            self.status_var.set(status)

        self.choose_folder_btn.config(state="disabled" if busy else "normal")
        self.choose_workspace_btn.config(state="disabled" if busy else "normal")
        self.default_workspace_btn.config(state="disabled" if busy else "normal")
        self.convert_btn.config(state="disabled" if busy else "normal")
        self.platform_combo.config(state="disabled" if busy else "readonly")
        self.slot_combo.config(state="disabled" if busy else "readonly")
        self.ship_combo.config(state="disabled" if busy else "readonly")

        if busy:
            self.import_btn.config(state="disabled")

        try:
            self.root_app.configure(cursor="watch" if busy else "")
            self.root_app.update_idletasks()
        except Exception:
            pass

        if not busy and isinstance(self.last_loaded_root, dict) and self.ship_bases:
            self.import_btn.config(state="normal")

    def _set_workspace_from_dict(self, d: dict):
        self.tool_root = d["tool_root"]
        self.backups_dir = d["backups_dir"]
        self.builds_dir = d["builds_dir"]
        self.work_root = d["work_root"]
        self.export_work_dir = d["export_work_dir"]
        self.import_work_dir = d["import_work_dir"]
        self.save_id = d["save_id"]
        self.root_app.register_work_root(self.work_root)
        self._refresh_workspace_root_display()

    def _clear_loaded_state(self):
        self.ship_bases = []
        self.ship_labels = []
        self.ship_names_only = []
        self.ship_seeds = []
        self.last_loaded_root = None
        self.active_seed = ""
        self.platform_format = ""
        self.json_path.set("")
        self.json_path_display.set("No converted JSON loaded.")
        self.ship_combo["values"] = []
        self.import_btn.config(state="disabled")
        self.text.delete("1.0", tk.END)
        self.status_var.set("Ready.")
        self.ship_combo.set("")
        self.ship_label_var.set("")
        self._refresh_details_status()

    def _refresh_details_status(self):
        if self.show_details_var.get():
            if self.json_path.get().strip():
                self.details_status_var.set("Showing decoded Objects[] for the selected target corvette.")
            else:
                self.details_status_var.set("Technical details will appear after a slot is loaded.")
        else:
            self.details_status_var.set("Technical details are hidden.")

    def _toggle_details(self):
        if self.show_details_var.get():
            self.details_frame.pack(fill="both", expand=True, pady=(10, 0))
        else:
            self.details_frame.pack_forget()
        self._refresh_details_status()

    def _refresh_workspace_root_display(self):
        current_save = self.save_folder.get().strip()
        if current_save:
            override = self.root_app.get_workspace_root_override()
            preview = override or default_workspace_root_for_save(current_save)
        elif self.tool_root:
            preview = self.tool_root
        else:
            preview = self.root_app.get_workspace_root_override()

        if preview:
            self.workspace_root_display.set(short_display_path(preview))
        else:
            self.workspace_root_display.set("Choose a save folder to preview the default workspace root.")

        if self.root_app.get_workspace_root_override():
            self.workspace_mode_var.set("Custom workspace root is active for both tabs.")
        else:
            self.workspace_mode_var.set("Default workspace root lives next to the selected save folder.")

    def choose_workspace_root(self):
        current_save = self.save_folder.get().strip()
        initial_dir = self.tool_root or self.root_app.get_workspace_root_override() or APP_DIR
        folder = filedialog.askdirectory(title="Choose a workspace root for Backups, Builds, and Work", initialdir=initial_dir)
        if folder:
            persisted = self.root_app.set_workspace_root_override(folder)
            if current_save:
                d = ensure_tool_dirs_for_save(current_save, self.root_app.get_workspace_root_override())
                self._set_workspace_from_dict(d)
                self._clear_loaded_state()
            else:
                self.tool_root = os.path.abspath(folder)
            self.root_app.refresh_workspace_views()
            if not persisted:
                messagebox.showwarning(
                    "Settings not saved",
                    "The workspace root changed for this session, but the app could not save the preference to disk.",
                    parent=self
                )

    def use_default_workspace_root(self):
        persisted = self.root_app.set_workspace_root_override("")
        current_save = self.save_folder.get().strip()
        if current_save:
            d = ensure_tool_dirs_for_save(current_save, "")
            self._set_workspace_from_dict(d)
            self._clear_loaded_state()
        else:
            self.tool_root = ""
        self.root_app.refresh_workspace_views()
        if not persisted:
            messagebox.showwarning(
                "Settings not saved",
                "The workspace root was reset for this session, but the app could not save the preference to disk.",
                parent=self
            )

    def _populate_slots(self, folder: str):
        self._slots = list_save_slots(folder)
        labels = [slot_display_label(s) for s in self._slots]
        self.slot_combo["values"] = labels
        if labels:
            self.slot_combo.current(0)
            self._selected_slot = self._slots[0]
            self.slot_label_var.set(labels[0])
        else:
            self._selected_slot = None
            self.slot_label_var.set("")
            self.slot_combo["values"] = []

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select your TARGET NMS save folder to IMPORT into")
        if folder:
            self.save_folder.set(folder)
            self.save_folder_display.set(short_display_path(folder))
            d = ensure_tool_dirs_for_save(folder, self.root_app.get_workspace_root_override())
            self._set_workspace_from_dict(d)
            self._clear_loaded_state()
            self._populate_slots(folder)

    def on_slot_changed(self, *_):
        if self._busy:
            return
        idx = self.slot_combo.current()
        self._clear_loaded_state()  # clear ship/json first

        if 0 <= idx < len(self._slots):
            self._selected_slot = self._slots[idx]
            self.slot_label_var.set(self.slot_combo["values"][idx])
        else:
            self._selected_slot = None
            self.slot_label_var.set("")

    def _selected_restore_file(self) -> str:
        if not self._selected_slot:
            return "save2.hg"
        return self._selected_slot["restore_file"]

    def _selected_auto_file(self) -> str:
        if not self._selected_slot:
            return "save.hg"
        return self._selected_slot["auto_file"]

    def convert_and_load(self):
        if self._busy:
            return

        folder = self.save_folder.get().strip()
        if not folder:
            messagebox.showerror("Missing folder", "Choose the target save folder first.", parent=self)
            return

        if not os.path.isfile(LIBNOM_EXE):
            messagebox.showerror(
                "libNOM missing",
                "libNOM CLI not found.\n\n"
                f"Expected:\n{LIBNOM_EXE}\n\n"
                "Fix: put libNOM.io.cli.exe inside the app's libNOM folder.",
                parent=self
            )
            return

        if not self._selected_slot:
            messagebox.showerror(
                "No slots found",
                "No save.hg/save2.hg/save3.hg... files were detected in that folder.",
                parent=self
            )
            return

        d = ensure_tool_dirs_for_save(folder, self.root_app.get_workspace_root_override())
        self._set_workspace_from_dict(d)

        if not pre_convert_warning_gate(self):
            return

        self.import_btn.config(state="disabled")
        self.ship_combo["values"] = []
        self.text.delete("1.0", tk.END)

        slot_num = int(self._selected_slot["slot"])
        restore_file = self._selected_restore_file()

        self._set_busy(True, f"Converting Slot {slot_num} ({restore_file}) to JSON…")

        def worker():
            try:
                platform_format = resolve_platform_format(folder, restore_file, self.platform_choice.get())
                self.after(0, lambda: self.status_var.set(
                    f"Detected: {platform_format} — Converting Slot {slot_num}…"
                ))

                out_json = run_convert_savehg_to_json(folder, restore_file, self.import_work_dir, self.save_id, slot_num)

                self.after(0, lambda: self.status_var.set("Loading JSON…"))
                with open(out_json, "r", encoding="utf-8") as f:
                    data = json.load(f)

                self.after(0, lambda: self.status_var.set("Scanning corvettes…"))
                ship_bases = find_player_ship_bases(data)
                if not ship_bases:
                    raise RuntimeError(
                        "Converted JSON loaded, but no Corvette bases were found at:\n"
                        "BaseContext → PlayerStateData → PersistentPlayerBases (BaseType=PlayerShipBase)"
                    )

                info_by_base_index = pair_bases_to_corvette_info(data, ship_bases)

                _primary_i, active_seed = get_active_ship_reference(data)

                labels, names_only, seeds = [], [], []
                for i, b in enumerate(ship_bases):
                    info = info_by_base_index.get(i)
                    if info:
                        nm = info["name"]
                        seed = info["seed"]
                    else:
                        ga = b.get("GalacticAddress")
                        nm = "Corvette (Unknown)" + (f" @ {ga}" if isinstance(ga, int) else "")
                        seed = ""

                    obj_count = len(get_base_objects(b))
                    is_active, _active_i, _base_ship_i, _active_seed = base_matches_active_ship(data, b, seed)
                    active_tag = " [ACTIVE]" if is_active else ""

                    labels.append(f"{i+1}. {nm}{active_tag}  (Objects: {obj_count})")
                    names_only.append(nm)
                    seeds.append(seed)

                def on_success():
                    self.platform_format = platform_format
                    self.json_path.set(out_json)
                    self.json_path_display.set(short_display_path(out_json))
                    self.last_loaded_root = data
                    self.active_seed = active_seed

                    self.ship_bases = ship_bases
                    self.ship_labels = labels
                    self.ship_names_only = names_only
                    self.ship_seeds = seeds

                    self.ship_combo["values"] = self.ship_labels
                    self.ship_combo.current(0)

                    self.import_btn.config(state="normal")
                    self.on_ship_selected()
                    self._refresh_details_status()
                    self._set_busy(False, "Ready.")

                self.after(0, on_success)

            except subprocess.CalledProcessError as e:
                def on_fail():
                    stdout = (getattr(e, "stdout", "") or "").strip()
                    stderr = (getattr(e, "stderr", "") or "").strip()
                    details = "\n\n".join([t for t in (stdout, stderr) if t]) or str(e)
                    messagebox.showerror("Convert failed", "libNOM failed.\n\n" + details, parent=self)
                    self._set_busy(False, "Ready.")
                self.after(0, on_fail)

            except Exception as e:
                def on_fail2():
                    messagebox.showerror("Error", str(e), parent=self)
                    self._set_busy(False, "Ready.")
                self.after(0, on_fail2)

        threading.Thread(target=worker, daemon=True).start()

    def on_ship_selected(self, *_):
        idx = self.ship_combo.current()
        if idx < 0 or idx >= len(self.ship_bases):
            return
        base = self.ship_bases[idx]
        payload = get_base_objects(base)
        pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, pretty)

    def _block_if_active_selected(self, action_name: str) -> bool:
        if not isinstance(self.last_loaded_root, dict):
            return True

        sel_i = self.ship_combo.current()
        if sel_i < 0 or sel_i >= len(self.ship_bases):
            return True

        selected_base = self.ship_bases[sel_i]
        sel_seed = (self.ship_seeds[sel_i] or "").lower() if 0 <= sel_i < len(self.ship_seeds) else ""
        is_active, active_i, sel_ship_i, active_seed = base_matches_active_ship(self.last_loaded_root, selected_base, sel_seed)

        if DEBUG_PAIRING:
            label = self.ship_names_only[sel_i] if sel_i < len(self.ship_names_only) else "<unknown>"
            print(f"\n=== DEBUG: Active-ship check ({action_name}) [IMPORT] ===")
            print("Selected:", label)
            print("PrimaryShip index:", active_i)
            print("Selected ship index:", sel_ship_i)
            print("Active seed:", active_seed)
            print("Selected seed:", sel_seed)

        if active_i is None and not active_seed:
            ok = messagebox.askokcancel(
                "Can't verify active ship",
                f"I couldn't determine which Corvette is active from this converted save JSON.\n\n"
                f"Make sure the Corvette you're about to {action_name.lower()} is NOT active.\n\nContinue?",
                parent=self
            )
            return ok

        if is_active:
            label = self.ship_names_only[sel_i] if sel_i < len(self.ship_names_only) else "Selected Corvette"
            messagebox.showwarning(
                "Active ship detected",
                f"{action_name} blocked:\n\n"
                f"'{label}' appears to be your CURRENT ACTIVE SHIP.\n\n"
                "Switch to a different ship in-game, save, fully close the game, then convert again.",
                parent=self
            )
            return False

        return True

    def import_into_selected(self):
        if self._busy:
            return
        folder = self.save_folder.get().strip()
        if not folder:
            messagebox.showerror("Missing folder", "Choose the target save folder first.", parent=self)
            return

        if not os.path.isfile(LIBNOM_EXE):
            messagebox.showerror(
                "libNOM missing",
                "libNOM CLI not found.\n\n"
                f"Expected:\n{LIBNOM_EXE}\n\n"
                "Fix: put libNOM.io.cli.exe inside the app's libNOM folder.",
                parent=self
            )
            return

        if not self._selected_slot:
            messagebox.showerror("No slot", "Pick a Slot first.", parent=self)
            return

        if not isinstance(self.last_loaded_root, dict):
            messagebox.showerror("Not loaded", "Convert + Load in the Import tab first.", parent=self)
            return

        idx = self.ship_combo.current()
        if idx < 0 or idx >= len(self.ship_bases):
            messagebox.showerror("Nothing selected", "Select a target corvette first.", parent=self)
            return

        if not self._block_if_active_selected("Import"):
            return

        if is_nms_running():
            messagebox.showwarning(
                "Game is running",
                "No Man’s Sky appears to be running.\n\n"
                "Close the game before importing to avoid corrupt/partial data.",
                parent=self
            )
            return

        build_path = filedialog.askopenfilename(
            title="Select a Corvette build JSON to import...",
            initialdir=self.builds_dir if self.builds_dir else None,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not build_path:
            return

        try:
            self.status_var.set("Loading build file…")
            imported_objects, meta = parse_build_file(build_path)
        except Exception as e:
            messagebox.showerror("Invalid build file", str(e), parent=self)
            return

        if not isinstance(imported_objects, list) or not all(isinstance(x, dict) for x in imported_objects):
            messagebox.showerror("Invalid build file", "Objects list must be a JSON list of objects (dict entries).", parent=self)
            return

        target_name = self.ship_names_only[idx] if idx < len(self.ship_names_only) else f"Corvette {idx+1}"
        meta_name = meta.get("name") if isinstance(meta, dict) else None
        meta_author = meta.get("author") if isinstance(meta, dict) else None
        compat_mode = meta.get("compat_mode") if isinstance(meta, dict) else None

        slot_num = int(self._selected_slot["slot"])
        auto_file = self._selected_auto_file()
        restore_file = self._selected_restore_file()

        summary_lines = [
            "This will REPLACE the entire build on the selected Corvette.",
            "",
            f"Target Slot: {slot_num}",
            f"Will write: {auto_file} + {restore_file} (and mf_*.hg pairs)",
            "",
            f"Target Corvette: {target_name}",
            f"Imported objects: {len(imported_objects)}",
        ]
        if meta_name:
            summary_lines.append(f"Build name: {meta_name}")
        if meta_author:
            summary_lines.append(f"Author: {meta_author}")
        if compat_mode == "raw-objects-list":
            summary_lines.append("Build source: Compatibility input (raw Objects[] list)")
        elif compat_mode == "Objects-wrapper":
            summary_lines.append("Build source: Compatibility input (wrapper with 'Objects')")

        summary_lines += [
            "",
            "IMPORTANT:",
            "• Use a dummy/empty Corvette you are willing to overwrite.",
            "• A backup will be created automatically before any changes.",
            "",
            "Continue?"
        ]

        if not messagebox.askokcancel("Import (Replace)", "\n".join(summary_lines), parent=self):
            return

        try:
            backup_dir = mandatory_backup(folder, self.backups_dir)
        except Exception as e:
            messagebox.showerror("Backup failed", str(e), parent=self)
            return

        base = self.ship_bases[idx]
        parent, key = get_base_objects_ref(base)
        if parent is None:
            messagebox.showerror("Import failed", "Could not locate Objects[] in the selected Corvette base.", parent=self)
            return

        self.status_var.set("Applying build…")
        parent[key] = imported_objects

        self._set_busy(True, "Writing save…")

        root_to_write = self.last_loaded_root
        work_dir = self.import_work_dir
        try:
            platform_format = self.platform_format or resolve_platform_format(folder, restore_file, self.platform_choice.get())
        except Exception as e:
            self._set_busy(False, "Ready.")
            messagebox.showerror("Platform required", str(e), parent=self)
            return
        save_folder = folder

        def worker_write():
            tmp_json = os.path.join(work_dir, "_corvette_tool_modified_save.json")
            try:
                with open(tmp_json, "w", encoding="utf-8") as f:
                    json.dump(root_to_write, f, ensure_ascii=False)

                # Write BOTH files of the selected slot + their mf_ counterparts
                convert_json_to_savehg(platform_format, tmp_json, save_folder, work_dir, restore_file)
                convert_json_to_savehg(platform_format, tmp_json, save_folder, work_dir, auto_file)

                try:
                    os.remove(tmp_json)
                except Exception:
                    pass

                def on_success():
                    self._set_busy(False, "Ready.")
                    messagebox.showinfo(
                        "Import complete",
                        "Build imported successfully!\n\n"
                        f"Backup created at:\n{backup_dir}\n\n"
                        "Next steps:\n"
                        "1) Launch the game\n"
                        "2) Load your save\n"
                        "3) Go to the Corvette and check the build",
                        parent=self
                    )

                self.after(0, on_success)

            except subprocess.CalledProcessError as e:
                def on_fail_proc():
                    stdout = (getattr(e, "stdout", "") or "").strip()
                    stderr = (getattr(e, "stderr", "") or "").strip()
                    details = "\n\n".join([t for t in (stdout, stderr) if t]) or str(e)

                    self._set_busy(False, "Ready.")
                    messagebox.showerror(
                        "Write failed",
                        "Writing back to the save file(s) failed.\n\n"
                        f"{details}\n\n"
                        f"Your backup is here:\n{backup_dir}",
                        parent=self
                    )

                self.after(0, on_fail_proc)

            except Exception as e:
                def on_fail():
                    self._set_busy(False, "Ready.")
                    messagebox.showerror(
                        "Write failed",
                        "Writing back to the save file(s) failed.\n\n"
                        f"Error: {e}\n\n"
                        f"Your backup is here:\n{backup_dir}",
                        parent=self
                    )
                self.after(0, on_fail)

        threading.Thread(target=worker_write, daemon=True).start()


def corvette_summary(root: dict) -> tuple[list[dict], int | None, str]:
    ship_bases = find_player_ship_bases(root)
    info_by_base_index = pair_bases_to_corvette_info(root, ship_bases)
    primary_i, active_seed = get_active_ship_reference(root)

    summary = []
    for i, base in enumerate(ship_bases):
        info = info_by_base_index.get(i, {})
        name = info.get("name") or f"Corvette {i+1}"
        seed = (info.get("seed") or "").lower()
        objects = get_base_objects(base)
        base_ship_i = info.get("ship_index")
        if base_ship_i is None:
            _ship, base_ship_i, _pairing = find_shipownership_entry_for_base(root, base)
        is_active, _active_i, _base_ship_i, _active_seed = base_matches_active_ship(root, base, seed)
        summary.append({
            "index": i,
            "name": name,
            "seed": seed,
            "shipownership_index": base_ship_i,
            "pairing_method": info.get("pairing") or "",
            "object_count": len(objects),
            "is_active": is_active,
        })

    return summary, primary_i, active_seed


def choose_non_active_corvette(summary: list[dict]) -> dict:
    for item in summary:
        if not item.get("is_active") and int(item.get("object_count", 0)) > 0:
            return item
    raise RuntimeError("No non-active Corvette with Objects[] was found for this self-test.")


def load_converted_root(folder: str, work_dir: str, save_id: str, slot_num: int, restore_file: str) -> tuple[str, dict]:
    out_json = run_convert_savehg_to_json(folder, restore_file, work_dir, save_id, slot_num)
    with open(out_json, "r", encoding="utf-8") as f:
        return out_json, json.load(f)


def hash_jsonable(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    import hashlib
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def restore_save_folder_from_backup(backup_dir: str, save_folder: str) -> int:
    restored = 0
    for name in os.listdir(backup_dir):
        src_path = os.path.join(backup_dir, name)
        dst_path = os.path.join(save_folder, name)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, dst_path)
            restored += 1
    return restored


def run_headless_self_test(source_save: str, target_save: str) -> dict:
    source_save = os.path.abspath(source_save)
    target_save = os.path.abspath(target_save)
    restore_file = "save2.hg"
    auto_file = "save.hg"
    slot_num = 1

    report: dict = {
        "ok": False,
        "source_save": source_save,
        "target_save": target_save,
        "steps": [],
    }

    source_dirs = ensure_tool_dirs_for_save(source_save)
    target_dirs = ensure_tool_dirs_for_save(target_save)
    backup_dir = ""
    target_needs_restore = False

    try:
        source_platform = resolve_platform_format(source_save, restore_file, "Auto-detect")
        target_platform = resolve_platform_format(target_save, restore_file, "Auto-detect")
        report["source_platform"] = source_platform
        report["target_platform"] = target_platform
        report["steps"].append("platform_detection")

        _, source_root = load_converted_root(source_save, source_dirs["export_work_dir"], source_dirs["save_id"], slot_num, restore_file)
        source_summary, source_active_index, source_active_seed = corvette_summary(source_root)
        report["source_corvettes"] = source_summary
        report["source_active_ship_index"] = source_active_index
        report["source_active_seed"] = source_active_seed
        report["steps"].append("source_convert")

        active_matches = [item for item in source_summary if item.get("is_active")]
        report["active_guard_checked"] = False
        if len(active_matches) == 1:
            active_item = active_matches[0]
            guard_blocks = False
            active_item_index = active_item.get("shipownership_index")
            if source_active_index is not None and active_item_index is not None:
                guard_blocks = int(active_item_index) == int(source_active_index)
            elif source_active_seed and active_item.get("seed"):
                guard_blocks = active_item.get("seed") == source_active_seed
            if not guard_blocks:
                raise RuntimeError("Active Corvette detection succeeded, but the guard condition did not match it.")
            report["active_guard_checked"] = True
            report["active_corvette"] = active_item
            report["steps"].append("active_guard")

        source_pick = choose_non_active_corvette(source_summary)
        source_bases = find_player_ship_bases(source_root)
        source_objects = get_base_objects(source_bases[int(source_pick["index"])])
        wrapper = build_wrapper(source_objects, f"Self Test Export - {source_pick['name']}", "EXE self-test")
        build_path = os.path.join(source_dirs["builds_dir"], "exe-self-test-export.json")
        with open(build_path, "w", encoding="utf-8") as f:
            json.dump(wrapper, f, indent=2, ensure_ascii=False)
        imported_objects, _meta = parse_build_file(build_path)
        source_hash = hash_jsonable(imported_objects)
        report["build_path"] = build_path
        report["export_source"] = source_pick
        report["export_hash"] = source_hash
        report["steps"].append("export_build")

        _, target_root_before = load_converted_root(target_save, target_dirs["import_work_dir"], target_dirs["save_id"], slot_num, restore_file)
        target_summary_before, _target_active_index, _target_active_seed = corvette_summary(target_root_before)
        target_pick = choose_non_active_corvette(target_summary_before)
        target_before = dict(target_pick)
        target_before["objects_hash"] = hash_jsonable(
            get_base_objects(find_player_ship_bases(target_root_before)[int(target_pick["index"])])
        )
        if target_before["objects_hash"] == source_hash:
            raise RuntimeError("Target Corvette already matches the exported build; import self-test cannot prove a change.")
        report["import_target_before"] = target_before
        report["steps"].append("target_convert")

        backup_dir = mandatory_backup(target_save, target_dirs["backups_dir"])
        report["backup_dir"] = backup_dir
        report["steps"].append("backup")

        target_bases_before = find_player_ship_bases(target_root_before)
        parent, key = get_base_objects_ref(target_bases_before[int(target_pick["index"])])
        if parent is None:
            raise RuntimeError("Could not locate Objects[] in the selected target Corvette during self-test.")
        parent[key] = imported_objects
        target_needs_restore = True

        tmp_json = os.path.join(target_dirs["import_work_dir"], "_exe_self_test_modified_save.json")
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(target_root_before, f, ensure_ascii=False)
        try:
            convert_json_to_savehg(target_platform, tmp_json, target_save, target_dirs["import_work_dir"], restore_file)
            convert_json_to_savehg(target_platform, tmp_json, target_save, target_dirs["import_work_dir"], auto_file)
        finally:
            try:
                os.remove(tmp_json)
            except Exception:
                pass
        report["steps"].append("import_write")

        _, target_root_after = load_converted_root(target_save, target_dirs["import_work_dir"], target_dirs["save_id"], slot_num, restore_file)
        target_bases_after = find_player_ship_bases(target_root_after)
        post_objects = get_base_objects(target_bases_after[int(target_pick["index"])])
        post_hash = hash_jsonable(post_objects)
        if post_hash != source_hash:
            raise RuntimeError("Imported target Corvette does not match the exported build hash.")
        report["import_target_after"] = {
            "index": int(target_pick["index"]),
            "name": target_pick["name"],
            "objects_hash": post_hash,
            "object_count": len(post_objects),
        }
        report["steps"].append("import_verify")

        restored_files = restore_save_folder_from_backup(backup_dir, target_save)
        target_needs_restore = False
        report["restored_files"] = restored_files

        _, target_root_restored = load_converted_root(target_save, target_dirs["import_work_dir"], target_dirs["save_id"], slot_num, restore_file)
        target_bases_restored = find_player_ship_bases(target_root_restored)
        restored_objects = get_base_objects(target_bases_restored[int(target_pick["index"])])
        restored_hash = hash_jsonable(restored_objects)
        if restored_hash != target_before["objects_hash"]:
            raise RuntimeError("Backup restore verification failed; the target save did not return to its original state.")
        report["restore_hash"] = restored_hash
        report["steps"].append("restore_verify")

        clean_transient_work_root(source_dirs["work_root"])
        clean_transient_work_root(target_dirs["work_root"])
        report["steps"].append("work_cleanup")

        report["ok"] = True
        return report

    except Exception as exc:
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        return report

    finally:
        if target_needs_restore and backup_dir and os.path.isdir(backup_dir):
            try:
                restore_save_folder_from_backup(backup_dir, target_save)
            except Exception:
                pass
        clean_transient_work_root(source_dirs["work_root"])
        clean_transient_work_root(target_dirs["work_root"])


def parse_cli_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test-source")
    parser.add_argument("--self-test-target")
    parser.add_argument("--self-test-report")
    return parser.parse_known_args()


if __name__ == "__main__":
    args, _unknown = parse_cli_args()
    if args.self_test_source or args.self_test_target or args.self_test_report:
        report_path = args.self_test_report
        report = {
            "ok": False,
            "error": "Missing self-test arguments.",
        }
        exit_code = 1

        if args.self_test_source and args.self_test_target and report_path:
            report = run_headless_self_test(args.self_test_source, args.self_test_target)
            exit_code = 0 if report.get("ok") else 1

        try:
            report_dir = os.path.dirname(os.path.abspath(report_path))
            if report_dir:
                os.makedirs(report_dir, exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        except Exception:
            exit_code = 1

        raise SystemExit(exit_code)

    App().mainloop()
