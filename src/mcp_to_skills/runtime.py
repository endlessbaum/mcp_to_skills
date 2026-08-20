import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


def runtime_dir() -> Path:
    override = os.environ.get("MCP_TO_SKILLS_RUNTIME_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "mcp-to-skills" / "runtime"
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "mcp-to-skills"
    return Path(tempfile.gettempdir()) / ("mcp-to-skills-%s" % getattr(os, "getuid", lambda: "user")())


def state_path() -> Path:
    return runtime_dir() / "broker.json"


def ensure_runtime_dir() -> Path:
    directory = runtime_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def read_state() -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(state_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def write_state(value: Dict[str, Any]) -> None:
    directory = ensure_runtime_dir()
    temporary = directory / ("broker-%d.tmp" % os.getpid())
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(str(temporary), str(state_path()))


def remove_state(only_pid: Optional[int] = None) -> None:
    if only_pid is not None:
        state = read_state()
        if state and state.get("pid") != only_pid:
            return
    try:
        state_path().unlink()
    except FileNotFoundError:
        pass

