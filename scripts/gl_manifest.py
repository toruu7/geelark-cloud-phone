"""Agent tool-schema export and feature manifest."""
from _version import __version__ as VERSION
import gl_base

def export_agent_schemas(fmt="all", server_url="http://localhost:5055"):
    """Exports universal tool schemas for ANY agent ecosystem:
    - OpenAI / xAI (Grok Bot) Function Calling tools array
    - Model Context Protocol (MCP) tools/list schema
    - OpenAPI 3.1.0 specification (Custom GPTs, Dify, Coze, LangChain)
    """
    mcp_tools = [
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
                        "enum": ["use", "status", "youtube-flow", "tiktok-feed", "batch-run", "broadcast", "batch-profiles", "deep-link", "open-app", "smart-click", "click-text", "scroll-find", "dismiss-popup", "hide-keyboard", "recover", "capture"],
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

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"]
            }
        }
        for t in mcp_tools
    ]

    openapi_spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "GeeLark Cloud Phone Universal Agent Gateway",
            "version": VERSION,
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
                                "schema": mcp_tools[0]["inputSchema"]
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
                                "schema": mcp_tools[2]["inputSchema"]
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

    if fmt in ["openai", "xai"]:
        return {"format": fmt, "tools": openai_tools}
    elif fmt == "mcp":
        return {"format": "mcp", "tools": mcp_tools}
    elif fmt == "openapi":
        return openapi_spec
    return {
        "openai_xai_tools": openai_tools,
        "mcp_tools": mcp_tools,
        "openapi_3_1": openapi_spec
    }

def get_feature_manifest():
    """Returns structured catalog of all capabilities, recipes, batch actions, and configuration."""
    return {
        "version": VERSION,
        "name": "geelark-cloud-phone",
        "description": "Universal GeeLark cloud phone controller for AI agents and automation orchestrators",
        "keywords": [
            "geelark", "cloud-phone", "android-automation", "mobile-agent", "agent-skill",
            "claude-code", "antigravity", "hermes-agent", "openclaw", "codex", "adb",
            "ocr", "n8n", "set-of-mark", "tiktok-automation", "youtube-automation",
            "bezier-gestures"
        ],
        "supported_agents": [
            "Claude Code & Claude Desktop (SKILL.md + MCP)",
            "Google Antigravity (SKILL.md + MCP)",
            "xAI Grok Bot / https://x.ai/bot (Remote MCP + OpenAPI + Plain-Text Prompt)",
            "Cursor & Windsurf (SKILL.md + Stdio/Remote MCP)",
            "OpenClaw & Hermes Agent (SKILL.md + CLI)",
            "OpenAI Codex & Custom GPTs (SKILL.md + OpenAPI 3.1)",
            "Cline, Roo Code & Zed (Stdio MCP)",
            "LangChain, CrewAI, AutoGen, Dify & Coze (OpenAPI + Function Calling)",
            "n8n, Make, Zapier & Telegram/Discord Bots (Webhook /prompt & /run)"
        ],
        "capabilities": {
            "target_management": {
                "description": "Lock onto specific cloud phone profiles without repetitive arguments",
                "commands": ["use", "status", "list-windows", "focus", "launch-app"]
            },
            "visual_screen_capture": {
                "description": "Screen capture with auto-crop, Set-of-Mark numbered badges, and low-token optimization",
                "commands": ["capture", "tap-mark"],
                "features": ["--annotate (SoM badges)", "--low-token (~70% vision token reduction)", "auto-crop toolbar/titlebar"]
            },
            "touch_gestures_navigation": {
                "description": "Human-like gesture curves and navigation controls",
                "commands": ["tap", "swipe", "type", "key", "hide-keyboard"],
                "features": ["Cubic Bézier curve interpolation with easing", "Normalized coordinates (0.0 to 1.0)", "Clipboard paste injection"]
            },
            "windows_native_ocr": {
                "description": "Zero-dependency local Windows OCR engine for fast, free text recognition",
                "commands": ["find-text", "click-text", "wait-text", "scroll-find"],
                "features": ["80ms local execution", "$0 token cost", "Autonomous scroll-find loop"]
            },
            "app_launcher_deep_links": {
                "description": "0.1s instant deep-linking via Android Intents and ADB monkey launching",
                "commands": ["open-app", "deep-link"],
                "common_apps": gl_base.COMMON_APPS
            },
            "automated_compound_recipes": {
                "description": "1-click high-level mobile workflows",
                "commands": ["youtube-flow", "tiktok-feed"],
                "features": ["Auto ad skipping", "Description link finder", "Randomized watch times & like probability"]
            },
            "multi_device_orchestration": {
                "description": "Execute actions across multiple profiles or all devices at once",
                "commands": ["batch-run", "broadcast", "batch-profiles"]
            },
            "self_healing_failsafes": {
                "description": "Obstacle detection, render stability checking, and emergency recovery",
                "commands": ["wait-stable", "dismiss-popup", "recover"]
            },
            "external_integrations": {
                "description": "HTTP Webhook bridge and n8n workflows for Docker and orchestrator triggers",
                "commands": ["webhook_bridge", "n8n-trigger"],
                "components": ["scripts/webhook_bridge.py", "examples/n8n_trigger.json", "examples/sample_batch.json"]
            }
        },
        "supported_batch_actions": [
            "tap", "swipe", "type", "key", "open-app", "deep-link",
            "smart-click", "click-text", "wait-text", "scroll-find",
            "dismiss-popup", "hide-keyboard", "wait-stable", "sleep",
            "capture", "youtube-flow", "tiktok-feed", "prompt"
        ],
        "common_apps": gl_base.COMMON_APPS,
        "key_mappings": {
            "back": "ADB keyevent KEYCODE_BACK; fallback normalized tap (0.18, 0.97)",
            "home": "ADB keyevent KEYCODE_HOME; fallback normalized tap (0.50, 0.97)",
            "recent / appswitch": "ADB keyevent KEYCODE_APP_SWITCH; fallback normalized tap (0.82, 0.97)",
            "enter": "VK_RETURN (0x0D)",
            "tab": "VK_TAB (0x09)",
            "esc": "VK_ESCAPE (0x1B)",
            "backspace": "VK_BACK (0x08)"
        },
        "environment": {
            "is_windows": gl_base.IS_WINDOWS,
            "geelark_exe_path": gl_base.GEELARK_PATH,
            "adb_path": gl_base.GEELARK_ADB_PATH,
            "active_target": gl_base.get_active_target()
        }
    }
