/**
 * GeeLark bulk automation backend (v2): a Google Sheet as daily routine, task queue and report log.
 *
 * You edit three tabs, all with dropdowns (no typing of task formats):
 *   Phones   - your phones (tick, name, cloud/local, GeeLark profile id)
 *   Library  - named tasks you can pick from ("Open YouTube", "Watch YouTube video", ...)
 *   Routine  - the daily plan: pick a phone, pick a task, optionally a link and a duration. Row order = run order.
 * Settings holds the daily run time, a pause switch and run limits. Dashboard and Reports update themselves.
 *
 * DESIGN IS NOT OWNED BY THIS SCRIPT: colours, widths, fonts, dropdown chips and the Overview layout are applied to the
 * sheet itself. setup() only fills in what is missing and never overwrites an existing dropdown, colour rule or the
 * Overview tab. This script only writes plain values to the hidden _state tab, which the Overview reads.
 *
 * Every day at the run time this script copies the Routine into the Tasks queue. The runner (scripts/geelark.py
 * bulk-run --only-cloud, on a VPS or GitHub Actions) works through the queue and reports back here.
 *
 * Setup: see references/bulk_automation.md. Short version:
 *   1. Paste this file in Extensions > Apps Script. Project Settings > Script properties: SECRET = <random string>.
 *   2. Run setup() once (authorize). 3. Deploy > Manage deployments > edit > New version (access: Anyone).
 */

var TAB = { TASKS: 'Tasks', REPORTS: 'Reports', RUNS: 'Runs', ROUTINE: 'Routine', PHONES: 'Phones',
            LIBRARY: 'Library', PLAYBOOKS: 'Playbooks', SETTINGS: 'Settings', DASH: 'Overview', STATE: '_state' };

var HEADERS = {
  Tasks: ['task_id', 'device', 'action', 'params', 'status', 'attempts', 'worker', 'claimed_at', 'finished_at', 'result',
          'batch', 'phone', 'task', 'value'],
  Reports: ['timestamp', 'run_id', 'task_id', 'device', 'action', 'status', 'attempts', 'duration_s', 'message', 'output',
            'phone', 'task'],
  Runs: ['run_id', 'started', 'finished', 'workers', 'total', 'success', 'failed', 'other', 'notes'],
  Routine: ['enabled', 'phone', 'task', 'value', 'duration_s', 'note'],
  Phones: ['enabled', 'label', 'type', 'phone_id', 'device', 'group'],
  Library: ['name', 'action', 'params_template', 'value_hint', 'description'],
  Playbooks: ['playbook', 'task', 'value', 'duration_s', 'note'],
  Settings: ['setting', 'value', 'help']
};

// Must match the runner's actions (scripts/gl_bulk.py ACTIONS); a test keeps the two lists in sync.
var ALLOWED_ACTIONS = ['open-app', 'force-stop', 'deep-link', 'key', 'tap', 'swipe', 'type', 'sleep', 'screenshot',
                       'click-text', 'wait-text', 'assert-text', 'check-device', 'description-link', 'flow'];

var STALE_MINUTES = 15;        // a task stuck in "running" longer than this is handed out again
var CELL_LIMIT = 2000;         // keep cells small; full detail lives in the runner's local JSONL log
var CATCH_UP_MINUTES = 360;    // if the 5-minute tick was missed, still start the day's batch up to this late
var REPORT_KEEP_DAYS = 90;
var MAX_ROWS = 500;            // dropdown/validation range depth
var TERMINAL = { success: 1, failed: 1, skipped: 1, expired: 1, error: 1 };
var NOW_ = function () { return new Date(); };   // replaced in tests

// setting, default, help
var DEFAULT_SETTINGS = [
  ['enabled', 'TRUE', 'Tick = the routine is queued automatically every day at run_time.'],
  ['run_time', '09:00', 'Time of day the routine is queued (24h, in the time zone below).'],
  ['timezone', '', 'Blank = this spreadsheet\'s time zone (File > Settings).'],
  ['paused', 'FALSE', 'EMERGENCY STOP. While ticked the runner starts nothing and no new batch is queued.'],
  ['on_failure', 'continue', 'continue = keep going after a failed task. stop = skip that phone\'s remaining tasks for the day.'],
  ['retries', '1', 'Extra attempts for a failed task.'],
  ['max_cloud_phones', '2', 'Most cloud phones started at the same time (each bills per minute).'],
  ['task_timeout_s', '120', 'Seconds one task attempt may take.'],
  ['max_phone_minutes', '8', 'Spend cap: a cloud phone takes no new task once it has been up this many minutes.'],
  ['daily_phone_minutes', '120', 'Spend cap: total cloud phone-minutes per day. Once reached, no new phone or task starts.'],
  ['max_runtime_min', '120', 'After this many minutes a run starts no NEW tasks (unfinished ones stay pending).'],
  ['task_delay_s', '2', 'Pause between tasks on the same phone.'],
  ['keep_days', '14', 'How many days of finished tasks stay in the Tasks tab (Reports keep 90 days).'],
  ['report_email', '', 'Where to email the daily report when the day\'s tasks finish. Blank = no email.']
];

var TIMEZONES = ['', 'UTC', 'Africa/Cairo', 'Africa/Johannesburg', 'Africa/Lagos', 'America/Chicago', 'America/Denver',
  'America/Los_Angeles', 'America/New_York', 'America/Sao_Paulo', 'America/Toronto', 'Asia/Bangkok', 'Asia/Dhaka',
  'Asia/Dubai', 'Asia/Hong_Kong', 'Asia/Jakarta', 'Asia/Karachi', 'Asia/Kolkata', 'Asia/Manila', 'Asia/Riyadh',
  'Asia/Seoul', 'Asia/Shanghai', 'Asia/Singapore', 'Asia/Tokyo', 'Australia/Sydney', 'Europe/Berlin', 'Europe/Istanbul',
  'Europe/London', 'Europe/Madrid', 'Europe/Moscow', 'Europe/Paris', 'Pacific/Auckland'];

// name, action, params_template, value_hint, description.  {value} and {duration} are filled from the Routine row.
var LIBRARY_SEED = [
  ['Check phone is online', 'check-device', '{}', '', 'Reports the phone model and foreground app. Changes nothing.'],
  ['Open YouTube', 'open-app', '{"name":"youtube"}', '', 'Launches the YouTube app and checks it reached the foreground.'],
  ['Open TikTok', 'open-app', '{"name":"tiktok"}', '', ''],
  ['Open Chrome', 'open-app', '{"name":"chrome"}', '', ''],
  ['Open link in YouTube', 'deep-link', '{"url":"{value}","package":"com.google.android.youtube"}', 'video link', 'Opens the link inside the YouTube app.'],
  ['Open link in Chrome', 'deep-link', '{"url":"{value}","package":"com.android.chrome"}', 'web link', ''],
  ['Watch YouTube video', 'flow',
    '{"steps":[{"action":"open-app","name":"youtube"},{"action":"deep-link","url":"{value}","package":"com.google.android.youtube"},{"action":"wait-text","text":"Skip","timeout":20,"click":true,"optional":true},{"action":"sleep","seconds":{duration}}]}',
    'video link + duration', 'Opens the video, skips an ad if one appears, then keeps watching for the chosen duration.'],
  ['Browse YouTube Shorts (~2 min)', 'flow',
    '{"steps":[{"action":"deep-link","url":"https://www.youtube.com/shorts","package":"com.google.android.youtube"},{"action":"sleep","seconds":6},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300},{"action":"sleep","seconds":7},{"action":"swipe","x1":0.5,"y1":0.8,"x2":0.5,"y2":0.15,"duration_ms":300}]}',
    '', 'Opens the YouTube Shorts feed and swipes to a new Short every ~7 seconds for about 2 minutes. Browse only: no likes, comments or subscribes.'],
  ['Click description link', 'description-link', '{"spec":"{value}"}', 'video link | link text',
    'Opens the video, waits out any ad, opens the description, then TAPS the link whose text you give: it opens in the in-app browser tab and the page loads. Waits, screenshots the page, then goes back. Value = video link, a bar, then the link text. Stops without tapping if an ad is on screen or the description cannot be confirmed.'],
  ['Skip ad if shown', 'wait-text', '{"text":"Skip","timeout":30,"click":true,"optional":true}', '', 'Taps Skip if an ad shows it; fine if there is no ad.'],
  ['Wait', 'sleep', '{"seconds":{duration}}', 'duration', ''],
  ['Next video (swipe up)', 'swipe', '{"x1":0.5,"y1":0.78,"x2":0.5,"y2":0.25,"duration_ms":350}', '', ''],
  ['Tap text on screen', 'click-text', '{"text":"{value}"}', 'button text', 'Finds a button/label by its text and taps it.'],
  ['Confirm text is on screen', 'assert-text', '{"text":"{value}"}', 'text to look for', 'Marks the task failed if the text is not visible.'],
  ['Press Back', 'key', '{"name":"back"}', '', ''],
  ['Press Home', 'key', '{"name":"home"}', '', ''],
  ['Close YouTube', 'force-stop', '{"name":"youtube"}', '', ''],
  ['Close TikTok', 'force-stop', '{"name":"tiktok"}', '', ''],
  ['Close Chrome', 'force-stop', '{"name":"chrome"}', '', ''],
  ['Take screenshot', 'screenshot', '{}', '', 'Saved on the runner; the file path appears in Reports.']
];

var DURATIONS = [5, 10, 15, 30, 45, 60, 90, 120, 180, 300, 600, 900, 1800, 3600];

// ---------------------------------------------------------------------------------------------------------------
// Web app entry point (called by the runner)
// ---------------------------------------------------------------------------------------------------------------
function doPost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return out_({ ok: false, error: 'bad_json' });
  }
  var secret = PropertiesService.getScriptProperties().getProperty('SECRET');
  if (!secret || body.secret !== secret) {
    return out_({ ok: false, error: 'unauthorized' });
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(25000);   // serializes claims so two workers never get the same task
  try {
    switch (body.action) {
      case 'ping':     return out_({ ok: true, now: NOW_().toISOString() });
      case 'claim':    return out_(claim_(body));
      case 'devices':  return out_(devices_());
      case 'settings': return out_({ ok: true, settings: settingsForRunner_() });
      case 'report':   return out_(report_(body));
      case 'log':      return out_(log_(body));
      case 'summary':  return out_(summary_(body));
      case 'enqueue':  return out_(enqueueNow_(body));
      case 'inspect':  return out_(inspect_());
      default:         return out_({ ok: false, error: 'unknown_action' });
    }
  } catch (err) {
    return out_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// ---------------------------------------------------------------------------------------------------------------
// Queue: claim / devices / report / log / summary
// ---------------------------------------------------------------------------------------------------------------
function claim_(body) {
  var t = table_(TAB.TASKS);
  need_(t, ['task_id', 'device', 'action', 'params', 'status', 'attempts', 'worker', 'claimed_at']);
  var worker = String(body.worker || '');
  var limit = Math.max(1, Math.min(Number(body.limit) || 1, 20));
  var now = NOW_();
  var claimed = [];
  for (var i = 0; i < t.rows.length && claimed.length < limit; i++) {
    var row = t.rows[i];
    var status = String(row.status || '').trim().toLowerCase();
    var device = String(row.device || '').trim();
    if (!String(row.action || '').trim()) continue;
    var stale = status === 'running' && row.claimed_at && (now - new Date(row.claimed_at)) > STALE_MINUTES * 60000;
    if (!(status === '' || status === 'pending' || stale)) continue;
    if (device && device !== worker) continue;          // blank device = any worker may take it
    if (!device && body.exact) continue;                // ...except billed cloud phones, which only take tasks addressed to them
    var taskId = String(row.task_id || '') || ('row-' + row._row);
    setCells_(t, row, { task_id: taskId, status: 'running', worker: worker, claimed_at: now.toISOString() });
    claimed.push({ task_id: taskId, device: device, action: String(row.action).trim(),
                   params: String(row.params || ''), attempts: Number(row.attempts) || 0 });
  }
  return { ok: true, tasks: claimed };
}

// Distinct devices named by tasks that are waiting, plus how many waiting tasks name no device at all.
function devices_() {
  var t = table_(TAB.TASKS);
  need_(t, ['device', 'action', 'status', 'claimed_at']);
  var now = NOW_();
  var seen = {};
  var blank = 0;
  t.rows.forEach(function (row) {
    var status = String(row.status || '').trim().toLowerCase();
    var stale = status === 'running' && row.claimed_at && (now - new Date(row.claimed_at)) > STALE_MINUTES * 60000;
    if (!(status === '' || status === 'pending' || stale)) return;
    if (!String(row.action || '').trim()) return;
    var device = String(row.device || '').trim();
    if (device) seen[device] = true; else blank++;
  });
  return { ok: true, devices: Object.keys(seen), blank: blank };
}

function report_(body) {
  var t = table_(TAB.TASKS);
  need_(t, ['task_id', 'status', 'attempts', 'finished_at', 'result']);
  var status = String(body.status || 'unknown');
  var row = null;
  for (var i = t.rows.length - 1; i >= 0; i--) {
    if (String(t.rows[i].task_id) === String(body.task_id)) { row = t.rows[i]; break; }
  }
  if (row) {
    setCells_(t, row, {
      status: status === 'success' ? 'success' : (status === 'skipped' ? 'skipped' : 'failed'),
      attempts: Number(body.attempts) || 0, finished_at: NOW_().toISOString(), result: clip_(body.message)
    });
  }
  appendObj_(TAB.REPORTS, {
    timestamp: NOW_().toISOString(), run_id: body.run_id || '', task_id: body.task_id || '', device: body.device || '',
    action: body.task_action || '', status: status, attempts: Number(body.attempts) || 0,
    duration_s: Number(body.duration_s) || 0, message: clip_(body.message), output: clip_(body.output),
    phone: row ? row.phone || '' : '', task: row ? row.task || '' : ''
  });
  if (row && row.batch) maybeSendReport_(batchKey_(row.batch), 'All tasks finished.');
  safely_(refreshDashboard_);
  return { ok: true };
}

// Non-task events: device offline, retries, warnings, "any other report".
function log_(body) {
  appendObj_(TAB.REPORTS, {
    timestamp: NOW_().toISOString(), run_id: body.run_id || '', task_id: body.task_id || '', device: body.device || '',
    action: body.task_action || 'event', status: body.level || 'info', message: clip_(body.message), output: clip_(body.output)
  });
  return { ok: true };
}

function summary_(body) {
  appendObj_(TAB.RUNS, {
    run_id: body.run_id || '', started: body.started || '', finished: body.finished || NOW_().toISOString(),
    workers: body.workers || '', total: Number(body.total) || 0, success: Number(body.success) || 0,
    failed: Number(body.failed) || 0, other: Number(body.other) || 0, notes: clip_(body.notes)
  });
  safely_(refreshDashboard_);
  return { ok: true };
}

// ---------------------------------------------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------------------------------------------
function settingsMap_() {
  var map = {};
  DEFAULT_SETTINGS.forEach(function (d) { map[d[0]] = d[1]; });
  var t;
  try { t = table_(TAB.SETTINGS); } catch (e) { return map; }
  t.rows.forEach(function (r) {
    var key = String(r.setting || '').trim();
    if (key && r.value !== '' && r.value !== undefined && r.value !== null) map[key] = r.value;
  });
  return map;
}

function settingsForRunner_() {
  var map = settingsMap_();
  var out = {};
  Object.keys(map).forEach(function (k) {
    var v = map[k];
    out[k] = (typeof v === 'boolean') ? (v ? 'TRUE' : 'FALSE') : (v instanceof Date ? normalizeTime_(v, tz_(map)) : String(v));
  });
  return out;
}

function truthy_(v) {
  return v === true || /^(true|yes|y|1|on|checked)$/i.test(String(v).trim());
}

function tz_(map) {
  var z = map && map.timezone ? String(map.timezone).trim() : '';
  return z || SpreadsheetApp.getActive().getSpreadsheetTimeZone();
}

// "9:5", "09:00", "09:00:00" or a time-of-day Date  ->  "HH:mm" (or null)
function normalizeTime_(v, tz) {
  if (v instanceof Date) return Utilities.formatDate(v, tz, 'HH:mm');
  var m = /^(\d{1,2}):(\d{2})/.exec(String(v).trim());
  if (!m) return null;
  var h = Number(m[1]), mi = Number(m[2]);
  if (h > 23 || mi > 59) return null;
  return ('0' + h).slice(-2) + ':' + m[2];
}

function minutesOf_(hhmm) {
  var p = hhmm.split(':');
  return Number(p[0]) * 60 + Number(p[1]);
}

// ---------------------------------------------------------------------------------------------------------------
// Daily schedule
// ---------------------------------------------------------------------------------------------------------------
// Time-driven trigger, every 5 minutes. Checking "is it past run_time and not yet queued today" (instead of one
// exact-time trigger) survives edits to run_time, missed ticks and outages.
function tick() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return;
  try {
    var map = settingsMap_();
    var props = PropertiesService.getScriptProperties();
    if (truthy_(map.enabled) && !truthy_(map.paused)) {
      var tz = tz_(map);
      var runAt = normalizeTime_(map.run_time, tz);
      if (runAt) {
        var today = Utilities.formatDate(NOW_(), tz, 'yyyy-MM-dd');
        var nowMin = minutesOf_(Utilities.formatDate(NOW_(), tz, 'HH:mm'));
        var late = nowMin - minutesOf_(runAt);
        if (props.getProperty('LAST_SCHEDULED_DATE') !== today && late >= 0) {
          if (late <= CATCH_UP_MINUTES) {
            enqueue_({ batch: today, scheduled: true });
          } else {
            props.setProperty('LAST_SCHEDULED_DATE', today);   // too late to start today: skip, don't surprise anyone at night
            appendObj_(TAB.REPORTS, { timestamp: NOW_().toISOString(), device: '', action: 'schedule', status: 'warning',
              message: 'Missed the ' + runAt + ' start on ' + today + ' (tick was not running); skipped.' });
          }
        }
      }
    }
    sendOverdueReport_(map);
    safely_(refreshDashboard_);
  } finally {
    lock.releaseLock();
  }
}

function enqueueNow_(body) {
  var map = settingsMap_();
  var tz = tz_(map);
  var today = Utilities.formatDate(NOW_(), tz, 'yyyy-MM-dd');
  if (body.dry_run) return { ok: true, dry_run: true, result: enqueue_({ batch: today, dryRun: true }) };
  if (truthy_(map.paused)) return { ok: false, error: 'paused' };
  var batch = body.force ? today + '-manual-' + Utilities.formatDate(NOW_(), tz, 'HHmm') : today;
  return { ok: true, result: enqueue_({ batch: batch, scheduled: !body.force }) };
}

// Copy the Routine into the Tasks queue. Never starts a phone itself; the runner does that.
function enqueue_(opts) {
  var batch = opts.batch;
  var phones = readPhones_();
  var playbooks = readPlaybooks_();
  var library = {};
  table_(TAB.LIBRARY).rows.forEach(function (r) { if (String(r.name || '').trim()) library[String(r.name).trim()] = r; });
  var routine = table_(TAB.ROUTINE).rows;
  var plan = [], problems = [], counts = {};
  var groups = {};                                             // group name -> phone labels, in Phones-tab order
  Object.keys(phones).forEach(function (label) {
    var g = phones[label].group;
    if (g) (groups[g] = groups[g] || []).push(label);
  });

  routine.forEach(function (r) {
    var targetName = String(r.phone || r['phone group'] || '').trim();   // header may be "phone" or "phone group"
    var taskName = String(r.task || '').trim();
    if (!targetName && !taskName) return;                      // empty row
    if (!truthy_(r.enabled)) return;                           // switched off
    var where = 'Routine row ' + r._row;
    // a row names one phone, or a group: every phone in the group gets the task
    var labels = phones[targetName] ? [targetName] : groups[targetName];
    if (!labels) { problems.push(where + ': "' + targetName + '" is not a phone or a group in the Phones tab.'); return; }
    labels.forEach(function (phoneName) { addRow_(r, phoneName, where, taskName); });
  });

  // A Routine row names a Library task, or a playbook (a named list of Library tasks, expanded into its steps in order).
  // The Library wins if a name is in both. Playbooks cannot contain playbooks.
  function addRow_(r, phoneName, where, taskName) {
    var phone = phones[phoneName];
    if (!phone.enabled) return;                                // phone switched off: its tasks are skipped quietly
    if (phone.error) { problems.push(where + ': ' + phone.error); return; }
    if (!library[taskName] && playbooks[taskName]) {
      playbooks[taskName].forEach(function (st) {
        addTask_(phoneName, phone, st.task, blank_(st.value) ? r.value : st.value, blank_(st.duration) ? r.duration_s : st.duration,
                 where + ' > playbook "' + taskName + '" step ' + st.n + ' (Playbooks row ' + st.row + ')');
      });
      return;
    }
    addTask_(phoneName, phone, taskName, r.value, r.duration_s, where);
  }

  function addTask_(phoneName, phone, taskName, value, duration, where) {
    var lib = library[taskName];
    if (!lib) { problems.push(where + ': task "' + taskName + '" is not in the Library tab (or, for a Routine row, the Playbooks tab).'); return; }
    var action = String(lib.action || '').trim();
    if (ALLOWED_ACTIONS.indexOf(action) < 0) { problems.push(where + ': library action "' + action + '" is not supported.'); return; }
    var params;
    try {
      params = fillTemplate_(lib.params_template, value, duration);
      var parsed = JSON.parse(params);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('params must be a JSON object');
    } catch (err) {
      problems.push(where + ' (' + taskName + '): ' + err.message);
      return;
    }
    counts[phoneName] = (counts[phoneName] || 0) + 1;
    plan.push({ task_id: batch + '-' + slug_(phoneName) + '-' + ('0' + counts[phoneName]).slice(-2), device: phone.device,
                action: action, params: params, status: 'pending', batch: batch, phone: phoneName, task: taskName,
                value: blank_(value) ? '' : String(value) });
  }

  if (opts.dryRun) return { batch: batch, plan: plan, problems: problems };

  var tasks = table_(TAB.TASKS);
  need_(tasks, ['task_id', 'status']);
  var existing = {};
  tasks.rows.forEach(function (r) { existing[String(r.task_id)] = true; });
  expireOld_(tasks, batch);
  var fresh = plan.filter(function (p) { return !existing[p.task_id]; });
  if (fresh.length) {
    var sh = tasks.sheet;
    var rows = fresh.map(function (p) { return tasks.headers.map(function (h) { return p[h] === undefined ? '' : p[h]; }); });
    sh.getRange(sh.getLastRow() + 1, 1, rows.length, tasks.headers.length).setValues(rows);
  }
  problems.forEach(function (msg) {
    appendObj_(TAB.REPORTS, { timestamp: NOW_().toISOString(), device: '', action: 'routine', status: 'error', message: clip_(msg) });
  });
  var props = PropertiesService.getScriptProperties();
  props.setProperty('LAST_BATCH', batch);
  props.setProperty('LAST_BATCH_AT', NOW_().toISOString());
  props.deleteProperty('REPORTED_' + batch);
  if (opts.scheduled) props.setProperty('LAST_SCHEDULED_DATE', batch.slice(0, 10));
  trim_();
  appendObj_(TAB.REPORTS, { timestamp: NOW_().toISOString(), device: '', action: 'schedule', status: 'info',
    message: 'Queued ' + fresh.length + ' task(s) for ' + batch + (problems.length ? '; ' + problems.length + ' routine problem(s), see error rows.' : '.') });
  if (!fresh.length) maybeSendReport_(batch, 'Nothing to run today.');
  safely_(refreshDashboard_);
  return { batch: batch, enqueued: fresh.length, problems: problems };
}

function blank_(v) { return v === undefined || v === null || String(v).trim() === ''; }

// {playbook name: [{task, value, duration, n, row}]}; a blank playbook cell means "same playbook as the row above".
function readPlaybooks_() {
  var map = {}, current = '';
  table_(TAB.PLAYBOOKS).rows.forEach(function (r) {
    if (!blank_(r.playbook)) current = String(r.playbook).trim();
    var task = String(r.task || '').trim();
    if (!current || !task) return;
    var steps = (map[current] = map[current] || []);
    steps.push({ task: task, value: r.value, duration: r.duration_s, n: steps.length + 1, row: r._row });
  });
  return map;
}

function readPhones_() {
  var map = {};
  table_(TAB.PHONES).rows.forEach(function (r) {
    var label = String(r.label || '').trim();
    if (!label) return;
    var type = String(r.type || 'cloud').trim().toLowerCase();
    var id = String(r.phone_id === undefined ? '' : r.phone_id).trim();
    var p = { enabled: truthy_(r.enabled), device: '', error: '', group: String(r.group || '').trim() };
    if (type === 'local') {
      if (!/^[A-Za-z0-9_.:\-]+$/.test(id)) p.error = 'phone "' + label + '" needs an ADB serial in phone_id.';
      p.device = id;
    } else {
      if (!/^[A-Za-z0-9_\-]+$/.test(id)) p.error = 'phone "' + label + '" needs its GeeLark profile id in phone_id.';
      p.device = 'cloud:' + id;
    }
    map[label] = p;
  });
  return map;
}

// {value} / {duration} in a Library template. In a "quoted" slot they become JSON strings, bare they must be numbers.
function fillTemplate_(template, value, duration) {
  var out = String(template === undefined || template === '' ? '{}' : template);
  var v = value === undefined || value === null ? '' : String(value).trim();
  var d = duration === undefined || duration === null ? '' : String(duration).trim();
  if (out.indexOf('{value}') >= 0 && v === '') throw new Error('this task needs a value (link or text) in the "value" column');
  if (out.indexOf('{duration}') >= 0 && d === '') throw new Error('this task needs a duration_s');
  out = out.replace(/"\{value\}"/g, function () { return JSON.stringify(v); });
  out = out.replace(/"\{duration\}"/g, function () { return JSON.stringify(d); });
  if (out.indexOf('{value}') >= 0) {
    if (!isFinite(Number(v))) throw new Error('value must be a number for this task');
    out = out.replace(/\{value\}/g, function () { return String(Number(v)); });
  }
  if (out.indexOf('{duration}') >= 0) {
    if (!isFinite(Number(d))) throw new Error('duration_s must be a number');
    out = out.replace(/\{duration\}/g, function () { return String(Number(d)); });
  }
  return out;
}

// A batch id like "2026-11-03" looks like a date, so Sheets may store it as one. Always compare it as text.
function batchKey_(v) {
  if (v instanceof Date) return Utilities.formatDate(v, tz_(settingsMap_()), 'yyyy-MM-dd');
  return v === undefined || v === null ? '' : String(v);
}

function slug_(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'phone';
}

// Tasks from an earlier day that never ran are marked expired so yesterday's queue can't run today.
function expireOld_(tasks, batch) {
  var day = String(batch).slice(0, 10);
  tasks.rows.forEach(function (r) {
    var status = String(r.status || '').trim().toLowerCase();
    if (!(status === 'pending' || status === 'running')) return;
    var b = batchKey_(r.batch);
    if (!b || b.slice(0, 10) >= day) return;                   // hand-added rows and same-day rows stay
    setCells_(tasks, r, { status: 'expired', result: 'not run before the next daily batch' });
  });
}

// Drop finished task rows older than keep_days and old report rows, keeping the header and formatting.
function trim_() {
  var map = settingsMap_();
  var keep = Math.max(1, Number(map.keep_days) || 14);
  var cutoff = new Date(NOW_().getTime() - keep * 86400000);
  rewriteWithout_(TAB.TASKS, function (o) {
    var status = String(o.status || '').toLowerCase();
    return TERMINAL[status] && o.finished_at && new Date(o.finished_at) < cutoff ||
           status === 'expired' && o.batch && new Date(batchKey_(o.batch).slice(0, 10)) < cutoff;
  });
  var repCut = new Date(NOW_().getTime() - REPORT_KEEP_DAYS * 86400000);
  rewriteWithout_(TAB.REPORTS, function (o) { return o.timestamp && new Date(o.timestamp) < repCut; });
}

function rewriteWithout_(name, shouldDrop) {
  var t = table_(name);
  var keepRows = t.values.slice(1).filter(function (vals) {
    var o = {};
    t.headers.forEach(function (h, i) { if (h) o[h] = vals[i]; });
    return !shouldDrop(o);
  });
  if (keepRows.length === t.values.length - 1) return;
  var sh = t.sheet;
  if (sh.getLastRow() > 1) sh.getRange(2, 1, sh.getLastRow() - 1, t.headers.length).clearContent();
  if (keepRows.length) sh.getRange(2, 1, keepRows.length, t.headers.length).setValues(keepRows);
}

// ---------------------------------------------------------------------------------------------------------------
// Daily report email
// ---------------------------------------------------------------------------------------------------------------
function batchStats_(batch) {
  var rows = table_(TAB.TASKS).rows.filter(function (r) { return batchKey_(r.batch) === String(batch); });
  var stats = { rows: rows, total: rows.length, open: 0, success: 0, failed: 0, skipped: 0, expired: 0, phones: {}, failures: [] };
  rows.forEach(function (r) {
    var s = String(r.status || '').trim().toLowerCase();
    if (!TERMINAL[s]) stats.open++;
    if (s === 'success') stats.success++;
    else if (s === 'failed' || s === 'error') stats.failed++;
    else if (s === 'skipped') stats.skipped++;
    else if (s === 'expired') stats.expired++;
    var key = String(r.phone || r.device || '?');
    var p = stats.phones[key] || (stats.phones[key] = { total: 0, success: 0, failed: 0, other: 0 });
    p.total++;
    if (s === 'success') p.success++; else if (s === 'failed' || s === 'error') p.failed++; else p.other++;
    if (s === 'failed' || s === 'error') stats.failures.push((r.phone || r.device) + ' / ' + (r.task || r.action) + ': ' + (r.result || 'failed'));
  });
  return stats;
}

function maybeSendReport_(batch, reason) {
  var props = PropertiesService.getScriptProperties();
  if (props.getProperty('REPORTED_' + batch)) return;
  var stats = batchStats_(batch);
  if (stats.open > 0) return;
  props.setProperty('REPORTED_' + batch, NOW_().toISOString());   // set first: never send twice
  sendReport_(batch, stats, reason);
}

function sendOverdueReport_(map) {
  var props = PropertiesService.getScriptProperties();
  var batch = props.getProperty('LAST_BATCH'), at = props.getProperty('LAST_BATCH_AT');
  if (!batch || !at || props.getProperty('REPORTED_' + batch)) return;
  var limitMin = (Number(map.max_runtime_min) || 120) + 30;
  if ((NOW_() - new Date(at)) < limitMin * 60000) return;
  props.setProperty('REPORTED_' + batch, NOW_().toISOString());
  sendReport_(batch, batchStats_(batch), 'INCOMPLETE: the runner did not finish these tasks in time.');
}

function sendReport_(batch, stats, reason) {
  var to = String(settingsMap_().report_email || '').trim();
  if (!to) return;
  var lines = ['GeeLark daily report: ' + batch, reason, '',
    'Tasks: ' + stats.total + '   OK: ' + stats.success + '   Failed: ' + stats.failed + '   Skipped: ' + stats.skipped +
    '   Not finished: ' + stats.open, '', 'Per phone:'];
  Object.keys(stats.phones).forEach(function (k) {
    var p = stats.phones[k];
    lines.push('  ' + k + ': ' + p.success + '/' + p.total + ' OK' + (p.failed ? ', ' + p.failed + ' failed' : ''));
  });
  if (stats.failures.length) {
    lines.push('', 'Problems:');
    stats.failures.slice(0, 30).forEach(function (f) { lines.push('  - ' + f); });
  }
  lines.push('', 'Open the sheet for details: ' + SpreadsheetApp.getActive().getUrl());
  var ok = stats.failed === 0 && stats.open === 0;
  try {
    MailApp.sendEmail(to, 'GeeLark ' + batch + ': ' + (ok ? 'all ' + stats.success + ' OK' : stats.success + '/' + stats.total + ' OK, attention needed'), lines.join('\n'));
  } catch (err) {
    appendObj_(TAB.REPORTS, { timestamp: NOW_().toISOString(), device: '', action: 'email', status: 'error', message: 'Could not send the report email: ' + err });
  }
}

// ---------------------------------------------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------------------------------------------
function refreshDashboard_() {
  var map = settingsMap_();
  var tz = tz_(map);
  var props = PropertiesService.getScriptProperties();
  var status = truthy_(map.paused) ? 'PAUSED (emergency stop)' : (truthy_(map.enabled) ? 'Active' : 'Off (schedule disabled)');
  var runAt = normalizeTime_(map.run_time, tz) || '?';
  var today = Utilities.formatDate(NOW_(), tz, 'yyyy-MM-dd');
  var nowMin = minutesOf_(Utilities.formatDate(NOW_(), tz, 'HH:mm'));
  var next = (props.getProperty('LAST_SCHEDULED_DATE') !== today && runAt !== '?' && nowMin < minutesOf_(runAt) ? 'today' : 'tomorrow') + ' at ' + runAt;
  var state = ensureSheet_(TAB.STATE, []);
  state.getRange(1, 2, 5, 1).setNumberFormat('@');   // keep '2026-11-03' and timestamps as text, not date numbers
  state.getRange(1, 1, 5, 2).setValues([
    ['updated', Utilities.formatDate(NOW_(), tz, 'yyyy-MM-dd HH:mm')],
    ['status', status],
    ['next_run', next],
    ['latest_batch', props.getProperty('LAST_BATCH') || '(none yet)'],
    ['timezone', tz]
  ]);
  try { state.hideSheet(); } catch (e) { /* already hidden */ }
}

// ---------------------------------------------------------------------------------------------------------------
// Setup: tabs, seed data, dropdowns, colours, trigger
// ---------------------------------------------------------------------------------------------------------------
function setup() {
  if (!PropertiesService.getScriptProperties().getProperty('SECRET')) {
    throw new Error('Add a script property named SECRET (Project Settings > Script properties) and run setup() again.');
  }
  Object.keys(HEADERS).forEach(function (name) { ensureSheet_(name, HEADERS[name]); });
  ensureSheet_(TAB.DASH, []);   // Overview: created empty if missing, never rewritten by the script
  ensureSheet_(TAB.STATE, []);
  seedSettings_();
  seedLibrary_();
  seedPlaybooks_();
  seedExamples_();
  applyUi_();
  installTrigger_();
  // If today's start time has already passed, wait for tomorrow instead of surprising you with a run right now.
  var map = settingsMap_();
  var tz = tz_(map);
  var runAt = normalizeTime_(map.run_time, tz);
  if (runAt && minutesOf_(Utilities.formatDate(NOW_(), tz, 'HH:mm')) >= minutesOf_(runAt)) {
    PropertiesService.getScriptProperties().setProperty('LAST_SCHEDULED_DATE', Utilities.formatDate(NOW_(), tz, 'yyyy-MM-dd'));
  }
  refreshDashboard_();
  return 'Setup complete. Fill in Phones, then Routine. The first automatic run is ' +
         (truthy_(map.enabled) ? 'at ' + runAt + ' (next occurrence).' : 'off until you tick "enabled" in Settings.');
}

function ensureSheet_(name, headers) {
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (!headers.length) return sh;
  if (sh.getLastRow() === 0) {
    sh.appendRow(headers);
  } else {
    var have = sh.getRange(1, 1, 1, Math.max(1, sh.getLastColumn())).getValues()[0].map(function (h) { return String(h).trim(); });
    var missing = headers.filter(function (h) { return have.indexOf(h) < 0; });
    if (missing.length) sh.getRange(1, have.length + 1, 1, missing.length).setValues([missing]);   // upgrade an older layout in place
  }
  sh.setFrozenRows(1);
  sh.getRange(1, 1, 1, sh.getLastColumn()).setFontWeight('bold');
  return sh;
}

function seedSettings_() {
  var sh = sheet_(TAB.SETTINGS);
  var have = {};
  table_(TAB.SETTINGS).rows.forEach(function (r) { have[String(r.setting).trim()] = true; });
  DEFAULT_SETTINGS.forEach(function (d) {
    if (!have[d[0]]) sh.appendRow([d[0], d[1] === 'TRUE' ? true : (d[1] === 'FALSE' ? false : d[1]), d[2]]);
  });
}

// Named lists of steps. One row per step; the playbook name only has to be written on its first row. A step's value and
// duration may be left blank: the Routine row that assigns the playbook then supplies them.
var PLAYBOOK_SEED = [
  ['Watch routine', 'Open YouTube', '', '', 'Replace the link below with your video, or clear it and give the link in the Routine row.'],
  ['', 'Watch YouTube video', 'https://www.youtube.com/watch?v=Bm84BAtOfQw', '60', ''],
  ['', 'Take screenshot', '', '', 'proof for the report'],
  ['', 'Close YouTube', '', '', ''],
  ['Browse routine', 'Check phone is online', '', '', ''],
  ['', 'Browse YouTube Shorts (~2 min)', '', '', 'browse only'],
  ['', 'Take screenshot', '', '', 'proof for the report'],
  ['', 'Press Home', '', '', ''],
  ['', 'Close YouTube', '', '', '']
];

function seedPlaybooks_() {
  var sh = sheet_(TAB.PLAYBOOKS);
  if (sh.getLastRow() >= 2) return;                 // never add rows to a playbook list somebody has already edited
  PLAYBOOK_SEED.forEach(function (row) { sh.appendRow(row); });
}

function seedLibrary_() {
  var sh = sheet_(TAB.LIBRARY);
  var have = {};
  table_(TAB.LIBRARY).rows.forEach(function (r) { have[String(r.name).trim()] = true; });
  LIBRARY_SEED.forEach(function (row) { if (!have[row[0]]) sh.appendRow(row); });
}

function seedExamples_() {
  var phones = sheet_(TAB.PHONES);
  if (phones.getLastRow() < 2) phones.appendRow([false, 'Phone 1', 'cloud', 'PASTE_GEELARK_PROFILE_ID', '']);
  var routine = sheet_(TAB.ROUTINE);
  if (routine.getLastRow() < 2) {
    routine.appendRow([false, 'Phone 1', 'Check phone is online', '', '', 'Example row (switched off). Tick "enabled" once Phones is filled in.']);
  }
}

function installTrigger_() {
  ScriptApp.getProjectTriggers().forEach(function (t) { if (t.getHandlerFunction() === 'tick') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('tick').timeBased().everyMinutes(5).create();
}

// Dropdowns, checkboxes and status colours, applied ONLY where missing. A dropdown that already exists (for example one
// converted to a chip, or customised in the sheet) is left alone, as are existing colour rules and column widths.
function applyUi_() {
  var rule = function () { return SpreadsheetApp.newDataValidation(); };
  var strictList = function (values) { return rule().requireValueInList(values, true).setAllowInvalid(false).build(); };
  var ifMissing = function (range, built) { if (!range.getDataValidation()) range.setDataValidation(built); };

  var routine = sheet_(TAB.ROUTINE), phones = sheet_(TAB.PHONES), lib = sheet_(TAB.LIBRARY), settings = sheet_(TAB.SETTINGS);
  var range = function (sh, col) { return sh.getRange(2, col, MAX_ROWS, 1); };

  ifMissing(range(routine, 1), rule().requireCheckbox().build());
  // Helper lists in the hidden _state tab (the script only ever writes _state!A1:B5): every phone and group name, and every
  // Library task and playbook name. Formulas keep them current as you add phones, groups and playbooks.
  var stateSheet = sheet_(TAB.STATE);
  if (!stateSheet.getRange(1, 4).getFormula()) {
    stateSheet.getRange(1, 4).setFormula('=SORT(UNIQUE(FILTER({Phones!B2:B;Phones!F2:F},{Phones!B2:B;Phones!F2:F}<>"")))');
  }
  if (!stateSheet.getRange(1, 6).getFormula()) {
    stateSheet.getRange(1, 6).setFormula('=SORT(UNIQUE(FILTER({Library!A2:A;Playbooks!A2:A},{Library!A2:A;Playbooks!A2:A}<>"")))');
  }
  ifMissing(range(routine, 2), rule().requireValueInRange(stateSheet.getRange(1, 4, 200, 1), true).setAllowInvalid(true)
    .setHelpText('Pick a phone, or a group name from the Phones tab').build());
  ifMissing(range(routine, 3), rule().requireValueInRange(stateSheet.getRange(1, 6, 300, 1), true).setAllowInvalid(true)
    .setHelpText('Pick a task from the Library tab, or a playbook from the Playbooks tab').build());
  var playbooksSheet = sheet_(TAB.PLAYBOOKS);
  ifMissing(range(playbooksSheet, 2), rule().requireValueInRange(lib.getRange(2, 1, MAX_ROWS, 1), true).setAllowInvalid(false)
    .setHelpText('Pick a task from the Library tab').build());
  ifMissing(range(playbooksSheet, 4), strictList(DURATIONS.map(String)));
  ifMissing(range(routine, 5), strictList(DURATIONS.map(String)));
  ifMissing(range(phones, 1), rule().requireCheckbox().build());
  ifMissing(range(phones, 3), strictList(['cloud', 'local']));
  var tasksSheet = sheet_(TAB.TASKS);
  var batchCol = tasksSheet.getRange(1, 1, 1, Math.max(1, tasksSheet.getLastColumn())).getValues()[0].map(function (h) { return String(h).trim(); }).indexOf('batch');
  if (batchCol >= 0) tasksSheet.getRange(2, batchCol + 1, MAX_ROWS * 4, 1).setNumberFormat('@');
  // GeeLark profile ids are 18-digit numbers; Sheets stores long numbers as floats and would silently change the last digits.
  phones.getRange(2, 4, MAX_ROWS, 1).setNumberFormat('@');
  if (!phones.getRange('E2').getFormula()) {
    phones.getRange('E2').setFormula('=ARRAYFORMULA(IF(B2:B="","",IF(C2:C="local",D2:D,"cloud:"&D2:D)))');
  }
  ifMissing(range(lib, 2), strictList(ALLOWED_ACTIONS));

  // per-setting dropdowns in Settings!B
  var times = [];
  for (var h = 0; h < 24; h++) for (var m = 0; m < 60; m += 15) times.push(('0' + h).slice(-2) + ':' + ('0' + m).slice(-2));
  var lists = {
    run_time: times, on_failure: ['continue', 'stop'], retries: ['0', '1', '2', '3'], max_cloud_phones: ['1', '2', '3', '4', '5', '6', '8', '10'],
    task_timeout_s: ['60', '120', '180', '300', '600', '900'], max_phone_minutes: ['5', '8', '10', '12', '15', '20'],
    daily_phone_minutes: ['30', '60', '120', '200', '300', '500'], max_runtime_min: ['15', '30', '60', '120', '180', '240', '480'],
    task_delay_s: ['0', '2', '5', '10', '30', '60'], keep_days: ['7', '14', '30', '60', '90']
  };
  table_(TAB.SETTINGS).rows.forEach(function (r) {
    var key = String(r.setting).trim();
    var cell = settings.getRange(r._row, 2);
    if (key === 'enabled' || key === 'paused') ifMissing(cell, rule().requireCheckbox().build());
    else if (key === 'timezone') ifMissing(cell, rule().requireValueInList(TIMEZONES, true).setAllowInvalid(true).build());
    else if (lists[key]) ifMissing(cell, rule().requireValueInList(lists[key], true).setAllowInvalid(false).build());
    if (key === 'run_time') cell.setNumberFormat('@');
  });

  // status colours (Tasks col 5, Reports col 6): only on a sheet that has no colour rules yet
  var colours = { success: '#dcfce7', failed: '#fee2e2', error: '#fee2e2', running: '#dbeafe', pending: '#fef3c7',
                  skipped: '#e5e7eb', expired: '#e5e7eb', offline: '#fef3c7', timeout: '#fef3c7', warning: '#fef3c7', info: '#f3f4f6' };
  [[TAB.TASKS, 5], [TAB.REPORTS, 6]].forEach(function (pair) {
    var sh = sheet_(pair[0]);
    if (sh.getConditionalFormatRules().length) return;
    var target = sh.getRange(2, pair[1], 2000, 1);
    sh.setConditionalFormatRules(Object.keys(colours).map(function (text) {
      return SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(text).setBackground(colours[text]).setRanges([target]).build();
    }));
  });
}

// ---------------------------------------------------------------------------------------------------------------
// Menu + read-only inspection
// ---------------------------------------------------------------------------------------------------------------
function onOpen() {
  SpreadsheetApp.getUi().createMenu('GeeLark')
    .addItem('Preview what the routine will queue', 'menuPreview')
    .addItem('Run the routine now (queue a manual batch)', 'menuRunNow')
    .addItem('Refresh overview status', 'menuRefresh')
    .addItem('Install / repair setup', 'setup')
    .addToUi();
}

function menuPreview() {
  var r = enqueue_({ batch: Utilities.formatDate(NOW_(), tz_(settingsMap_()), 'yyyy-MM-dd'), dryRun: true });
  var text = r.plan.length + ' task(s) would be queued.\n' + r.plan.map(function (p) { return '  ' + p.phone + ': ' + p.task + (p.value ? ' [' + p.value + ']' : ''); }).join('\n');
  if (r.problems.length) text += '\n\nProblems:\n  ' + r.problems.join('\n  ');
  SpreadsheetApp.getUi().alert('Routine preview', text, SpreadsheetApp.getUi().ButtonSet.OK);
}

function menuRunNow() {
  var ui = SpreadsheetApp.getUi();
  var ans = ui.alert('Queue a manual batch?', 'This queues today\'s routine again. The runner will start the phones (cloud phones bill per minute) the next time it checks.', ui.ButtonSet.YES_NO);
  if (ans !== ui.Button.YES) return;
  var res = enqueueNow_({ force: true });
  ui.alert(res.ok ? 'Queued ' + res.result.enqueued + ' task(s) as batch ' + res.result.batch : 'Not queued: ' + res.error);
}

function menuRefresh() { refreshDashboard_(); }

// Read-only structure report so the setup can be verified remotely (no secrets or task contents).
function inspect_() {
  var tabs = {};
  Object.keys(TAB).forEach(function (k) {
    var sh = SpreadsheetApp.getActive().getSheetByName(TAB[k]);
    tabs[TAB[k]] = sh ? { rows: Math.max(0, sh.getLastRow() - 1), columns: sh.getLastColumn() } : null;
  });
  var dv = function (tab, a1) {
    var sh = SpreadsheetApp.getActive().getSheetByName(tab);
    var rule = sh ? sh.getRange(a1).getDataValidation() : null;
    return rule ? String(rule.getCriteriaType()) : null;
  };
  var props = PropertiesService.getScriptProperties();
  var map = settingsMap_();
  return { ok: true, tabs: tabs, triggers: ScriptApp.getProjectTriggers().map(function (t) { return t.getHandlerFunction(); }),
    validations: { routine_enabled: dv(TAB.ROUTINE, 'A2'), routine_phone: dv(TAB.ROUTINE, 'B2'), routine_task: dv(TAB.ROUTINE, 'C2'),
                   routine_duration: dv(TAB.ROUTINE, 'E2'), phones_type: dv(TAB.PHONES, 'C2'), library_action: dv(TAB.LIBRARY, 'B2') },
    settings: { enabled: map.enabled, paused: map.paused, run_time: map.run_time, timezone: tz_(map), report_email_set: !!String(map.report_email || '').trim() },
    last_batch: props.getProperty('LAST_BATCH'), last_scheduled_date: props.getProperty('LAST_SCHEDULED_DATE') };
}

// ---------------------------------------------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------------------------------------------
function sheet_(name) {
  var s = SpreadsheetApp.getActive().getSheetByName(name);
  if (!s) throw new Error('Missing tab "' + name + '". Run setup().');
  return s;
}

function table_(name) {
  var sh = sheet_(name);
  var values = sh.getDataRange().getValues();
  var headers = (values[0] || []).map(function (h) { return String(h).trim(); });
  var rows = [];
  for (var r = 1; r < values.length; r++) {
    var o = { _row: r + 1 };
    for (var c = 0; c < headers.length; c++) if (headers[c]) o[headers[c]] = values[r][c];
    rows.push(o);
  }
  return { sheet: sh, headers: headers, rows: rows, values: values };
}

function need_(table, cols) {
  cols.forEach(function (c) {
    if (table.headers.indexOf(c) < 0) throw new Error('A tab is missing column "' + c + '". Run setup() to repair it.');
  });
}

function setCells_(table, row, fields) {
  Object.keys(fields).forEach(function (k) {
    var idx = table.headers.indexOf(k);
    if (idx >= 0) table.sheet.getRange(row._row, idx + 1).setValue(fields[k]);
    row[k] = fields[k];
  });
}

function appendObj_(tab, obj) {
  var sh = sheet_(tab);
  var headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(function (h) { return String(h).trim(); });
  sh.appendRow(headers.map(function (h) { return obj[h] === undefined ? '' : obj[h]; }));
}

function safely_(fn) {
  try { fn(); } catch (err) { /* cosmetic work (dashboard/formatting) must never break the queue */ }
}

function clip_(v) {
  var s = v === undefined || v === null ? '' : String(v);
  return s.length > CELL_LIMIT ? s.slice(0, CELL_LIMIT) + '…' : s;
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
