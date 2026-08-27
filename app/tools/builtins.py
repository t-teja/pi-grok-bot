"""Built-in allowlisted Pi tools. Never runs unbounded shell as root."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from zoneinfo import ZoneInfo
    try:
        USER_TZ = ZoneInfo("Asia/Kolkata")
    except Exception:
        USER_TZ = ZoneInfo("Asia/Calcutta")
except Exception:
    USER_TZ = timezone(timedelta(hours=5, minutes=30))

from app.tools.registry import Tool, ToolRegistry

SAFE_NAME = re.compile(r"^[\w.\- ]+$")


def _run(argv: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return None


def _vcgencmd(*args: str) -> str | None:
    exe = shutil.which("vcgencmd")
    if not exe:
        return None
    try:
        proc = _run([exe, *args], timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip()


def _cpu_percent() -> float | None:
    def snapshot() -> tuple[int, int] | None:
        line = _read_text(Path("/proc/stat"))
        if not line:
            return None
        parts = line.split()
        nums = [int(x) for x in parts[1:8]]
        idle = nums[3] + nums[4]
        total = sum(nums)
        return idle, total

    a = snapshot()
    time.sleep(0.12)
    b = snapshot()
    if not a or not b:
        return None
    idle_d = b[0] - a[0]
    total_d = b[1] - a[1]
    if total_d <= 0:
        return None
    return round(100.0 * (1.0 - idle_d / total_d), 1)


def _mem_info() -> dict[str, Any]:
    info: dict[str, int] = {}
    raw = _read_text(Path("/proc/meminfo")) or ""
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        num = rest.strip().split()[0]
        try:
            info[key] = int(num)
        except ValueError:
            continue
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    used = max(total - avail, 0)
    return {
        "total_mb": round(total / 1024, 1),
        "used_mb": round(used / 1024, 1),
        "available_mb": round(avail / 1024, 1),
        "percent": round(100.0 * used / total, 1) if total else None,
    }


def _cpu_temp_c() -> float | None:
    out = _vcgencmd("measure_temp")
    if out:
        m = re.search(r"temp=([0-9.]+)", out)
        if m:
            return float(m.group(1))
    for candidate in (
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/class/hwmon/hwmon0/temp1_input"),
    ):
        raw = _read_text(candidate)
        if not raw:
            continue
        try:
            val = float(raw)
        except ValueError:
            continue
        return round(val / 1000.0, 1) if val > 200 else val
    return None


def _throttle() -> str | None:
    return _vcgencmd("get_throttled")


def handle_get_datetime(_args: dict[str, Any]) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(USER_TZ)
    local = datetime.now().astimezone()
    return {
        "utc": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST (Asia/Calcutta)"),
        "local": local.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "iso": now_utc.isoformat(),
        "weekday": now_ist.strftime("%A"),
    }


def handle_get_system_stats(_args: dict[str, Any]) -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    load = os.getloadavg() if hasattr(os, "getloadavg") else (None, None, None)
    return {
        "cpu_percent": _cpu_percent(),
        "load_avg_1_5_15": list(load),
        "temperature_c": _cpu_temp_c(),
        "throttled": _throttle(),
        "memory": _mem_info(),
        "disk": {
            "total_gb": round(disk.total / 1e9, 2),
            "used_gb": round(disk.used / 1e9, 2),
            "free_gb": round(disk.free / 1e9, 2),
            "percent": round(100.0 * disk.used / disk.total, 1) if disk.total else None,
        },
        "hostname": os.uname().nodename if hasattr(os, "uname") else None,
        "pi_vcgencmd": bool(shutil.which("vcgencmd")),
    }


def make_run_command(settings: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    allow = {item["name"]: item for item in settings.allowlist}
    timeout = int(settings.tools.get("command_timeout_sec") or 15)

    def handle(args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name") or "").strip()
        if name not in allow:
            return {
                "error": f"Command '{name}' is not on the allowlist.",
                "allowed": sorted(allow),
            }
        item = allow[name]
        argv = list(item["argv"])
        try:
            proc = _run(argv, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"error": f"Command '{name}' timed out after {timeout}s"}
        except OSError as exc:
            return {"error": str(exc)}
        return {
            "name": name,
            "argv": argv,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-2000:],
        }

    return handle


def handle_open_url(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or "").strip()
    if not re.match(r"^https?://", url, re.I):
        return {"error": "URL must start with http:// or https://"}
    return {"url": url, "opened_in_ui": True}


def make_set_timer(scheduler: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def handle(args: dict[str, Any]) -> dict[str, Any]:
        seconds = args.get("seconds")
        minutes = args.get("minutes")
        message = str(args.get("message") or "Timer done").strip() or "Timer done"
        delay = 0
        if seconds is not None:
            delay += int(seconds)
        if minutes is not None:
            delay += int(minutes) * 60
        if delay <= 0:
            return {"error": "Provide a positive seconds and/or minutes value."}
        if delay > 24 * 3600:
            return {"error": "Timers longer than 24 hours are not allowed."}
        due = datetime.now(timezone.utc) + timedelta(seconds=delay)
        timer_id = scheduler.add(delay, message)
        return {
            "id": timer_id,
            "seconds": delay,
            "message": message,
            "due_utc": due.isoformat(),
            "due_ist": due.astimezone(USER_TZ).strftime("%H:%M:%S IST"),
        }

    return handle


def _volume_backend() -> str | None:
    if shutil.which("wpctl"):
        return "wpctl"
    if shutil.which("pactl"):
        return "pactl"
    if shutil.which("amixer"):
        return "amixer"
    return None


def handle_set_volume(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    backend = _volume_backend()
    if not backend:
        return {"error": "No volume tool found (tried wpctl, pactl, amixer)."}
    step = int(args.get("step") or 5)
    step = max(1, min(step, 25))
    try:
        if backend == "wpctl":
            if action == "up":
                _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{step}%+"])
            elif action == "down":
                _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{step}%-"])
            elif action == "mute":
                _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"])
            elif action == "unmute":
                _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
            elif action == "toggle_mute":
                _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
            else:
                return {"error": "action must be up, down, mute, unmute, or toggle_mute"}
            status = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
            return {"backend": backend, "action": action, "status": (status.stdout or "").strip()}
        if backend == "pactl":
            if action == "up":
                _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"+{step}%"])
            elif action == "down":
                _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"-{step}%"])
            elif action == "mute":
                _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"])
            elif action == "unmute":
                _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
            elif action == "toggle_mute":
                _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
            else:
                return {"error": "action must be up, down, mute, unmute, or toggle_mute"}
            status = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
            mute = _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
            return {
                "backend": backend,
                "action": action,
                "volume": (status.stdout or "").strip(),
                "mute": (mute.stdout or "").strip(),
            }
        if action == "up":
            _run(["amixer", "sset", "Master", f"{step}%+"])
        elif action == "down":
            _run(["amixer", "sset", "Master", f"{step}%-"])
        elif action in {"mute", "unmute", "toggle_mute"}:
            _run(["amixer", "sset", "Master", "toggle"])
        else:
            return {"error": "action must be up, down, mute, unmute, or toggle_mute"}
        status = _run(["amixer", "sget", "Master"])
        return {"backend": backend, "action": action, "status": (status.stdout or "")[-500:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def make_screenshot(settings: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    dest_dir = settings.screenshot_dir
    dest_dir.mkdir(parents=True, exist_ok=True)

    def handle(_args: dict[str, Any]) -> dict[str, Any]:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = dest_dir / f"kiosk-{stamp}.png"
        commands = []
        if shutil.which("scrot"):
            commands.append(["scrot", "-o", str(dest)])
        if shutil.which("grim"):
            commands.append(["grim", str(dest)])
        if shutil.which("gnome-screenshot"):
            commands.append(["gnome-screenshot", "-f", str(dest)])
        if shutil.which("import"):
            commands.append(["import", "-window", "root", str(dest)])
        last_err = "No screenshot tool found (tried scrot, grim, gnome-screenshot, import, mss)."
        for argv in commands:
            try:
                proc = _run(argv, timeout=10)
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_err = str(exc)
                continue
            if dest.is_file() and dest.stat().st_size > 0:
                return {"path": str(dest), "bytes": dest.stat().st_size, "via": argv[0]}
            last_err = (proc.stderr or proc.stdout or "empty file").strip()
        try:
            import mss  # type: ignore

            with mss.mss() as sct:
                sct.shot(output=str(dest))
            if dest.is_file():
                return {"path": str(dest), "bytes": dest.stat().st_size, "via": "mss"}
        except Exception as exc:
            last_err = str(exc)
        return {"error": last_err}

    return handle


def _audio_files(music_dir: Path) -> list[Path]:
    if not music_dir.is_dir():
        return []
    exts = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus"}
    files = [p for p in music_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    return sorted(files, key=lambda p: p.name.lower())


def make_list_music(settings: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def handle(_args: dict[str, Any]) -> dict[str, Any]:
        music_dir = settings.music_dir
        files = _audio_files(music_dir)
        return {
            "directory": str(music_dir),
            "exists": music_dir.is_dir(),
            "files": [p.name for p in files],
        }

    return handle


def make_play_music(settings: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def handle(args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("filename") or "").strip()
        if not name or not SAFE_NAME.match(name) or "/" in name or "\\" in name:
            return {"error": "Provide a simple filename from the music directory."}
        path = settings.music_dir / name
        if not path.is_file():
            available = [p.name for p in _audio_files(settings.music_dir)]
            return {"error": f"File not found: {name}", "available": available}
        player = None
        argv = None
        for exe, extra in (
            ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
            ("paplay", []),
            ("aplay", []),
            ("pw-play", []),
            ("mpg123", ["-q"]),
        ):
            if shutil.which(exe):
                player = exe
                argv = [exe, *extra, str(path)]
                break
        if not argv:
            return {"error": "No audio player found (tried ffplay, paplay, aplay, pw-play, mpg123)."}
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            return {"error": str(exc)}
        return {"playing": name, "player": player, "path": str(path)}

    return handle


def handle_list_allowlisted_commands(settings: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def handle(_args: dict[str, Any]) -> dict[str, Any]:
        return {
            "commands": [
                {
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "argv": item.get("argv"),
                }
                for item in settings.allowlist
            ]
        }

    return handle


EMPTY_PARAMS = {"type": "object", "properties": {}, "additionalProperties": False}


def register_all(registry: ToolRegistry, settings: Any, scheduler: Any | None = None) -> None:
    registry.register(Tool(
        name="get_datetime",
        description="Get the current date and time (UTC, IST, and local).",
        parameters=EMPTY_PARAMS,
        handler=handle_get_datetime,
    ))
    registry.register(Tool(
        name="get_system_stats",
        description="Get Raspberry Pi / Linux CPU, temperature, memory, and disk stats.",
        parameters=EMPTY_PARAMS,
        handler=handle_get_system_stats,
    ))
    registry.register(Tool(
        name="list_allowlisted_commands",
        description="List commands the kiosk is allowed to run. Use run_allowlisted_command with one of these names.",
        parameters=EMPTY_PARAMS,
        handler=handle_list_allowlisted_commands(settings),
    ))
    registry.register(Tool(
        name="run_allowlisted_command",
        description="Run a command from the configured allowlist by name. Never arbitrary shell.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Allowlist entry name, e.g. uptime"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        handler=make_run_command(settings),
    ))
    registry.register(Tool(
        name="open_url",
        description="Open an http(s) URL in the kiosk UI (and optionally a browser tab).",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "http or https URL"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=handle_open_url,
        ui_event="open_url",
    ))

    def _timer_unconfigured(_args: dict[str, Any]) -> dict[str, Any]:
        return {"error": "Timer scheduler is not running in this process."}

    registry.register(Tool(
        name="set_timer",
        description="Set a timer/reminder. The kiosk will speak the message when it is due.",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "Seconds to wait"},
                "minutes": {"type": "integer", "description": "Minutes to wait"},
                "message": {"type": "string", "description": "What to say when the timer fires"},
            },
            "additionalProperties": False,
        },
        handler=make_set_timer(scheduler) if scheduler is not None else _timer_unconfigured,
    ))
    registry.register(Tool(
        name="set_volume",
        description="Change speaker volume using wpctl, pactl, or amixer.",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["up", "down", "mute", "unmute", "toggle_mute"]},
                "step": {"type": "integer", "description": "Percent step for up/down (default 5)"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        handler=handle_set_volume,
    ))
    registry.register(Tool(
        name="take_screenshot",
        description="Capture a screenshot of the kiosk display and save it under data/screenshots.",
        parameters=EMPTY_PARAMS,
        handler=make_screenshot(settings),
    ))
    registry.register(Tool(
        name="list_music",
        description="List audio files in the configured local music directory.",
        parameters=EMPTY_PARAMS,
        handler=make_list_music(settings),
    ))
    registry.register(Tool(
        name="play_music",
        description="Play a local audio file from the music directory by filename.",
        parameters={
            "type": "object",
            "properties": {"filename": {"type": "string", "description": "File name only, e.g. jazz.mp3"}},
            "required": ["filename"],
            "additionalProperties": False,
        },
        handler=make_play_music(settings),
    ))
