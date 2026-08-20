import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import BrokerError
from .process_control import detached_process_flags
from .runtime import ensure_runtime_dir, read_state, remove_state


class BrokerUnavailable(BrokerError):
    pass


class _BootstrapLock:
    def __init__(self):
        self.file = None

    def __enter__(self) -> "_BootstrapLock":
        path = ensure_runtime_dir() / "broker.lock"
        self.file = path.open("a+b")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        if not self.file:
            return
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


def _exchange(state: Dict[str, Any], request: Dict[str, Any], timeout: float) -> Any:
    payload = dict(request)
    payload["token"] = state["token"]
    try:
        with socket.create_connection((state["host"], int(state["port"])), timeout=timeout) as connection:
            connection.settimeout(timeout)
            connection.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            response_file = connection.makefile("rb")
            raw = response_file.readline(8 * 1024 * 1024)
    except (OSError, KeyError, ValueError) as exc:
        raise BrokerUnavailable("Session broker is unavailable: %s" % exc)
    if not raw:
        raise BrokerUnavailable("Session broker closed the connection without a response")
    try:
        response = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise BrokerUnavailable("Session broker returned invalid data: %s" % exc)
    if not response.get("ok"):
        raise BrokerError(response.get("error", "Session broker request failed"))
    return response.get("result")


def existing_broker() -> Optional[Dict[str, Any]]:
    state = read_state()
    if not state:
        return None
    try:
        _exchange(state, {"action": "ping"}, timeout=0.5)
        return state
    except BrokerError:
        remove_state(only_pid=state.get("pid"))
        return None


def ensure_broker(startup_timeout: float = 5.0) -> Dict[str, Any]:
    with _BootstrapLock():
        current = existing_broker()
        if current:
            return current
        command = [sys.executable, "-m", "mcp_to_skills.broker"]
        log_path = ensure_runtime_dir() / "broker.log"
        kwargs: Dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = detached_process_flags()
        else:
            kwargs["start_new_session"] = True
        try:
            with log_path.open("wb") as log_file:
                kwargs["stdout"] = log_file
                kwargs["stderr"] = subprocess.STDOUT
                process = subprocess.Popen(command, **kwargs)
        except OSError as exc:
            raise BrokerError("Could not launch session broker: %s" % exc)
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise BrokerError(
                    "Session broker exited during startup (code %s)%s"
                    % (process.returncode, _broker_log_detail(log_path))
                )
            state = existing_broker()
            # Windows virtual-environment launchers can hand execution to a
            # base Python process whose PID differs from Popen.pid. The
            # authenticated ping in existing_broker is the readiness proof.
            if state:
                return state
            time.sleep(0.05)
        try:
            process.terminate()
        except OSError:
            pass
        raise BrokerError(
            "Session broker did not become ready within %.1f seconds%s"
            % (startup_timeout, _broker_log_detail(log_path))
        )


def _broker_log_detail(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not text:
        return ""
    lines = text.splitlines()[-8:]
    return ": " + " | ".join(lines)


def broker_request(request: Dict[str, Any], start_if_missing: bool = False, timeout: float = 130.0) -> Any:
    state = ensure_broker() if start_if_missing else existing_broker()
    if not state:
        return None
    try:
        return _exchange(state, request, timeout=timeout)
    except BrokerUnavailable:
        remove_state(only_pid=state.get("pid"))
        if start_if_missing:
            raise
        return None
