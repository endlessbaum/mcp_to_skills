import collections
import json
import os
import queue
import subprocess
import threading
from typing import Any, Deque, Dict, List, Optional

from .config import ServerConfig
from .errors import McpError, McpResponseError
from .process_control import ChildProcessGuard


class StdioMcpClient:
    MODERN_VERSION = "2026-07-28"
    LEGACY_VERSION = "2025-11-25"
    SUPPORTED_LEGACY_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}

    def __init__(self, config: ServerConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self._guard: Optional[ChildProcessGuard] = None
        self._next_id = 1
        self._pending: Dict[int, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stderr: Deque[str] = collections.deque(maxlen=40)
        self.server_info: Dict[str, Any] = {}
        self.protocol_version: Optional[str] = None
        self.modern = False

    @property
    def pid(self) -> Optional[int]:
        return self.process.pid if self.process else None

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    def start(self) -> None:
        self._spawn()
        try:
            discovery = self.request(
                "server/discover",
                {"_meta": self._modern_meta()},
                timeout=self.config.discovery_timeout,
            )
        except McpResponseError as exc:
            if exc.code == -32022:
                supported = exc.data.get("supported", []) if isinstance(exc.data, dict) else []
                self.stop()
                raise McpError(
                    "MCP server does not support protocol %s (supported: %s)"
                    % (self.MODERN_VERSION, ", ".join(supported) or "unknown")
                )
            self._start_legacy()
            return
        except McpError:
            self._start_legacy()
            return

        if not isinstance(discovery, dict) or not isinstance(discovery.get("supportedVersions"), list):
            self.stop()
            raise McpError("MCP server returned an invalid server/discover result")
        if self.MODERN_VERSION not in discovery["supportedVersions"]:
            self.stop()
            raise McpError(
                "MCP server does not advertise a supported modern protocol version (advertised: %s)"
                % ", ".join(str(item) for item in discovery["supportedVersions"])
            )
        self.modern = True
        self.protocol_version = self.MODERN_VERSION
        self.server_info = discovery

    def _spawn(self) -> None:
        environment = os.environ.copy()
        environment.update(self.config.env)
        try:
            self.process = subprocess.Popen(
                [self.config.command] + self.config.args,
                cwd=self.config.cwd,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise McpError("Could not start MCP server '%s': %s" % (self.config.name, exc))
        self._guard = ChildProcessGuard(self.process)
        threading.Thread(target=self._read_stdout, name="mcp-stdout-%s" % self.config.name, daemon=True).start()
        threading.Thread(target=self._read_stderr, name="mcp-stderr-%s" % self.config.name, daemon=True).start()

    def _start_legacy(self) -> None:
        if not self.is_running():
            self.stop()
            self.process = None
            self._spawn()
        try:
            result = self.request(
                "initialize",
                {
                    "protocolVersion": self.LEGACY_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-to-skills", "version": "0.1.0"},
                },
                timeout=self.config.initialize_timeout,
            )
            self.server_info = result if isinstance(result, dict) else {}
            negotiated = self.server_info.get("protocolVersion")
            if negotiated not in self.SUPPORTED_LEGACY_VERSIONS:
                raise McpError("MCP server negotiated an unsupported protocol version: %s" % negotiated)
            self.protocol_version = negotiated
            self.modern = False
            self.notify("notifications/initialized", {})
        except Exception:
            self.stop()
            raise

    def _modern_meta(self) -> Dict[str, Any]:
        return {
            "io.modelcontextprotocol/protocolVersion": self.MODERN_VERSION,
            "io.modelcontextprotocol/clientInfo": {"name": "mcp-to-skills", "version": "0.1.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }

    def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        try:
            for line in self.process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict) and isinstance(message.get("id"), int):
                    with self._pending_lock:
                        waiter = self._pending.get(message["id"])
                    if waiter:
                        waiter.put(message)
        finally:
            detail = self._stderr_detail()
            error = McpError("MCP server '%s' exited%s" % (self.config.name, detail))
            with self._pending_lock:
                waiters = list(self._pending.values())
            for waiter in waiters:
                waiter.put(error)

    def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        for line in self.process.stderr:
            self._stderr.append(line.rstrip())

    def _stderr_detail(self) -> str:
        lines = [line for line in self._stderr if line]
        return ": " + " | ".join(lines[-5:]) if lines else ""

    def _send(self, message: Dict[str, Any]) -> None:
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise McpError("MCP server '%s' is not running%s" % (self.config.name, self._stderr_detail()))
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        try:
            with self._write_lock:
                self.process.stdin.write(payload + "\n")
                self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpError("Could not write to MCP server '%s': %s%s" % (self.config.name, exc, self._stderr_detail()))

    def request(self, method: str, params: Dict[str, Any], timeout: float) -> Any:
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            waiter: queue.Queue = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            try:
                response = waiter.get(timeout=timeout)
            except queue.Empty:
                raise McpError("MCP request '%s' timed out after %.1f seconds" % (method, timeout))
            if isinstance(response, Exception):
                raise response
            if "error" in response:
                error = response["error"]
                if isinstance(error, dict):
                    raise McpResponseError(error.get("code", ""), error.get("message", error), error.get("data"))
                raise McpError("MCP error: %s" % error)
            return response.get("result")
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def notify(self, method: str, params: Dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def call_tool(self, tool: str, arguments: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {"name": tool, "arguments": arguments}
        if self.modern:
            params["_meta"] = self._modern_meta()
        return self.request(
            "tools/call",
            params,
            timeout=self.config.call_timeout,
        )

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return every tool advertised by the server, following cursors."""
        tools: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        seen_cursors = set()
        while True:
            params: Dict[str, Any] = {}
            if cursor is not None:
                params["cursor"] = cursor
            if self.modern:
                params["_meta"] = self._modern_meta()
            result = self.request("tools/list", params, timeout=self.config.call_timeout)
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise McpError("MCP server returned an invalid tools/list result")
            page = result["tools"]
            if any(not isinstance(tool, dict) or not isinstance(tool.get("name"), str) for tool in page):
                raise McpError("MCP server returned an invalid tool definition")
            tools.extend(page)
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tools
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise McpError("MCP server returned an invalid tools/list cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def stop(self, graceful_timeout: float = 3.0, terminate_timeout: float = 2.0) -> None:
        process = self.process
        if not process:
            return
        if process.poll() is None and process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            try:
                process.wait(timeout=graceful_timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=terminate_timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=terminate_timeout)
        if self._guard:
            self._guard.close()
            self._guard = None
