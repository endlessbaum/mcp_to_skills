import argparse
import atexit
import json
import os
import secrets
import signal
import socketserver
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import ServerConfig
from .errors import McpToSkillsError
from .mcp_client import StdioMcpClient
from .runtime import remove_state, write_state


@dataclass
class Session:
    config: ServerConfig
    client: StdioMcpClient
    started_at: float = field(default_factory=time.time)
    last_call_at: float = field(default_factory=time.time)
    active_calls: int = 0

    def summary(self) -> Dict[str, Any]:
        return {
            "server": self.config.name,
            "state": "ready" if self.client.is_running() else "crashed",
            "pid": self.client.pid,
            "age": max(0.0, time.time() - self.started_at),
            "idle": max(0.0, time.time() - self.last_call_at),
            "idle_timeout": self.config.idle_timeout,
        }


class SessionRegistry:
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self.lock = threading.RLock()
        self.exit_requested = threading.Event()
        self._closed = False
        self._created_at = time.monotonic()
        self._monitor = threading.Thread(target=self._monitor_idle, name="session-idle-monitor", daemon=True)
        self._monitor.start()

    def start(self, raw_config: Dict[str, Any]) -> Dict[str, Any]:
        config = ServerConfig.from_wire(raw_config)
        with self.lock:
            current = self.sessions.get(config.name)
            if current and current.client.is_running():
                result = current.summary()
                result["already_running"] = True
                return result
            if current:
                current.client.stop()
                self.sessions.pop(config.name, None)
            client = StdioMcpClient(config)
            client.start()
            session = Session(config=config, client=client)
            self.sessions[config.name] = session
            self.exit_requested.clear()
            result = session.summary()
            result["already_running"] = False
            return result

    def status(self, server: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            session = self.sessions.get(server)
            if not session:
                return None
            if not session.client.is_running():
                session.client.stop()
                self.sessions.pop(server, None)
                if not self.sessions:
                    self.exit_requested.set()
                return None
            return session.summary()

    def list(self) -> List[Dict[str, Any]]:
        with self.lock:
            names = list(self.sessions)
        return [value for value in (self.status(name) for name in names) if value]

    def call(self, server: str, tool: str, arguments: Dict[str, Any]) -> Any:
        with self.lock:
            session = self.sessions.get(server)
            if not session or not session.client.is_running():
                raise McpToSkillsError("Session is not running: %s" % server)
            session.active_calls += 1
            session.last_call_at = time.time()
        try:
            return session.client.call_tool(tool, arguments)
        finally:
            with self.lock:
                session.active_calls -= 1
                session.last_call_at = time.time()
                if not session.client.is_running():
                    self.sessions.pop(server, None)
                    if not self.sessions:
                        self.exit_requested.set()

    def stop(self, server: str) -> bool:
        with self.lock:
            session = self.sessions.pop(server, None)
        if not session:
            return False
        session.client.stop()
        with self.lock:
            if not self.sessions:
                self.exit_requested.set()
        return True

    def stop_all(self, request_exit: bool = True) -> List[str]:
        with self.lock:
            sessions = list(self.sessions.items())
            self.sessions.clear()
        for _, session in sessions:
            session.client.stop()
        if request_exit:
            self.exit_requested.set()
        return [name for name, _ in sessions]

    def _monitor_idle(self) -> None:
        while not self._closed:
            time.sleep(0.25)
            now = time.time()
            expired: List[str] = []
            with self.lock:
                if not self.sessions and time.monotonic() - self._created_at >= 5.0:
                    self.exit_requested.set()
                    continue
                for name, session in self.sessions.items():
                    timeout = session.config.idle_timeout
                    if timeout > 0 and session.active_calls == 0 and now - session.last_call_at >= timeout:
                        expired.append(name)
            for name in expired:
                self.stop(name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop_all()


class BrokerServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address: Any, registry: SessionRegistry, token: str):
        self.registry = registry
        self.token = token
        super().__init__(address, BrokerHandler)


class BrokerHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw = self.rfile.readline(8 * 1024 * 1024)
            request = json.loads(raw.decode("utf-8"))
            if request.get("token") != self.server.token:
                raise McpToSkillsError("Broker authentication failed")
            result = self.dispatch(request)
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": str(exc) or exc.__class__.__name__}
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()

    def dispatch(self, request: Dict[str, Any]) -> Any:
        registry = self.server.registry
        action = request.get("action")
        if action == "ping":
            return {"pid": os.getpid()}
        if action == "start":
            return registry.start(request["config"])
        if action == "status":
            return registry.status(request["server"])
        if action == "list":
            return registry.list()
        if action == "call":
            arguments = request.get("arguments", {})
            if not isinstance(arguments, dict):
                raise McpToSkillsError("Tool arguments must be a JSON object")
            return {"tool_result": registry.call(request["server"], request["tool"], arguments)}
        if action == "stop":
            return {"stopped": registry.stop(request["server"])}
        if action == "stop_all":
            return {"stopped": registry.stop_all()}
        raise McpToSkillsError("Unknown broker action: %s" % action)


def run_broker() -> int:
    registry = SessionRegistry()
    token = secrets.token_urlsafe(32)
    server = BrokerServer(("127.0.0.1", 0), registry, token)
    pid = os.getpid()
    write_state({"host": "127.0.0.1", "port": server.server_address[1], "token": token, "pid": pid})
    atexit.register(registry.close)

    def request_exit(_signum: int, _frame: Any) -> None:
        registry.exit_requested.set()

    for signal_name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), request_exit)
    server.timeout = 0.2
    try:
        while not registry.exit_requested.is_set():
            server.handle_request()
    finally:
        registry.close()
        server.server_close()
        remove_state(only_pid=pid)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)
    return run_broker()


if __name__ == "__main__":
    raise SystemExit(main())
