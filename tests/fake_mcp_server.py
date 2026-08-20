"""Small JSON-lines MCP server used by integration tests."""

import json
import os
import sys


calls = 0
modern = "--modern" in sys.argv
for raw in sys.stdin:
    try:
        message = json.loads(raw)
    except ValueError:
        continue
    method = message.get("method")
    if "id" not in message:
        continue
    if method == "server/discover" and modern:
        result = {
            "resultType": "complete",
            "supportedVersions": ["2026-07-28"],
            "capabilities": {"tools": {}},
            "ttlMs": 0,
            "cacheScope": "private",
        }
        response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
    elif method == "initialize" and not modern:
        result = {
            "protocolVersion": message.get("params", {}).get("protocolVersion"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-mcp", "version": "1.0"},
        }
        response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
    elif method == "tools/list":
        if modern and "_meta" not in message.get("params", {}):
            response = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32602, "message": "modern metadata required"},
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo the supplied values.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"value": {"type": "integer"}},
                            },
                        },
                        {
                            "name": "fail",
                            "description": "Return a test error.",
                            "inputSchema": {"type": "object", "additionalProperties": False},
                        },
                    ]
                },
            }
    elif method == "tools/call":
        if modern and "_meta" not in message.get("params", {}):
            response = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32602, "message": "modern metadata required"},
            }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue
        calls += 1
        params = message.get("params", {})
        if params.get("name") == "fail":
            response = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32001, "message": "requested failure"},
            }
        else:
            payload = {"pid": os.getpid(), "calls": calls, "arguments": params.get("arguments", {})}
            response = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
            }
    else:
        response = {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32601, "message": "method not found"},
        }
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
