"""Load the deliberately small YAML subset used by mcp.yaml files.

The evaluation build has no runtime dependencies.  The parser supports nested
mappings, block lists, inline JSON-style lists, strings, booleans, null, and
numbers.  That covers generated mcp.yaml files while rejecting YAML features
whose meaning would otherwise be surprising.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import ConfigError


@dataclass(frozen=True)
class ServerConfig:
    name: str
    command: str
    args: List[str]
    env: Dict[str, str]
    cwd: Optional[str]
    lifecycle_mode: str
    idle_timeout: float
    initialize_timeout: float
    discovery_timeout: float
    call_timeout: float

    def to_wire(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "cwd": self.cwd,
            "lifecycle_mode": self.lifecycle_mode,
            "idle_timeout": self.idle_timeout,
            "initialize_timeout": self.initialize_timeout,
            "discovery_timeout": self.discovery_timeout,
            "call_timeout": self.call_timeout,
        }

    @classmethod
    def from_wire(cls, value: Dict[str, Any]) -> "ServerConfig":
        return cls(**value)


def _strip_comment(value: str) -> str:
    quote = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in ("'", '"'):
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        elif char == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.rstrip()


def _scalar(value: str, line_number: int) -> Any:
    value = _strip_comment(value).strip()
    if not value:
        return None
    if value[0:1] in ('"', "'"):
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise ConfigError("Invalid quoted string on line %d: %s" % (line_number, exc))
        if len(value) < 2 or value[-1] != "'":
            raise ConfigError("Unterminated quoted string on line %d" % line_number)
        return value[1:-1].replace("''", "'")
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ConfigError("Inline collections must use JSON syntax on line %d: %s" % (line_number, exc))
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "~"):
        return None
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", value):
        return float(value)
    return value


def parse_yaml_subset(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()

    for line_number, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ConfigError("Tabs are not allowed for indentation (line %d)" % line_number)
        indent = len(raw) - len(raw.lstrip(" "))
        content = _strip_comment(raw.strip())
        if not content:
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ConfigError("Invalid indentation on line %d" % line_number)
        parent = stack[-1][1]

        if content.startswith("- ") or content == "-":
            if not isinstance(parent, list):
                raise ConfigError("List item without a list key on line %d" % line_number)
            parent.append(_scalar(content[1:].strip(), line_number))
            continue

        if ":" not in content:
            raise ConfigError("Expected 'key: value' on line %d" % line_number)
        key, raw_value = content.split(":", 1)
        key = key.strip()
        if not key or not isinstance(parent, dict):
            raise ConfigError("Invalid mapping on line %d" % line_number)
        raw_value = raw_value.strip()
        if raw_value:
            parent[key] = _scalar(raw_value, line_number)
            continue

        # Choose list/dict by looking at the next meaningful, more-indented line.
        child: Any = {}
        for following in lines[line_number:]:
            if not following.strip() or following.lstrip().startswith("#"):
                continue
            next_indent = len(following) - len(following.lstrip(" "))
            if next_indent <= indent:
                break
            child = [] if following.strip().startswith("-") else {}
            break
        parent[key] = child
        stack.append((indent, child))

    return root


def _number(value: Any, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ConfigError("%s must be a number greater than or equal to %s" % (label, minimum))
    return float(value)


def load_config(path: Path, expected_name: Optional[str] = None) -> ServerConfig:
    try:
        data = parse_yaml_subset(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError("Cannot read configuration %s: %s" % (path, exc))
    if not isinstance(data, dict):
        raise ConfigError("Configuration root must be a mapping")
    name = data.get("name")
    command = data.get("command")
    transport = data.get("transport", "stdio")
    if not isinstance(name, str) or not name:
        raise ConfigError("mcp.yaml requires a non-empty 'name'")
    if expected_name and name != expected_name:
        raise ConfigError("Configuration name '%s' does not match requested server '%s'" % (name, expected_name))
    if transport != "stdio":
        raise ConfigError("Session mode currently supports only transport: stdio")
    if not isinstance(command, str) or not command:
        raise ConfigError("mcp.yaml requires a non-empty 'command'")
    args = data.get("args", [])
    env = data.get("env", {})
    lifecycle = data.get("lifecycle", {})
    if not isinstance(args, list) or any(not isinstance(item, (str, int, float)) for item in args):
        raise ConfigError("'args' must be a list of scalar values")
    if not isinstance(env, dict) or any(not isinstance(key, str) for key in env):
        raise ConfigError("'env' must be a mapping")
    if not isinstance(lifecycle, dict):
        raise ConfigError("'lifecycle' must be a mapping")
    mode = lifecycle.get("mode", "on-demand")
    if mode not in ("on-demand", "session"):
        raise ConfigError("lifecycle.mode must be 'on-demand' or 'session'")
    cwd = data.get("cwd")
    if cwd is not None:
        if not isinstance(cwd, str):
            raise ConfigError("'cwd' must be a path string")
        candidate = Path(cwd)
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        cwd = str(candidate.resolve())
    return ServerConfig(
        name=name,
        command=command,
        args=[str(item) for item in args],
        env={str(key): str(value) for key, value in env.items()},
        cwd=cwd,
        lifecycle_mode=mode,
        idle_timeout=_number(lifecycle.get("idle_timeout", 600), "lifecycle.idle_timeout"),
        initialize_timeout=_number(lifecycle.get("initialize_timeout", 30), "lifecycle.initialize_timeout", 0.1),
        discovery_timeout=_number(lifecycle.get("discovery_timeout", 1.5), "lifecycle.discovery_timeout", 0.1),
        call_timeout=_number(lifecycle.get("call_timeout", 120), "lifecycle.call_timeout", 0.1),
    )


def find_config(server: str, explicit: Optional[str] = None) -> Path:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    else:
        cwd = Path.cwd().resolve()
        candidates.extend((cwd / "mcp.yaml", cwd / server / "mcp.yaml"))
        # Match Codex's repository skill discovery: a server-specific mcp.yaml
        # may live beside SKILL.md under .agents/skills/<server> at any level
        # from the current directory through the repository root.
        for directory in (cwd,) + tuple(cwd.parents):
            candidates.append(directory / ".agents" / "skills" / server / "mcp.yaml")
            if (directory / ".git").exists():
                break
        config_root = os.environ.get("MCP_TO_SKILLS_CONFIG_DIR")
        if config_root:
            candidates.extend((Path(config_root) / server / "mcp.yaml", Path(config_root) / (server + ".yaml")))
        candidates.append(Path.home() / ".mcp-to-skills" / "servers" / server / "mcp.yaml")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    rendered = "\n  ".join(str(candidate) for candidate in candidates)
    raise ConfigError("No mcp.yaml found for '%s'. Checked:\n  %s" % (server, rendered))
