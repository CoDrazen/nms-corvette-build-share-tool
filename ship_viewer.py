import os
import json
import shutil
import subprocess
import tkinter as tk
import threading
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from datetime import datetime, timezone


# Portable app path
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Portable bundled EXE path
LIBNOM_EXE = os.path.join(APP_DIR, "libNOM", "libNOM.io.cli.exe")

# Set True to print pairing diagnostics to the terminal
DEBUG_PAIRING = True

# Wrapper file format constants
BUILD_FORMAT = "NMS-CorvetteBuild"
BUILD_VERSION = 1

# Tool workspace folder (created next to st_... save folder)
TOOL_ROOT_NAME = "NMS_CorvetteTool"

def apply_dark_theme(root: tk.Tk):
    """
    Simple dark theme for ttk + base Tk widgets.
    Works on Windows/macOS/Linux (with small native differences).
    """
    root.configure(bg="#1e1e1e")

    style = ttk.Style(root)

    # Use a ttk theme that actually respects color changes
    # (vista doesn't always obey bg changes, clam usually does)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # Global defaults
    style.configure(".", background="#1e1e1e", foreground="#e6e6e6")
    style.configure("TFrame", background="#1e1e1e")
    style.configure("TLabel", background="#1e1e1e", foreground="#e6e6e6")

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

    # Optional: nicer separators if you use them
    style.configure("TSeparator", background="#333333")


# -----------------------------
# Tool workspace helpers
# -----------------------------

def ensure_tool_dirs_for_save(save_folder: str) -> dict:
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
    parent = os.path.dirname(save_folder)
    save_id = os.path.basename(save_folder)

    tool_root = os.path.join(parent, TOOL_ROOT_NAME)
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


def stable_work_json_path(work_dir: str, save_id: str) -> str:
    return os.path.join(work_dir, f"{save_id}.save2.hg.json")


def clean_work_json(work_dir: str, save_id: str) -> None:
    """
    Clean ONLY inside this slot-specific work_dir:
      - delete stable JSON
      - delete any leftover save2.hg.*.json produced by libNOM
    """
    stable = stable_work_json_path(work_dir, save_id)
    try:
        if os.path.isfile(stable):
            os.remove(stable)
    except Exception:
        pass

    try:
        for name in os.listdir(work_dir):
            low = name.lower()
            if low.startswith("save2.hg.") and low.endswith(".json"):
                try:
                    os.remove(os.path.join(work_dir, name))
                except Exception:
                    pass
    except Exception:
        pass


# -----------------------------
# libNOM helpers
# -----------------------------

def _windows_no_console_startupinfo():
    """
    Hide console window for subprocess calls on Windows.
    Returns (startupinfo, creationflags) or (None, 0) on non-Windows.
    """
    if os.name != "nt":
        return None, 0
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    creationflags = subprocess.CREATE_NO_WINDOW
    return startupinfo, creationflags


def _run_libnom(args: list[str], cwd: str | None = None, input_text: str | None = None) -> str:
    r"""
    Portable runner:
      1) Prefer bundled EXE:  <app>\libNOM\libNOM.io.cli.exe
      2) Optional fallback:  dotnet <app>\libNOM\libNOM.io.cli.dll

    Returns stdout+stderr (best-effort). Raises CalledProcessError on failure.
    """
    startupinfo, creationflags = _windows_no_console_startupinfo()

    # EXE portable
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


def run_convert_save2hg_to_json(save_folder: str, work_dir: str, save_id: str) -> str:
    r"""
    Converts <save_folder>\save2.hg to JSON, outputs into work_dir.
    Returns stable JSON path:
      <work_dir>\<save_id>.save2.hg.json
    """
    save_hg = os.path.join(save_folder, "save2.hg")
    if not os.path.isfile(save_hg):
        raise FileNotFoundError(f"save2.hg not found in: {save_folder}")

    clean_work_json(work_dir, save_id)

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
        candidates = [
            f for f in os.listdir(work_dir)
            if f.lower().startswith("save2.hg.") and f.lower().endswith(".json")
        ]
        if not candidates:
            raise RuntimeError("Convert ran but no JSON was created/found in Work folder.")
        candidates.sort(key=lambda f: os.path.getmtime(os.path.join(work_dir, f)), reverse=True)
        created_path = os.path.join(work_dir, candidates[0])
    else:
        created_save2hg = [f for f in created if f.lower().startswith("save2.hg.")]
        pick = created_save2hg[0] if created_save2hg else created[0]
        created_path = os.path.join(work_dir, pick)

    stable_path = stable_work_json_path(work_dir, save_id)
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


def detect_platform_format_from_savehg(save_folder: str) -> str:
    # Strong Steam hint
    if os.path.isfile(os.path.join(save_folder, "steam_autocloud.vdf")):
        return "Steam"

    save_hg = os.path.join(save_folder, "save2.hg")
    if not os.path.isfile(save_hg):
        return "Steam"

    try:
        out = _run_libnom(["Analyze", "-I", save_hg])
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

    return "Steam"


def convert_json_to_savehg(platform_format: str,json_in_path: str,save_folder: str,work_dir: str,out_name: str) -> None:
    r"""
    Convert JSON -> platform output in work_dir, replace <save_folder>\<out_name>
    with the produced .data, then delete ALL .data/.meta from work_dir.
    """
    if not os.path.isfile(json_in_path):
        raise FileNotFoundError(f"JSON input not found: {json_in_path}")

    save_hg = os.path.join(save_folder, out_name)
    tmp_target = save_hg + ".tmp"
    
    # Ensure a clean workdir for this conversion
    for name in list(os.listdir(work_dir)):
        if name.lower().endswith((".data", ".meta")):
            try:
                os.remove(os.path.join(work_dir, name))
            except Exception:
                pass
    
    # Snapshot before conversion so we can identify *new* outputs
    before = set(os.listdir(work_dir))

    # Convert JSON back to platform output (goes to work_dir)
    _run_libnom([
        "Convert",
        "-I", json_in_path,
        "-O", work_dir,
        "-F", platform_format
    ])

    after = set(os.listdir(work_dir))
    created = list(after - before)

    # Find newest .data created
    data_candidates = [f for f in created if f.lower().endswith(".data")]
    meta_candidates = [f for f in created if f.lower().endswith(".meta")]

    if not data_candidates:
        data_candidates = [f for f in os.listdir(work_dir) if f.lower().endswith(".data")]
    if not meta_candidates:
        meta_candidates = [f for f in os.listdir(work_dir) if f.lower().endswith(".meta")]

    if not data_candidates:
        raise RuntimeError("Convert succeeded but no .data output was found in the work folder.")

    data_candidates.sort(
        key=lambda f: os.path.getmtime(os.path.join(work_dir, f)),
        reverse=True
    )
    data_path = os.path.join(work_dir, data_candidates[0])

    # Atomic replace
    shutil.copy2(data_path, tmp_target)
    os.replace(tmp_target, save_hg)

    # FULL cleanup: no leftovers, ever
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
    """
    Extract "0x..." from a resource dict Seed field.
    Accept: Seed = [true, "0x...."]
    """
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
    """
    Try to detect No Man's Sky running.
    Best-effort: check process list for common exe names.
    """
    possible = {"NMS.exe", "NoMansSky.exe", "NoMansSky", "NMS"}
    try:
        startupinfo, creationflags = _windows_no_console_startupinfo()
        out = subprocess.check_output(
            ["tasklist"],
            text=True,
            errors="ignore",
            startupinfo=startupinfo,
            creationflags=creationflags
        )
        out_u = out.upper()
        return any(p.upper() in out_u for p in possible)
    except Exception:
        return False


def get_primary_ship_index(root: dict):
    v = deep_get(root, ["BaseContext", "PlayerStateData", "PrimaryShip"], default=None)
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    return None


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


def get_shipownership_resource(root: dict, idx: int) -> dict:
    ships = get_shipownership_list(root)
    if not isinstance(idx, int) or idx < 0 or idx >= len(ships):
        return {}
    ship = ships[idx]
    if not isinstance(ship, dict):
        return {}
    res = ship.get("Resource")
    return res if isinstance(res, dict) else {}


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


def pair_bases_to_corvette_info(root: dict, ship_bases: list[dict]) -> dict[int, dict]:
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
        if key in seen:
            continue
        seen.add(key)

        prefixes = seed_hex_to_prefixes(seed_hex)
        boost = 5 if in_shipownership else 0
        records.append((display_name, seed_hex, seed_unix, prefixes, boost))

    base_ts_list = [collect_unix_timestamps_anywhere(b) for b in ship_bases]

    candidates = []
    for base_i, base_ts in enumerate(base_ts_list):
        for (display_name, seed_hex, seed_unix, prefixes, boost) in records:
            sc = score_match(base_ts, seed_unix, prefixes)
            if sc > 0:
                candidates.append((sc, boost, base_i, display_name, seed_hex))

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)

    assigned_base = set()
    assigned_seed = set()
    mapping = {}

    for sc, boost, base_i, display_name, seed_hex in candidates:
        if base_i in assigned_base:
            continue
        if seed_hex.lower() in assigned_seed:
            continue
        mapping[base_i] = {"name": display_name, "seed": seed_hex.lower()}
        assigned_base.add(base_i)
        assigned_seed.add(seed_hex.lower())

    if DEBUG_PAIRING:
        print("\n=== DEBUG: Corvette pairing ===")
        print(f"Bases={len(ship_bases)} Records={len(records)} Candidates={len(candidates)}\n")
        for i, b in enumerate(ship_bases):
            ga = b.get("GalacticAddress")
            ts_count = len(base_ts_list[i])
            info = mapping.get(i)
            label = info["name"] if info else "<NO MATCH>"
            seed = info["seed"] if info else ""
            print(f"Base[{i}] GA={ga} unix_ts_found={ts_count} -> {label} {seed}")

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
    r"""
    Always create a backup of the SAVE FOLDER files into:
      <backups_root>\<save_id>\backup_YYYYMMDD_HHMMSS\

    Returns backup directory path.
    """
    save_id = os.path.basename(os.path.abspath(save_folder))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_dir = os.path.join(backups_root, save_id, f"backup_{stamp}")
    os.makedirs(backup_dir, exist_ok=True)

    for name in os.listdir(save_folder):
        src = os.path.join(save_folder, name)
        if os.path.isfile(src):
            try:
                shutil.copy2(src, os.path.join(backup_dir, name))
            except Exception:
                pass

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
        return data, {}

    if isinstance(data, dict):
        objs = data.get("objects")
        if isinstance(objs, list):
            meta = dict(data)
            meta.pop("objects", None)
            return objs, meta

        objs2 = data.get("Objects")
        if isinstance(objs2, list):
            meta = dict(data)
            meta.pop("Objects", None)
            return objs2, meta

    raise ValueError("Build file must be either a JSON list (Objects[]) or a wrapper object containing 'objects'.")


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
        apply_dark_theme(self)
        self.title("NMS Corvette Build Share Tool (libNOM)")
        self.geometry("1200x760")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        self.export_tab = ExportTab(nb, self)
        self.import_tab = ImportTab(nb, self)

        nb.add(self.export_tab, text="Export")
        nb.add(self.import_tab, text="Import")


class ExportTab(ttk.Frame):
    def __init__(self, parent, root_app: App):
        super().__init__(parent, padding=10)
        self.root_app = root_app

        # state
        self.save_folder = tk.StringVar()
        self.json_path = tk.StringVar()
        self.ship_label_var = tk.StringVar()

        self.ship_bases = []
        self.ship_labels = []
        self.ship_names_only = []
        self.ship_seeds = []
        self.last_loaded_root = None
        self.active_seed = ""
        self.platform_format = "Steam"

        # workspace (derived from save folder)
        self.tool_root = ""
        self.backups_dir = ""
        self.builds_dir = ""
        self.work_root = ""
        self.export_work_dir = ""
        self.import_work_dir = ""
        self.save_id = ""

        # UI
        top = ttk.Frame(self)
        top.pack(fill="x")

        # busy flag
        self._busy = False

        ttk.Button(top, text="Choose SAVE Folder (Export)", command=self.choose_folder).pack(side="left")
        ttk.Label(top, textvariable=self.save_folder).pack(side="left", padx=10)

        self.convert_btn = ttk.Button(top, text="Convert + Load Corvettes", command=self.convert_and_load)
        self.convert_btn.pack(side="left", padx=10)

        self.export_btn = ttk.Button(top, text="Export Build", command=self.export_selected, state="disabled")
        self.export_btn.pack(side="left", padx=10)

        # status label (right side of the top row)
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")


        mid = ttk.Frame(self)
        mid.pack(fill="x", pady=(10, 0))

        ttk.Label(mid, text="Corvette:").pack(side="left")
        self.ship_combo = ttk.Combobox(mid, textvariable=self.ship_label_var, state="readonly", width=95)
        self.ship_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.ship_combo.bind("<<ComboboxSelected>>", self.on_ship_selected)

        info = ttk.Frame(self)
        info.pack(fill="x", pady=(10, 0))
        ttk.Label(info, text="Decoded JSON (Work\\Export):").pack(side="left")
        ttk.Label(info, textvariable=self.json_path).pack(side="left", padx=8)

        self.text = ScrolledText(self, wrap="none", height=24)
        self.text.pack(fill="both", expand=True, pady=(10, 0))

        # Dark styling for Tk Text widget
        self.text.configure(
            bg="#151515",
            fg="#e6e6e6",
            insertbackground="#e6e6e6",
            selectbackground="#404040",
            selectforeground="#ffffff"
        )

    def _set_busy(self, busy: bool, status: str | None = None):
        self._busy = busy
        if status is not None:
            self.status_var.set(status)

        # Disable/enable convert button while working
        self.convert_btn.config(state="disabled" if busy else "normal")

        # Export button should stay disabled while busy
        if busy:
            self.export_btn.config(state="disabled")

        # Cursor feedback (watch cursor)
        try:
            self.root_app.configure(cursor="watch" if busy else "")
            self.root_app.update_idletasks()
        except Exception:
            pass

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select your NMS SAVE folder to EXPORT from (contains save2.hg)")
        if folder:
            self.save_folder.set(folder)
            d = ensure_tool_dirs_for_save(folder)
            self._set_workspace_from_dict(d)

            # reset UI state
            self._clear_loaded_state()

    def _set_workspace_from_dict(self, d: dict):
        self.tool_root = d["tool_root"]
        self.backups_dir = d["backups_dir"]
        self.builds_dir = d["builds_dir"]
        self.work_root = d["work_root"]
        self.export_work_dir = d["export_work_dir"]
        self.import_work_dir = d["import_work_dir"]
        self.save_id = d["save_id"]

    def _clear_loaded_state(self):
        self.ship_bases = []
        self.ship_labels = []
        self.ship_names_only = []
        self.ship_seeds = []
        self.last_loaded_root = None
        self.active_seed = ""
        self.platform_format = "Steam"
        self.json_path.set("")
        self.ship_combo["values"] = []
        self.export_btn.config(state="disabled")
        self.text.delete("1.0", tk.END)
        self.status_var.set("Ready.")

    def convert_and_load(self):
        if self._busy:
            return

        folder = self.save_folder.get().strip()
        if not folder:
            messagebox.showerror("Missing folder", "Choose the export save folder first.", parent=self)
            return

        # Fast fail: libNOM must exist before we spawn the worker thread
        if not os.path.isfile(LIBNOM_EXE):
            messagebox.showerror(
                "libNOM missing",
                "libNOM CLI not found.\n\n"
                f"Expected:\n{LIBNOM_EXE}\n\n"
                "Fix: put libNOM.io.cli.exe inside the app's libNOM folder.",
                parent=self
            )
            return
        
        d = ensure_tool_dirs_for_save(folder)
        self._set_workspace_from_dict(d)

        if not pre_convert_warning_gate(self):
            return

        # prevent stale UI while converting
        self.export_btn.config(state="disabled")
        self.ship_combo["values"] = []
        self.text.delete("1.0", tk.END)

        self._set_busy(True, "Converting save to JSON…")

        def worker():
            try:
                platform_format = detect_platform_format_from_savehg(folder)
                self.after(0, lambda: self.status_var.set(f"Detected platform: {platform_format} — Converting save to JSON…"))
                
                # Phase 1: convert
                out_json = run_convert_save2hg_to_json(folder, self.export_work_dir, self.save_id)

                # Phase 2: load json
                self.after(0, lambda: self.status_var.set("Loading JSON…"))
                with open(out_json, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Phase 3: scan + pair
                self.after(0, lambda: self.status_var.set("Scanning corvettes…"))
                ship_bases = find_player_ship_bases(data)
                if not ship_bases:
                    raise RuntimeError(
                        "Converted JSON loaded, but no Corvette bases were found at:\n"
                        "BaseContext → PlayerStateData → PersistentPlayerBases (BaseType=PlayerShipBase)"
                    )

                info_by_base_index = pair_bases_to_corvette_info(data, ship_bases)

                primary_i = get_primary_ship_index(data)
                active_res = get_shipownership_resource(data, primary_i) if primary_i is not None else {}
                active_seed = resource_seed_hex(active_res)

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
                    is_active = (seed and active_seed and seed.lower() == active_seed.lower())
                    active_tag = " [ACTIVE]" if is_active else ""

                    labels.append(f"{i+1}. {nm}{active_tag}  (Objects: {obj_count})")
                    names_only.append(nm)
                    seeds.append(seed)

                # UI update (must be in main thread)
                def on_success():
                    self.platform_format = platform_format
                    self.json_path.set(out_json)
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

        primary_i = get_primary_ship_index(self.last_loaded_root)
        active_res = get_shipownership_resource(self.last_loaded_root, primary_i) if primary_i is not None else {}
        active_seed = resource_seed_hex(active_res)

        sel_seed = (self.ship_seeds[sel_i] or "").lower() if 0 <= sel_i < len(self.ship_seeds) else ""

        if DEBUG_PAIRING:
            label = self.ship_names_only[sel_i] if sel_i < len(self.ship_names_only) else "<unknown>"
            print(f"\n=== DEBUG: Active-ship check ({action_name}) [EXPORT] ===")
            print("Selected:", label)
            print("PrimaryShip index:", primary_i)
            print("Active seed:", active_seed)
            print("Selected seed:", sel_seed)

        if not active_seed:
            ok = messagebox.askokcancel(
                "Can’t verify active ship",
                f"I couldn’t read the active ship seed from PrimaryShip/ShipOwnership in this JSON.\n\n"
                f"Make sure the Corvette you’re about to {action_name.lower()} is NOT active.\n\nContinue?",
                parent=self
            )
            return ok

        if active_seed and sel_seed and active_seed == sel_seed:
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

        # state (separate from Export tab)
        self.save_folder = tk.StringVar()
        self.json_path = tk.StringVar()
        self.ship_label_var = tk.StringVar()

        self.ship_bases = []
        self.ship_labels = []
        self.ship_names_only = []
        self.ship_seeds = []
        self.last_loaded_root = None
        self.active_seed = ""
        self.platform_format = "Steam"

        # workspace (derived from save folder)
        self.tool_root = ""
        self.backups_dir = ""
        self.builds_dir = ""
        self.work_root = ""
        self.export_work_dir = ""
        self.import_work_dir = ""
        self.save_id = ""

        # UI
        top = ttk.Frame(self)
        top.pack(fill="x")

        self._busy = False
        
        ttk.Button(top, text="Choose TARGET Save Folder (Import)", command=self.choose_folder).pack(side="left")
        ttk.Label(top, textvariable=self.save_folder).pack(side="left", padx=10)

        self.convert_btn = ttk.Button(top, text="Convert + Load Corvettes", command=self.convert_and_load)
        self.convert_btn.pack(side="left", padx=10)

        self.import_btn = ttk.Button(top, text="Import Build (Replace)", command=self.import_into_selected, state="disabled")
        self.import_btn.pack(side="left", padx=10)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        mid = ttk.Frame(self)
        mid.pack(fill="x", pady=(10, 0))

        ttk.Label(mid, text="Target Corvette:").pack(side="left")
        self.ship_combo = ttk.Combobox(mid, textvariable=self.ship_label_var, state="readonly", width=95)
        self.ship_combo.pack(side="left", padx=8, fill="x", expand=True)
        self.ship_combo.bind("<<ComboboxSelected>>", self.on_ship_selected)

        info = ttk.Frame(self)
        info.pack(fill="x", pady=(10, 0))
        ttk.Label(info, text="Decoded JSON (Work\\Import):").pack(side="left")
        ttk.Label(info, textvariable=self.json_path).pack(side="left", padx=8)

        self.text = ScrolledText(self, wrap="none", height=24)
        self.text.pack(fill="both", expand=True, pady=(10, 0))

        # Dark styling for Tk Text widget
        self.text.configure(
            bg="#151515",
            fg="#e6e6e6",
            insertbackground="#e6e6e6",
            selectbackground="#404040",
            selectforeground="#ffffff"
        )

    def _set_busy(self, busy: bool, status: str | None = None):
        self._busy = busy
        if status is not None:
            self.status_var.set(status)

        self.convert_btn.config(state="disabled" if busy else "normal")

        # Import button must stay disabled while busy
        if busy:
            self.import_btn.config(state="disabled")

        try:
            self.root_app.configure(cursor="watch" if busy else "")
            self.root_app.update_idletasks()
        except Exception:
            pass

        if not busy and isinstance(self.last_loaded_root, dict) and self.ship_bases:
            self.import_btn.config(state="normal")


    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select your TARGET NMS save folder to IMPORT into (contains save2.hg)")
        if folder:
            self.save_folder.set(folder)
            d = ensure_tool_dirs_for_save(folder)
            self._set_workspace_from_dict(d)
            self._clear_loaded_state()

    def _set_workspace_from_dict(self, d: dict):
        self.tool_root = d["tool_root"]
        self.backups_dir = d["backups_dir"]
        self.builds_dir = d["builds_dir"]
        self.work_root = d["work_root"]
        self.export_work_dir = d["export_work_dir"]
        self.import_work_dir = d["import_work_dir"]
        self.save_id = d["save_id"]

    def _clear_loaded_state(self):
        self.ship_bases = []
        self.ship_labels = []
        self.ship_names_only = []
        self.ship_seeds = []
        self.last_loaded_root = None
        self.active_seed = ""
        self.platform_format = "Steam"
        self.json_path.set("")
        self.ship_combo["values"] = []
        self.import_btn.config(state="disabled")
        self.text.delete("1.0", tk.END)
        self.status_var.set("Ready.")

    def convert_and_load(self):
        if self._busy:
            return

        folder = self.save_folder.get().strip()
        if not folder:
            messagebox.showerror("Missing folder", "Choose the target save folder first.", parent=self)
            return

        # Fast fail: libNOM must exist before we spawn the worker thread
        if not os.path.isfile(LIBNOM_EXE):
            messagebox.showerror(
                "libNOM missing",
                "libNOM CLI not found.\n\n"
                f"Expected:\n{LIBNOM_EXE}\n\n"
                "Fix: put libNOM.io.cli.exe inside the app's libNOM folder.",
                parent=self
            )
            return

        d = ensure_tool_dirs_for_save(folder)
        self._set_workspace_from_dict(d)

        if not pre_convert_warning_gate(self):
            return

        # prevent stale UI while converting
        self.import_btn.config(state="disabled")
        self.ship_combo["values"] = []
        self.text.delete("1.0", tk.END)

        self._set_busy(True, "Converting save to JSON…")

        def worker():
            try:
                platform_format = detect_platform_format_from_savehg(folder)
                self.after(0, lambda: self.status_var.set(f"Detected platform: {platform_format} — Converting save to JSON…"))

                # Phase 1: convert
                out_json = run_convert_save2hg_to_json(folder, self.import_work_dir, self.save_id)

                # Phase 2: load json
                self.after(0, lambda: self.status_var.set("Loading JSON…"))
                with open(out_json, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Phase 3: scan + pair
                self.after(0, lambda: self.status_var.set("Scanning corvettes…"))
                ship_bases = find_player_ship_bases(data)
                if not ship_bases:
                    raise RuntimeError(
                        "Converted JSON loaded, but no Corvette bases were found at:\n"
                        "BaseContext → PlayerStateData → PersistentPlayerBases (BaseType=PlayerShipBase)"
                    )

                info_by_base_index = pair_bases_to_corvette_info(data, ship_bases)

                primary_i = get_primary_ship_index(data)
                active_res = get_shipownership_resource(data, primary_i) if primary_i is not None else {}
                active_seed = resource_seed_hex(active_res)

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
                    is_active = (seed and active_seed and seed.lower() == active_seed.lower())
                    active_tag = " [ACTIVE]" if is_active else ""

                    labels.append(f"{i+1}. {nm}{active_tag}  (Objects: {obj_count})")
                    names_only.append(nm)
                    seeds.append(seed)

                # UI update (must be in main thread)
                def on_success():
                    self.platform_format = platform_format
                    self.json_path.set(out_json)
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

        primary_i = get_primary_ship_index(self.last_loaded_root)
        active_res = get_shipownership_resource(self.last_loaded_root, primary_i) if primary_i is not None else {}
        active_seed = resource_seed_hex(active_res)

        sel_seed = (self.ship_seeds[sel_i] or "").lower() if 0 <= sel_i < len(self.ship_seeds) else ""

        if DEBUG_PAIRING:
            label = self.ship_names_only[sel_i] if sel_i < len(self.ship_names_only) else "<unknown>"
            print(f"\n=== DEBUG: Active-ship check ({action_name}) [IMPORT] ===")
            print("Selected:", label)
            print("PrimaryShip index:", primary_i)
            print("Active seed:", active_seed)
            print("Selected seed:", sel_seed)

        if not active_seed:
            ok = messagebox.askokcancel(
                "Can’t verify active ship",
                f"I couldn’t read the active ship seed from PrimaryShip/ShipOwnership in this JSON.\n\n"
                f"Make sure the Corvette you’re about to {action_name.lower()} is NOT active.\n\nContinue?",
                parent=self
            )
            return ok

        if active_seed and sel_seed and active_seed == sel_seed:
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

        summary_lines = [
            "This will REPLACE the entire build on the selected Corvette.",
            "",
            f"Target Corvette: {target_name}",
            f"Imported objects: {len(imported_objects)}",
        ]
        if meta_name:
            summary_lines.append(f"Build name: {meta_name}")
        if meta_author:
            summary_lines.append(f"Author: {meta_author}")

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

        backup_dir = mandatory_backup(folder, self.backups_dir)

        base = self.ship_bases[idx]
        parent, key = get_base_objects_ref(base)
        if parent is None:
            messagebox.showerror("Import failed", "Could not locate Objects[] in the selected Corvette base.", parent=self)
            return

        # Apply build in memory (fast)
        self.status_var.set("Applying build…")
        parent[key] = imported_objects

        # From this point, do the heavy writing/conversion in a background thread
        self._set_busy(True, "Writing save…")

        # Copy the data we need into locals so the worker doesn't depend on UI state changing
        root_to_write = self.last_loaded_root
        work_dir = self.import_work_dir
        platform_format = self.platform_format or detect_platform_format_from_savehg(folder)
        save_folder = folder

        def worker_write():
            tmp_json = os.path.join(work_dir, "_corvette_tool_modified_save.json")
            try:
                # Write modified JSON
                with open(tmp_json, "w", encoding="utf-8") as f:
                    json.dump(root_to_write, f, ensure_ascii=False)

                # Convert + write both saves
                convert_json_to_savehg(platform_format, tmp_json, save_folder, work_dir, "save2.hg")
                convert_json_to_savehg(platform_format, tmp_json, save_folder, work_dir, "save.hg")

                # Cleanup temp json
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
                    # Show libNOM's real error text (stdout/stderr)
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



if __name__ == "__main__":
    App().mainloop()
