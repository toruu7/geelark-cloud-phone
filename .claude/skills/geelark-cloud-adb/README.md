# geelark-cloud-adb

Headless GeeLark cloud phone control for Claude (and any agent): start the phone and enable ADB through GeeLark's Cloud OpenAPI, then drive it with ADB. No desktop app, no window, no mouse, so it can run on an always-on server.

- Skill instructions: [SKILL.md](SKILL.md)
- CLI: `scripts/geelark_adb.py` (standard library only; needs `adb`)
- Sibling skill (GUI-based): geelark-cloud-phone

```bash
export GEELARK_API_TOKEN=...        # from GeeLark settings, never commit it
export GEELARK_CLOUD_PHONE_ID=...
python scripts/geelark_adb.py up
python scripts/geelark_adb.py open-url "https://www.youtube.com/watch?v=..." --package com.google.android.youtube
python scripts/geelark_adb.py skip-ad
python scripts/geelark_adb.py shot --out s.png
python scripts/geelark_adb.py down
```

Install as a Claude Code skill by copying or linking this folder to `~/.claude/skills/geelark-cloud-adb`.
Respect each platform's terms; platforms may restrict automated accounts.
