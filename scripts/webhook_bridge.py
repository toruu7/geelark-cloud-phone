#!/usr/bin/env python3
"""
GeeLark Universal Agent Gateway & Webhook Bridge (v4.2)
Runs on Windows Host to allow ANY AI Agent or Orchestrator to control GeeLark Cloud Phones:
- x.ai/bot (Grok Bot), Claude, Cursor, Windsurf (via Remote MCP /mcp & /sse)
- OpenAI Custom GPTs, Dify, Coze, LangChain, CrewAI (via /openapi.json & Function Calling)
- Telegram/Discord Bots, Small Local LLMs, Make, Zapier (via Plain-Text /prompt)
- n8n & Docker Containers (via /run)

Usage:
  python scripts/webhook_bridge.py [--port 5055] [--tunnel]
"""

import sys
import os
import json
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 5055
MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MB upper bound for memory safety
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GEELARK_PY = os.path.join(SCRIPT_DIR, "geelark.py")

MCP_TOOLS_MANIFEST = [
    {
        "name": "geelark_prompt",
        "description": "Control GeeLark cloud phone using plain natural language instructions (e.g., 'watch 5 tiktoks on profile 4', 'open youtube link and skip ads', 'dismiss popups on all phones').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Plain text instruction to execute on the cloud phone."},
                "window": {"type": "string", "description": "Optional target profile number or window title."}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "geelark_smart_click",
        "description": "Multi-path element clicker: tries ADB UI tree bounds -> Local Windows OCR -> Scroll-Find loop -> Normalized anchor fallback.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text label, content description, or anchor name (e.g. 'Skip', 'Search', 'home')."},
                "window": {"type": "string", "description": "Optional target profile number."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "geelark_command",
        "description": "Execute any GeeLark CLI command or compound recipe (use, status, youtube-flow, tiktok-feed, batch-run, broadcast, deep-link, dismiss-popup, recover).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": [
                        "use", "status", "youtube-flow", "tiktok-feed", "batch-run",
                        "broadcast", "batch-profiles", "deep-link", "open-app",
                        "smart-click", "click-text", "scroll-find", "dismiss-popup",
                        "hide-keyboard", "recover", "capture", "ensure-device"
                    ],
                    "description": "Command or recipe name."
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments for the command."
                }
            },
            "required": ["command"]
        }
    }
]


def get_openapi_spec(server_url="http://localhost:5055"):
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "GeeLark Cloud Phone Universal Agent Gateway",
            "version": "4.2.0",
            "description": "Universal REST, Webhook, and Remote MCP gateway for controlling GeeLark cloud phones from x.ai/bot (Grok), OpenAI Custom GPTs, Claude, n8n, Dify, CrewAI, and LangChain."
        },
        "servers": [{"url": server_url}],
        "paths": {
            "/prompt": {
                "post": {
                    "operationId": "geelarkPrompt",
                    "summary": "Execute plain-text natural language phone instruction",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": MCP_TOOLS_MANIFEST[0]["inputSchema"]
                            }
                        }
                    },
                    "responses": {"200": {"description": "Execution result"}}
                }
            },
            "/run": {
                "post": {
                    "operationId": "geelarkRunCommand",
                    "summary": "Execute structured GeeLark CLI command or recipe",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": MCP_TOOLS_MANIFEST[2]["inputSchema"]
                            }
                        }
                    },
                    "responses": {"200": {"description": "Command output"}}
                }
            },
            "/mcp": {
                "post": {
                    "operationId": "geelarkMcpJsonRpc",
                    "summary": "Model Context Protocol (MCP) JSON-RPC 2.0 endpoint",
                    "responses": {"200": {"description": "JSON-RPC 2.0 response"}}
                }
            }
        }
    }


class GeeLarkBridgeHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def _read_json_body(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length < 0:
                content_length = 0
        except (ValueError, TypeError):
            content_length = 0

        if content_length > MAX_BODY_BYTES:
            return None, f"Payload too large ({content_length} bytes exceeds {MAX_BODY_BYTES} byte limit)"

        body = self.rfile.read(content_length).decode("utf-8", errors="replace") if content_length > 0 else ""
        try:
            payload = json.loads(body) if body else {}
        except Exception as e:
            return None, f"Invalid JSON body: {str(e)}"

        if not isinstance(payload, dict):
            return None, "JSON body must be an object/dict"
        return payload, None

    def _run_geelark_cli(self, command, args=None):
        cmd = [sys.executable, GEELARK_PY, str(command)]
        if isinstance(args, list):
            cmd.extend([str(a) for a in args])
        elif isinstance(args, str):
            cmd.extend(args.split())
        elif isinstance(args, (int, float, bool)):
            cmd.append(str(args))

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        try:
            stdout_parsed = json.loads(proc.stdout.strip())
        except Exception:
            stdout_parsed = proc.stdout.strip()

        return {
            "status": "success" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "command": cmd,
            "output": stdout_parsed,
            "stderr": proc.stderr.strip() if proc.stderr else None
        }

    def do_OPTIONS(self):
        self._send_json(200, {"status": "ok"})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "healthy", "service": "geelark-webhook-bridge", "version": "4.2.0"})
        elif self.path == "/openapi.json":
            host = self.headers.get("Host", f"localhost:{PORT}")
            scheme = "https" if "trycloudflare" in host or "ngrok" in host else "http"
            self._send_json(200, get_openapi_spec(server_url=f"{scheme}://{host}"))
        elif self.path in ["/mcp", "/sse"]:
            self._send_json(200, {
                "protocol": "mcp",
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "geelark-cloud-phone", "version": "4.2.0"},
                "tools": MCP_TOOLS_MANIFEST
            })
        else:
            self._send_json(200, {
                "service": "geelark-webhook-bridge",
                "version": "4.2.0",
                "endpoints": {
                    "POST /run": "Execute a GeeLark CLI command or recipe",
                    "POST /prompt": "Execute a plain-text natural language phone instruction",
                    "POST /mcp": "Model Context Protocol (MCP) JSON-RPC 2.0 endpoint",
                    "GET /sse": "Remote MCP capability & tool manifest",
                    "GET /openapi.json": "OpenAPI 3.1.0 specification for x.ai/bot & Custom GPTs",
                    "GET /health": "Health check"
                }
            })

    def do_POST(self):
        if self.path not in ["/run", "/prompt", "/mcp", "/sse"]:
            self._send_json(404, {"status": "error", "message": "Endpoint not found. Use POST /run, POST /prompt, or POST /mcp"})
            return

        payload, err = self._read_json_body()
        if err:
            self._send_json(400, {"status": "error", "message": err})
            return

        # Route 1: Plain-Text Natural Language Prompt (/prompt)
        if self.path == "/prompt":
            prompt_text = payload.get("prompt", payload.get("text", ""))
            if not prompt_text:
                self._send_json(400, {"status": "error", "message": "Missing 'prompt' field in request body"})
                return
            cli_args = [str(prompt_text)]
            if payload.get("window"):
                cli_args.extend(["--window", str(payload["window"])])
            try:
                res = self._run_geelark_cli("prompt", cli_args)
                self._send_json(200 if res["returncode"] == 0 else 500, res)
            except subprocess.TimeoutExpired:
                self._send_json(504, {"status": "error", "message": "Command timed out after 90s"})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})
            return

        # Route 2: Model Context Protocol JSON-RPC 2.0 (/mcp or /sse)
        if self.path in ["/mcp", "/sse"]:
            rpc_id = payload.get("id")
            method = payload.get("method", "")
            params = payload.get("params") or {}

            if method == "initialize":
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "geelark-cloud-phone", "version": "4.2.0"}
                    }
                })
                return
            elif method in ["notifications/initialized", "ping"]:
                self._send_json(200, {"jsonrpc": "2.0", "id": rpc_id, "result": {}})
                return
            elif method == "tools/list":
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {"tools": MCP_TOOLS_MANIFEST}
                })
                return
            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments") or {}
                try:
                    if tool_name == "geelark_prompt":
                        p_args = [str(tool_args.get("prompt", ""))]
                        if tool_args.get("window"):
                            p_args.extend(["--window", str(tool_args["window"])])
                        res = self._run_geelark_cli("prompt", p_args)
                    elif tool_name == "geelark_smart_click":
                        sc_args = [str(tool_args.get("query", ""))]
                        if tool_args.get("window"):
                            sc_args.extend(["--window", str(tool_args["window"])])
                        res = self._run_geelark_cli("smart-click", sc_args)
                    elif tool_name == "geelark_command":
                        c_name = tool_args.get("command", "status")
                        c_args = tool_args.get("args", [])
                        res = self._run_geelark_cli(c_name, c_args)
                    else:
                        self._send_json(400, {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                        })
                        return

                    self._send_json(200, {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(res["output"], indent=2) if isinstance(res["output"], dict) else str(res["output"])}],
                            "isError": res["returncode"] != 0
                        }
                    })
                except Exception as e:
                    self._send_json(500, {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32000, "message": str(e)}
                    })
                return
            else:
                self._send_json(400, {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32601, "message": f"Unsupported MCP method: {method}"}
                })
                return

        # Route 3: Standard CLI Command Runner (/run)
        command = payload.get("command")
        args = payload.get("args", [])

        if not command:
            self._send_json(400, {"status": "error", "message": "Missing 'command' field in request body"})
            return

        try:
            response = self._run_geelark_cli(command, args)
            self._send_json(200 if response["returncode"] == 0 else 500, response)
        except subprocess.TimeoutExpired:
            self._send_json(504, {"status": "error", "message": "Command timed out after 90s"})
        except Exception as e:
            self._send_json(500, {"status": "error", "message": str(e)})


def main():
    port = PORT
    use_tunnel = "--tunnel" in sys.argv
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    server = HTTPServer(("0.0.0.0", port), GeeLarkBridgeHandler)
    print(f"============================================================")
    print(f"  GeeLark Universal Agent Gateway running on port {port}")
    print(f"============================================================")
    print(f"  * Local Webhook (/run):       http://localhost:{port}/run")
    print(f"  * Plain-Text (/prompt):       http://localhost:{port}/prompt")
    print(f"  * Remote MCP (/mcp & /sse):   http://localhost:{port}/mcp")
    print(f"  * OpenAPI 3.1 Spec:           http://localhost:{port}/openapi.json")
    print(f"  * Docker n8n URL:             http://host.docker.internal:{port}/run")

    if use_tunnel:
        print(f"\n[*] Launching public HTTPS ingress tunnel (npx untun)...")
        try:
            subprocess.Popen(["npx", "--yes", "untun@latest", "tunnel", f"http://localhost:{port}"])
        except Exception as e:
            print(f"[!] Could not auto-start tunnel: {e}. Run 'npx untun@latest tunnel http://localhost:{port}' manually.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down bridge...")
        server.server_close()


if __name__ == "__main__":
    main()
