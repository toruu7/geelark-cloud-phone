# Run your GeeLark custom automations from the sheet (via n8n)

You built automations ("task flows") inside GeeLark. This connects them to the sheet: put a task in a **Routine** row (or on the
**Manual** tab), and when the runner reaches that phone it calls your **n8n webhook**; n8n starts the automation on that phone with
GeeLark's API; the runner then **waits until GeeLark says the automation finished** (completed / failed / cancelled) before it
stops the phone.

```
Sheet (Routine / Manual row: phone + "GeeLark automation (n8n)" + flow id)
   -> runner starts the phone, then POSTs {phone_id, flow, params} to your n8n webhook
        -> n8n calls GeeLark "Create custom task" (/open/v1/task/rpa/add) and answers {"task_id": "..."}
   -> runner polls GeeLark "Query task" (/open/v1/task/query) every 10 s until status 3 completed / 4 failed / 7 cancelled
   -> result (and GeeLark's failure reason) is written to the sheet; the phone is stopped
```

Why the runner polls instead of n8n: the phone is billing and must not be stopped while the automation is still running, and the
runner already holds the GeeLark token. n8n only has to start the task and return its id.

## What GeeLark's docs say (and do not say)

Source: the official [GeeLark OpenAPI docs](https://github.com/GeeLark/geelark-openapi).
- **Create custom task** `POST /open/v1/task/rpa/add`: `id` (phone id), `flowId`, `scheduleAt` (timestamp), optional `name`, `remark`, `paramMap`. Returns `taskId`.
- **Task flow query** `POST /open/v1/task/flow/list`: lists your flows (`id`, `title`, `desc`, `params` = parameter names).
- **Query task** `POST /open/v1/task/query` (`ids`): `status` 1 waiting, 2 in progress, 3 completed, 4 failed, 7 cancelled, plus `failCode` / `failDesc`.
- **Cancel task** `POST /open/v1/task/cancel`.
- **Not documented:** whether a task starts a phone that is shut down, and the unit of `scheduleAt` (the examples look like seconds). The runner always starts the phone first, so the first is not a problem; the workflow sends the current time in seconds.

## One-time setup

### 1. Find your flow id (and its parameter names)
From this repo, with `GEELARK_API_TOKEN` set:

```bash
python scripts/geelark.py cloud-api /open/v1/task/flow/list --data '{"page":1,"pageSize":100}'
```

Each item shows `id` (use this as the flow id), `title` and `params` (the parameter names the flow expects). Parameter types:
String -> text, Batch text -> list of text, Number, Boolean, File -> list of links.

### 2. Create two credentials in n8n
- **geelark runner webhook token**: type *Header Auth*, name `X-Webhook-Token`, value = a long random string you make up. The runner will send it.
- **GeeLark API token**: type *Header Auth*, name `Authorization`, value `Bearer <your GeeLark API token>`. This token lives in your n8n; keep that instance private.

### 3. Import the workflow
In n8n: *Workflows > Import from file* > `deploy/n8n/geelark-automation-workflow.json`. Open each node that shows a credential warning and pick the credential from step 2 (webhook node: the runner token; HTTP node: the GeeLark token). **Activate** the workflow and copy the **Production URL** of the Webhook node (not the test URL).

The workflow is four nodes: *Webhook* (checks the token, waits for the answer) -> *Make traceId* (GeeLark wants a UUID header) -> *Start GeeLark automation* (HTTP POST to `/open/v1/task/rpa/add`, with `id`, `flowId`, `paramMap` from the runner's request) -> *Answer the runner* (`{"task_id": ...}`, or `{"status": "failed", "message": ...}` if GeeLark refused).

I could not run n8n here, so the first execution is the real test. Node versions differ slightly between n8n releases; if an import warning appears, the four steps are simple to rebuild by hand.

### 4. Tell the runner where the webhook is (environment variables, never the sheet)

| Variable | Value |
| :--- | :--- |
| `GEELARK_N8N_WEBHOOK_URL` | the Production URL (must be `https://`; `http://` only for localhost) |
| `GEELARK_N8N_WEBHOOK_TOKEN` | the token from step 2 |
| `GEELARK_N8N_WEBHOOK_HEADER` | optional: header name if you did not use `X-Webhook-Token` |

Set them where the runner runs: on your PC (for runs I start locally) **and** in the cloud environment `geelark-test` (for the cloud routine). If the cloud environment restricts outbound domains, allow your n8n host there. The sheet only ever holds the flow id, so nobody who can edit the sheet can send the runner's token to another server.

### 5. Put it in the sheet
- The Library has a task **GeeLark automation (n8n)** (action `webhook`). If your Library lacks it, redeploy the Apps Script and run `setup`, or add the row by hand: name `GeeLark automation (n8n)`, action `webhook`, params_template `{"spec":"{value}"}`.
- In **Routine** (daily) or **Manual** (on demand) add a row: `phone` = a phone or group, `task` = `GeeLark automation (n8n)`, `value` = the flow id, or `flow id | {"Title": "hello", "Desc": "world"}` to pass parameters as JSON.
- Several steps work too: put the task inside a **Playbook** (for example open the app, run the automation, take a screenshot).

## Test it on one phone first

```bash
# a one-task file; replace the phone id and the flow id
echo '[{"task_id":"n8n-test","device":"cloud:<phone id>","action":"webhook","params":{"spec":"<flow id>"}}]' > n8n-test.json
python scripts/geelark.py bulk-run --tasks n8n-test.json --cloud --transport api --no-sheet --only-cloud --max-cloud-phones 1 --retries 0
python scripts/geelark.py bulk-cloud-stop
```

Check: the n8n execution appears, GeeLark shows the task, and the runner prints `GeeLark automation completed`. Then try it from the sheet.

## Behaviour and limits

| Situation | What happens |
| :--- | :--- |
| Automation completes | Task succeeds; GeeLark's task id and run time are in the Reports `output`. |
| Automation fails or is cancelled | Task fails with GeeLark's `failDesc` / `failCode` (for example "Device offline (20129)"). |
| Takes longer than `max_wait_s` (default **600 s**) or the task limit | The runner **cancels** the GeeLark task, then fails the task, so the phone is never stopped under a running automation. Raise the wait by editing the Library row's params_template to `{"spec":"{value}","max_wait_s":1800}` (30 to 3600). |
| n8n unreachable, or answers an error | Task fails with the HTTP status; the URL and token are never printed. |
| The workflow answers no `task_id` | Task fails with a hint (otherwise the phone would be stopped immediately). `"track": false` in the params skips tracking, which is not recommended. |
| Webhook URL not set on the runner | Task fails: `GEELARK_N8N_WEBHOOK_URL is not set`. |

Cost: the phone bills for the whole time the automation runs plus start-up. A task is not interrupted by `max_phone_minutes`, but `daily_phone_minutes` stops new phones and tasks once reached, so raise it for long automations. This task type is allowed a longer time limit than `task_timeout_s` (its `max_wait_s` plus 60 s).

## What this does not do
It starts and tracks *your* automation; it does not look inside it. What the flow does on the account is up to you, and the usual platform rules and the risks to your accounts apply to it just as if you had pressed the button in GeeLark.
