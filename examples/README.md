# Triggering GeeLark Cloud Phone Automation via n8n

This example shows how to trigger GeeLark cloud phone automations directly from **n8n** (running locally in Docker or installed natively on Windows).

---

## Architecture Overview

```
[Trigger: Webhook / Cron / Chatbot]
                  │
                  ▼
          [n8n Workflow]
                  │
     ┌────────────┴────────────┐
     ▼                         ▼
(Docker n8n)              (Host n8n)
HTTP POST to              Execute Command node
http://host.docker.internal:5055/run   python scripts/geelark.py
     │                         │
     ▼                         │
[scripts/webhook_bridge.py]    │
     │                         │
     └────────────┬────────────┘
                  ▼
      [GeeLark Cloud Phone Window]
```

---

## Option 1: n8n Running in Local Docker (Recommended)

Because Docker containers run in an isolated Linux environment, they communicate with your Windows host via `host.docker.internal`.

### Step 1: Start the Webhook Bridge on Windows
In a Windows terminal:
```powershell
python scripts/webhook_bridge.py
```
This starts a lightweight zero-dependency bridge on port `5055`.

### Step 2: Import the Workflow in n8n
1. Open your n8n dashboard (e.g. `http://localhost:5678`).
2. Go to **Workflows** -> **Import from File**.
3. Select `examples/n8n_trigger.json`.

### Step 3: Trigger via HTTP POST
You can test the webhook via curl or any API tester:
```bash
# Example 1: Open a YouTube video instantly
curl -X POST http://localhost:5678/webhook/geelark-action \
  -H "Content-Type: application/json" \
  -d '{
    "command": "deep-link",
    "args": ["https://www.youtube.com/watch?v=Bm84BAtOfQw"]
  }'

# Example 2: Skip an ad
curl -X POST http://localhost:5678/webhook/geelark-action \
  -H "Content-Type: application/json" \
  -d '{
    "command": "click-text",
    "args": ["Skip"]
  }'

# Example 3: Tap normalized coordinates
curl -X POST http://localhost:5678/webhook/geelark-action \
  -H "Content-Type: application/json" \
  -d '{
    "command": "tap",
    "args": ["0.5", "0.8", "--norm"]
  }'
```

---

## Option 2: n8n Installed Directly on Windows (`npx n8n`)

If you installed n8n directly on Windows (`npm install -g n8n` or `npx n8n`):
1. In the imported workflow, connect **Webhook Inbound** directly to the **Execute Directly (Host n8n)** node.
2. The node runs:
   ```bash
   python "C:\Users\Backspace\.gemini\config\skills\geelark-cloud-phone\scripts\geelark.py" {{ $json.body.command }} {{ $json.body.args.join(' ') }}
   ```
3. It executes natively on your desktop without requiring the webhook bridge.
