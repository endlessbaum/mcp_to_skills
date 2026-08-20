# ⚠️ EXPERIMENTAL — 実験段階のソフトウェアです

> **このプロジェクトは現在、評価・検証を目的とした実験版です。**  
> コマンド形式、設定形式、Sessionの挙動、Skillの配置方法は、予告なく変更される可能性があります。
> 重要な環境や本番用途では使用せず、MCPプロセスが正常に終了していることを確認してください。

# mcp-to-skills

`mcp-to-skills` moves the lifetime of a stdio MCP server behind a project-local
command and a local session broker. The broker exists only while it owns an
active MCP session, so the server does not need to be registered with Codex or
ChatGPT Desktop and does not remain permanently active.

This repository currently contains the first Session Mode evaluation build.

To make a server callable as an actual project-scoped Codex Skill, follow
[the Codex project Skill placement guide](docs/CODEX_SKILLS.md). A complete
Blender example is available under `examples/blender-project/.agents/skills`.

## Add to a project with uv

Run the following from the root of each project that will use an MCP Skill. If
the project does not have a `pyproject.toml` yet, create a minimal one first:

```powershell
cd C:\path\to\your-project
uv init --bare  # Skip this line when pyproject.toml already exists
uv add --dev "mcp-to-skills @ git+https://github.com/endlessbaum/mcp_to_skills.git"
uv run mcp-to-skills --version
```

This records `mcp-to-skills` as a project development dependency, updates
`uv.lock`, and installs it into the project's persistent `.venv`. Nothing is
added to the global `PATH`; run every command through `uv run`.

To update the Git dependency later:

```powershell
uv lock --upgrade-package mcp-to-skills
uv sync
```

Pinning a release, branch, or revision is also supported by uv's Git dependency
options. Private repositories require Git credentials that can already access
the repository.

For development of `mcp-to-skills` itself, use its repository environment:

```powershell
uv sync
uv run mcp-to-skills session list
```

## Generate a Codex Skill

Run the command from the root of the project where Codex should discover the
Skill:

```powershell
uv run mcp-to-skills generate blender --session
```

This starts `uvx blender-mcp` temporarily, obtains the Tool names and schemas
with MCP `tools/list`, stops that inspection process, and creates:

```text
.agents/skills/blender/
├─ SKILL.md
├─ mcp.yaml
└─ references/
   └─ tools.md
```

`--session` writes `lifecycle.mode: session` and Session workflow guidance.
Without it, the generated lifecycle is `on-demand`, as required by the
evaluation specification. If the MCP server is not launched as
`uvx <name>-mcp`, pass an existing configuration:

```powershell
uv run mcp-to-skills generate blender --session --config C:\path\to\blender-mcp.yaml
```

Alternatively use `--command` and repeat `--arg`. `--no-inspect` creates the
Skill without starting the server, but cannot populate the Tool reference.
Existing generated files are preserved unless `--force` is supplied.
The checked-in Blender example remains a readable sample; `generate` creates a
fresh `SKILL.md` and Tool reference from the MCP server being inspected.

## Server configuration

Create an `mcp.yaml` for each stdio server:

```yaml
name: blender
transport: stdio
command: uvx
args:
  - blender-mcp
lifecycle:
  mode: session
  idle_timeout: 600
```

Optional lifecycle settings are `initialize_timeout` (30 seconds),
`discovery_timeout` (1.5 seconds), and `call_timeout` (120 seconds).
`idle_timeout: 0` disables idle expiry.

For `uv run mcp-to-skills session start blender`, configuration is searched in
this order:

1. A path passed with `--config`.
2. `./mcp.yaml`.
3. `./blender/mcp.yaml`.
4. `.agents/skills/blender/mcp.yaml` from the current directory through the
   Git repository root.
5. `MCP_TO_SKILLS_CONFIG_DIR/blender/mcp.yaml` or `blender.yaml`.
6. `~/.mcp-to-skills/servers/blender/mcp.yaml`.

## Session commands

```powershell
uv run mcp-to-skills session start blender
uv run mcp-to-skills session status blender
uv run mcp-to-skills session list
uv run mcp-to-skills session call blender get_scene_info
uv run mcp-to-skills session call blender execute_blender_code --json '{"code":"..."}'
uv run mcp-to-skills session stop blender
uv run mcp-to-skills session stop --all
```

Starting the same named server twice reuses its existing process. The idle
clock is reset around every tool call, and a call in progress is never expired.
Stopping closes the server's stdin, waits for normal exit, then escalates to
terminate and kill.

The broker listens only on loopback and authenticates requests with a random
token in its runtime state file. On Windows, every MCP child is assigned to a
kill-on-close Job Object when the OS permits it. This prevents a child from
surviving an abrupt broker exit. Other platforms receive normal signal and
`atexit` cleanup; stronger parent-death enforcement remains future work.

Both current MCP 2026-07-28 `server/discover` / per-request metadata and legacy
initialize-based protocol versions through 2025-11-25 are supported.

## Test

```powershell
uv run python -m unittest discover -s tests -v
```

The integration suite starts detached brokers and fake legacy/modern stdio MCP
servers. It verifies Skill generation and Tool discovery, reuse, repeated calls,
listing, stop, stop-all, idle expiry, tool errors, and automatic broker shutdown.

## Evaluation-build scope

Implemented in this first slice:

- `session start`, `status`, `list`, `call`, `stop`, and `stop --all`
- `generate` with on-demand or `--session` lifecycle guidance
- automatic `SKILL.md`, `mcp.yaml`, and `references/tools.md` generation
- duplicate-start prevention and session reuse
- idle timeout, including `0` to disable it
- staged child shutdown
- Windows Job Object child cleanup
- current and legacy MCP stdio negotiation
