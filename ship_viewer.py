import os
import re
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

    try:
        style.theme_use("clam")
    except Exception:
        pass

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

    style.configure("TSeparator", background="#333333")


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


def stable_work_json_path(work_dir: str, save_id: str, slot_num: int) -> str:
    # stable per-slot json filename
    return os.path.join(work_dir, f"{save_id}.slot{slot_num}.save.json")


def clean_work_json(work_dir: str, save_id: str, slot_num: int) -> None:
    """
    Clean ONLY inside this slot-specific work_dir:
      - delete stable JSON for this slot
      - delete any leftover save*.hg.*.json produced by libNOM
    """
    stable = stable_work_json_path(work_dir, save_id, slot_num)
    try:
        if os.path.isfile(stable):
            os.remove(stable)
    except Exception:
        pass

    try:
        for name in os.listdir(work_dir):
            low = name.lower()
            if low.startswith("save") and low.endswith(".json") and ".hg." in low:
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
        return "Steam"

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

    return "Steam"


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
        self.platform_format = "Steam"

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

        ttk.Button(top, text="Choose SAVE Folder (Export)", command=self.choose_folder).pack(side="left")
        ttk.Label(top, textvariable=self.save_folder).pack(side="left", padx=10)

        self.convert_btn = ttk.Button(top, text="Convert + Load Corvettes", command=self.convert_and_load)
        self.convert_btn.pack(side="left", padx=10)

        self.export_btn = ttk.Button(top, text="Export Build", command=self.export_selected, state="disabled")
        self.export_btn.pack(side="left", padx=10)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

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

        info = ttk.Frame(self)
        info.pack(fill="x", pady=(10, 0))
        ttk.Label(info, text="Decoded JSON (Work\\Export):").pack(side="left")
        ttk.Label(info, textvariable=self.json_path).pack(side="left", padx=8)

        self.text = ScrolledText(self, wrap="none", height=24)
        self.text.pack(fill="both", expand=True, pady=(10, 0))
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
        self.ship_combo.set("")
        self.ship_label_var.set("")

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
            d = ensure_tool_dirs_for_save(folder)
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

        d = ensure_tool_dirs_for_save(folder)
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
                platform_format = detect_platform_format_from_savehg(folder, restore_file)
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

        self.save_folder = tk.StringVar()
        self.json_path = tk.StringVar()
        self.ship_label_var = tk.StringVar()

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
        self.platform_format = "Steam"

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

        info = ttk.Frame(self)
        info.pack(fill="x", pady=(10, 0))
        ttk.Label(info, text="Decoded JSON (Work\\Import):").pack(side="left")
        ttk.Label(info, textvariable=self.json_path).pack(side="left", padx=8)

        self.text = ScrolledText(self, wrap="none", height=24)
        self.text.pack(fill="both", expand=True, pady=(10, 0))
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
        self.ship_combo.set("")
        self.ship_label_var.set("")

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
            d = ensure_tool_dirs_for_save(folder)
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

        d = ensure_tool_dirs_for_save(folder)
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
                platform_format = detect_platform_format_from_savehg(folder, restore_file)
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

        self.status_var.set("Applying build…")
        parent[key] = imported_objects

        self._set_busy(True, "Writing save…")

        root_to_write = self.last_loaded_root
        work_dir = self.import_work_dir
        platform_format = self.platform_format or detect_platform_format_from_savehg(folder, restore_file)
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


if __name__ == "__main__":
    App().mainloop()
