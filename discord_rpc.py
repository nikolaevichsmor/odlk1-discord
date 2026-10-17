"""
Zero-dependency Multi-Project Discord Rich Presence (RPC) client for BOINC.
Communicates directly with the local Discord client via Windows Named Pipes (\\\\.\\pipe\\discord-ipc-0..9).
Supports cyclic status rotation across active BOINC projects.
"""
import copy
import ctypes
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
import uuid

DEFAULT_CLIENT_ID = "1559236488305311916"
GITHUB_REPO_URL = "https://github.com/nikolaevichsmor/boinc-discord"
RAW_DOCS_BASE = "https://raw.githubusercontent.com/nikolaevichsmor/boinc-discord/main/docs"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discord_config.json")

# Built-in supported BOINC projects
PROJECTS = [
    {
        "id": "odlk1",
        "name": "latinsquares",
        "client_id": "1559236488305311916",
        "url_match": "latinsquares",
        "job_log": "job_log_boinc.multi-pool.info_latinsquares.txt",
        "details": "Searching 10x10 Latin Squares",
        "large_image": f"{RAW_DOCS_BASE}/odlk1_matrix_v2.gif",
        "large_text": "latinsquares",
        "project_url": "https://boinc.multi-pool.info/latinsquares/",
        "enabled": True
    },
    {
        "id": "milkyway",
        "name": "MilkyWay@home",
        "client_id": "1559236488305311916",
        "url_match": "milkyway",
        "job_log": "job_log_milkyway.cs.rpi.edu_milkyway.txt",
        "details": "N-Body Galaxy Simulation",
        "large_image": f"{RAW_DOCS_BASE}/milkyway_v2.gif",
        "large_text": "MilkyWay@home",
        "project_url": "https://milkyway.cs.rpi.edu/milkyway/",
        "enabled": True
    },
    {
        "id": "wcg",
        "name": "World Community Grid",
        "client_id": "1559236488305311916",
        "url_match": "worldcommunitygrid",
        "job_log": "job_log_www.worldcommunitygrid.org.txt",
        "details": "Medical & Humanitarian Research",
        "large_image": f"{RAW_DOCS_BASE}/wcg_v3.gif",
        "large_text": "World Community Grid",
        "project_url": "https://www.worldcommunitygrid.org/",
        "enabled": True
    },
    {
        "id": "asteroids",
        "name": "Asteroids@home",
        "client_id": "1559236488305311916",
        "url_match": "asteroidsathome",
        "job_log": "job_log_asteroidsathome.net_boinc.txt",
        "details": "3D Asteroid Shape Modeling",
        "large_image": f"{RAW_DOCS_BASE}/asteroids_v2.gif",
        "large_text": "Asteroids@home",
        "project_url": "https://asteroidsathome.net/boinc/",
        "enabled": True
    },
    {
        "id": "einstein",
        "name": "Einstein@Home",
        "client_id": "1559236488305311916",
        "url_match": "einstein",
        "job_log": "job_log_einstein.phys.uwm.edu.txt",
        "details": "Pulsar & Gravity Wave Search",
        "large_image": f"{RAW_DOCS_BASE}/einstein.gif",
        "large_text": "Einstein@Home",
        "project_url": "https://einstein.phys.uwm.edu/",
        "enabled": True
    },
    {
        "id": "primegrid",
        "name": "PrimeGrid",
        "client_id": "1559236488305311916",
        "url_match": "primegrid",
        "job_log": "job_log_www.primegrid.com.txt",
        "details": "Record Prime Number Search",
        "large_image": f"{RAW_DOCS_BASE}/primegrid_v2.gif",
        "large_text": "PrimeGrid",
        "project_url": "https://www.primegrid.com/",
        "enabled": True
    },
    {
        "id": "rosetta",
        "name": "Rosetta@home",
        "client_id": "1559236488305311916",
        "url_match": "bakerlab.org",
        "job_log": "job_log_boinc.bakerlab.org_rosetta.txt",
        "details": "3D Protein Folding & Design",
        "large_image": f"{RAW_DOCS_BASE}/rosetta.gif",
        "large_text": "Rosetta@home",
        "project_url": "https://boinc.bakerlab.org/",
        "enabled": True
    }
]


def load_config():
    defaults = {
        "update_interval": 4.5,
        "rotate_interval": 18.0,
        "boinc_data": None,
        "boinccmd": None
    }
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in ("update_interval", "rotate_interval", "boinc_data", "boinccmd"):
                if data.get(k) is not None:
                    defaults[k] = data[k]
        except Exception:
            pass
    return defaults


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


if sys.platform == "win32":
    import msvcrt
    _k32 = ctypes.windll.kernel32
    _k32.PeekNamedPipe.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)
    ]
    _k32.PeekNamedPipe.restype = ctypes.c_int


class DiscordIPC:
    """Low-level Discord IPC client over named pipe with non-blocking reads and dynamic client_id switching."""
    OP_HANDSHAKE = 0
    OP_FRAME = 1
    OP_CLOSE = 2
    OP_PING = 3
    OP_PONG = 4

    def __init__(self, client_id=None):
        self.client_id = str(client_id or DEFAULT_CLIENT_ID)
        self.pipe = None
        self.connected = False
        self._lock = threading.Lock()

    def _read_exact(self, num_bytes, timeout=1.0):
        if not self.pipe:
            raise OSError("Pipe not open")
        if sys.platform == "win32":
            handle = ctypes.c_void_p(msvcrt.get_osfhandle(self.pipe.fileno()))
            start = time.time()
            avail = ctypes.c_uint32(0)
            while time.time() - start < timeout:
                res = _k32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
                if not res:
                    raise OSError("Pipe broken or disconnected")
                if avail.value >= num_bytes:
                    return self.pipe.read(num_bytes)
                time.sleep(0.02)
            raise TimeoutError("Timeout waiting for response from Discord pipe")
        else:
            return self.pipe.read(num_bytes)

    def switch_client_id(self, new_client_id):
        """Switches the active Discord Application Client ID, reconnecting cleanly if changed."""
        new_client_id = str(new_client_id or DEFAULT_CLIENT_ID)
        if self.client_id == new_client_id and self.connected and self.pipe:
            return True
        if self.connected:
            self.clear_activity()
            self.disconnect()
        self.client_id = new_client_id
        return self.connect()

    def connect(self):
        acquired = self._lock.acquire(timeout=0.5)
        if not acquired:
            return False
        try:
            if self.connected and self.pipe:
                return True
            self.connected = False
            if self.pipe:
                try:
                    self.pipe.close()
                except Exception:
                    pass
                self.pipe = None

            k32 = ctypes.windll.kernel32 if sys.platform == "win32" else None
            for i in range(10):
                pipe_path = rf"\\.\pipe\discord-ipc-{i}"
                if k32 and not k32.WaitNamedPipeW(pipe_path, 50):
                    continue
                try:
                    self.pipe = open(pipe_path, "r+b", buffering=0)
                    payload = json.dumps({"v": 1, "client_id": self.client_id}).encode("utf-8")
                    self.pipe.write(struct.pack("<II", self.OP_HANDSHAKE, len(payload)) + payload)

                    hdr = self._read_exact(8, timeout=3.0)
                    op, length = struct.unpack("<II", hdr)
                    resp_data = self._read_exact(length, timeout=3.0).decode("utf-8", errors="ignore")
                    resp = json.loads(resp_data)
                    if op == self.OP_FRAME and resp.get("cmd") == "DISPATCH" and resp.get("evt") == "READY":
                        self.connected = True
                        return True
                    else:
                        self._disconnect_locked()
                        continue
                except Exception:
                    if self.pipe:
                        try:
                            self.pipe.close()
                        except Exception:
                            pass
                        self.pipe = None
            return False
        finally:
            self._lock.release()

    def send_activity(self, activity):
        acquired = self._lock.acquire(timeout=0.5)
        if not acquired:
            return False
        try:
            if not self.connected or not self.pipe:
                return False
            payload = {
                "cmd": "SET_ACTIVITY",
                "args": {
                    "pid": os.getpid(),
                    "activity": activity
                },
                "nonce": str(uuid.uuid4())
            }
            try:
                data = json.dumps(payload).encode("utf-8")
                self.pipe.write(struct.pack("<II", self.OP_FRAME, len(data)) + data)
                hdr = self._read_exact(8, timeout=2.0)
                op, length = struct.unpack("<II", hdr)
                self._read_exact(length, timeout=2.0)
                if op == self.OP_CLOSE:
                    self._disconnect_locked()
                    return False
                return True
            except Exception:
                self._disconnect_locked()
                return False
        finally:
            self._lock.release()

    def clear_activity(self):
        acquired = self._lock.acquire(timeout=0.5)
        if not acquired:
            return False
        try:
            if not self.connected or not self.pipe:
                return False
            payload = {
                "cmd": "SET_ACTIVITY",
                "args": {
                    "pid": os.getpid(),
                    "activity": None
                },
                "nonce": str(uuid.uuid4())
            }
            try:
                data = json.dumps(payload).encode("utf-8")
                self.pipe.write(struct.pack("<II", self.OP_FRAME, len(data)) + data)
                hdr = self._read_exact(8, timeout=0.8)
                _, length = struct.unpack("<II", hdr)
                self._read_exact(length, timeout=0.8)
                return True
            except Exception:
                self._disconnect_locked()
                return False
        finally:
            self._lock.release()

    def _disconnect_locked(self):
        self.connected = False
        if self.pipe:
            try:
                self.pipe.close()
            except Exception:
                pass
            self.pipe = None

    def disconnect(self):
        acquired = self._lock.acquire(timeout=0.5)
        if not acquired:
            return
        try:
            self._disconnect_locked()
        finally:
            self._lock.release()


class BoincPresenceService:
    """
    Background worker that monitors multiple BOINC projects and rotates them cyclically in Discord RPC.
    Respects Discord rate limits (default updates every 4.5s, rotates active projects every 18s).
    """

    def __init__(self, boinc_data=None, boinccmd=None,
                 update_interval=None, rotate_interval=None,
                 on_status_change=None):
        cfg = load_config()
        self.default_client_id = DEFAULT_CLIENT_ID
        self.projects = copy.deepcopy(PROJECTS)

        self.ipc = DiscordIPC(client_id=self.default_client_id)
        self.running = False
        self.paused = False
        self.thread = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()

        self.update_interval = float(update_interval or cfg.get("update_interval", 4.5))
        self.rotate_interval = float(rotate_interval or cfg.get("rotate_interval", 18.0))
        self.last_update = 0.0
        self.last_rotate_time = 0.0

        self.data_dir = boinc_data or cfg.get("boinc_data") or self._find_boinc_data()
        self.boinccmd = boinccmd or cfg.get("boinccmd") or self._find_boinccmd()

        # Per-project state: sticky task tracking & job_log line count cache
        self.tracked_tasks = {}  # { proj_id: {"wu_name": str, "start_time": int} }
        self._job_log_cache = {}  # { proj_id: (mtime, size, count) }

        # Rotation state
        self.rotation_index = 0
        self.locked_project_id = None  # None = Auto Rotate across active projects
        self.active_project_ids = []
        self.current_displayed_project = None
        self.current_displayed_pct = 0.0
        self.on_status_change = on_status_change

    def _find_boinc_data(self):
        for candidate in [r"C:\Other\data.BOINC", r"C:\ProgramData\BOINC", r"C:\Other\BOINC"]:
            if os.path.isdir(candidate):
                return candidate
        return None

    def _find_boinccmd(self):
        for candidate in [r"C:\Other\BOINC\boinccmd.exe", r"C:\Program Files\BOINC\boinccmd.exe"]:
            if os.path.isfile(candidate):
                return candidate
        return "boinccmd"

    def get_completed_tasks_count(self, project):
        if not self.data_dir:
            return 0
        job_log_name = project.get("job_log")
        if not job_log_name:
            return 0
        path = os.path.join(self.data_dir, job_log_name)
        if not os.path.isfile(path):
            return 0
        pid = project["id"]
        try:
            st = os.stat(path)
            cached = self._job_log_cache.get(pid)
            if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
                return cached[2]
            with open(path, "rb") as f:
                count = sum(buf.count(b"\n") for buf in iter(lambda: f.read(1024 * 1024), b""))
            self._job_log_cache[pid] = (st.st_mtime, st.st_size, count)
            return count
        except Exception:
            return 0

    def _fetch_all_boinc_tasks(self):
        if not self.data_dir or not os.path.isfile(self.boinccmd):
            return []
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        try:
            out = subprocess.run(
                [self.boinccmd, "--get_tasks"],
                cwd=self.data_dir,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=flags
            ).stdout
        except Exception:
            return []

        tasks = []
        cur = None
        for line in out.splitlines():
            if re.match(r"^\d+\) -+", line):
                cur = {}
                tasks.append(cur)
            elif cur is not None and ":" in line:
                k, v = line.split(":", 1)
                cur[k.strip()] = v.strip()
        return tasks

    def _select_task_for_project(self, project, all_tasks):
        """
        Finds active executing tasks for `project` and returns (wu_name, frac, elapsed, start_time) or None.
        Tracks a chosen workunit continuously to 100% before picking the next freshest task.
        """
        pid = project["id"]
        url_match = (project.get("url_match") or "").lower()
        active = [
            t for t in all_tasks
            if url_match in (t.get("project URL") or "").lower()
            and t.get("active_task_state") == "EXECUTING"
        ]
        if not active:
            self.tracked_tasks.pop(pid, None)
            return None

        state = self.tracked_tasks.get(pid)
        tracked = None
        if state and state.get("wu_name"):
            tracked = next(
                (t for t in active if (t.get("WU name") or t.get("name")) == state["wu_name"]),
                None
            )

        now = time.time()
        if not tracked:
            min_frac = 2.0
            for t in active:
                try:
                    frac = float(t.get("fraction done", 0.0))
                    if frac < min_frac:
                        min_frac = frac
                        tracked = t
                except ValueError:
                    pass
            if tracked:
                wu_name = tracked.get("WU name") or tracked.get("name") or project["name"]
                try:
                    el = float(tracked.get("elapsed task time", 0.0))
                except ValueError:
                    el = 0.0
                start_ts = int(now - el) if el > 0 else int(now)
                self.tracked_tasks[pid] = {"wu_name": wu_name, "start_time": start_ts}

        if tracked:
            try:
                frac = float(tracked.get("fraction done", 0.0))
            except ValueError:
                frac = 0.0
            try:
                elapsed = float(tracked.get("elapsed task time", 0.0))
            except ValueError:
                elapsed = 0.0
            wu_name = tracked.get("WU name") or tracked.get("name") or project["name"]
            start_ts = int(now - elapsed) if elapsed > 0 else self.tracked_tasks[pid]["start_time"]
            self.tracked_tasks[pid]["start_time"] = start_ts
            return wu_name, frac, elapsed, start_ts

        return None

    def get_active_projects_telemetry(self):
        """
        Polls BOINC once and returns a list of (project_dict, task_tuple) for all currently executing projects.
        """
        all_tasks = self._fetch_all_boinc_tasks()
        active_list = []
        for proj in self.projects:
            if not proj.get("enabled", True):
                continue
            t_info = self._select_task_for_project(proj, all_tasks)
            if t_info is not None:
                active_list.append((proj, t_info))
        self.active_project_ids = [p["id"] for p, _ in active_list]
        return active_list

    def force_next_project(self):
        """Immediately advances the cyclic rotation to the next active project."""
        self.locked_project_id = None
        self.rotation_index += 1
        self.last_rotate_time = time.time()
        self.last_update = 0.0
        self._wake_event.set()

    def set_locked_project(self, project_id):
        """Locks Discord status to a specific project ID, or None for automatic cyclic rotation."""
        self.locked_project_id = project_id
        self.last_rotate_time = time.time()
        self.last_update = 0.0
        self._wake_event.set()

    def get_status_summary(self):
        """Returns a human-readable status string for the system tray tooltip and menu."""
        if self.paused:
            return "BOINC Discord RPC (Paused)"
        if not self.current_displayed_project:
            return "BOINC Discord RPC (Waiting for tasks)"
        pname = self.current_displayed_project.get("name", "BOINC")
        pct = self.current_displayed_pct
        total_active = len(self.active_project_ids)
        if total_active > 1 and not self.locked_project_id:
            return f"BOINC RPC - {pname} ({pct:.1f}%) [{total_active} active]"
        return f"BOINC RPC - {pname} ({pct:.1f}%)"

    def _notify_status(self):
        if self.on_status_change:
            try:
                self.on_status_change()
            except Exception:
                pass

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self._stop_event.set()
        self._wake_event.set()
        if self.ipc:
            self.ipc.clear_activity()
            self.ipc.disconnect()

    def set_paused(self, paused: bool):
        self.paused = paused
        if paused:
            if self.ipc:
                self.ipc.clear_activity()
        else:
            self.last_update = 0.0
        self._notify_status()
        self._wake_event.set()

    def _build_activity(self, project, wu_name, frac, start_time):
        pct = frac * 100.0
        total_completed = self.get_completed_tasks_count(project)
        completed_str = f"{total_completed:,}".replace(",", " ")

        details = project.get("details") or f"Computing {project['name']}"
        state_str = f"{pct:.1f}% ({completed_str} tasks completed)"

        activity = {
            "name": project.get("name", "BOINC"),
            "details": details,
            "state": state_str,
            "timestamps": {
                "start": start_time
            },
            "buttons": [
                {
                    "label": "What is this?",
                    "url": "https://boinc.berkeley.edu/"
                },
                {
                    "label": "GitHub",
                    "url": GITHUB_REPO_URL
                }
            ]
        }

        assets = {}
        if project.get("large_image"):
            assets["large_image"] = project["large_image"]
            assets["large_text"] = project.get("large_text", project.get("name", "BOINC"))
        if project.get("small_image"):
            assets["small_image"] = project["small_image"]
            assets["small_text"] = project.get("small_text", "BOINC")
        if assets:
            activity["assets"] = assets

        return activity, pct

    def _run_loop(self):
        self.last_rotate_time = time.time()
        while not self._stop_event.is_set():
            if self.paused:
                if self.ipc.connected:
                    self.ipc.clear_activity()
                self._wake_event.wait(timeout=0.5)
                self._wake_event.clear()
                continue

            now = time.time()
            if now - self.last_update < self.update_interval:
                self._wake_event.wait(timeout=0.4)
                self._wake_event.clear()
                continue

            active_telemetry = self.get_active_projects_telemetry()
            if not active_telemetry:
                self.current_displayed_project = None
                self.current_displayed_pct = 0.0
                if self.ipc.connected:
                    self.ipc.clear_activity()
                self._notify_status()
                self.last_update = now
                self._wake_event.wait(timeout=2.5)
                self._wake_event.clear()
                continue

            # Choose which project to display in this cycle
            chosen_pair = None
            if self.locked_project_id:
                chosen_pair = next(
                    ((p, t) for p, t in active_telemetry if p["id"] == self.locked_project_id),
                    None
                )

            if chosen_pair is None:
                # Automatic cyclic rotation across active projects
                if len(active_telemetry) > 1 and (now - self.last_rotate_time) >= self.rotate_interval:
                    self.rotation_index = (self.rotation_index + 1) % len(active_telemetry)
                    self.last_rotate_time = now
                else:
                    self.rotation_index = self.rotation_index % len(active_telemetry)
                chosen_pair = active_telemetry[self.rotation_index]

            project, (wu_name, frac, elapsed, start_time) = chosen_pair
            target_client_id = project.get("client_id") or self.default_client_id

            # Ensure IPC is connected with the target project's Discord Client ID
            if not self.ipc.switch_client_id(target_client_id):
                self._wake_event.wait(timeout=4.0)
                self._wake_event.clear()
                continue

            activity, pct = self._build_activity(project, wu_name, frac, start_time)
            success = self.ipc.send_activity(activity)
            self.last_update = time.time()

            if success:
                self.current_displayed_project = project
                self.current_displayed_pct = pct
                self._notify_status()
                self._wake_event.wait(timeout=self.update_interval)
                self._wake_event.clear()
            else:
                self._wake_event.wait(timeout=2.0)
                self._wake_event.clear()


# Backwards-compatibility alias
OdlkPresenceService = BoincPresenceService
