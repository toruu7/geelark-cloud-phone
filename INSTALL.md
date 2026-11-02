# Installing the GeeLark Cloud Phone Skill 📱⚡

This skill is packaged according to the universal **Agent Skill Standard**, making it compatible with any modern coding agent or CLI:
- **Claude Code** (Anthropic)
- **Hermes Agent**
- **OpenClaw**
- **OpenAI Codex / Custom Agents**
- **Google Antigravity**

---

## ⚡ Quick Prerequisites

Ensure Python 3.8+ is installed on the Windows host with `Pillow`:
```bash
pip install -r requirements.txt
```
No extra native compilers, build tools, or binary dependencies are required.

---

## 1. Google Antigravity

### Global Installation:
Clone or copy the skill folder into your Antigravity skills directory:
```powershell
# Windows PowerShell
New-Item -ItemType Directory -Force -Path "$HOME\.gemini\config\skills"
Copy-Item -Recurse -Force "geelark-cloud-phone" "$HOME\.gemini\config\skills\"
```
Antigravity automatically discovers and activates this skill whenever you ask to control, automate, or inspect GeeLark cloud phones.

---

## 2. Claude Code (Anthropic)

### Option A: Project-level (Recommended)
Copy the skill folder into your workspace's `.claude/skills/` directory:
```powershell
mkdir -p .claude/skills
cp -r geelark-cloud-phone .claude/skills/
```

### Option B: Global (All Claude Code projects)
Copy into your user's global Claude skills folder:
```powershell
mkdir -p "$HOME/.claude/skills"
cp -r geelark-cloud-phone "$HOME/.claude/skills/"
```
When you start Claude Code (`claude`), it will automatically detect `geelark-cloud-phone` in its skill registry.

---

## 3. OpenClaw

In your OpenClaw workspace:
```powershell
mkdir -p skills
cp -r geelark-cloud-phone skills/
```
In your OpenClaw configuration or agent prompt, add `geelark-cloud-phone` to your enabled skills.

---

## 4. Hermes Agent

For Hermes:
```powershell
mkdir -p .hermes/skills
cp -r geelark-cloud-phone .hermes/skills/
```
Hermes will inspect `SKILL.md` and invoke `python scripts/geelark.py` via its command execution tool.

---

## 5. OpenAI Codex / Custom Agent Workflows

If your agent runs from a system prompt or terminal tool:
1. Provide the path to `geelark.py` in your agent prompt.
2. Include the contents of `SKILL.md` in the agent's context or system prompt:
   > "You have access to the GeeLark Cloud Phone Skill. To control cloud phones visually or via ADB, run `python scripts/geelark.py <command>`. Refer to `SKILL.md` for full command syntax and normalized coordinate mapping."

---

## 6. Local Docker n8n Integration

If you want to trigger cloud phone actions via **n8n** running in local Docker:
1. Start the host webhook bridge with a token (listening beyond loopback so Docker can reach it):
   ```powershell
   $env:GEELARK_BRIDGE_TOKEN = "<long random secret>"
   python scripts/webhook_bridge.py --host 0.0.0.0
   ```
2. In n8n, import [`examples/n8n_trigger.json`](examples/n8n_trigger.json).
3. The workflow routes requests to `http://host.docker.internal:5055/run`.
4. See [examples/README.md](examples/README.md) for full instructions and sample curl requests.

---

## 7. Optional: pre-approve read-only commands in Claude Code

To stop Claude Code prompting for commands that only look at the phone, add them to `permissions.allow` in your settings (adjust the path to where you installed the skill):
```json
{
  "permissions": {
    "allow": [
      "Bash(python *geelark-cloud-phone*/scripts/geelark.py status*)",
      "Bash(python *geelark-cloud-phone*/scripts/geelark.py list-windows*)",
      "Bash(python *geelark-cloud-phone*/scripts/geelark.py capture*)",
      "Bash(python *geelark-cloud-phone*/scripts/geelark.py find-text*)"
    ]
  }
}
```
Leave tap, swipe, type, key, batch and recipe commands unapproved so you see each one that changes the phone.
