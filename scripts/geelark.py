#!/usr/bin/env python3
"""
GeeLark Cloud Phone Controller CLI (facade).

The implementation lives in the gl_* modules next to this file:
  gl_base.py - Shared foundation: Win32 handles, constants, paths, active-target session, gesture math.
  gl_win32.py - Window discovery, focusing, raw screen-rect capture and phone-screen geometry.
  gl_vision.py - Phone screenshot capture, OCR invocation, Set-of-Mark annotation and screen-stability checks.
  gl_input.py - Taps, swipes, typing and navigation keys (GUI mouse events or ADB injection).
  gl_ocr.py - OCR-driven find / click / wait / scroll-find actions.
  gl_apps.py - App launching, deep links, popup dismissal, recovery and UI-tree dump.
  gl_recipes.py - One-command compound recipes (YouTube flow, TikTok feed).
  gl_orch.py - System status and multi-step / multi-phone orchestration (batch-run, broadcast, batch-profiles).
  gl_smart.py - Multi-path element grounding (smart-click).
  gl_cloud.py - GeeLark Cloud OpenAPI client and device-readiness resolver.
  gl_prompt.py - Deterministic plain-text instruction transpiler.
  gl_manifest.py - Agent tool-schema export and feature manifest.
  gl_cli.py - Argument parsing and command dispatch.

This module re-exports every public name so `import geelark` and `python geelark.py <cmd>` keep working.
To patch behaviour in tests, patch the defining gl_* module (each name is defined in exactly one place).
"""

import os
import sys
import json
import time
import subprocess

from _version import __version__ as VERSION
from gl_adb import run_adb
from gl_lock import DeviceLock, LockTimeout
from gl_base import (
    BITMAPINFOHEADER,
    COMMON_APPS,
    GEELARK_ADB_PATH,
    GEELARK_PATH,
    IS_WINDOWS,
    Image,
    ImageChops,
    ImageDraw,
    KEYEVENTF_KEYUP,
    MARKS_CACHE_PATH,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    OCR_HELPER_PATH,
    RECT,
    SCRIPT_DIR,
    SESSION_CACHE_PATH,
    SM_CXVIRTUALSCREEN,
    SM_CYVIRTUALSCREEN,
    SM_XVIRTUALSCREEN,
    SM_YVIRTUALSCREEN,
    SRCCOPY,
    SW_RESTORE,
    VK_BACK,
    VK_CONTROL,
    VK_ESCAPE,
    VK_MENU,
    VK_RETURN,
    VK_TAB,
    VK_V,
    _read_session,
    _write_json_atomic,
    bezier_point,
    ease_in_out,
    gdi32,
    get_active_adb_device,
    get_active_target,
    input_mode,
    kernel32,
    set_active_target,
    user32,
    with_desktop
)
from gl_win32 import (
    capture_rect,
    find_target_window,
    focus_window,
    get_phone_screen_bounds,
    list_windows
)
from gl_vision import (
    capture_and_annotate,
    capture_phone,
    run_ocr,
    tap_mark,
    wait_screen_stable
)
from gl_input import (
    _adb_input_device,
    hide_keyboard,
    send_key,
    set_clipboard_text,
    swipe,
    tap,
    type_text
)
from gl_ocr import (
    click_text_on_screen,
    find_text_on_screen,
    scroll_find,
    wait_and_click_text
)
from gl_apps import (
    deep_link,
    dismiss_popups,
    dump_ui_tree,
    emergency_recover,
    open_app
)
from gl_recipes import (
    recipe_tiktok_feed,
    recipe_youtube_flow
)
from gl_orch import (
    batch_profiles,
    broadcast_action,
    execute_batch_steps,
    get_system_status
)
from gl_smart import (
    KNOWN_UI_ANCHORS,
    RE_XML_BOUNDS,
    RE_XML_DESC,
    RE_XML_NODE,
    RE_XML_TEXT,
    smart_click
)
from gl_cloud import (
    CLOUD_RETRY_STATUSES,
    RE_CLOUD_ENDPOINT,
    cloud_api_request,
    ensure_device_ready
)
from gl_prompt import (
    RE_CLICK_TEXT,
    RE_OPEN_APP,
    RE_PROFILE_NUM,
    RE_TYPE_TEXT,
    RE_URL,
    RE_VIDEO_COUNT,
    execute_natural_prompt
)
from gl_manifest import (
    export_agent_schemas,
    get_feature_manifest
)
from gl_cli import (
    LOCK_FREE_COMMANDS,
    main
)


if __name__ == "__main__":
    main()
