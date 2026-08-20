"""Generate a project-scoped Codex Skill from a stdio MCP server."""

import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .config import ServerConfig, load_config
from .errors import McpToSkillsError
from .mcp_client import StdioMcpClient


_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class GenerationResult:
    path: Path
    mode: str
    tool_count: int
    inspected: bool


def validate_skill_name(name: str) -> None:
    if len(name) > 64 or not _SKILL_NAME.fullmatch(name):
        raise McpToSkillsError(
            "Server name must be 1-64 lowercase letters, digits, or hyphen-separated words"
        )


def build_server_config(
    server: str,
    session: bool,
    config_path: Optional[str] = None,
    command: Optional[str] = None,
    arguments: Optional[Sequence[str]] = None,
    idle_timeout: Optional[float] = None,
) -> ServerConfig:
    validate_skill_name(server)
    mode = "session" if session else "on-demand"
    timeout = 600.0 if idle_timeout is None else idle_timeout
    if not math.isfinite(timeout) or timeout < 0:
        raise McpToSkillsError("--idle-timeout must be greater than or equal to 0")

    if config_path:
        if command is not None or arguments:
            raise McpToSkillsError("--config cannot be combined with --command or --arg")
        source = load_config(Path(config_path), expected_name=server)
        return replace(source, lifecycle_mode=mode, idle_timeout=timeout)

    executable = command or "uvx"
    if command is None and not arguments:
        server_arguments = [server + "-mcp"]
    else:
        server_arguments = list(arguments or [])
    return ServerConfig(
        name=server,
        command=executable,
        args=server_arguments,
        env={},
        cwd=None,
        lifecycle_mode=mode,
        idle_timeout=timeout,
        initialize_timeout=30.0,
        discovery_timeout=1.5,
        call_timeout=120.0,
    )


def inspect_tools(config: ServerConfig) -> List[Dict[str, Any]]:
    client = StdioMcpClient(config)
    try:
        client.start()
        return client.list_tools()
    finally:
        client.stop()


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_config(config: ServerConfig) -> str:
    lines = [
        "name: " + _yaml_scalar(config.name),
        "transport: stdio",
        "command: " + _yaml_scalar(config.command),
        "args:",
    ]
    if config.args:
        lines.extend("  - " + _yaml_scalar(argument) for argument in config.args)
    else:
        lines[-1] = "args: []"
    if config.cwd is not None:
        lines.append("cwd: " + _yaml_scalar(config.cwd))
    if config.env:
        lines.append("env:")
        for key in sorted(config.env):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise McpToSkillsError("Environment variable name cannot be written to mcp.yaml: %s" % key)
            lines.append("  %s: %s" % (key, _yaml_scalar(config.env[key])))
    lines.extend(("lifecycle:", "  mode: " + config.lifecycle_mode))
    if config.lifecycle_mode == "session":
        lines.append("  idle_timeout: %s" % _format_number(config.idle_timeout))
    if config.initialize_timeout != 30.0:
        lines.append("  initialize_timeout: %s" % _format_number(config.initialize_timeout))
    if config.discovery_timeout != 1.5:
        lines.append("  discovery_timeout: %s" % _format_number(config.discovery_timeout))
    if config.call_timeout != 120.0:
        lines.append("  call_timeout: %s" % _format_number(config.call_timeout))
    return "\n".join(lines) + "\n"


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _single_line(value: Any) -> str:
    return " ".join(str(value).split())


def _description(server: str, tools: Sequence[Dict[str, Any]]) -> str:
    names = [_single_line(tool["name"])[:100] for tool in tools[:5]]
    suffix = ", including " + ", ".join(names) if names else ""
    return "Use the %s MCP server through mcp-to-skills for its exposed operations%s." % (
        server,
        suffix,
    )


def render_skill(server: str, mode: str, tools: Sequence[Dict[str, Any]], inspected: bool) -> str:
    description = _description(server, tools)
    lines = [
        "---",
        "name: " + server,
        "description: " + json.dumps(description, ensure_ascii=False),
        "---",
        "",
        "# %s MCP" % server,
        "",
        "Use `mcp-to-skills` to call this MCP server. Before choosing a tool or building",
        "arguments, read [the generated tool reference](references/tools.md).",
        "",
    ]
    if mode == "session":
        lines.extend(
            (
                "## Session workflow",
                "",
                "1. Run `mcp-to-skills session status %s`." % server,
                "2. If it is off, run `mcp-to-skills session start %s`." % server,
                "3. Call tools with `mcp-to-skills session call %s <tool> --json '<object>'`." % server,
                "4. Keep the session running between related calls; do not stop it after each call.",
                "5. When the related work is complete, run `mcp-to-skills session stop %s`." % server,
            )
        )
    else:
        lines.extend(
            (
                "## On-demand workflow",
                "",
                "1. Immediately before an operation, run `mcp-to-skills session start %s`." % server,
                "2. Call the required tool with `mcp-to-skills session call %s <tool> --json '<object>'`." % server,
                "3. Immediately after the operation, run `mcp-to-skills session stop %s`." % server,
            )
        )
    if not inspected:
        lines.extend(
            (
                "",
                "> Tool discovery was skipped during generation. Regenerate without `--no-inspect`",
                "> before relying on tool names or argument schemas.",
            )
        )
    return "\n".join(lines) + "\n"


def render_tools_reference(server: str, tools: Sequence[Dict[str, Any]], inspected: bool) -> str:
    lines = [
        "# %s MCP tools" % server,
        "",
        "Call a listed tool with:",
        "",
        "```text",
        "mcp-to-skills session call %s <tool> --json '<object>'" % server,
        "```",
        "",
    ]
    if not inspected:
        lines.append("Tool discovery was skipped. Regenerate without `--no-inspect` to populate this file.")
        return "\n".join(lines) + "\n"
    if not tools:
        lines.append("The MCP server returned no tools from `tools/list`.")
        return "\n".join(lines) + "\n"

    for tool in tools:
        name = _single_line(tool["name"])
        lines.extend(("## `%s`" % name.replace("`", "\\`"), ""))
        tool_description = _single_line(tool.get("description", ""))
        lines.append(tool_description or "No description was supplied by the MCP server.")
        lines.extend(("", "Input schema:", "", "```json"))
        schema = tool.get("inputSchema", {"type": "object"})
        lines.append(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True))
        lines.extend(("```", ""))
        if "outputSchema" in tool:
            lines.extend(("Output schema:", "", "```json"))
            lines.append(json.dumps(tool["outputSchema"], ensure_ascii=False, indent=2, sort_keys=True))
            lines.extend(("```", ""))
    return "\n".join(lines).rstrip() + "\n"


def generate_skill(
    config: ServerConfig,
    output: Path,
    inspect: bool = True,
    force: bool = False,
) -> GenerationResult:
    target = output.resolve()
    known_files = (
        target / "SKILL.md",
        target / "mcp.yaml",
        target / "references" / "tools.md",
    )
    existing = [path for path in known_files if path.exists()]
    if existing and not force:
        raise McpToSkillsError(
            "Generated files already exist in %s; use --force to overwrite them" % target
        )

    tools = inspect_tools(config) if inspect else []
    skill_text = render_skill(config.name, config.lifecycle_mode, tools, inspect)
    config_text = render_config(config)
    tools_text = render_tools_reference(config.name, tools, inspect)

    try:
        (target / "references").mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(skill_text, encoding="utf-8")
        (target / "mcp.yaml").write_text(config_text, encoding="utf-8")
        (target / "references" / "tools.md").write_text(tools_text, encoding="utf-8")
    except OSError as exc:
        raise McpToSkillsError("Could not write generated Skill to %s: %s" % (target, exc))
    return GenerationResult(target, config.lifecycle_mode, len(tools), inspect)
