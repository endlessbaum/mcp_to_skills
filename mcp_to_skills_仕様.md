# mcp_to_skills — Session Mode 追加仕様

## 1. 方針変更

MVPに **Experimental Session Mode** を追加する。

従来のon-demand方式も残すが、実運用ではSession Modeを重要機能として評価する。

```text
on-demand
MCP起動
→ 1処理
→ MCP終了


session
MCP起動
→ call
→ call
→ call
→ ...
→ 明示的にstop
→ MCP終了
```

目的は「MCPを常時起動しない」ことであり、「tool callごとにMCPを終了する」ことではない。

---

# 2. Session Modeの基本操作

開始：

```bash
mcp-to-skills session start blender
```

状態確認：

```bash
mcp-to-skills session status blender
```

Tool呼び出し：

```bash
mcp-to-skills session call blender get_scene_info
```

引数あり：

```bash
mcp-to-skills session call blender execute_blender_code \
  --json '{"code":"..."}'
```

終了：

```bash
mcp-to-skills session stop blender
```

---

# 3. ライフサイクル

```text
session start blender
        │
        ▼
 uvx blender-mcp
        │
        ▼
 MCP initialize
        │
        ▼
   Session Ready
        │
    ┌───┼─────────┐
    ▼   ▼         ▼
  call  call      call
    │   │         │
    └───┴─────────┘
        │
        ▼
session stop blender
        │
        ▼
 MCP shutdown
        │
        ▼
 stdio close
        │
        ▼
 process terminate
```

---

# 4. 重要な原則

Session ModeでもMCPをCodexやChatGPT Desktopへ登録しない。

MCP Serverは常に、

```text
Codex
 ↓
Skill
 ↓
mcp-to-skills
 ↓
MCP Server
```

の子として管理する。

ChatGPT/CodexのMCP設定には追加しない。

---

# 5. Session管理

`session start` を実行したCLIプロセス自身が終了するとstdio MCPも終了してしまうため、Session Modeでは小さなBrokerプロセスを使用する。

```text
Codex Skill
     │
     ▼
mcp-to-skills CLI
     │
     │ local IPC
     ▼
┌──────────────────────┐
│ Session Broker       │
│                      │
│ blender              │
│ PID: 12345           │
│ state: ready         │
│                      │
│ MCP Client           │
└──────────┬───────────┘
           │ stdio
           ▼
    blender-mcp
```

BrokerはMCP Serverの親プロセスとなる。

---

# 6. Brokerの重要な制約

Broker自体を永続サービスにはしない。

以下の場合のみ存在する。

```text
MCP Session数 > 0
```

最後のSessionが終了したらBrokerも終了する。

```text
blender stop
 ↓
active sessions = 0
 ↓
Broker終了
```

したがって通常時は、

```text
Broker        OFF
blender-mcp   OFF
```

となる。

---

# 7. Session一覧

```bash
mcp-to-skills session list
```

例：

```text
SERVER       STATE     PID      AGE
blender      ready     18440    04:32
```

何もなければ、

```text
No active MCP sessions.
```

とする。

これはOSプロセス監視ではなく、**mcp_to_skills自身が所有しているSessionの表示**である。

---

# 8. 二重起動防止

既に起動している場合、

```bash
mcp-to-skills session start blender
```

を再実行しても二重起動しない。

```text
Session already running.

blender
PID: 18440
```

既存Sessionを再利用する。

---

# 9. Skillからの利用

生成されるSKILL.mdではSession Modeを優先して案内する。

基本フロー：

```text
Blender操作が必要
 ↓
session status blender
 ↓
OFFなら
 session start blender
 ↓
session call ...
 ↓
必要なだけ作業
```

重要：

**1 tool call終了ごとにstopしない。**

一連のBlender作業が終わるまでSessionを維持する。

---

# 10. 明示的な終了

Skillには、

> Blenderを使用する一連の作業が完了したらSessionを停止する。

というルールを記述する。

```bash
mcp-to-skills session stop blender
```

これにより、

```text
「GLBにして」
 ↓
Session start
 ↓
Blender作業
 ↓
export完了
 ↓
Session stop
```

となる。

---

# 11. 評価版Idle Timeout

終了忘れ対策として、評価版でもIdle Timeoutを実装する。

デフォルト：

```text
10分
```

設定：

```yaml
session:
  idle_timeout: 600
```

最後のtool callから10分経過したら、

```text
idle timeout
 ↓
MCP shutdown
 ↓
process terminate
 ↓
Session削除
```

とする。

---

# 12. Timeout無効化

必要なら、

```yaml
session:
  idle_timeout: 0
```

で無効化可能とする。

ただし推奨しない。

---

# 13. Crash対策

Brokerが異常終了した場合、その子であるMCP Serverも終了させる。

WindowsではJob Object等の利用を検討する。

目的：

```text
Broker crash
      ↓
blender-mcpだけ孤児化
```

を可能な限り防ぐ。

これは本ツールの重要要件とする。

---

# 14. Session Stop

通常終了：

```text
MCP shutdown
 ↓
stdin close
 ↓
正常終了待ち
```

一定時間終了しなければ、

```text
terminate
 ↓
timeout
 ↓
kill
```

と段階的に終了させる。

---

# 15. Stop All

安全弁として、

```bash
mcp-to-skills session stop --all
```

を用意する。

結果：

```text
Stopping MCP sessions...

blender    stopped
foo        stopped

No active MCP sessions.
```

---

# 16. Codex作業終了への対応

理想的にはSkill処理終了時にstopする。

ただし、

- Codex強制終了
- ChatGPT Desktop終了
- PCスリープ
- Codexのエラー
- ユーザーが途中で作業放棄

などがある。

そのため、

**明示stop + Idle Timeout + 親子プロセス管理**

の3段階でSession残留を防止する。

---

# 17. Blenderでの想定

例えば、

```text
User:
「このFBXをThree.jsで使えるようにして」
```

Skill：

```text
session status blender
 ↓
OFF
 ↓
session start blender
 ↓
import FBX
 ↓
scene確認
 ↓
material確認
 ↓
material変更
 ↓
viewport確認
 ↓
mesh最適化
 ↓
GLB export
 ↓
結果確認
 ↓
session stop blender
```

この間だけ、

```text
Broker
blender-mcp
```

が存在する。

---

# 18. On-demandとの使い分け

簡単なMCP：

```text
filesystem
calculator
単発API

→ on-demand
```

状態を維持しながら作業するMCP：

```text
Blender
ブラウザ
IDE
データベース
長時間作業系

→ session
```

---

# 19. Skill側での推奨Mode指定

`mcp.yaml`：

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

単発型：

```yaml
lifecycle:
  mode: on-demand
```

---

# 20. Generate時の自動設定

```bash
mcp-to-skills generate blender
```

では、とりあえず、

```yaml
lifecycle:
  mode: on-demand
```

を生成する。

ユーザーが、

```bash
mcp-to-skills generate blender --session
```

とした場合、

```yaml
lifecycle:
  mode: session
  idle_timeout: 600
```

とする。

将来的にはMCPの性質から推測してもよいが、評価版では自動判断しない。

---

# 21. 評価版で必須とするSession機能

MVP/評価版に以下を含める。

```text
session start
session status
session list
session call
session stop
session stop --all
idle timeout
二重起動防止
```

加えて可能なら、

```text
Broker終了時のMCP子プロセス終了保証
```

まで実装する。

---

# 22. 評価したいポイント

評価版では特に以下を見る。

### 起動コスト

Blender MCPを毎回spawnする場合とSession再利用の場合の差。

### 操作感

Codexが、

```text
start
→ call × N
→ stop
```

を自然に扱えるか。

### Session残留

通常終了・異常終了・Codex中断時にMCPが残らないか。

### Skillとの相性

CodexがSKILL.mdの指示に従って適切なタイミングでstart/stopできるか。

### MCP互換性

Blender以外のstdio MCPでも同じBroker方式が利用できるか。

---

# 23. この機能の位置付け

`mcp_to_skills` の本質はMCP→Skillファイル変換そのものより、

> **MCP ServerのライフサイクルをSkill側へ移すこと**

に置く。

つまり、

```text
Codex lifecycle
    ≠
MCP lifecycle
```

として、

```text
Skill lifecycle
    ↓
MCP lifecycle
```

へ近づける。

理想状態：

```text
普段
MCP = 0

必要になる
 ↓
Skill
 ↓
MCP start

作業中
 ↓
MCP reuse

作業完了
 ↓
MCP stop

通常状態
 ↓
MCP = 0
```

このSession Modeを `mcp_to_skills` 評価版の主要な検証対象とする。