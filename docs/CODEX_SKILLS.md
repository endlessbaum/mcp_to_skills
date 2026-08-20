# Codexから呼び出せるプロジェクトSkillの配置

## 結論

MCP Serverごとに、プロジェクトの`.agents/skills`へSkillディレクトリを配置する。

```text
<REPO_ROOT>/
├─ .agents/
│  └─ skills/
│     └─ blender/
│        ├─ SKILL.md
│        ├─ mcp.yaml
│        └─ references/
│           └─ tools.md
└─ ...
```

Codexは、現在の作業ディレクトリからGitリポジトリのルートまで、各階層の
`.agents/skills`を探索する。リポジトリ内のサブディレクトリから開始した場合も、
ルートのSkillを利用できる。

`SKILL.md`はCodexがSkillを発見・選択するためのファイルで、`mcp.yaml`は
`mcp-to-skills`がstdio MCP Serverを起動するためのファイルである。

## 1. 対象プロジェクトへuvで追加する

`mcp-to-skills`をOS全体へインストールする必要はない。対象プロジェクトの
dev依存関係として追加し、プロジェクトの永続的な`.venv`から実行する。

```powershell
cd <REPO_ROOT>
uv init --bare  # pyproject.tomlがない場合だけ実行
uv add --dev "mcp-to-skills @ git+https://github.com/endlessbaum/mcp_to_skills.git"
uv run mcp-to-skills --version
```

`uv add`により`pyproject.toml`と`uv.lock`が更新され、実体はプロジェクト内の
`.venv`へインストールされる。グローバルPATHの設定やPowerShell、Codexの
再起動は不要である。Skill内でも必ず`uv run mcp-to-skills`を使用する。

GitHub版を更新する場合:

```powershell
uv lock --upgrade-package mcp-to-skills
uv sync
```

`mcp.yaml`内の`uvx`はMCP Server自体を起動するための指定であり、
`mcp-to-skills`のインストール方式とは別である。

## 2. プロジェクトSkillを配置する

Blenderの場合:

```text
<REPO_ROOT>/.agents/skills/blender/SKILL.md
<REPO_ROOT>/.agents/skills/blender/mcp.yaml
```

対象プロジェクトのルートで次を実行すると、自動配置される。

```powershell
cd <REPO_ROOT>
uv run mcp-to-skills generate blender --session
```

このコマンドは既定で`uvx blender-mcp`を検査用に一時起動し、MCPの
`tools/list`からTool名、説明、引数スキーマを取得したあと停止する。生成先は
`.agents/skills/blender`である。

MCP Serverの起動方法が既定と異なる場合は、既存の設定を指定する。

```powershell
uv run mcp-to-skills generate blender --session --config C:\path\to\mcp.yaml
```

または`--command`と繰り返し指定できる`--arg`を使う。MCPを起動できない状態で
雛形だけ作る場合は`--no-inspect`を使用できるが、`references/tools.md`にはTool
情報が入らない。既存の生成ファイルを更新するときだけ`--force`を指定する。

`--session`を省略すると、仕様どおり`lifecycle.mode: on-demand`が生成される。

Skillディレクトリ名、`SKILL.md`の`name`、`mcp.yaml`の`name`は同じ値にする。

```text
blender/
SKILL.md: name: blender
mcp.yaml:  name: blender
```

これにより、リポジトリ内のどこから次を実行しても、Skillと同居した設定が
自動的に見つかる。

```powershell
uv run mcp-to-skills session start blender
```

## 3. 生成されたSKILL.mdを確認する

最低限、YAML frontmatterの`name`と`description`が必要である。
`description`はCodexが暗黙にSkillを選ぶ判断材料になるため、対象作業と
対象外を具体的に書く。

```markdown
---
name: blender
description: Blender MCPを使って3Dシーン、メッシュ、マテリアル、3Dファイル変換を操作する。Blenderを必要としない作業では使用しない。
---

# Blender Session

Blender操作にはプロジェクト環境のmcp-to-skills Session Modeを使用する。

1. `uv run mcp-to-skills session status blender`で状態を確認する。
2. OFFなら`uv run mcp-to-skills session start blender`を実行する。
3. `uv run mcp-to-skills session call blender <tool> [--json '<object>']`で必要な操作を続ける。
4. Tool callごとには停止しない。
5. 一連のBlender作業が完了したら`uv run mcp-to-skills session stop blender`を実行する。
```

`generate`はTool名、用途、引数スキーマを`references/tools.md`へ分離し、
`SKILL.md`から必要時に読むよう指示する。MCP Serverの説明だけでは利用場面が
曖昧な場合は、生成後に`description`を具体化する。

## 4. 生成されたmcp.yamlを確認する

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

MCPプロセスは親プロセスの環境変数を継承する。APIキーなどの秘密情報を
リポジトリ内の`mcp.yaml`へ直接コミットしない。

## 5. Codexから呼び出す

Codexを対象プロジェクトまたはそのサブディレクトリで開始する。

明示的に呼び出す場合:

```text
$blender このFBXを読み込み、Three.js向けのGLBとして出力して
```

Codex CLIまたはIDEでは`/skills`でも発見済みSkillを確認できる。
ChatGPTデスクトップではサイドバーのSkillsから確認できる。

Skillの`description`と依頼内容が一致すれば、`$blender`を明示しなくても
Codexが自動選択できる。ただし、最初の動作確認では明示呼び出しを使う。

Skillの追加・変更は通常自動検出される。表示されない場合は、対象リポジトリを
作業ディレクトリとして開いていることを確認してからCodexを再起動する。

## 6. 呼び出し確認

最初は副作用の小さいToolで確認する。

```text
$blender 現在のシーン情報だけを取得して。変更はしないで。
```

確認ポイント:

1. CodexがSkillの`SKILL.md`を読み込む。
2. `session status blender`を実行する。
3. 必要な場合だけSessionを開始する。
4. `get_scene_info`など、Skillに記載したToolを呼び出す。
5. 作業完了後にSessionを停止する。

Skillが見つからない場合は次を確認する。

- Codexの作業ディレクトリが対象リポジトリ内にある。
- パスが`.agent/skills`ではなく`.agents/skills`になっている。
- ファイル名が大文字の`SKILL.md`になっている。
- frontmatterに`name`と`description`がある。
- `name`が小文字英数字とハイフンで構成されている。
- Skillが`~/.codex/config.toml`の`[[skills.config]]`で無効化されていない。
- 変更が表示されない場合はCodexを再起動する。

## 個人Skillとの違い

全プロジェクトで使う個人Skillは`$HOME/.agents/skills/<name>`へ置く。
プロジェクトと一緒に管理・レビュー・共有するMCP Skillは、
`<REPO_ROOT>/.agents/skills/<name>`へコミットする。

`~/.codex/skills/.system`はCodex組み込みSkill用であり、プロジェクトSkillの
配置先には使用しない。

## 配布時

単一リポジトリ内で使う場合は`.agents/skills`で十分である。複数リポジトリや
他ユーザーへインストール可能な形で配布する場合は、将来的にSkillと実行環境を
Pluginとしてパッケージ化する。
