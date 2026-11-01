#!/usr/bin/env python3
"""
GeeLark Webhook Bridge for n8n & External Orchestrators
Runs on Windows Host to allow Docker containers (like n8n), webhooks,
and remote agents to execute GeeLark commands seamlessly via HTTP POST.

Usage:
  python scripts/webhook_bridge.py [--port 5055]
"""

import sys
import os
import json
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 5055
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
GEELARK_PY = os.path.join(SCRIPT_DIR, "geelark.py")

class GeeLarkBridgeHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def do_OPTIONS(self):
        self._send_json(200, {"status": "ok"})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "healthy", "service": "geelark-webhook-bridge"})
        else:
            self._send_json(200, {
                "service": "geelark-webhook-bridge",
                "endpoints": {
                    "POST /run": "Execute a GeeLark CLI command",
                    "GET /health": "Health check"
                }
            })

    def do_POST(self):
        if self.path != "/run":
            self._send_json(404, {"status": "error", "message": "Endpoint not found. Use POST /run"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length < 0:
                content_length = 0
        except (ValueError, TypeError):
            content_length = 0

        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
        
        try:
            payload = json.loads(body) if body else {}
        except Exception as e:
            self._send_json(400, {"status": "error", "message": f"Invalid JSON body: {str(e)}"})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {"status": "error", "message": "JSON body must be an object/dict"})
            return

        command = payload.get("command")
        args = payload.get("args", [])
        
        if not command:
            self._send_json(400, {"status": "error", "message": "Missing 'command' field in request body"})
            return

        cmd = [sys.executable, GEELARK_PY, str(command)]
        if isinstance(args, list):
            cmd.extend([str(a) for a in args])
        elif isinstance(args, str):
            cmd.extend(args.split())
        elif isinstance(args, (int, float, bool)):
            cmd.append(str(args))

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            try:
                stdout_parsed = json.loads(proc.stdout.strip())
            except Exception:
                stdout_parsed = proc.stdout.strip()

            response = {
                "status": "success" if proc.returncode == 0 else "error",
                "returncode": proc.returncode,
                "command": cmd,
                "output": stdout_parsed,
                "stderr": proc.stderr.strip() if proc.stderr else None
            }
            self._send_json(200 if proc.returncode == 0 else 500, response)
        except subprocess.TimeoutExpired:
            self._send_json(504, {"status": "error", "message": "Command timed out after 90s"})
        except Exception as e:
            self._send_json(500, {"status": "error", "message": str(e)})

    def log_message(self, format, *args):
        # Clean logging
        sys.stderr.write(f"[GeeLarkBridge] {args[0]} - {args[1]}\n")

def main():
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else PORT
    server = HTTPServer(("0.0.0.0", port), GeeLarkBridgeHandler)
    print(f"[*] GeeLark Webhook Bridge listening on http://0.0.0.0:{port}")
    print(f"[*] Docker containers can reach this at: http://host.docker.internal:{port}/run")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping GeeLark Webhook Bridge")
        server.server_close()

if __name__ == "__main__":
    main()
