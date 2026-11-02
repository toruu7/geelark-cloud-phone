#!/usr/bin/env python3
"""
Unit and Integration Test Suite for GeeLark Webhook Bridge.
Persona: Usopp (Sniper / Edge-Case Hunter & Test Scout)

Covers:
- GET /health endpoint (liveness check)
- GET / endpoint (endpoint metadata documentation)
- OPTIONS preflight CORS checks
- POST /run:
  * 404 for invalid routes
  * 400 for missing command field
  * 400 for malformed JSON payload
  * 400 for non-dict JSON body (e.g., lists, scalars)
  * Resilient handling of missing, negative, or non-integer Content-Length headers
  * Subprocess invocation with list args, string args, and scalar args
  * Successful CLI execution returning JSON output (HTTP 200)
  * Successful CLI execution returning plain text output (HTTP 200)
  * Non-zero return codes from CLI (HTTP 500)
  * Subprocess timeouts (HTTP 504)
  * Unexpected runtime exceptions during execution (HTTP 500)
"""

import sys
import os
import json
import io
import subprocess
import unittest
from unittest.mock import patch, MagicMock

# Add scripts directory to path
SCRIPT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import webhook_bridge


class DummyRequest:
    def __init__(self, raw_bytes):
        self._file = io.BytesIO(raw_bytes)

    def makefile(self, *args, **kwargs):
        return self._file


class TestWebhookBridge(unittest.TestCase):
    """Test suite for HTTP handlers in GeeLark Webhook Bridge."""

    def _create_handler(self, method="GET", path="/", body=None, headers=None):
        handler = webhook_bridge.GeeLarkBridgeHandler.__new__(webhook_bridge.GeeLarkBridgeHandler)
        handler.path = path
        handler.command = method
        handler.wfile = io.BytesIO()
        handler.headers = headers or {}
        
        if body is not None:
            if isinstance(body, str):
                body_bytes = body.encode("utf-8")
            elif isinstance(body, bytes):
                body_bytes = body
            else:
                body_bytes = json.dumps(body).encode("utf-8")
            handler.rfile = io.BytesIO(body_bytes)
            if "Content-Length" not in handler.headers:
                handler.headers["Content-Length"] = str(len(body_bytes))
        else:
            handler.rfile = io.BytesIO(b"")

        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler

    def test_health_endpoint(self):
        """Verify GET /health returns 200 with service health status."""
        handler = self._create_handler("GET", "/health")
        handler.do_GET()

        handler.send_response.assert_called_with(200)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["status"], "healthy")
        self.assertEqual(output["service"], "geelark-webhook-bridge")

    def test_root_endpoint_metadata(self):
        """Verify GET / returns documentation of endpoints."""
        handler = self._create_handler("GET", "/")
        handler.do_GET()

        handler.send_response.assert_called_with(200)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("endpoints", output)
        self.assertIn("POST /run", output["endpoints"])

    def test_options_preflight_cors(self):
        """Verify OPTIONS returns 200 with CORS headers."""
        handler = self._create_handler("OPTIONS", "/run")
        handler.do_OPTIONS()

        handler.send_response.assert_called_with(200)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["status"], "ok")
        handler.send_header.assert_any_call("Access-Control-Allow-Origin", "*")

    def test_post_invalid_endpoint_returns_404(self):
        """Verify POST to non-existent endpoint returns 404."""
        handler = self._create_handler("POST", "/invalid-endpoint")
        handler.do_POST()

        handler.send_response.assert_called_with(404)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["status"], "error")
        self.assertIn("Endpoint not found", output["message"])

    def test_post_missing_command_returns_400(self):
        """Verify POST /run with missing command returns 400 error."""
        handler = self._create_handler("POST", "/run", body={"args": ["some-arg"]})
        handler.do_POST()

        handler.send_response.assert_called_with(400)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["status"], "error")
        self.assertIn("Missing 'command'", output["message"])

    def test_post_malformed_json_returns_400(self):
        """Verify POST /run with malformed JSON body returns 400 error."""
        handler = self._create_handler("POST", "/run", body="{ INVALID JSON %%%")
        handler.do_POST()

        handler.send_response.assert_called_with(400)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["status"], "error")
        self.assertIn("Invalid JSON body", output["message"])

    def test_post_non_dict_json_body_returns_400(self):
        """Verify POST /run with JSON array or scalar returns 400 error."""
        handler = self._create_handler("POST", "/run", body=[1, 2, 3])
        handler.do_POST()

        handler.send_response.assert_called_with(400)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["status"], "error")
        self.assertIn("JSON body must be an object/dict", output["message"])

    def test_post_missing_or_invalid_content_length(self):
        """Verify missing or non-integer Content-Length header is handled safely without crashing."""
        handler = self._create_handler("POST", "/run", headers={"Content-Length": "invalid_number"})
        handler.do_POST()

        handler.send_response.assert_called_with(400)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["status"], "error")

    def test_post_successful_command_with_json_output(self):
        """Verify POST /run parses stdout as JSON and returns HTTP 200."""
        handler = self._create_handler("POST", "/run", body={"command": "features", "args": ["--json"]})
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"name": "geelark-cloud-phone", "version": "4.1"})
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            handler.do_POST()

            mock_run.assert_called_once()
            called_cmd = mock_run.call_args[0][0]
            self.assertEqual(called_cmd[2], "features")
            self.assertEqual(called_cmd[3], "--json")

            handler.send_response.assert_called_with(200)
            output = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertEqual(output["status"], "success")
            self.assertEqual(output["output"]["name"], "geelark-cloud-phone")

    def test_post_successful_command_with_text_output(self):
        """Verify POST /run preserves text output when stdout is not JSON."""
        handler = self._create_handler("POST", "/run", body={"command": "status"})
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Raw non-JSON CLI status string"
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc):
            handler.do_POST()

            handler.send_response.assert_called_with(200)
            output = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertEqual(output["status"], "success")
            self.assertEqual(output["output"], "Raw non-JSON CLI status string")

    def test_post_command_with_string_and_scalar_args(self):
        """Verify args passed as a string or scalar are properly split and forwarded."""
        # String args
        handler_str = self._create_handler("POST", "/run", body={"command": "tap", "args": "0.5 0.8 --norm"})
        mock_proc = MagicMock(returncode=0, stdout="{}", stderr="")
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            handler_str.do_POST()
            called_cmd = mock_run.call_args[0][0]
            self.assertIn("0.5", called_cmd)
            self.assertIn("0.8", called_cmd)
            self.assertIn("--norm", called_cmd)

        # Scalar int arg
        handler_scalar = self._create_handler("POST", "/run", body={"command": "use", "args": 4})
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            handler_scalar.do_POST()
            called_cmd = mock_run.call_args[0][0]
            self.assertIn("4", called_cmd)

    def test_post_command_failure_returns_500(self):
        """Verify non-zero process exit codes trigger HTTP 500 error response."""
        handler = self._create_handler("POST", "/run", body={"command": "tap", "args": ["invalid", "coords"]})
        
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "ValueError: invalid literal for float"

        with patch("subprocess.run", return_value=mock_proc):
            handler.do_POST()

            handler.send_response.assert_called_with(500)
            output = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertEqual(output["status"], "error")
            self.assertEqual(output["returncode"], 1)
            self.assertIn("ValueError", output["stderr"])

    def test_post_command_timeout_returns_504(self):
        """Verify command timeout triggers HTTP 504 gateway timeout."""
        handler = self._create_handler("POST", "/run", body={"command": "wait-text", "args": ["Skip"]})

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="geelark", timeout=90)):
            handler.do_POST()

            handler.send_response.assert_called_with(504)
            output = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertEqual(output["status"], "error")
            self.assertIn("timed out after 90s", output["message"])

    def test_post_unexpected_exception_returns_500(self):
        """Verify unexpected OS or subprocess exceptions trigger HTTP 500."""
        handler = self._create_handler("POST", "/run", body={"command": "features"})

        with patch("subprocess.run", side_effect=OSError("Fork failed")):
            handler.do_POST()

            handler.send_response.assert_called_with(500)
            output = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertEqual(output["status"], "error")
            self.assertIn("Fork failed", output["message"])

    def test_get_openapi_spec_endpoint(self):
        """Verify GET /openapi.json returns OpenAPI 3.1.0 schema."""
        handler = self._create_handler("GET", "/openapi.json", headers={"Host": "localhost:5055"})
        handler.do_GET()

        handler.send_response.assert_called_with(200)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["openapi"], "3.1.0")
        self.assertIn("/prompt", output["paths"])
        self.assertIn("/mcp", output["paths"])

    def test_get_mcp_sse_discovery_endpoint(self):
        """Verify GET /sse returns Remote MCP capability and tools manifest."""
        handler = self._create_handler("GET", "/sse")
        handler.do_GET()

        handler.send_response.assert_called_with(200)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["protocol"], "mcp")
        self.assertEqual(len(output["tools"]), 3)

    def test_post_prompt_endpoint(self):
        """Verify POST /prompt forwards natural language instruction to geelark.py prompt."""
        handler = self._create_handler("POST", "/prompt", body={"prompt": "watch 3 tiktoks on profile 4", "window": "4"})
        mock_proc = MagicMock(returncode=0, stdout=json.dumps({"status": "success", "transpiled_intent": "tiktok-feed"}), stderr="")

        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            handler.do_POST()
            handler.send_response.assert_called_with(200)
            called_cmd = mock_run.call_args[0][0]
            self.assertEqual(called_cmd[2], "prompt")
            self.assertEqual(called_cmd[3], "watch 3 tiktoks on profile 4")

    def test_post_mcp_jsonrpc_protocol(self):
        """Verify POST /mcp handles initialize, tools/list, and tools/call JSON-RPC 2.0 requests."""
        # 1. initialize
        h_init = self._create_handler("POST", "/mcp", body={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        h_init.do_POST()
        out_init = json.loads(h_init.wfile.getvalue().decode("utf-8"))
        self.assertEqual(out_init["result"]["serverInfo"]["name"], "geelark-cloud-phone")

        # 2. tools/list
        h_list = self._create_handler("POST", "/mcp", body={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        h_list.do_POST()
        out_list = json.loads(h_list.wfile.getvalue().decode("utf-8"))
        self.assertEqual(len(out_list["result"]["tools"]), 3)

        # 3. tools/call (geelark_prompt)
        h_call = self._create_handler("POST", "/mcp", body={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "geelark_prompt", "arguments": {"prompt": "dismiss popups"}}
        })
        mock_proc = MagicMock(returncode=0, stdout=json.dumps({"status": "success"}), stderr="")
        with patch("subprocess.run", return_value=mock_proc):
            h_call.do_POST()
            out_call = json.loads(h_call.wfile.getvalue().decode("utf-8"))
            self.assertFalse(out_call["result"]["isError"])
            self.assertIn("success", out_call["result"]["content"][0]["text"])

    def test_post_oversized_payload_rejected_for_memory_safety(self):
        """Verify payloads larger than MAX_BODY_BYTES are rejected immediately."""
        huge_len = str(webhook_bridge.MAX_BODY_BYTES + 1024)
        handler = self._create_handler("POST", "/run", headers={"Content-Length": huge_len})
        handler.do_POST()
        handler.send_response.assert_called_with(400)
        output = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(output["status"], "error")
        self.assertIn("Payload too large", output["message"])

    def test_mcp_stdio_rpc_handler_methods(self):
        """Verify scripts/mcp_stdio.py handles initialize, ping, tools/list, tools/call, and unknown methods."""
        import mcp_stdio

        # 1. initialize
        res_init = mcp_stdio.handle_rpc_message({"jsonrpc": "2.0", "id": 10, "method": "initialize"})
        self.assertEqual(res_init["result"]["serverInfo"]["name"], "geelark-cloud-phone")

        # 2. ping
        res_ping = mcp_stdio.handle_rpc_message({"jsonrpc": "2.0", "id": 11, "method": "ping"})
        self.assertEqual(res_ping["result"], {})

        # 3. notifications/initialized returns None
        self.assertIsNone(mcp_stdio.handle_rpc_message({"jsonrpc": "2.0", "method": "notifications/initialized"}))

        # 4. tools/list
        res_list = mcp_stdio.handle_rpc_message({"jsonrpc": "2.0", "id": 12, "method": "tools/list"})
        self.assertEqual(len(res_list["result"]["tools"]), 3)

        # 5. tools/call (geelark_smart_click)
        with patch.object(mcp_stdio, "run_cli", return_value=(0, '{"status": "success"}')) as mock_cli:
            res_call = mcp_stdio.handle_rpc_message({
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {"name": "geelark_smart_click", "arguments": {"query": "Skip", "window": "4"}}
            })
            self.assertFalse(res_call["result"]["isError"])
            mock_cli.assert_called_once_with("smart-click", ["Skip", "--window", "4"])

        # 6. Unknown tool returns -32601 error
        res_unk_tool = mcp_stdio.handle_rpc_message({
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}}
        })
        self.assertEqual(res_unk_tool["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
