---
name: blender
description: Blender MCPを使って3Dシーン、メッシュ、マテリアル、FBX・GLBなどの3Dファイルを操作する。Blenderを必要としない作業では使用しない。
---

# Blender Session

Blender操作には、同じSkillディレクトリの`mcp.yaml`と
プロジェクト環境に追加した`mcp-to-skills`のSession Modeを使用する。

最初に`uv run mcp-to-skills session status blender`で状態を確認する。
SessionがOFFの場合だけ`uv run mcp-to-skills session start blender`を実行する。

利用するTool:

- `get_scene_info`: 現在のシーン情報を取得する。引数は不要。
- `execute_blender_code`: Blender Pythonコードを実行する。`--json`へ`code`を渡す。

呼び出し例:

```powershell
uv run mcp-to-skills session call blender get_scene_info
uv run mcp-to-skills session call blender execute_blender_code --json '{"code":"print(1)"}'
```

一連の作業中はSessionを再利用し、Tool callごとには停止しない。
Blenderを使う作業が完了したら、結果を確認したうえで
`uv run mcp-to-skills session stop blender`を実行する。
