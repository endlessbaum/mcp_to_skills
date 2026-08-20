import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .config import find_config, load_config
from .errors import McpToSkillsError
from .generate import build_server_config, generate_skill
from .ipc import broker_request


def _age(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return "%d:%02d:%02d" % (hours, minutes, secs) if hours else "%02d:%02d" % (minutes, secs)


def _print_status(server: str, status: Optional[Dict[str, Any]]) -> None:
    if not status:
        print("Session not running.\n")
        print(server)
        print("STATE: off")
        return
    print(server)
    print("STATE: %s" % status["state"])
    print("PID: %s" % status["pid"])
    print("AGE: %s" % _age(status["age"]))


def _session_start(args: argparse.Namespace) -> int:
    path = find_config(args.server, args.config)
    config = load_config(path, expected_name=args.server)
    result = broker_request(
        {"action": "start", "config": config.to_wire()},
        start_if_missing=True,
        timeout=config.initialize_timeout + 5.0,
    )
    if result["already_running"]:
        print("Session already running.\n")
    else:
        print("Session started.\n")
    print(args.server)
    print("PID: %s" % result["pid"])
    return 0


def _session_status(args: argparse.Namespace) -> int:
    result = broker_request({"action": "status", "server": args.server})
    _print_status(args.server, result)
    return 0


def _session_list(_args: argparse.Namespace) -> int:
    result = broker_request({"action": "list"})
    sessions = result or []
    if not sessions:
        print("No active MCP sessions.")
        return 0
    rows = [(item["server"], item["state"], str(item["pid"]), _age(item["age"])) for item in sessions]
    widths = [max(len(label), *(len(row[index]) for row in rows)) for index, label in enumerate(("SERVER", "STATE", "PID", "AGE"))]
    template = "  ".join("{:<%d}" % width for width in widths)
    print(template.format("SERVER", "STATE", "PID", "AGE"))
    for row in rows:
        print(template.format(*row))
    return 0


def _session_call(args: argparse.Namespace) -> int:
    try:
        arguments = json.loads(args.json) if args.json is not None else {}
    except json.JSONDecodeError as exc:
        raise McpToSkillsError("--json is not valid JSON: %s" % exc)
    if not isinstance(arguments, dict):
        raise McpToSkillsError("--json must contain a JSON object")
    result = broker_request(
        {"action": "call", "server": args.server, "tool": args.tool, "arguments": arguments},
        timeout=3600.0,
    )
    if result is None:
        raise McpToSkillsError("Session is not running: %s" % args.server)
    print(json.dumps(result["tool_result"], ensure_ascii=False, indent=2))
    return 0


def _session_stop(args: argparse.Namespace) -> int:
    if args.all:
        result = broker_request({"action": "stop_all"})
        names = result["stopped"] if result else []
        if names:
            print("Stopping MCP sessions...\n")
            for name in names:
                print("%-12s stopped" % name)
            print("\nNo active MCP sessions.")
        else:
            print("No active MCP sessions.")
        return 0
    if not args.server:
        raise McpToSkillsError("Specify a server or use --all")
    result = broker_request({"action": "stop", "server": args.server})
    if result and result["stopped"]:
        print("Session stopped.\n")
        print(args.server)
    else:
        print("Session not running.\n")
        print(args.server)
    return 0


def _generate(args: argparse.Namespace) -> int:
    config = build_server_config(
        server=args.server,
        session=args.session,
        config_path=args.config,
        command=args.mcp_command,
        arguments=args.arguments,
        idle_timeout=args.idle_timeout,
    )
    output = args.output or str(Path.cwd() / ".agents" / "skills" / args.server)
    if not args.no_inspect:
        print("Inspecting MCP server: %s" % args.server)
    result = generate_skill(config, Path(output), inspect=not args.no_inspect, force=args.force)
    print("Generated Codex Skill: %s" % result.path)
    print("Mode: %s" % result.mode)
    print("Tools: %d%s" % (result.tool_count, " (inspection skipped)" if not result.inspected else ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-to-skills")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    generate = subcommands.add_parser("generate", help="Generate a project-scoped Codex Skill")
    generate.add_argument("server", help="Skill and MCP server name")
    generate.add_argument(
        "--session",
        action="store_true",
        help="Generate Session Mode guidance (default: on-demand)",
    )
    generate.add_argument("--config", help="Use an existing mcp.yaml as the server definition")
    generate.add_argument("--command", dest="mcp_command", help="MCP server executable (default: uvx)")
    generate.add_argument("--arg", dest="arguments", action="append", help="MCP server argument; repeat as needed")
    generate.add_argument("--output", help="Skill directory (default: .agents/skills/<server>)")
    generate.add_argument("--idle-timeout", type=float, help="Session idle timeout in seconds (default: 600)")
    generate.add_argument("--no-inspect", action="store_true", help="Generate without starting the MCP server")
    generate.add_argument("--force", action="store_true", help="Overwrite generated files in the target directory")
    generate.set_defaults(handler=_generate)

    session = subcommands.add_parser("session", help="Manage reusable MCP sessions")
    session_commands = session.add_subparsers(dest="session_command", required=True)

    start = session_commands.add_parser("start", help="Start or reuse an MCP session")
    start.add_argument("server")
    start.add_argument("--config", help="Path to mcp.yaml")
    start.set_defaults(handler=_session_start)

    status = session_commands.add_parser("status", help="Show one session")
    status.add_argument("server")
    status.set_defaults(handler=_session_status)

    listing = session_commands.add_parser("list", help="List owned sessions")
    listing.set_defaults(handler=_session_list)

    call = session_commands.add_parser("call", help="Call a tool in a running session")
    call.add_argument("server")
    call.add_argument("tool")
    call.add_argument("--json", metavar="OBJECT", help="Tool arguments as a JSON object")
    call.set_defaults(handler=_session_call)

    stop = session_commands.add_parser("stop", help="Stop one or all sessions")
    stop.add_argument("server", nargs="?")
    stop.add_argument("--all", action="store_true", help="Stop every owned session")
    stop.set_defaults(handler=_session_stop)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return args.handler(args)
    except McpToSkillsError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
