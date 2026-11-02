#!/usr/bin/env python3
"""
GeeLark Native Stdio MCP Server (JSON-RPC 2.0 over stdin/stdout)
Enables instant zero-dependency MCP integration with:
- Claude Desktop & Claude Code
- Cursor & Windsurf
- Cline & Roo Code
- Google Antigravity
- Zed & OpenCode

Usage in mcp.json / claude_desktop_config.json:
{
  "mcpServers": {
    "geelark-cloud-phone": {
      "command": "python",
      "args": ["<path-to>/geelark-cloud-phone/scripts/mcp_stdio.py"]
    }
  }
}
"""

import sys
import os
import json
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GEELARK_PY = os.path.join(SCRIPT_DIR, "geelark.py")

sys.path.insert(0, SCRIPT_DIR)
from webhook_bridge import MCP_TOOLS_MANIFEST, ALLOWED_COMMANDS, normalize_cli_args
from _version import __version__ as VERSION


def run_cli(command, args=None):
    if str(command) not in ALLOWED_COMMANDS:
        return 1, f"Command '{command}' is not allowed"
    cmd = [sys.executable, GEELARK_PY, str(command)]
    cmd.extend(normalize_cli_args(args))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    return proc.returncode, proc.stdout.strip() or proc.stderr.strip()


def handle_rpc_message(msg):
    rpc_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "geelark-cloud-phone", "version": VERSION}
            }
        }
    elif method in ["notifications/initialized"]:
        return None
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"tools": MCP_TOOLS_MANIFEST}
        }
    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        try:
            if tool_name == "geelark_prompt":
                p_args = [str(tool_args.get("prompt", ""))]
                if tool_args.get("window"):
                    p_args.extend(["--window", str(tool_args["window"])])
                code, out = run_cli("prompt", p_args)
            elif tool_name == "geelark_smart_click":
                sc_args = [str(tool_args.get("query", ""))]
                if tool_args.get("window"):
                    sc_args.extend(["--window", str(tool_args["window"])])
                code, out = run_cli("smart-click", sc_args)
            elif tool_name == "geelark_command":
                c_name = tool_args.get("command", "status")
                c_args = tool_args.get("args", [])
                code, out = run_cli(c_name, c_args)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                }

            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": out}],
                    "isError": code != 0
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32000, "message": str(e)}
            }
    elif rpc_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }
    return None


def main():
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                resp = handle_rpc_message(msg)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
    except (KeyboardInterrupt, EOFError, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
